"""
Views for Billing & Invoicing domain.

Handles:
- List view with pagination, search, status filters, and IDOR protection
- Detail view with line items and payment reconciliation
- Confirm and Cancel actions (POST-only)
- ReportLab PDF export
"""

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import HttpRequest, HttpResponse, HttpResponseNotAllowed
from django.shortcuts import render, redirect
from django.views.decorators.http import require_POST
from .models import Invoice
from .services import (
    scope_invoices_for_user,
    get_invoice_for_user_or_404,
    filter_invoices,
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
