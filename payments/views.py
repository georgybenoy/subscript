"""
Views for Subscript Payments domain.
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render, redirect, get_object_or_404
from accounts.permissions import staff_or_admin_required
from billing.models import Invoice
from .forms import PaymentRecordForm
from .models import Payment
from .services import (
    record_payment,
    scope_payments_for_user,
    get_payment_for_user_or_404,
)


@login_required
def payment_list_view(request: HttpRequest) -> HttpResponse:
    """
    Renders payments directory with search filters and tenant scoping.
    """
    qs = (
        scope_payments_for_user(request.user)
        .select_related("invoice", "invoice__subscription", "invoice__subscription__customer")
        .order_by("-payment_date", "-created_at")
    )

    query = request.GET.get("q")
    method = request.GET.get("method")
    status = request.GET.get("status")

    if query:
        q_str = query.strip()
        qs = qs.filter(
            Q(reference__icontains=q_str)
            | Q(invoice__invoice_number__icontains=q_str)
            | Q(invoice__subscription__customer__name__icontains=q_str)
            | Q(invoice__subscription__customer__email__icontains=q_str)
        )

    if method:
        qs = qs.filter(method=method.strip())

    paginator = Paginator(qs, 25)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    context = {
        "payments": page_obj.object_list,
        "page_obj": page_obj,
        "query": query,
        "method": method,
        "status": status,
    }
    return render(request, "payments/list.html", context)


@login_required
@staff_or_admin_required
def payment_create_view(request: HttpRequest) -> HttpResponse:
    """
    Form view to record incoming payments against confirmed invoices.
    Staff and Admin only.
    """
    if request.method == "POST":
        form = PaymentRecordForm(request.POST)
        if form.is_valid():
            try:
                payment = record_payment(
                    invoice=form.cleaned_data["invoice"],
                    amount=form.cleaned_data["amount"],
                    method=form.cleaned_data["payment_method"],
                    reference=form.cleaned_data.get("transaction_reference") or "",
                    notes=form.cleaned_data.get("notes") or "",
                    recorded_by=request.user,
                )
                messages.success(
                    request,
                    f"Payment of ${payment.amount} recorded successfully (Ref: {payment.reference}).",
                )
                return redirect("billing:invoice_detail", pk=payment.invoice.pk)
            except Exception as e:
                form.add_error(None, str(e.message if hasattr(e, "message") else e))
    else:
        initial = {}
        invoice_id = request.GET.get("invoice")
        if invoice_id:
            try:
                inv = Invoice.objects.get(pk=invoice_id)
                initial["invoice"] = inv
                initial["amount"] = inv.outstanding_balance
                initial["customer"] = inv.customer
            except Invoice.DoesNotExist:
                pass
        form = PaymentRecordForm(initial=initial)

    context = {
        "form": form,
    }
    return render(request, "payments/form.html", context)


@login_required
def payment_detail_view(request: HttpRequest, pk: int) -> HttpResponse:
    """
    Renders individual payment receipt. Protected by tenant scoping.
    """
    payment = get_payment_for_user_or_404(request.user, pk)
    context = {
        "payment": payment,
    }
    return render(request, "payments/detail.html", context)
