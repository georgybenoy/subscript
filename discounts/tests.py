from datetime import timedelta
from decimal import Decimal
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone
from discounts.models import Discount
from discounts import services


class DiscountModelTests(TestCase):
    """
    Tests for Discount model: creation, defaults, normalization,
    field validations, and constraints.
    """

    def setUp(self):
        self.now = timezone.now()

    def test_discount_creation_and_defaults(self):
        """Test default values on Discount creation."""
        discount = Discount.objects.create(
            code="WELCOME10",
            discount_type=Discount.DiscountType.PERCENTAGE,
            amount=Decimal("10.00"),
            valid_from=self.now,
        )
        self.assertEqual(discount.code, "WELCOME10")
        self.assertEqual(discount.discount_type, Discount.DiscountType.PERCENTAGE)
        self.assertEqual(discount.amount, Decimal("10.00"))
        self.assertTrue(discount.is_active)
        self.assertEqual(discount.times_redeemed, 0)
        self.assertIsNone(discount.valid_until)
        self.assertIsNone(discount.max_redemptions)
        self.assertIsNotNone(discount.created_at)
        self.assertIsNotNone(discount.updated_at)

    def test_discount_code_uniqueness(self):
        """Test that duplicate discount codes trigger IntegrityError / ValidationError."""
        Discount.objects.create(
            code="UNIQUECODE",
            discount_type=Discount.DiscountType.FIXED,
            amount=Decimal("50.00"),
            valid_from=self.now,
        )
        duplicate = Discount(
            code="UNIQUECODE",
            discount_type=Discount.DiscountType.PERCENTAGE,
            amount=Decimal("20.00"),
            valid_from=self.now,
        )
        with self.assertRaises(ValidationError) as ctx:
            duplicate.full_clean()
        self.assertIn("code", ctx.exception.message_dict)

        with self.assertRaises(IntegrityError):
            duplicate.save()

    def test_code_normalization_on_clean(self):
        """Test that clean() and clean_fields() strip whitespace and uppercase code."""
        discount = Discount(
            code="  save25now  ",
            discount_type=Discount.DiscountType.PERCENTAGE,
            amount=Decimal("25.00"),
            valid_from=self.now,
        )
        discount.full_clean()
        self.assertEqual(discount.code, "SAVE25NOW")

    def test_code_normalization_on_save_and_create(self):
        """Test that save() and objects.create() normalize code without full_clean()."""
        discount1 = Discount(
            code="  promo50  ",
            discount_type=Discount.DiscountType.FIXED,
            amount=Decimal("50.00"),
            valid_from=self.now,
        )
        discount1.save()
        discount1.refresh_from_db()
        self.assertEqual(discount1.code, "PROMO50")

        discount2 = Discount.objects.create(
            code="  diwali100  ",
            discount_type=Discount.DiscountType.FIXED,
            amount=Decimal("100.00"),
            valid_from=self.now,
        )
        discount2.refresh_from_db()
        self.assertEqual(discount2.code, "DIWALI100")

    def test_negative_amount_rejected(self):
        """Test that negative discount amounts fail model validation."""
        discount = Discount(
            code="NEGATIVE",
            discount_type=Discount.DiscountType.FIXED,
            amount=Decimal("-10.00"),
            valid_from=self.now,
        )
        with self.assertRaises(ValidationError) as ctx:
            discount.full_clean()
        self.assertIn("amount", ctx.exception.message_dict)

    def test_percentage_greater_than_100_rejected(self):
        """Test that percentage discounts exceeding 100% fail model validation."""
        discount = Discount(
            code="OVER100",
            discount_type=Discount.DiscountType.PERCENTAGE,
            amount=Decimal("100.01"),
            valid_from=self.now,
        )
        with self.assertRaises(ValidationError) as ctx:
            discount.full_clean()
        self.assertIn("amount", ctx.exception.message_dict)

    def test_valid_until_earlier_than_valid_from_rejected(self):
        """Test that valid_until earlier than valid_from fails model validation."""
        discount = Discount(
            code="TIMETRAVEL",
            discount_type=Discount.DiscountType.FIXED,
            amount=Decimal("50.00"),
            valid_from=self.now,
            valid_until=self.now - timedelta(days=1),
        )
        with self.assertRaises(ValidationError) as ctx:
            discount.full_clean()
        self.assertIn("valid_until", ctx.exception.message_dict)

    def test_string_representation(self):
        """Test string representation of Discount."""
        discount = Discount(
            code="DIWALI20",
            discount_type=Discount.DiscountType.PERCENTAGE,
            amount=Decimal("20.00"),
            valid_from=self.now,
        )
        self.assertIn("DIWALI20", str(discount))
        self.assertIn("20.00", str(discount))


class DiscountValidationServiceTests(TestCase):
    """
    Tests for validate_discount_code service: active status,
    date validity boundaries, redemption limits, and error messages.
    """

    def setUp(self):
        self.now = timezone.now()
        self.discount = Discount.objects.create(
            code="SUMMERSALE",
            discount_type=Discount.DiscountType.PERCENTAGE,
            amount=Decimal("15.00"),
            valid_from=self.now - timedelta(days=1),
            valid_until=self.now + timedelta(days=7),
            max_redemptions=10,
            times_redeemed=2,
            is_active=True,
        )

    def test_valid_discount_code(self):
        """Test that an active coupon within limits returns valid status."""
        is_valid, discount, message = services.validate_discount_code("SUMMERSALE", at_date=self.now)
        self.assertTrue(is_valid)
        self.assertEqual(discount, self.discount)
        self.assertIn("valid", message.lower())

    def test_case_and_whitespace_insensitivity(self):
        """Test validation with lowercase and leading/trailing whitespace."""
        is_valid, discount, _ = services.validate_discount_code("  summersale  ", at_date=self.now)
        self.assertTrue(is_valid)
        self.assertEqual(discount, self.discount)

    def test_empty_or_nonexistent_code(self):
        """Test validation failure for empty or non-existent coupon codes."""
        is_valid, discount, msg = services.validate_discount_code("")
        self.assertFalse(is_valid)
        self.assertIsNone(discount)

        is_valid, discount, msg = services.validate_discount_code("DOESNOTEXIST")
        self.assertFalse(is_valid)
        self.assertIsNone(discount)
        self.assertIn("invalid", msg.lower())

    def test_inactive_discount(self):
        """Test that deactivating a discount causes validation to fail."""
        self.discount.is_active = False
        self.discount.save()
        is_valid, discount, msg = services.validate_discount_code("SUMMERSALE", at_date=self.now)
        self.assertFalse(is_valid)
        self.assertEqual(discount, self.discount)
        self.assertIn("inactive", msg.lower())

    def test_future_discount_not_yet_valid(self):
        """Test that a discount with valid_from in the future fails validation."""
        self.discount.valid_from = self.now + timedelta(days=2)
        self.discount.save()
        is_valid, discount, msg = services.validate_discount_code("SUMMERSALE", at_date=self.now)
        self.assertFalse(is_valid)
        self.assertIn("not yet active", msg.lower())

    def test_expired_discount(self):
        """Test that an expired discount fails validation."""
        self.discount.valid_until = self.now - timedelta(seconds=1)
        self.discount.save()
        is_valid, discount, msg = services.validate_discount_code("SUMMERSALE", at_date=self.now)
        self.assertFalse(is_valid)
        self.assertIn("expired", msg.lower())

    def test_validity_exact_boundaries(self):
        """Test that exact boundary dates (valid_from and valid_until) are considered valid."""
        # Exact valid_from match
        is_valid_from, _, _ = services.validate_discount_code(
            "SUMMERSALE",
            at_date=self.discount.valid_from,
        )
        self.assertTrue(is_valid_from)

        # Exact valid_until match
        is_valid_until, _, _ = services.validate_discount_code(
            "SUMMERSALE",
            at_date=self.discount.valid_until,
        )
        self.assertTrue(is_valid_until)

    def test_exhausted_redemptions(self):
        """Test that a discount reaching its max_redemptions fails validation."""
        self.discount.times_redeemed = 10
        self.discount.save()
        is_valid, discount, msg = services.validate_discount_code("SUMMERSALE", at_date=self.now)
        self.assertFalse(is_valid)
        self.assertIn("maximum redemption limit", msg.lower())

    def test_unlimited_redemptions(self):
        """Test that max_redemptions=None allows arbitrary redemption counts."""
        self.discount.max_redemptions = None
        self.discount.times_redeemed = 9999
        self.discount.save()
        is_valid, discount, _ = services.validate_discount_code("SUMMERSALE", at_date=self.now)
        self.assertTrue(is_valid)


class DiscountCalculationServiceTests(TestCase):
    """
    Tests for get_applicable_discount calculation logic: percentage, fixed,
    capping at subtotal, decimal rounding, and non-mutation during preview.
    """

    def setUp(self):
        self.now = timezone.now()
        self.pct_discount = Discount.objects.create(
            code="PCT20",
            discount_type=Discount.DiscountType.PERCENTAGE,
            amount=Decimal("20.00"),
            valid_from=self.now - timedelta(days=1),
        )
        self.fixed_discount = Discount.objects.create(
            code="FLAT250",
            discount_type=Discount.DiscountType.FIXED,
            amount=Decimal("250.00"),
            valid_from=self.now - timedelta(days=1),
        )

    def test_percentage_calculation(self):
        """Test percentage deduction: 20% off 1000.00 = 200.00."""
        discount_amount = services.get_applicable_discount(
            discount=self.pct_discount,
            subtotal=Decimal("1000.00"),
        )
        self.assertEqual(discount_amount, Decimal("200.00"))

    def test_fixed_calculation(self):
        """Test fixed deduction: 250.00 off 1000.00 = 250.00."""
        discount_amount = services.get_applicable_discount(
            discount=self.fixed_discount,
            subtotal=Decimal("1000.00"),
        )
        self.assertEqual(discount_amount, Decimal("250.00"))

    def test_discount_capped_at_subtotal(self):
        """Test that a fixed discount larger than subtotal caps at subtotal."""
        discount_amount = services.get_applicable_discount(
            discount=self.fixed_discount,
            subtotal=Decimal("150.00"),
        )
        # Should not exceed subtotal of 150.00
        self.assertEqual(discount_amount, Decimal("150.00"))

    def test_decimal_rounding_half_up(self):
        """Test rounding half up for fractional cents (e.g. 15% off 33.33 = 4.9995 -> 5.00)."""
        pct15 = Discount.objects.create(
            code="PCT15",
            discount_type=Discount.DiscountType.PERCENTAGE,
            amount=Decimal("15.00"),
            valid_from=self.now - timedelta(days=1),
        )
        discount_amount = services.get_applicable_discount(
            discount=pct15,
            subtotal=Decimal("33.33"),
        )
        # 33.33 * 0.15 = 4.9995 -> rounded to 5.00
        self.assertEqual(discount_amount, Decimal("5.00"))

    def test_zero_and_negative_subtotal(self):
        """Test zero and negative subtotal returns Decimal('0.00')."""
        amount_zero = services.get_applicable_discount(
            discount=self.pct_discount,
            subtotal=Decimal("0.00"),
        )
        self.assertEqual(amount_zero, Decimal("0.00"))

        amount_negative = services.get_applicable_discount(
            discount=self.pct_discount,
            subtotal=Decimal("-100.00"),
        )
        self.assertEqual(amount_negative, Decimal("0.00"))

    def test_missing_subscription_discount(self):
        """Test that an object or subscription without discount returns Decimal('0.00')."""
        class DummySubscription:
            discount = None

        amount = services.get_applicable_discount(
            subscription=DummySubscription(),
            subtotal=Decimal("500.00"),
        )
        self.assertEqual(amount, Decimal("0.00"))

        amount_none = services.get_applicable_discount(
            discount=None,
            subscription=None,
            subtotal=Decimal("500.00"),
        )
        self.assertEqual(amount_none, Decimal("0.00"))

    def test_preview_never_increments_redemption(self):
        """Test that calculating applicable discount (preview) never increments times_redeemed."""
        initial_count = self.pct_discount.times_redeemed
        for _ in range(5):
            services.get_applicable_discount(
                discount=self.pct_discount,
                subtotal=Decimal("500.00"),
            )
        self.pct_discount.refresh_from_db()
        self.assertEqual(self.pct_discount.times_redeemed, initial_count)


class DiscountRedemptionServiceTests(TestCase):
    """
    Tests for atomic record_discount_redemption commit: increments,
    limit enforcement, and non-existent handling.
    """

    def setUp(self):
        self.now = timezone.now()
        self.discount = Discount.objects.create(
            code="LIMITEDREDEMPTION",
            discount_type=Discount.DiscountType.FIXED,
            amount=Decimal("50.00"),
            valid_from=self.now - timedelta(days=1),
            max_redemptions=3,
            times_redeemed=0,
            is_active=True,
        )

    def test_successful_redemption_increment(self):
        """Test that record_discount_redemption increments times_redeemed by 1."""
        success = services.record_discount_redemption(self.discount)
        self.assertTrue(success)
        self.discount.refresh_from_db()
        self.assertEqual(self.discount.times_redeemed, 1)

    def test_redemption_limit_enforcement(self):
        """Test that redemption cannot exceed max_redemptions."""
        # Exhaust all 3 redemptions
        self.assertTrue(services.record_discount_redemption(self.discount))
        self.assertTrue(services.record_discount_redemption(self.discount))
        self.assertTrue(services.record_discount_redemption(self.discount))
        self.discount.refresh_from_db()
        self.assertEqual(self.discount.times_redeemed, 3)

        # 4th attempt must fail and not increment
        failed = services.record_discount_redemption(self.discount)
        self.assertFalse(failed)
        self.discount.refresh_from_db()
        self.assertEqual(self.discount.times_redeemed, 3)

    def test_redemption_on_inactive_discount(self):
        """Test that redemption cannot be recorded for inactive discounts."""
        self.discount.is_active = False
        self.discount.save()
        success = services.record_discount_redemption(self.discount)
        self.assertFalse(success)
        self.discount.refresh_from_db()
        self.assertEqual(self.discount.times_redeemed, 0)

    def test_redemption_on_none_discount(self):
        """Test record_discount_redemption gracefully handles None."""
        self.assertFalse(services.record_discount_redemption(None))

    def test_cannot_redeem_expired_discount(self):
        """Test that an expired discount cannot be redeemed even if active."""
        expired_discount = Discount.objects.create(
            code="EXPIREDREDEMPTION",
            discount_type=Discount.DiscountType.FIXED,
            amount=Decimal("20.00"),
            valid_from=self.now - timedelta(days=10),
            valid_until=self.now - timedelta(days=1),
            is_active=True,
        )
        success = services.record_discount_redemption(expired_discount)
        self.assertFalse(success)
        expired_discount.refresh_from_db()
        self.assertEqual(expired_discount.times_redeemed, 0)

    def test_cannot_redeem_future_discount(self):
        """Test that a discount starting in the future cannot be redeemed."""
        future_discount = Discount.objects.create(
            code="FUTUREREDEMPTION",
            discount_type=Discount.DiscountType.FIXED,
            amount=Decimal("20.00"),
            valid_from=self.now + timedelta(days=2),
            is_active=True,
        )
        success = services.record_discount_redemption(future_discount)
        self.assertFalse(success)
        future_discount.refresh_from_db()
        self.assertEqual(future_discount.times_redeemed, 0)

    def test_can_redeem_currently_valid_discount(self):
        """Test that a discount currently in its validity window can be redeemed."""
        valid_discount = Discount.objects.create(
            code="CURRENTLYVALID",
            discount_type=Discount.DiscountType.PERCENTAGE,
            amount=Decimal("10.00"),
            valid_from=self.now - timedelta(hours=1),
            valid_until=self.now + timedelta(hours=1),
            max_redemptions=5,
            is_active=True,
        )
        success = services.record_discount_redemption(valid_discount)
        self.assertTrue(success)
        valid_discount.refresh_from_db()
        self.assertEqual(valid_discount.times_redeemed, 1)

    def test_unlimited_redemptions_work(self):
        """Test that max_redemptions=None allows unlimited redemptions atomically."""
        unlimited_discount = Discount.objects.create(
            code="UNLIMITEDREDEMPTION",
            discount_type=Discount.DiscountType.FIXED,
            amount=Decimal("15.00"),
            valid_from=self.now - timedelta(days=1),
            max_redemptions=None,
            is_active=True,
        )
        for i in range(1, 6):
            self.assertTrue(services.record_discount_redemption(unlimited_discount))
            unlimited_discount.refresh_from_db()
            self.assertEqual(unlimited_discount.times_redeemed, i)


class ApplyEndpointTests(TestCase):
    """
    Tests for discounts:apply endpoint (/discounts/apply/):
    GET and POST requests, JSON vs HTMX response, preview safety.
    """

    def setUp(self):
        self.client = Client()
        self.now = timezone.now()
        self.discount = Discount.objects.create(
            code="CHECKOUT20",
            discount_type=Discount.DiscountType.PERCENTAGE,
            amount=Decimal("20.00"),
            valid_from=self.now - timedelta(days=1),
            valid_until=self.now + timedelta(days=10),
            max_redemptions=5,
            times_redeemed=1,
            is_active=True,
        )

    def test_apply_endpoint_post_valid_json(self):
        """Test POST /discounts/apply/ with valid code returns 200 and calculation JSON."""
        response = self.client.post(
            reverse("discounts:apply"),
            {
                "code": "CHECKOUT20",
                "subtotal": "500.00",
                "quantity": "1",
            },
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["valid"])
        self.assertEqual(data["code"], "CHECKOUT20")
        self.assertEqual(data["discount_amount"], "100.00")
        self.assertEqual(data["final_total"], "400.00")

        # Confirm preview did not record usage
        self.discount.refresh_from_db()
        self.assertEqual(self.discount.times_redeemed, 1)

    def test_apply_endpoint_get_valid_json(self):
        """Test GET /discounts/apply/ with valid code returns preview calculation."""
        response = self.client.get(
            reverse("discounts:apply"),
            {"code": "CHECKOUT20", "subtotal": "1000.00"},
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["valid"])
        self.assertEqual(data["discount_amount"], "200.00")
        self.assertEqual(data["final_total"], "800.00")

    def test_apply_endpoint_invalid_code(self):
        """Test apply endpoint with invalid code returns valid=False and message."""
        response = self.client.post(
            reverse("discounts:apply"),
            {"code": "NONEXISTENT", "subtotal": "500.00"},
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertFalse(data["valid"])
        self.assertEqual(data["discount_amount"], "0.00")
        self.assertIn("invalid", data["message"].lower())

    def test_apply_endpoint_htmx_response(self):
        """Test that HX-Request header returns rendered HTML badge snippet."""
        response = self.client.post(
            reverse("discounts:apply"),
            {"code": "CHECKOUT20", "subtotal": "500.00"},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response["Content-Type"])
        self.assertIn(b"CHECKOUT20", response.content)
        self.assertIn(b"Applied!", response.content)
        self.assertIn(b"400.00", response.content)

    def test_apply_endpoint_invalid_subtotal(self):
        """Test apply endpoint with malformed subtotal defaults to 0.00 safely."""
        response = self.client.post(
            reverse("discounts:apply"),
            {"code": "CHECKOUT20", "subtotal": "not-a-number"},
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["valid"])
        self.assertEqual(data["subtotal"], "0.00")
        self.assertEqual(data["discount_amount"], "0.00")
        self.assertEqual(data["final_total"], "0.00")

    def test_apply_endpoint_negative_subtotal(self):
        """Test apply endpoint with negative subtotal clamps to 0.00 safely."""
        response = self.client.post(
            reverse("discounts:apply"),
            {"code": "CHECKOUT20", "subtotal": "-100.00"},
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["valid"])
        self.assertEqual(data["subtotal"], "0.00")
        self.assertEqual(data["discount_amount"], "0.00")
        self.assertEqual(data["final_total"], "0.00")

    def test_apply_endpoint_invalid_quantity(self):
        """Test apply endpoint with invalid quantity defaults to 1."""
        response = self.client.post(
            reverse("discounts:apply"),
            {"code": "CHECKOUT20", "subtotal": "100.00", "quantity": "invalid"},
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["valid"])
        self.assertEqual(data["discount_amount"], "20.00")
        self.assertEqual(data["final_total"], "80.00")

    def test_apply_endpoint_empty_code(self):
        """Test apply endpoint with empty coupon code returns valid=False."""
        response = self.client.post(
            reverse("discounts:apply"),
            {"code": "", "subtotal": "100.00"},
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertFalse(data["valid"])
        self.assertEqual(data["code"], "")
        self.assertEqual(data["discount_amount"], "0.00")
        self.assertIn("empty", data["message"].lower())

    def test_apply_endpoint_preview_never_increments_redemptions(self):
        """Test that preview requests via endpoint never change times_redeemed."""
        initial_count = self.discount.times_redeemed
        for _ in range(5):
            self.client.post(
                reverse("discounts:apply"),
                {"code": "CHECKOUT20", "subtotal": "200.00"},
            )
            self.client.get(
                reverse("discounts:apply"),
                {"code": "CHECKOUT20", "subtotal": "200.00"},
            )
        self.discount.refresh_from_db()
        self.assertEqual(self.discount.times_redeemed, initial_count)


from django.contrib.auth import get_user_model
User = get_user_model()


class DiscountViewsSecurityTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.admin = User.objects.create_user(
            email='admin@test.com', password='password123', role=User.Role.ADMIN
        )
        self.staff = User.objects.create_user(
            email='staff@test.com', password='password123', role=User.Role.STAFF
        )
        self.customer = User.objects.create_user(
            email='cust@test.com', password='password123', role=User.Role.CUSTOMER
        )
        self.discount = Discount.objects.create(
            code='TEST10',
            discount_type=Discount.DiscountType.PERCENTAGE,
            amount=Decimal('10.00'),
            valid_from=timezone.now(),
        )

    def test_anonymous_redirects_to_login(self):
        resp = self.client.get(reverse('discounts:discount_list'))
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/accounts/login/', resp.url)

    def test_customer_denied_403(self):
        self.client.force_login(self.customer)
        resp = self.client.get(reverse('discounts:discount_list'))
        self.assertEqual(resp.status_code, 403)

        resp_create = self.client.get(reverse('discounts:discount_create'))
        self.assertEqual(resp_create.status_code, 403)

    def test_staff_admin_allowed_200(self):
        self.client.force_login(self.staff)
        resp = self.client.get(reverse('discounts:discount_list'))
        self.assertEqual(resp.status_code, 200)

        self.client.force_login(self.admin)
        resp = self.client.get(reverse('discounts:discount_list'))
        self.assertEqual(resp.status_code, 200)

    def test_create_discount_post(self):
        self.client.force_login(self.admin)
        resp = self.client.post(
            reverse('discounts:discount_create'),
            {
                'code': 'PROMO2026',
                'discount_type': Discount.DiscountType.PERCENTAGE,
                'amount': '15.00',
                'valid_from': str(timezone.localdate()),
                'max_redemptions': '100',
            },
        )
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(Discount.objects.filter(code='PROMO2026').exists())
