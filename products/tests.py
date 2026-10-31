from decimal import Decimal
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import TestCase
from products.models import Plan, Product, ProductVariant


class ProductModelTests(TestCase):
    """
    Tests for Product model: creation, validation, active status,
    and string representation.
    """

    def test_product_creation_and_attributes(self):
        """Test Product creation with required name, description and active status default."""
        product = Product.objects.create(
            name="Subscript CRM",
            description="Comprehensive customer relationship suite.",
        )
        self.assertEqual(product.name, "Subscript CRM")
        self.assertEqual(product.description, "Comprehensive customer relationship suite.")
        self.assertTrue(product.is_active)
        self.assertIsNotNone(product.created_at)
        self.assertIsNotNone(product.updated_at)

    def test_product_name_required(self):
        """Test that a blank product name is rejected by model validation."""
        product = Product(name="", description="Missing name")
        with self.assertRaises(ValidationError) as ctx:
            product.full_clean()
        self.assertIn("name", ctx.exception.message_dict)

    def test_product_str_representation(self):
        """Test Product __str__ representation returns the name."""
        product = Product(name="Billing Engine")
        self.assertEqual(str(product), "Billing Engine")


class ProductVariantModelTests(TestCase):
    """
    Tests for ProductVariant model: relationships, SKU uniqueness,
    price validation, normalization, and string representation.
    """

    def setUp(self):
        self.product = Product.objects.create(
            name="Subscript Enterprise",
            description="Enterprise tier product",
        )

    def test_variant_creation_and_relationship(self):
        """Test ProductVariant creation and its foreign key relationship to Product."""
        variant = ProductVariant.objects.create(
            product=self.product,
            name="Additional 10GB Storage",
            sku="STORAGE-10GB",
            price=Decimal("499.00"),
            is_active=True,
        )
        self.assertEqual(variant.product, self.product)
        self.assertEqual(variant.name, "Additional 10GB Storage")
        self.assertEqual(variant.sku, "STORAGE-10GB")
        self.assertEqual(variant.price, Decimal("499.00"))
        self.assertTrue(variant.is_active)
        self.assertIn(variant, self.product.variants.all())

    def test_product_variant_cascade_delete(self):
        """Test deleting a product cascades to its variants."""
        ProductVariant.objects.create(
            product=self.product,
            name="Add-on Tier",
            sku="ADDON-TIER-1",
            price=Decimal("150.00"),
        )
        self.assertEqual(self.product.variants.count(), 1)
        self.product.delete()
        self.assertEqual(ProductVariant.objects.count(), 0)

    def test_sku_uniqueness(self):
        """Test that duplicate SKUs raise an IntegrityError upon saving and ValidationError on clean."""
        ProductVariant.objects.create(
            product=self.product,
            name="Variant Alpha",
            sku="UNIQUE-SKU-001",
            price=Decimal("100.00"),
        )
        duplicate_variant = ProductVariant(
            product=self.product,
            name="Variant Beta",
            sku="UNIQUE-SKU-001",
            price=Decimal("200.00"),
        )
        with self.assertRaises(ValidationError) as clean_ctx:
            duplicate_variant.full_clean()
        self.assertIn("sku", clean_ctx.exception.message_dict)

        with self.assertRaises(IntegrityError):
            duplicate_variant.save()

    def test_negative_variant_price_rejected(self):
        """Test that negative variant prices are rejected by model validation."""
        variant = ProductVariant(
            product=self.product,
            name="Discount Addon",
            sku="INVALID-PRICE-SKU",
            price=Decimal("-10.00"),
        )
        with self.assertRaises(ValidationError) as ctx:
            variant.full_clean()
        self.assertIn("price", ctx.exception.message_dict)

    def test_zero_variant_price_allowed(self):
        """Test that zero variant price is allowed (e.g. complimentary add-ons)."""
        variant = ProductVariant(
            product=self.product,
            name="Free Addon",
            sku="FREE-SKU-001",
            price=Decimal("0.00"),
        )
        variant.full_clean()  # Should not raise
        variant.save()
        self.assertEqual(variant.price, Decimal("0.00"))

    def test_sku_normalization_through_validation_path(self):
        """Test that clean() normalizes SKU by trimming whitespace and uppercasing."""
        variant = ProductVariant(
            product=self.product,
            name="Support Pack",
            sku="  addon-support-247  ",
            price=Decimal("999.00"),
        )
        variant.full_clean()
        self.assertEqual(variant.sku, "ADDON-SUPPORT-247")

    def test_sku_normalization_through_save(self):
        """Test that save() normalizes SKU without explicit full_clean()."""
        variant = ProductVariant(
            product=self.product,
            name="Backup Tier",
            sku="  backup-tier-weekly  ",
            price=Decimal("150.00"),
        )
        variant.save()
        variant.refresh_from_db()
        self.assertEqual(variant.sku, "BACKUP-TIER-WEEKLY")

    def test_sku_normalization_through_objects_create(self):
        """Test that objects.create() normalizes SKU automatically."""
        variant = ProductVariant.objects.create(
            product=self.product,
            name="Log Audit",
            sku="  log-audit-pro  ",
            price=Decimal("250.00"),
        )
        variant.refresh_from_db()
        self.assertEqual(variant.sku, "LOG-AUDIT-PRO")

    def test_variant_str_representation(self):
        """Test ProductVariant __str__ format: '{product.name} - {name} ({sku})'."""
        variant = ProductVariant(
            product=self.product,
            name="Priority Support",
            sku="PRIORITY-SUPP",
            price=Decimal("500.00"),
        )
        self.assertEqual(str(variant), "Subscript Enterprise - Priority Support (PRIORITY-SUPP)")


class PlanModelTests(TestCase):
    """
    Tests for Plan model: creation, relationships, all billing intervals,
    price validation, code uniqueness, normalization, and string representation.
    """

    def setUp(self):
        self.product = Product.objects.create(
            name="Subscript Analytics",
            description="Analytics SaaS product",
        )

    def test_plan_creation_and_relationship(self):
        """Test Plan creation with default values and relationship to Product."""
        plan = Plan.objects.create(
            product=self.product,
            name="Pro Monthly",
            code="ANALYTICS-PRO-M",
            billing_interval=Plan.BillingInterval.MONTHLY,
            price=Decimal("1999.00"),
            currency="INR",
            trial_days=14,
            is_active=True,
        )
        self.assertEqual(plan.product, self.product)
        self.assertEqual(plan.name, "Pro Monthly")
        self.assertEqual(plan.code, "ANALYTICS-PRO-M")
        self.assertEqual(plan.billing_interval, Plan.BillingInterval.MONTHLY)
        self.assertEqual(plan.price, Decimal("1999.00"))
        self.assertEqual(plan.currency, "INR")
        self.assertEqual(plan.trial_days, 14)
        self.assertTrue(plan.is_active)
        self.assertIn(plan, self.product.plans.all())

    def test_plan_cascade_delete(self):
        """Test deleting a product cascades to its plans."""
        Plan.objects.create(
            product=self.product,
            name="Cascade Plan",
            code="CASCADE-PLAN",
            billing_interval=Plan.BillingInterval.MONTHLY,
            price=Decimal("100.00"),
        )
        self.assertEqual(self.product.plans.count(), 1)
        self.product.delete()
        self.assertEqual(Plan.objects.count(), 0)

    def test_all_four_billing_intervals(self):
        """Test that all four documented billing intervals are valid choices."""
        intervals = [
            (Plan.BillingInterval.WEEKLY, "WEEKLY-CODE"),
            (Plan.BillingInterval.MONTHLY, "MONTHLY-CODE"),
            (Plan.BillingInterval.QUARTERLY, "QUARTERLY-CODE"),
            (Plan.BillingInterval.YEARLY, "YEARLY-CODE"),
        ]
        for interval, code in intervals:
            plan = Plan(
                product=self.product,
                name=f"Plan {interval}",
                code=code,
                billing_interval=interval,
                price=Decimal("500.00"),
            )
            plan.full_clean()
            plan.save()
            self.assertEqual(plan.billing_interval, interval)

    def test_invalid_billing_interval_rejected(self):
        """Test that an unsupported billing interval is rejected by validation."""
        plan = Plan(
            product=self.product,
            name="Daily Plan",
            code="DAILY-PLAN",
            billing_interval="DAILY",
            price=Decimal("50.00"),
        )
        with self.assertRaises(ValidationError) as ctx:
            plan.full_clean()
        self.assertIn("billing_interval", ctx.exception.message_dict)

    def test_negative_plan_price_rejected(self):
        """Test that negative plan prices are rejected by model validation."""
        plan = Plan(
            product=self.product,
            name="Negative Price Plan",
            code="NEG-PRICE-PLAN",
            price=Decimal("-100.00"),
        )
        with self.assertRaises(ValidationError) as ctx:
            plan.full_clean()
        self.assertIn("price", ctx.exception.message_dict)

    def test_zero_plan_price_allowed(self):
        """Test that zero plan price is permitted (e.g. Free Tier)."""
        plan = Plan(
            product=self.product,
            name="Free Community",
            code="FREE-COMMUNITY",
            price=Decimal("0.00"),
        )
        plan.full_clean()
        plan.save()
        self.assertEqual(plan.price, Decimal("0.00"))

    def test_unique_plan_codes(self):
        """Test that duplicate plan codes raise IntegrityError on save and ValidationError on clean."""
        Plan.objects.create(
            product=self.product,
            name="Plan Prime",
            code="PLAN-UNIQUE-01",
            price=Decimal("299.00"),
        )
        duplicate_plan = Plan(
            product=self.product,
            name="Plan Prime Duplicate",
            code="PLAN-UNIQUE-01",
            price=Decimal("399.00"),
        )
        with self.assertRaises(ValidationError) as clean_ctx:
            duplicate_plan.full_clean()
        self.assertIn("code", clean_ctx.exception.message_dict)

        with self.assertRaises(IntegrityError):
            duplicate_plan.save()

    def test_plan_code_and_currency_normalization_through_validation_path(self):
        """Test that clean() normalizes code and currency to uppercase and trimmed."""
        plan = Plan(
            product=self.product,
            name="Enterprise Annual",
            code="  ent-annual-2026  ",
            currency="  usd  ",
            price=Decimal("12000.00"),
        )
        plan.full_clean()
        self.assertEqual(plan.code, "ENT-ANNUAL-2026")
        self.assertEqual(plan.currency, "USD")

    def test_plan_normalization_through_save(self):
        """Test that save() normalizes code and currency without explicit full_clean()."""
        plan = Plan(
            product=self.product,
            name="Developer Monthly",
            code="  dev-monthly  ",
            currency="  usd  ",
            price=Decimal("49.00"),
        )
        plan.save()
        plan.refresh_from_db()
        self.assertEqual(plan.code, "DEV-MONTHLY")
        self.assertEqual(plan.currency, "USD")

    def test_plan_normalization_through_objects_create(self):
        """Test that objects.create() normalizes code and currency automatically."""
        plan = Plan.objects.create(
            product=self.product,
            name="Growth Quarterly",
            code="  growth-quarterly  ",
            currency="  eur  ",
            price=Decimal("299.00"),
        )
        plan.refresh_from_db()
        self.assertEqual(plan.code, "GROWTH-QUARTERLY")
        self.assertEqual(plan.currency, "EUR")

    def test_plan_str_representation(self):
        """Test Plan __str__ format: '{product.name} - {name} ({code})'."""
        plan = Plan(
            product=self.product,
            name="Starter Monthly",
            code="START-M",
            price=Decimal("499.00"),
        )
        self.assertEqual(str(plan), "Subscript Analytics - Starter Monthly (START-M)")
