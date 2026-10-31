"""
Management command to execute batch recurring billing for subscriptions.

Usage:
    python manage.py generate_due_invoices [--date YYYY-MM-DD] [--dry-run]
"""

from datetime import datetime
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from billing.services import generate_due_invoices


class Command(BaseCommand):
    help = "Generates recurring billing invoices for due active subscriptions."

    def add_arguments(self, parser):
        parser.add_argument(
            "--date",
            type=str,
            default=None,
            help="Evaluation date in YYYY-MM-DD format (default: today).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Simulate billing run without database mutations.",
        )

    def handle(self, *args, **options):
        date_str = options.get("date")
        dry_run = options.get("dry_run", False)

        if date_str:
            try:
                as_of = datetime.strptime(date_str, "%Y-%m-%d").date()
            except ValueError:
                raise CommandError(f"Invalid date format '{date_str}'. Expected YYYY-MM-DD.")
        else:
            as_of = timezone.localdate()

        mode_label = "[DRY-RUN] " if dry_run else ""
        self.stdout.write(
            self.style.NOTICE(f"{mode_label}Executing recurring invoice generation as of {as_of}...")
        )

        summary = generate_due_invoices(as_of=as_of, dry_run=dry_run)

        self.stdout.write("\n" + "=" * 50)
        self.stdout.write(self.style.SUCCESS(f"{mode_label}Billing Run Summary:"))
        self.stdout.write(f"  - Invoices Created:      {summary['created']}")
        self.stdout.write(f"  - Skipped (Duplicates):  {summary['skipped_duplicates']}")
        self.stdout.write(f"  - Skipped (Ineligible):  {summary['skipped_ineligible']}")
        self.stdout.write(f"  - Failures / Errors:     {summary['failed']}")
        self.stdout.write("=" * 50)

        if summary["errors"]:
            self.stdout.write(self.style.ERROR("\nError details:"))
            for err in summary["errors"]:
                self.stdout.write(f"  * Subscription {err['subscription']}: {err['reason']}")

        if dry_run:
            self.stdout.write(self.style.WARNING("\nDry run complete. No records created."))
        else:
            self.stdout.write(self.style.SUCCESS(f"\nBatch processing complete. {summary['created']} invoices generated."))
