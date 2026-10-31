from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from accounts.permissions import staff_or_admin_required
from products.models import Plan
from .forms import SubscriptionFilterForm, SubscriptionForm
from .models import Subscription, SubscriptionStatus
from .services import (
    activate_subscription,
    cancel_subscription,
    get_subscriptions_for_user,
    pause_subscription,
    search_and_filter_subscriptions,
)


@login_required
def subscription_list_view(request):
    """
    Role-scoped subscription list:
    - Staff / Admin: see all subscriptions
    - Customer: see only their own subscriptions
    """
    queryset = get_subscriptions_for_user(request.user)
    available_plans = Plan.objects.filter(is_active=True)

    q = request.GET.get("q")
    plan_id = request.GET.get("plan")
    status = request.GET.get("status")

    queryset = search_and_filter_subscriptions(
        queryset,
        query=q,
        plan_id=plan_id,
        status=status,
    )

    paginator = Paginator(queryset, 15)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    return render(
        request,
        "subscriptions/list.html",
        {
            "subscriptions": page_obj.object_list,
            "page_obj": page_obj,
            "available_plans": available_plans,
        },
    )


@login_required
def subscription_detail_view(request, pk):
    """
    Role-scoped subscription detail:
    - Staff / Admin: full detail
    - Customer: only their own subscription (403/404 if not owned)
    """
    sub_qs = get_subscriptions_for_user(request.user)
    subscription = get_object_or_404(sub_qs, pk=pk)

    return render(
        request,
        "subscriptions/detail.html",
        {
            "subscription": subscription,
        },
    )


@staff_or_admin_required
def subscription_create_view(request):
    """Staff/admin view to create a new subscription agreement or sales quotation."""
    initial_data = {}
    requested_status = request.GET.get("status", "").upper()
    if requested_status in (SubscriptionStatus.QUOTATION, SubscriptionStatus.DRAFT, SubscriptionStatus.ACTIVE):
        initial_data["status"] = requested_status

    if request.method == "POST":
        form = SubscriptionForm(request.POST)
        if form.is_valid():
            sub = form.save()
            messages.success(request, f"Subscription '{sub.subscription_number}' created successfully.")
            return redirect(reverse("subscriptions:subscription_detail", kwargs={"pk": sub.pk}))
    else:
        form = SubscriptionForm(initial=initial_data)

    return render(
        request,
        "subscriptions/form.html",
        {
            "form": form,
            "object": None,
        },
    )


@staff_or_admin_required
def subscription_edit_view(request, pk):
    """Staff/admin view to update subscription agreement parameters."""
    sub = get_object_or_404(Subscription, pk=pk)

    if request.method == "POST":
        form = SubscriptionForm(request.POST, instance=sub)
        if form.is_valid():
            sub = form.save()
            messages.success(request, f"Subscription '{sub.subscription_number}' updated successfully.")
            return redirect(reverse("subscriptions:subscription_detail", kwargs={"pk": sub.pk}))
    else:
        form = SubscriptionForm(instance=sub)

    return render(
        request,
        "subscriptions/form.html",
        {
            "form": form,
            "object": sub,
        },
    )


@staff_or_admin_required
@require_POST
def subscription_confirm_view(request, pk):
    """Transitions quotation or draft subscription to ACTIVE."""
    sub = get_object_or_404(Subscription, pk=pk)
    try:
        activate_subscription(sub)
        messages.success(request, f"Subscription '{sub.subscription_number}' is now ACTIVE.")
    except Exception as exc:
        messages.error(request, f"Cannot activate subscription: {exc}")
    return redirect(reverse("subscriptions:subscription_detail", kwargs={"pk": sub.pk}))


@staff_or_admin_required
@require_POST
def subscription_pause_view(request, pk):
    """Pauses an active subscription."""
    sub = get_object_or_404(Subscription, pk=pk)
    try:
        pause_subscription(sub)
        messages.success(request, f"Subscription '{sub.subscription_number}' has been PAUSED.")
    except Exception as exc:
        messages.error(request, f"Cannot pause subscription: {exc}")
    return redirect(reverse("subscriptions:subscription_detail", kwargs={"pk": sub.pk}))


@staff_or_admin_required
@require_POST
def subscription_cancel_view(request, pk):
    """Cancels a subscription."""
    sub = get_object_or_404(Subscription, pk=pk)
    try:
        cancel_subscription(sub, immediate=True)
        messages.success(request, f"Subscription '{sub.subscription_number}' has been CANCELLED.")
    except Exception as exc:
        messages.error(request, f"Cannot cancel subscription: {exc}")
    return redirect(reverse("subscriptions:subscription_detail", kwargs={"pk": sub.pk}))
