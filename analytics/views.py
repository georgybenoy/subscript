"""
Views for Financial Analytics and Reporting.

Handles:
- Executive HTML dashboard view (/analytics/)
- JSON API endpoint for Chart.js interactive rendering (/analytics/data/)
Restricted to Staff and Admin users.
"""

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render
from accounts.permissions import staff_or_admin_required
from .services import get_dashboard_context


@login_required
@staff_or_admin_required
def analytics_dashboard_view(request: HttpRequest) -> HttpResponse:
    """
    Renders executive SaaS financial dashboard with Chart.js visualizations.
    Restricted to Staff and Superuser administrators.
    """
    date_from = request.GET.get("date_from")
    date_to = request.GET.get("date_to")
    group_by = request.GET.get("group_by", "month")

    context = get_dashboard_context(
        date_from=date_from,
        date_to=date_to,
        group_by=group_by,
    )
    # Provide formatted currency values for Member 2's KPI cards
    context.update({
        "collections": f"INR {context['collected_revenue']}",
        "overdue_amount": f"INR {context['outstanding_balance']}",
    })
    return render(request, "analytics/index.html", context)


@login_required
@staff_or_admin_required
def analytics_data_json_view(request: HttpRequest) -> JsonResponse:
    """
    REST JSON endpoint returning get_dashboard_context directly for Chart.js.
    Restricted to Staff and Superuser administrators.
    """
    date_from = request.GET.get("date_from")
    date_to = request.GET.get("date_to")
    group_by = request.GET.get("group_by", "month")

    context = get_dashboard_context(
        date_from=date_from,
        date_to=date_to,
        group_by=group_by,
    )
    return JsonResponse(context)
