from decimal import Decimal
from django.contrib import messages
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods, require_POST

from accounts.permissions import staff_or_admin_required
from .forms import DiscountFilterForm, DiscountForm
from .models import Discount
from . import services


@require_http_methods(["GET", "POST"])
def apply_discount_view(request):
    """
    Validates a discount code and returns preview calculations.
    Supports both JSON responses and HTMX snippets for checkout preview workflows.
    Never increments times_redeemed (preview only).
    """
    data = request.POST if request.method == "POST" else request.GET
    code = data.get("code", "")
    subtotal_str = data.get("subtotal", "0.00")
    quantity_str = data.get("quantity", "1")

    try:
        subtotal = Decimal(str(subtotal_str).strip())
        if subtotal < Decimal("0.00"):
            subtotal = Decimal("0.00")
    except Exception:
        subtotal = Decimal("0.00")

    try:
        quantity = max(1, int(quantity_str))
    except Exception:
        quantity = 1

    is_valid, discount, message = services.validate_discount_code(code)

    if is_valid and discount:
        discount_amount = services.get_applicable_discount(
            discount=discount,
            subtotal=subtotal,
            quantity=quantity,
        )
        final_total = max(Decimal("0.00"), subtotal - discount_amount)
        payload = {
            "valid": True,
            "code": discount.code,
            "discount_type": discount.discount_type,
            "amount": str(discount.amount),
            "discount_amount": str(discount_amount),
            "subtotal": str(subtotal),
            "final_total": str(final_total),
            "message": message,
        }
    else:
        payload = {
            "valid": False,
            "code": str(code).strip().upper() if code else "",
            "discount_type": None,
            "amount": "0.00",
            "discount_amount": "0.00",
            "subtotal": str(subtotal),
            "final_total": str(subtotal),
            "message": message,
        }

    # If HTMX request and not explicitly requesting JSON, render HTML badge
    if request.headers.get("HX-Request") and not (
        request.headers.get("Accept") == "application/json"
        or request.GET.get("format") == "json"
    ):
        context = {**payload, "discount": discount}
        return render(request, "discounts/_coupon_badge.html", context)

    return JsonResponse(payload, status=200)


@staff_or_admin_required
def discount_list_view(request):
    """Staff/admin view listing all promotional discount rules with pagination and filters."""
    queryset = Discount.objects.all()
    filter_form = DiscountFilterForm(request.GET)

    q = request.GET.get("q")
    discount_type = request.GET.get("discount_type")
    status = request.GET.get("status")

    queryset = services.search_and_filter_discounts(
        queryset,
        query=q,
        discount_type=discount_type,
        status=status,
    )

    paginator = Paginator(queryset, 15)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    return render(
        request,
        "discounts/list.html",
        {
            "discounts": page_obj.object_list,
            "page_obj": page_obj,
            "filter_form": filter_form,
        },
    )


@staff_or_admin_required
def discount_create_view(request):
    """Staff/admin view to create a new discount rule."""
    if request.method == "POST":
        form = DiscountForm(request.POST)
        if form.is_valid():
            discount = form.save()
            messages.success(request, f"Discount coupon '{discount.code}' created successfully.")
            return redirect(reverse("discounts:discount_list"))
    else:
        form = DiscountForm()

    return render(
        request,
        "discounts/form.html",
        {
            "form": form,
            "object": None,
        },
    )


@staff_or_admin_required
def discount_edit_view(request, pk):
    """Staff/admin view to edit an existing discount rule."""
    discount = get_object_or_404(Discount, pk=pk)

    if request.method == "POST":
        form = DiscountForm(request.POST, instance=discount)
        if form.is_valid():
            discount = form.save()
            messages.success(request, f"Discount coupon '{discount.code}' updated successfully.")
            return redirect(reverse("discounts:discount_list"))
    else:
        form = DiscountForm(instance=discount)

    return render(
        request,
        "discounts/form.html",
        {
            "form": form,
            "object": discount,
        },
    )


@staff_or_admin_required
@require_POST
def discount_toggle_status_view(request, pk):
    """Staff/admin action to toggle a discount's active status."""
    discount = get_object_or_404(Discount, pk=pk)
    discount.is_active = not discount.is_active
    discount.save(update_fields=["is_active"])
    status_label = "activated" if discount.is_active else "deactivated"
    messages.success(request, f"Discount '{discount.code}' has been {status_label}.")
    return redirect(reverse("discounts:discount_list"))
