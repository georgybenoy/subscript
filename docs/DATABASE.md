# Subscript Database Schema Contract

This document defines the authoritative database model contract for the **Subscript** Subscription Management and Recurring Billing Platform (Make-a-ton hackathon).

---

## 1. Architectural Rules for All Members

1. **Monetary Precision Rule**:
   - ALL monetary amounts MUST use `models.DecimalField(max_digits=12, decimal_places=2)`.
   - Never use `FloatField` or integer cents for monetary calculations.
2. **Cross-App Foreign Key Rule**:
   - Never import models directly across apps (to prevent circular import cycles).
   - Use string references for foreign keys across apps (e.g. `"customers.Customer"`, `"subscriptions.Subscription"`, `"billing.Invoice"`).
   - For user references, ALWAYS use `settings.AUTH_USER_MODEL` (configured to `"accounts.User"`).
3. **App Ownership Boundaries**:
   - **Backend Lead**: `accounts/`, `customers/`, `config/`, shared settings.
   - **Member 2**: `templates/`, `static/`, UI integration.
   - **Member 3**: `products/`, `subscriptions/`, `discounts/`.
   - **Member 4**: `billing/`, `payments/`, `analytics/`.
   - No team member shall redefine or modify another member's models or business logic without prior coordination.
4. **Deletion Protection**:
   - Financial and billing models MUST use `models.PROTECT` on `Customer`, `Subscription`, and `Invoice` foreign keys to preserve audit trails.

---

## 2. ASCII Relationship Diagram

```text
+---------------------+
|    accounts.User    |
| (AUTH_USER_MODEL)   |
+----------+----------+
           | 1:1 (nullable)
           v
+---------------------+           +------------------------+
|  customers.Customer |<----------|    discounts.Discount   |
+----------+----------+           +-----------+------------+
           |                                  |
           | 1:N                              | 1:N
           v                                  v
+---------------------+           +------------------------+
| subscriptions.      |<----------|     products.Plan      |
|    Subscription     |           +-----------+------------+
+----------+----------+                       | 1:N
           |                                  v
           | 1:N                  +------------------------+
           |                      |    products.Product    |
           |                      +-----------+------------+
           |                                  | 1:N
           v                                  v
+---------------------+           +------------------------+
| subscriptions.      |---------->| products.ProductVariant|
|  SubscriptionItem   |           +------------------------+
+---------------------+
           |
           | 1:N (periodically billed)
           v
+---------------------+
|   billing.Invoice   |<----------+
+----------+----------+           |
           |                      | 1:N
           | 1:N                  |
           v                      |
+---------------------+   +---------------------+
| billing.InvoiceItem |   |  payments.Payment   |
+---------------------+   +---------------------+
```

---

## 3. Data Dictionary & Contract Specification

### A. App: `accounts` (Owner: Backend Lead)

#### `User(AbstractUser)`
- Primary authentication identity.
- **Fields**:
  - `id`: `BigAutoField` (PK)
  - `email`: `EmailField(unique=True, max_length=255)` (`USERNAME_FIELD`)
  - `username`: `CharField(max_length=150, blank=True, null=True)` (optional display name)
  - `role`: `CharField(max_length=20, choices=[ADMIN, STAFF, CUSTOMER], default=CUSTOMER)`
  - `is_active`: `BooleanField(default=True)`
  - `created_at`: `DateTimeField(auto_now_add=True)`
  - `updated_at`: `DateTimeField(auto_now=True)`

---

### B. App: `customers` (Owner: Backend Lead)

#### `Customer`
- Subscriber identity (individual or business).
- **Fields**:
  - `id`: `BigAutoField` (PK)
  - `user`: `OneToOneField(settings.AUTH_USER_MODEL, on_delete=SET_NULL, null=True, blank=True, related_name="customer_profile")`
  - `name`: `CharField(max_length=255)`
  - `company_name`: `CharField(max_length=255, blank=True)`
  - `email`: `EmailField(max_length=255, db_index=True)`
  - `phone`: `CharField(max_length=50, blank=True)`
  - `billing_address`: `TextField(blank=True)`
  - `city`: `CharField(max_length=100, blank=True)`
  - `state`: `CharField(max_length=100, blank=True)`
  - `country`: `CharField(max_length=100, blank=True, default="IN")`
  - `tax_id`: `CharField(max_length=100, blank=True)` (e.g. GSTIN, VAT, TIN)
  - `is_active`: `BooleanField(default=True)`
  - `created_at`: `DateTimeField(auto_now_add=True)`
  - `updated_at`: `DateTimeField(auto_now=True)`

---

### C. App: `products` (Owner: Member 3)

#### `Product`
- Core service or SaaS product offering.
- **Fields**:
  - `id`: `BigAutoField` (PK)
  - `name`: `CharField(max_length=255)`
  - `description`: `TextField(blank=True)`
  - `is_active`: `BooleanField(default=True)`
  - `created_at`: `DateTimeField(auto_now_add=True)`
  - `updated_at`: `DateTimeField(auto_now=True)`

#### `ProductVariant`
- Specific tier or add-on SKU belonging to a product.
- **Fields**:
  - `id`: `BigAutoField` (PK)
  - `product`: `ForeignKey("products.Product", on_delete=models.CASCADE, related_name="variants")`
  - `name`: `CharField(max_length=255)`
  - `sku`: `CharField(max_length=100, unique=True)`
  - `price`: `DecimalField(max_digits=12, decimal_places=2)`
  - `is_active`: `BooleanField(default=True)`
  - `created_at`: `DateTimeField(auto_now_add=True)`
  - `updated_at`: `DateTimeField(auto_now=True)`

#### `Plan`
- Recurring subscription pricing model for a product.
- **Fields**:
  - `id`: `BigAutoField` (PK)
  - `product`: `ForeignKey("products.Product", on_delete=models.CASCADE, related_name="plans")`
  - `name`: `CharField(max_length=255)`
  - `code`: `CharField(max_length=100, unique=True)` (e.g. `PRO-MONTHLY`)
  - `billing_interval`: `CharField(max_length=20, choices=[WEEKLY, MONTHLY, QUARTERLY, YEARLY])`
  - `price`: `DecimalField(max_digits=12, decimal_places=2)`
  - `currency`: `CharField(max_length=3, default="INR")`
  - `trial_days`: `PositiveIntegerField(default=0)`
  - `is_active`: `BooleanField(default=True)`
  - `created_at`: `DateTimeField(auto_now_add=True)`
  - `updated_at`: `DateTimeField(auto_now=True)`

---

### D. App: `discounts` (Owner: Member 3)

#### `Discount`
- Coupons and promotional discounts.
- **Fields**:
  - `id`: `BigAutoField` (PK)
  - `code`: `CharField(max_length=50, unique=True)`
  - `discount_type`: `CharField(max_length=20, choices=[PERCENTAGE, FIXED])`
  - `amount`: `DecimalField(max_digits=12, decimal_places=2)`
  - `valid_from`: `DateTimeField()`
  - `valid_until`: `DateTimeField(null=True, blank=True)`
  - `max_redemptions`: `PositiveIntegerField(null=True, blank=True)`
  - `times_redeemed`: `PositiveIntegerField(default=0)`
  - `is_active`: `BooleanField(default=True)`
  - `created_at`: `DateTimeField(auto_now_add=True)`
  - `updated_at`: `DateTimeField(auto_now=True)`

---

### E. App: `subscriptions` (Owner: Member 3)

#### `Subscription`
- Recurring agreement linking a Customer to a Plan.
- **Fields**:
  - `id`: `BigAutoField` (PK)
  - `customer`: `ForeignKey("customers.Customer", on_delete=models.PROTECT, related_name="subscriptions")`
  - `plan`: `ForeignKey("products.Plan", on_delete=models.PROTECT, related_name="subscriptions")`
  - `discount`: `ForeignKey("discounts.Discount", on_delete=models.SET_NULL, null=True, blank=True, related_name="subscriptions")`
  - `status`: `CharField(max_length=20, choices=[TRIALING, ACTIVE, PAST_DUE, CANCELED, PAUSED], default="ACTIVE")`
  - `current_period_start`: `DateTimeField()`
  - `current_period_end`: `DateTimeField()`
  - `cancel_at_period_end`: `BooleanField(default=False)`
  - `created_at`: `DateTimeField(auto_now_add=True)`
  - `updated_at`: `DateTimeField(auto_now=True)`

#### `SubscriptionItem`
- Line items or add-ons attached to an active subscription.
- **Fields**:
  - `id`: `BigAutoField` (PK)
  - `subscription`: `ForeignKey("subscriptions.Subscription", on_delete=models.CASCADE, related_name="items")`
  - `variant`: `ForeignKey("products.ProductVariant", on_delete=models.PROTECT, null=True, blank=True, related_name="subscription_items")`
  - `quantity`: `PositiveIntegerField(default=1)`
  - `unit_price`: `DecimalField(max_digits=12, decimal_places=2)`

---

### F. App: `billing` (Owner: Member 4)

#### `Invoice`
- Billing statement generated for subscription periods.
- **Fields**:
  - `id`: `BigAutoField` (PK)
  - `customer`: `ForeignKey("customers.Customer", on_delete=models.PROTECT, related_name="invoices")`
  - `subscription`: `ForeignKey("subscriptions.Subscription", on_delete=models.SET_NULL, null=True, blank=True, related_name="invoices")`
  - `invoice_number`: `CharField(max_length=100, unique=True)`
  - `status`: `CharField(max_length=20, choices=[DRAFT, OPEN, PAID, UNCOLLECTIBLE, VOID], default="DRAFT")`
  - `subtotal`: `DecimalField(max_digits=12, decimal_places=2)`
  - `tax_amount`: `DecimalField(max_digits=12, decimal_places=2, default=0.00)`
  - `discount_amount`: `DecimalField(max_digits=12, decimal_places=2, default=0.00)`
  - `total`: `DecimalField(max_digits=12, decimal_places=2)`
  - `due_date`: `DateField()`
  - `paid_at`: `DateTimeField(null=True, blank=True)`
  - `created_at`: `DateTimeField(auto_now_add=True)`
  - `updated_at`: `DateTimeField(auto_now=True)`

#### `InvoiceItem`
- Individual billing lines on an invoice.
- **Fields**:
  - `id`: `BigAutoField` (PK)
  - `invoice`: `ForeignKey("billing.Invoice", on_delete=models.CASCADE, related_name="items")`
  - `description`: `CharField(max_length=255)`
  - `quantity`: `PositiveIntegerField(default=1)`
  - `unit_price`: `DecimalField(max_digits=12, decimal_places=2)`
  - `amount`: `DecimalField(max_digits=12, decimal_places=2)`

---

### G. App: `payments` (Owner: Member 4)

#### `Payment`
- Monetary transaction against an invoice.
- **Fields**:
  - `id`: `BigAutoField` (PK)
  - `invoice`: `ForeignKey("billing.Invoice", on_delete=models.PROTECT, related_name="payments")`
  - `customer`: `ForeignKey("customers.Customer", on_delete=models.PROTECT, related_name="payments")`
  - `amount`: `DecimalField(max_digits=12, decimal_places=2)`
  - `currency`: `CharField(max_length=3, default="INR")`
  - `payment_method`: `CharField(max_length=30, choices=[CARD, UPI, NET_BANKING, OFFLINE], default="CARD")`
  - `transaction_reference`: `CharField(max_length=150, unique=True)`
  - `status`: `CharField(max_length=20, choices=[PENDING, SUCCESS, FAILED, REFUNDED], default="PENDING")`
  - `created_at`: `DateTimeField(auto_now_add=True)`

---

### H. App: `analytics` (Owner: Member 4)
- Aggregates and reports MRR, ARR, churn rate, and cohort metrics across `subscriptions`, `billing`, and `payments`.
