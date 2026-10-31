from django.urls import path
from . import views

app_name = "products"

urlpatterns = [
    path("", views.product_list_view, name="list"),
    path("create/", views.product_create_view, name="create"),
    path("<int:pk>/", views.product_detail_view, name="detail"),
    path("<int:pk>/edit/", views.product_edit_view, name="edit"),
    path("plans/", views.plan_list_view, name="plan_list"),
    path("plans/create/", views.plan_create_view, name="plan_create"),
    path("plans/<int:pk>/edit/", views.plan_edit_view, name="plan_edit"),
    path("variants/create/", views.variant_create_view, name="variant_create"),
]
