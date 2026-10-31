import re
from django.contrib.auth import get_user_model
from django.core import mail
from django.core.cache import cache
from django.test import Client, TestCase
from django.urls import reverse
from customers.models import Customer
from customers.services import scope_queryset_for_user

User = get_user_model()


class PasswordResetWorkflowTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.email = "resetme@example.com"
        self.user = User.objects.create_user(
            email=self.email,
            password="InitialPassword1!",
            first_name="Reset",
            last_name="Tester",
        )

    def test_password_reset_end_to_end(self):
        # 1. Request password reset
        res_req = self.client.post(
            reverse("accounts:password_reset"),
            {"email": self.email},
        )
        self.assertEqual(res_req.status_code, 302)
        self.assertRedirects(res_req, reverse("accounts:password_reset_done"))

        # 2. Verify email delivered to outbox
        self.assertEqual(len(mail.outbox), 1)
        email_body = mail.outbox[0].body
        self.assertIn(self.email, email_body)

        # 3. Extract reset link from email body
        match = re.search(r"(/accounts/reset/[^ \n\r]+)", email_body)
        self.assertTrue(bool(match), "Password reset URL not found in email body.")
        reset_url = match.group(1)

        # 4. Visit reset confirm URL (Django follows Referer-leak protection redirect to set-password)
        res_confirm_get = self.client.get(reset_url, follow=True)
        self.assertEqual(res_confirm_get.status_code, 200)
        self.assertTrue(res_confirm_get.context["validlink"])
        confirm_form_url = res_confirm_get.request["PATH_INFO"]

        # 5. Attempt weak password (rejected by SubscriptPasswordValidator)
        res_weak = self.client.post(
            confirm_form_url,
            {
                "new_password1": "weak",
                "new_password2": "weak",
            },
        )
        self.assertEqual(res_weak.status_code, 200)
        self.assertContains(res_weak, "at least 9 characters")

        # 6. Post valid password meeting all rules
        new_password = "BrandNewStrongPass1!"
        res_success = self.client.post(
            confirm_form_url,
            {
                "new_password1": new_password,
                "new_password2": new_password,
            },
        )
        self.assertEqual(res_success.status_code, 302)
        self.assertRedirects(res_success, reverse("accounts:password_reset_complete"))

        # 7. Old password fails
        login_old = self.client.post(
            reverse("accounts:login"),
            {"email": self.email, "password": "InitialPassword1!"},
        )
        self.assertEqual(login_old.status_code, 200)
        self.assertContains(login_old, "Invalid email address or password")

        # 8. New password succeeds
        login_new = self.client.post(
            reverse("accounts:login"),
            {"email": self.email, "password": new_password},
        )
        self.assertEqual(login_new.status_code, 302)
        self.assertTrue("_auth_user_id" in self.client.session)

    def test_user_enumeration_avoided(self):
        # Submitting nonexistent email gives identical response
        res = self.client.post(
            reverse("accounts:password_reset"),
            {"email": "nonexistent@example.com"},
        )
        self.assertEqual(res.status_code, 302)
        self.assertRedirects(res, reverse("accounts:password_reset_done"))
        # No email sent for nonexistent user
        self.assertEqual(len(mail.outbox), 0)


class LoginThrottlingTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = Client()
        self.email = "target@example.com"
        self.user = User.objects.create_user(
            email=self.email,
            password="TargetPassword1!",
        )

    def tearDown(self):
        cache.clear()

    def test_five_failed_attempts_trigger_lockout(self):
        # 5 failed login attempts
        for i in range(5):
            res = self.client.post(
                reverse("accounts:login"),
                {"email": self.email, "password": "WrongPassword1!"},
                REMOTE_ADDR="192.168.1.100",
            )
            self.assertEqual(res.status_code, 200)

        # 6th attempt should hit lockout
        res_locked = self.client.post(
            reverse("accounts:login"),
            {"email": self.email, "password": "TargetPassword1!"},  # even with correct password!
            REMOTE_ADDR="192.168.1.100",
        )
        self.assertEqual(res_locked.status_code, 200)
        self.assertContains(res_locked, "Too many failed login attempts")


class ScopeQuerysetHelperTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            email="admin_scope@subscript.local",
            password="Password1!",
        )
        self.staff = User.objects.create_user(
            email="staff_scope@subscript.local",
            password="Password1!",
            role=User.Role.STAFF,
            is_staff=True,
        )
        self.user_x = User.objects.create_user(
            email="user_x@example.com",
            password="Password1!",
            role=User.Role.CUSTOMER,
        )
        self.user_y = User.objects.create_user(
            email="user_y@example.com",
            password="Password1!",
            role=User.Role.CUSTOMER,
        )

        self.cust_x = Customer.objects.create(user=self.user_x, name="Cust X", email="x@x.com")
        self.cust_y = Customer.objects.create(user=self.user_y, name="Cust Y", email="y@y.com")

    def test_scope_queryset_for_roles(self):
        base_qs = Customer.objects.all()

        # Admin gets everything
        admin_res = scope_queryset_for_user(base_qs, self.admin, "user")
        self.assertEqual(admin_res.count(), 2)

        # Staff gets everything
        staff_res = scope_queryset_for_user(base_qs, self.staff, "user")
        self.assertEqual(staff_res.count(), 2)

        # Customer X gets only X
        cust_x_res = scope_queryset_for_user(base_qs, self.user_x, "user")
        self.assertEqual(cust_x_res.count(), 1)
        self.assertEqual(cust_x_res.first(), self.cust_x)

        # Inactive or None gets none
        self.user_x.is_active = False
        self.user_x.save()
        inactive_res = scope_queryset_for_user(base_qs, self.user_x, "user")
        self.assertEqual(inactive_res.count(), 0)

        anon_res = scope_queryset_for_user(base_qs, None, "user")
        self.assertEqual(anon_res.count(), 0)


class ErrorPagesRenderingTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.customer = User.objects.create_user(
            email="cust_err@example.com",
            password="Password1!",
            role=User.Role.CUSTOMER,
        )

    def test_403_page_rendered_for_forbidden_action(self):
        self.client.login(email=self.customer.email, password="Password1!")
        res = self.client.get(reverse("accounts:user_list"))
        self.assertEqual(res.status_code, 403)
        self.assertTemplateUsed(res, "403.html")
        self.assertContains(res, "Access Denied", status_code=403)

    def test_404_page_rendered_for_missing_resource(self):
        self.client.login(email=self.customer.email, password="Password1!")
        # Customer trying to access a customer PK they do not own
        res = self.client.get("/customers/999999/")
        self.assertEqual(res.status_code, 404)
        self.assertTemplateUsed(res, "404.html")
        self.assertContains(res, "Page Not Found", status_code=404)
