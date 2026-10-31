# Subscript Platform Architecture & Developer Guide

This document specifies the technical architecture, development conventions, and cross-team integration contracts for **Subscript**, a Subscription Management and Recurring Billing modular monolith platform.

---

## 1. Modular Monolith Architecture & Ownership

Subscript is architected as a clean modular Django monolith. Each app represents a discrete domain.

| Application | Domain Scope | Owning Member | Responsibilities |
| :--- | :--- | :--- | :--- |
| `config/` | System Core & Settings | Backend Lead | Central configuration, root URL routing, security middleware, logging, environment variables. |
| `accounts/` | Identity, Auth & RBAC | Backend Lead | Custom User model, authentication, password reset, role authorization (`ADMIN`, `STAFF`, `CUSTOMER`), login throttling. |
| `customers/` | Customer Registry | Backend Lead | Customer entity, business profile, contact details, tax ID, scoping helpers, IDOR defense. |
| `products/` | Catalog & Plans | Member 3 | SaaS products, add-on variants (`ProductVariant`), recurring billing plans (`Plan`). |
| `subscriptions/`| Subscription Lifecycle | Member 3 | Active subscriptions, billing periods, plan attachments, line items (`SubscriptionItem`). |
| `discounts/` | Coupons & Promotions | Member 3 | Discount codes, fixed & percentage promotions, redemptions. |
| `billing/` | Invoicing & Statements | Member 4 | Invoices (`Invoice`), line items (`InvoiceItem`), PDF invoice generation via ReportLab, tax calculations. |
| `payments/` | Transaction Processing | Member 4 | Payment execution, transaction references, payment gateway hooks, status tracking. |
| `analytics/` | Financial Reporting | Member 4 | MRR, ARR, churn, lifetime value, and cohort charts (via Chart.js). |
| `templates/` & `static/` | UI & Presentation | Member 2 | Bootstrap 5 layout, custom CSS, HTMX reactive patterns, Chart.js bundles, form styling. |

---

## 2. URL Routing Conventions

Root URL dispatching is centralized in `config/urls.py`. All apps follow strict namespacing rules:

### Root URL Table

| Root Prefix | Included App / View | Namespace (`app_name`) | Example Named URL | Trailing Slash |
| :--- | :--- | :--- | :--- | :--- |
| `/` | `config.views.dashboard_view` | (Global root) | `{% url 'dashboard' %}` | Required |
| `/admin/` | `django.contrib.admin.site.urls` | `admin` | `{% url 'admin:index' %}` | Required |
| `/accounts/` | `accounts.urls` | `accounts` | `{% url 'accounts:login' %}` | Required |
| `/customers/` | `customers.urls` | `customers` | `{% url 'customers:detail' pk %}` | Required |
| `/products/` | `products.urls` | `products` | `{% url 'products:plan_list' %}` | Required |
| `/subscriptions/`| `subscriptions.urls` | `subscriptions` | `{% url 'subscriptions:list' %}` | Required |
| `/discounts/` | `discounts.urls` | `discounts` | `{% url 'discounts:apply' %}` | Required |
| `/billing/` | `billing.urls` | `billing` | `{% url 'billing:invoice_detail' pk %}` | Required |
| `/payments/` | `payments.urls` | `payments` | `{% url 'payments:checkout' %}` | Required |
| `/analytics/` | `analytics.urls` | `analytics` | `{% url 'analytics:mrr' %}` | Required |

### Rules:
1. **Always use trailing slashes** for all route paths (e.g., `path("invoices/", ...)`).
2. **Reverse using `<app_name>:<action>` syntax** in templates and Python code (e.g. `reverse("customers:detail", kwargs={"pk": customer.pk})`).
3. **Empty `urlpatterns = []`** in teammate skeletons ensures other apps can boot and pass system checks even before feature implementation.

---

## 3. Business Service Layer Conventions

To keep views thin, maintainable, and testable:
1. **Views are HTTP adapters only**:
   - Views handle HTTP request validation, CSRF verification, form binding, calling services, and returning `HttpResponse` or redirects.
2. **Business logic lives in `services.py`**:
   - Model creation, complex calculations, database mutations, external calls, and authorization enforcement reside in `<app>/services.py`.
3. **NO cross-app model imports at module level**:
   - Cross-app model imports at module header level create circular dependencies.
   - Cross-app references in models MUST use string references (e.g. `"customers.Customer"`).
   - In service functions, use `django.apps.apps.get_model("app_label", "ModelName")` or lazy imports inside the function body.

---

## 4. Authentication & RBAC Permission Matrix

Subscript enforces 3 distinct roles defined in `accounts.models.User.Role`:

| Capability / Resource | ADMIN | STAFF | CUSTOMER | Anonymous |
| :--- | :---: | :---: | :---: | :---: |
| Authenticate / Reset Password | Yes | Yes | Yes | Yes |
| Access Dashboard (`/`) | Yes (Admin View) | Yes (Staff View) | Yes (Customer Portal) | Redirects to Login |
| Manage Staff & User Status | Yes | No (403) | No (403) | Redirects to Login |
| View Customer Directory | Yes (All) | Yes (All) | Yes (Own Record Only) | Redirects to Login |
| Create / Deactivate Customers | Yes | Yes | No (403) | Redirects to Login |
| Edit Customer Data | Yes (All) | Yes (All) | Yes (Own Contact/Billing) | Redirects to Login |
| Manage Plans & Products | Yes | Yes | View Active Only | View Public Only |
| Generate & Manage Invoices | Yes | Yes | View Own Only | No (403/Login) |
| Execute Payments | Yes | Yes | Pay Own Invoices | No (403/Login) |
| View Financial Analytics | Yes | Yes | No (403) | Redirects to Login |

---

## 5. Customer Scoping Pattern (`scope_queryset_for_user`)

To prevent Insecure Direct Object Reference (IDOR) vulnerabilities and data leakage across tenants, **Member 3** and **Member 4** MUST scope all customer-facing querysets using the reusable helper in `customers.services`:

```python
from customers.services import scope_queryset_for_user
```

### Signature:
```python
scope_queryset_for_user(qs: QuerySet, user: User, customer_lookup: str = "customer__user") -> QuerySet
```

### Behavior:
- **Admin / Staff**: Returns `qs.all()`.
- **Customer**: Returns `qs.filter(**{customer_lookup: user})`.
- **Anonymous / Inactive**: Returns `qs.none()`.

### Teammate Integration Examples:

#### 1. Member 3 (`subscriptions` app):
```python
# subscriptions/services.py
from customers.services import scope_queryset_for_user
from .models import Subscription

def get_subscriptions_for_user(user):
    return scope_queryset_for_user(
        Subscription.objects.select_related("plan", "customer"),
        user=user,
        customer_lookup="customer__user",
    )
```

#### 2. Member 4 (`billing` app):
```python
# billing/services.py
from customers.services import scope_queryset_for_user
from .models import Invoice

def get_invoices_for_user(user):
    return scope_queryset_for_user(
        Invoice.objects.select_related("customer"),
        user=user,
        customer_lookup="customer__user",
    )
```

#### 3. Member 4 (`payments` app):
```python
# payments/services.py
from customers.services import scope_queryset_for_user
from .models import Payment

def get_payments_for_user(user):
    return scope_queryset_for_user(
        Payment.objects.select_related("invoice", "customer"),
        user=user,
        customer_lookup="customer__user",
    )
```

---

## 6. Integration Process for Teammates

### Step-by-Step for Members 2, 3, and 4:
1. **Branch Checkout**:
   - Base your feature branch off `feature/accounts-customers` (or `main` once merged).
2. **Adding URL Patterns**:
   - Add routes to your app's `urls.py`. Do not alter `config/urls.py` unless adding a top-level route.
3. **Database Migrations**:
   - Run `python manage.py makemigrations <your_app>`.
   - Never run `makemigrations` globally without specifying your app name.
   - Run `python manage.py migrate` to apply locally.
4. **Testing Before Push**:
   - Ensure `python manage.py test` passes completely without regressions.
   - Run `python manage.py check` to verify system health.

---

## 7. Template Conventions (Member 2 Ownership)

All templates extend `templates/base.html`:
- Standard template blocks:
  - `{% block title %}{% endblock %}`: Page title.
  - `{% block content %}{% endblock %}`: Main content area.
- HTMX Integration:
  - The `<body>` tag includes `hx-headers='{"X-CSRFToken": "{{ csrf_token }}"}'` so all HTMX `hx-get`, `hx-post`, and `hx-put` requests automatically send valid CSRF headers.
- Flash messages:
  - Standard Django messages framework is rendered automatically above `{% block content %}` in `templates/base.html`.

---

## 8. Full Resolved Project URL Map

All URLs resolved by django.urls.get_resolver() across all integrated applications:

| Path Pattern | URL Name | Namespace | View / Callback | Auth / Access Requirement |
| :--- | :--- | :--- | :--- | :--- |
| / | dashboard | - | config.views.dashboard_view | Login required (Role-aware dashboard) |
| ccounts/register/ | ccounts:register | ccounts | ccounts.views.register_view | Public / Anonymous |
| ccounts/login/ | ccounts:login | ccounts | ccounts.views.login_view | Public (Rate-limited, max 5 attempts) |
| ccounts/logout/ | ccounts:logout | ccounts | ccounts.views.logout_view | Login required |
| ccounts/password_reset/ | ccounts:password_reset | ccounts | django.contrib.auth.views.PasswordResetView | Public |
| ccounts/password_reset/done/ | ccounts:password_reset_done | ccounts | django.contrib.auth.views.PasswordResetDoneView | Public |
| ccounts/reset/<uidb64>/<token>/ | ccounts:password_reset_confirm | ccounts | django.contrib.auth.views.PasswordResetConfirmView | Public |
| ccounts/reset/done/ | ccounts:password_reset_complete | ccounts | django.contrib.auth.views.PasswordResetCompleteView | Public |
| ccounts/password_change/ | ccounts:password_change | ccounts | django.contrib.auth.views.PasswordChangeView | Login required |
| ccounts/password_change/done/ | ccounts:password_change_done | ccounts | django.contrib.auth.views.PasswordChangeDoneView | Login required |
| ccounts/profile/ | ccounts:profile | ccounts | ccounts.views.profile_view | Login required |
| ccounts/staff/create/ | ccounts:staff_create | ccounts | ccounts.views.staff_create_view | Admin only |
| ccounts/users/ | ccounts:user_list | ccounts | ccounts.views.user_list_view | Admin only |
| ccounts/users/<id>/toggle-active/ | ccounts:user_toggle_active | ccounts | ccounts.views.user_toggle_active_view | Admin only |
| customers/ | customers:list | customers | customers.views.customer_list_view | Login required (Staff/Admin all, Customer own) |
| customers/create/ | customers:create | customers | customers.views.customer_create_view | Staff / Admin only |
| customers/<pk>/ | customers:detail | customers | customers.views.customer_detail_view | Login required (Object-level IDOR check) |
| customers/<pk>/edit/ | customers:edit | customers | customers.views.customer_edit_view | Login required (Staff/Admin or own profile) |
| customers/<pk>/status/ | customers:status_toggle | customers | customers.views.customer_status_toggle_view | Staff / Admin only |
| illing/ | illing:invoice_list | illing | illing.views.invoice_list_view | Login required (Scoped by role) |
| illing/invoices/ | illing:invoice_list_invoices | illing | illing.views.invoice_list_view | Login required (Alias) |
| illing/<pk>/ | illing:invoice_detail | illing | illing.views.invoice_detail_view | Login required (Scoped by role) |
| illing/invoices/<pk>/ | illing:invoice_detail_invoices | illing | illing.views.invoice_detail_view | Login required (Alias) |
| illing/<pk>/confirm/ | illing:invoice_confirm | illing | illing.views.confirm_invoice_view | Staff / Admin only |
| illing/<pk>/cancel/ | illing:invoice_cancel | illing | illing.views.cancel_invoice_view | Staff / Admin only |
| illing/<pk>/pdf/ | illing:invoice_pdf | illing | illing.views.invoice_pdf_view | Login required (Scoped by role) |
| illing/invoices/<pk>/pdf/ | illing:invoice_pdf_alias | illing | illing.views.invoice_pdf_view | Login required (Alias) |
| payments/ | payments:payment_list | payments | payments.views.payment_list_view | Login required (Scoped by role) |
| payments/create/ | payments:payment_create | payments | payments.views.payment_create_view | Staff / Admin only |
| payments/record/ | payments:payment_record | payments | payments.views.payment_create_view | Staff / Admin only (Alias) |
| payments/<pk>/ | payments:payment_detail | payments | payments.views.payment_detail_view | Login required (Scoped by role) |
| nalytics/ | nalytics:dashboard | nalytics | nalytics.views.analytics_dashboard_view | Staff / Admin only |
| nalytics/data/ | nalytics:data | nalytics | nalytics.views.analytics_data_json_view | Staff / Admin only |
