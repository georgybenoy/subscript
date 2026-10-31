from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.http import Http404
from django.test import Client, TestCase
from django.urls import reverse
from .forms import CustomerForm, validate_phone_number
from .models import Customer
from . import services

User = get_user_model()


class CustomerServiceTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            email="admin@subscript.local",
            password="AdminPassword1!",
        )
        self.staff = User.objects.create_user(
            email="staff@subscript.local",
            password="StaffPassword1!",
            role=User.Role.STAFF,
            is_staff=True,
        )
        self.user_a = User.objects.create_user(
            email="usera@example.com",
            password="UserPassword1!",
            role=User.Role.CUSTOMER,
        )
        self.user_b = User.objects.create_user(
            email="userb@example.com",
            password="UserPassword1!",
            role=User.Role.CUSTOMER,
        )

        self.cust_a = Customer.objects.create(
            user=self.user_a,
            name="Alice Corp",
            company_name="Acme Global",
            email="alice@acme.com",
            phone="+91 98765 11111",
            city="Bengaluru",
            state="Karnataka",
            country="IN",
            tax_id="GSTIN1111",
            is_active=True,
        )
        self.cust_b = Customer.objects.create(
            user=self.user_b,
            name="Bob Ltd",
            company_name="Beta Systems",
            email="bob@beta.com",
            phone="+91 98765 22222",
            city="Mumbai",
            state="Maharashtra",
            country="IN",
            tax_id="GSTIN2222",
            is_active=False,
        )

    def test_get_customers_for_user_roles(self):
        # Admin gets all
        admin_qs = services.get_customers_for_user(self.admin)
        self.assertEqual(admin_qs.count(), 2)

        # Staff gets all
        staff_qs = services.get_customers_for_user(self.staff)
        self.assertEqual(staff_qs.count(), 2)

        # User A gets only own profile
        user_a_qs = services.get_customers_for_user(self.user_a)
        self.assertEqual(user_a_qs.count(), 1)
        self.assertEqual(user_a_qs.first(), self.cust_a)

    def test_get_customer_for_user_or_404_idor_prevention(self):
        # User A accessing Customer A -> OK
        cust = services.get_customer_for_user_or_404(self.user_a, self.cust_a.pk)
        self.assertEqual(cust, self.cust_a)

        # User A accessing Customer B -> 404
        with self.assertRaises(Http404):
            services.get_customer_for_user_or_404(self.user_a, self.cust_b.pk)

        # Admin accessing Customer B -> OK
        admin_access = services.get_customer_for_user_or_404(self.admin, self.cust_b.pk)
        self.assertEqual(admin_access, self.cust_b)

    def test_search_and_filter(self):
        qs = Customer.objects.all()

        # Search by company
        res_company = services.search_and_filter_customers(qs, query="Beta")
        self.assertEqual(res_company.count(), 1)
        self.assertEqual(res_company.first(), self.cust_b)

        # Search by phone
        res_phone = services.search_and_filter_customers(qs, query="11111")
        self.assertEqual(res_phone.count(), 1)
        self.assertEqual(res_phone.first(), self.cust_a)

        # Filter by status active
        res_active = services.search_and_filter_customers(qs, status="active")
        self.assertEqual(res_active.count(), 1)
        self.assertEqual(res_active.first(), self.cust_a)

        # Filter by status inactive
        res_inactive = services.search_and_filter_customers(qs, status="inactive")
        self.assertEqual(res_inactive.count(), 1)
        self.assertEqual(res_inactive.first(), self.cust_b)

        # Combined filter
        res_comb = services.search_and_filter_customers(qs, query="Alice", city="Bengaluru", status="active")
        self.assertEqual(res_comb.count(), 1)

    def test_link_and_unlink_user(self):
        cust_orphan = Customer.objects.create(name="Orphan", email="orphan@test.com")
        new_user = User.objects.create_user(email="newcustomer@test.com", password="Pass123!word")

        # Link to customer user
        services.link_customer_to_user(cust_orphan, new_user)
        self.assertEqual(cust_orphan.user, new_user)

        # Link to staff user fails
        with self.assertRaises(ValidationError):
            services.link_customer_to_user(cust_orphan, self.staff)

        # Unlink user
        services.unlink_customer_user(cust_orphan)
        self.assertIsNone(cust_orphan.user)


class CustomerViewPermissionTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.password = "SecuredPassword1!"

        self.admin = User.objects.create_superuser(
            email="admin_v@subscript.local",
            password=self.password,
        )
        self.staff = User.objects.create_user(
            email="staff_v@subscript.local",
            password=self.password,
            role=User.Role.STAFF,
            is_staff=True,
        )
        self.user_a = User.objects.create_user(
            email="usera_v@example.com",
            password=self.password,
            role=User.Role.CUSTOMER,
        )
        self.user_b = User.objects.create_user(
            email="userb_v@example.com",
            password=self.password,
            role=User.Role.CUSTOMER,
        )

        self.cust_a = Customer.objects.create(
            user=self.user_a,
            name="Alice View Corp",
            email="alice_v@acme.com",
            phone="+91 99999 11111",
            city="Chennai",
            is_active=True,
        )
        self.cust_b = Customer.objects.create(
            user=self.user_b,
            name="Bob View Corp",
            email="bob_v@beta.com",
            phone="+91 99999 22222",
            city="Delhi",
            is_active=True,
        )

    def test_anonymous_redirected_to_login(self):
        urls = [
            reverse("customers:list"),
            reverse("customers:create"),
            reverse("customers:detail", kwargs={"pk": self.cust_a.pk}),
            reverse("customers:edit", kwargs={"pk": self.cust_a.pk}),
        ]
        for url in urls:
            res = self.client.get(url)
            self.assertEqual(res.status_code, 302)
            self.assertTrue(res.url.startswith(reverse("accounts:login")))

    def test_admin_and_staff_can_create_customer(self):
        self.client.login(email=self.staff.email, password=self.password)
        res = self.client.post(
            reverse("customers:create"),
            {
                "name": "New Corp",
                "company_name": "New Ventures Ltd",
                "email": "new@corp.com",
                "phone": "+91 88888 77777",
                "country": "IN",
                "is_active": True,
            },
        )
        self.assertEqual(res.status_code, 302)
        self.assertTrue(Customer.objects.filter(email="new@corp.com").exists())

    def test_customer_cannot_create_customer(self):
        self.client.login(email=self.user_a.email, password=self.password)
        res = self.client.get(reverse("customers:create"))
        self.assertEqual(res.status_code, 403)

        res_post = self.client.post(reverse("customers:create"), {"name": "Hacker Corp", "email": "hacker@corp.com"})
        self.assertEqual(res_post.status_code, 403)

    def test_customer_cannot_toggle_status(self):
        self.client.login(email=self.user_a.email, password=self.password)
        res = self.client.post(reverse("customers:status_toggle", kwargs={"pk": self.cust_a.pk}))
        self.assertEqual(res.status_code, 403)

    def test_staff_can_toggle_status(self):
        self.client.login(email=self.staff.email, password=self.password)
        res = self.client.post(reverse("customers:status_toggle", kwargs={"pk": self.cust_a.pk}))
        self.assertEqual(res.status_code, 302)
        self.cust_a.refresh_from_db()
        self.assertFalse(self.cust_a.is_active)

    def test_customer_cannot_access_other_customer(self):
        # User A attempting to view Customer B detail -> 404
        self.client.login(email=self.user_a.email, password=self.password)
        res_detail = self.client.get(reverse("customers:detail", kwargs={"pk": self.cust_b.pk}))
        self.assertEqual(res_detail.status_code, 404)

        # User A attempting to edit Customer B -> 404
        res_edit = self.client.get(reverse("customers:edit", kwargs={"pk": self.cust_b.pk}))
        self.assertEqual(res_edit.status_code, 404)

    def test_customer_sees_only_own_record_in_list(self):
        self.client.login(email=self.user_a.email, password=self.password)
        res = self.client.get(reverse("customers:list"))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "Alice View Corp")
        self.assertNotContains(res, "Bob View Corp")


class CustomerHTMXAndPaginationTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.password = "ComplexPass1!"
        self.staff = User.objects.create_user(
            email="staff_htmx@subscript.local",
            password=self.password,
            role=User.Role.STAFF,
            is_staff=True,
        )
        self.client.login(email=self.staff.email, password=self.password)

        # Create 25 customers to trigger pagination (page size = 15)
        for i in range(25):
            Customer.objects.create(
                name=f"Customer {i:02d}",
                company_name="Batch Enterprise",
                email=f"batch_{i:02d}@example.com",
                phone=f"+91 90000 {i:05d}",
                city="Pune",
                is_active=True,
            )

    def test_htmx_request_returns_partial_only(self):
        res = self.client.get(
            reverse("customers:list"),
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(res.status_code, 200)
        # Should contain table markup
        self.assertContains(res, "<table")
        # Should NOT contain base.html layout navigation
        self.assertNotContains(res, "<nav class=\"navbar")

    def test_pagination_retains_filters(self):
        res = self.client.get(
            f"{reverse('customers:list')}?q=Batch&city=Pune&page=2"
        )
        self.assertEqual(res.status_code, 200)
        self.assertIn("q=Batch", res.context["preserved_query"])
        self.assertIn("city=Pune", res.context["preserved_query"])
        self.assertNotIn("page=2", res.context["preserved_query"])


class CustomerFormValidationTests(TestCase):
    def test_phone_validator_valid(self):
        self.assertEqual(validate_phone_number("+91 98765 43210"), "+91 98765 43210")
        self.assertEqual(validate_phone_number("1234567890"), "1234567890")
        self.assertEqual(validate_phone_number("+1-555-123-4567"), "+1-555-123-4567")

    def test_phone_validator_invalid_characters(self):
        with self.assertRaises(ValidationError):
            validate_phone_number("invalid-phone-abc")

    def test_phone_validator_too_short(self):
        with self.assertRaises(ValidationError):
            validate_phone_number("12345")

    def test_customer_form_excludes_is_active_for_customer(self):
        customer_user = User(role=User.Role.CUSTOMER)
        form = CustomerForm(user=customer_user)
        self.assertNotIn("is_active", form.fields)

        admin_user = User(role=User.Role.ADMIN)
        form_admin = CustomerForm(user=admin_user)
        self.assertIn("is_active", form_admin.fields)
