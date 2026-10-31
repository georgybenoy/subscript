from django.contrib import admin
from .models import Discount


@admin.register(Discount)
class DiscountAdmin(admin.ModelAdmin):
    list_display = (
        "code",
        "discount_type",
        "amount",
        "is_active",
        "valid_from",
        "valid_until",
        "redemption_progress",
        "created_at",
    )
    list_filter = ("discount_type", "is_active", "valid_from", "valid_until")
    search_fields = ("code",)
    ordering = ("-created_at",)

    @admin.display(description="Redemptions")
    def redemption_progress(self, obj):
        if obj.max_redemptions is not None:
            return f"{obj.times_redeemed} / {obj.max_redemptions}"
        return f"{obj.times_redeemed} / ∞ (Unlimited)"
