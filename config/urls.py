"""
URL configuration for Subscript project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
"""

from django.contrib import admin
from django.http import HttpResponse
from django.urls import include, path
from . import views

urlpatterns = [
    # Administration
    path("admin/", admin.site.urls),

    # Favicon endpoint
    path("favicon.ico", lambda request: HttpResponse(b"", content_type="image/x-icon")),

    # Dashboard root
    path("", views.dashboard_view, name="dashboard"),

    # Accounts & Authentication (Owned by Backend Lead)
    path("accounts/", include("accounts.urls")),

    # Customers (Owned by Backend Lead)
    path("customers/", include("customers.urls")),

    # Products & Plans (Member 3)
    path("products/", include("products.urls")),

    # Subscriptions (Member 3)
    path("subscriptions/", include("subscriptions.urls")),

    # Discounts (Member 3)
    path("discounts/", include("discounts.urls")),

    # Billing & Invoices (Member 4 - billing/invoices/)
    path("billing/", include("billing.urls")),

    # Payments (Member 4)
    path("payments/", include("payments.urls")),

    # Analytics & Reports (Member 4)
    path("analytics/", include("analytics.urls")),
]
