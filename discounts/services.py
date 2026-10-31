from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional, Tuple, Union
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


def validate_discount_code(
    code: Optional[str],
    at_date: Optional[Union[datetime, date]] = None,
) -> Tuple[bool, Optional[Discount], str]:
    """
    Validates a discount code for eligibility against active status,
    validity date window, and maximum redemption limits.

    Returns:
        (is_valid: bool, discount: Optional[Discount], message: str)
    """
    if not code:
        return False, None, "Discount code cannot be empty."

    clean_code = str(code).strip().upper()
    try:
        discount = Discount.objects.get(code=clean_code)
    except Discount.DoesNotExist:
        return False, None, f"Discount code '{clean_code}' is invalid."

    if not discount.is_active:
        return False, discount, f"Discount code '{clean_code}' is inactive."

    now = at_date or timezone.now()
    if isinstance(now, date) and not isinstance(now, datetime):
        now = timezone.make_aware(datetime.combine(now, datetime.min.time()))

    if discount.valid_from and now < discount.valid_from:
        return False, discount, f"Discount code '{clean_code}' is not yet active."

    if discount.valid_until and now > discount.valid_until:
        return False, discount, f"Discount code '{clean_code}' has expired."

    if discount.max_redemptions is not None and discount.times_redeemed >= discount.max_redemptions:
        return False, discount, f"Discount code '{clean_code}' has reached its maximum redemption limit."

    return True, discount, f"Discount code '{clean_code}' is valid."


def is_discount_valid(
    discount: Optional[Discount],
    on_date: Optional[Union[date, datetime]] = None,
) -> bool:
    """
    Checks if a discount rule is currently valid and eligible for redemption.
    """
    if discount is None:
        return False
    is_valid, _, _ = validate_discount_code(discount.code, at_date=on_date)
    return is_valid


def get_applicable_discount(
    subscription=None,
    subtotal: Decimal = Decimal("0.00"),
    quantity: int = 1,
    at_date: Optional[Union[datetime, date]] = None,
    discount: Optional[Discount] = None,
) -> Decimal:
    """
    Calculates the applicable discount monetary amount for a given subtotal.
    This is an idempotent, read-only preview calculation that NEVER alters
    the discount's times_redeemed count.

    Rules:
    - Resolves discount from explicit argument or subscription.discount.
    - Returns Decimal("0.00") if missing, inactive, not yet valid, expired or exhausted.
    - PERCENTAGE: calculates percentage of subtotal rounded to 2 decimal places (ROUND_HALF_UP).
    - FIXED: uses fixed amount.
    - Caps discount at subtotal (cannot produce a negative invoice total).
    - Never returns a negative amount.
    """
    resolved_discount = discount
    if resolved_discount is None and subscription is not None:
        resolved_discount = getattr(subscription, "discount", None)

    if resolved_discount is None:
        return Decimal("0.00")

    if not isinstance(subtotal, Decimal):
        try:
            subtotal = Decimal(str(subtotal))
        except Exception:
            return Decimal("0.00")

    if subtotal <= Decimal("0.00"):
        return Decimal("0.00")

    is_valid, _, _ = validate_discount_code(resolved_discount.code, at_date=at_date)
    if not is_valid:
        return Decimal("0.00")

    if resolved_discount.discount_type == Discount.DiscountType.PERCENTAGE:
        raw_discount = subtotal * (resolved_discount.amount / Decimal("100.00"))
    elif resolved_discount.discount_type == Discount.DiscountType.FIXED:
        raw_discount = resolved_discount.amount
    else:
        return Decimal("0.00")

    discount_amount = quantize_money(raw_discount)

    if discount_amount > subtotal:
        discount_amount = subtotal
    if discount_amount < Decimal("0.00"):
        discount_amount = Decimal("0.00")

    return discount_amount


def calculate_discount_amount(
    discount: Optional[Discount],
    subtotal: Decimal,
    on_date: Optional[Union[date, datetime]] = None,
) -> Decimal:
    """Compatibility alias for get_applicable_discount."""
    return get_applicable_discount(
        discount=discount,
        subtotal=subtotal,
        at_date=on_date,
    )


def record_discount_redemption(discount: Optional[Discount]) -> bool:
    """
    Atomically records a confirmed redemption for a discount using F expressions.
    Enforces active status, validity window, and max_redemptions atomically.
    """
    if discount is None or not getattr(discount, "pk", None):
        return False

    now = timezone.now()
    with transaction.atomic():
        query = (
            Discount.objects.filter(
                pk=discount.pk,
                is_active=True,
                valid_from__lte=now,
            )
            .filter(Q(valid_until__isnull=True) | Q(valid_until__gte=now))
            .filter(
                Q(max_redemptions__isnull=True) | Q(times_redeemed__lt=F("max_redemptions"))
            )
        )

        updated = query.update(times_redeemed=F("times_redeemed") + 1)

        if updated == 1:
            discount.refresh_from_db(fields=["times_redeemed"])
            return True
        return False


def apply_discount(discount: Discount) -> bool:
    """Compatibility wrapper around record_discount_redemption."""
    return record_discount_redemption(discount)


def get_subscription_discount(
    subscription,
    at_date: Optional[Union[date, datetime]] = None,
) -> Optional[Discount]:
    """Retrieves and validates any discount attached to a subscription."""
    discount = getattr(subscription, "discount", None)
    if discount and is_discount_valid(discount, on_date=at_date):
        return discount
    return None


def search_and_filter_discounts(
    queryset: QuerySet,
    query: Optional[str] = None,
    discount_type: Optional[str] = None,
    status: Optional[str] = None,
) -> QuerySet:
    """Filters discount queryset for admin/staff management list."""
    if query:
        q = query.strip()
        queryset = queryset.filter(code__icontains=q)

    if discount_type:
        dt = discount_type.strip().upper()
        if dt in (DiscountType.PERCENTAGE, DiscountType.FIXED):
            queryset = queryset.filter(discount_type=dt)

    if status:
        st = status.strip().lower()
        now = timezone.now()
        if st == "active":
            queryset = queryset.filter(
                is_active=True,
                valid_from__lte=now,
            ).filter(
                Q(valid_until__isnull=True) | Q(valid_until__gte=now)
            )
        elif st in ("expired", "inactive"):
            queryset = queryset.filter(
                Q(is_active=False) | Q(valid_until__lt=now)
            )

    return queryset
