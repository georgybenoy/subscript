# Subscript Billing, Payments & Analytics Integration Contract & Architecture Guide

**Author:** Member 4 (Senior Backend Engineer — Billing, Payments, Analytics, and Financial Intelligence)  
**Apps Owned:** `billing/`, `payments/`, `analytics/`, `tests/`, `billing/management/commands/`  
**Monolithic Boundaries:** Clean decoupling, zero-float financial policies, snapshot immutability, and database-level aggregations.

---

## 1. Domain Overview & Model Architecture

### Models

#### `billing.Invoice` (`billing_invoice`)
- **Primary Fields:** `invoice_number` (Unique, format `INV-<year>-<6-digit seq>`), `issue_date`, `due_date`, `billing_period_start`, `billing_period_end`.
- **Monetary Precision:** `subtotal`, `discount_amount`, `tax_amount`, `total_amount` — all `DecimalField(max_digits=12, decimal_places=2)`.
- **Status Enum:** `InvoiceStatus.choices` = `['DRAFT', 'CONFIRMED', 'PAID', 'CANCELLED']`.
- **Foreign Keys:**
  - `subscription`: Foreign key to `"subscriptions.Subscription"` (`on_delete=models.PROTECT`, `db_constraint=False`).
  - `applied_discount`: Nullable Foreign key to `"discounts.Discount"` (`on_delete=models.SET_NULL`, `db_constraint=False`).
- **Constraints & Indexes:**
  - `UniqueConstraint(fields=['subscription', 'billing_period_start', 'billing_period_end'], name='unique_subscription_billing_period')`: Strict audit guarantee — a cancelled period is never silently re-billed.
  - `CheckConstraint(check=Q(total_amount__gte=Decimal('0.00')), name='check_invoice_total_non_negative')`.
  - Indexes on `status`, `due_date`, `(subscription, billing_period_start)`, and `created_at`.
- **Derived Properties & QuerySet Annotations:**
  - `is_overdue`: Derived dynamically: `status != 'CANCELLED'`, `status != 'PAID'`, `due_date < today`, and `outstanding_balance > 0`.
  - `InvoiceQuerySet.overdue(as_of=None)`: Database-level filterable queryset method using `with_outstanding()`.
  - Immutability: Blocked from mutating financial totals, line items, or periods once confirmed, paid, or cancelled (both in `save()` and bulk `update()` / `delete()`).

#### `billing.InvoiceItem` (`billing_invoiceitem`)
- **Primary Fields:** `invoice` (FK CASCADE), `product` (FK SET_NULL), `description`, `quantity`, `unit_price`, `tax_rate`, `line_subtotal`, `line_tax`, `line_total`.
- **Snapshot Immutability:** Prices and tax rates are point-in-time snapshots copied at billing time; live product updates never alter past statements.
- **Audit Defense:** Cannot add, modify, or bulk-mutate line items on confirmed, paid, or cancelled invoices.

#### `payments.Payment` (`payments_payment`)
- **Primary Fields:** `invoice` (FK PROTECT), `amount`, `method` (`['BANK_TRANSFER', 'CASH', 'CARD', 'UPI', 'OTHER']`), `payment_date`, `reference`, `notes`, `created_at`.
- **Permanent Audit Record:** Single or bulk deletion is strictly forbidden (`ValidationError`). `update()` is blocked on monetary and reference fields.

---

## 2. Shared Integration Boundaries

### A. Boundary with Member 3 (Products, Subscriptions, Discounts)
All interactions with Member 3's domain pass through `billing/integrations.py`.

1. **Model Contract Expected from Member 3:**
   - `products.Product`: `name`, `description`, `is_active`.
   - `products.Plan`: `name`, `billing_frequency` (`'DAILY'`, `'WEEKLY'`, `'MONTHLY'`, `'YEARLY'`), `price` (`DecimalField`), `currency`.
   - `subscriptions.Subscription`:
     - `subscription_number`: Unique string.
     - `customer`: ForeignKey to `customers.Customer` (`on_delete=models.PROTECT`).
     - `plan`: ForeignKey to `products.Plan` (`on_delete=models.PROTECT`).
     - `status`: `['DRAFT', 'QUOTATION', 'CONFIRMED', 'ACTIVE', 'PAUSED', 'CLOSED']`.
     - `start_date`, `expiry_date`, `next_billing_date` (DateFields).
     - `payment_terms`: Integer offset in days (defaults to 15).
   - `subscriptions.SubscriptionItem`:
     - `subscription`: ForeignKey (`related_name="items"`).
     - `product`: ForeignKey to `products.Product`.
     - `quantity`: Positive integer.
     - `unit_price`: DecimalField(12, 2).
     - `tax_rate`: DecimalField(5, 2) snapshot (e.g., 18.00).
   - `discounts.Discount`:
     - `code`: Unique string.
     - `discount_type`: `'PERCENTAGE'` or `'FIXED'`.
     - `amount`: DecimalField(12, 2).
     - `usage_count`: Positive integer.
     - `is_active`: Boolean.

2. **Integration Functions & Services:**
   - `billing.integrations.calculate_next_billing_date(current_date, billing_frequency) -> date`:
     Handles leap years, 30/31-day month boundaries, and frequency offsets. Member 3 can swap in their implementation seamlessly.
   - `billing.integrations.resolve_discount(subscription, subtotal, total_quantity, at_date=None) -> (Decimal, Optional[Discount])`:
     Resolves coupon or tiered discounts. Capped at subtotal, never produces a negative invoice.
   - `billing.integrations.commit_discount_usage(discount_obj)`:
     Atomically increments `discount.usage_count = F("usage_count") + 1`. Executed strictly upon invoice confirmation (`confirm_invoice`), NEVER during draft generation.

3. **Step-by-Step Instructions for Member 3 when connecting real models:**
   - Step 1: Create standard Django migrations in `products/`, `subscriptions/`, and `discounts/`.
   - Step 2: Open `billing/models.py` and change `db_constraint=False` to `True` on cross-app ForeignKeys (`subscription`, `applied_discount`, `product`).
   - Step 3: Remove the runtime fallback class definitions in `billing/integrations.py`.
   - Step 4: Run `python manage.py makemigrations billing` to generate the foreign key constraint migration.
   - Step 5: Run `python manage.py test` to verify full compatibility.

---

### B. Boundary with Member 2 (UI Templates & Design)
All views cleanly feed Member 2's templates with pre-calculated, tenant-scoped contexts:

1. **`invoices/list.html`** (`/billing/`):
   - `invoices`: Paginated (25/page) QuerySet of `Invoice` records annotated with `with_paid_amount()` and `with_outstanding()`.
   - `page_obj`: Paginator page object.
   - Query filters supported: `q` (invoice number or customer name/company/email), `status` (DRAFT, CONFIRMED, PAID, CANCELLED, OVERDUE), `due_date`, `start_date`, `end_date`.

2. **`invoices/detail.html`** (`/billing/<pk>/`):
   - `invoice`: Authoritative instance with prefetched `items` and `payments`.
   - Properties available on `invoice`: `total`, `customer`, `paid_amount`, `outstanding_balance`, `is_overdue`.
   - Actions provided: Confirm (`/billing/<pk>/confirm/`), Cancel (`/billing/<pk>/cancel/`), PDF Download (`/billing/<pk>/pdf/`).

3. **`payments/list.html`** (`/payments/`):
   - `payments`: Paginated QuerySet of `Payment` audit records.
   - `page_obj`: Paginator page object.

4. **`payments/form.html`** (`/payments/create/`):
   - Form fields: `invoice`, `customer`, `amount`, `payment_method`, `transaction_reference`, `status`, `notes`.

5. **`analytics/index.html`** (`/analytics/`):
   - KPI values: `mrr`, `arr`, `collections`, `overdue_amount`, `active_subscriptions`, `churn_rate`, `ltv`.
   - Chart.js REST Endpoint: `/analytics/data/` returning exact JSON context.

---

## 3. URL Routing Reference

| Namespace & Name | Path | HTTP Method | Permissions | Purpose |
| :--- | :--- | :--- | :--- | :--- |
| `billing:invoice_list` | `/billing/` | GET | Login Required (Tenant Scoped) | Directory of invoices with multi-criteria search and pagination |
| `billing:invoice_detail` | `/billing/<int:pk>/` | GET | Login Required (Tenant Scoped) | Statement detail view with line items and payment ledgers |
| `billing:invoice_pdf` | `/billing/<int:pk>/pdf/` | GET | Login Required (Tenant Scoped) | Streaming ReportLab PDF statement download |
| `billing:invoice_confirm` | `/billing/<int:pk>/confirm/` | POST | Staff / Admin Only | Transitions DRAFT -> CONFIRMED, commits discount usage |
| `billing:invoice_cancel` | `/billing/<int:pk>/cancel/` | POST | Staff / Admin Only | Cancels invoice with zero payments |
| `payments:payment_list` | `/payments/` | GET | Login Required (Tenant Scoped) | List settled payments |
| `payments:payment_detail`| `/payments/<int:pk>/` | GET | Login Required (Tenant Scoped) | Detail view of single payment audit record |
| `payments:payment_create`| `/payments/create/` | GET / POST | Staff / Admin Only | Record payment with real-time balance validation |
| `analytics:dashboard` | `/analytics/` | GET | Staff / Admin Only | Executive HTML recurring revenue analytics dashboard |
| `analytics:data` | `/analytics/data/` | GET | Staff / Admin Only | REST JSON data endpoint for Chart.js |

---

## 4. Financial Intelligence & Analytics Context

`analytics.services.get_dashboard_context(date_from=None, date_to=None, group_by="month") -> dict`

Executes pure database aggregations without Python loops. Returns exact schema:

```json
{
  "active_subscriptions": 10,
  "mrr": "1000.00",
  "arr": "12000.00",
  "collected_revenue": "8500.00",
  "outstanding_balance": "1500.00",
  "overdue_invoice_count": 1,
  "revenue_chart": {
    "labels": ["2026-08", "2026-09", "2026-10"],
    "data": ["2500.00", "3000.00", "3000.00"]
  },
  "subscription_chart": {
    "labels": ["2026-08", "2026-09", "2026-10"],
    "data": [3, 4, 3]
  },
  "collection_chart": {
    "labels": ["2026-08", "2026-09", "2026-10"],
    "data": ["2500.00", "3000.00", "3000.00"]
  },
  "invoiced_chart": {
    "labels": ["2026-08", "2026-09", "2026-10"],
    "data": ["3000.00", "3500.00", "3500.00"]
  }
}
```

### Normalization Rules for MRR
- DAILY: `SUM(quantity * unit_price) * 365 / 12`
- WEEKLY: `SUM(quantity * unit_price) * 52 / 12`
- MONTHLY: `SUM(quantity * unit_price) * 1`
- YEARLY / ANNUAL: `SUM(quantity * unit_price) / 12`
- Gross list value (gross of discounts)
- ARR strictly equals `MRR * 12`

---

## 5. Management Commands

1. **`python manage.py generate_due_invoices [--date YYYY-MM-DD] [--dry-run]`**
   - Recurring generation engine.
   - Enforces eligibility (`ACTIVE`, `next_billing_date <= today`, `period_start <= expiry_date`).
   - Caps catch-up billing at 24 cycles per subscription.
   - Idempotent and concurrency-safe with savepoints and retry sequence logic.

2. **`python manage.py reconcile_billing`**
   - Audits all invoices against the payment ledger.
   - Verifies paid amounts and auto-resolves any status discrepancies between balance and PAID status.

3. **`python manage.py seed_billing_data`**
   - Development seed command.
   - Uses real domain services exclusively to generate realistic subscribers, invoices across all lifecycle states (DRAFT, CONFIRMED, PAID, OVERDUE, CANCELLED), and payments.

---

## 6. How to Run Tests

Execute the complete 59-test suite covering models, views, services, security, immutability, PDF rendering, analytics, and end-to-end integration:

```bash
python manage.py test tests.test_billing_models tests.test_invoice_views tests.test_recurring_billing tests.test_confirm_cancel tests.test_payment_processing tests.test_pdf_and_overdue tests.test_analytics tests.test_e2e_billing_flow
```
