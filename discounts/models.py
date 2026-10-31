from decimal import Decimal
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone


class DiscountType(models.TextChoices):
    PERCENTAGE = "PERCENTAGE", "Percentage"
    FIXED = "FIXED", "Fixed Amount"


class Discount(models.Model):
    """
    Promotional discounts and coupon rules.
    Specified in docs/DATABASE.md Section 3.D.
    """

    name = models.CharField(max_length=255, blank=True, default="")
    code = models.CharField(max_length=50, unique=True, db_index=True)
    discount_type = models.CharField(
        max_length=20,
        choices=DiscountType.choices,
        default=DiscountType.PERCENTAGE,
    )
    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    usage_limit = models.PositiveIntegerField(null=True, blank=True)
    times_used = models.PositiveIntegerField(default=0)
    usage_count = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Discount"
        verbose_name_plural = "Discounts"
        indexes = [
            models.Index(fields=["code"]),
            models.Index(fields=["discount_type"]),
            models.Index(fields=["is_active"]),
        ]

    def __str__(self):
        label = f"{self.amount}%" if self.discount_type == DiscountType.PERCENTAGE else f"${self.amount}"
        return f"{self.code} ({label} OFF)"

    # --------------------------------------------------------------------------
    # Compatibility properties (aligning docs/DATABASE.md, Member 2 UI & Member 4)
    # --------------------------------------------------------------------------
    @property
    def value(self) -> Decimal:
        return self.amount

    @value.setter
    def value(self, val: Decimal):
        self.amount = val

    @property
    def valid_from(self):
        return self.start_date

    @valid_from.setter
    def valid_from(self, val):
        self.start_date = val

    @property
    def valid_until(self):
        return self.end_date

    @valid_until.setter
    def valid_until(self, val):
        self.end_date = val

    @property
    def max_redemptions(self):
        return self.usage_limit

    @max_redemptions.setter
    def max_redemptions(self, val):
        self.usage_limit = val

    @property
    def times_redeemed(self):
        return self.usage_count

    @times_redeemed.setter
    def times_redeemed(self, val):
        self.usage_count = val
        self.times_used = val

    def clean_fields(self, exclude=None):
        if self.code:
            self.code = self.code.strip().upper()
        if not self.name and self.code:
            self.name = self.code
        super().clean_fields(exclude=exclude)

    def clean(self):
        super().clean()
        if self.code:
            self.code = self.code.strip().upper()
        if not self.name and self.code:
            self.name = self.code

        if self.discount_type == DiscountType.PERCENTAGE:
            if self.amount is not None and (self.amount < Decimal("0.00") or self.amount > Decimal("100.00")):
                raise ValidationError({"amount": "Percentage discount must be between 0 and 100."})
        elif self.discount_type == DiscountType.FIXED:
            if self.amount is not None and self.amount <= Decimal("0.00"):
                raise ValidationError({"amount": "Fixed discount amount must be strictly greater than 0."})

        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValidationError({"end_date": "End date cannot be earlier than start date."})

    def save(self, *args, **kwargs):
        if self.code:
            self.code = self.code.strip().upper()
        if not self.name and self.code:
            self.name = self.code
        if self.usage_count and not self.times_used:
            self.times_used = self.usage_count
        elif self.times_used and not self.usage_count:
            self.usage_count = self.times_used
        self.full_clean()
        super().save(*args, **kwargs)
