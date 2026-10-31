from .models import Customer


def create_customer_for_user(user, **extra_fields) -> Customer:
    """
    Creates and links a Customer profile for the given User account.
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
