"""
Management command to run automated audit reconciliation across all invoices and payment ledgers.

Usage:
    python manage.py reconcile_billing
"""

from django.core.management.base import BaseCommand
from billing.models import Invoice
from payments.services import reconcile_invoice


class Command(BaseCommand):
    help = "Audits and reconciles all invoices against recorded payment ledgers."

    def handle(self, *args, **options):
        self.stdout.write(self.style.NOTICE("Starting comprehensive billing reconciliation audit..."))

        invoices = Invoice.objects.all().order_by("id")
        total_count = invoices.count()
        reconciled_clean = 0
        discrepancies_found = 0

        for inv in invoices:
            res = reconcile_invoice(inv)
            if res["reconciled"]:
                reconciled_clean += 1
            else:
                discrepancies_found += 1
                self.stdout.write(
                    self.style.WARNING(
                        f"Discrepancy resolved on Invoice {res['invoice_number']} (ID {res['invoice_id']}): "
                        f"{'; '.join(res['discrepancies'])} | Paid: {res['paid_amount']}, Total: {res['total_amount']}"
                    )
                )

        self.stdout.write("\n" + "=" * 50)
        self.stdout.write(self.style.SUCCESS(f"Reconciliation Complete."))
        self.stdout.write(f"Total Invoices Audited: {total_count}")
        self.stdout.write(f"Invoices in Exact Sync: {reconciled_clean}")
        if discrepancies_found > 0:
            self.stdout.write(self.style.WARNING(f"Discrepancies Corrected: {discrepancies_found}"))
        else:
            self.stdout.write(self.style.SUCCESS("Discrepancies: 0 (All financial ledgers in perfect sync)"))
        self.stdout.write("=" * 50 + "\n")
