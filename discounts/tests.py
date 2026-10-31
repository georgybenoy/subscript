from datetime import timedelta
from decimal import Decimal
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from .models import Discount, DiscountType
from .services import (
    apply_discount,
    calculate_discount_amount,
    is_discount_valid,
    search_and_filter_discounts,
)

User = get_user_model()


class DiscountModelValidationTests(TestCase):
    def test_percentage_discount_valid_range(self):
        d = Discount(
            code="PERC20",
            discount_type=DiscountType.PERCENTAGE,
            amount=Decimal("20.00"),
        )
        d.full_clean()
        d.save()
        self.assertEqual(d.code, "PERC20")

    def test_percentage_discount_cannot_exceed_100(self):
        d = Discount(
            code="INVALID150",
            discount_type=DiscountType.PERCENTAGE,
            amount=Decimal("150.00"),
        )
        with self.assertRaises(ValidationError):
            d.full_clean()

    def test_fixed_discount_must_be_positive(self):
        d = Discount(
            code="ZEROFIXED",
            discount_type=DiscountType.FIXED,
            amount=Decimal("0.00"),
        )
        with self.assertRaises(ValidationError):
            d.full_clean()

    def test_end_date_cannot_be_before_start_date(self):
        today = timezone.localdate()
        d = Discount(
            code="DATEERR",
            discount_type=DiscountType.PERCENTAGE,
            amount=Decimal("10.00"),
            start_date=today,
            end_date=today - timedelta(days=1),
        )
        with self.assertRaises(ValidationError):
            d.full_clean()


class DiscountServicesTests(TestCase):
    def setUp(self):
        self.today = timezone.localdate()
        self.percent_disc = Discount.objects.create(
            code="SAVE25",
            discount_type=DiscountType.PERCENTAGE,
            amount=Decimal("25.00"),
            start_date=self.today - timedelta(days=5),
            end_date=self.today + timedelta(days=5),
            usage_limit=10,
            times_used=0,
            is_active=True,
        )
        self.fixed_disc = Discount.objects.create(
            code="FLAT50",
            discount_type=DiscountType.FIXED,
            amount=Decimal("50.00"),
            start_date=self.today - timedelta(days=2),
            end_date=self.today + timedelta(days=2),
            usage_limit=5,
            times_used=0,
            is_active=True,
        )

    def test_is_discount_valid(self):
        self.assertTrue(is_discount_valid(self.percent_disc, on_date=self.today))

        # Inactive
        self.percent_disc.is_active = False
        self.assertFalse(is_discount_valid(self.percent_disc, on_date=self.today))
        self.percent_disc.is_active = True

        # Expired by date
        past_date = self.today + timedelta(days=10)
        self.assertFalse(is_discount_valid(self.percent_disc, on_date=past_date))

        # Before start date
        future_start = self.today - timedelta(days=10)
        self.assertFalse(is_discount_valid(self.percent_disc, on_date=future_start))

        # Usage limit reached
        self.percent_disc.times_used = 10
        self.assertFalse(is_discount_valid(self.percent_disc, on_date=self.today))

    def test_calculate_discount_amount_percentage(self):
        # 25% of 200 is 50.00
        amt = calculate_discount_amount(self.percent_disc, Decimal("200.00"))
        self.assertEqual(amt, Decimal("50.00"))

        # Capped at subtotal
        amt_capped = calculate_discount_amount(self.percent_disc, Decimal("30.00"))
        self.assertEqual(amt_capped, Decimal("7.50"))

    def test_calculate_discount_amount_fixed(self):
        # 50.00 flat off 100.00 -> 50.00
        amt = calculate_discount_amount(self.fixed_disc, Decimal("100.00"))
        self.assertEqual(amt, Decimal("50.00"))

        # Capped at subtotal if subtotal < fixed discount
        amt_capped = calculate_discount_amount(self.fixed_disc, Decimal("35.00"))
        self.assertEqual(amt_capped, Decimal("35.00"))

    def test_apply_discount_atomic(self):
        success = apply_discount(self.percent_disc)
        self.assertTrue(success)
        self.percent_disc.refresh_from_db()
        self.assertEqual(self.percent_disc.times_used, 1)

    def test_search_and_filter_discounts(self):
        qs = Discount.objects.all()
        res = search_and_filter_discounts(qs, query="SAVE")
        self.assertEqual(res.count(), 1)
        self.assertEqual(res.first().code, "SAVE25")

        res_type = search_and_filter_discounts(qs, discount_type="FIXED")
        self.assertEqual(res_type.count(), 1)
        self.assertEqual(res_type.first().code, "FLAT50")


class DiscountViewsSecurityTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.admin = User.objects.create_user(
            email="admin@test.com", password="password123", role=User.Role.ADMIN
        )
        self.staff = User.objects.create_user(
            email="staff@test.com", password="password123", role=User.Role.STAFF
        )
        self.customer = User.objects.create_user(
            email="cust@test.com", password="password123", role=User.Role.CUSTOMER
        )
        self.discount = Discount.objects.create(
            code="TEST10",
            discount_type=DiscountType.PERCENTAGE,
            amount=Decimal("10.00"),
        )

    def test_anonymous_redirects_to_login(self):
        resp = self.client.get(reverse("discounts:discount_list"))
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/accounts/login/", resp.url)

    def test_customer_denied_403(self):
        self.client.force_login(self.customer)
        resp = self.client.get(reverse("discounts:discount_list"))
        self.assertEqual(resp.status_code, 403)

        resp_create = self.client.get(reverse("discounts:discount_create"))
        self.assertEqual(resp_create.status_code, 403)

    def test_staff_admin_allowed_200(self):
        self.client.force_login(self.staff)
        resp = self.client.get(reverse("discounts:discount_list"))
        self.assertEqual(resp.status_code, 200)

        self.client.force_login(self.admin)
        resp = self.client.get(reverse("discounts:discount_list"))
        self.assertEqual(resp.status_code, 200)

    def test_create_discount_post(self):
        self.client.force_login(self.admin)
        resp = self.client.post(
            reverse("discounts:discount_create"),
            {
                "code": "PROMO2026",
                "discount_type": DiscountType.PERCENTAGE,
                "amount": "15.00",
                "valid_from": str(timezone.localdate()),
                "max_redemptions": "100",
            },
        )
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(Discount.objects.filter(code="PROMO2026").exists())
