"""
Role-Based Access Control (RBAC) Permissions Module.

Single source of truth for authorization across Subscript platform.

Permission Matrix:
--------------------------------------------------------------------------------
Role       | Scope & Capabilities
--------------------------------------------------------------------------------
ADMIN      | Complete administrative access:
           | - Manage all users and staff creation/deactivation
           | - Full access to all platform apps (products, plans, invoices, etc.)
           | - System configuration & financial oversight
STAFF      | Operational access:
           | - Operational day-to-day access (customers, plans, subscriptions,
           |   invoices, analytics)
           | - NO user/staff creation or role/account administration
CUSTOMER   | Restricted client access:
           | - View and manage own customer profile, subscriptions, and invoices
           | - NO administrative or operational staff interfaces
--------------------------------------------------------------------------------
Rules:
- Unauthenticated or inactive users are redirected to LOGIN_URL with ?next=
- Authenticated users with insufficient roles receive HTTP 403 (PermissionDenied)
"""

from functools import wraps
from django.conf import settings
from django.contrib.auth.mixins import AccessMixin
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.urls import NoReverseMatch, reverse
from .models import User


def _is_authenticated_and_active(user) -> bool:
    """Helper to verify if a user is both authenticated and active."""
    return bool(user and user.is_authenticated and user.is_active)


def get_login_redirect_url(next_path: str = None) -> str:
    """Safely resolves LOGIN_URL and appends next path if provided."""
    try:
        base_url = reverse(settings.LOGIN_URL)
    except NoReverseMatch:
        base_url = str(settings.LOGIN_URL)

    if next_path:
        return f"{base_url}?next={next_path}"
    return base_url


def role_required(*roles):
    """
    Decorator requiring the authenticated user to be active and have
    one of the specified roles.
    - If unauthenticated or inactive: redirects to LOGIN_URL.
    - If authenticated but incorrect role: raises PermissionDenied (HTTP 403).
    """
    allowed_roles = set(roles)

    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            if not _is_authenticated_and_active(request.user):
                path = request.get_full_path()
                return redirect(get_login_redirect_url(path))

            if request.user.role not in allowed_roles:
                raise PermissionDenied("You do not have permission to access this resource.")

            return view_func(request, *args, **kwargs)

        return _wrapped_view

    return decorator


def admin_required(view_func):
    """Decorator requiring ADMIN role."""
    return role_required(User.Role.ADMIN)(view_func)


def staff_or_admin_required(view_func):
    """Decorator requiring either STAFF or ADMIN role."""
    return role_required(User.Role.STAFF, User.Role.ADMIN)(view_func)


def customer_required(view_func):
    """Decorator requiring CUSTOMER role."""
    return role_required(User.Role.CUSTOMER)(view_func)


class RoleRequiredMixin(AccessMixin):
    """
    CBV mixin verifying that the user is authenticated, active,
    and has one of the allowed roles.
    """

    allowed_roles = ()

    def get_allowed_roles(self):
        return tuple(self.allowed_roles)

    def dispatch(self, request, *args, **kwargs):
        if not _is_authenticated_and_active(request.user):
            return redirect(get_login_redirect_url(request.get_full_path()))

        allowed = self.get_allowed_roles()
        if allowed and request.user.role not in allowed:
            raise PermissionDenied("You do not have permission to access this resource.")

        return super().dispatch(request, *args, **kwargs)


class AdminRequiredMixin(RoleRequiredMixin):
    """CBV mixin requiring ADMIN role."""

    allowed_roles = (User.Role.ADMIN,)


class StaffOrAdminRequiredMixin(RoleRequiredMixin):
    """CBV mixin requiring either STAFF or ADMIN role."""

    allowed_roles = (User.Role.STAFF, User.Role.ADMIN)
