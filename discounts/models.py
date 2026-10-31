from datetime import date, datetime, timedelta
from decimal import Decimal
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone


class Discount(models.Model):
    """
    Coupons and promotional discounts.
    Specified in docs/DATABASE.md Section 3.D.
    """

    class DiscountType(models.TextChoices):
        PERCENTAGE = "PERCENTAGE", "Percentage"
        FIXED = "FIXED", "Fixed Amount"

    code = models.CharField(max_length=50, unique=True, db_index=True)
    discount_type = models.CharField(
        max_length=20,
        choices=DiscountType.choices,
        default=DiscountType.PERCENTAGE,
    )
    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    valid_from = models.DateTimeField(default=timezone.now)
    valid_until = models.DateTimeField(null=True, blank=True)
    max_redemptions = models.PositiveIntegerField(null=True, blank=True)
    times_redeemed = models.PositiveIntegerField(default=0)
    usage_count = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Discount"
        verbose_name_plural = "Discounts"
        indexes = [
            models.Index(fields=["is_active"]),
            models.Index(fields=["valid_from", "valid_until"]),
        ]

    def __str__(self):
        return f"{self.code} ({self.get_discount_type_display()} - {self.amount})"

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
    def name(self) -> str:
        return self.code

    @name.setter
    def name(self, val: str):
        if not self.code and val:
            self.code = val

    @property
    def start_date(self):
        if self.valid_from is None:
            return None
        return self.valid_from.date() if isinstance(self.valid_from, datetime) else self.valid_from

    @start_date.setter
    def start_date(self, val):
        if val is None:
            self.valid_from = None
        elif isinstance(val, datetime):
            self.valid_from = val
        elif isinstance(val, date):
            self.valid_from = timezone.make_aware(datetime.combine(val, datetime.min.time()))
        else:
            self.valid_from = val

    @property
    def end_date(self):
        if self.valid_until is None:
            return None
        return self.valid_until.date() if isinstance(self.valid_until, datetime) else self.valid_until

    @end_date.setter
    def end_date(self, val):
        if val is None:
            self.valid_until = None
        elif isinstance(val, datetime):
            self.valid_until = val
        elif isinstance(val, date):
            self.valid_until = timezone.make_aware(datetime.combine(val, datetime.max.time().replace(microsecond=0)))
        else:
            self.valid_until = val

    @property
    def usage_limit(self):
        return self.max_redemptions

    @usage_limit.setter
    def usage_limit(self, val):
        self.max_redemptions = val

    @property
    def times_used(self) -> int:
        return max(self.times_redeemed, self.usage_count)

    @times_used.setter
    def times_used(self, val: int):
        self.times_redeemed = val
        self.usage_count = val

    def clean_fields(self, exclude=None):
        if self.code:
            self.code = self.code.strip().upper()
        if self.valid_from is None:
            self.valid_from = timezone.now()
        super().clean_fields(exclude=exclude)

    def clean(self):
        super().clean()
        if self.code:
            self.code = self.code.strip().upper()

        if self.valid_from is None:
            self.valid_from = timezone.now()

        if self.discount_type == self.DiscountType.PERCENTAGE:
            if self.amount is not None:
                if self.amount < Decimal("0.00"):
                    raise ValidationError({"amount": "Percentage discount must be between 0 and 100."})
                if self.amount > Decimal("100.00"):
                    raise ValidationError({"amount": "Percentage discount cannot exceed 100.00%."})
        elif self.discount_type == self.DiscountType.FIXED:
            if self.amount is not None and self.amount <= Decimal("0.00"):
                raise ValidationError({"amount": "Fixed discount amount must be strictly greater than 0."})

        if self.valid_from and self.valid_until and self.valid_until < self.valid_from:
            raise ValidationError({"valid_until": "valid_until cannot be earlier than valid_from."})

    def save(self, *args, **kwargs):
        if self.code:
            self.code = self.code.strip().upper()
        if self.valid_from is None:
            self.valid_from = timezone.now()
        if self.usage_count and not self.times_redeemed:
            self.times_redeemed = self.usage_count
        elif self.times_redeemed and not self.usage_count:
            self.usage_count = self.times_redeemed
        super().save(*args, **kwargs)


# Module-level alias for backwards compatibility
DiscountType = Discount.DiscountType
