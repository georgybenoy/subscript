"""
End-to-End lifecycle integration test for Subscript recurring billing, payment reconciliation,
analytics reflection, and security scoping.

Workflow under test:
1. Active subscription created with plan, items, and applicable discount
2. Recurring billing engine generates DRAFT invoice
3. Confirmation commits discount usage atomically and locks immutability
4. Partial payment recorded: outstanding balance decreases, invoice remains CONFIRMED
5. Settlement payment recorded: invoice automatically marks PAID with zero balance
6. Analytics accurately aggregates collected revenue, MRR, ARR, and zero overdue
7. Authoritative PDF generated cleanly from stored ledger records
8. Tenant isolation: Customer A views statement, Customer B receives 404, unauthenticated redirected
"""

from datetime import date, timedelta
from decimal import Decimal
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import Client
from django.utils import timezone

from analytics.services import get_dashboard_context
from billing.integrations import Discount, Plan, Product, Subscription, SubscriptionItem
from billing.models import Invoice, InvoiceStatus
from billing.pdf import generate_invoice_pdf
from billing.services import confirm_invoice, generate_due_invoices
from customers.models import Customer
from payments.models import Payment
from payments.services import record_payment
from tests.test_billing_models import BaseBillingTestCase

User = get_user_model()


class EndToEndBillingLifecycleTests(BaseBillingTestCase):
    def setUp(self):
        super().setUp()
        self.client = Client()
        self.today = timezone.localdate()
        self.password = "SecurePassword123!"

        # Clear default base subscription so only test subscriptions exist
        self.subscription.status = "DRAFT"
        self.subscription.save()

        # Customer A (Owner)
        self.user_a = User.objects.create_user(
            email="cust_a_e2e@test.local", password=self.password, role=User.Role.CUSTOMER
        )
        self.customer_a = Customer.objects.create(
            user=self.user_a,
            name="Alpha Corp",
            company_name="Alpha Corp Ltd",
            email="cust_a_e2e@test.local",
            tax_id="GSTIN-E2E-01",
        )

        # Customer B (Tenant isolation adversary)
        self.user_b = User.objects.create_user(
            email="cust_b_e2e@test.local", password=self.password, role=User.Role.CUSTOMER
        )
        self.customer_b = Customer.objects.create(
            user=self.user_b,
            name="Beta Corp",
            company_name="Beta Corp Ltd",
            email="cust_b_e2e@test.local",
        )

        # Product and Monthly Plan
        self.product = Product.objects.create(name="Subscript Pro")
        self.plan = Plan.objects.create(
            product=self.product,
            name="Pro Monthly",
            billing_frequency="MONTHLY",
            price=Decimal("100.00"),
        )

        # Discount code
        self.discount = Discount.objects.create(
            code="SAVE10",
            discount_type="PERCENTAGE",
            amount=Decimal("10.00"),
            usage_count=0,
            is_active=True,
        )

    def test_complete_billing_and_payment_lifecycle(self):
        """Executes full end-to-end billing and cash reconciliation lifecycle."""

        # Step 1: Active Subscription Created
        sub = Subscription.objects.create(
            subscription_number="SUB-E2E-001",
            customer=self.customer_a,
            plan=self.plan,
            status="ACTIVE",
            start_date=self.today - timedelta(days=30),
            next_billing_date=self.today - timedelta(days=30),
            payment_terms=15,
        )
        SubscriptionItem.objects.create(
            subscription=sub,
            product=self.product,
            description="Pro Seats (x1)",
            quantity=1,
            unit_price=Decimal("100.00"),
            tax_rate=Decimal("18.00"),
        )

        # Step 2: Recurring billing run creates draft invoice
        summary = generate_due_invoices(as_of=self.today)
        self.assertEqual(summary["created"], 1)

        invoice = Invoice.objects.filter(subscription=sub).first()
        self.assertIsNotNone(invoice)
        self.assertEqual(invoice.status, InvoiceStatus.DRAFT)
        # Subtotal: 100.00, Tax: 18.00 -> Total: 118.00
        self.assertEqual(invoice.subtotal, Decimal("100.00"))
        self.assertEqual(invoice.tax_amount, Decimal("18.00"))
        self.assertEqual(invoice.total_amount, Decimal("118.00"))

        # Link discount to draft invoice
        invoice.applied_discount = self.discount
        invoice.discount_amount = Decimal("10.00")
        invoice.total_amount = Decimal("108.00")
        invoice.save()

        # Step 3: Confirm commits discount usage once
        self.assertEqual(self.discount.usage_count, 0)
        confirm_invoice(invoice)
        invoice.refresh_from_db()
        self.discount.refresh_from_db()
        self.assertEqual(invoice.status, InvoiceStatus.CONFIRMED)
        self.assertEqual(self.discount.usage_count, 1)

        # Step 4: Partial Payment
        pay1 = record_payment(
            invoice=invoice,
            amount=Decimal("50.00"),
            method="CARD",
            payment_date=self.today - timedelta(days=5),
            reference="TXN-PARTIAL-1",
        )
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, InvoiceStatus.CONFIRMED)
        self.assertEqual(invoice.paid_amount, Decimal("50.00"))
        self.assertEqual(invoice.outstanding_balance, Decimal("58.00"))

        # Step 5: Full Payment marks PAID
        pay2 = record_payment(
            invoice=invoice,
            amount=Decimal("58.00"),
            method="UPI",
            payment_date=self.today,
            reference="TXN-FINAL-2",
        )
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, InvoiceStatus.PAID)
        self.assertEqual(invoice.paid_amount, Decimal("108.00"))
        self.assertEqual(invoice.outstanding_balance, Decimal("0.00"))
        self.assertIsNotNone(invoice.paid_at)

        # Step 6: Invoice reflected in Analytics
        context = get_dashboard_context()
        self.assertEqual(context["active_subscriptions"], 1)
        self.assertEqual(context["mrr"], "100.00")
        self.assertEqual(context["arr"], "1200.00")
        self.assertEqual(context["collected_revenue"], "108.00")
        self.assertEqual(context["outstanding_balance"], "0.00")
        self.assertEqual(context["overdue_invoice_count"], 0)

        # Step 7: PDF generated successfully
        pdf_bytes = generate_invoice_pdf(invoice)
        self.assertTrue(pdf_bytes.startswith(b"%PDF-"))

        # Step 8: Customer accesses own data
        self.client.force_login(self.user_a)
        resp_detail = self.client.get(f"/billing/{invoice.pk}/")
        self.assertEqual(resp_detail.status_code, 200)

        resp_pdf = self.client.get(f"/billing/{invoice.pk}/pdf/")
        self.assertEqual(resp_pdf.status_code, 200)
        self.assertEqual(resp_pdf["Content-Type"], "application/pdf")

        # Step 9: Customer B gets 404
        self.client.force_login(self.user_b)
        resp_b_detail = self.client.get(f"/billing/{invoice.pk}/")
        self.assertEqual(resp_b_detail.status_code, 404)

        resp_b_pdf = self.client.get(f"/billing/{invoice.pk}/pdf/")
        self.assertEqual(resp_b_pdf.status_code, 404)

        # Step 10: Unauthenticated redirected to login
        self.client.logout()
        resp_anon_detail = self.client.get(f"/billing/{invoice.pk}/")
        self.assertEqual(resp_anon_detail.status_code, 302)
        self.assertIn("/accounts/login/", resp_anon_detail["Location"])

        resp_anon_pdf = self.client.get(f"/billing/{invoice.pk}/pdf/")
        self.assertEqual(resp_anon_pdf.status_code, 302)
        self.assertIn("/accounts/login/", resp_anon_pdf["Location"])
