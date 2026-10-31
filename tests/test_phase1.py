from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from customers.models import Customer

User = get_user_model()


class UserModelTests(TestCase):
    def test_create_regular_user(self):
        user = User.objects.create_user(
            email="subscriber@example.com",
            password="SecurePassword123!",
        )
        self.assertEqual(user.email, "subscriber@example.com")
        self.assertEqual(user.username, "subscriber")
        self.assertEqual(user.role, User.Role.CUSTOMER)
        self.assertTrue(user.is_customer_role)
        self.assertFalse(user.is_admin_role)
        self.assertFalse(user.is_staff_role)
        self.assertTrue(user.is_active)
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)

    def test_create_superuser(self):
        admin = User.objects.create_superuser(
            email="root@subscript.local",
            password="AdminRootPassword123!",
        )
        self.assertEqual(admin.role, User.Role.ADMIN)
        self.assertTrue(admin.is_admin_role)
        self.assertTrue(admin.is_staff)
        self.assertTrue(admin.is_superuser)

    def test_create_user_without_email_fails(self):
        with self.assertRaises(ValueError):
            User.objects.create_user(email="")


class CustomerModelTests(TestCase):
    def test_create_customer_profile(self):
        user = User.objects.create_user(
            email="customer@corp.com",
            password="CustomerPass123!",
        )
        customer = Customer.objects.create(
            user=user,
            name="John Doe",
            company_name="Acme Corp",
            email="billing@acme.com",
            phone="+919876543210",
            billing_address="123 Tech Park",
            city="Bengaluru",
            state="Karnataka",
            country="IN",
            tax_id="29ABCDE1234F1Z5",
        )
        self.assertEqual(str(customer), "John Doe (Acme Corp)")
        self.assertTrue(customer.is_active)
        self.assertEqual(customer.user.email, "customer@corp.com")
        self.assertEqual(user.customer_profile, customer)


class RoutingSmokeTests(TestCase):
    def setUp(self):
        self.client = Client()

    def test_dashboard_smoke_test(self):
        user = User.objects.create_user(email="dash@example.com", password="DashPassword1!")
        self.client.login(email="dash@example.com", password="DashPassword1!")
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Welcome back", response.content)

    def test_accounts_login_placeholder(self):
        response = self.client.get(reverse("accounts:login"))
        self.assertEqual(response.status_code, 200)

    def test_customers_list_placeholder(self):
        response = self.client.get(reverse("customers:list"))
        self.assertEqual(response.status_code, 200)
