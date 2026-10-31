from django.urls import path
from . import views

app_name = "discounts"

urlpatterns = [
    path("", views.discount_list_view, name="discount_list"),
    path("create/", views.discount_create_view, name="discount_create"),
    path("<int:pk>/edit/", views.discount_edit_view, name="discount_edit"),
]
