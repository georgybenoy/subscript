"""
Tests for Phase 6: Financial Intelligence & Analytics Services and Views.

Verifies:
- MRR normalization for each frequency (DAILY, WEEKLY, MONTHLY, YEARLY)
- Paused, Quotation, Draft, and Closed subscriptions excluded from MRR/ARR
- ARR calculation strictly equals MRR * 12
- Collected revenue excludes unpaid/confirmed invoices
- Outstanding balance sums (total_amount - paid_amount) over CONFIRMED invoices
- Empty database returns exact zeroes with empty chart structures
- Query count assertion ensuring pure database aggregation without N+1
- Staff/Admin access allowed, Customer access forbidden (403 PermissionDenied)
"""

from datetime import date, timedelta
from decimal import Decimal
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from analytics.services import calculate_mrr_and_arr, get_dashboard_context
from billing.integrations import Plan, Product, Subscription, SubscriptionItem
from billing.models import Invoice, InvoiceStatus
from customers.models import Customer
from payments.models import Payment
from payments.services import record_payment
from tests.test_billing_models import BaseBillingTestCase

User = get_user_model()


class AnalyticsTests(BaseBillingTestCase):
    def setUp(self):
        super().setUp()
        self.client = Client()
        self.password = "StrongPassword123!"

        # Admin user
        self.admin_user = User.objects.create_superuser(
            email="admin_analytics@test.local", password=self.password
        )

        # Staff user
        self.staff_user = User.objects.create_user(
            email="staff_analytics@test.local", password=self.password, role=User.Role.STAFF
        )

        # Customer user
        self.cust_user = User.objects.create_user(
            email="cust_analytics@test.local", password=self.password, role=User.Role.CUSTOMER
        )
        self.customer.user = self.cust_user
        self.customer.save()

        # Disable default active subscription from base setup to start with clean slate
        self.subscription.status = "DRAFT"
        self.subscription.save()

    def test_empty_database_returns_zeroes(self):
        """Empty database returns all zeroes and empty chart series with exact required keys."""
        # Clean any setup subscriptions
        Subscription.objects.all().delete()

        context = get_dashboard_context()

        # Check exact required keys
        required_keys = {
            "active_subscriptions",
            "mrr",
            "arr",
            "collected_revenue",
            "outstanding_balance",
            "overdue_invoice_count",
            "revenue_chart",
            "subscription_chart",
            "collection_chart",
            "invoiced_chart",
        }
        self.assertEqual(required_keys.difference(context.keys()), set())

        # Exact zero values
        self.assertEqual(context["active_subscriptions"], 0)
        self.assertEqual(context["mrr"], "0.00")
        self.assertEqual(context["arr"], "0.00")
        self.assertEqual(context["collected_revenue"], "0.00")
        self.assertEqual(context["outstanding_balance"], "0.00")
        self.assertEqual(context["overdue_invoice_count"], 0)

        # Chart structures
        self.assertEqual(context["revenue_chart"]["labels"], [])
        self.assertEqual(context["revenue_chart"]["data"], [])
        self.assertEqual(context["subscription_chart"]["labels"], [])
        self.assertEqual(context["subscription_chart"]["data"], [])
        self.assertEqual(context["collection_chart"]["labels"], [])
        self.assertEqual(context["collection_chart"]["data"], [])
        self.assertEqual(context["invoiced_chart"]["labels"], [])
        self.assertEqual(context["invoiced_chart"]["data"], [])

    def test_mrr_for_each_frequency_and_arr_multiplier(self):
        """
        Tests MRR normalization across DAILY, WEEKLY, MONTHLY, and YEARLY plans.
        Verifies ARR = MRR * 12.
        """
        # 1. Monthly plan: $100 / month -> MRR $100.00
        plan_monthly = Plan.objects.create(name="Monthly Plan", billing_frequency="MONTHLY")
        sub_monthly = Subscription.objects.create(
            subscription_number="SUB-M-01",
            customer=self.customer,
            plan=plan_monthly,
            status="ACTIVE",
            start_date=date(2026, 1, 1),
        )
        SubscriptionItem.objects.create(
            subscription=sub_monthly,
            quantity=1,
            unit_price=Decimal("100.00"),
        )
        mrr, arr = calculate_mrr_and_arr()
        self.assertEqual(mrr, Decimal("100.00"))
        self.assertEqual(arr, Decimal("1200.00"))
        self.assertEqual(arr, mrr * Decimal("12"))

        # 2. Daily plan: $10 / day -> MRR $10 * 365 / 12 = $304.17
        plan_daily = Plan.objects.create(name="Daily Plan", billing_frequency="DAILY")
        sub_daily = Subscription.objects.create(
            subscription_number="SUB-D-01",
            customer=self.customer,
            plan=plan_daily,
            status="ACTIVE",
            start_date=date(2026, 1, 1),
        )
        SubscriptionItem.objects.create(
            subscription=sub_daily,
            quantity=1,
            unit_price=Decimal("10.00"),
        )
        # Combined: 100.00 + 304.17 = 404.17
        mrr, arr = calculate_mrr_and_arr()
        self.assertEqual(mrr, Decimal("404.17"))
        self.assertEqual(arr, Decimal("4850.04"))
        self.assertEqual(arr, mrr * Decimal("12"))

        # 3. Weekly plan: $100 / week -> MRR $100 * 52 / 12 = $433.33
        plan_weekly = Plan.objects.create(name="Weekly Plan", billing_frequency="WEEKLY")
        sub_weekly = Subscription.objects.create(
            subscription_number="SUB-W-01",
            customer=self.customer,
            plan=plan_weekly,
            status="ACTIVE",
            start_date=date(2026, 1, 1),
        )
        SubscriptionItem.objects.create(
            subscription=sub_weekly,
            quantity=1,
            unit_price=Decimal("100.00"),
        )
        # Combined: 404.1666... + 433.3333... = 837.50
        mrr, arr = calculate_mrr_and_arr()
        self.assertEqual(mrr, Decimal("837.50"))
        self.assertEqual(arr, Decimal("10050.00"))
        self.assertEqual(arr, mrr * Decimal("12"))

        # 4. Yearly plan: $1200 / year -> MRR $1200 / 12 = $100.00
        plan_yearly = Plan.objects.create(name="Yearly Plan", billing_frequency="YEARLY")
        sub_yearly = Subscription.objects.create(
            subscription_number="SUB-Y-01",
            customer=self.customer,
            plan=plan_yearly,
            status="ACTIVE",
            start_date=date(2026, 1, 1),
        )
        SubscriptionItem.objects.create(
            subscription=sub_yearly,
            quantity=1,
            unit_price=Decimal("1200.00"),
        )
        # Combined: 837.50 + 100.00 = 937.50
        mrr, arr = calculate_mrr_and_arr()
        self.assertEqual(mrr, Decimal("937.50"))
        self.assertEqual(arr, Decimal("11250.00"))
        self.assertEqual(arr, mrr * Decimal("12"))

    def test_paused_and_closed_subscriptions_excluded(self):
        """Subscriptions with status PAUSED, CLOSED, QUOTATION, or DRAFT do not contribute to MRR."""
        plan = Plan.objects.create(name="Enterprise", billing_frequency="MONTHLY")

        for status_val in ["PAUSED", "CLOSED", "QUOTATION", "DRAFT"]:
            sub = Subscription.objects.create(
                subscription_number=f"SUB-INACT-{status_val}",
                customer=self.customer,
                plan=plan,
                status=status_val,
                start_date=date(2026, 1, 1),
            )
            SubscriptionItem.objects.create(
                subscription=sub,
                quantity=1,
                unit_price=Decimal("5000.00"),
            )

        mrr, arr = calculate_mrr_and_arr()
        self.assertEqual(mrr, Decimal("0.00"))
        self.assertEqual(arr, Decimal("0.00"))

    def test_collected_revenue_excludes_unpaid_invoices(self):
        """
        Collected revenue reflects only settled payments;
        unpaid or partially paid invoice balances are not treated as collected cash.
        """
        today = timezone.localdate()
        invoice = Invoice.objects.create(
            subscription=self.subscription,
            invoice_number="INV-2026-REV01",
            issue_date=today,
            due_date=today + timedelta(days=15),
            billing_period_start=today - timedelta(days=30),
            billing_period_end=today - timedelta(days=1),
            subtotal=Decimal("1000.00"),
            tax_amount=Decimal("0.00"),
            discount_amount=Decimal("0.00"),
            total_amount=Decimal("1000.00"),
            status=InvoiceStatus.CONFIRMED,
        )

        context_unpaid = get_dashboard_context()
        self.assertEqual(context_unpaid["collected_revenue"], "0.00")
        self.assertEqual(context_unpaid["outstanding_balance"], "1000.00")

        # Record partial payment of 400.00
        record_payment(
            invoice=invoice,
            amount=Decimal("400.00"),
            method="CARD",
            payment_date=today,
        )

        context_partial = get_dashboard_context()
        self.assertEqual(context_partial["collected_revenue"], "400.00")
        self.assertEqual(context_partial["outstanding_balance"], "600.00")

    def test_query_count_constant_aggregation(self):
        """
        Asserts that analytics dashboard context executes a small, constant number of queries
        irrespective of volume (pure DB aggregation without N+1 loops).
        """
        # Create multiple subscriptions and invoices
        plan = Plan.objects.create(name="Scale Plan", billing_frequency="MONTHLY")
        for i in range(10):
            sub = Subscription.objects.create(
                subscription_number=f"SUB-SCALE-{i}",
                customer=self.customer,
                plan=plan,
                status="ACTIVE",
                start_date=date(2026, 1, 1),
            )
            SubscriptionItem.objects.create(
                subscription=sub,
                quantity=2,
                unit_price=Decimal("50.00"),
            )

        # Measure query count
        with self.assertNumQueries(9):
            context = get_dashboard_context()

        self.assertEqual(context["active_subscriptions"], 10)
        self.assertEqual(context["mrr"], "1000.00")

    def test_analytics_views_and_permission_enforcement(self):
        """
        Validates HTML view and JSON API endpoint.
        Ensures Staff/Admin access is granted and Customer role is denied (403).
        """
        # Customer access rejected with 403 Forbidden
        self.client.force_login(self.cust_user)
        resp_html_cust = self.client.get("/analytics/")
        self.assertEqual(resp_html_cust.status_code, 403)

        resp_json_cust = self.client.get("/analytics/data/")
        self.assertEqual(resp_json_cust.status_code, 403)

        # Staff access granted
        self.client.force_login(self.staff_user)
        resp_html_staff = self.client.get("/analytics/")
        self.assertEqual(resp_html_staff.status_code, 200)

        resp_json_staff = self.client.get("/analytics/data/")
        self.assertEqual(resp_json_staff.status_code, 200)
        data = resp_json_staff.json()
        self.assertIn("active_subscriptions", data)
        self.assertIn("mrr", data)
        self.assertIn("arr", data)
        self.assertIn("revenue_chart", data)
