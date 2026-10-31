from django.urls import path
from . import views

app_name = "payments"

urlpatterns = [
    path("", views.payment_list_view, name="payment_list"),
    path("create/", views.payment_create_view, name="payment_create"),
    path("record/", views.payment_create_view, name="payment_record"),
    path("<int:pk>/", views.payment_detail_view, name="payment_detail"),
]
