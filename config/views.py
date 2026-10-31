from django.contrib.auth.decorators import login_required
from django.shortcuts import render


@login_required
def dashboard_view(request):
    """
    Role-aware dashboard view at root ("/").
    Shows context based strictly on user role (Admin, Staff, Customer).
    """
    context = {
        "role": request.user.role,
        "is_admin": request.user.is_admin_role,
        "is_staff": request.user.is_staff_role,
        "is_customer": request.user.is_customer_role,
    }
    return render(request, "dashboard.html", context)
