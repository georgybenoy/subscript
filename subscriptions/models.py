import uuid
from decimal import Decimal
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class SubscriptionStatus(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    QUOTATION = "QUOTATION", "Quotation"
    CONFIRMED = "CONFIRMED", "Confirmed"
    ACTIVE = "ACTIVE", "Active"
    PAUSED = "PAUSED", "Paused"
    PAST_DUE = "PAST_DUE", "Past Due"
    CANCELLED = "CANCELLED", "Cancelled"
    EXPIRED = "EXPIRED", "Expired"
    CLOSED = "CLOSED", "Closed"


class Subscription(models.Model):
    """
    Recurring subscription contract linking a Customer to a Plan and optional Line Items.
    Specified in docs/DATABASE.md Section 3.E and billing domain contract.
    """

    subscription_number = models.CharField(max_length=100, unique=True, db_index=True, blank=True)
    customer = models.ForeignKey(
        "customers.Customer",
        on_delete=models.PROTECT,
        related_name="subscriptions",
    )
    plan = models.ForeignKey(
        "products.Plan",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="subscriptions",
    )
    discount = models.ForeignKey(
        "discounts.Discount",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="subscriptions",
    )
    status = models.CharField(
        max_length=20,
        choices=SubscriptionStatus.choices,
        default=SubscriptionStatus.DRAFT,
        db_index=True,
    )
    start_date = models.DateField(default=timezone.localdate)
    expiry_date = models.DateField(null=True, blank=True)
    next_billing_date = models.DateField(null=True, blank=True, db_index=True)
    payment_terms = models.PositiveIntegerField(default=15)
    current_period_start = models.DateField(default=timezone.localdate)
    current_period_end = models.DateField(null=True, blank=True)
    cancel_at_period_end = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Subscription"
        verbose_name_plural = "Subscriptions"
        indexes = [
            models.Index(fields=["subscription_number"]),
            models.Index(fields=["status"]),
            models.Index(fields=["next_billing_date"]),
            models.Index(fields=["customer", "status"]),
        ]

    def __str__(self):
        return f"{self.subscription_number or f'SUB-{self.pk}'} - {self.customer.name}"

    def clean(self):
        super().clean()
        if not self.subscription_number:
            self.subscription_number = f"SUB-{uuid.uuid4().hex[:8].upper()}"

        if self.start_date and not self.current_period_start:
            self.current_period_start = self.start_date
        if self.expiry_date and not self.current_period_end:
            self.current_period_end = self.expiry_date

        if self.start_date and self.expiry_date and self.expiry_date < self.start_date:
            raise ValidationError({"expiry_date": "Expiry date cannot be earlier than start date."})

    def save(self, *args, **kwargs):
        if not self.subscription_number:
            self.subscription_number = f"SUB-{uuid.uuid4().hex[:8].upper()}"
        if self.start_date and not self.current_period_start:
            self.current_period_start = self.start_date
        if self.expiry_date and not self.current_period_end:
            self.current_period_end = self.expiry_date
        if self.status == SubscriptionStatus.ACTIVE and not self.next_billing_date:
            self.next_billing_date = self.current_period_start
        super().save(*args, **kwargs)

    @property
    def total_recurring_amount(self) -> Decimal:
        """Returns recurring sum of subscription line items or base plan price."""
        items = self.items.all()
        if items.exists():
            return sum((item.subtotal for item in items), Decimal("0.00"))
        if self.plan:
            return self.plan.base_price
        return Decimal("0.00")


class SubscriptionItem(models.Model):
    """
    Individual line items or tier add-ons belonging to an agreement.
    Specified in docs/DATABASE.md Section 3.E.
    """

    subscription = models.ForeignKey(
        Subscription,
        on_delete=models.CASCADE,
        related_name="items",
    )
    product = models.ForeignKey(
        "products.Product",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="subscription_items",
    )
    variant = models.ForeignKey(
        "products.ProductVariant",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="subscription_items",
    )
    description = models.CharField(max_length=255, blank=True, default="")
    quantity = models.PositiveIntegerField(default=1)
    unit_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    tax_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["id"]
        verbose_name = "Subscription Line Item"
        verbose_name_plural = "Subscription Line Items"

    def __str__(self):
        desc = self.description or (self.product.name if self.product else "Line Item")
        return f"{desc} ({self.quantity}x @ ${self.unit_price})"

    @property
    def subtotal(self) -> Decimal:
        return (self.unit_price * self.quantity).quantize(Decimal("0.01"))

    def clean(self):
        super().clean()
        if self.variant and not self.product:
            self.product = self.variant.product

        if not self.description:
            if self.variant:
                self.description = f"{self.variant.product.name} - {self.variant.name}"
            elif self.product:
                self.description = self.product.name

        if self.subscription and self.subscription.plan:
            min_qty = getattr(self.subscription.plan, "minimum_quantity", 1)
            if self.quantity < min_qty:
                raise ValidationError({"quantity": f"Quantity must be at least minimum plan quantity ({min_qty})."})

    def save(self, *args, **kwargs):
        if self.variant and not self.product:
            self.product = self.variant.product
        if not self.description:
            if self.variant:
                self.description = f"{self.variant.product.name} - {self.variant.name}"
            elif self.product:
                self.description = self.product.name
        if not self.unit_price or self.unit_price == Decimal("0.00"):
            if self.variant:
                self.unit_price = self.variant.effective_price
            elif self.product:
                self.unit_price = self.product.sales_price
            elif self.subscription and self.subscription.plan:
                self.unit_price = self.subscription.plan.base_price
        super().save(*args, **kwargs)
