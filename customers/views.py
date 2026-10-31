from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST
from accounts.permissions import staff_or_admin_required
from .forms import CustomerFilterForm, CustomerForm
from . import services


@login_required
def customer_list_view(request):
    """
    Paginated customer list with live search and filtering.
    Supports HTMX partial rendering for dynamic tables.
    """
    filter_form = CustomerFilterForm(request.GET)
    customers_qs = services.get_customers_for_user(request.user)

    if filter_form.is_valid():
        customers_qs = services.search_and_filter_customers(
            queryset=customers_qs,
            query=filter_form.cleaned_data.get("q"),
            status=filter_form.cleaned_data.get("status"),
            city=filter_form.cleaned_data.get("city"),
            state=filter_form.cleaned_data.get("state"),
            country=filter_form.cleaned_data.get("country"),
        )

    # 15 customers per page
    paginator = Paginator(customers_qs, 15)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    # Preserve query string excluding page for pagination links
    params = request.GET.copy()
    params.pop("page", None)
    preserved_query = params.urlencode()

    context = {
        "page_obj": page_obj,
        "filter_form": filter_form,
        "preserved_query": preserved_query,
        "total_count": paginator.count,
    }

    # HTMX request detection: return table partial only
    is_htmx = request.headers.get("HX-Request") == "true" or request.headers.get("hx-request") == "true"
    if is_htmx:
        return render(request, "customers/_customer_table.html", context)

    return render(request, "customers/customer_list.html", context)


@staff_or_admin_required
def customer_create_view(request):
    """
    Customer creation view for staff and administrators.
    """
    if request.method == "POST":
        form = CustomerForm(request.POST, user=request.user)
        if form.is_valid():
            customer = form.save()
            messages.success(request, f"Customer '{customer.name}' has been created.")
            return redirect("customers:detail", pk=customer.pk)
    else:
        form = CustomerForm(user=request.user)

    return render(request, "customers/customer_form.html", {"form": form, "is_create": True})


@login_required
def customer_detail_view(request, pk: int):
    """
    Customer profile view with lazy integration slots for Subscriptions,
    Invoices, and Payments.
    """
    customer = services.get_customer_for_user_or_404(request.user, pk)

    context = {
        "customer": customer,
        "subscriptions": services.get_customer_subscriptions(customer),
        "invoices": services.get_customer_invoices(customer),
        "payments": services.get_customer_payments(customer),
    }
    return render(request, "customers/customer_detail.html", context)


@login_required
def customer_edit_view(request, pk: int):
    """
    Customer update view.
    Staff/Admin can edit all fields; Customers can edit only their own contact/billing fields.
    """
    customer = services.get_customer_for_user_or_404(request.user, pk)

    if request.method == "POST":
        form = CustomerForm(request.POST, instance=customer, user=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, f"Customer profile for '{customer.name}' updated.")
            return redirect("customers:detail", pk=customer.pk)
    else:
        form = CustomerForm(instance=customer, user=request.user)

    return render(
        request,
        "customers/customer_form.html",
        {"form": form, "customer": customer, "is_create": False},
    )


@staff_or_admin_required
@require_POST
def customer_status_toggle_view(request, pk: int):
    """
    Toggle customer active/inactive status (Admin/Staff only).
    """
    customer = services.get_customer_for_user_or_404(request.user, pk)
    new_status = not customer.is_active
    services.set_customer_status(customer, new_status)

    status_label = "activated" if new_status else "deactivated"
    messages.success(request, f"Customer '{customer.name}' was successfully {status_label}.")
    return redirect("customers:detail", pk=customer.pk)
