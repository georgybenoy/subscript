from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST
from .forms import (
    EmailAuthenticationForm,
    ProfileForm,
    RegistrationForm,
    StaffCreationForm,
)
from .models import User
from .permissions import admin_required
from . import services


def register_view(request):
    """
    Public customer registration.
    Auto-provisions Customer profile via accounts/services.py.
    """
    if request.user.is_authenticated:
        return redirect("dashboard")

    if request.method == "POST":
        form = RegistrationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            messages.success(request, "Registration successful! Welcome to Subscript.")
            return redirect("dashboard")
    else:
        form = RegistrationForm()

    return render(request, "accounts/register.html", {"form": form})


def login_view(request):
    """
    Email-based authentication.
    Validates next redirect parameter to avoid open redirects.
    """
    if request.user.is_authenticated:
        return redirect("dashboard")

    next_url = request.GET.get("next") or request.POST.get("next") or ""

    if request.method == "POST":
        form = EmailAuthenticationForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            messages.success(request, f"Welcome back, {user.first_name or user.email}!")

            if next_url and url_has_allowed_host_and_scheme(
                url=next_url,
                allowed_hosts={request.get_host()},
                require_https=request.is_secure(),
            ):
                return redirect(next_url)
            return redirect(settings.LOGIN_REDIRECT_URL)
    else:
        form = EmailAuthenticationForm(request)

    return render(request, "accounts/login.html", {"form": form, "next": next_url})


@require_POST
def logout_view(request):
    """
    Secure POST-only logout.
    """
    logout(request)
    messages.info(request, "You have been signed out.")
    return redirect(settings.LOGOUT_REDIRECT_URL)


@login_required
def profile_view(request):
    """
    User profile management.
    Allows editing first_name and last_name only.
    """
    if request.method == "POST":
        form = ProfileForm(request.POST, instance=request.user)
        if form.is_valid():
            form.save(user=request.user)
            messages.success(request, "Profile updated successfully.")
            return redirect("accounts:profile")
    else:
        form = ProfileForm(instance=request.user)

    return render(request, "accounts/profile.html", {"form": form})


@admin_required
def staff_create_view(request):
    """
    Admin-only staff provisioning view.
    """
    if request.method == "POST":
        form = StaffCreationForm(request.POST)
        if form.is_valid():
            staff_user = form.save(acting_admin=request.user)
            messages.success(request, f"Staff account provisioned for {staff_user.email}.")
            return redirect("accounts:user_list")
    else:
        form = StaffCreationForm()

    return render(request, "accounts/staff_create.html", {"form": form})


@admin_required
def user_list_view(request):
    """
    Admin-only user registry view with role breakdown and active toggle.
    """
    users = User.objects.all().order_by("-created_at")
    return render(request, "accounts/user_list.html", {"users": users})


@admin_required
@require_POST
def user_toggle_active_view(request, user_id):
    """
    Admin-only toggle for user active status.
    Prevents self-deactivation.
    """
    try:
        target_user = services.toggle_user_active_status(
            acting_admin=request.user,
            target_user_id=user_id,
        )
        status = "activated" if target_user.is_active else "deactivated"
        messages.success(request, f"User {target_user.email} was successfully {status}.")
    except (ValidationError, PermissionDenied) as exc:
        msg = exc.message if hasattr(exc, "message") else str(exc)
        messages.error(request, msg)

    return redirect("accounts:user_list")
