from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import Client, TestCase
from django.urls import reverse
from accounts.validators import SubscriptPasswordValidator
from customers.models import Customer

User = get_user_model()


class PasswordValidatorTests(TestCase):
    def setUp(self):
        self.validator = SubscriptPasswordValidator(min_length=9)

    def test_valid_password(self):
        # 9+ chars, upper, lower, special
        self.assertIsNone(self.validator.validate("Valid1@Pass"))

    def test_password_too_short(self):
        # 8 chars (min length is 9)
        with self.assertRaises(ValidationError) as ctx:
            self.validator.validate("Ab1@cdef")
        self.assertIn("at least 9 characters", str(ctx.exception))

    def test_password_missing_uppercase(self):
        with self.assertRaises(ValidationError) as ctx:
            self.validator.validate("lowercase1@pass")
        self.assertIn("uppercase letter", str(ctx.exception))

    def test_password_missing_lowercase(self):
        with self.assertRaises(ValidationError) as ctx:
            self.validator.validate("UPPERCASE1@PASS")
        self.assertIn("lowercase letter", str(ctx.exception))

    def test_password_missing_special_character(self):
        with self.assertRaises(ValidationError) as ctx:
            self.validator.validate("Alphanumeric123")
        self.assertIn("special character", str(ctx.exception))


class RegistrationAndServiceTests(TestCase):
    def setUp(self):
        self.client = Client()

    def test_registration_creates_customer_role(self):
        # Attempt to inject role=ADMIN in POST
        response = self.client.post(
            reverse("accounts:register"),
            {
                "email": "customer1@example.com",
                "first_name": "Alice",
                "last_name": "Smith",
                "password1": "SecurePass1!",
                "password2": "SecurePass1!",
                "role": "ADMIN",  # Malicious injection attempt
            },
        )
        self.assertEqual(response.status_code, 302)
        user = User.objects.get(email="customer1@example.com")
        self.assertEqual(user.role, User.Role.CUSTOMER)
        self.assertTrue(user.is_customer_role)
        self.assertFalse(user.is_admin_role)
        self.assertFalse(user.is_staff)

        # Ensure linked Customer profile was auto-provisioned
        self.assertTrue(hasattr(user, "customer_profile"))
        customer = user.customer_profile
        self.assertEqual(customer.name, "Alice Smith")
        self.assertEqual(customer.email, "customer1@example.com")

    def test_case_insensitive_duplicate_email_rejected(self):
        User.objects.create_user(email="testuser@example.com", password="Password1!")

        response = self.client.post(
            reverse("accounts:register"),
            {
                "email": "TestUser@Example.COM",
                "first_name": "Test",
                "last_name": "User",
                "password1": "SecurePass1!",
                "password2": "SecurePass1!",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertFormError(
            response.context["form"],
            "email",
            "A user with this email address already exists.",
        )


class AuthenticationFlowTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.password = "StrongAuthPass1!"
        self.user = User.objects.create_user(
            email="auth@example.com",
            password=self.password,
            first_name="Auth",
            last_name="Tester",
        )

    def test_login_success_and_logout_post_only(self):
        # Login
        login_res = self.client.post(
            reverse("accounts:login"),
            {"email": "auth@example.com", "password": self.password},
        )
        self.assertEqual(login_res.status_code, 302)
        self.assertTrue("_auth_user_id" in self.client.session)

        # GET on logout is rejected (405 Method Not Allowed)
        get_logout_res = self.client.get(reverse("accounts:logout"))
        self.assertEqual(get_logout_res.status_code, 405)

        # POST on logout succeeds
        post_logout_res = self.client.post(reverse("accounts:logout"))
        self.assertEqual(post_logout_res.status_code, 302)
        self.assertFalse("_auth_user_id" in self.client.session)

    def test_login_safe_next_redirect(self):
        login_res = self.client.post(
            f"{reverse('accounts:login')}?next=/accounts/profile/",
            {"email": "auth@example.com", "password": self.password},
        )
        self.assertRedirects(login_res, "/accounts/profile/")

    def test_login_unsafe_next_redirect_ignored(self):
        login_res = self.client.post(
            f"{reverse('accounts:login')}?next=https://malicious.evil.com/steal",
            {"email": "auth@example.com", "password": self.password},
        )
        self.assertRedirects(login_res, reverse("dashboard"))

    def test_inactive_user_cannot_login(self):
        self.user.is_active = False
        self.user.save()

        res = self.client.post(
            reverse("accounts:login"),
            {"email": "auth@example.com", "password": self.password},
        )
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "This account is inactive")
        self.assertFalse("_auth_user_id" in self.client.session)


class RBACPermissionsTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.password = "ComplexPass1!"

        self.admin = User.objects.create_superuser(
            email="admin@subscript.local",
            password=self.password,
        )
        self.staff = User.objects.create_user(
            email="staff@subscript.local",
            password=self.password,
            role=User.Role.STAFF,
            is_staff=True,
        )
        self.customer = User.objects.create_user(
            email="client@subscript.local",
            password=self.password,
            role=User.Role.CUSTOMER,
        )

    def test_anonymous_redirected_to_login(self):
        protected_urls = [
            reverse("dashboard"),
            reverse("accounts:profile"),
            reverse("accounts:user_list"),
            reverse("accounts:staff_create"),
        ]
        for url in protected_urls:
            res = self.client.get(url)
            self.assertEqual(res.status_code, 302)
            self.assertTrue(res.url.startswith(reverse("accounts:login")))

    def test_customer_access_forbidden_on_admin_pages(self):
        self.client.login(email=self.customer.email, password=self.password)

        res_users = self.client.get(reverse("accounts:user_list"))
        self.assertEqual(res_users.status_code, 403)

        res_staff_create = self.client.get(reverse("accounts:staff_create"))
        self.assertEqual(res_staff_create.status_code, 403)

    def test_staff_access_forbidden_on_user_admin_pages(self):
        self.client.login(email=self.staff.email, password=self.password)

        res_users = self.client.get(reverse("accounts:user_list"))
        self.assertEqual(res_users.status_code, 403)

        res_staff_create = self.client.get(reverse("accounts:staff_create"))
        self.assertEqual(res_staff_create.status_code, 403)

    def test_admin_access_allowed_on_admin_pages(self):
        self.client.login(email=self.admin.email, password=self.password)

        res_users = self.client.get(reverse("accounts:user_list"))
        self.assertEqual(res_users.status_code, 200)

        res_staff_create = self.client.get(reverse("accounts:staff_create"))
        self.assertEqual(res_staff_create.status_code, 200)

    def test_admin_can_provision_staff(self):
        self.client.login(email=self.admin.email, password=self.password)
        res = self.client.post(
            reverse("accounts:staff_create"),
            {
                "email": "newstaff@subscript.local",
                "first_name": "Bob",
                "last_name": "Staff",
                "password": "StaffPass1!",
            },
        )
        self.assertEqual(res.status_code, 302)
        new_staff = User.objects.get(email="newstaff@subscript.local")
        self.assertEqual(new_staff.role, User.Role.STAFF)
        self.assertTrue(new_staff.is_staff)

    def test_admin_cannot_deactivate_self(self):
        self.client.login(email=self.admin.email, password=self.password)
        res = self.client.post(
            reverse("accounts:user_toggle_active", kwargs={"user_id": self.admin.pk})
        )
        self.assertEqual(res.status_code, 302)
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_active)

    def test_admin_can_deactivate_other_user(self):
        self.client.login(email=self.admin.email, password=self.password)
        res = self.client.post(
            reverse("accounts:user_toggle_active", kwargs={"user_id": self.customer.pk})
        )
        self.assertEqual(res.status_code, 302)
        self.customer.refresh_from_db()
        self.assertFalse(self.customer.is_active)

    def test_dashboard_role_aware_context(self):
        # Admin
        self.client.login(email=self.admin.email, password=self.password)
        res_admin = self.client.get(reverse("dashboard"))
        self.assertEqual(res_admin.status_code, 200)
        self.assertContains(res_admin, "User & Role Management")

        # Staff
        self.client.login(email=self.staff.email, password=self.password)
        res_staff = self.client.get(reverse("dashboard"))
        self.assertEqual(res_staff.status_code, 200)
        self.assertContains(res_staff, "Operational Workspace")

        # Customer
        self.client.login(email=self.customer.email, password=self.password)
        res_cust = self.client.get(reverse("dashboard"))
        self.assertEqual(res_cust.status_code, 200)
        self.assertContains(res_cust, "My Account & Subscriptions")
