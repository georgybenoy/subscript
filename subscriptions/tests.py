from datetime import date, timedelta
from decimal import Decimal
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from customers.models import Customer
from products.models import Plan, Product, ProductVariant
from .models import Subscription, SubscriptionItem, SubscriptionStatus
from .services import (
    InvalidSubscriptionTransitionError,
    activate_subscription,
    cancel_subscription,
    compute_next_billing_date,
    create_subscription,
    get_subscriptions_due_for_billing,
    get_subscriptions_for_user,
    pause_subscription,
    renew_subscription,
    resume_subscription,
)

User = get_user_model()


class SubscriptionLifecycleAndDateTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="cust1@test.com", password="password123", role=User.Role.CUSTOMER
        )
        self.customer = Customer.objects.create(
            user=self.user,
            name="Test Customer One",
            email="cust1@test.com",
        )
        self.product = Product.objects.create(
            name="Cloud SaaS",
            sales_price=Decimal("100.00"),
        )
        self.variant = ProductVariant.objects.create(
            product=self.product,
            name="Pro Tier",
            sku="CLOUD-PRO",
            price_adjustment=Decimal("20.00"),
        )
        self.plan = Plan.objects.create(
            product=self.product,
            name="Monthly Pro",
            code="PLAN-PRO-M",
            billing_interval=Plan.BillingInterval.MONTHLY,
            base_price=Decimal("120.00"),
            minimum_quantity=2,
        )

    def test_compute_next_billing_date_month_end_pinning(self):
        # Jan 31 -> Feb 28 (or 29)
        jan_31 = date(2026, 1, 31)
        next_date = compute_next_billing_date(jan_31, "MONTHLY")
        self.assertEqual(next_date, date(2026, 2, 28))

        # Leap year 2028: Jan 31 -> Feb 29
        jan_31_leap = date(2028, 1, 31)
        next_leap = compute_next_billing_date(jan_31_leap, "MONTHLY")
        self.assertEqual(next_leap, date(2028, 2, 29))

        # Weekly
        next_week = compute_next_billing_date(date(2026, 3, 1), "WEEKLY")
        self.assertEqual(next_week, date(2026, 3, 8))

        # Yearly
        next_year = compute_next_billing_date(date(2026, 3, 1), "YEARLY")
        self.assertEqual(next_year, date(2027, 3, 1))

    def test_create_subscription_with_line_items_validates_min_qty(self):
        # Minimum quantity is 2 for this plan. 1 should fail.
        with self.assertRaises(ValidationError):
            create_subscription(
                customer=self.customer,
                plan=self.plan,
                items_data=[
                    {"variant": self.variant, "quantity": 1}
                ],
            )

        # 2 should succeed
        sub = create_subscription(
            customer=self.customer,
            plan=self.plan,
            items_data=[
                {"variant": self.variant, "quantity": 2}
            ],
        )
        self.assertEqual(sub.status, SubscriptionStatus.DRAFT)
        self.assertEqual(sub.items.count(), 1)
        item = sub.items.first()
        self.assertEqual(item.quantity, 2)
        # Snapshot unit price should be effective price (100 + 20 = 120.00)
        self.assertEqual(item.unit_price, Decimal("120.00"))
        self.assertEqual(item.subtotal, Decimal("240.00"))

    def test_lifecycle_transitions(self):
        sub = create_subscription(
            customer=self.customer,
            plan=self.plan,
            start_date=date(2026, 5, 1),
        )
        self.assertEqual(sub.status, SubscriptionStatus.DRAFT)

        # Activate
        activate_subscription(sub, as_of=date(2026, 5, 1))
        self.assertEqual(sub.status, SubscriptionStatus.ACTIVE)
        self.assertEqual(sub.current_period_start, date(2026, 5, 1))
        self.assertEqual(sub.current_period_end, date(2026, 6, 1))

        # Pause
        pause_subscription(sub)
        self.assertEqual(sub.status, SubscriptionStatus.PAUSED)

        # Resume
        resume_subscription(sub)
        self.assertEqual(sub.status, SubscriptionStatus.ACTIVE)

        # Cancel
        cancel_subscription(sub, immediate=True)
        self.assertEqual(sub.status, SubscriptionStatus.CANCELLED)

        # Illegal transition: CANCELLED cannot transition to PAUSED
        with self.assertRaises(InvalidSubscriptionTransitionError):
            pause_subscription(sub)

    def test_get_subscriptions_due_for_billing(self):
        today = timezone.localdate()
        sub = create_subscription(
            customer=self.customer,
            plan=self.plan,
            status=SubscriptionStatus.ACTIVE,
            start_date=today - timedelta(days=30),
        )
        sub.next_billing_date = today - timedelta(days=1)
        sub.save(update_fields=["next_billing_date"])

        due = get_subscriptions_due_for_billing(as_of_date=today)
        self.assertIn(sub, due)


class SubscriptionSecurityAndScopingTests(TestCase):
    def setUp(self):
        self.client = Client()

        # Users
        self.admin = User.objects.create_user(
            email="admin@test.com", password="password123", role=User.Role.ADMIN
        )
        self.staff = User.objects.create_user(
            email="staff@test.com", password="password123", role=User.Role.STAFF
        )
        self.user1 = User.objects.create_user(
            email="user1@test.com", password="password123", role=User.Role.CUSTOMER
        )
        self.user2 = User.objects.create_user(
            email="user2@test.com", password="password123", role=User.Role.CUSTOMER
        )

        # Customers
        self.cust1 = Customer.objects.create(user=self.user1, name="Customer 1", email="user1@test.com")
        self.cust2 = Customer.objects.create(user=self.user2, name="Customer 2", email="user2@test.com")

        # Products & Plans
        self.product = Product.objects.create(name="Platform Core")
        self.plan = Plan.objects.create(
            product=self.product,
            name="Standard Plan",
            code="PLAN-STD",
            billing_interval=Plan.BillingInterval.MONTHLY,
            base_price=Decimal("50.00"),
        )

        # Subscriptions
        self.sub1 = create_subscription(
            customer=self.cust1,
            plan=self.plan,
            status=SubscriptionStatus.ACTIVE,
        )
        self.sub2 = create_subscription(
            customer=self.cust2,
            plan=self.plan,
            status=SubscriptionStatus.ACTIVE,
        )

    def test_anonymous_redirects_to_login(self):
        resp = self.client.get(reverse("subscriptions:subscription_list"))
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/accounts/login/", resp.url)

    def test_customer_only_sees_own_subscriptions_in_list(self):
        self.client.force_login(self.user1)
        resp = self.client.get(reverse("subscriptions:subscription_list"))
        self.assertEqual(resp.status_code, 200)
        subs = resp.context["subscriptions"]
        self.assertIn(self.sub1, subs)
        self.assertNotIn(self.sub2, subs)

    def test_customer_cannot_view_other_customer_detail(self):
        self.client.force_login(self.user1)
        # Own sub detail
        resp_own = self.client.get(
            reverse("subscriptions:subscription_detail", kwargs={"pk": self.sub1.pk})
        )
        self.assertEqual(resp_own.status_code, 200)

        # Other customer sub detail -> 404 (scoped queryset)
        resp_other = self.client.get(
            reverse("subscriptions:subscription_detail", kwargs={"pk": self.sub2.pk})
        )
        self.assertEqual(resp_other.status_code, 404)

    def test_customer_cannot_create_or_edit(self):
        self.client.force_login(self.user1)
        resp_create = self.client.get(reverse("subscriptions:subscription_create"))
        self.assertEqual(resp_create.status_code, 403)

        resp_edit = self.client.get(
            reverse("subscriptions:subscription_edit", kwargs={"pk": self.sub1.pk})
        )
        self.assertEqual(resp_edit.status_code, 403)

    def test_staff_and_admin_have_full_access(self):
        self.client.force_login(self.staff)
        resp = self.client.get(reverse("subscriptions:subscription_list"))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.context["subscriptions"]), 2)

        # Action: pause subscription
        resp_pause = self.client.post(
            reverse("subscriptions:subscription_pause", kwargs={"pk": self.sub1.pk})
        )
        self.assertEqual(resp_pause.status_code, 302)
        self.sub1.refresh_from_db()
        self.assertEqual(self.sub1.status, SubscriptionStatus.PAUSED)
