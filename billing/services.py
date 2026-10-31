"""
Core business services for Billing & Invoicing domain.

Responsibilities:
- Invariant calculations (calculate_invoice_totals)
- QuerySet access scoping & IDOR prevention (scope_invoices_for_user)
- Multi-criteria invoice filtering and search
- Atomic invoice generation, confirmation, and cancellation workflows
"""

from datetime import date
from decimal import Decimal
from typing import Optional
from django.db import transaction
from django.db.models import Q, QuerySet
from django.http import Http404
from django.utils import timezone
from customers.services import scope_queryset_for_user
from .models import Invoice, InvoiceItem, InvoiceStatus
from .money import (
    quantize_money,
    calculate_line_subtotal,
    calculate_line_tax,
    calculate_line_total,
)


def calculate_invoice_totals(invoice: Invoice) -> Invoice:
    """
    Computes all line amounts and invoice-level totals using per-line ROUND_HALF_UP arithmetic.
    Ensures:
    - line_subtotal = quantity x unit_price
    - line_tax = line_subtotal x tax_rate / 100
    - line_total = line_subtotal + line_tax
    - invoice subtotal = sum of line_subtotals
    - invoice tax_amount = sum of line_taxes
    - discount_amount capped at subtotal
    - total_amount = max(0, subtotal - discount_amount + tax_amount)
    """
    items = list(invoice.items.all())

    running_subtotal = Decimal("0.00")
    running_tax = Decimal("0.00")

    for item in items:
        # Re-quantize line values
        item.line_subtotal = calculate_line_subtotal(item.quantity, item.unit_price)
        item.line_tax = calculate_line_tax(item.line_subtotal, item.tax_rate)
        item.line_total = calculate_line_total(item.line_subtotal, item.line_tax)

        if invoice.status == InvoiceStatus.DRAFT:
            item.save(update_fields=["line_subtotal", "line_tax", "line_total"])

        running_subtotal += item.line_subtotal
        running_tax += item.line_tax

    invoice.subtotal = quantize_money(running_subtotal)
    invoice.tax_amount = quantize_money(running_tax)

    # Discount cannot exceed subtotal
    current_discount = quantize_money(invoice.discount_amount or Decimal("0.00"))
    invoice.discount_amount = min(current_discount, invoice.subtotal)

    net_total = invoice.subtotal - invoice.discount_amount + invoice.tax_amount
    invoice.total_amount = quantize_money(max(Decimal("0.00"), net_total))

    invoice.save(update_fields=["subtotal", "tax_amount", "discount_amount", "total_amount", "updated_at"])
    return invoice


def scope_invoices_for_user(user, qs: Optional[QuerySet[Invoice]] = None) -> QuerySet[Invoice]:
    """
    Scopes Invoice QuerySet strictly to the current user's role:
    - Admin & Staff: full access to all invoices.
    - Customer role: restricted to invoices attached to customer profile.
    - Inactive / unauthenticated: empty QuerySet.
    """
    if qs is None:
        qs = Invoice.objects.all()

    return scope_queryset_for_user(qs, user, customer_lookup="subscription__customer__user")


def get_invoice_for_user_or_404(user, pk: int) -> Invoice:
    """
    Object-level access controller preventing Insecure Direct Object Reference (IDOR).
    Raises Http404 (never 403) to prevent leaking invoice existence across tenants.
    """
    qs = (
        scope_invoices_for_user(user)
        .select_related("subscription", "subscription__customer", "subscription__plan")
        .prefetch_related("items", "payments")
    )
    try:
        return qs.get(pk=pk)
    except Invoice.DoesNotExist:
        raise Http404("Invoice not found or access denied.")


def filter_invoices(
    qs: QuerySet[Invoice],
    query: Optional[str] = None,
    status: Optional[str] = None,
    due_date: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> QuerySet[Invoice]:
    """
    Applies multi-criteria search, status filters, and date range constraints.
    """
    if query:
        q_str = query.strip()
        qs = qs.filter(
            Q(invoice_number__icontains=q_str)
            | Q(subscription__customer__name__icontains=q_str)
            | Q(subscription__customer__company_name__icontains=q_str)
            | Q(subscription__customer__email__icontains=q_str)
        )

    if status:
        stat = status.strip().upper()
        if stat == "OVERDUE":
            qs = qs.overdue()
        elif stat in ["OPEN", "CONFIRMED"]:
            qs = qs.filter(status=InvoiceStatus.CONFIRMED)
        elif stat in ["VOID", "CANCELLED"]:
            qs = qs.filter(status=InvoiceStatus.CANCELLED)
        elif stat in InvoiceStatus.values:
            qs = qs.filter(status=stat)

    if due_date:
        try:
            qs = qs.filter(due_date=due_date.strip())
        except Exception:
            pass

    if start_date:
        try:
            qs = qs.filter(issue_date__gte=start_date.strip())
        except Exception:
            pass

    if end_date:
        try:
            qs = qs.filter(issue_date__lte=end_date.strip())
        except Exception:
            pass

    return qs.order_by("-issue_date", "-created_at")
