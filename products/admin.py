from django.contrib import admin
from .models import Plan, Product, ProductVariant


class ProductVariantInline(admin.TabularInline):
    model = ProductVariant
    extra = 0
    fields = ("name", "sku", "price", "is_active")


class PlanInline(admin.TabularInline):
    model = Plan
    extra = 0
    fields = ("name", "code", "billing_interval", "price", "currency", "trial_days", "is_active")


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("name", "is_active", "variant_count", "plan_count", "created_at", "updated_at")
    list_filter = ("is_active", "created_at")
    search_fields = ("name", "description")
    inlines = [ProductVariantInline, PlanInline]
    ordering = ("-created_at",)

    @admin.display(description="Variants")
    def variant_count(self, obj):
        return obj.variants.count()

    @admin.display(description="Plans")
    def plan_count(self, obj):
        return obj.plans.count()


@admin.register(ProductVariant)
class ProductVariantAdmin(admin.ModelAdmin):
    list_display = ("name", "sku", "product", "price", "is_active", "created_at")
    list_filter = ("is_active", "product", "created_at")
    search_fields = ("name", "sku", "product__name")
    ordering = ("-created_at",)


@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "code",
        "product",
        "billing_interval",
        "price",
        "currency",
        "trial_days",
        "is_active",
        "created_at",
    )
    list_filter = ("billing_interval", "is_active", "currency", "product", "created_at")
    search_fields = ("name", "code", "product__name")
    ordering = ("-created_at",)
