"""
Core business services for Billing & Invoicing domain.

Responsibilities:
- Invariant calculations (calculate_invoice_totals)
- QuerySet access scoping & IDOR prevention (scope_invoices_for_user)
- Multi-criteria invoice filtering and search
- Atomic invoice generation, confirmation, and cancellation workflows
"""

from datetime import date, timedelta
from decimal import Decimal
from typing import Optional, Tuple
from django.apps import apps
from django.core.exceptions import ValidationError
from django.db import connection, transaction, IntegrityError
from django.db.models import Q, QuerySet
from django.http import Http404
from django.utils import timezone
from customers.services import scope_queryset_for_user
from .integrations import calculate_next_billing_date, resolve_discount
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


def generate_unique_invoice_number(issue_year: int) -> str:
    """
    Generates a unique invoice number format: INV-<year>-<6-digit sequence>.
    Includes retry logic to handle SQLite concurrent execution safely.
    """
    prefix = f"INV-{issue_year}-"
    last_inv = (
        Invoice.objects.filter(invoice_number__startswith=prefix)
        .order_by("-invoice_number")
        .first()
    )
    seq = 1
    if last_inv:
        try:
            last_seq = int(last_inv.invoice_number.split("-")[-1])
            seq = last_seq + 1
        except (ValueError, IndexError):
            seq = Invoice.objects.filter(invoice_number__startswith=prefix).count() + 1

    for attempt in range(10):
        candidate = f"{prefix}{seq + attempt:06d}"
        if not Invoice.objects.filter(invoice_number=candidate).exists():
            return candidate

    import uuid
    return f"{prefix}{uuid.uuid4().hex[:6].upper()}"


def generate_invoice(
    subscription, as_of: Optional[date] = None
) -> Tuple[Optional[Invoice], str, str]:
    """
    Generates one invoice for one subscription period idempotently.
    Returns: (invoice, status_code, message)
    where status_code in {"created", "skipped_ineligible", "skipped_duplicate", "failed"}
    """
    if as_of is None:
        as_of = timezone.localdate()

    status_str = str(getattr(subscription, "status", "")).upper()
    if status_str != "ACTIVE":
        return None, "skipped_ineligible", f"Subscription status '{status_str}' is not ACTIVE."

    period_start = getattr(subscription, "next_billing_date", None)
    if not period_start or period_start > as_of:
        return None, "skipped_ineligible", f"Next billing date {period_start} is not due as of {as_of}."

    expiry_date = getattr(subscription, "expiry_date", None)
    if expiry_date and period_start > expiry_date:
        return None, "skipped_ineligible", f"Period start {period_start} is after subscription expiry {expiry_date}."

    # Determine billing frequency from attached plan
    plan = getattr(subscription, "plan", None)
    frequency = getattr(plan, "billing_frequency", "MONTHLY")

    next_date = calculate_next_billing_date(period_start, frequency)
    period_end = next_date - timedelta(days=1)

    # Check duplicate period on same subscription
    if Invoice.objects.filter(
        subscription=subscription,
        billing_period_start=period_start,
        billing_period_end=period_end,
    ).exists():
        return None, "skipped_duplicate", f"Period {period_start} to {period_end} is already billed."

    # Parse payment terms (offset in days)
    try:
        terms = int(getattr(subscription, "payment_terms", 15))
        if terms <= 0:
            terms = 15
    except (ValueError, TypeError):
        terms = 15
    due_date = period_start + timedelta(days=terms)

    issue_date = min(period_start, as_of)

    try:
        with transaction.atomic():
            # Savepoint for unique constraint race condition protection
            with transaction.atomic():
                invoice_number = generate_unique_invoice_number(issue_date.year)
                invoice = Invoice(
                    subscription=subscription,
                    invoice_number=invoice_number,
                    issue_date=issue_date,
                    due_date=due_date,
                    billing_period_start=period_start,
                    billing_period_end=period_end,
                    status=InvoiceStatus.DRAFT,
                )
                invoice.save()

            # Pull line items from subscription
            sub_items = list(getattr(subscription, "items", []).all()) if hasattr(subscription, "items") else []
            total_quantity = 0

            if sub_items:
                for sub_item in sub_items:
                    qty = int(getattr(sub_item, "quantity", 1) or 1)
                    uprice = quantize_money(getattr(sub_item, "unit_price", Decimal("0.00")))
                    trate = quantize_money(getattr(sub_item, "tax_rate", Decimal("0.00")))
                    desc = getattr(sub_item, "description", "") or (
                        getattr(getattr(sub_item, "product", None), "name", "") or "Subscription Line Item"
                    )

                    l_subtotal = calculate_line_subtotal(qty, uprice)
                    l_tax = calculate_line_tax(l_subtotal, trate)
                    l_total = calculate_line_total(l_subtotal, l_tax)

                    InvoiceItem.objects.create(
                        invoice=invoice,
                        product=getattr(sub_item, "product", None),
                        description=desc,
                        quantity=qty,
                        unit_price=uprice,
                        tax_rate=trate,
                        line_subtotal=l_subtotal,
                        line_tax=l_tax,
                        line_total=l_total,
                    )
                    total_quantity += qty
            elif plan:
                plan_price = quantize_money(getattr(plan, "price", Decimal("0.00")))
                l_subtotal = plan_price
                l_tax = Decimal("0.00")
                l_total = plan_price

                InvoiceItem.objects.create(
                    invoice=invoice,
                    product=getattr(plan, "product", None),
                    description=getattr(plan, "name", "Recurring Plan License"),
                    quantity=1,
                    unit_price=plan_price,
                    tax_rate=Decimal("0.00"),
                    line_subtotal=l_subtotal,
                    line_tax=l_tax,
                    line_total=l_total,
                )
                total_quantity = 1

            # Compute invoice totals
            subtotal = quantize_money(sum(item.line_subtotal for item in invoice.items.all()))
            tax_amount = quantize_money(sum(item.line_tax for item in invoice.items.all()))

            discount_amount, discount_obj = resolve_discount(
                subscription, subtotal, total_quantity, at_date=period_start
            )
            discount_amount = min(discount_amount, subtotal)
            total_amount = quantize_money(max(Decimal("0.00"), subtotal - discount_amount + tax_amount))

            invoice.subtotal = subtotal
            invoice.tax_amount = tax_amount
            invoice.discount_amount = discount_amount
            invoice.total_amount = total_amount
            invoice.applied_discount = discount_obj
            invoice.save(update_fields=["subtotal", "tax_amount", "discount_amount", "total_amount", "applied_discount", "updated_at"])

            # Advance subscription next_billing_date ONLY after invoice and items are created
            subscription.next_billing_date = next_date
            subscription.save(update_fields=["next_billing_date"])

            return invoice, "created", f"Invoice {invoice.invoice_number} generated successfully."

    except (IntegrityError, ValidationError) as e:
        return None, "skipped_duplicate", f"Period {period_start} to {period_end} duplicate collision: {e}"
    except Exception as e:
        return None, "failed", str(e)


def generate_due_invoices(as_of: Optional[date] = None, dry_run: bool = False) -> dict:
    """
    Loops over eligible subscriptions and generates invoices for due periods.
    Catches up missed periods in chronological order up to a safety cap of 24.
    Runs each subscription in its own transaction so one failure never rolls back the rest.
    """
    if as_of is None:
        as_of = timezone.localdate()

    SubscriptionModel = apps.get_model("subscriptions", "Subscription")

    subscriptions = (
        SubscriptionModel.objects.filter(
            status="ACTIVE",
            next_billing_date__lte=as_of,
        )
        .select_related("plan", "customer")
        .prefetch_related("items")
    )

    summary = {
        "created": 0,
        "skipped_duplicates": 0,
        "skipped_ineligible": 0,
        "failed": 0,
        "errors": [],
        "invoices": [],
    }

    for sub in subscriptions:
        periods_generated = 0
        max_periods = 24

        while (
            sub.status == "ACTIVE"
            and sub.next_billing_date
            and sub.next_billing_date <= as_of
            and periods_generated < max_periods
        ):
            if dry_run:
                summary["created"] += 1
                periods_generated += 1
                freq = getattr(getattr(sub, "plan", None), "billing_frequency", "MONTHLY")
                sub.next_billing_date = calculate_next_billing_date(sub.next_billing_date, freq)
                continue

            inv, code, message = generate_invoice(sub, as_of=as_of)
            if code == "created":
                summary["created"] += 1
                summary["invoices"].append(inv)
                periods_generated += 1
            elif code == "skipped_duplicate":
                summary["skipped_duplicates"] += 1
                break
            elif code == "skipped_ineligible":
                summary["skipped_ineligible"] += 1
                break
            elif code == "failed":
                summary["failed"] += 1
                summary["errors"].append({
                    "subscription": getattr(sub, "subscription_number", str(sub.pk)),
                    "reason": message,
                })
                break

        if periods_generated >= max_periods:
            import logging
            logger = logging.getLogger("billing")
            logger.warning(
                f"Subscription {getattr(sub, 'subscription_number', sub.pk)} reached safety cap of 24 periods."
            )

    return summary
