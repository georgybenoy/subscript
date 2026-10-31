from django.core.exceptions import ValidationError
from django.db import transaction
from customers.services import create_customer_for_user
from .models import User


@transaction.atomic
def register_customer(email: str, password: str, first_name: str = "", last_name: str = "") -> User:
    """
    Registers a new Customer user and automatically provisions their Customer profile.
    Role is ALWAYS forced to CUSTOMER.
    """
    email_clean = email.strip().lower()

    if User.objects.filter(email__iexact=email_clean).exists():
        raise ValidationError("A user with this email address already exists.")

    user = User.objects.create_user(
        email=email_clean,
        password=password,
        first_name=first_name.strip(),
        last_name=last_name.strip(),
        role=User.Role.CUSTOMER,
        is_staff=False,
        is_superuser=False,
    )

    # Provision customer profile via customers.services
    create_customer_for_user(user)

    return user


def update_user_profile(user: User, first_name: str, last_name: str) -> User:
    """
    Updates basic profile attributes (first_name, last_name) for a user.
    Role and email are immutable via profile update.
    """
    user.first_name = first_name.strip()
    user.last_name = last_name.strip()
    user.save(update_fields=["first_name", "last_name", "updated_at"])

    # Synchronize linked customer name if profile exists
    if hasattr(user, "customer_profile") and user.customer_profile:
        full_name = f"{user.first_name} {user.last_name}".strip() or user.username
        if full_name:
            user.customer_profile.name = full_name
            user.customer_profile.save(update_fields=["name", "updated_at"])

    return user
