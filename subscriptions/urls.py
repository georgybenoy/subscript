from django.urls import path
from . import views

app_name = "subscriptions"

urlpatterns = [
    path("", views.subscription_list_view, name="subscription_list"),
    path("create/", views.subscription_create_view, name="subscription_create"),
    path("<int:pk>/", views.subscription_detail_view, name="subscription_detail"),
    path("<int:pk>/edit/", views.subscription_edit_view, name="subscription_edit"),
    path("<int:pk>/confirm/", views.subscription_confirm_view, name="subscription_confirm"),
    path("<int:pk>/pause/", views.subscription_pause_view, name="subscription_pause"),
    path("<int:pk>/cancel/", views.subscription_cancel_view, name="subscription_cancel"),
]
