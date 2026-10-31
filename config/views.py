"""
Core project views for Subscript.
"""

from decimal import Decimal
from django.apps import apps
from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.shortcuts import render
from django.utils import timezone

from customers.models import Customer
from customers.services import (
    get_customer_subscriptions,
    get_customer_invoices,
    get_customer_payments,
)


@login_required
def dashboard_view(request):
    """
    Role-aware dashboard view at root ("/").
    Provides real aggregate statistics for Admin/Staff, and scoped portal data for Customers.
    Gracefully handles empty tables or missing optional apps.
    """
    user = request.user
    context = {
        "role": getattr(user, "role", "CUSTOMER"),
        "is_admin": getattr(user, "is_admin_role", False),
        "is_staff": getattr(user, "is_staff_role", False),
        "is_customer": getattr(user, "is_customer_role", True),
    }

    if user.is_customer_role:
        # Customer portal view
        customer = getattr(user, "customer_profile", None)
        if customer:
            my_subs = list(get_customer_subscriptions(customer, user=user))
            my_invs = list(get_customer_invoices(customer, user=user))
            my_pays = list(get_customer_payments(customer, user=user))

            active_subs_count = sum(1 for s in my_subs if getattr(s, "status", "") == "ACTIVE")

            # Outstanding balance from unpaid invoices
            unpaid_sum = sum(
                (getattr(inv, "total_amount", getattr(inv, "total", Decimal("0.00"))) or Decimal("0.00"))
                for inv in my_invs
                if getattr(inv, "status", "") in ("DRAFT", "OPEN", "CONFIRMED")
            )

            # Find next billing date if any active subscription has next renewal / period_end
            next_date = None
            for s in my_subs:
                end_date = getattr(s, "current_period_end", None)
                if end_date and (next_date is None or end_date < next_date):
                    next_date = end_date

            context.update({
                "customer": customer,
                "my_subscriptions": my_subs,
                "my_invoices": my_invs,
                "my_payments": my_pays,
                "active_subscriptions_count": active_subs_count,
                "outstanding_balance": f"${unpaid_sum:,.2f}",
                "next_billing_date": next_date.strftime("%b %d, %Y") if next_date else "None scheduled",
            })
        else:
            context.update({
                "customer": None,
                "my_subscriptions": [],
                "my_invoices": [],
                "my_payments": [],
                "active_subscriptions_count": 0,
                "outstanding_balance": "$0.00",
                "next_billing_date": "None scheduled",
            })
    else:
        # Admin / Staff executive view
        total_customers = Customer.objects.count()

        # Subscriptions
        active_subscriptions = 0
        recent_subscriptions = []
        try:
            Subscription = apps.get_model("subscriptions", "Subscription")
            active_subscriptions = Subscription.objects.filter(status="ACTIVE").count()
            recent_subscriptions = list(
                Subscription.objects.select_related("customer", "plan").order_by("-id")[:5]
            )
        except Exception:
            pass

        # Invoices
        outstanding_payments = Decimal("0.00")
        overdue_invoices = 0
        overdue_invoice_items = []
        try:
            Invoice = apps.get_model("billing", "Invoice")
            outstanding_qs = Invoice.objects.exclude(status="PAID")
            agg = outstanding_qs.aggregate(total=Sum("total_amount"))
            outstanding_payments = agg.get("total") or Decimal("0.00")

            today = timezone.localdate()
            overdue_qs = outstanding_qs.filter(due_date__lt=today)
            overdue_invoices = overdue_qs.count()
            overdue_invoice_items = list(overdue_qs.order_by("due_date")[:5])
        except Exception:
            pass

        # Payments
        this_month_payments = Decimal("0.00")
        try:
            Payment = apps.get_model("payments", "Payment")
            now = timezone.now()
            agg = Payment.objects.filter(
                payment_date__year=now.year, payment_date__month=now.month
            ).aggregate(total=Sum("amount"))
            this_month_payments = agg.get("total") or Decimal("0.00")
        except Exception:
            pass

        mrr_val = this_month_payments
        arr_val = this_month_payments * 12

        context.update({
            "total_customers": total_customers,
            "active_subscriptions": active_subscriptions,
            "recent_subscriptions": recent_subscriptions,
            "mrr": f"${mrr_val:,.2f}",
            "arr": f"${arr_val:,.2f}",
            "outstanding_payments": f"${outstanding_payments:,.2f}",
            "overdue_invoices": overdue_invoices,
            "overdue_invoice_items": overdue_invoice_items,
        })

    return render(request, "dashboard.html", context)
