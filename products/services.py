"""
Business services for the Products, Variants, and Plans domain.
"""

from decimal import Decimal
from typing import Optional
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q, QuerySet
from django.http import Http404
from django.shortcuts import get_object_or_404

from .models import Product, ProductType, ProductVariant, Plan


def get_products_for_user(user) -> QuerySet[Product]:
    """
    Returns products accessible to the user:
    - Staff / Admin: all products (active and inactive)
    - Customer / Anonymous: active products only
    """
    if user and user.is_authenticated and (getattr(user, "is_admin_role", False) or getattr(user, "is_staff_role", False)):
        return Product.objects.all().prefetch_related("variants", "plans")
    return Product.objects.filter(is_active=True).prefetch_related("variants", "plans")


def get_plans_for_user(user) -> QuerySet[Plan]:
    """
    Returns plans accessible to the user:
    - Staff / Admin: all plans
    - Customer / Anonymous: active plans only on active products
    """
    if user and user.is_authenticated and (getattr(user, "is_admin_role", False) or getattr(user, "is_staff_role", False)):
        return Plan.objects.all().select_related("product")
    return Plan.objects.filter(is_active=True, product__is_active=True).select_related("product")


def search_and_filter_products(
    queryset: QuerySet[Product],
    query: Optional[str] = None,
    product_type: Optional[str] = None,
    status: Optional[str] = None,
) -> QuerySet[Product]:
    """
    Filters product querysets by query term, product type, and active status.
    """
    if query:
        q_clean = query.strip()
        queryset = queryset.filter(
            Q(name__icontains=q_clean)
            | Q(description__icontains=q_clean)
            | Q(variants__sku__icontains=q_clean)
            | Q(variants__name__icontains=q_clean)
        ).distinct()

    if product_type:
        queryset = queryset.filter(product_type=product_type.strip().upper())

    if status:
        stat_lower = status.strip().lower()
        if stat_lower in ("active", "1", "true"):
            queryset = queryset.filter(is_active=True)
        elif stat_lower in ("archived", "inactive", "0", "false"):
            queryset = queryset.filter(is_active=False)

    return queryset


def get_product_for_user_or_404(pk: int, user=None) -> Product:
    """
    Object-level access: customers & anonymous can only retrieve active products.
    """
    qs = get_products_for_user(user)
    try:
        return qs.get(pk=pk)
    except Product.DoesNotExist:
        raise Http404(f"Product #{pk} not found or inactive.")


@transaction.atomic
def create_product(data: dict) -> Product:
    """Creates a new product catalog offering."""
    product = Product(
        name=data.get("name", "").strip(),
        description=data.get("description", "").strip(),
        product_type=data.get("product_type", ProductType.SAAS),
        sales_price=Decimal(str(data.get("sales_price", "0.00"))),
        cost_price=Decimal(str(data.get("cost_price", "0.00"))),
        is_active=bool(data.get("is_active", True)),
    )
    product.full_clean()
    product.save()
    return product


@transaction.atomic
def update_product(product: Product, data: dict) -> Product:
    """Updates an existing product."""
    for field in ("name", "description", "product_type", "sales_price", "cost_price", "is_active"):
        if field in data:
            val = data[field]
            if field in ("sales_price", "cost_price"):
                val = Decimal(str(val))
            elif field == "name":
                val = val.strip()
            setattr(product, field, val)
    product.full_clean()
    product.save()
    return product


@transaction.atomic
def create_variant(product: Product, data: dict) -> ProductVariant:
    """Creates a product variant / SKU add-on."""
    variant = ProductVariant(
        product=product,
        name=data.get("name", "").strip(),
        sku=data.get("sku", "").strip().upper(),
        value=data.get("value", "").strip(),
        price=Decimal(str(data.get("price", product.sales_price))),
        price_adjustment=Decimal(str(data.get("price_adjustment", "0.00"))),
        is_active=bool(data.get("is_active", True)),
    )
    variant.full_clean()
    variant.save()
    return variant


@transaction.atomic
def create_plan(product: Product, data: dict) -> Plan:
    """Creates a recurring subscription pricing plan."""
    plan = Plan(
        product=product,
        name=data.get("name", "").strip(),
        code=data.get("code", "").strip().upper(),
        billing_interval=data.get("billing_interval", Plan.BillingInterval.MONTHLY),
        billing_frequency=data.get("billing_interval", Plan.BillingInterval.MONTHLY),
        price=Decimal(str(data.get("price", product.sales_price))),
        base_price=Decimal(str(data.get("base_price", data.get("price", product.sales_price)))),
        minimum_quantity=int(data.get("minimum_quantity", 1)),
        currency=data.get("currency", "INR").strip().upper(),
        trial_days=int(data.get("trial_days", 0)),
        is_active=bool(data.get("is_active", True)),
    )
    plan.full_clean()
    plan.save()
    return plan
