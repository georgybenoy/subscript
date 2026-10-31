"""
Payment processing services for Subscript Payments domain.

Responsibilities:
- Atomic payment recording against confirmed invoices
- Strict overpayment, zero/negative, future date, and status validations
- Invoice settlement and status reconciliation
"""

from datetime import date
from decimal import Decimal
from typing import Optional
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum, Value, Q, QuerySet
from django.db.models.functions import Coalesce
from django.http import Http404
from django.utils import timezone
from customers.services import scope_queryset_for_user
from billing.models import Invoice, InvoiceStatus
from billing.money import quantize_money
from .models import Payment, PaymentMethod


def get_invoice_paid_amount(invoice: Invoice) -> Decimal:
    """
    Computes total verified settled payments against an invoice.
    """
    total = Payment.objects.filter(invoice=invoice).aggregate(
        total=Coalesce(Sum("amount"), Value(Decimal("0.00")))
    )["total"]
    return quantize_money(total)


def get_invoice_outstanding_balance(invoice: Invoice) -> Decimal:
    """
    Computes remaining balance on an invoice.
    """
    paid = get_invoice_paid_amount(invoice)
    remaining = invoice.total_amount - paid
    return quantize_money(max(Decimal("0.00"), remaining))


def record_payment(
    invoice: Invoice,
    amount: Decimal,
    method: str = PaymentMethod.CARD,
    payment_date: Optional[date] = None,
    reference: str = "",
    notes: str = "",
    recorded_by=None,
) -> Payment:
    """
    Records a payment against an invoice inside an atomic transaction.
    Re-reads invoice and payment totals inside the transaction to prevent race conditions.
    """
    if isinstance(amount, float):
        raise TypeError("Float values are forbidden. Use Decimal.")
    amount = quantize_money(amount)

    if amount <= Decimal("0.00"):
        raise ValidationError("Payment amount must be greater than zero.")

    if payment_date is None:
        payment_date = timezone.localdate()
    elif payment_date > timezone.localdate():
        raise ValidationError("Payment date cannot be in the future.")

    with transaction.atomic():
        # Re-read invoice inside transaction
        inv = Invoice.objects.select_for_update().get(pk=invoice.pk)

        # Status validation with distinct error messages
        if inv.status == InvoiceStatus.DRAFT:
            raise ValidationError("Cannot record payment for a DRAFT invoice. Invoice must be CONFIRMED.")
        elif inv.status == InvoiceStatus.CANCELLED:
            raise ValidationError("Cannot record payment for a CANCELLED invoice.")
        elif inv.status == InvoiceStatus.PAID:
            raise ValidationError("Cannot record payment for an already PAID invoice.")
        elif inv.status != InvoiceStatus.CONFIRMED:
            raise ValidationError(f"Payments can only be recorded on CONFIRMED invoices (current: {inv.status}).")

        # Re-read outstanding balance inside lock
        current_paid = get_invoice_paid_amount(inv)
        outstanding = quantize_money(inv.total_amount - current_paid)

        if amount > outstanding:
            raise ValidationError(
                f"Payment amount (${amount}) exceeds outstanding invoice balance (${outstanding}). Overpayment is rejected."
            )

        if not reference:
            import uuid
            reference = f"TXN-{payment_date.year}-{uuid.uuid4().hex[:8].upper()}"

        payment = Payment.objects.create(
            invoice=inv,
            amount=amount,
            method=method,
            payment_date=payment_date,
            reference=reference,
            notes=notes or "",
        )

        # Check if invoice is now fully settled
        new_paid = current_paid + amount
        if new_paid >= inv.total_amount:
            inv.status = InvoiceStatus.PAID
            inv.paid_at = timezone.now()
            inv.save(update_fields=["status", "paid_at", "updated_at"])

        return payment


def reconcile_invoice(invoice: Invoice) -> dict:
    """
    Verifies that invoice status matches payment records.
    Sets status to PAID if outstanding == 0.
    """
    with transaction.atomic():
        inv = Invoice.objects.select_for_update().get(pk=invoice.pk)
        paid_sum = get_invoice_paid_amount(inv)
        outstanding = quantize_money(max(Decimal("0.00"), inv.total_amount - paid_sum))

        discrepancies = []
        is_reconciled = True

        if outstanding == Decimal("0.00") and inv.total_amount > Decimal("0.00"):
            if inv.status != InvoiceStatus.PAID:
                discrepancies.append(f"Status was '{inv.status}', expected 'PAID'")
                inv.status = InvoiceStatus.PAID
                if not inv.paid_at:
                    inv.paid_at = timezone.now()
                inv.save(update_fields=["status", "paid_at", "updated_at"])
                is_reconciled = False
        elif outstanding > Decimal("0.00"):
            if inv.status == InvoiceStatus.PAID:
                discrepancies.append("Status was 'PAID', but invoice has outstanding balance")
                inv.status = InvoiceStatus.CONFIRMED
                inv.paid_at = None
                inv.save(update_fields=["status", "paid_at", "updated_at"])
                is_reconciled = False

        return {
            "invoice_id": inv.id,
            "invoice_number": inv.invoice_number,
            "total_amount": inv.total_amount,
            "paid_amount": paid_sum,
            "outstanding": outstanding,
            "stored_status": inv.status,
            "reconciled": is_reconciled,
            "discrepancies": discrepancies,
        }


def scope_payments_for_user(user, qs: Optional[QuerySet[Payment]] = None) -> QuerySet[Payment]:
    """
    Scopes Payment QuerySet strictly to current user's role:
    - Admin & Staff: see all payments
    - Customer: see only payments for own invoices
    """
    if qs is None:
        qs = Payment.objects.all()

    return scope_queryset_for_user(qs, user, customer_lookup="invoice__subscription__customer__user")


def get_payment_for_user_or_404(user, pk: int) -> Payment:
    """
    Tenant-scoped payment retrieval preventing IDOR.
    """
    qs = scope_payments_for_user(user).select_related(
        "invoice",
        "invoice__subscription",
        "invoice__subscription__customer",
    )
    try:
        return qs.get(pk=pk)
    except Payment.DoesNotExist:
        raise Http404("Payment not found or access denied.")
