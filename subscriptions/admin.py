from django.contrib import admin
from .models import Subscription, SubscriptionItem


class SubscriptionItemInline(admin.TabularInline):
    model = SubscriptionItem
    extra = 0
    raw_id_fields = ("variant",)
    fields = ("variant", "quantity", "unit_price")


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "customer",
        "plan",
        "status",
        "current_period_start",
        "current_period_end",
        "cancel_at_period_end",
        "subtotal_display",
        "total_display",
        "created_at",
    )
    list_filter = (
        "status",
        "cancel_at_period_end",
        "plan__billing_interval",
        "created_at",
    )
    search_fields = (
        "customer__name",
        "customer__email",
        "plan__name",
        "plan__code",
    )
    raw_id_fields = ("customer", "plan", "discount")
    readonly_fields = ("created_at", "updated_at", "paused_at")
    inlines = [SubscriptionItemInline]
    ordering = ("-created_at",)

    @admin.display(description="Subtotal")
    def subtotal_display(self, obj):
        return f"{obj.plan.currency} {obj.get_subtotal()}"

    @admin.display(description="Total")
    def total_display(self, obj):
        return f"{obj.plan.currency} {obj.get_total()}"


@admin.register(SubscriptionItem)
class SubscriptionItemAdmin(admin.ModelAdmin):
    list_display = ("id", "subscription", "variant", "quantity", "unit_price", "amount_display")
    list_filter = ("quantity",)
    raw_id_fields = ("subscription", "variant")

    @admin.display(description="Amount")
    def amount_display(self, obj):
        return obj.get_amount()
