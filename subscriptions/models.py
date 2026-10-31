import calendar
from datetime import timedelta
from decimal import Decimal
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models


class Subscription(models.Model):
    """
    Recurring agreement linking a Customer to a Plan.
    Specified in docs/DATABASE.md Section 3.E with approved paused_at field.
    """

    class Status(models.TextChoices):
        TRIALING = "TRIALING", "Trialing"
        ACTIVE = "ACTIVE", "Active"
        PAST_DUE = "PAST_DUE", "Past Due"
        CANCELED = "CANCELED", "Canceled"
        PAUSED = "PAUSED", "Paused"

    customer = models.ForeignKey(
        "customers.Customer",
        on_delete=models.PROTECT,
        related_name="subscriptions",
    )
    plan = models.ForeignKey(
        "products.Plan",
        on_delete=models.PROTECT,
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
        choices=Status.choices,
        default=Status.ACTIVE,
    )
    current_period_start = models.DateTimeField()
    current_period_end = models.DateTimeField()
    cancel_at_period_end = models.BooleanField(default=False)
    paused_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Subscription"
        verbose_name_plural = "Subscriptions"
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["current_period_start", "current_period_end"]),
            models.Index(fields=["customer", "status"]),
        ]

    def __str__(self):
        return f"{self.customer} - {self.plan.name} ({self.get_status_display()})"

    def clean(self):
        super().clean()
        if (
            self.current_period_start
            and self.current_period_end
            and self.current_period_end <= self.current_period_start
        ):
            raise ValidationError(
                {"current_period_end": "current_period_end must be after current_period_start."}
            )

    def get_subtotal(self) -> Decimal:
        """
        Calculates the pre-discount recurring subtotal:
        plan.price + sum(item.unit_price * item.quantity).
        """
        base_price = getattr(self.plan, "price", Decimal("0.00"))
        # If prefetched or queryable, sum up items
        items_total = sum(
            (item.unit_price * item.quantity for item in self.items.all()),
            Decimal("0.00"),
        )
        return (base_price + items_total).quantize(Decimal("0.01"))

    def get_discount_amount(self) -> Decimal:
        """
        Calculates applicable monetary discount using the Phase 2 discount engine.
        Returns Decimal('0.00') if no discount attached or discount is not eligible.
        """
        if not self.discount:
            return Decimal("0.00")

        from discounts import services as discount_services

        return discount_services.get_applicable_discount(
            subscription=self,
            subtotal=self.get_subtotal(),
        )

    def get_total(self) -> Decimal:
        """
        Calculates final total after discount (floored at 0.00).
        """
        subtotal = self.get_subtotal()
        discount = self.get_discount_amount()
        return max(Decimal("0.00"), subtotal - discount).quantize(Decimal("0.01"))


class SubscriptionItem(models.Model):
    """
    Line items or add-ons attached to an active subscription.
    Specified in docs/DATABASE.md Section 3.E.
    """

    subscription = models.ForeignKey(
        "subscriptions.Subscription",
        on_delete=models.CASCADE,
        related_name="items",
    )
    variant = models.ForeignKey(
        "products.ProductVariant",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="subscription_items",
    )
    quantity = models.PositiveIntegerField(
        default=1,
        validators=[MinValueValidator(1)],
    )
    unit_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.00"))],
    )

    class Meta:
        ordering = ["id"]
        verbose_name = "Subscription Item"
        verbose_name_plural = "Subscription Items"
        indexes = [
            models.Index(fields=["subscription"]),
        ]

    def __str__(self):
        name = self.variant.name if self.variant else "Custom Add-on"
        return f"{self.subscription.id} - {name} x{self.quantity}"

    def get_amount(self) -> Decimal:
        """Calculates line item monetary amount: quantity * unit_price."""
        return (self.unit_price * self.quantity).quantize(Decimal("0.01"))
