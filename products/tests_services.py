from decimal import Decimal
from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from products.models import Product, ProductType, ProductVariant, Plan
from products import services

User = get_user_model()


class ProductServicesAndViewsTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            email="prod_admin@subscript.local", password="AdminPassword123!", role=User.Role.ADMIN
        )
        self.staff = User.objects.create_user(
            email="prod_staff@subscript.local", password="StaffPassword123!", role=User.Role.STAFF, is_staff=True
        )
        self.cust = User.objects.create_user(
            email="prod_cust@subscript.local", password="CustPassword123!", role=User.Role.CUSTOMER
        )

        self.client_anon = Client()
        self.client_cust = Client()
        self.client_cust.force_login(self.cust)
        self.client_staff = Client()
        self.client_staff.force_login(self.staff)
        self.client_admin = Client()
        self.client_admin.force_login(self.admin)

        self.product_active = Product.objects.create(
            name="Cloud SaaS Pro",
            description="Active SaaS service",
            product_type=ProductType.SAAS,
            sales_price=Decimal("100.00"),
            cost_price=Decimal("20.00"),
            is_active=True,
        )
        self.product_inactive = Product.objects.create(
            name="Legacy Hardware",
            description="Archived product",
            product_type=ProductType.HARDWARE,
            sales_price=Decimal("50.00"),
            cost_price=Decimal("35.00"),
            is_active=False,
        )

    def test_effective_price_calculation(self):
        """Effective price = product.sales_price + variant.price_adjustment."""
        variant = ProductVariant.objects.create(
            product=self.product_active,
            name="Gold Add-on",
            sku="GOLD-ADDON-01",
            price_adjustment=Decimal("25.50"),
        )
        self.assertEqual(variant.effective_price, Decimal("125.50"))

    def test_search_and_filter_products(self):
        """Tests filtering by query, product_type, and status."""
        qs = Product.objects.all()
        # Query search
        res_q = services.search_and_filter_products(qs, query="Cloud")
        self.assertIn(self.product_active, res_q)
        self.assertNotIn(self.product_inactive, res_q)

        # Type filter
        res_type = services.search_and_filter_products(qs, product_type="HARDWARE")
        self.assertIn(self.product_inactive, res_type)
        self.assertNotIn(self.product_active, res_type)

        # Status filter
        res_status = services.search_and_filter_products(qs, status="active")
        self.assertIn(self.product_active, res_status)
        self.assertNotIn(self.product_inactive, res_status)

    def test_customer_and_anonymous_can_only_view_active_products(self):
        """Customers and anonymous users can access catalog, but only see active products."""
        # Anon
        res_anon = self.client_anon.get(reverse("products:list"))
        self.assertEqual(res_anon.status_code, 200)
        self.assertContains(res_anon, "Cloud SaaS Pro")
        self.assertNotContains(res_anon, "Legacy Hardware")

        # Customer
        res_cust = self.client_cust.get(reverse("products:list"))
        self.assertEqual(res_cust.status_code, 200)
        self.assertContains(res_cust, "Cloud SaaS Pro")
        self.assertNotContains(res_cust, "Legacy Hardware")

        # Staff can see inactive
        res_staff = self.client_staff.get(reverse("products:list"))
        self.assertEqual(res_staff.status_code, 200)
        self.assertContains(res_staff, "Legacy Hardware")

    def test_customer_cannot_create_or_edit_products(self):
        """Customers must receive 403 on staff/admin management views."""
        res_create = self.client_cust.get(reverse("products:create"))
        self.assertEqual(res_create.status_code, 403)

        res_edit = self.client_cust.get(reverse("products:edit", kwargs={"pk": self.product_active.pk}))
        self.assertEqual(res_edit.status_code, 403)

    def test_staff_can_create_and_edit_product(self):
        """Staff and Admin can create and edit products."""
        data = {
            "name": "New Consulting Service",
            "sales_price": "250.00",
            "cost_price": "50.00",
            "product_type": "SERVICE",
            "is_active": "on",
            "description": "Expert consulting package",
        }
        res_create = self.client_staff.post(reverse("products:create"), data)
        self.assertEqual(res_create.status_code, 302)
        created = Product.objects.filter(name="New Consulting Service").first()
        self.assertIsNotNone(created)
        self.assertEqual(created.sales_price, Decimal("250.00"))
