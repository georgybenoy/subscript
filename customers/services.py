from typing import Optional
from django.apps import apps
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Q, QuerySet
from django.http import Http404
from .models import Customer

User = get_user_model()


def get_customers_for_user(user) -> QuerySet[Customer]:
    """
    Returns queryset of customers accessible by the given user.
    - Admin & Staff: full access to all customer records.
    - Customer role: restricted to their own linked Customer record.
    - Inactive / unauthenticated: empty queryset.
    """
    if not (user and user.is_authenticated and user.is_active):
        return Customer.objects.none()

    if getattr(user, "is_admin_role", False) or getattr(user, "is_staff_role", False):
        return Customer.objects.all()

    if getattr(user, "is_customer_role", False):
        return Customer.objects.filter(user=user)

    return Customer.objects.none()


def get_customer_for_user_or_404(user, pk: int) -> Customer:
    """
    Object-level access controller preventing Insecure Direct Object Reference (IDOR).
    Raises Http404 if the customer does not exist or the user has no access.
    """
    queryset = get_customers_for_user(user)
    try:
        return queryset.get(pk=pk)
    except Customer.DoesNotExist:
        raise Http404("Customer not found or access denied.")


def search_and_filter_customers(
    queryset: QuerySet[Customer],
    query: Optional[str] = None,
    status: Optional[str] = None,
    city: Optional[str] = None,
    state: Optional[str] = None,
    country: Optional[str] = None,
) -> QuerySet[Customer]:
    """
    Applies multi-field search and filters to a Customer queryset.
    """
    if query:
        q = query.strip()
        queryset = queryset.filter(
            Q(name__icontains=q)
            | Q(company_name__icontains=q)
            | Q(email__icontains=q)
            | Q(phone__icontains=q)
            | Q(tax_id__icontains=q)
            | Q(city__icontains=q)
        )

    if status:
        status_clean = str(status).strip().lower()
        if status_clean in ("active", "true", "1"):
            queryset = queryset.filter(is_active=True)
        elif status_clean in ("inactive", "false", "0"):
            queryset = queryset.filter(is_active=False)

    if city and city.strip():
        queryset = queryset.filter(city__icontains=city.strip())

    if state and state.strip():
        queryset = queryset.filter(state__icontains=state.strip())

    if country and country.strip():
        queryset = queryset.filter(country__icontains=country.strip())

    return queryset


def create_customer(data: dict, created_by: Optional[User] = None) -> Customer:
    """
    Creates a new Customer record from validated data dictionary.
    """
    clean_data = {k: v.strip() if isinstance(v, str) else v for k, v in data.items()}
    customer = Customer.objects.create(**clean_data)
    return customer


def create_customer_for_user(user: User, **extra_fields) -> Customer:
    """
    Provisions a Customer profile automatically for a registered user.
    """
    name = f"{user.first_name} {user.last_name}".strip()
    if not name:
        name = user.username or user.email.split("@")[0]

    defaults = {
        "name": name,
        "email": user.email,
        "is_active": True,
    }
    defaults.update(extra_fields)

    customer, _created = Customer.objects.get_or_create(
        user=user,
        defaults=defaults,
    )
    return customer


def update_customer(customer: Customer, data: dict) -> Customer:
    """
    Updates an existing Customer with cleaned data.
    """
    for field, value in data.items():
        if hasattr(customer, field):
            setattr(customer, field, value.strip() if isinstance(value, str) else value)
    customer.save()
    return customer


def set_customer_status(customer: Customer, is_active: bool) -> Customer:
    """
    Activates or deactivates a customer.
    """
    customer.is_active = bool(is_active)
    customer.save(update_fields=["is_active", "updated_at"])
    return customer


def link_customer_to_user(customer: Customer, user: User) -> Customer:
    """
    Links a customer to a User account (Admin/Staff only).
    Validates that user has CUSTOMER role and is not already linked.
    """
    if not user.is_customer_role:
        raise ValidationError("Only accounts with role 'CUSTOMER' can be linked to a customer profile.")

    existing_profile = getattr(user, "customer_profile", None)
    if existing_profile and existing_profile.pk != customer.pk:
        raise ValidationError(f"This user is already linked to customer: {existing_profile.name}")

    customer.user = user
    customer.save(update_fields=["user", "updated_at"])
    return customer


def unlink_customer_user(customer: Customer) -> Customer:
    """
    Removes user account association from customer.
    """
    customer.user = None
    customer.save(update_fields=["user", "updated_at"])
    return customer


def get_current_customer(user) -> Optional[Customer]:
    """
    Returns the linked Customer profile for an authenticated user, or None.
    """
    if not (user and user.is_authenticated and user.is_active):
        return None
    return getattr(user, "customer_profile", None)


def scope_queryset_for_user(qs: QuerySet, user, customer_lookup: str = "customer__user") -> QuerySet:
    """
    Reusable queryset scoping for teammate applications exposing customer financial data.
    - Admin & Staff: full access (returns qs.all())
    - Customer role: strictly scoped to own user (returns qs.filter(**{customer_lookup: user}))
    - Unauthenticated / Inactive / Unknown role: returns qs.none()

    Teammate usage conventions:
    - subscriptions -> scope_queryset_for_user(Subscription.objects.all(), user, "customer__user")
    - invoices      -> scope_queryset_for_user(Invoice.objects.all(), user, "customer__user")
    - payments      -> scope_queryset_for_user(Payment.objects.all(), user, "customer__user")
    """
    if not (user and user.is_authenticated and user.is_active):
        return qs.none()

    if getattr(user, "is_admin_role", False) or getattr(user, "is_staff_role", False):
        return qs.all()

    if getattr(user, "is_customer_role", False):
        return qs.filter(**{customer_lookup: user})

    return qs.none()



# ==============================================================================
# INTEGRATION HELPERS (LAZY LOADING FOR TEAMMATES' APPS)
# ==============================================================================
def get_customer_subscriptions(customer: Customer):
    """
    Retrieves subscriptions for a customer if Member 3's subscriptions app is active.
    Gracefully falls back to empty list if unmigrated or uninitialized.
    """
    try:
        Subscription = apps.get_model("subscriptions", "Subscription")
        return Subscription.objects.filter(customer=customer)
    except (LookupError, Exception):
        return []


def get_customer_invoices(customer: Customer):
    """
    Retrieves invoices for a customer if Member 4's billing app is active.
    Gracefully falls back to empty list if unmigrated or uninitialized.
    """
    try:
        Invoice = apps.get_model("billing", "Invoice")
        return Invoice.objects.filter(customer=customer)
    except (LookupError, Exception):
        return []


def get_customer_payments(customer: Customer):
    """
    Retrieves payments for a customer if Member 4's payments app is active.
    Gracefully falls back to empty list if unmigrated or uninitialized.
    """
    try:
        Payment = apps.get_model("payments", "Payment")
        return Payment.objects.filter(customer=customer)
    except (LookupError, Exception):
        return []
