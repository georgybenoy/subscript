from django.contrib import admin
from .models import Customer


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "company_name",
        "email",
        "phone",
        "country",
        "is_active",
        "created_at",
    )
    list_filter = ("is_active", "country", "created_at")
    search_fields = ("name", "company_name", "email", "phone", "tax_id")
    readonly_fields = ("created_at", "updated_at")
    raw_id_fields = ("user",)
