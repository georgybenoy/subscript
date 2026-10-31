"""
Views for the Products, Variants, and Plans domain.
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from accounts.permissions import staff_or_admin_required

from .forms import ProductFilterForm, ProductForm, ProductVariantForm, PlanForm
from .models import Product, ProductVariant, Plan
from . import services


def product_list_view(request):
    """
    Catalog directory with search and filters.
    Staff/Admin see all products; Customers & Anonymous see active products only.
    """
    base_qs = services.get_products_for_user(request.user)

    filter_form = ProductFilterForm(request.GET)
    query = request.GET.get("q")
    product_type = request.GET.get("type")
    status = request.GET.get("status")

    products_qs = services.search_and_filter_products(
        base_qs,
        query=query,
        product_type=product_type,
        status=status,
    )

    paginator = Paginator(products_qs, 15)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    context = {
        "products": page_obj.object_list,
        "page_obj": page_obj,
        "filter_form": filter_form,
    }
    return render(request, "products/list.html", context)


def product_detail_view(request, pk: int):
    """
    Detailed product view showing associated variants and recurring billing plans.
    """
    product = services.get_product_for_user_or_404(pk, user=request.user)
    context = {
        "product": product,
    }
    return render(request, "products/detail.html", context)


@login_required
@staff_or_admin_required
def product_create_view(request):
    """Creates a new product offering (Staff/Admin only)."""
    if request.method == "POST":
        form = ProductForm(request.POST)
        if form.is_valid():
            product = form.save()
            messages.success(request, f"Product '{product.name}' was created successfully.")
            return redirect("products:detail", pk=product.pk)
    else:
        form = ProductForm()

    return render(request, "products/form.html", {"form": form, "object": None})


@login_required
@staff_or_admin_required
def product_edit_view(request, pk: int):
    """Updates an existing product (Staff/Admin only)."""
    product = get_object_or_404(Product, pk=pk)
    if request.method == "POST":
        form = ProductForm(request.POST, instance=product)
        if form.is_valid():
            product = form.save()
            messages.success(request, f"Product '{product.name}' was updated successfully.")
            return redirect("products:detail", pk=product.pk)
    else:
        form = ProductForm(instance=product)

    return render(request, "products/form.html", {"form": form, "object": product})


def plan_list_view(request):
    """Lists subscription plans."""
    plans = services.get_plans_for_user(request.user)
    return render(request, "products/plan_list.html", {"plans": plans})


@login_required
@staff_or_admin_required
def plan_create_view(request):
    """Creates a subscription pricing plan (Staff/Admin only)."""
    initial = {}
    product_id = request.GET.get("product")
    if product_id:
        initial["product"] = product_id

    if request.method == "POST":
        form = PlanForm(request.POST)
        if form.is_valid():
            plan = form.save()
            messages.success(request, f"Billing Plan '{plan.name}' created.")
            return redirect("products:detail", pk=plan.product.pk)
    else:
        form = PlanForm(initial=initial)

    return render(request, "products/plan_form.html", {"form": form, "object": None})


@login_required
@staff_or_admin_required
def plan_edit_view(request, pk: int):
    """Updates a subscription pricing plan (Staff/Admin only)."""
    plan = get_object_or_404(Plan, pk=pk)
    if request.method == "POST":
        form = PlanForm(request.POST, instance=plan)
        if form.is_valid():
            plan = form.save()
            messages.success(request, f"Billing Plan '{plan.name}' updated.")
            return redirect("products:detail", pk=plan.product.pk)
    else:
        form = PlanForm(instance=plan)

    return render(request, "products/plan_form.html", {"form": form, "object": plan})


@login_required
@staff_or_admin_required
def variant_create_view(request):
    """Creates a variant for a product (Staff/Admin only)."""
    initial = {}
    product_id = request.GET.get("product")
    if product_id:
        initial["product"] = product_id

    if request.method == "POST":
        form = ProductVariantForm(request.POST)
        if form.is_valid():
            variant = form.save()
            messages.success(request, f"Variant '{variant.name}' created.")
            return redirect("products:detail", pk=variant.product.pk)
    else:
        form = ProductVariantForm(initial=initial)

    return render(request, "products/variant_form.html", {"form": form, "object": None})
