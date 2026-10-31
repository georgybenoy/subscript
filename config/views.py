from django.http import HttpResponse


def dashboard_view(request):
    """
    Temporary simple dashboard view.
    To be styled/expanded by Member 2 with Bootstrap 5 / HTMX templates.
    """
    return HttpResponse(
        "<h1>Subscript Dashboard</h1>"
        "<p>Subscription Management & Recurring Billing Platform</p>"
        "<ul>"
        '<li><a href="/accounts/login/">Login</a></li>'
        '<li><a href="/customers/">Customers</a></li>'
        '<li><a href="/admin/">Admin</a></li>'
        "</ul>"
    )
