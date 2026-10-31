import calendar
from datetime import datetime, timedelta
from decimal import Decimal
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone
from customers.models import Customer
from discounts.models import Discount
from products.models import Plan, Product, ProductVariant
from subscriptions.models import Subscription, SubscriptionItem
from subscriptions import services

User = get_user_model()


class SubscriptionModelTests(TestCase):
    """
    Tests for Subscription and SubscriptionItem models:
    defaults, validation, monetary calculations, string representations.
    """

    def setUp(self):
        self.now = timezone.now()
        self.customer = Customer.objects.create(
            name="Acme Corp",
            email="billing@acme.com",
            is_active=True,
        )
        self.product = Product.objects.create(
            name="Cloud Storage",
            is_active=True,
        )
        self.plan = Plan.objects.create(
            product=self.product,
            name="Pro Monthly",
            code="STORAGE-PRO-MONTHLY",
            billing_interval=Plan.BillingInterval.MONTHLY,
            price=Decimal("100.00"),
            currency="USD",
            trial_days=0,
            is_active=True,
        )

    def test_subscription_creation_and_defaults(self):
        """Test default values on Subscription creation."""
        sub = Subscription.objects.create(
            customer=self.customer,
            plan=self.plan,
            current_period_start=self.now,
            current_period_end=self.now + timedelta(days=30),
        )
        self.assertEqual(sub.status, Subscription.Status.ACTIVE)
        self.assertFalse(sub.cancel_at_period_end)
        self.assertIsNone(sub.discount)
        self.assertIsNone(sub.paused_at)
        self.assertIsNotNone(sub.created_at)
        self.assertIsNotNone(sub.updated_at)
        self.assertIn("Acme Corp", str(sub))
        self.assertIn("Pro Monthly", str(sub))

    def test_subscription_period_end_before_start_rejected(self):
        """Test validation error when current_period_end <= current_period_start."""
        sub = Subscription(
            customer=self.customer,
            plan=self.plan,
            current_period_start=self.now,
            current_period_end=self.now - timedelta(days=1),
        )
        with self.assertRaises(ValidationError) as ctx:
            sub.full_clean()
        self.assertIn("current_period_end", ctx.exception.message_dict)

    def test_subscription_items_and_subtotal(self):
        """Test that get_subtotal() sums plan base price and addon items."""
        variant1 = ProductVariant.objects.create(
            product=self.product,
            name="100GB Extra",
            sku="EXTRA-100GB",
            price=Decimal("15.00"),
            is_active=True,
        )
        variant2 = ProductVariant.objects.create(
            product=self.product,
            name="Dedicated IP",
            sku="DEDICATED-IP",
            price=Decimal("25.00"),
            is_active=True,
        )

        sub = Subscription.objects.create(
            customer=self.customer,
            plan=self.plan,
            current_period_start=self.now,
            current_period_end=self.now + timedelta(days=30),
        )

        # Plan base price is 100.00
        self.assertEqual(sub.get_subtotal(), Decimal("100.00"))

        # Add item: 2 * 15.00 = 30.00
        SubscriptionItem.objects.create(
            subscription=sub,
            variant=variant1,
            quantity=2,
            unit_price=Decimal("15.00"),
        )
        # Add item: 1 * 25.00 = 25.00
        SubscriptionItem.objects.create(
            subscription=sub,
            variant=variant2,
            quantity=1,
            unit_price=Decimal("25.00"),
        )

        # 100.00 + 30.00 + 25.00 = 155.00
        self.assertEqual(sub.get_subtotal(), Decimal("155.00"))
        self.assertEqual(sub.get_total(), Decimal("155.00"))

    def test_subscription_item_validation(self):
        """Test item quantity and unit_price constraints."""
        sub = Subscription.objects.create(
            customer=self.customer,
            plan=self.plan,
            current_period_start=self.now,
            current_period_end=self.now + timedelta(days=30),
        )
        invalid_item = SubscriptionItem(
            subscription=sub,
            quantity=0,
            unit_price=Decimal("-5.00"),
        )
        with self.assertRaises(ValidationError) as ctx:
            invalid_item.full_clean()
        self.assertIn("quantity", ctx.exception.message_dict)
        self.assertIn("unit_price", ctx.exception.message_dict)

    def test_discount_integration(self):
        """Test that get_discount_amount() and get_total() apply attached discount."""
        discount = Discount.objects.create(
            code="FLAT20OFF",
            discount_type=Discount.DiscountType.FIXED,
            amount=Decimal("20.00"),
            valid_from=self.now - timedelta(days=1),
            is_active=True,
        )
        sub = Subscription.objects.create(
            customer=self.customer,
            plan=self.plan,  # price: 100.00
            discount=discount,
            current_period_start=self.now,
            current_period_end=self.now + timedelta(days=30),
        )
        self.assertEqual(sub.get_subtotal(), Decimal("100.00"))
        self.assertEqual(sub.get_discount_amount(), Decimal("20.00"))
        self.assertEqual(sub.get_total(), Decimal("80.00"))


class BillingDateCalculationTests(TestCase):
    """
    Tests for calculate_next_billing_date across all four billing intervals:
    Weekly, Monthly, Quarterly, Yearly, with month-end clipping and leap years.
    """

    def test_weekly_interval(self):
        """Test weekly interval adds exactly 7 days."""
        start = timezone.make_aware(datetime(2026, 5, 1, 10, 0, 0))
        expected = timezone.make_aware(datetime(2026, 5, 8, 10, 0, 0))
        self.assertEqual(
            services.calculate_next_billing_date(start, Plan.BillingInterval.WEEKLY),
            expected,
        )

    def test_monthly_interval_regular(self):
        """Test regular monthly calculation (March 15 -> April 15)."""
        start = timezone.make_aware(datetime(2026, 3, 15, 14, 30, 0))
        expected = timezone.make_aware(datetime(2026, 4, 15, 14, 30, 0))
        self.assertEqual(
            services.calculate_next_billing_date(start, Plan.BillingInterval.MONTHLY),
            expected,
        )

    def test_monthly_interval_year_rollover(self):
        """Test monthly interval across year boundary (December 20 -> January 20 next year)."""
        start = timezone.make_aware(datetime(2026, 12, 20, 9, 0, 0))
        expected = timezone.make_aware(datetime(2027, 1, 20, 9, 0, 0))
        self.assertEqual(
            services.calculate_next_billing_date(start, Plan.BillingInterval.MONTHLY),
            expected,
        )

    def test_monthly_month_end_clipping_january_to_february_non_leap(self):
        """Test Jan 31 clips to Feb 28 in a non-leap year (2025)."""
        start = timezone.make_aware(datetime(2025, 1, 31, 12, 0, 0))
        expected = timezone.make_aware(datetime(2025, 2, 28, 12, 0, 0))
        self.assertEqual(
            services.calculate_next_billing_date(start, Plan.BillingInterval.MONTHLY),
            expected,
        )

    def test_monthly_month_end_clipping_january_to_february_leap_year(self):
        """Test Jan 31 clips to Feb 29 in a leap year (2024)."""
        start = timezone.make_aware(datetime(2024, 1, 31, 12, 0, 0))
        expected = timezone.make_aware(datetime(2024, 2, 29, 12, 0, 0))
        self.assertEqual(
            services.calculate_next_billing_date(start, Plan.BillingInterval.MONTHLY),
            expected,
        )

    def test_monthly_month_end_clipping_march_to_april(self):
        """Test March 31 clips to April 30 (30-day month)."""
        start = timezone.make_aware(datetime(2026, 3, 31, 12, 0, 0))
        expected = timezone.make_aware(datetime(2026, 4, 30, 12, 0, 0))
        self.assertEqual(
            services.calculate_next_billing_date(start, Plan.BillingInterval.MONTHLY),
            expected,
        )

    def test_quarterly_interval_regular(self):
        """Test quarterly interval (Jan 10 -> April 10)."""
        start = timezone.make_aware(datetime(2026, 1, 10, 8, 0, 0))
        expected = timezone.make_aware(datetime(2026, 4, 10, 8, 0, 0))
        self.assertEqual(
            services.calculate_next_billing_date(start, Plan.BillingInterval.QUARTERLY),
            expected,
        )

    def test_quarterly_month_end_clipping(self):
        """Test quarterly interval clipping (Jan 31 -> April 30)."""
        start = timezone.make_aware(datetime(2026, 1, 31, 8, 0, 0))
        expected = timezone.make_aware(datetime(2026, 4, 30, 8, 0, 0))
        self.assertEqual(
            services.calculate_next_billing_date(start, Plan.BillingInterval.QUARTERLY),
            expected,
        )

    def test_yearly_interval_regular(self):
        """Test regular yearly interval (June 1, 2026 -> June 1, 2027)."""
        start = timezone.make_aware(datetime(2026, 6, 1, 0, 0, 0))
        expected = timezone.make_aware(datetime(2027, 6, 1, 0, 0, 0))
        self.assertEqual(
            services.calculate_next_billing_date(start, Plan.BillingInterval.YEARLY),
            expected,
        )

    def test_yearly_leap_year_clipping(self):
        """Test Feb 29 in leap year (2024) clips to Feb 28 in non-leap year (2025)."""
        start = timezone.make_aware(datetime(2024, 2, 29, 12, 0, 0))
        expected = timezone.make_aware(datetime(2025, 2, 28, 12, 0, 0))
        self.assertEqual(
            services.calculate_next_billing_date(start, Plan.BillingInterval.YEARLY),
            expected,
        )

    def test_unsupported_interval_raises_error(self):
        """Test invalid billing interval raises ValidationError."""
        start = timezone.now()
        with self.assertRaises(ValidationError):
            services.calculate_next_billing_date(start, "HOURLY")


class SubscriptionLifecycleServiceTests(TestCase):
    """
    Tests for subscription lifecycle state machine:
    create, confirm, activate, pause, resume, cancel, and renew.
    """

    def setUp(self):
        self.now = timezone.now()
        self.customer = Customer.objects.create(
            name="Alpha Corp",
            email="contact@alpha.com",
            is_active=True,
        )
        self.product = Product.objects.create(name="Pro SaaS", is_active=True)
        self.paid_plan = Plan.objects.create(
            product=self.product,
            name="Standard Monthly",
            code="SAAS-MONTHLY",
            billing_interval=Plan.BillingInterval.MONTHLY,
            price=Decimal("50.00"),
            trial_days=0,
            is_active=True,
        )
        self.trial_plan = Plan.objects.create(
            product=self.product,
            name="Trial Plan 14d",
            code="SAAS-TRIAL-14D",
            billing_interval=Plan.BillingInterval.MONTHLY,
            price=Decimal("50.00"),
            trial_days=14,
            is_active=True,
        )

    def test_create_subscription_without_trial(self):
        """Test creating subscription on a non-trial plan starts in ACTIVE status."""
        sub = services.create_subscription(
            customer=self.customer,
            plan=self.paid_plan,
            start_date=self.now,
        )
        self.assertEqual(sub.status, Subscription.Status.ACTIVE)
        self.assertEqual(sub.current_period_start, self.now)
        expected_end = services.calculate_next_billing_date(self.now, Plan.BillingInterval.MONTHLY)
        self.assertEqual(sub.current_period_end, expected_end)

    def test_create_subscription_with_trial(self):
        """Test creating subscription on a trial plan starts in TRIALING status."""
        sub = services.create_subscription(
            customer=self.customer,
            plan=self.trial_plan,
            start_date=self.now,
        )
        self.assertEqual(sub.status, Subscription.Status.TRIALING)
        self.assertEqual(sub.current_period_start, self.now)
        self.assertEqual(sub.current_period_end, self.now + timedelta(days=14))

    def test_create_subscription_inactive_customer_rejected(self):
        """Test creating subscription fails if customer is inactive."""
        self.customer.is_active = False
        self.customer.save()
        with self.assertRaises(ValidationError) as ctx:
            services.create_subscription(customer=self.customer, plan=self.paid_plan)
        self.assertIn("Customer is inactive", str(ctx.exception))

    def test_create_subscription_inactive_plan_rejected(self):
        """Test creating subscription fails if plan is inactive."""
        self.paid_plan.is_active = False
        self.paid_plan.save()
        with self.assertRaises(ValidationError) as ctx:
            services.create_subscription(customer=self.customer, plan=self.paid_plan)
        self.assertIn("Plan is inactive", str(ctx.exception))

    def test_create_subscription_with_discount(self):
        """Test creating subscription with active discount attaches successfully."""
        discount = Discount.objects.create(
            code="SAVE10",
            discount_type=Discount.DiscountType.PERCENTAGE,
            amount=Decimal("10.00"),
            valid_from=self.now - timedelta(days=1),
            is_active=True,
        )
        sub = services.create_subscription(
            customer=self.customer,
            plan=self.paid_plan,
            discount=discount,
        )
        self.assertEqual(sub.discount, discount)

    def test_create_subscription_with_invalid_discount_rejected(self):
        """Test creating subscription with expired discount raises ValidationError."""
        expired_discount = Discount.objects.create(
            code="EXPIRED",
            discount_type=Discount.DiscountType.PERCENTAGE,
            amount=Decimal("10.00"),
            valid_from=self.now - timedelta(days=10),
            valid_until=self.now - timedelta(days=1),
            is_active=True,
        )
        with self.assertRaises(ValidationError):
            services.create_subscription(
                customer=self.customer,
                plan=self.paid_plan,
                discount=expired_discount,
            )

    def test_confirm_subscription(self):
        """Test confirm_subscription validates customer and plan readiness."""
        sub = services.create_subscription(customer=self.customer, plan=self.paid_plan)
        confirmed = services.confirm_subscription(sub)
        self.assertEqual(confirmed.pk, sub.pk)

    def test_activate_subscription_from_trial(self):
        """Test activating a TRIALING subscription transitions to ACTIVE and starts billing cycle."""
        sub = services.create_subscription(
            customer=self.customer,
            plan=self.trial_plan,
            start_date=self.now,
        )
        self.assertEqual(sub.status, Subscription.Status.TRIALING)

        activated = services.activate_subscription(sub)
        self.assertEqual(activated.status, Subscription.Status.ACTIVE)
        self.assertGreaterEqual(activated.current_period_end, activated.current_period_start)

    def test_activate_subscription_invalid_status_rejected(self):
        """Test activating an already CANCELED subscription is rejected."""
        sub = services.create_subscription(customer=self.customer, plan=self.paid_plan)
        services.close_subscription(sub, immediate=True)
        with self.assertRaises(ValidationError):
            services.activate_subscription(sub)

    def test_pause_and_resume_preserves_unused_paid_time(self):
        """
        Test that pausing sets status=PAUSED and paused_at, and resuming
        extends current_period_end by the exact paused duration.
        """
        start = timezone.now()
        sub = services.create_subscription(
            customer=self.customer,
            plan=self.paid_plan,
            start_date=start,
        )
        original_end = sub.current_period_end

        # Pause 5 days into cycle
        pause_date = start + timedelta(days=5)
        services.pause_subscription(sub, at_date=pause_date)
        sub.refresh_from_db()
        self.assertEqual(sub.status, Subscription.Status.PAUSED)
        self.assertEqual(sub.paused_at, pause_date)

        # Resume 10 days later (paused for exactly 10 days)
        resume_date = pause_date + timedelta(days=10)
        services.resume_subscription(sub, at_date=resume_date)
        sub.refresh_from_db()

        self.assertEqual(sub.status, Subscription.Status.ACTIVE)
        self.assertIsNone(sub.paused_at)
        # Period end should be extended by exactly 10 days
        self.assertEqual(sub.current_period_end, original_end + timedelta(days=10))

    def test_cannot_pause_non_active_subscription(self):
        """Test that pausing a PAUSED or CANCELED subscription fails."""
        sub = services.create_subscription(customer=self.customer, plan=self.paid_plan)
        services.pause_subscription(sub)
        # Attempting to pause again
        with self.assertRaises(ValidationError):
            services.pause_subscription(sub)

    def test_cannot_resume_non_paused_subscription(self):
        """Test that resuming an ACTIVE subscription fails."""
        sub = services.create_subscription(customer=self.customer, plan=self.paid_plan)
        with self.assertRaises(ValidationError):
            services.resume_subscription(sub)

    def test_immediate_cancellation(self):
        """Test immediate cancellation transitions status to CANCELED."""
        sub = services.create_subscription(customer=self.customer, plan=self.paid_plan)
        services.close_subscription(sub, immediate=True)
        sub.refresh_from_db()
        self.assertEqual(sub.status, Subscription.Status.CANCELED)
        self.assertFalse(sub.cancel_at_period_end)

    def test_period_end_cancellation(self):
        """Test period-end cancellation flags cancel_at_period_end while remaining ACTIVE."""
        sub = services.create_subscription(customer=self.customer, plan=self.paid_plan)
        services.close_subscription(sub, immediate=False)
        sub.refresh_from_db()
        self.assertEqual(sub.status, Subscription.Status.ACTIVE)
        self.assertTrue(sub.cancel_at_period_end)

    def test_resume_earlier_timestamp_rejected(self):
        """Test resuming with a timestamp earlier than paused_at raises ValidationError."""
        start = timezone.now()
        sub = services.create_subscription(
            customer=self.customer,
            plan=self.paid_plan,
            start_date=start,
        )
        pause_date = start + timedelta(days=2)
        services.pause_subscription(sub, at_date=pause_date)
        sub.refresh_from_db()
        self.assertEqual(sub.status, Subscription.Status.PAUSED)
        self.assertEqual(sub.paused_at, pause_date)

        # Attempt to resume before pause_date
        earlier_date = pause_date - timedelta(minutes=5)
        with self.assertRaises(ValidationError) as ctx:
            services.resume_subscription(sub, at_date=earlier_date)
        self.assertIn("earlier than pause date", str(ctx.exception))

        # Confirm paused_at is NOT cleared and status remains PAUSED
        sub.refresh_from_db()
        self.assertEqual(sub.status, Subscription.Status.PAUSED)
        self.assertEqual(sub.paused_at, pause_date)

    def test_resume_equal_timestamp_succeeds(self):
        """Test resuming with timestamp equal to paused_at leaves current_period_end unchanged."""
        start = timezone.now()
        sub = services.create_subscription(
            customer=self.customer,
            plan=self.paid_plan,
            start_date=start,
        )
        original_end = sub.current_period_end
        pause_date = start + timedelta(days=3)
        services.pause_subscription(sub, at_date=pause_date)

        # Resume at exact same timestamp
        services.resume_subscription(sub, at_date=pause_date)
        sub.refresh_from_db()

        self.assertEqual(sub.status, Subscription.Status.ACTIVE)
        self.assertIsNone(sub.paused_at)
        self.assertEqual(sub.current_period_end, original_end)

    def test_resume_later_timestamp_extends_period(self):
        """Test resuming with a later timestamp extends current_period_end by exact delta."""
        start = timezone.now()
        sub = services.create_subscription(
            customer=self.customer,
            plan=self.paid_plan,
            start_date=start,
        )
        original_end = sub.current_period_end
        pause_date = start + timedelta(days=4)
        services.pause_subscription(sub, at_date=pause_date)

        # Resume 3 days later
        resume_date = pause_date + timedelta(days=3)
        services.resume_subscription(sub, at_date=resume_date)
        sub.refresh_from_db()

        self.assertEqual(sub.status, Subscription.Status.ACTIVE)
        self.assertIsNone(sub.paused_at)
        self.assertEqual(sub.current_period_end, original_end + timedelta(days=3))

    def test_renewal_before_period_end_rejected(self):
        """Test that renewing before current_period_end is rejected."""
        sub = services.create_subscription(customer=self.customer, plan=self.paid_plan)
        # 1. Calling without at_date when now < current_period_end
        with self.assertRaises(ValidationError) as ctx:
            services.renew_subscription(sub)
        self.assertIn("before current period end", str(ctx.exception))

        # 2. Calling with explicit at_date earlier than current_period_end
        earlier_date = sub.current_period_end - timedelta(seconds=1)
        with self.assertRaises(ValidationError) as ctx:
            services.renew_subscription(sub, at_date=earlier_date)
        self.assertIn("before current period end", str(ctx.exception))

    def test_renewal_at_exact_period_end_succeeds(self):
        """Test that renewing at exact current_period_end boundary succeeds."""
        sub = services.create_subscription(customer=self.customer, plan=self.paid_plan)
        old_end = sub.current_period_end
        renewed = services.renew_subscription(sub, at_date=old_end)
        sub.refresh_from_db()
        self.assertEqual(sub.status, Subscription.Status.ACTIVE)
        self.assertEqual(sub.current_period_start, old_end)
        expected_new_end = services.calculate_next_billing_date(
            old_end,
            Plan.BillingInterval.MONTHLY,
        )
        self.assertEqual(sub.current_period_end, expected_new_end)

    def test_renewal_regular(self):
        """Test renewing an ACTIVE subscription advances current_period_start and end."""
        sub = services.create_subscription(customer=self.customer, plan=self.paid_plan)
        old_end = sub.current_period_end
        services.renew_subscription(sub, at_date=old_end)
        sub.refresh_from_db()
        self.assertEqual(sub.status, Subscription.Status.ACTIVE)
        self.assertEqual(sub.current_period_start, old_end)
        expected_new_end = services.calculate_next_billing_date(
            old_end,
            Plan.BillingInterval.MONTHLY,
        )
        self.assertEqual(sub.current_period_end, expected_new_end)

    def test_renewal_churns_when_cancel_at_period_end(self):
        """Test that renewing a subscription with cancel_at_period_end=True finalizes cancellation."""
        sub = services.create_subscription(customer=self.customer, plan=self.paid_plan)
        services.close_subscription(sub, immediate=False)
        self.assertTrue(sub.cancel_at_period_end)

        services.renew_subscription(sub, at_date=sub.current_period_end)
        sub.refresh_from_db()
        self.assertEqual(sub.status, Subscription.Status.CANCELED)
        self.assertFalse(sub.cancel_at_period_end)


class SubscriptionViewsAndScopingTests(TestCase):
    """
    Tests for subscriptions views, authentication, and IDOR protection.
    """

    def setUp(self):
        self.client = Client()
        self.now = timezone.now()

        # Users
        self.admin_user = User.objects.create_superuser(
            email="admin@example.com",
            password="adminpassword123",
            role=User.Role.ADMIN,
        )
        self.customer_user1 = User.objects.create_user(
            email="user1@example.com",
            password="userpassword123",
            role=User.Role.CUSTOMER,
        )
        self.customer_user2 = User.objects.create_user(
            email="user2@example.com",
            password="userpassword123",
            role=User.Role.CUSTOMER,
        )

        # Customers linked to users
        self.customer1 = Customer.objects.create(
            user=self.customer_user1,
            name="Customer One",
            email="user1@example.com",
            is_active=True,
        )
        self.customer2 = Customer.objects.create(
            user=self.customer_user2,
            name="Customer Two",
            email="user2@example.com",
            is_active=True,
        )

        self.product = Product.objects.create(name="App Suite", is_active=True)
        self.plan = Plan.objects.create(
            product=self.product,
            name="Monthly Plan",
            code="SUITE-MONTHLY",
            billing_interval=Plan.BillingInterval.MONTHLY,
            price=Decimal("49.99"),
            is_active=True,
        )

        # Subscriptions
        self.sub1 = services.create_subscription(customer=self.customer1, plan=self.plan)
        self.sub2 = services.create_subscription(customer=self.customer2, plan=self.plan)

    def test_unauthenticated_redirects_to_login(self):
        """Test anonymous user is redirected to login."""
        response = self.client.get(reverse("subscriptions:list"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response.url)

    def test_admin_can_view_all_subscriptions(self):
        """Test Admin role can view all subscriptions."""
        self.client.force_login(self.admin_user)
        response = self.client.get(reverse("subscriptions:list"), HTTP_ACCEPT="application/json")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        ids = [item["id"] for item in data["subscriptions"]]
        self.assertIn(self.sub1.id, ids)
        self.assertIn(self.sub2.id, ids)

    def test_customer_only_views_own_subscriptions(self):
        """Test Customer role only views their own subscriptions (IDOR defense)."""
        self.client.force_login(self.customer_user1)
        response = self.client.get(reverse("subscriptions:list"), HTTP_ACCEPT="application/json")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        ids = [item["id"] for item in data["subscriptions"]]
        self.assertIn(self.sub1.id, ids)
        self.assertNotIn(self.sub2.id, ids)

    def test_customer_cannot_view_foreign_subscription_detail(self):
        """Test Customer cannot access another customer's subscription detail (returns 404)."""
        self.client.force_login(self.customer_user1)
        # Attempting to access customer2's subscription
        response = self.client.get(
            reverse("subscriptions:detail", kwargs={"pk": self.sub2.pk}),
            HTTP_ACCEPT="application/json",
        )
        self.assertEqual(response.status_code, 404)

    def test_pause_and_resume_view_endpoints(self):
        """Test pause and resume POST endpoints."""
        self.client.force_login(self.customer_user1)

        # Pause sub1
        pause_url = reverse("subscriptions:pause", kwargs={"pk": self.sub1.pk})
        response = self.client.post(pause_url, HTTP_ACCEPT="application/json")
        self.assertEqual(response.status_code, 200)
        self.sub1.refresh_from_db()
        self.assertEqual(self.sub1.status, Subscription.Status.PAUSED)

        # Resume sub1
        resume_url = reverse("subscriptions:resume", kwargs={"pk": self.sub1.pk})
        response = self.client.post(resume_url, HTTP_ACCEPT="application/json")
        self.assertEqual(response.status_code, 200)
        self.sub1.refresh_from_db()
        self.assertEqual(self.sub1.status, Subscription.Status.ACTIVE)

    def test_subscription_list_view_html(self):
        """Test GET /subscriptions/ renders HTML template with subscription cards/rows."""
        self.client.force_login(self.admin_user)
        response = self.client.get(reverse("subscriptions:list"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "subscriptions/subscription_list.html")
        self.assertContains(response, "Subscription Management")
        self.assertContains(response, "Customer One")
        self.assertContains(response, "Customer Two")
        self.assertContains(response, "Monthly Plan")

    def test_subscription_list_view_status_filter_html(self):
        """Test GET /subscriptions/?status=ACTIVE filters HTML display."""
        self.client.force_login(self.admin_user)
        response = self.client.get(reverse("subscriptions:list") + "?status=ACTIVE")
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "subscriptions/subscription_list.html")
        self.assertEqual(response.context["selected_status"], "ACTIVE")

    def test_subscription_list_empty_state_html(self):
        """Test empty state messaging when user has no subscriptions."""
        empty_user = User.objects.create_user(
            email="empty@example.com",
            password="userpassword123",
            role=User.Role.CUSTOMER,
        )
        Customer.objects.create(
            user=empty_user,
            name="Empty Customer",
            email="empty@example.com",
            is_active=True,
        )
        self.client.force_login(empty_user)
        response = self.client.get(reverse("subscriptions:list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No Subscriptions Found")

    def test_subscription_detail_view_html(self):
        """Test GET /subscriptions/<id>/ renders HTML detail template."""
        self.client.force_login(self.customer_user1)
        response = self.client.get(reverse("subscriptions:detail", kwargs={"pk": self.sub1.pk}))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "subscriptions/subscription_detail.html")
        self.assertContains(response, f"Subscription #{self.sub1.id}")
        self.assertContains(response, "Customer One")
        self.assertContains(response, "Monthly Plan")
        self.assertContains(response, "Recurring Total")
