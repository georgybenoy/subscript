"""
Tests for Payment processing services, partial settlements, overpayment rejections,
status transitions, and tenant access controls.
"""

from datetime import date, timedelta
from decimal import Decimal
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import Client, TestCase
from django.urls import reverse

from customers.models import Customer
from billing.integrations import Subscription
from billing.models import Invoice, InvoiceStatus
from payments.models import Payment, PaymentMethod
from payments.services import (
    record_payment,
    reconcile_invoice,
    get_invoice_paid_amount,
    get_invoice_outstanding_balance,
)
from tests.test_billing_models import BaseBillingTestCase

User = get_user_model()


class PaymentProcessingTests(BaseBillingTestCase):
    def setUp(self):
        super().setUp()
        self.client = Client()
        self.password = "SecPass123!"

        self.admin = User.objects.create_superuser(
            email="admin_pay@test.local", password=self.password
        )
        self.staff = User.objects.create_user(
            email="staff_pay@test.local", password=self.password, role=User.Role.STAFF
        )
        self.cust_user = User.objects.create_user(
            email="cust_pay@test.local", password=self.password, role=User.Role.CUSTOMER
        )
        self.customer.user = self.cust_user
        self.customer.save()

        # Confirmed invoice of $10,000.00
        self.inv = Invoice.objects.create(
            subscription=self.subscription,
            invoice_number="INV-PAY-10000",
            issue_date=date(2026, 1, 1),
            due_date=date(2026, 1, 16),
            billing_period_start=date(2026, 1, 1),
            billing_period_end=date(2026, 1, 31),
            subtotal=Decimal("10000.00"),
            total_amount=Decimal("10000.00"),
            status=InvoiceStatus.CONFIRMED,
        )

    def test_partial_payment_and_full_settlement(self):
        # 1. Pay $4,000.00 -> Outstanding $6,000.00 -> Status remains CONFIRMED
        p1 = record_payment(self.inv, Decimal("4000.00"), method=PaymentMethod.BANK_TRANSFER)
        self.assertEqual(p1.amount, Decimal("4000.00"))

        self.inv.refresh_from_db()
        self.assertEqual(get_invoice_paid_amount(self.inv), Decimal("4000.00"))
        self.assertEqual(get_invoice_outstanding_balance(self.inv), Decimal("6000.00"))
        self.assertEqual(self.inv.status, InvoiceStatus.CONFIRMED)
        self.assertIsNone(self.inv.paid_at)

        # 2. Pay remaining $6,000.00 -> Outstanding $0.00 -> Status becomes PAID
        p2 = record_payment(self.inv, Decimal("6000.00"), method=PaymentMethod.UPI)
        self.assertEqual(p2.amount, Decimal("6000.00"))

        self.inv.refresh_from_db()
        self.assertEqual(get_invoice_paid_amount(self.inv), Decimal("10000.00"))
        self.assertEqual(get_invoice_outstanding_balance(self.inv), Decimal("0.00"))
        self.assertEqual(self.inv.status, InvoiceStatus.PAID)
        self.assertIsNotNone(self.inv.paid_at)

    def test_overpayment_rejected(self):
        record_payment(self.inv, Decimal("4000.00"), method=PaymentMethod.CARD)
        # Attempting to pay $7,000 when $6,000 is outstanding
        with self.assertRaises(ValidationError) as ctx:
            record_payment(self.inv, Decimal("7000.00"), method=PaymentMethod.CARD)
        self.assertIn("exceeds outstanding invoice balance", str(ctx.exception))

    def test_zero_and_negative_payment_rejected(self):
        with self.assertRaises(ValidationError):
            record_payment(self.inv, Decimal("0.00"), method=PaymentMethod.CARD)

        with self.assertRaises(ValidationError):
            record_payment(self.inv, Decimal("-500.00"), method=PaymentMethod.CARD)

    def test_future_payment_date_rejected(self):
        future_date = date.today() + timedelta(days=5)
        with self.assertRaises(ValidationError) as ctx:
            record_payment(self.inv, Decimal("100.00"), payment_date=future_date)
        self.assertIn("future", str(ctx.exception).lower())

    def test_draft_and_cancelled_invoices_reject_payments(self):
        # DRAFT
        draft_inv = Invoice.objects.create(
            subscription=self.subscription,
            invoice_number="INV-DRAFT-PAY",
            issue_date=date(2026, 2, 1),
            due_date=date(2026, 2, 16),
            billing_period_start=date(2026, 2, 1),
            billing_period_end=date(2026, 2, 28),
            total_amount=Decimal("100.00"),
            status=InvoiceStatus.DRAFT,
        )
        with self.assertRaises(ValidationError) as ctx:
            record_payment(draft_inv, Decimal("50.00"))
        self.assertIn("DRAFT", str(ctx.exception))

        # CANCELLED
        canc_inv = Invoice.objects.create(
            subscription=self.subscription,
            invoice_number="INV-CANC-PAY",
            issue_date=date(2026, 3, 1),
            due_date=date(2026, 3, 16),
            billing_period_start=date(2026, 3, 1),
            billing_period_end=date(2026, 3, 31),
            total_amount=Decimal("100.00"),
            status=InvoiceStatus.CANCELLED,
        )
        with self.assertRaises(ValidationError) as ctx:
            record_payment(canc_inv, Decimal("50.00"))
        self.assertIn("CANCELLED", str(ctx.exception))

    def test_double_submission_fails_on_second_attempt(self):
        # Pay full amount
        record_payment(self.inv, Decimal("10000.00"))
        # Second attempt must fail because invoice is now PAID and outstanding is 0
        with self.assertRaises(ValidationError):
            record_payment(self.inv, Decimal("10000.00"))

    def test_reconcile_invoice_detects_and_resolves_mismatch(self):
        # Simulate an invoice whose stored status fell out of sync
        Payment.objects.create(
            invoice=self.inv,
            amount=Decimal("10000.00"),
            method=PaymentMethod.BANK_TRANSFER,
            reference="TXN-SYNC-01",
        )
        # Manually keep status as CONFIRMED to simulate mismatch
        Invoice.objects.filter(pk=self.inv.pk).update(status=InvoiceStatus.CONFIRMED)

        report = reconcile_invoice(self.inv)
        self.assertFalse(report["reconciled"])
        self.assertEqual(len(report["discrepancies"]), 1)

        self.inv.refresh_from_db()
        self.assertEqual(self.inv.status, InvoiceStatus.PAID)

    def test_payment_views_permissions_and_customer_scoping(self):
        p = record_payment(self.inv, Decimal("500.00"), method=PaymentMethod.UPI)

        # 1. Staff can view list and see payment
        self.client.login(email=self.staff.email, password=self.password)
        res_staff = self.client.get(reverse("payments:payment_list"))
        self.assertEqual(res_staff.status_code, 200)
        self.assertContains(res_staff, p.reference)

        # 2. Customer can view own payment
        self.client.login(email=self.cust_user.email, password=self.password)
        res_cust = self.client.get(reverse("payments:payment_list"))
        self.assertEqual(res_cust.status_code, 200)
        self.assertContains(res_cust, p.reference)

        # 3. Customer cannot access payment create form (403 PermissionDenied)
        res_create = self.client.get(reverse("payments:payment_create"))
        self.assertEqual(res_create.status_code, 403)
