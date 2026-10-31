from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from . import services


@login_required
def subscription_list_view(request):
    """
    Lists subscriptions visible to the authenticated user.
    Enforces IDOR defense via tenant-scoped querysets:
    - Admin/Staff: all subscriptions across all customers.
    - Customer: only their own subscriptions.
    """
    subscriptions_qs = services.get_subscriptions_for_user(request.user)
    status_filter = request.GET.get("status")
    if status_filter:
        subscriptions_qs = subscriptions_qs.filter(status=status_filter.strip().upper())

    if request.headers.get("Accept") == "application/json" or request.GET.get("format") == "json":
        data = [
            {
                "id": sub.id,
                "customer": sub.customer.name,
                "plan": sub.plan.name,
                "plan_code": sub.plan.code,
                "status": sub.status,
                "current_period_start": sub.current_period_start.isoformat(),
                "current_period_end": sub.current_period_end.isoformat(),
                "cancel_at_period_end": sub.cancel_at_period_end,
                "subtotal": str(sub.get_subtotal()),
                "total": str(sub.get_total()),
            }
            for sub in subscriptions_qs
        ]
        return JsonResponse({"subscriptions": data}, status=200)

    context = {
        "subscriptions": subscriptions_qs,
        "selected_status": status_filter or "",
    }
    return render(request, "subscriptions/subscription_list.html", context)


@login_required
def subscription_detail_view(request, pk: int):
    """
    Displays detail for a specific subscription.
    Enforces tenant scoping to prevent IDOR (raises 404 for unauthorized access).
    """
    subscriptions_qs = services.get_subscriptions_for_user(request.user)
    subscription = get_object_or_404(subscriptions_qs, pk=pk)

    if request.headers.get("Accept") == "application/json" or request.GET.get("format") == "json":
        data = {
            "id": subscription.id,
            "customer_id": subscription.customer.id,
            "customer_name": subscription.customer.name,
            "plan_code": subscription.plan.code,
            "plan_name": subscription.plan.name,
            "billing_interval": subscription.plan.billing_interval,
            "status": subscription.status,
            "current_period_start": subscription.current_period_start.isoformat(),
            "current_period_end": subscription.current_period_end.isoformat(),
            "cancel_at_period_end": subscription.cancel_at_period_end,
            "paused_at": subscription.paused_at.isoformat() if subscription.paused_at else None,
            "subtotal": str(subscription.get_subtotal()),
            "discount_amount": str(subscription.get_discount_amount()),
            "total": str(subscription.get_total()),
            "items": [
                {
                    "id": item.id,
                    "variant": item.variant.name if item.variant else None,
                    "quantity": item.quantity,
                    "unit_price": str(item.unit_price),
                    "amount": str(item.get_amount()),
                }
                for item in subscription.items.all()
            ],
        }
        return JsonResponse(data, status=200)

    context = {
        "subscription": subscription,
        "items": subscription.items.all(),
    }
    return render(request, "subscriptions/subscription_detail.html", context)


@login_required
@require_POST
def subscription_pause_view(request, pk: int):
    """
    Pauses an active subscription.
    """
    subscriptions_qs = services.get_subscriptions_for_user(request.user)
    subscription = get_object_or_404(subscriptions_qs, pk=pk)

    try:
        services.pause_subscription(subscription)
        messages.success(request, f"Subscription #{subscription.id} has been paused.")
    except ValidationError as err:
        messages.error(request, str(err.message if hasattr(err, "message") else err))

    if request.headers.get("Accept") == "application/json":
        return JsonResponse({"id": subscription.id, "status": subscription.status})
    return redirect("subscriptions:detail", pk=subscription.pk)


@login_required
@require_POST
def subscription_resume_view(request, pk: int):
    """
    Resumes a paused subscription, restoring remaining paid time.
    """
    subscriptions_qs = services.get_subscriptions_for_user(request.user)
    subscription = get_object_or_404(subscriptions_qs, pk=pk)

    try:
        services.resume_subscription(subscription)
        messages.success(request, f"Subscription #{subscription.id} has been resumed.")
    except ValidationError as err:
        messages.error(request, str(err.message if hasattr(err, "message") else err))

    if request.headers.get("Accept") == "application/json":
        return JsonResponse({"id": subscription.id, "status": subscription.status})
    return redirect("subscriptions:detail", pk=subscription.pk)


@login_required
@require_POST
def subscription_cancel_view(request, pk: int):
    """
    Cancels a subscription immediately or at period end.
    """
    subscriptions_qs = services.get_subscriptions_for_user(request.user)
    subscription = get_object_or_404(subscriptions_qs, pk=pk)

    immediate = request.POST.get("immediate", "false").lower() in ("true", "1")
    try:
        services.close_subscription(subscription, immediate=immediate)
        action_msg = "canceled immediately" if immediate else "scheduled for cancellation at period end"
        messages.success(request, f"Subscription #{subscription.id} {action_msg}.")
    except ValidationError as err:
        messages.error(request, str(err.message if hasattr(err, "message") else err))

    if request.headers.get("Accept") == "application/json":
        return JsonResponse(
            {
                "id": subscription.id,
                "status": subscription.status,
                "cancel_at_period_end": subscription.cancel_at_period_end,
            }
        )
    return redirect("subscriptions:detail", pk=subscription.pk)
