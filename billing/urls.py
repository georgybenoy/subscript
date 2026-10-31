from django.urls import path
from . import views

app_name = "billing"

urlpatterns = [
    # Directory & Detail
    path("", views.invoice_list_view, name="invoice_list"),
    path("invoices/", views.invoice_list_view, name="invoice_list_invoices"),
    path("<int:pk>/", views.invoice_detail_view, name="invoice_detail"),
    path("invoices/<int:pk>/", views.invoice_detail_view, name="invoice_detail_invoices"),

    # Actions (POST-only)
    path("<int:pk>/confirm/", views.confirm_invoice_view, name="invoice_confirm"),
    path("<int:pk>/cancel/", views.cancel_invoice_view, name="invoice_cancel"),

    # PDF Export
    path("<int:pk>/pdf/", views.invoice_pdf_view, name="invoice_pdf"),
    path("invoices/<int:pk>/pdf/", views.invoice_pdf_view, name="invoice_pdf_alias"),
]
