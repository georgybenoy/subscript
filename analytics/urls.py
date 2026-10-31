from django.urls import path
from . import views

app_name = "analytics"

urlpatterns = [
    path("", views.analytics_dashboard_view, name="dashboard"),
    path("data/", views.analytics_data_json_view, name="data"),
]
