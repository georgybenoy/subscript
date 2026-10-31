import logging
from django.core.cache import cache
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from customers.services import create_customer_for_user
from .models import User

logger = logging.getLogger("accounts")

MAX_LOGIN_FAILURES = 5
LOCKOUT_TIME_SECONDS = 300  # 5 minutes


# ==============================================================================
# LOGIN THROTTLING & SECURITY HELPERS
# ==============================================================================
def get_client_ip(request) -> str:
    """Extract client IP address from HTTP request."""
    if not request:
        return "127.0.0.1"
    x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded_for:
        return x_forwarded_for.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "127.0.0.1")


def get_throttle_cache_keys(ip: str, email: str) -> tuple[str, str]:
    clean_email = email.strip().lower()
    fail_key = f"login_fail_count:{ip}:{clean_email}"
    lock_key = f"login_locked:{ip}:{clean_email}"
    return fail_key, lock_key


def is_login_throttled(ip: str, email: str) -> bool:
    """Check if login is currently locked due to too many failed attempts."""
    _, lock_key = get_throttle_cache_keys(ip, email)
    return bool(cache.get(lock_key))


def record_failed_login(ip: str, email: str) -> int:
    """
    Increments failed login attempts for this IP + email pair.
    Locks login for 5 minutes when failures reach MAX_LOGIN_FAILURES.
    Returns current failure count.
    """
    fail_key, lock_key = get_throttle_cache_keys(ip, email)
    count = cache.get(fail_key, 0) + 1
    cache.set(fail_key, count, timeout=LOCKOUT_TIME_SECONDS)

    logger.warning(
        f"Failed login attempt ({count}/{MAX_LOGIN_FAILURES}) for email '{email}' from IP {ip}"
    )

    if count >= MAX_LOGIN_FAILURES:
        cache.set(lock_key, True, timeout=LOCKOUT_TIME_SECONDS)
        logger.warning(
            f"Login lockout triggered (5 minutes) for email '{email}' from IP {ip}"
        )

    return count


def reset_failed_logins(ip: str, email: str):
    """Resets failed login count and lockout status upon successful authentication."""
    fail_key, lock_key = get_throttle_cache_keys(ip, email)
    cache.delete(fail_key)
    cache.delete(lock_key)



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


@transaction.atomic
def create_staff_user(
    acting_admin: User,
    email: str,
    password: str,
    first_name: str = "",
    last_name: str = "",
) -> User:
    """
    Creates a new STAFF user. Can only be invoked by an active ADMIN user.
    Role is ALWAYS forced to STAFF.
    """
    if not (acting_admin and acting_admin.is_authenticated and acting_admin.is_admin_role):
        raise PermissionDenied("Only administrators can create staff users.")

    email_clean = email.strip().lower()

    if User.objects.filter(email__iexact=email_clean).exists():
        raise ValidationError("A user with this email address already exists.")

    user = User.objects.create_user(
        email=email_clean,
        password=password,
        first_name=first_name.strip(),
        last_name=last_name.strip(),
        role=User.Role.STAFF,
        is_staff=True,
        is_superuser=False,
    )
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


def toggle_user_active_status(acting_admin: User, target_user_id: int) -> User:
    """
    Toggles is_active status of target user.
    Admin cannot deactivate themselves.
    """
    if not (acting_admin and acting_admin.is_authenticated and acting_admin.is_admin_role):
        raise PermissionDenied("Only administrators can modify user active status.")

    try:
        target_user = User.objects.get(pk=target_user_id)
    except User.DoesNotExist:
        raise ValidationError("User not found.")

    if target_user.pk == acting_admin.pk:
        raise ValidationError("Administrators cannot deactivate their own account.")

    target_user.is_active = not target_user.is_active
    target_user.save(update_fields=["is_active", "updated_at"])
    return target_user
