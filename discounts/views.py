from decimal import Decimal
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_http_methods
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
