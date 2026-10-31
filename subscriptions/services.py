import calendar
from datetime import timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from .models import Subscription, SubscriptionItem


def calculate_next_billing_date(
    start_date: timezone.datetime,
    billing_interval: str,
) -> timezone.datetime:
    """
    Computes the subsequent recurring billing boundary date based on interval:
    - WEEKLY: exactly +7 days.
    - MONTHLY: +1 month, clipping to the maximum days in target month.
    - QUARTERLY: +3 months, clipping to the maximum days in target month.
    - YEARLY: +1 year, handling leap year Feb 29 clipping to Feb 28.
    Preserves time components (hour, minute, second, microsecond, tzinfo).
    """
    interval = str(billing_interval).strip().upper()

    if interval == "WEEKLY":
        return start_date + timedelta(days=7)

    if interval == "MONTHLY":
        target_year = start_date.year + (start_date.month // 12)
        target_month = (start_date.month % 12) + 1
        max_day = calendar.monthrange(target_year, target_month)[1]
        target_day = min(start_date.day, max_day)
        return start_date.replace(year=target_year, month=target_month, day=target_day)

    if interval == "QUARTERLY":
        total_months = start_date.month + 3
        target_year = start_date.year + ((total_months - 1) // 12)
        target_month = ((total_months - 1) % 12) + 1
        max_day = calendar.monthrange(target_year, target_month)[1]
        target_day = min(start_date.day, max_day)
        return start_date.replace(year=target_year, month=target_month, day=target_day)

    if interval == "YEARLY":
        target_year = start_date.year + 1
        target_month = start_date.month
        max_day = calendar.monthrange(target_year, target_month)[1]
        target_day = min(start_date.day, max_day)
        return start_date.replace(year=target_year, month=target_month, day=target_day)

    raise ValidationError(f"Unsupported billing interval: '{billing_interval}'.")


def create_subscription(
    customer,
    plan,
    discount=None,
    items: Optional[List[Dict[str, Any]]] = None,
    start_date: Optional[timezone.datetime] = None,
    trial_days: Optional[int] = None,
) -> Subscription:
    """
    Creates a new Subscription with items and initial cycle dates.
    - Enforces active status for Customer and Plan.
    - Validates discount eligibility via discounts.services.
    - Supports trial period: if trial_days > 0, sets status to TRIALING.
    - Creates attached SubscriptionItem line items atomically.
    """
    if not customer or not getattr(customer, "is_active", False):
        raise ValidationError("Cannot create subscription: Customer is inactive or missing.")

    if not plan or not getattr(plan, "is_active", False):
        raise ValidationError("Cannot create subscription: Plan is inactive or missing.")

    # Validate discount if provided
    resolved_discount = discount
    if resolved_discount:
        from discounts import services as discount_services

        code = getattr(resolved_discount, "code", str(resolved_discount))
        is_valid, valid_discount, message = discount_services.validate_discount_code(
            code=code,
            at_date=start_date or timezone.now(),
        )
        if not is_valid:
            raise ValidationError(f"Invalid discount: {message}")
        resolved_discount = valid_discount

    effective_start = start_date or timezone.now()
    effective_trial = trial_days if trial_days is not None else getattr(plan, "trial_days", 0)

    if effective_trial > 0:
        initial_status = Subscription.Status.TRIALING
        effective_end = effective_start + timedelta(days=effective_trial)
    else:
        initial_status = Subscription.Status.ACTIVE
        effective_end = calculate_next_billing_date(effective_start, plan.billing_interval)

    with transaction.atomic():
        subscription = Subscription(
            customer=customer,
            plan=plan,
            discount=resolved_discount,
            status=initial_status,
            current_period_start=effective_start,
            current_period_end=effective_end,
            cancel_at_period_end=False,
        )
        subscription.full_clean()
        subscription.save()

        if items:
            for item_data in items:
                variant = item_data.get("variant")
                quantity = item_data.get("quantity", 1)
                unit_price = item_data.get(
                    "unit_price",
                    getattr(variant, "price", Decimal("0.00")) if variant else Decimal("0.00"),
                )
                item = SubscriptionItem(
                    subscription=subscription,
                    variant=variant,
                    quantity=quantity,
                    unit_price=unit_price,
                )
                item.full_clean()
                item.save()

    return subscription


def confirm_subscription(subscription: Subscription) -> Subscription:
    """
    Validates readiness and integrity of a subscription agreement.
    Checks customer status, plan status, and attached line items.
    """
    if not subscription.customer.is_active:
        raise ValidationError("Subscription confirmation failed: customer is inactive.")

    if not subscription.plan.is_active:
        raise ValidationError("Subscription confirmation failed: plan is inactive.")

    if subscription.discount and not subscription.discount.is_active:
        raise ValidationError("Subscription confirmation failed: attached discount is inactive.")

    return subscription


def activate_subscription(subscription: Subscription) -> Subscription:
    """
    Transitions a subscription into ACTIVE status (e.g., from TRIALING).
    Commences regular billing cycle if converting from trial.
    """
    if subscription.status == Subscription.Status.ACTIVE:
        return subscription

    if subscription.status != Subscription.Status.TRIALING:
        raise ValidationError(
            f"Cannot activate subscription with status '{subscription.status}'. "
            f"Only TRIALING subscriptions can be directly activated."
        )

    now = timezone.now()
    subscription.status = Subscription.Status.ACTIVE
    subscription.current_period_start = now
    subscription.current_period_end = calculate_next_billing_date(
        now,
        subscription.plan.billing_interval,
    )
    subscription.save(
        update_fields=["status", "current_period_start", "current_period_end", "updated_at"]
    )
    return subscription


def pause_subscription(
    subscription: Subscription,
    at_date: Optional[timezone.datetime] = None,
) -> Subscription:
    """
    Transitions an ACTIVE subscription into PAUSED status.
    Records paused_at timestamp to ensure unused paid time is preserved upon resumption.
    """
    if subscription.status != Subscription.Status.ACTIVE:
        raise ValidationError(
            f"Cannot pause subscription with status '{subscription.status}'. "
            f"Only ACTIVE subscriptions can be paused."
        )

    pause_time = at_date or timezone.now()
    subscription.status = Subscription.Status.PAUSED
    subscription.paused_at = pause_time
    subscription.save(update_fields=["status", "paused_at", "updated_at"])
    return subscription


def resume_subscription(
    subscription: Subscription,
    at_date: Optional[timezone.datetime] = None,
) -> Subscription:
    """
    Restores a PAUSED subscription to ACTIVE status.
    Accurately extends current_period_end by the exact pause duration using paused_at.
    Rejects resume timestamps earlier than paused_at.
    """
    if subscription.status != Subscription.Status.PAUSED:
        raise ValidationError(
            f"Cannot resume subscription with status '{subscription.status}'. "
            f"Only PAUSED subscriptions can be resumed."
        )

    resume_time = at_date or timezone.now()
    if subscription.paused_at:
        if resume_time < subscription.paused_at:
            raise ValidationError("Resume date cannot be earlier than pause date.")

        pause_duration = resume_time - subscription.paused_at
        if pause_duration.total_seconds() > 0:
            subscription.current_period_end = subscription.current_period_end + pause_duration

    subscription.status = Subscription.Status.ACTIVE
    subscription.paused_at = None
    subscription.save(
        update_fields=["status", "current_period_end", "paused_at", "updated_at"]
    )
    return subscription


def close_subscription(
    subscription: Subscription,
    immediate: bool = True,
) -> Subscription:
    """
    Cancels a subscription.
    - immediate=True: Immediately transitions status to CANCELED.
    - immediate=False: Marks cancel_at_period_end=True, remaining ACTIVE until current_period_end.
    """
    if subscription.status == Subscription.Status.CANCELED:
        raise ValidationError("Subscription is already canceled.")

    if immediate:
        subscription.status = Subscription.Status.CANCELED
        subscription.cancel_at_period_end = False
        subscription.save(update_fields=["status", "cancel_at_period_end", "updated_at"])
    else:
        subscription.cancel_at_period_end = True
        subscription.save(update_fields=["cancel_at_period_end", "updated_at"])

    return subscription


def renew_subscription(
    subscription: Subscription,
    at_date: Optional[timezone.datetime] = None,
) -> Subscription:
    """
    Advances the billing cycle at period end, or finalizes cancellation
    if cancel_at_period_end is flagged.
    Prevents renewal prior to current_period_end.
    """
    if subscription.status != Subscription.Status.ACTIVE:
        raise ValidationError(
            f"Cannot renew subscription with status '{subscription.status}'. "
            f"Only ACTIVE subscriptions can be renewed."
        )

    eval_date = at_date or timezone.now()
    if eval_date < subscription.current_period_end:
        raise ValidationError(
            f"Cannot renew subscription before current period end ({subscription.current_period_end})."
        )

    if subscription.cancel_at_period_end:
        subscription.status = Subscription.Status.CANCELED
        subscription.cancel_at_period_end = False
        subscription.save(update_fields=["status", "cancel_at_period_end", "updated_at"])
        return subscription

    old_end = subscription.current_period_end
    subscription.current_period_start = old_end
    subscription.current_period_end = calculate_next_billing_date(
        old_end,
        subscription.plan.billing_interval,
    )
    subscription.save(
        update_fields=["current_period_start", "current_period_end", "updated_at"]
    )
    return subscription


def get_subscriptions_for_user(user):
    """
    Tenant-scoped query for Subscriptions preventing IDOR vulnerabilities.
    Delegates to customers.services.scope_queryset_for_user.
    - Admin/Staff: all subscriptions.
    - Customer: only subscriptions belonging to their linked customer.
    - Anonymous/Inactive: empty queryset.
    """
    from customers.services import scope_queryset_for_user

    qs = Subscription.objects.select_related("customer", "plan", "discount")
    return scope_queryset_for_user(qs, user=user, customer_lookup="customer__user")
