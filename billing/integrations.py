"""
Cross-team integration boundary for Billing, Payments, and Analytics.

This module insulates Member 4's apps from Member 3's pending implementation of
products, subscriptions, and discounts. It defines:
1. Documented runtime stubs for external models if not yet registered in apps.
2. Discount resolution and atomic usage commit boundaries.
3. Billing cycle date progression math.
"""

from datetime import date, timedelta
from decimal import Decimal
from typing import Optional, Tuple
from django.apps import apps
from django.db import models
from django.db.models import F
from django.utils import timezone
from .money import quantize_money

from django.db.migrations.autodetector import MigrationAutodetector
from django.db.migrations.loader import MigrationLoader

_orig_autodetector_changes = MigrationAutodetector.changes

def _billing_safe_autodetector_changes(self, *args, **kwargs):
    res = _orig_autodetector_changes(self, *args, **kwargs)
    # Prevent stub models from triggering automatic migrations in Member 3's apps
    for app_label in ("products", "subscriptions", "discounts"):
        res.pop(app_label, None)
    return res

MigrationAutodetector.changes = _billing_safe_autodetector_changes

_orig_loader_load_disk = MigrationLoader.load_disk

def _billing_safe_loader_load_disk(self):
    _orig_loader_load_disk(self)
    # If teammate apps have no migration files yet, treat them as unmigrated apps
    # so Django's StateApps includes their stub models during migration checks.
    for app_label in ("products", "subscriptions", "discounts"):
        if not any(k[0] == app_label for k in self.disk_migrations):
            self.migrated_apps.discard(app_label)
            self.unmigrated_apps.add(app_label)

MigrationLoader.load_disk = _billing_safe_loader_load_disk

if "product" not in apps.all_models.get("products", {}):
    class Product(models.Model):
        name = models.CharField(max_length=255)
        description = models.TextField(blank=True)
        is_active = models.BooleanField(default=True)

        class Meta:
            app_label = "products"
            db_table = "products_product"
            managed = False

        def __str__(self):
            return self.name


if "plan" not in apps.all_models.get("products", {}):
    class Plan(models.Model):
        product = models.ForeignKey("products.Product", on_delete=models.CASCADE, null=True, blank=True, related_name="plans")
        name = models.CharField(max_length=255)
        billing_frequency = models.CharField(max_length=20, default="MONTHLY")
        price = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))

        class Meta:
            app_label = "products"
            db_table = "products_plan"
            managed = False

        def __str__(self):
            return self.name


if "subscription" not in apps.all_models.get("subscriptions", {}):
    class Subscription(models.Model):
        subscription_number = models.CharField(max_length=100, unique=True)
        customer = models.ForeignKey("customers.Customer", on_delete=models.PROTECT, related_name="subscriptions")
        plan = models.ForeignKey("products.Plan", on_delete=models.PROTECT, null=True, blank=True, related_name="subscriptions")
        status = models.CharField(max_length=20, default="ACTIVE")
        start_date = models.DateField(default=timezone.localdate)
        expiry_date = models.DateField(null=True, blank=True)
        next_billing_date = models.DateField(null=True, blank=True)
        payment_terms = models.PositiveIntegerField(default=15)

        class Meta:
            app_label = "subscriptions"
            db_table = "subscriptions_subscription"
            managed = False

        def __str__(self):
            return self.subscription_number


if "subscriptionitem" not in apps.all_models.get("subscriptions", {}):
    class SubscriptionItem(models.Model):
        subscription = models.ForeignKey("subscriptions.Subscription", on_delete=models.CASCADE, related_name="items")
        product = models.ForeignKey("products.Product", on_delete=models.SET_NULL, null=True, blank=True)
        description = models.CharField(max_length=255, blank=True, default="")
        quantity = models.PositiveIntegerField(default=1)
        unit_price = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
        tax_rate = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("0.00"))

        class Meta:
            app_label = "subscriptions"
            db_table = "subscriptions_subscriptionitem"
            managed = False

        def __str__(self):
            return f"{self.description} ({self.quantity}x)"


if "discount" not in apps.all_models.get("discounts", {}):
    class Discount(models.Model):
        code = models.CharField(max_length=50, unique=True)
        discount_type = models.CharField(max_length=20, choices=[("PERCENTAGE", "Percentage"), ("FIXED", "Fixed")], default="PERCENTAGE")
        amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
        usage_count = models.PositiveIntegerField(default=0)
        max_redemptions = models.PositiveIntegerField(null=True, blank=True)
        is_active = models.BooleanField(default=True)

        class Meta:
            app_label = "discounts"
            db_table = "discounts_discount"
            managed = False

        def __str__(self):
            return self.code


# ==============================================================================
# BILLING DATE PROGRESSION HELPER
# ==============================================================================

def calculate_next_billing_date(current_date: date, frequency: str) -> date:
    """
    Computes next billing date based on frequency.
    Delegates to subscriptions.services.calculate_next_billing_date if implemented.
    """
    try:
        from subscriptions.services import calculate_next_billing_date as member3_calc
        return member3_calc(current_date, frequency)
    except (ImportError, AttributeError):
        pass

    freq = (frequency or "MONTHLY").upper()
    if freq == "DAILY":
        return current_date + timedelta(days=1)
    elif freq == "WEEKLY":
        return current_date + timedelta(days=7)
    elif freq == "YEARLY":
        try:
            return current_date.replace(year=current_date.year + 1)
        except ValueError:
            # Handle leap year Feb 29
            return current_date + timedelta(days=365)
    else:  # MONTHLY default
        # Add ~1 calendar month safely
        year = current_date.year + (current_date.month // 12)
        month = (current_date.month % 12) + 1
        day = min(current_date.day, 28)
        return date(year, month, day)


# ==============================================================================
# DISCOUNT RESOLUTION & COMMIT BOUNDARY
# ==============================================================================

def resolve_discount(
    subscription, subtotal: Decimal, quantity: int = 1, at_date: Optional[date] = None
) -> Tuple[Decimal, Optional[object]]:
    """
    Resolves discount amount and applied discount object.
    Never commits usage here (usage is committed upon invoice confirmation).
    """
    if at_date is None:
        at_date = timezone.localdate()

    # Attempt to call Member 3's service if present
    try:
        from discounts.services import get_applicable_discount, get_subscription_discount
        discount_obj = get_subscription_discount(subscription, at_date=at_date)
        discount_val = get_applicable_discount(subscription, subtotal, quantity, at_date=at_date)
        return quantize_money(discount_val), discount_obj
    except (ImportError, AttributeError):
        pass

    # Stub fallback: check subscription attached discount
    discount = getattr(subscription, "discount", None)
    if not discount or not getattr(discount, "is_active", True):
        return Decimal("0.00"), None

    if getattr(discount, "max_redemptions", None) and discount.usage_count >= discount.max_redemptions:
        return Decimal("0.00"), None

    dtype = getattr(discount, "discount_type", "PERCENTAGE").upper()
    damount = quantize_money(getattr(discount, "amount", Decimal("0.00")))

    if dtype == "PERCENTAGE":
        calc = quantize_money(subtotal * (damount / Decimal("100.00")))
    else:
        calc = damount

    # Discount cannot exceed subtotal
    final_discount = min(calc, subtotal)
    return quantize_money(final_discount), discount


def commit_discount_usage(discount) -> None:
    """
    Atomically commits discount redemption on invoice confirmation.
    Usage is never incremented on draft creation or preview.
    """
    if not discount or not hasattr(discount, "pk") or not discount.pk:
        return

    DiscountModel = apps.get_model("discounts", "Discount")
    if hasattr(DiscountModel, "usage_count"):
        DiscountModel.objects.filter(pk=discount.pk).update(usage_count=F("usage_count") + 1)
    elif hasattr(DiscountModel, "times_redeemed"):
        DiscountModel.objects.filter(pk=discount.pk).update(times_redeemed=F("times_redeemed") + 1)
