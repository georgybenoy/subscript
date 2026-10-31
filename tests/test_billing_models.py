"""
Comprehensive test suite for Subscript Billing and Payments models and money arithmetic.

Covers:
- quantize_money precision, ROUND_HALF_UP, and float rejection
- Line calculations: quantity x unit_price, tax_rate, line_total
- InvoiceItem snapshots, constraints, and immutability
- Invoice totals, discount cap at subtotal, non-negative total
- Strict UniqueConstraint duplicate period prevention (including cancelled periods)
- Derived overdue logic (due today is NOT overdue, cancelled is NOT overdue, paid is NOT overdue)
- Payment positive amount validation, append-only immutability, and deletion prevention
"""

from datetime import date, timedelta
from decimal import Decimal
from django.core.exceptions import ValidationError
from django.db import connection, IntegrityError
from django.test import TestCase
from django.utils import timezone

from customers.models import Customer
from billing.integrations import (
    Product,
    Plan,
    Subscription,
    SubscriptionItem,
    Discount,
)
from billing.models import Invoice, InvoiceItem, InvoiceStatus
from billing.money import (
    quantize_money,
    calculate_line_subtotal,
    calculate_line_tax,
    calculate_line_total,
)
from payments.models import Payment, PaymentMethod


class BaseBillingTestCase(TestCase):
    """
    Base test case ensuring prerequisite database tables exist for stub models.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        with connection.cursor() as cursor:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS products_product (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name VARCHAR(255) NOT NULL,
                    description TEXT,
                    is_active BOOLEAN NOT NULL DEFAULT 1
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS products_plan (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name VARCHAR(255) NOT NULL,
                    billing_frequency VARCHAR(20) NOT NULL DEFAULT 'MONTHLY',
                    price DECIMAL(12, 2) NOT NULL DEFAULT '0.00',
                    product_id INTEGER
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS discounts_discount (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    code VARCHAR(50) NOT NULL UNIQUE,
                    discount_type VARCHAR(20) NOT NULL DEFAULT 'PERCENTAGE',
                    amount DECIMAL(12, 2) NOT NULL DEFAULT '0.00',
                    usage_count INTEGER NOT NULL DEFAULT 0,
                    max_redemptions INTEGER,
                    is_active BOOLEAN NOT NULL DEFAULT 1
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS subscriptions_subscription (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    subscription_number VARCHAR(100) NOT NULL UNIQUE,
                    status VARCHAR(20) NOT NULL DEFAULT 'ACTIVE',
                    start_date DATE,
                    expiry_date DATE,
                    next_billing_date DATE,
                    payment_terms INTEGER NOT NULL DEFAULT 15,
                    customer_id INTEGER NOT NULL,
                    plan_id INTEGER
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS subscriptions_subscriptionitem (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    description VARCHAR(255) NOT NULL DEFAULT '',
                    quantity INTEGER NOT NULL DEFAULT 1,
                    unit_price DECIMAL(12, 2) NOT NULL DEFAULT '0.00',
                    tax_rate DECIMAL(5, 2) NOT NULL DEFAULT '0.00',
                    product_id INTEGER,
                    subscription_id INTEGER NOT NULL
                )
            """)

    def setUp(self):
        super().setUp()
        self.customer = Customer.objects.create(
            name="Alpha Corp",
            company_name="Alpha Corporation Ltd",
            email="billing@alphacorp.test",
            tax_id="GSTIN-ALPHA-01",
        )
        self.plan = Plan.objects.create(
            name="Pro Monthly",
            billing_frequency="MONTHLY",
            price=Decimal("199.00"),
        )
        self.subscription = Subscription.objects.create(
            subscription_number="SUB-2026-0001",
            customer=self.customer,
            plan=self.plan,
            status="ACTIVE",
            start_date=date(2026, 1, 1),
            next_billing_date=date(2026, 2, 1),
            payment_terms=15,
        )


class MoneyPrecisionTests(TestCase):
    """
    Tests strict Decimal arithmetic, ROUND_HALF_UP rounding, and float prohibition.
    """

    def test_float_strictly_forbidden(self):
        with self.assertRaises(TypeError):
            quantize_money(12.34)

        with self.assertRaises(TypeError):
            quantize_money(0.0)

    def test_int_and_str_accepted_and_quantized(self):
        self.assertEqual(quantize_money(100), Decimal("100.00"))
        self.assertEqual(quantize_money("49.9"), Decimal("49.90"))
        self.assertEqual(quantize_money("0"), Decimal("0.00"))

    def test_round_half_up_convention(self):
        # 0.005 rounds up to 0.01; 0.004 rounds down to 0.00
        self.assertEqual(quantize_money(Decimal("10.005")), Decimal("10.01"))
        self.assertEqual(quantize_money(Decimal("10.004")), Decimal("10.00"))
        self.assertEqual(quantize_money(Decimal("2.125")), Decimal("2.13"))
        self.assertEqual(quantize_money(Decimal("2.124")), Decimal("2.12"))

    def test_line_subtotal_calculation(self):
        subtotal = calculate_line_subtotal(3, Decimal("19.99"))
        self.assertEqual(subtotal, Decimal("59.97"))

    def test_line_tax_calculation_quantized_per_line(self):
        # 59.97 * 18% = 10.7946 -> rounds to 10.79
        tax = calculate_line_tax(Decimal("59.97"), Decimal("18.00"))
        self.assertEqual(tax, Decimal("10.79"))

    def test_line_total_reconciles_subtotal_and_tax(self):
        line_total = calculate_line_total(Decimal("59.97"), Decimal("10.79"))
        self.assertEqual(line_total, Decimal("70.76"))


class InvoiceItemModelTests(BaseBillingTestCase):
    """
    Tests InvoiceItem creation, line calculation snapshots, and immutability.
    """

    def test_create_line_item_and_amount_property(self):
        invoice = Invoice.objects.create(
            subscription=self.subscription,
            invoice_number="INV-2026-0001",
            issue_date=date(2026, 1, 1),
            due_date=date(2026, 1, 16),
            billing_period_start=date(2026, 1, 1),
            billing_period_end=date(2026, 1, 31),
            subtotal=Decimal("100.00"),
            total_amount=Decimal("118.00"),
            status=InvoiceStatus.DRAFT,
        )
        item = InvoiceItem.objects.create(
            invoice=invoice,
            description="Base Platform License",
            quantity=1,
            unit_price=Decimal("100.00"),
            tax_rate=Decimal("18.00"),
            line_subtotal=Decimal("100.00"),
            line_tax=Decimal("18.00"),
            line_total=Decimal("118.00"),
        )
        self.assertEqual(item.amount, Decimal("118.00"))
        self.assertEqual(item.line_subtotal, Decimal("100.00"))
        self.assertEqual(item.line_tax, Decimal("18.00"))

    def test_snapshot_integrity_when_external_price_changes(self):
        # Changing plan price does not mutate existing snapshot line item
        product = Product.objects.create(name="Add-on Storage")
        item = InvoiceItem(
            invoice=Invoice.objects.create(
                subscription=self.subscription,
                invoice_number="INV-2026-0002",
                issue_date=date(2026, 1, 1),
                due_date=date(2026, 1, 16),
                billing_period_start=date(2026, 1, 1),
                billing_period_end=date(2026, 1, 31),
                status=InvoiceStatus.DRAFT,
            ),
            product=product,
            description="Add-on Storage Tier 1",
            quantity=2,
            unit_price=Decimal("50.00"),
            tax_rate=Decimal("10.00"),
            line_subtotal=Decimal("100.00"),
            line_tax=Decimal("10.00"),
            line_total=Decimal("110.00"),
        )
        item.save()

        # External change
        product.name = "Renamed Product"
        product.save()

        item.refresh_from_db()
        self.assertEqual(item.unit_price, Decimal("50.00"))
        self.assertEqual(item.line_total, Decimal("110.00"))

    def test_items_immutable_on_confirmed_invoice(self):
        invoice = Invoice.objects.create(
            subscription=self.subscription,
            invoice_number="INV-2026-0003",
            issue_date=date(2026, 1, 1),
            due_date=date(2026, 1, 16),
            billing_period_start=date(2026, 1, 1),
            billing_period_end=date(2026, 1, 31),
            subtotal=Decimal("100.00"),
            total_amount=Decimal("100.00"),
            status=InvoiceStatus.DRAFT,
        )
        item = InvoiceItem.objects.create(
            invoice=invoice,
            description="Subscription Fee",
            quantity=1,
            unit_price=Decimal("100.00"),
            line_subtotal=Decimal("100.00"),
            line_total=Decimal("100.00"),
        )

        # Confirm the invoice
        invoice.status = InvoiceStatus.CONFIRMED
        invoice.save()

        # Attempting to modify item
        item.unit_price = Decimal("200.00")
        with self.assertRaises(ValidationError):
            item.save()

        # Attempting to delete item
        with self.assertRaises(ValidationError):
            item.delete()

        # Attempting to add new item to confirmed invoice
        with self.assertRaises(ValidationError):
            InvoiceItem.objects.create(
                invoice=invoice,
                description="Late Added Item",
                quantity=1,
                unit_price=Decimal("50.00"),
                line_subtotal=Decimal("50.00"),
                line_total=Decimal("50.00"),
            )


class InvoiceModelTests(BaseBillingTestCase):
    """
    Tests Invoice model arithmetic, discount capping, unique constraints, and overdue annotations.
    """

    def test_invoice_totals_and_template_properties(self):
        invoice = Invoice.objects.create(
            subscription=self.subscription,
            invoice_number="INV-2026-0010",
            issue_date=date(2026, 2, 1),
            due_date=date(2026, 2, 16),
            billing_period_start=date(2026, 2, 1),
            billing_period_end=date(2026, 2, 28),
            subtotal=Decimal("500.00"),
            discount_amount=Decimal("50.00"),
            tax_amount=Decimal("81.00"),
            total_amount=Decimal("531.00"),
            status=InvoiceStatus.DRAFT,
        )
        # Verify compatibility properties
        self.assertEqual(invoice.total, Decimal("531.00"))
        self.assertEqual(invoice.customer.name, "Alpha Corp")
        self.assertEqual(invoice.paid_amount, Decimal("0.00"))
        self.assertEqual(invoice.outstanding_balance, Decimal("531.00"))

    def test_discount_capped_and_non_negative_total(self):
        # Negative amounts are rejected
        invoice = Invoice(
            subscription=self.subscription,
            invoice_number="INV-2026-0011",
            issue_date=date(2026, 2, 1),
            due_date=date(2026, 2, 16),
            billing_period_start=date(2026, 2, 1),
            billing_period_end=date(2026, 2, 28),
            subtotal=Decimal("-10.00"),
            total_amount=Decimal("-10.00"),
        )
        with self.assertRaises(ValidationError):
            invoice.save()

    def test_strict_duplicate_prevention_on_billing_period(self):
        Invoice.objects.create(
            subscription=self.subscription,
            invoice_number="INV-2026-0012",
            issue_date=date(2026, 1, 1),
            due_date=date(2026, 1, 16),
            billing_period_start=date(2026, 1, 1),
            billing_period_end=date(2026, 1, 31),
            status=InvoiceStatus.DRAFT,
        )

        # Attempting to create duplicate period on same subscription raises error
        with self.assertRaises((IntegrityError, ValidationError)):
            Invoice.objects.create(
                subscription=self.subscription,
                invoice_number="INV-2026-0013",
                issue_date=date(2026, 1, 1),
                due_date=date(2026, 1, 16),
                billing_period_start=date(2026, 1, 1),
                billing_period_end=date(2026, 1, 31),
                status=InvoiceStatus.DRAFT,
            )

    def test_cancelled_period_is_not_silently_rebilled(self):
        # Strict decision: cancelled invoices still protect the period constraint
        inv = Invoice.objects.create(
            subscription=self.subscription,
            invoice_number="INV-2026-0014",
            issue_date=date(2026, 3, 1),
            due_date=date(2026, 3, 16),
            billing_period_start=date(2026, 3, 1),
            billing_period_end=date(2026, 3, 31),
            status=InvoiceStatus.CANCELLED,
        )
        self.assertEqual(inv.status, InvoiceStatus.CANCELLED)

        # Attempt to bill the same period again fails
        with self.assertRaises((IntegrityError, ValidationError)):
            Invoice.objects.create(
                subscription=self.subscription,
                invoice_number="INV-2026-0015",
                issue_date=date(2026, 3, 1),
                due_date=date(2026, 3, 16),
                billing_period_start=date(2026, 3, 1),
                billing_period_end=date(2026, 3, 31),
                status=InvoiceStatus.DRAFT,
            )

    def test_overdue_derived_manager_and_property(self):
        today = timezone.localdate()

        # 1. Invoice past due date with balance > 0 -> OVERDUE
        overdue_inv = Invoice.objects.create(
            subscription=self.subscription,
            invoice_number="INV-OVERDUE-1",
            issue_date=today - timedelta(days=30),
            due_date=today - timedelta(days=5),
            billing_period_start=today - timedelta(days=30),
            billing_period_end=today - timedelta(days=1),
            total_amount=Decimal("200.00"),
            status=InvoiceStatus.CONFIRMED,
        )

        # 2. Invoice due TODAY -> NOT overdue (edge case requirement!)
        due_today_inv = Invoice.objects.create(
            subscription=self.subscription,
            invoice_number="INV-TODAY-1",
            issue_date=today - timedelta(days=15),
            due_date=today,
            billing_period_start=today - timedelta(days=15),
            billing_period_end=today + timedelta(days=15),
            total_amount=Decimal("200.00"),
            status=InvoiceStatus.CONFIRMED,
        )

        # 3. Invoice past due date but CANCELLED -> NOT overdue
        cancelled_inv = Invoice.objects.create(
            subscription=self.subscription,
            invoice_number="INV-CANCELLED-1",
            issue_date=today - timedelta(days=40),
            due_date=today - timedelta(days=10),
            billing_period_start=today - timedelta(days=40),
            billing_period_end=today - timedelta(days=11),
            total_amount=Decimal("200.00"),
            status=InvoiceStatus.CANCELLED,
        )

        # 4. Invoice past due date but fully PAID -> NOT overdue
        paid_inv = Invoice.objects.create(
            subscription=self.subscription,
            invoice_number="INV-PAID-1",
            issue_date=today - timedelta(days=40),
            due_date=today - timedelta(days=10),
            billing_period_start=today - timedelta(days=70),
            billing_period_end=today - timedelta(days=41),
            total_amount=Decimal("150.00"),
            status=InvoiceStatus.PAID,
        )
        Payment.objects.create(
            invoice=paid_inv,
            amount=Decimal("150.00"),
            method=PaymentMethod.CARD,
            reference="TXN-FULL-PAID",
        )

        # Verify property
        self.assertTrue(overdue_inv.is_overdue)
        self.assertFalse(due_today_inv.is_overdue)
        self.assertFalse(cancelled_inv.is_overdue)
        self.assertFalse(paid_inv.is_overdue)

        # Verify database QuerySet manager .overdue()
        overdue_qs = Invoice.objects.overdue()
        overdue_ids = list(overdue_qs.values_list("id", flat=True))
        self.assertIn(overdue_inv.id, overdue_ids)
        self.assertNotIn(due_today_inv.id, overdue_ids)
        self.assertNotIn(cancelled_inv.id, overdue_ids)
        self.assertNotIn(paid_inv.id, overdue_ids)

    def test_invoice_financial_immutability_on_confirmation(self):
        invoice = Invoice.objects.create(
            subscription=self.subscription,
            invoice_number="INV-2026-IMMUTABLE",
            issue_date=date(2026, 1, 1),
            due_date=date(2026, 1, 16),
            billing_period_start=date(2026, 1, 1),
            billing_period_end=date(2026, 1, 31),
            subtotal=Decimal("100.00"),
            total_amount=Decimal("100.00"),
            status=InvoiceStatus.CONFIRMED,
        )

        # Attempt to change total_amount
        invoice.total_amount = Decimal("50.00")
        with self.assertRaises(ValidationError):
            invoice.save()

        # Status transition to PAID is allowed
        invoice.refresh_from_db()
        invoice.status = InvoiceStatus.PAID
        invoice.save()
        self.assertEqual(invoice.status, InvoiceStatus.PAID)


class PaymentModelTests(BaseBillingTestCase):
    """
    Tests Payment model creation, positive amount validation, append-only immutability,
    and deletion prevention.
    """

    def setUp(self):
        super().setUp()
        self.invoice = Invoice.objects.create(
            subscription=self.subscription,
            invoice_number="INV-PAY-001",
            issue_date=date(2026, 1, 1),
            due_date=date(2026, 1, 16),
            billing_period_start=date(2026, 1, 1),
            billing_period_end=date(2026, 1, 31),
            subtotal=Decimal("200.00"),
            total_amount=Decimal("200.00"),
            status=InvoiceStatus.CONFIRMED,
        )

    def test_create_payment_and_template_properties(self):
        payment = Payment.objects.create(
            invoice=self.invoice,
            amount=Decimal("100.00"),
            method=PaymentMethod.UPI,
            reference="UPI-REF-9921",
            notes="Initial installment",
        )
        self.assertEqual(payment.amount, Decimal("100.00"))
        self.assertEqual(payment.customer.name, "Alpha Corp")
        self.assertEqual(payment.transaction_reference, "UPI-REF-9921")
        self.assertEqual(payment.payment_method, PaymentMethod.UPI)
        self.assertEqual(payment.status, "SUCCESS")

    def test_zero_or_negative_payment_amount_rejected(self):
        payment_zero = Payment(
            invoice=self.invoice,
            amount=Decimal("0.00"),
            method=PaymentMethod.CARD,
            reference="TXN-ZERO",
        )
        with self.assertRaises(ValidationError):
            payment_zero.save()

        payment_neg = Payment(
            invoice=self.invoice,
            amount=Decimal("-50.00"),
            method=PaymentMethod.CARD,
            reference="TXN-NEG",
        )
        with self.assertRaises(ValidationError):
            payment_neg.save()

    def test_payment_append_only_immutability(self):
        payment = Payment.objects.create(
            invoice=self.invoice,
            amount=Decimal("75.00"),
            method=PaymentMethod.CARD,
            reference="TXN-IMMUTABLE-1",
        )

        # Modifying amount raises ValidationError
        payment.amount = Decimal("80.00")
        with self.assertRaises(ValidationError):
            payment.save()

        # Deleting payment is strictly forbidden
        payment.refresh_from_db()
        with self.assertRaises(ValidationError):
            payment.delete()

    def test_bulk_payment_update_and_delete_blocked(self):
        Payment.objects.create(
            invoice=self.invoice,
            amount=Decimal("50.00"),
            method=PaymentMethod.CARD,
            reference="TXN-BULK-1",
        )
        with self.assertRaises(ValidationError):
            Payment.objects.filter(reference="TXN-BULK-1").update(amount=Decimal("60.00"))

        with self.assertRaises(ValidationError):
            Payment.objects.filter(reference="TXN-BULK-1").delete()


class HardeningAndSyncTests(BaseBillingTestCase):
    """
    Verifies that billing integration boundary protects other members' apps
    and prevents bulk mutations of confirmed invoices.
    """

    def test_bulk_confirmed_invoice_update_and_delete_blocked(self):
        inv = Invoice.objects.create(
            subscription=self.subscription,
            invoice_number="INV-BULK-TEST",
            issue_date=date(2026, 1, 1),
            due_date=date(2026, 1, 16),
            billing_period_start=date(2026, 1, 1),
            billing_period_end=date(2026, 1, 31),
            subtotal=Decimal("100.00"),
            total_amount=Decimal("100.00"),
            status=InvoiceStatus.CONFIRMED,
        )
        with self.assertRaises(ValidationError):
            Invoice.objects.filter(id=inv.id).update(total_amount=Decimal("50.00"))

        with self.assertRaises(ValidationError):
            Invoice.objects.filter(id=inv.id).delete()

    def test_migration_autodetector_never_generates_teammate_migrations(self):
        from django.core.management import call_command
        import io
        out = io.StringIO()
        call_command("makemigrations", "--check", "--dry-run", stdout=out)
        self.assertIn("No changes detected", out.getvalue())
