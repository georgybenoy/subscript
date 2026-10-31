from decimal import Decimal
from django.core.validators import MinValueValidator
from django.db import models


class Product(models.Model):
    """
    Core service or SaaS product offering.
    Specified in docs/DATABASE.md Section 3.C.
    """

    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Product"
        verbose_name_plural = "Products"
        indexes = [
            models.Index(fields=["name"]),
            models.Index(fields=["is_active"]),
        ]

    def __str__(self):
        return self.name


class ProductVariant(models.Model):
    """
    Specific tier or add-on SKU belonging to a product.
    Specified in docs/DATABASE.md Section 3.C.
    """

    product = models.ForeignKey(
        "products.Product",
        on_delete=models.CASCADE,
        related_name="variants",
    )
    name = models.CharField(max_length=255)
    sku = models.CharField(max_length=100, unique=True)
    price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Product Variant"
        verbose_name_plural = "Product Variants"
        indexes = [
            models.Index(fields=["sku"]),
            models.Index(fields=["is_active"]),
        ]

    def __str__(self):
        return f"{self.product.name} - {self.name} ({self.sku})"

    def clean_fields(self, exclude=None):
        if self.sku:
            self.sku = self.sku.strip().upper()
        super().clean_fields(exclude=exclude)

    def clean(self):
        super().clean()
        if self.sku:
            self.sku = self.sku.strip().upper()

    def save(self, *args, **kwargs):
        if self.sku:
            self.sku = self.sku.strip().upper()
        super().save(*args, **kwargs)


class Plan(models.Model):
    """
    Recurring subscription pricing model for a product.
    Specified in docs/DATABASE.md Section 3.C.
    """

    class BillingInterval(models.TextChoices):
        WEEKLY = "WEEKLY", "Weekly"
        MONTHLY = "MONTHLY", "Monthly"
        QUARTERLY = "QUARTERLY", "Quarterly"
        YEARLY = "YEARLY", "Yearly"

    product = models.ForeignKey(
        "products.Product",
        on_delete=models.CASCADE,
        related_name="plans",
    )
    name = models.CharField(max_length=255)
    code = models.CharField(max_length=100, unique=True)
    billing_interval = models.CharField(
        max_length=20,
        choices=BillingInterval.choices,
        default=BillingInterval.MONTHLY,
    )
    price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    currency = models.CharField(max_length=3, default="INR")
    trial_days = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Plan"
        verbose_name_plural = "Plans"
        indexes = [
            models.Index(fields=["code"]),
            models.Index(fields=["billing_interval"]),
            models.Index(fields=["is_active"]),
        ]

    def __str__(self):
        return f"{self.product.name} - {self.name} ({self.code})"

    def clean_fields(self, exclude=None):
        if self.code:
            self.code = self.code.strip().upper()
        if self.currency:
            self.currency = self.currency.strip().upper()
        super().clean_fields(exclude=exclude)

    def clean(self):
        super().clean()
        if self.code:
            self.code = self.code.strip().upper()
        if self.currency:
            self.currency = self.currency.strip().upper()

    def save(self, *args, **kwargs):
        if self.code:
            self.code = self.code.strip().upper()
        if self.currency:
            self.currency = self.currency.strip().upper()
        super().save(*args, **kwargs)
