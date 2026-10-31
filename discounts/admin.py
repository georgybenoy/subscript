from django.contrib import admin
from .models import Discount


@admin.register(Discount)
class DiscountAdmin(admin.ModelAdmin):
    list_display = (
        "code",
        "name",
        "discount_type",
        "amount",
        "start_date",
        "end_date",
        "times_used",
        "usage_limit",
        "is_active",
    )
    list_filter = ("discount_type", "is_active", "start_date", "end_date")
    search_fields = ("code", "name")
    readonly_fields = ("created_at", "updated_at", "times_used")
