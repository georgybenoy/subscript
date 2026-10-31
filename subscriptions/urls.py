from django.urls import path
from . import views

app_name = "subscriptions"

urlpatterns = [
    path("", views.subscription_list_view, name="list"),
    path("<int:pk>/", views.subscription_detail_view, name="detail"),
    path("<int:pk>/pause/", views.subscription_pause_view, name="pause"),
    path("<int:pk>/resume/", views.subscription_resume_view, name="resume"),
    path("<int:pk>/cancel/", views.subscription_cancel_view, name="cancel"),
]
