"""
Automated Permission Audit and RBAC Matrix Verification.

Verifies access control across all roles:
1. Anonymous: 302 redirect to login on protected routes, 200 on public routes.
2. Customer: 403 Forbidden on staff/admin routes, 200 on own portal routes.
3. Staff: 200 on operational routes, 403 Forbidden on admin-only routes.
4. Admin: 200 on all routes.
5. Cross-Tenant IDOR: Customer A cannot access Customer B's records (404/403).
"""

from decimal import Decimal
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase, Client
from django.urls import reverse
from customers.models import Customer

User = get_user_model()


class PermissionMatrixTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Ensure prerequisite tables exist for Member 3's pending subscription models
        with connection.cursor() as cursor:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS subscriptions_subscription (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    subscription_number VARCHAR(100) NOT NULL UNIQUE,
                    customer_id BIGINT NOT NULL,
                    plan_id BIGINT,
                    status VARCHAR(20) NOT NULL DEFAULT 'ACTIVE',
                    start_date DATE NOT NULL,
                    expiry_date DATE,
                    next_billing_date DATE,
                    payment_terms INTEGER NOT NULL DEFAULT 15
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS subscriptions_subscriptionitem (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    subscription_id BIGINT NOT NULL,
                    product_id BIGINT,
                    description VARCHAR(255) NOT NULL DEFAULT '',
                    quantity INTEGER NOT NULL DEFAULT 1,
                    unit_price DECIMAL(12, 2) NOT NULL DEFAULT '0.00',
                    tax_rate DECIMAL(5, 2) NOT NULL DEFAULT '0.00'
                )
            """)

    @classmethod
    def setUpTestData(cls):
        # 1. Admin
        cls.admin_user = User.objects.create_superuser(
            email="perm_admin@subscript.local",
            password="AdminPassword123!",
            first_name="Admin",
            last_name="User",
            role=User.Role.ADMIN,
        )

        # 2. Staff
        cls.staff_user = User.objects.create_user(
            email="perm_staff@subscript.local",
            password="StaffPassword123!",
            first_name="Staff",
            last_name="User",
            role=User.Role.STAFF,
            is_staff=True,
        )

        # 3. Customer A
        cls.cust_user_a = User.objects.create_user(
            email="perm_cust_a@subscript.local",
            password="CustomerPassword123!",
            first_name="Alice",
            last_name="Customer",
            role=User.Role.CUSTOMER,
        )
        cls.customer_a = Customer.objects.create(
            user=cls.cust_user_a,
            name="Alice Customer",
            company_name="Acme Corp",
            email="alice@acme.com",
            billing_address="100 First St",
            city="New York",
            state="NY",
            country="US",
        )

        # 4. Customer B
        cls.cust_user_b = User.objects.create_user(
            email="perm_cust_b@subscript.local",
            password="CustomerPassword123!",
            first_name="Bob",
            last_name="Customer",
            role=User.Role.CUSTOMER,
        )
        cls.customer_b = Customer.objects.create(
            user=cls.cust_user_b,
            name="Bob Customer",
            company_name="Beta LLC",
            email="bob@beta.com",
            billing_address="200 Second St",
            city="San Francisco",
            state="CA",
            country="US",
        )

    def setUp(self):
        self.anon_client = Client()
        self.admin_client = Client()
        self.admin_client.force_login(self.admin_user)
        self.staff_client = Client()
        self.staff_client.force_login(self.staff_user)
        self.cust_client_a = Client()
        self.cust_client_a.force_login(self.cust_user_a)
        self.cust_client_b = Client()
        self.cust_client_b.force_login(self.cust_user_b)

    # ==========================================================================
    # 1. ANONYMOUS USER ACCESS
    # ==========================================================================
    def test_anonymous_public_routes_return_200(self):
        """Public authentication endpoints must return 200 for anonymous users."""
        public_urls = [
            reverse("accounts:login"),
            reverse("accounts:register"),
            reverse("accounts:password_reset"),
            reverse("accounts:password_reset_done"),
            reverse("accounts:password_reset_complete"),
        ]
        for url in public_urls:
            with self.subTest(url=url):
                res = self.anon_client.get(url)
                self.assertEqual(res.status_code, 200)

    def test_anonymous_protected_routes_redirect_to_login(self):
        """Protected endpoints must redirect anonymous users to login (302)."""
        protected_urls = [
            reverse("dashboard"),
            reverse("accounts:profile"),
            reverse("accounts:password_change"),
            reverse("accounts:staff_create"),
            reverse("accounts:user_list"),
            reverse("customers:list"),
            reverse("customers:create"),
            reverse("customers:detail", kwargs={"pk": self.customer_a.pk}),
            reverse("billing:invoice_list"),
            reverse("payments:payment_list"),
            reverse("payments:payment_create"),
            reverse("analytics:dashboard"),
            reverse("analytics:data"),
        ]
        for url in protected_urls:
            with self.subTest(url=url):
                res = self.anon_client.get(url)
                self.assertEqual(res.status_code, 302)
                self.assertIn("/accounts/login/", res.url)

    # ==========================================================================
    # 2. CUSTOMER ROLE ACCESS & RBAC RESTRICTIONS
    # ==========================================================================
    def test_customer_denied_access_to_admin_and_staff_routes(self):
        """Customers must receive 403 Forbidden on staff and admin routes."""
        staff_admin_urls = [
            reverse("accounts:staff_create"),
            reverse("accounts:user_list"),
            reverse("customers:create"),
            reverse("payments:payment_create"),
            reverse("analytics:dashboard"),
            reverse("analytics:data"),
        ]
        for url in staff_admin_urls:
            with self.subTest(url=url):
                res = self.cust_client_a.get(url)
                self.assertEqual(res.status_code, 403)

    def test_customer_can_access_own_portal_routes(self):
        """Customer can access own dashboard, profile, customer detail, and directories."""
        res_dash = self.cust_client_a.get(reverse("dashboard"))
        self.assertEqual(res_dash.status_code, 200)

        res_profile = self.cust_client_a.get(reverse("accounts:profile"))
        self.assertEqual(res_profile.status_code, 200)

        res_cust_list = self.cust_client_a.get(reverse("customers:list"))
        self.assertEqual(res_cust_list.status_code, 200)

        res_cust_detail = self.cust_client_a.get(
            reverse("customers:detail", kwargs={"pk": self.customer_a.pk})
        )
        self.assertEqual(res_cust_detail.status_code, 200)

        res_billing = self.cust_client_a.get(reverse("billing:invoice_list"))
        self.assertEqual(res_billing.status_code, 200)

        res_payments = self.cust_client_a.get(reverse("payments:payment_list"))
        self.assertEqual(res_payments.status_code, 200)

    # ==========================================================================
    # 3. STAFF ROLE ACCESS & PRIVILEGE BOUNDARIES
    # ==========================================================================
    def test_staff_denied_access_to_admin_only_routes(self):
        """Staff must receive 403 Forbidden on admin-only routes."""
        admin_only_urls = [
            reverse("accounts:staff_create"),
            reverse("accounts:user_list"),
        ]
        for url in admin_only_urls:
            with self.subTest(url=url):
                res = self.staff_client.get(url)
                self.assertEqual(res.status_code, 403)

        # POST toggle user active
        res_toggle = self.staff_client.post(
            reverse("accounts:user_toggle_active", kwargs={"user_id": self.cust_user_a.pk})
        )
        self.assertEqual(res_toggle.status_code, 403)

    @patch("analytics.views.get_dashboard_context", return_value={"collected_revenue": "0.00", "outstanding_balance": "0.00"})
    def test_staff_permitted_access_to_operational_routes(self, mock_analytics):
        """Staff must receive 200 on operational management routes."""
        staff_urls = [
            reverse("dashboard"),
            reverse("customers:list"),
            reverse("customers:create"),
            reverse("customers:detail", kwargs={"pk": self.customer_a.pk}),
            reverse("billing:invoice_list"),
            reverse("payments:payment_list"),
            reverse("payments:payment_create"),
            reverse("analytics:dashboard"),
            reverse("analytics:data"),
        ]
        for url in staff_urls:
            with self.subTest(url=url):
                res = self.staff_client.get(url)
                self.assertEqual(res.status_code, 200)

    # ==========================================================================
    # 4. ADMIN ROLE ACCESS
    # ==========================================================================
    @patch("analytics.views.get_dashboard_context", return_value={"collected_revenue": "0.00", "outstanding_balance": "0.00"})
    def test_admin_permitted_access_to_all_routes(self, mock_analytics):
        """Admin must receive 200 on all system routes."""
        all_routes = [
            reverse("dashboard"),
            reverse("accounts:staff_create"),
            reverse("accounts:user_list"),
            reverse("customers:list"),
            reverse("customers:create"),
            reverse("customers:detail", kwargs={"pk": self.customer_a.pk}),
            reverse("customers:detail", kwargs={"pk": self.customer_b.pk}),
            reverse("billing:invoice_list"),
            reverse("payments:payment_list"),
            reverse("payments:payment_create"),
            reverse("analytics:dashboard"),
            reverse("analytics:data"),
        ]
        for url in all_routes:
            with self.subTest(url=url):
                res = self.admin_client.get(url)
                self.assertEqual(res.status_code, 200)

    # ==========================================================================
    # 5. CROSS-TENANT DATA ISOLATION (IDOR DEFENSE)
    # ==========================================================================
    def test_customer_cannot_access_other_customer_detail_or_edit(self):
        """Customer A accessing Customer B's detail or edit must return 404 (IDOR defense)."""
        # Customer A accessing Customer B detail
        res_b_detail = self.cust_client_a.get(
            reverse("customers:detail", kwargs={"pk": self.customer_b.pk})
        )
        self.assertEqual(res_b_detail.status_code, 404)

        # Customer A accessing Customer B edit
        res_b_edit = self.cust_client_a.get(
            reverse("customers:edit", kwargs={"pk": self.customer_b.pk})
        )
        self.assertEqual(res_b_edit.status_code, 404)

    def test_customer_cannot_toggle_customer_status(self):
        """Customer cannot toggle active/inactive status of any customer (403)."""
        res_toggle_own = self.cust_client_a.post(
            reverse("customers:status_toggle", kwargs={"pk": self.customer_a.pk})
        )
        self.assertEqual(res_toggle_own.status_code, 403)

        res_toggle_other = self.cust_client_a.post(
            reverse("customers:status_toggle", kwargs={"pk": self.customer_b.pk})
        )
        self.assertEqual(res_toggle_other.status_code, 403)
