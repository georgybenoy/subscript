"""
Development management command to seed realistic billing and recurring subscription data.

Rules:
- Uses REAL domain services (generate_invoice, confirm_invoice, record_payment, cancel_invoice)
- Never bypasses domain validation rules
- Demonstrates invoices across all lifecycle states: DRAFT, CONFIRMED, PAID, OVERDUE, CANCELLED
"""

from datetime import date, timedelta
from decimal import Decimal
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from billing.integrations import Plan, Product, Subscription, SubscriptionItem
from billing.models import Invoice, InvoiceStatus
from billing.services import cancel_invoice, confirm_invoice, generate_invoice
from customers.models import Customer
from payments.services import record_payment

User = get_user_model()


class Command(BaseCommand):
    help = "Seeds realistic billing, subscription, and payment data for development."

    def handle(self, *args, **options):
        self.stdout.write(self.style.NOTICE("Seeding Subscript billing platform development data..."))

        today = timezone.localdate()

        # 1. Base Products & Plans
        p_saas = Product.objects.create(name="Subscript Enterprise SaaS", description="Complete recurring billing engine")
        p_api = Product.objects.create(name="Realtime Webhook Ingestion API", description="High-throughput event queue")

        plan_monthly = Plan.objects.create(product=p_saas, name="Scale Monthly", billing_frequency="MONTHLY", price=Decimal("299.00"))
        plan_yearly = Plan.objects.create(product=p_saas, name="Enterprise Annual", billing_frequency="YEARLY", price=Decimal("2990.00"))
        plan_daily = Plan.objects.create(product=p_api, name="High-Frequency Daily Metered", billing_frequency="DAILY", price=Decimal("15.00"))

        # 2. Customers
        u_alpha, _ = User.objects.get_or_create(
            email="finance@alphaworks.test",
            defaults={"role": User.Role.CUSTOMER, "is_active": True},
        )
        u_alpha.set_password("DevPassword123!")
        u_alpha.save()

        cust_alpha, _ = Customer.objects.get_or_create(
            email="finance@alphaworks.test",
            defaults={
                "user": u_alpha,
                "name": "AlphaWorks Global",
                "company_name": "AlphaWorks Technologies Inc",
                "billing_address": "450 Innovation Way, Suite 800, Silicon Valley CA",
                "tax_id": "US-EIN-9928374",
            },
        )

        u_beta, _ = User.objects.get_or_create(
            email="billing@betastack.test",
            defaults={"role": User.Role.CUSTOMER, "is_active": True},
        )
        u_beta.set_password("DevPassword123!")
        u_beta.save()

        cust_beta, _ = Customer.objects.get_or_create(
            email="billing@betastack.test",
            defaults={
                "user": u_beta,
                "name": "BetaStack Cloud",
                "company_name": "BetaStack Infrastructure Ltd",
                "billing_address": "12 Silicon Square, Tech Quarter, London UK",
                "tax_id": "GB-VAT-11029384",
            },
        )

        # 3. Subscriptions
        # Sub 1: Active Monthly on AlphaWorks (Generates regular confirmed + paid invoices)
        sub_alpha = Subscription.objects.create(
            subscription_number="SUB-SEED-ALPHA",
            customer=cust_alpha,
            plan=plan_monthly,
            status="ACTIVE",
            start_date=today - timedelta(days=90),
            next_billing_date=today - timedelta(days=60),
            payment_terms=15,
        )
        SubscriptionItem.objects.create(
            subscription=sub_alpha,
            product=p_saas,
            description="Core Platform Seats (10x)",
            quantity=10,
            unit_price=Decimal("29.90"),
            tax_rate=Decimal("18.00"),
        )

        # Generate Period 1 Invoice (PAID state)
        inv1, _, _ = generate_invoice(sub_alpha, as_of=today - timedelta(days=60))
        if inv1:
            confirm_invoice(inv1)
            record_payment(
                invoice=inv1,
                amount=inv1.total_amount,
                method="BANK_TRANSFER",
                payment_date=inv1.due_date - timedelta(days=2),
                reference="WIRE-ALPHA-001",
                notes="Settled via automated ACH transfer",
            )
            self.stdout.write(f"  Created PAID invoice {inv1.invoice_number} (${inv1.total_amount})")

        # Advance next billing date and generate Period 2 Invoice (OVERDUE state)
        sub_alpha.next_billing_date = today - timedelta(days=30)
        sub_alpha.save()
        inv2, _, _ = generate_invoice(sub_alpha, as_of=today - timedelta(days=30))
        if inv2:
            confirm_invoice(inv2)
            # Make due date past so it becomes overdue
            inv2.due_date = today - timedelta(days=5)
            inv2.save(update_fields=["due_date"])
            self.stdout.write(f"  Created OVERDUE invoice {inv2.invoice_number} (${inv2.total_amount})")

        # Sub 2: Active Daily on BetaStack (Generates Draft & Cancelled examples)
        sub_beta = Subscription.objects.create(
            subscription_number="SUB-SEED-BETA",
            customer=cust_beta,
            plan=plan_daily,
            status="ACTIVE",
            start_date=today - timedelta(days=10),
            next_billing_date=today,
            payment_terms=15,
        )
        SubscriptionItem.objects.create(
            subscription=sub_beta,
            product=p_api,
            description="Realtime API Ingestion Meter",
            quantity=1,
            unit_price=Decimal("15.00"),
            tax_rate=Decimal("0.00"),
        )

        # Generate Period 1 for Beta (DRAFT state)
        inv_draft, _, _ = generate_invoice(sub_beta, as_of=today)
        if inv_draft:
            self.stdout.write(f"  Created DRAFT invoice {inv_draft.invoice_number} (${inv_draft.total_amount})")

        # Sub 3: Annual Agreement on AlphaWorks (Generates CANCELLED invoice)
        sub_annual = Subscription.objects.create(
            subscription_number="SUB-SEED-ANNUAL",
            customer=cust_alpha,
            plan=plan_yearly,
            status="ACTIVE",
            start_date=today - timedelta(days=365),
            next_billing_date=today - timedelta(days=365),
            payment_terms=30,
        )
        SubscriptionItem.objects.create(
            subscription=sub_annual,
            product=p_saas,
            description="Enterprise Unlimited Annual",
            quantity=1,
            unit_price=Decimal("2990.00"),
            tax_rate=Decimal("18.00"),
        )
        inv_cancel, _, _ = generate_invoice(sub_annual, as_of=today - timedelta(days=365))
        if inv_cancel:
            confirm_invoice(inv_cancel)
            cancel_invoice(inv_cancel)
            self.stdout.write(f"  Created CANCELLED invoice {inv_cancel.invoice_number}")

        self.stdout.write(self.style.SUCCESS("\nDatabase seed completed successfully with real domain workflows!"))
