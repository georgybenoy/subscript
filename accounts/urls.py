from django.urls import path
from . import views

app_name = "accounts"

urlpatterns = [
    # Registration & Authentication
    path("register/", views.register_view, name="register"),
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),

    # Profile Management
    path("profile/", views.profile_view, name="profile"),

    # Admin Staff & User Administration
    path("staff/create/", views.staff_create_view, name="staff_create"),
    path("users/", views.user_list_view, name="user_list"),
    path("users/<int:user_id>/toggle-active/", views.user_toggle_active_view, name="user_toggle_active"),
]
