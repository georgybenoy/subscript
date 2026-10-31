from django.urls import path
from . import views

app_name = "customers"

urlpatterns = [
    path("", views.customer_list_view, name="list"),
    path("create/", views.customer_create_view, name="create"),
    path("<int:pk>/", views.customer_detail_view, name="detail"),
    path("<int:pk>/edit/", views.customer_edit_view, name="edit"),
    path("<int:pk>/status/", views.customer_status_toggle_view, name="status_toggle"),
]
