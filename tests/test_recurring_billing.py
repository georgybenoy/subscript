"""
Comprehensive test suite for Recurring Billing Engine, Idempotency, Catch-Up Billing,
and the generate_due_invoices management command.
"""

from datetime import date, timedelta
from decimal import Decimal
import io
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase

from customers.models import Customer
from billing.integrations import Subscription, Plan, SubscriptionItem, Product
from billing.models import Invoice, InvoiceStatus
from billing.services import generate_invoice, generate_due_invoices
from tests.test_billing_models import BaseBillingTestCase


class RecurringBillingTests(BaseBillingTestCase):
    def setUp(self):
        super().setUp()
        self.subscription.status = "DRAFT"
        self.subscription.save()
        self.product = Product.objects.create(name="Pro Tier")
        self.plan = Plan.objects.create(
            name="Pro Monthly Plan",
            billing_frequency="MONTHLY",
            price=Decimal("150.00"),
            product=self.product,
        )
        self.sub = Subscription.objects.create(
            subscription_number="SUB-REC-001",
            customer=self.customer,
            plan=self.plan,
            status="ACTIVE",
            start_date=date(2026, 1, 1),
            next_billing_date=date(2026, 1, 1),
            payment_terms=15,
        )
        SubscriptionItem.objects.create(
            subscription=self.sub,
            product=self.product,
            description="Pro Tier Monthly Seat",
            quantity=2,
            unit_price=Decimal("75.00"),
            tax_rate=Decimal("18.00"),
        )

    def test_single_period_invoice_generation_advances_date(self):
        inv, code, msg = generate_invoice(self.sub, as_of=date(2026, 1, 15))
        self.assertEqual(code, "created")
        self.assertIsNotNone(inv)
        self.assertEqual(inv.status, InvoiceStatus.DRAFT)
        self.assertEqual(inv.billing_period_start, date(2026, 1, 1))
        # 1 month: Jan 1 to Jan 31
        self.assertEqual(inv.billing_period_end, date(2026, 1, 31))
        self.assertEqual(inv.due_date, date(2026, 1, 16))  # 15 days from start

        # Subscription date advanced to Feb 1
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.next_billing_date, date(2026, 2, 1))

    def test_repeated_runs_give_one_invoice_per_period(self):
        # Run 1: creates invoice for Jan
        summary1 = generate_due_invoices(as_of=date(2026, 1, 15))
        self.assertEqual(summary1["created"], 1)

        # Run 2 on same date: skips duplicate
        summary2 = generate_due_invoices(as_of=date(2026, 1, 15))
        self.assertEqual(summary2["created"], 0)

        # Run 3 on same date: still 0
        summary3 = generate_due_invoices(as_of=date(2026, 1, 15))
        self.assertEqual(summary3["created"], 0)

        # Verify only 1 invoice exists in DB
        self.assertEqual(Invoice.objects.filter(subscription=self.sub).count(), 1)

    def test_paused_and_closed_subscriptions_never_billed(self):
        self.sub.status = "PAUSED"
        self.sub.save()
        inv_paused, code_p, _ = generate_invoice(self.sub, as_of=date(2026, 1, 15))
        self.assertEqual(code_p, "skipped_ineligible")

        self.sub.status = "CLOSED"
        self.sub.save()
        inv_closed, code_c, _ = generate_invoice(self.sub, as_of=date(2026, 1, 15))
        self.assertEqual(code_c, "skipped_ineligible")

        self.assertEqual(Invoice.objects.filter(subscription=self.sub).count(), 0)

    def test_forced_midway_failure_rolls_back_everything(self):
        original_date = self.sub.next_billing_date
        # Force a failure inside invoice item creation
        with patch("billing.models.InvoiceItem.objects.create", side_effect=RuntimeError("Simulated DB Disk Crash")):
            inv, code, msg = generate_invoice(self.sub, as_of=date(2026, 1, 15))
            self.assertEqual(code, "failed")
            self.assertIsNone(inv)

        # Assert no invoice was created and next_billing_date was NOT advanced
        self.assertEqual(Invoice.objects.filter(subscription=self.sub).count(), 0)
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.next_billing_date, original_date)

    def test_catch_up_billing_generates_three_periods_in_order(self):
        # Subscription next_billing_date is Jan 1. As of March 15, 3 periods are due:
        # Period 1: Jan 1 - Jan 31
        # Period 2: Feb 1 - Feb 28
        # Period 3: Mar 1 - Mar 31
        summary = generate_due_invoices(as_of=date(2026, 3, 15))
        self.assertEqual(summary["created"], 3)

        invoices = Invoice.objects.filter(subscription=self.sub).order_by("billing_period_start")
        self.assertEqual(invoices.count(), 3)

        inv1, inv2, inv3 = invoices
        self.assertEqual(inv1.billing_period_start, date(2026, 1, 1))
        self.assertEqual(inv1.billing_period_end, date(2026, 1, 31))

        self.assertEqual(inv2.billing_period_start, date(2026, 2, 1))
        self.assertEqual(inv2.billing_period_end, date(2026, 2, 28))

        self.assertEqual(inv3.billing_period_start, date(2026, 3, 1))
        self.assertEqual(inv3.billing_period_end, date(2026, 3, 31))

        # Next billing date is now April 1
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.next_billing_date, date(2026, 4, 1))

    def test_generate_due_invoices_command(self):
        out = io.StringIO()
        call_command("generate_due_invoices", "--date", "2026-01-15", stdout=out)
        output = out.getvalue()
        self.assertIn("Billing Run Summary:", output)
        self.assertIn("Invoices Created:      1", output)

        # Test dry-run
        out_dry = io.StringIO()
        call_command("generate_due_invoices", "--date", "2026-02-15", "--dry-run", stdout=out_dry)
        dry_output = out_dry.getvalue()
        self.assertIn("[DRY-RUN]", dry_output)
        self.assertIn("Dry run complete. No records created.", dry_output)
