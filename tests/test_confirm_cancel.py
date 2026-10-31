"""
Tests for Invoice confirmation, discount usage commit, immutability,
cancellation workflows, and action permissions.
"""

from datetime import date
from decimal import Decimal
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import Client, TestCase
from django.urls import reverse

from customers.models import Customer
from billing.integrations import Subscription, Plan, Discount, SubscriptionItem
from billing.models import Invoice, InvoiceItem, InvoiceStatus
from billing.services import confirm_invoice, cancel_invoice, generate_invoice
from payments.models import Payment, PaymentMethod
from tests.test_billing_models import BaseBillingTestCase

User = get_user_model()


class ConfirmAndCancelTests(BaseBillingTestCase):
    def setUp(self):
        super().setUp()
        self.client = Client()
        self.password = "StrongPassword123!"

        self.admin = User.objects.create_superuser(
            email="admin_c@test.local", password=self.password
        )
        self.staff = User.objects.create_user(
            email="staff_c@test.local", password=self.password, role=User.Role.STAFF
        )
        self.cust_user = User.objects.create_user(
            email="cust_c@test.local", password=self.password, role=User.Role.CUSTOMER
        )
        self.customer.user = self.cust_user
        self.customer.save()

        self.discount = Discount.objects.create(
            code="SAVE20",
            discount_type="PERCENTAGE",
            amount=Decimal("20.00"),
            usage_count=0,
            is_active=True,
        )

        self.sub = Subscription.objects.create(
            subscription_number="SUB-DISC-01",
            customer=self.customer,
            status="ACTIVE",
            start_date=date(2026, 1, 1),
            next_billing_date=date(2026, 1, 1),
        )
        self.sub.discount = self.discount
        self.sub.save()

        SubscriptionItem.objects.create(
            subscription=self.sub,
            description="Base Software",
            quantity=1,
            unit_price=Decimal("100.00"),
            tax_rate=Decimal("10.00"),
        )

    def test_discount_not_incremented_on_draft_generation(self):
        inv, code, _ = generate_invoice(self.sub, as_of=date(2026, 1, 15))
        self.assertEqual(code, "created")
        self.assertEqual(inv.status, InvoiceStatus.DRAFT)
        self.assertEqual(inv.subtotal, Decimal("100.00"))
        self.assertEqual(inv.discount_amount, Decimal("20.00"))  # 20% of 100
        self.assertEqual(inv.tax_amount, Decimal("10.00"))  # 10% tax
        self.assertEqual(inv.total_amount, Decimal("90.00"))  # 100 - 20 + 10

        # Verify discount usage_count was NOT incremented on draft
        self.discount.refresh_from_db()
        self.assertEqual(self.discount.usage_count, 0)

    def test_discount_incremented_on_confirmation(self):
        inv, _, _ = generate_invoice(self.sub, as_of=date(2026, 1, 15))
        self.assertEqual(self.discount.usage_count, 0)

        # Confirm the invoice
        confirm_invoice(inv)
        inv.refresh_from_db()
        self.assertEqual(inv.status, InvoiceStatus.CONFIRMED)

        # Discount usage is now incremented exactly once
        self.discount.refresh_from_db()
        self.assertEqual(self.discount.usage_count, 1)

        # Re-confirming does not increment usage again
        confirm_invoice(inv)
        self.discount.refresh_from_db()
        self.assertEqual(self.discount.usage_count, 1)

    def test_cancel_draft_and_confirmed_with_zero_payments(self):
        # 1. Cancel DRAFT
        draft_inv, _, _ = generate_invoice(self.sub, as_of=date(2026, 1, 15))
        cancel_invoice(draft_inv)
        draft_inv.refresh_from_db()
        self.assertEqual(draft_inv.status, InvoiceStatus.CANCELLED)

        # 2. Cancel CONFIRMED with zero payments
        conf_inv = Invoice.objects.create(
            subscription=self.sub,
            invoice_number="INV-CONF-ZERO-PAY",
            issue_date=date(2026, 2, 1),
            due_date=date(2026, 2, 16),
            billing_period_start=date(2026, 2, 1),
            billing_period_end=date(2026, 2, 28),
            subtotal=Decimal("100.00"),
            total_amount=Decimal("100.00"),
            status=InvoiceStatus.CONFIRMED,
        )
        cancel_invoice(conf_inv)
        conf_inv.refresh_from_db()
        self.assertEqual(conf_inv.status, InvoiceStatus.CANCELLED)

    def test_cancel_rejected_when_payments_exist(self):
        conf_inv = Invoice.objects.create(
            subscription=self.sub,
            invoice_number="INV-WITH-PAY",
            issue_date=date(2026, 2, 1),
            due_date=date(2026, 2, 16),
            billing_period_start=date(2026, 2, 1),
            billing_period_end=date(2026, 2, 28),
            subtotal=Decimal("200.00"),
            total_amount=Decimal("200.00"),
            status=InvoiceStatus.CONFIRMED,
        )
        # Record partial payment
        Payment.objects.create(
            invoice=conf_inv,
            amount=Decimal("50.00"),
            method=PaymentMethod.CARD,
            reference="TXN-CANCEL-TEST",
        )

        with self.assertRaises(ValidationError):
            cancel_invoice(conf_inv)

    def test_cancel_rejected_on_paid_invoice(self):
        paid_inv = Invoice.objects.create(
            subscription=self.sub,
            invoice_number="INV-PAID-TEST",
            issue_date=date(2026, 2, 1),
            due_date=date(2026, 2, 16),
            billing_period_start=date(2026, 2, 1),
            billing_period_end=date(2026, 2, 28),
            subtotal=Decimal("100.00"),
            total_amount=Decimal("100.00"),
            status=InvoiceStatus.PAID,
        )
        with self.assertRaises(ValidationError):
            cancel_invoice(paid_inv)

    def test_confirm_and_cancel_views_authorization(self):
        inv = Invoice.objects.create(
            subscription=self.sub,
            invoice_number="INV-VIEW-AUTH",
            issue_date=date(2026, 3, 1),
            due_date=date(2026, 3, 16),
            billing_period_start=date(2026, 3, 1),
            billing_period_end=date(2026, 3, 31),
            subtotal=Decimal("100.00"),
            total_amount=Decimal("100.00"),
            status=InvoiceStatus.DRAFT,
        )

        # GET request rejected (require_POST)
        self.client.login(email=self.admin.email, password=self.password)
        res_get = self.client.get(reverse("billing:invoice_confirm", kwargs={"pk": inv.pk}))
        self.assertEqual(res_get.status_code, 405)

        # Customer role cannot confirm (403 PermissionDenied)
        self.client.login(email=self.cust_user.email, password=self.password)
        res_cust = self.client.post(reverse("billing:invoice_confirm", kwargs={"pk": inv.pk}))
        self.assertEqual(res_cust.status_code, 403)

        # Staff can confirm
        self.client.login(email=self.staff.email, password=self.password)
        res_staff = self.client.post(reverse("billing:invoice_confirm", kwargs={"pk": inv.pk}))
        self.assertEqual(res_staff.status_code, 302)
        inv.refresh_from_db()
        self.assertEqual(inv.status, InvoiceStatus.CONFIRMED)
