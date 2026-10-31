"""
Business logic services for discounts and coupon redemptions.
"""

from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional, Union

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import F, Q, QuerySet
from django.utils import timezone

from .models import Discount, DiscountType


def quantize_money(amount: Union[Decimal, float, int, str, None]) -> Decimal:
    """Helper to ensure standard 2-decimal monetary representation."""
    if amount is None:
        return Decimal("0.00")
    if not isinstance(amount, Decimal):
        amount = Decimal(str(amount))
    return amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def is_discount_valid(
    discount: Optional[Discount],
    on_date: Optional[Union[date, datetime]] = None,
) -> bool:
    """
    Checks if a discount rule is currently valid and eligible for redemption.
    Verifies active status, start/end date window, and redemption count limits.
    """
    if discount is None:
        return False

    if not discount.is_active:
        return False

    if on_date is None:
        chk_date = timezone.localdate()
    elif isinstance(on_date, datetime):
        chk_date = on_date.date()
    else:
        chk_date = on_date

    # Validate start/from date
    start = discount.valid_from or discount.start_date
    if start and chk_date < start:
        return False

    # Validate end/until date
    end = discount.valid_until or discount.end_date
    if end and chk_date > end:
        return False

    # Validate usage cap
    limit = discount.max_redemptions if discount.max_redemptions is not None else discount.usage_limit
    times = discount.times_redeemed if discount.times_redeemed is not None else discount.times_used
    if limit is not None and times >= limit:
        return False

    return True


def calculate_discount_amount(
    discount: Optional[Discount],
    subtotal: Decimal,
    on_date: Optional[Union[date, datetime]] = None,
) -> Decimal:
    """
    Calculates the monetary discount amount to deduct from subtotal.
    Never exceeds subtotal, never negative, rounded half-up to 2 decimal places.
    """
    subtotal = quantize_money(subtotal)
    if subtotal <= Decimal("0.00") or not is_discount_valid(discount, on_date=on_date):
        return Decimal("0.00")

    dtype = (discount.discount_type or "").upper()
    rate = discount.amount

    if dtype == DiscountType.PERCENTAGE:
        raw_discount = subtotal * (rate / Decimal("100.00"))
    else:
        raw_discount = rate

    capped = min(raw_discount, subtotal)
    return quantize_money(max(Decimal("0.00"), capped))


@transaction.atomic
def apply_discount(discount: Discount) -> bool:
    """
    Atomically records a redemption of the discount rule.
    Locks row using select_for_update to prevent race conditions exceeding max_redemptions.
    """
    if not discount or not discount.pk:
        return False

    locked_discount = (
        Discount.objects.select_for_update()
        .filter(pk=discount.pk)
        .first()
    )
    if not locked_discount:
        return False

    if not is_discount_valid(locked_discount):
        return False

    Discount.objects.filter(pk=discount.pk).update(
        times_used=F("times_used") + 1
    )
    locked_discount.refresh_from_db(fields=["times_used"])
    discount.times_used = locked_discount.times_used
    return True


# ------------------------------------------------------------------------------
# Teammate Integration Bridges (Used by billing.services and billing.integrations)
# ------------------------------------------------------------------------------

def get_subscription_discount(
    subscription,
    at_date: Optional[Union[date, datetime]] = None,
) -> Optional[Discount]:
    """Retrieves and validates any discount attached to a subscription."""
    discount = getattr(subscription, "discount", None)
    if discount and is_discount_valid(discount, on_date=at_date):
        return discount
    return None


def get_applicable_discount(
    subscription,
    subtotal: Decimal,
    quantity: int = 1,
    at_date: Optional[Union[date, datetime]] = None,
) -> Decimal:
    """Calculates discount amount applicable for a subscription cycle."""
    discount = get_subscription_discount(subscription, at_date=at_date)
    if not discount:
        return Decimal("0.00")
    return calculate_discount_amount(discount, subtotal, on_date=at_date)


def search_and_filter_discounts(
    queryset: QuerySet,
    query: Optional[str] = None,
    discount_type: Optional[str] = None,
    status: Optional[str] = None,
) -> QuerySet:
    """Filters discount queryset for admin/staff management list."""
    if query:
        q = query.strip()
        queryset = queryset.filter(Q(code__icontains=q) | Q(name__icontains=q))

    if discount_type:
        dt = discount_type.strip().upper()
        if dt in (DiscountType.PERCENTAGE, DiscountType.FIXED):
            queryset = queryset.filter(discount_type=dt)

    if status:
        st = status.strip().lower()
        today = timezone.localdate()
        if st == "active":
            queryset = queryset.filter(
                is_active=True
            ).filter(
                Q(end_date__isnull=True) | Q(end_date__gte=today)
            )
        elif st in ("expired", "inactive"):
            queryset = queryset.filter(
                Q(is_active=False) | Q(end_date__lt=today)
            )

    return queryset
