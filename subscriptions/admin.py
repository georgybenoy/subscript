from django.contrib import admin
from .models import Subscription, SubscriptionItem


class SubscriptionItemInline(admin.TabularInline):
    model = SubscriptionItem
    extra = 1
    fields = ("product", "variant", "description", "quantity", "unit_price", "tax_rate")


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = (
        "subscription_number",
        "customer",
        "plan",
        "status",
        "start_date",
        "expiry_date",
        "next_billing_date",
        "payment_terms",
    )
    list_filter = ("status", "plan", "start_date", "next_billing_date")
    search_fields = (
        "subscription_number",
        "customer__name",
        "customer__email",
        "plan__name",
    )
    inlines = [SubscriptionItemInline]
    readonly_fields = ("created_at", "updated_at")


@admin.register(SubscriptionItem)
class SubscriptionItemAdmin(admin.ModelAdmin):
    list_display = (
        "subscription",
        "product",
        "variant",
        "quantity",
        "unit_price",
        "tax_rate",
    )
    list_filter = ("product", "variant")
    search_fields = ("subscription__subscription_number", "description")
