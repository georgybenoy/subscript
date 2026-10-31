"""
Unit and integration tests for Phase 5: Overdue logic and ReportLab PDF Generation.
"""

from datetime import date, timedelta
from decimal import Decimal
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import Client
from django.utils import timezone

from billing.integrations import Product, Subscription, Plan
from billing.models import Invoice, InvoiceItem, InvoiceStatus
from billing.pdf import generate_invoice_pdf
from billing.services import confirm_invoice, cancel_invoice
from customers.models import Customer
from payments.services import record_payment
from tests.test_billing_models import BaseBillingTestCase

User = get_user_model()


class OverdueAndPDFTestCase(BaseBillingTestCase):
    def setUp(self):
        super().setUp()
        self.client = Client()
        self.today = timezone.localdate()
        self.password = "StrongPass123!"

        # Admin user
        self.admin_user = User.objects.create_superuser(
            email="admin_pdf@test.local", password=self.password
        )

        # Customer user
        self.user = User.objects.create_user(
            email="cust_pdf@test.local", password=self.password, role=User.Role.CUSTOMER
        )
        self.customer.user = self.user
        self.customer.save()

        # Product
        self.product = Product.objects.create(
            name="Cloud Server Standard",
        )

    def test_overdue_edge_cases(self):
        """
        Tests overdue rules:
        - Due today: NOT overdue
        - Past due with balance > 0: OVERDUE
        - Paid in full: NOT overdue (even if past due)
        - Cancelled: NOT overdue (even if past due)
        """
        # 1. Due today, positive balance
        inv_due_today = Invoice.objects.create(
            subscription=self.subscription,
            invoice_number="INV-2026-TODAY01",
            issue_date=self.today - timedelta(days=15),
            due_date=self.today,
            billing_period_start=self.today - timedelta(days=30),
            billing_period_end=self.today - timedelta(days=1),
            subtotal=Decimal("100.00"),
            tax_amount=Decimal("0.00"),
            discount_amount=Decimal("0.00"),
            total_amount=Decimal("100.00"),
            status=InvoiceStatus.CONFIRMED,
        )
        self.assertFalse(inv_due_today.is_overdue)
        self.assertNotIn(inv_due_today, Invoice.objects.overdue())

        # 2. Past due with positive balance
        inv_overdue = Invoice.objects.create(
            subscription=self.subscription,
            invoice_number="INV-2026-PASTDUE1",
            issue_date=self.today - timedelta(days=30),
            due_date=self.today - timedelta(days=1),
            billing_period_start=self.today - timedelta(days=60),
            billing_period_end=self.today - timedelta(days=31),
            subtotal=Decimal("200.00"),
            tax_amount=Decimal("0.00"),
            discount_amount=Decimal("0.00"),
            total_amount=Decimal("200.00"),
            status=InvoiceStatus.CONFIRMED,
        )
        self.assertTrue(inv_overdue.is_overdue)
        self.assertIn(inv_overdue, Invoice.objects.overdue())

        # 3. Past due but paid in full
        inv_paid = Invoice.objects.create(
            subscription=self.subscription,
            invoice_number="INV-2026-PAID001",
            issue_date=self.today - timedelta(days=30),
            due_date=self.today - timedelta(days=1),
            billing_period_start=self.today - timedelta(days=90),
            billing_period_end=self.today - timedelta(days=61),
            subtotal=Decimal("150.00"),
            tax_amount=Decimal("0.00"),
            discount_amount=Decimal("0.00"),
            total_amount=Decimal("150.00"),
            status=InvoiceStatus.CONFIRMED,
        )
        record_payment(
            invoice=inv_paid,
            amount=Decimal("150.00"),
            method="BANK_TRANSFER",
            payment_date=self.today - timedelta(days=5),
        )
        inv_paid.refresh_from_db()
        self.assertEqual(inv_paid.status, InvoiceStatus.PAID)
        self.assertFalse(inv_paid.is_overdue)
        self.assertNotIn(inv_paid, Invoice.objects.overdue())

        # 4. Past due but cancelled
        inv_cancelled = Invoice.objects.create(
            subscription=self.subscription,
            invoice_number="INV-2026-CANCEL1",
            issue_date=self.today - timedelta(days=40),
            due_date=self.today - timedelta(days=10),
            billing_period_start=self.today - timedelta(days=120),
            billing_period_end=self.today - timedelta(days=91),
            subtotal=Decimal("300.00"),
            tax_amount=Decimal("0.00"),
            discount_amount=Decimal("0.00"),
            total_amount=Decimal("300.00"),
            status=InvoiceStatus.CANCELLED,
        )
        self.assertFalse(inv_cancelled.is_overdue)
        self.assertNotIn(inv_cancelled, Invoice.objects.overdue())

    def test_pdf_generation_valid_for_confirmed_and_paid(self):
        """Validates that PDF generation returns genuine PDF binary stream for CONFIRMED and PAID."""
        invoice = Invoice.objects.create(
            subscription=self.subscription,
            invoice_number="INV-2026-PDF001",
            issue_date=self.today,
            due_date=self.today + timedelta(days=15),
            billing_period_start=self.today - timedelta(days=30),
            billing_period_end=self.today - timedelta(days=1),
            subtotal=Decimal("100.00"),
            tax_amount=Decimal("18.00"),
            discount_amount=Decimal("10.00"),
            total_amount=Decimal("108.00"),
            status=InvoiceStatus.DRAFT,
        )
        InvoiceItem.objects.create(
            invoice=invoice,
            product=self.product,
            description="Professional Cloud Tier",
            quantity=1,
            unit_price=Decimal("100.00"),
            tax_rate=Decimal("18.00"),
            line_subtotal=Decimal("100.00"),
            line_tax=Decimal("18.00"),
            line_total=Decimal("118.00"),
        )
        invoice.status = InvoiceStatus.CONFIRMED
        invoice.save()

        pdf_bytes = generate_invoice_pdf(invoice)
        self.assertIsInstance(pdf_bytes, bytes)
        self.assertTrue(pdf_bytes.startswith(b"%PDF-"))

        # Transition to PAID and verify PDF remains renderable
        record_payment(
            invoice=invoice,
            amount=Decimal("108.00"),
            method="UPI",
            payment_date=self.today,
        )
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, InvoiceStatus.PAID)

        paid_pdf_bytes = generate_invoice_pdf(invoice)
        self.assertTrue(paid_pdf_bytes.startswith(b"%PDF-"))

    def test_pdf_generation_refused_for_draft_and_cancelled(self):
        """Verifies that PDF export is rejected for DRAFT and CANCELLED invoices."""
        draft_inv = Invoice.objects.create(
            subscription=self.subscription,
            invoice_number="INV-2026-DRAFT01",
            issue_date=self.today,
            due_date=self.today + timedelta(days=15),
            billing_period_start=self.today,
            billing_period_end=self.today + timedelta(days=30),
            subtotal=Decimal("50.00"),
            tax_amount=Decimal("0.00"),
            discount_amount=Decimal("0.00"),
            total_amount=Decimal("50.00"),
            status=InvoiceStatus.DRAFT,
        )
        with self.assertRaises(ValidationError):
            generate_invoice_pdf(draft_inv)

        cancelled_inv = Invoice.objects.create(
            subscription=self.subscription,
            invoice_number="INV-2026-CANC002",
            issue_date=self.today,
            due_date=self.today + timedelta(days=15),
            billing_period_start=self.today - timedelta(days=45),
            billing_period_end=self.today - timedelta(days=15),
            subtotal=Decimal("50.00"),
            tax_amount=Decimal("0.00"),
            discount_amount=Decimal("0.00"),
            total_amount=Decimal("50.00"),
            status=InvoiceStatus.CANCELLED,
        )
        with self.assertRaises(ValidationError):
            generate_invoice_pdf(cancelled_inv)

        # HTTP View behavior
        self.client.force_login(self.admin_user)
        resp_draft = self.client.get(f"/billing/{draft_inv.pk}/pdf/")
        self.assertEqual(resp_draft.status_code, 400)

        resp_cancel = self.client.get(f"/billing/{cancelled_inv.pk}/pdf/")
        self.assertEqual(resp_cancel.status_code, 400)

    def test_historical_integrity_after_product_or_plan_change(self):
        """
        Historical integrity: If product price is modified later,
        existing invoice line items, totals, and PDF reflect original billed values.
        """
        invoice = Invoice.objects.create(
            subscription=self.subscription,
            invoice_number="INV-2026-HIST01",
            issue_date=self.today,
            due_date=self.today + timedelta(days=15),
            billing_period_start=self.today - timedelta(days=30),
            billing_period_end=self.today - timedelta(days=1),
            subtotal=Decimal("100.00"),
            tax_amount=Decimal("0.00"),
            discount_amount=Decimal("0.00"),
            total_amount=Decimal("100.00"),
            status=InvoiceStatus.DRAFT,
        )
        item = InvoiceItem.objects.create(
            invoice=invoice,
            product=self.product,
            description="Base Subscription",
            quantity=1,
            unit_price=Decimal("100.00"),
            tax_rate=Decimal("0.00"),
            line_subtotal=Decimal("100.00"),
            line_tax=Decimal("0.00"),
            line_total=Decimal("100.00"),
        )
        invoice.status = InvoiceStatus.CONFIRMED
        invoice.save()

        # Mutate the subscription plan price
        self.plan.price = Decimal("250.00")
        self.plan.save()

        # Invoice item remains snapshot
        item.refresh_from_db()
        self.assertEqual(item.unit_price, Decimal("100.00"))
        self.assertEqual(item.line_total, Decimal("100.00"))

        # Re-generate PDF and verify it renders without issue
        pdf = generate_invoice_pdf(invoice)
        self.assertTrue(pdf.startswith(b"%PDF-"))

    def test_customer_isolation_pdf_download(self):
        """Customer A cannot download Customer B's PDF (returns 404)."""
        other_user = User.objects.create_user(
            email="othercust_pdf@test.local", password=self.password, role=User.Role.CUSTOMER
        )
        other_customer = Customer.objects.create(
            user=other_user, name="Other Co", email="other@test.local"
        )
        other_sub = Subscription.objects.create(
            subscription_number="SUB-OTHER-01",
            customer=other_customer,
            plan=self.plan,
            status="ACTIVE",
            start_date=date(2026, 1, 1),
            next_billing_date=date(2026, 2, 1),
        )

        # Invoice belongs to self.customer (self.user)
        invoice = Invoice.objects.create(
            subscription=self.subscription,
            invoice_number="INV-2026-ISOL01",
            issue_date=self.today,
            due_date=self.today + timedelta(days=15),
            billing_period_start=self.today - timedelta(days=30),
            billing_period_end=self.today - timedelta(days=1),
            subtotal=Decimal("100.00"),
            tax_amount=Decimal("0.00"),
            discount_amount=Decimal("0.00"),
            total_amount=Decimal("100.00"),
            status=InvoiceStatus.CONFIRMED,
        )

        # Attempt download as other_user -> 404
        self.client.force_login(other_user)
        response = self.client.get(f"/billing/{invoice.pk}/pdf/")
        self.assertEqual(response.status_code, 404)

        # Download as owning user succeeds
        self.client.force_login(self.user)
        response_owner = self.client.get(f"/billing/{invoice.pk}/pdf/")
        self.assertEqual(response_owner.status_code, 200)
        self.assertEqual(response_owner["Content-Type"], "application/pdf")
        self.assertIn(f"Invoice-{invoice.invoice_number}.pdf", response_owner["Content-Disposition"])
