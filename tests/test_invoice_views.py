"""
Tests for Invoice services, list view, detail view, pagination, search, and tenant isolation.
"""

from datetime import date, timedelta
from decimal import Decimal
from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from customers.models import Customer
from billing.integrations import Subscription, Plan
from billing.models import Invoice, InvoiceItem, InvoiceStatus
from billing.services import calculate_invoice_totals
from tests.test_billing_models import BaseBillingTestCase

User = get_user_model()


class InvoiceServiceAndViewsTests(BaseBillingTestCase):
    def setUp(self):
        super().setUp()
        self.client = Client()

        # Users
        self.password = "StrongPass123!"
        self.admin = User.objects.create_superuser(
            email="admin@test.local", password=self.password
        )
        self.staff = User.objects.create_user(
            email="staff@test.local", password=self.password, role=User.Role.STAFF
        )

        # Customer A
        self.user_a = User.objects.create_user(
            email="customerA@test.local", password=self.password, role=User.Role.CUSTOMER
        )
        self.customer_a = Customer.objects.create(
            user=self.user_a,
            name="Alice Customer",
            company_name="Alice Corp",
            email="alice@alicecorp.test",
        )
        self.sub_a = Subscription.objects.create(
            subscription_number="SUB-A-01",
            customer=self.customer_a,
            status="ACTIVE",
        )
        self.inv_a = Invoice.objects.create(
            subscription=self.sub_a,
            invoice_number="INV-A-1001",
            issue_date=date(2026, 1, 1),
            due_date=date(2026, 1, 15),
            billing_period_start=date(2026, 1, 1),
            billing_period_end=date(2026, 1, 31),
            subtotal=Decimal("100.00"),
            total_amount=Decimal("118.00"),
            status=InvoiceStatus.CONFIRMED,
        )

        # Customer B
        self.user_b = User.objects.create_user(
            email="customerB@test.local", password=self.password, role=User.Role.CUSTOMER
        )
        self.customer_b = Customer.objects.create(
            user=self.user_b,
            name="Bob Customer",
            company_name="Bob Enterprises",
            email="bob@bobcorp.test",
        )
        self.sub_b = Subscription.objects.create(
            subscription_number="SUB-B-01",
            customer=self.customer_b,
            status="ACTIVE",
        )
        self.inv_b = Invoice.objects.create(
            subscription=self.sub_b,
            invoice_number="INV-B-2001",
            issue_date=date(2026, 1, 1),
            due_date=date(2026, 1, 15),
            billing_period_start=date(2026, 1, 1),
            billing_period_end=date(2026, 1, 31),
            subtotal=Decimal("200.00"),
            total_amount=Decimal("200.00"),
            status=InvoiceStatus.CONFIRMED,
        )

    def test_calculate_invoice_totals_service(self):
        inv = Invoice.objects.create(
            subscription=self.sub_a,
            invoice_number="INV-CALC-TEST",
            issue_date=date(2026, 2, 1),
            due_date=date(2026, 2, 16),
            billing_period_start=date(2026, 2, 1),
            billing_period_end=date(2026, 2, 28),
            status=InvoiceStatus.DRAFT,
            discount_amount=Decimal("20.00"),
        )
        InvoiceItem.objects.create(
            invoice=inv,
            description="Item 1",
            quantity=2,
            unit_price=Decimal("50.00"),
            tax_rate=Decimal("18.00"),
        )
        InvoiceItem.objects.create(
            invoice=inv,
            description="Item 2",
            quantity=1,
            unit_price=Decimal("100.00"),
            tax_rate=Decimal("10.00"),
        )

        calculate_invoice_totals(inv)
        inv.refresh_from_db()

        # Item 1: 100 subtotal, 18 tax = 118
        # Item 2: 100 subtotal, 10 tax = 110
        # Subtotal: 200, Tax: 28, Discount: 20 -> Total: 208.00
        self.assertEqual(inv.subtotal, Decimal("200.00"))
        self.assertEqual(inv.tax_amount, Decimal("28.00"))
        self.assertEqual(inv.discount_amount, Decimal("20.00"))
        self.assertEqual(inv.total_amount, Decimal("208.00"))

    def test_admin_and_staff_see_all_invoices(self):
        # Admin
        self.client.login(email=self.admin.email, password=self.password)
        res_admin = self.client.get(reverse("billing:invoice_list"))
        self.assertEqual(res_admin.status_code, 200)
        self.assertContains(res_admin, "INV-A-1001")
        self.assertContains(res_admin, "INV-B-2001")

        # Staff
        self.client.login(email=self.staff.email, password=self.password)
        res_staff = self.client.get(reverse("billing:invoice_list"))
        self.assertEqual(res_staff.status_code, 200)
        self.assertContains(res_staff, "INV-A-1001")
        self.assertContains(res_staff, "INV-B-2001")

    def test_customer_isolation_in_list_view(self):
        self.client.login(email=self.user_a.email, password=self.password)
        res = self.client.get(reverse("billing:invoice_list"))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "INV-A-1001")
        self.assertNotContains(res, "INV-B-2001")

    def test_customer_accessing_other_customer_invoice_returns_404(self):
        # Customer A attempts to inspect Customer B's invoice
        self.client.login(email=self.user_a.email, password=self.password)
        res = self.client.get(reverse("billing:invoice_detail", kwargs={"pk": self.inv_b.pk}))
        # IDOR prevention: return 404, not 403
        self.assertEqual(res.status_code, 404)

    def test_invoice_search_and_status_filter(self):
        self.client.login(email=self.admin.email, password=self.password)

        # Search by customer company
        res_search = self.client.get(reverse("billing:invoice_list"), {"q": "Bob Enterprises"})
        self.assertContains(res_search, "INV-B-2001")
        self.assertNotContains(res_search, "INV-A-1001")

        # Filter by status
        res_status = self.client.get(reverse("billing:invoice_list"), {"status": "CONFIRMED"})
        self.assertContains(res_status, "INV-A-1001")
        self.assertContains(res_status, "INV-B-2001")

    def test_invoice_list_query_count_constant(self):
        # Create 10 additional invoices for performance test
        for i in range(10):
            Invoice.objects.create(
                subscription=self.sub_a,
                invoice_number=f"INV-PERF-{i}",
                issue_date=date(2026, 1, 1),
                due_date=date(2026, 1, 15),
                billing_period_start=date(2026, 1, 1) + timedelta(days=32 * (i + 1)),
                billing_period_end=date(2026, 1, 30) + timedelta(days=32 * (i + 1)),
                subtotal=Decimal("50.00"),
                total_amount=Decimal("50.00"),
                status=InvoiceStatus.CONFIRMED,
            )

        self.client.login(email=self.admin.email, password=self.password)
        # Assert query count remains small and bounded (prevent N+1 regardless of row count)
        # 1. session, 2. user, 3. paginator count, 4. invoices + join + annotations, 5. prefetched payments
        with self.assertNumQueries(5):
            res = self.client.get(reverse("billing:invoice_list"))
            self.assertEqual(res.status_code, 200)
