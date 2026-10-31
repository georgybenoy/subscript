from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.forms import UserCreationForm, UserChangeForm
from .models import User


class SubscriptUserCreationForm(UserCreationForm):
    class Meta:
        model = User
        fields = ("email", "role")


class SubscriptUserChangeForm(UserChangeForm):
    class Meta:
        model = User
        fields = "__all__"


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    form = SubscriptUserChangeForm
    add_form = SubscriptUserCreationForm

    list_display = (
        "email",
        "username",
        "role",
        "is_staff",
        "is_superuser",
        "is_active",
        "created_at",
    )
    list_filter = ("role", "is_staff", "is_superuser", "is_active")
    search_fields = ("email", "username")
    ordering = ("-created_at",)
    readonly_fields = ("created_at", "updated_at", "last_login", "date_joined")

    fieldsets = (
        (None, {"fields": ("email", "password")}),
        (
            "Profile Information",
            {
                "fields": (
                    "username",
                    "first_name",
                    "last_name",
                    "role",
                )
            },
        ),
        (
            "Permissions & Status",
            {
                "fields": (
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                )
            },
        ),
        (
            "Important Dates",
            {
                "fields": (
                    "created_at",
                    "updated_at",
                    "last_login",
                    "date_joined",
                )
            },
        ),
    )

    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("email", "role", "password_1", "password_2"),
            },
        ),
    )
