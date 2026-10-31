from django.urls import path
from . import views

app_name = "discounts"

urlpatterns = [
    path("apply/", views.apply_discount_view, name="apply"),
]
