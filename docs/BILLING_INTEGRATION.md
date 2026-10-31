# Subscript Billing, Payments & Analytics Integration Contract

**Domain:** Billing, Payments, and Financial Intelligence (`billing`, `payments`, `analytics`)  
**Owner:** Member 4 (Senior Backend Engineer)  
**Status:** Active  

---

## 1. Integration Boundary with Member 3 (Products, Subscriptions, Discounts)

To maintain clean decoupling and prevent circular imports, all interactions with Member 3's apps pass through `billing/integrations.py`.

### A. Requests for Member 3
1. **Model Contract:**
   - **`products.Product`**: Must have `name`, `description`, `is_active`.
   - **`products.Plan`**: Must have `name`, `billing_frequency` (choices: `'DAILY'`, `'WEEKLY'`, `'MONTHLY'`, `'YEARLY'`), `price` (DecimalField), `currency`.
   - **`subscriptions.Subscription`**:
     - `subscription_number`: CharField unique.
     - `customer`: ForeignKey to `"customers.Customer"`, `on_delete=models.PROTECT`.
     - `plan`: ForeignKey to `"products.Plan"`, `on_delete=models.PROTECT`.
     - `status`: Choices `['DRAFT', 'QUOTATION', 'CONFIRMED', 'ACTIVE', 'PAUSED', 'CLOSED']`.
     - `start_date`: DateField.
     - `expiry_date`: DateField, nullable.
     - `next_billing_date`: DateField.
     - `payment_terms`: IntegerField representing due date offset in days (fallback: 15 days).
   - **`subscriptions.SubscriptionItem`**:
     - `subscription`: ForeignKey to `"subscriptions.Subscription"`, `related_name="items"`.
     - `product`: ForeignKey to `"products.Product"`, nullable.
     - `quantity`: PositiveIntegerField.
     - `unit_price`: DecimalField(12, 2).
     - `tax_rate`: DecimalField(5, 2), e.g. 18.00 for 18%.
   - **`discounts.Discount`**:
     - `code`: CharField unique.
     - `discount_type`: `'PERCENTAGE'` or `'FIXED'`.
     - `amount`: DecimalField(12, 2).
     - `usage_count` / `times_redeemed`: PositiveIntegerField.
     - `is_active`: BooleanField.

2. **Date Progression Helper:**
   - Function requested: `subscriptions.services.calculate_next_billing_date(current_date, billing_frequency) -> date`.
   - Fallback stub provided in `billing.integrations.calculate_next_billing_date`.

3. **Discount Resolution & Atomic Commit:**
   - Function requested: `discounts.services.get_applicable_discount(subscription, subtotal, quantity, at_date=None) -> Decimal`.
   - Extended helper needed by Billing: `resolve_discount(subscription, subtotal, quantity, at_date)` which returns `(amount: Decimal, discount_obj: Optional[Discount])`.
   - Atomic commit helper: `commit_discount_usage(discount_obj)` which executes `discount.usage_count = F("usage_count") + 1` atomically.
   - Usage must ONLY be committed on invoice confirmation (`confirm_invoice`), NEVER during draft generation or preview.

---

## 2. Integration Boundary with Member 2 (Templates & UI)

The following context keys and model properties are provided to guarantee seamless compatibility with Member 2's templates in `templates/invoices/`, `templates/payments/`, and `templates/analytics/`:

### A. Model Properties
- **`Invoice.total`**: Alias for `Invoice.total_amount` (Decimal).
- **`Invoice.customer`**: Resolves to `Invoice.subscription.customer`.
- **`Invoice.is_overdue`**: Boolean property indicating non-cancelled, past due date, and outstanding balance > 0.
- **`Invoice.outstanding_balance`**: Decimal calculation of remaining balance.
- **`InvoiceItem.amount`**: Alias for `InvoiceItem.line_total` (Decimal).
- **`Payment.transaction_reference`**: Alias for `Payment.reference`.
- **`Payment.payment_method`**: Alias for `Payment.method`.
- **`Payment.customer`**: Resolves to `Payment.invoice.customer`.

### B. View Context Specifications
1. **`invoices/list.html`**:
   - `invoices`: QuerySet of `Invoice` objects (annotated with `paid_amount` and `outstanding`).
   - `page_obj`: Django Paginator page object.
2. **`invoices/detail.html`**:
   - `invoice`: Single `Invoice` instance with prefetched `items` and `payments`.
3. **`payments/list.html`**:
   - `payments`: QuerySet of `Payment` objects.
   - `page_obj`: Django Paginator page object.
4. **`payments/form.html`**:
   - `form`: Payment creation form with CSRF protection.
5. **`analytics/index.html`**:
   - `mrr`, `arr`, `collections`, `overdue_amount`, `active_subscriptions`, `churn_rate`, `ltv`.

---

## 3. Strict Architectural Decisions

1. **Unique Billing Periods:**
   - Database constraint: `UniqueConstraint(fields=['subscription', 'billing_period_start', 'billing_period_end'], name='unique_subscription_billing_period')`.
   - **Rationale:** A cancelled billing period is NOT silently re-billed. If a period is cancelled, regenerating invoices skips that period to maintain immutable billing audit histories.
2. **Zero-Float Financial Policy:**
   - All arithmetic uses `Decimal` and `quantize_money()` with `ROUND_HALF_UP`.
   - Floats are rejected with a runtime `TypeError`.
3. **Derived Overdue State:**
   - Overdue is never stored as an enum column. It is dynamically computed via database annotations and model properties to prevent state drift.
