"""
Models for Subscript Payments domain.

Core Specifications:
- Monetary precision using DecimalField(12, 2)
- Linked to billing.Invoice via PROTECT
- CheckConstraint amount > 0
- Append-only immutability (financial records cannot be modified or deleted)
- Template compatibility properties
"""

from decimal import Decimal
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from billing.money import quantize_money


class PaymentMethod(models.TextChoices):
    BANK_TRANSFER = "BANK_TRANSFER", "Bank Transfer"
    CASH = "CASH", "Cash"
    CARD = "CARD", "Card"
    UPI = "UPI", "UPI"
    OTHER = "OTHER", "Other"


class Payment(models.Model):
    """
    Settled monetary transaction recorded against an invoice.
    All payments are append-only audit records.
    """

    invoice = models.ForeignKey(
        "billing.Invoice",
        on_delete=models.PROTECT,
        related_name="payments",
        help_text="Target invoice for this payment",
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    method = models.CharField(
        max_length=30,
        choices=PaymentMethod.choices,
        default=PaymentMethod.CARD,
        db_index=True,
    )
    payment_date = models.DateField(default=timezone.localdate, db_index=True)
    reference = models.CharField(max_length=150, unique=True, db_index=True)
    notes = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "payments_payment"
        ordering = ["-payment_date", "-created_at"]
        constraints = [
            models.CheckConstraint(
                check=models.Q(amount__gt=Decimal("0.00")),
                name="payment_amount_gt_0",
            ),
        ]
        indexes = [
            models.Index(fields=["payment_date"], name="payments_date_idx"),
            models.Index(fields=["invoice"], name="payments_invoice_idx"),
        ]

    def __str__(self):
        return f"{self.reference} ({self.method}) - ${self.amount}"

    def clean(self):
        super().clean()
        if self.amount is not None and self.amount <= Decimal("0.00"):
            raise ValidationError({"amount": "Payment amount must be strictly greater than zero."})

    def save(self, *args, **kwargs):
        # Enforce append-only immutability
        if self.pk:
            orig = Payment.objects.filter(pk=self.pk).values("amount", "invoice_id", "reference").first()
            if orig and (orig["amount"] != self.amount or orig["invoice_id"] != self.invoice_id or orig["reference"] != self.reference):
                raise ValidationError("Payment financial records are immutable and append-only.")
        self.full_clean()
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError(
            "Payment records cannot be deleted. All transactions are permanent audit records."
        )

    # --------------------------------------------------------------------------
    # Compatibility & Template Properties
    # --------------------------------------------------------------------------
    @property
    def customer(self):
        """Resolves paying customer via invoice."""
        return getattr(self.invoice, "customer", None)

    @property
    def transaction_reference(self) -> str:
        """Alias for reference expected by Member 2 UI templates."""
        return self.reference

    @property
    def payment_method(self) -> str:
        """Alias for method expected by Member 2 UI templates."""
        return self.method

    @property
    def status(self) -> str:
        """All recorded payments in MVP are successfully settled."""
        return "SUCCESS"
