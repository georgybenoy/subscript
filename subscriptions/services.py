"""
Domain business logic services for Subscriptions lifecycle, date progression, and billing queries.
"""

import calendar
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, Optional, Union

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q, QuerySet
from django.utils import timezone

from customers.services import scope_queryset_for_user
from .models import Subscription, SubscriptionItem, SubscriptionStatus


class InvalidSubscriptionTransitionError(Exception):
    """Raised when an illegal lifecycle transition is attempted on a Subscription."""
    pass


# Lifecycle state machine transition map
VALID_TRANSITIONS = {
    SubscriptionStatus.DRAFT: {
        SubscriptionStatus.QUOTATION,
        SubscriptionStatus.CONFIRMED,
        SubscriptionStatus.ACTIVE,
        SubscriptionStatus.CANCELLED,
    },
    SubscriptionStatus.QUOTATION: {
        SubscriptionStatus.CONFIRMED,
        SubscriptionStatus.ACTIVE,
        SubscriptionStatus.CANCELLED,
    },
    SubscriptionStatus.CONFIRMED: {
        SubscriptionStatus.ACTIVE,
        SubscriptionStatus.CANCELLED,
    },
    SubscriptionStatus.ACTIVE: {
        SubscriptionStatus.PAUSED,
        SubscriptionStatus.CANCELLED,
        SubscriptionStatus.EXPIRED,
        SubscriptionStatus.CLOSED,
        SubscriptionStatus.PAST_DUE,
    },
    SubscriptionStatus.PAST_DUE: {
        SubscriptionStatus.ACTIVE,
        SubscriptionStatus.CANCELLED,
        SubscriptionStatus.CLOSED,
    },
    SubscriptionStatus.PAUSED: {
        SubscriptionStatus.ACTIVE,
        SubscriptionStatus.CANCELLED,
        SubscriptionStatus.CLOSED,
    },
    SubscriptionStatus.EXPIRED: {
        SubscriptionStatus.ACTIVE,
        SubscriptionStatus.CLOSED,
    },
    SubscriptionStatus.CANCELLED: set(),
    SubscriptionStatus.CLOSED: set(),
}


# ==============================================================================
# DATE PROGRESSION ENGINE
# ==============================================================================

def add_calendar_months(source_date: date, months: int) -> date:
    """
    Safely adds calendar months preserving month-end pinning.
    e.g., Jan 31 + 1 month -> Feb 28 (or 29 in leap year).
    """
    year = source_date.year + ((source_date.month + months - 1) // 12)
    month = ((source_date.month + months - 1) % 12) + 1
    max_day = calendar.monthrange(year, month)[1]
    day = min(source_date.day, max_day)
    return date(year, month, day)


def compute_next_billing_date(current_date: Union[date, datetime], frequency: str) -> date:
    """
    Computes next billing date according to cadence:
    DAILY, WEEKLY, MONTHLY, QUARTERLY, YEARLY.
    Handles leap years and month-end dates accurately.
    """
    if isinstance(current_date, datetime):
        current_date = current_date.date()

    freq = (frequency or "MONTHLY").upper()

    if freq == "DAILY":
        return current_date + timedelta(days=1)
    elif freq == "WEEKLY":
        return current_date + timedelta(days=7)
    elif freq == "MONTHLY":
        return add_calendar_months(current_date, 1)
    elif freq == "QUARTERLY":
        return add_calendar_months(current_date, 3)
    elif freq == "YEARLY":
        try:
            return current_date.replace(year=current_date.year + 1)
        except ValueError:
            # Handle leap year Feb 29
            return current_date + timedelta(days=365)
    else:
        return add_calendar_months(current_date, 1)


# Compatibility alias used by billing.integrations.calculate_next_billing_date
calculate_next_billing_date = compute_next_billing_date


# ==============================================================================
# SUBSCRIPTION LIFECYCLE OPERATIONS
# ==============================================================================

def transition_subscription_status(subscription: Subscription, target_status: str) -> Subscription:
    """
    Safely transitions a subscription to a new lifecycle state.
    Raises InvalidSubscriptionTransitionError if illegal.
    """
    current_status = subscription.status
    target = target_status.upper()

    if current_status == target:
        return subscription

    allowed_targets = VALID_TRANSITIONS.get(current_status, set())
    if target not in allowed_targets:
        raise InvalidSubscriptionTransitionError(
            f"Cannot transition subscription from '{current_status}' to '{target}'."
        )

    subscription.status = target
    subscription.save(update_fields=["status", "updated_at"])
    return subscription


@transaction.atomic
def create_subscription(
    customer,
    plan,
    items_data: Optional[List[Dict[str, Any]]] = None,
    discount=None,
    status: str = SubscriptionStatus.DRAFT,
    start_date: Optional[date] = None,
    expiry_date: Optional[date] = None,
    payment_terms: int = 15,
) -> Subscription:
    """
    Creates a new recurring subscription with line items.
    Validates minimum quantity against plan rules and snapshots pricing.
    """
    if start_date is None:
        start_date = timezone.localdate()

    cadence = getattr(plan, "billing_interval", getattr(plan, "billing_frequency", "MONTHLY"))
    period_end = expiry_date or compute_next_billing_date(start_date, cadence)

    sub = Subscription.objects.create(
        customer=customer,
        plan=plan,
        discount=discount,
        status=status,
        start_date=start_date,
        expiry_date=expiry_date,
        current_period_start=start_date,
        current_period_end=period_end,
        next_billing_date=start_date if status == SubscriptionStatus.ACTIVE else None,
        payment_terms=payment_terms,
    )

    if items_data:
        min_qty = getattr(plan, "minimum_quantity", 1)
        for item_info in items_data:
            qty = int(item_info.get("quantity", 1))
            if qty < min_qty:
                raise ValidationError(
                    f"Item quantity ({qty}) cannot be less than plan minimum ({min_qty})."
                )

            variant = item_info.get("variant")
            product = item_info.get("product") or (variant.product if variant else None)
            unit_price = item_info.get("unit_price")

            if unit_price is None:
                if variant:
                    unit_price = variant.effective_price
                elif product:
                    unit_price = product.sales_price
                else:
                    unit_price = plan.base_price

            SubscriptionItem.objects.create(
                subscription=sub,
                product=product,
                variant=variant,
                description=item_info.get("description", ""),
                quantity=qty,
                unit_price=unit_price,
                tax_rate=item_info.get("tax_rate", Decimal("0.00")),
            )

    return sub


def activate_subscription(subscription: Subscription, as_of: Optional[date] = None) -> Subscription:
    """
    Transitions subscription to ACTIVE.
    Initializes next_billing_date and billing periods.
    """
    if subscription.status == SubscriptionStatus.ACTIVE:
        return subscription

    transition_subscription_status(subscription, SubscriptionStatus.ACTIVE)

    cur_start = as_of or subscription.start_date or timezone.localdate()
    cadence = "MONTHLY"
    if subscription.plan:
        cadence = getattr(
            subscription.plan,
            "billing_interval",
            getattr(subscription.plan, "billing_frequency", "MONTHLY"),
        ) or "MONTHLY"
    cur_end = compute_next_billing_date(cur_start, cadence)

    subscription.current_period_start = cur_start
    subscription.current_period_end = cur_end
    if not subscription.next_billing_date:
        subscription.next_billing_date = cur_start

    subscription.save(
        update_fields=[
            "current_period_start",
            "current_period_end",
            "next_billing_date",
            "updated_at",
        ]
    )
    return subscription


def pause_subscription(subscription: Subscription) -> Subscription:
    """Pauses an active subscription."""
    return transition_subscription_status(subscription, SubscriptionStatus.PAUSED)


def resume_subscription(subscription: Subscription) -> Subscription:
    """Resumes a paused subscription to ACTIVE state."""
    return transition_subscription_status(subscription, SubscriptionStatus.ACTIVE)


def cancel_subscription(subscription: Subscription, immediate: bool = True) -> Subscription:
    """
    Cancels a subscription.
    If immediate, changes status to CANCELLED immediately.
    If not immediate, sets cancel_at_period_end = True.
    """
    if immediate:
        return transition_subscription_status(subscription, SubscriptionStatus.CANCELLED)
    else:
        subscription.cancel_at_period_end = True
        subscription.save(update_fields=["cancel_at_period_end", "updated_at"])
        return subscription


def expire_subscription(subscription: Subscription) -> Subscription:
    """Marks an agreement as expired."""
    return transition_subscription_status(subscription, SubscriptionStatus.EXPIRED)


def renew_subscription(subscription: Subscription) -> Subscription:
    """Advances period and renews active subscription agreement."""
    cadence = "MONTHLY"
    if subscription.plan:
        cadence = getattr(
            subscription.plan,
            "billing_interval",
            getattr(subscription.plan, "billing_frequency", "MONTHLY"),
        ) or "MONTHLY"
    next_start = subscription.current_period_end or timezone.localdate()
    next_end = compute_next_billing_date(next_start, cadence)

    subscription.current_period_start = next_start
    subscription.current_period_end = next_end
    subscription.next_billing_date = next_start

    if subscription.status in (SubscriptionStatus.EXPIRED, SubscriptionStatus.PAUSED):
        subscription.status = SubscriptionStatus.ACTIVE

    subscription.save(
        update_fields=[
            "status",
            "current_period_start",
            "current_period_end",
            "next_billing_date",
            "updated_at",
        ]
    )
    return subscription


# ==============================================================================
# BILLING ENGINE & DASHBOARD QUERY HELPERS
# ==============================================================================

def get_subscriptions_due_for_billing(as_of_date: Optional[date] = None) -> QuerySet:
    """
    Returns active subscriptions ready for recurring invoice generation.
    Matches next_billing_date <= as_of_date and not past expiry.
    """
    if as_of_date is None:
        as_of_date = timezone.localdate()

    return (
        Subscription.objects.filter(
            status=SubscriptionStatus.ACTIVE,
            next_billing_date__lte=as_of_date,
        )
        .filter(Q(expiry_date__isnull=True) | Q(expiry_date__gte=as_of_date))
        .select_related("customer", "plan", "discount")
        .prefetch_related("items", "items__variant", "items__product")
    )


def get_active_subscriptions_for_customer(customer) -> QuerySet:
    """Returns all active subscriptions belonging to a customer profile."""
    return Subscription.objects.filter(
        customer=customer,
        status=SubscriptionStatus.ACTIVE,
    ).select_related("plan")


def get_subscriptions_for_user(user) -> QuerySet:
    """
    Returns subscriptions scoped by user role:
    - Admin/Staff: all subscriptions
    - Customer: only subscriptions where customer.user == user
    - Others: none
    """
    qs = Subscription.objects.select_related("customer", "plan", "discount").prefetch_related("items")
    return scope_queryset_for_user(qs, user, customer_lookup="customer__user")


def search_and_filter_subscriptions(
    queryset: QuerySet,
    query: Optional[str] = None,
    plan_id: Optional[Union[str, int]] = None,
    status: Optional[str] = None,
) -> QuerySet:
    """Filters subscriptions with text search and status/plan dropdowns."""
    if query:
        q = query.strip()
        queryset = queryset.filter(
            Q(subscription_number__icontains=q)
            | Q(customer__name__icontains=q)
            | Q(customer__company_name__icontains=q)
            | Q(customer__email__icontains=q)
        )

    if plan_id:
        try:
            queryset = queryset.filter(plan_id=int(plan_id))
        except (ValueError, TypeError):
            pass

    if status:
        st = status.strip().upper()
        if st in SubscriptionStatus.values:
            queryset = queryset.filter(status=st)

    return queryset


def subscription_total(subscription: Subscription) -> Decimal:
    """Returns total recurring monetary amount for subscription."""
    return subscription.total_recurring_amount
