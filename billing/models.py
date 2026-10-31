"""
Models for Subscript Billing and Invoicing domain.

Core Specifications:
- Strict monetary precision using DecimalField(12, 2)
- UniqueConstraint on (subscription, billing_period_start, billing_period_end)
- Derived overdue logic (never stored) via QuerySet annotations
- Snapshot immutability enforced after confirmation
"""

from decimal import Decimal
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import ExpressionWrapper, F, Q, Sum, Value
from django.db.models.functions import Coalesce
from django.utils import timezone
from . import integrations  # noqa: F401 - Register model stubs if Member 3 models not yet active
from .money import quantize_money


class InvoiceStatus(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    CONFIRMED = "CONFIRMED", "Confirmed"
    PAID = "PAID", "Paid"
    CANCELLED = "CANCELLED", "Cancelled"


class InvoiceQuerySet(models.QuerySet):
    """
    Custom QuerySet for Invoice providing database-level annotations for
    payments, outstanding balance, and overdue state, as well as protecting
    against bulk mutations of confirmed invoices.
    """

    def with_paid_amount(self):
        return self.annotate(
            paid_amount=Coalesce(
                Sum("payments__amount"),
                Value(Decimal("0.00")),
                output_field=models.DecimalField(max_digits=12, decimal_places=2),
            )
        )

    def with_outstanding(self):
        return self.with_paid_amount().annotate(
            outstanding=ExpressionWrapper(
                F("total_amount") - F("paid_amount"),
                output_field=models.DecimalField(max_digits=12, decimal_places=2),
            )
        )

    def overdue(self, as_of=None):
        """
        Overdue is DERIVED, never stored:
        - not CANCELLED
        - due_date < today (or as_of)
        - outstanding > 0
        """
        if as_of is None:
            as_of = timezone.localdate()
        return (
            self.with_outstanding()
            .exclude(status=InvoiceStatus.CANCELLED)
            .filter(
                due_date__lt=as_of,
                outstanding__gt=Decimal("0.00"),
            )
        )

    def update(self, **kwargs):
        financial_fields = {
            "subtotal",
            "discount_amount",
            "tax_amount",
            "total_amount",
            "billing_period_start",
            "billing_period_end",
            "subscription",
            "subscription_id",
        }
        if financial_fields.intersection(kwargs.keys()):
            if self.filter(
                status__in=[
                    InvoiceStatus.CONFIRMED,
                    InvoiceStatus.PAID,
                    InvoiceStatus.CANCELLED,
                ]
            ).exists():
                raise ValidationError(
                    "Bulk update of financial fields on confirmed, paid, or cancelled invoices is strictly forbidden."
                )
        return super().update(**kwargs)

    def delete(self):
        if self.filter(
            status__in=[
                InvoiceStatus.CONFIRMED,
                InvoiceStatus.PAID,
                InvoiceStatus.CANCELLED,
            ]
        ).exists():
            raise ValidationError(
                "Cannot bulk-delete confirmed, paid, or cancelled invoices."
            )
        return super().delete()


class Invoice(models.Model):
    """
    Billing statement for a subscription cycle.
    """

    subscription = models.ForeignKey(
        "subscriptions.Subscription",
        on_delete=models.PROTECT,
        db_constraint=False,
        related_name="invoices",
        help_text="Linked recurring subscription agreement",
    )
    invoice_number = models.CharField(max_length=100, unique=True, db_index=True)
    issue_date = models.DateField(default=timezone.localdate, db_index=True)
    due_date = models.DateField(db_index=True)
    billing_period_start = models.DateField()
    billing_period_end = models.DateField()

    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    discount_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    tax_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))

    status = models.CharField(
        max_length=20,
        choices=InvoiceStatus.choices,
        default=InvoiceStatus.DRAFT,
        db_index=True,
    )
    applied_discount = models.ForeignKey(
        "discounts.Discount",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_constraint=False,
        related_name="invoices",
    )
    paid_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = InvoiceQuerySet.as_manager()

    class Meta:
        db_table = "billing_invoice"
        ordering = ["-issue_date", "-created_at"]
        constraints = [
            # Strict uniqueness: a cancelled period is NOT silently re-billed
            models.UniqueConstraint(
                fields=["subscription", "billing_period_start", "billing_period_end"],
                name="unique_subscription_billing_period",
            ),
            models.CheckConstraint(
                check=models.Q(total_amount__gte=Decimal("0.00")),
                name="invoice_total_amount_gte_0",
            ),
            models.CheckConstraint(
                check=models.Q(subtotal__gte=Decimal("0.00")),
                name="invoice_subtotal_gte_0",
            ),
            models.CheckConstraint(
                check=models.Q(discount_amount__gte=Decimal("0.00")),
                name="invoice_discount_amount_gte_0",
            ),
            models.CheckConstraint(
                check=models.Q(tax_amount__gte=Decimal("0.00")),
                name="invoice_tax_amount_gte_0",
            ),
        ]
        indexes = [
            models.Index(fields=["status"], name="billing_inv_status_idx"),
            models.Index(fields=["due_date"], name="billing_inv_due_date_idx"),
            models.Index(fields=["subscription", "billing_period_start"], name="billing_inv_sub_start_idx"),
            models.Index(fields=["created_at"], name="billing_inv_created_idx"),
        ]

    def __str__(self):
        return f"{self.invoice_number} ({self.status}) - {self.total_amount}"

    def clean(self):
        super().clean()
        if self.subtotal < Decimal("0.00"):
            raise ValidationError({"subtotal": "Subtotal cannot be negative."})
        if self.discount_amount < Decimal("0.00"):
            raise ValidationError({"discount_amount": "Discount amount cannot be negative."})
        if self.tax_amount < Decimal("0.00"):
            raise ValidationError({"tax_amount": "Tax amount cannot be negative."})
        if self.total_amount < Decimal("0.00"):
            raise ValidationError({"total_amount": "Total amount cannot be negative."})

    def save(self, *args, **kwargs):
        # Enforce financial immutability once confirmed
        if self.pk:
            orig = (
                Invoice.objects.filter(pk=self.pk)
                .values(
                    "status",
                    "subtotal",
                    "tax_amount",
                    "discount_amount",
                    "total_amount",
                    "billing_period_start",
                    "billing_period_end",
                    "subscription_id",
                )
                .first()
            )
            if orig and orig["status"] in [
                InvoiceStatus.CONFIRMED,
                InvoiceStatus.PAID,
                InvoiceStatus.CANCELLED,
            ]:
                # Allow status transition and paid_at updates, but protect monetary fields
                if (
                    orig["subtotal"] != self.subtotal
                    or orig["tax_amount"] != self.tax_amount
                    or orig["discount_amount"] != self.discount_amount
                    or orig["total_amount"] != self.total_amount
                    or orig["billing_period_start"] != self.billing_period_start
                    or orig["billing_period_end"] != self.billing_period_end
                    or orig["subscription_id"] != self.subscription_id
                ):
                    raise ValidationError(
                        "Confirmed, Paid, or Cancelled invoice financial totals and periods are immutable."
                    )

        self.full_clean()
        super().save(*args, **kwargs)

    # --------------------------------------------------------------------------
    # Compatibility & Template Properties
    # --------------------------------------------------------------------------
    @property
    def total(self) -> Decimal:
        """Alias for total_amount expected by Member 2 UI templates."""
        return self.total_amount

    @property
    def customer(self):
        """Resolves target customer profile through subscription agreement."""
        return getattr(self.subscription, "customer", None)

    @property
    def paid_amount(self) -> Decimal:
        """Calculates total settled payments against this invoice."""
        if not self.pk:
            return Decimal("0.00")
        total_paid = sum((p.amount for p in self.payments.all()), Decimal("0.00"))
        return quantize_money(total_paid)

    @property
    def outstanding_balance(self) -> Decimal:
        """Calculates current remaining balance due."""
        remaining = self.total_amount - self.paid_amount
        return quantize_money(max(Decimal("0.00"), remaining))

    @property
    def is_overdue(self) -> bool:
        """
        True only if invoice is not CANCELLED/PAID, past due date, and has outstanding balance.
        """
        if self.status in [InvoiceStatus.CANCELLED, InvoiceStatus.PAID]:
            return False
        today = timezone.localdate()
        return self.due_date < today and self.outstanding_balance > Decimal("0.00")


class InvoiceItemQuerySet(models.QuerySet):
    """
    QuerySet defense against bulk updates/deletions of items on confirmed invoices.
    """

    def update(self, **kwargs):
        if self.filter(
            invoice__status__in=[
                InvoiceStatus.CONFIRMED,
                InvoiceStatus.PAID,
                InvoiceStatus.CANCELLED,
            ]
        ).exists():
            raise ValidationError(
                "Cannot bulk-update items on confirmed, paid, or cancelled invoices."
            )
        return super().update(**kwargs)

    def delete(self):
        if self.filter(
            invoice__status__in=[
                InvoiceStatus.CONFIRMED,
                InvoiceStatus.PAID,
                InvoiceStatus.CANCELLED,
            ]
        ).exists():
            raise ValidationError(
                "Cannot bulk-delete items on confirmed, paid, or cancelled invoices."
            )
        return super().delete()


class InvoiceItem(models.Model):
    """
    Snapshot line item billed on an invoice.
    Prices and tax rates are captured at billing time and never read live afterwards.
    """

    invoice = models.ForeignKey(
        Invoice,
        on_delete=models.CASCADE,
        related_name="items",
    )
    product = models.ForeignKey(
        "products.Product",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_constraint=False,
        related_name="invoice_items",
    )
    description = models.CharField(max_length=255)
    quantity = models.PositiveIntegerField(default=1)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    tax_rate = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("0.00"))

    line_subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    line_tax = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    line_total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))

    objects = InvoiceItemQuerySet.as_manager()

    class Meta:
        db_table = "billing_invoiceitem"
        ordering = ["id"]
        constraints = [
            models.CheckConstraint(
                check=models.Q(quantity__gte=1),
                name="invoice_item_quantity_gte_1",
            ),
            models.CheckConstraint(
                check=models.Q(unit_price__gte=Decimal("0.00")),
                name="invoice_item_unit_price_gte_0",
            ),
            models.CheckConstraint(
                check=models.Q(tax_rate__gte=Decimal("0.00")),
                name="invoice_item_tax_rate_gte_0",
            ),
            models.CheckConstraint(
                check=models.Q(line_subtotal__gte=Decimal("0.00")),
                name="invoice_item_line_subtotal_gte_0",
            ),
            models.CheckConstraint(
                check=models.Q(line_tax__gte=Decimal("0.00")),
                name="invoice_item_line_tax_gte_0",
            ),
            models.CheckConstraint(
                check=models.Q(line_total__gte=Decimal("0.00")),
                name="invoice_item_line_total_gte_0",
            ),
        ]

    def __str__(self):
        return f"{self.description} ({self.quantity}x @ {self.unit_price})"

    @property
    def amount(self) -> Decimal:
        """Template alias for line_total."""
        return self.line_total

    def save(self, *args, **kwargs):
        # Enforce item immutability if invoice is confirmed, paid, or cancelled
        if self.invoice_id and self.invoice.status in [
            InvoiceStatus.CONFIRMED,
            InvoiceStatus.PAID,
            InvoiceStatus.CANCELLED,
        ]:
            raise ValidationError(
                "Cannot add or modify items on a confirmed, paid, or cancelled invoice."
            )
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.invoice_id and self.invoice.status in [
            InvoiceStatus.CONFIRMED,
            InvoiceStatus.PAID,
            InvoiceStatus.CANCELLED,
        ]:
            raise ValidationError(
                "Cannot delete items from a confirmed, paid, or cancelled invoice."
            )
        super().delete(*args, **kwargs)
