from decimal import Decimal, ROUND_HALF_UP
from typing import Optional, Tuple
from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone
from .models import Discount


def validate_discount_code(
    code: Optional[str],
    at_date: Optional[timezone.datetime] = None,
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

    if now < discount.valid_from:
        return False, discount, f"Discount code '{clean_code}' is not yet active."

    if discount.valid_until and now > discount.valid_until:
        return False, discount, f"Discount code '{clean_code}' has expired."

    if discount.max_redemptions is not None and discount.times_redeemed >= discount.max_redemptions:
        return False, discount, f"Discount code '{clean_code}' has reached its maximum redemption limit."

    return True, discount, f"Discount code '{clean_code}' is valid."


def get_applicable_discount(
    subscription=None,
    subtotal: Decimal = Decimal("0.00"),
    quantity: int = 1,
    at_date: Optional[timezone.datetime] = None,
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
    - Preserves `quantity` in the interface without inventing un-documented eligibility rules.
    """
    # 1. Resolve Discount instance
    resolved_discount = discount
    if resolved_discount is None and subscription is not None:
        resolved_discount = getattr(subscription, "discount", None)

    if resolved_discount is None:
        return Decimal("0.00")

    # 2. Convert and validate subtotal
    if not isinstance(subtotal, Decimal):
        try:
            subtotal = Decimal(str(subtotal))
        except Exception:
            return Decimal("0.00")

    if subtotal <= Decimal("0.00"):
        return Decimal("0.00")

    # 3. Validate eligibility
    is_valid, _, _ = validate_discount_code(resolved_discount.code, at_date=at_date)
    if not is_valid:
        return Decimal("0.00")

    # 4. Compute reduction based on discount_type
    if resolved_discount.discount_type == Discount.DiscountType.PERCENTAGE:
        raw_discount = subtotal * (resolved_discount.amount / Decimal("100.00"))
    elif resolved_discount.discount_type == Discount.DiscountType.FIXED:
        raw_discount = resolved_discount.amount
    else:
        return Decimal("0.00")

    # 5. Round to 2 decimal places using ROUND_HALF_UP
    discount_amount = raw_discount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    # 6. Cap discount at subtotal and floor at 0.00
    if discount_amount > subtotal:
        discount_amount = subtotal
    if discount_amount < Decimal("0.00"):
        discount_amount = Decimal("0.00")

    return discount_amount


def record_discount_redemption(discount: Optional[Discount]) -> bool:
    """
    Atomically records a confirmed redemption for a discount using F expressions.
    Enforces active status, validity window, and max_redemptions atomically to prevent
    concurrent race conditions.

    Returns:
        True if redemption was successfully committed (exactly 1 record updated); False otherwise.
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
