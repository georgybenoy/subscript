from django.contrib import messages
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from accounts.permissions import staff_or_admin_required
from .forms import DiscountFilterForm, DiscountForm
from .models import Discount
from .services import search_and_filter_discounts


@staff_or_admin_required
def discount_list_view(request):
    """Staff/admin view listing all promotional discount rules with pagination and filters."""
    queryset = Discount.objects.all()
    filter_form = DiscountFilterForm(request.GET)

    q = request.GET.get("q")
    discount_type = request.GET.get("discount_type")
    status = request.GET.get("status")

    queryset = search_and_filter_discounts(
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
