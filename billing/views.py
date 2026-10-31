"""
Views for Billing & Invoicing domain.

Handles:
- List view with pagination, search, status filters, and IDOR protection
- Detail view with line items and payment reconciliation
- Confirm and Cancel actions (POST-only)
- ReportLab PDF export
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.http import HttpRequest, HttpResponse, HttpResponseBadRequest, HttpResponseNotAllowed
from django.shortcuts import render, redirect
from django.views.decorators.http import require_POST
from accounts.permissions import staff_or_admin_required
from .models import Invoice, InvoiceStatus
from .services import (
    scope_invoices_for_user,
    get_invoice_for_user_or_404,
    filter_invoices,
    confirm_invoice,
    cancel_invoice,
)


@login_required
def invoice_list_view(request: HttpRequest) -> HttpResponse:
    """
    Renders invoice directory with multi-criteria search, status tabs, and pagination.
    Protected by backend tenant scoping.
    """
    base_qs = (
        scope_invoices_for_user(request.user)
        .select_related("subscription", "subscription__customer")
        .prefetch_related("payments")
        .with_paid_amount()
        .with_outstanding()
    )

    query = request.GET.get("q")
    status = request.GET.get("status")
    due_date = request.GET.get("due_date")
    start_date = request.GET.get("start_date")
    end_date = request.GET.get("end_date")

    filtered_qs = filter_invoices(
        base_qs,
        query=query,
        status=status,
        due_date=due_date,
        start_date=start_date,
        end_date=end_date,
    )

    paginator = Paginator(filtered_qs, 25)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    context = {
        "invoices": page_obj.object_list,
        "page_obj": page_obj,
        "query": query,
        "status": status,
        "due_date": due_date,
    }
    return render(request, "invoices/list.html", context)


@login_required
def invoice_detail_view(request: HttpRequest, pk: int) -> HttpResponse:
    """
    Renders invoice detail with line items, tax breakdown, and payment history.
    """
    invoice = get_invoice_for_user_or_404(request.user, pk)
    context = {
        "invoice": invoice,
    }
    return render(request, "invoices/detail.html", context)


@login_required
@staff_or_admin_required
@require_POST
def confirm_invoice_view(request: HttpRequest, pk: int) -> HttpResponse:
    """
    Transitions invoice from DRAFT to CONFIRMED and commits discount usage.
    POST-only, Admin/Staff only.
    """
    invoice = get_invoice_for_user_or_404(request.user, pk)
    try:
        confirm_invoice(invoice)
        messages.success(request, f"Invoice {invoice.invoice_number} successfully confirmed.")
    except ValidationError as e:
        messages.error(request, str(e.message if hasattr(e, "message") else e))
    return redirect("billing:invoice_detail", pk=pk)


@login_required
@staff_or_admin_required
@require_POST
def cancel_invoice_view(request: HttpRequest, pk: int) -> HttpResponse:
    """
    Cancels an invoice with zero payments.
    POST-only, Admin/Staff only.
    """
    invoice = get_invoice_for_user_or_404(request.user, pk)
    try:
        cancel_invoice(invoice)
        messages.success(request, f"Invoice {invoice.invoice_number} successfully cancelled.")
    except ValidationError as e:
        messages.error(request, str(e.message if hasattr(e, "message") else e))
    return redirect("billing:invoice_detail", pk=pk)


@login_required
def invoice_pdf_view(request: HttpRequest, pk: int) -> HttpResponse:
    """
    Renders and streams PDF invoice statement.
    Protected by tenant scoping (customers only access their own, staff/admin access all).
    Only permitted for CONFIRMED or PAID invoices.
    Refuses DRAFT and CANCELLED with clear error (HttpResponseBadRequest).
    """
    invoice = get_invoice_for_user_or_404(request.user, pk)
    if invoice.status in [InvoiceStatus.DRAFT, InvoiceStatus.CANCELLED]:
        return HttpResponseBadRequest(
            f"PDF statement generation is not allowed for {invoice.status} invoices. "
            "Only CONFIRMED and PAID invoices may be downloaded."
        )

    try:
        from .pdf import generate_invoice_pdf
        pdf_bytes = generate_invoice_pdf(invoice)
    except ValidationError as e:
        return HttpResponseBadRequest(str(e.message if hasattr(e, "message") else e))

    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    filename = f"Invoice-{invoice.invoice_number}.pdf"
    response["Content-Disposition"] = f'inline; filename="{filename}"'
    return response
