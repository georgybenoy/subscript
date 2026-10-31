# Subscript

> **Subscription Management and Recurring Billing Platform**  
> *Developed for the Make-a-ton Hackathon*

Subscript is a robust, modular Django monolith platform engineered for recurring billing lifecycles, automated subscription invoicing, payment reconciliation, and SaaS revenue intelligence.

---

## 🛠️ Tech Stack & Architecture Constraints

- **Backend Framework**: Python 3.11+, Django 5.2, Django ORM, SQLite
- **Frontend & UI**: Django Templates, Bootstrap 5.3, HTMX, Chart.js 4.4
- **Reporting & Document Generation**: ReportLab (PDF invoice generation), Pillow
- **Configuration & Secrets**: `python-dotenv` (`.env` configuration)
- **Strict Architectural Constraints**:
  - Modular Django monolith with thin views and explicit service layers (`services.py`).
  - `DecimalField(max_digits=12, decimal_places=2)` for all monetary data (never floats or integers).
  - Cross-app model relationships use string/settings-based FK references (e.g. `"customers.Customer"`, `settings.AUTH_USER_MODEL`).
  - No React, FastAPI, Redis, Celery, Docker, or microservices.

---

## 🏛️ Modular Monolith Domain Ownership

Subscript is structured as a clean modular monolith where each application represents an isolated domain communicating through thin service layers:

| App / Domain | Owning Member | Responsibilities & Scope |
| :--- | :--- | :--- |
| `config/` | **Backend Lead** | Root URL routing, shared settings, security middleware, environment configuration, role-aware dashboard. |
| `accounts/` | **Backend Lead** | Custom email-based User model, RBAC authorization (`ADMIN`, `STAFF`, `CUSTOMER`), password reset, rate-limited login. |
| `customers/` | **Backend Lead** | Customer registry, business profiles, HTMX live search, IDOR defense, and `scope_queryset_for_user` helper. |
| `products/` | **Member 3** | Product catalog (`Product`), add-on SKUs (`ProductVariant`), recurring billing plans (`Plan`). |
| `subscriptions/`| **Member 3** | Subscription lifecycle, billing intervals, plan attachments, line items. |
| `discounts/` | **Member 3** | Promotional coupons, percentage & fixed discounts, redemption tracking. |
| `billing/` | **Member 4** | Invoicing (`Invoice`, `InvoiceItem`), PDF invoice generation via ReportLab, tax calculation. |
| `payments/` | **Member 4** | Payment ledger (`Payment`), immutable transaction records, payment methods. |
| `analytics/` | **Member 4** | SaaS intelligence (MRR, ARR, collections, overdue balances, Chart.js visualizations). |
| `templates/` & `static/` | **Member 2** | Design system (`subscript.css`), Bootstrap 5 layouts, sidebar, HTMX modals, Chart.js modules. |

---

## 🚀 Key Features Implemented (Phases 1–5)

### 1. Custom Identity & Authentication (`accounts/`)
- **Email as Primary Key**: Custom user model using email for login (`USERNAME_FIELD = "email"`).
- **Strict Password Complexity**: Mandatory 9+ characters with uppercase, lowercase, and special characters enforced by `SubscriptPasswordValidator`.
- **Brute-Force Lockout Defense**: 5 consecutive failed login attempts trigger an automatic 5-minute lockout per email/IP pair via Django cache.
- **Zero-Enumeration Password Reset**: Fully implemented self-service password reset and password change workflows that prevent account enumeration.

### 2. Role-Based Access Control (RBAC) & Backend Authorization
- **Three Roles**: System Administrator (`ADMIN`), Operations Staff (`STAFF`), and Subscriber (`CUSTOMER`).
- **Backend-Enforced Security**: Single source of truth in `accounts/permissions.py` with decorators (`@admin_required`, `@staff_or_admin_required`, `@customer_required`) and CBV mixins. Permissions are strictly enforced on backend querysets and views, never merely by hiding UI buttons.
- **Session & Header Hardening**: HTTPOnly cookies, `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, and conditional production SSL/HSTS flags.

### 3. Customer Registry & Cross-Tenant Data Isolation (`customers/`)
- **Multi-Criteria Search & Filtering**: Multi-field query search (name, company, email, phone, tax ID, city) combined with status and geographical filters.
- **Reactive HTMX Table**: Live search and status filtering without full page reloads.
- **Pagination Query Preservation**: Retains active search filters across paginated navigation links.
- **IDOR Defense & Tenant Scoping**: Reusable `scope_queryset_for_user(qs, user, customer_lookup)` function ensuring customer accounts can never query other customers' records.

### 4. Role-Aware Executive Dashboard & Customer Billing Portal (`config/views.py`)
- **Executive View (Admin & Staff)**: Displays top-line SaaS metrics including total customer count, active subscriptions, MRR/ARR estimates, outstanding payments, and overdue invoice alerts alongside revenue momentum charts.
- **Customer Portal View (Customer)**: Personalized self-service portal displaying active subscriptions, renewal dates, outstanding balances, and recent billing statements.
- **Defensive Lazy Evaluation**: Safely queries cross-app models with graceful empty-state fallbacks and warning logs if optional domain tables are unpopulated.

### 5. Multi-Tab Customer Profile Integration
- **Subscriptions Tab**: Displays active and past agreements with renewal periods and status indicators.
- **Invoices Tab**: Displays historical invoices, due dates, statuses, and total amounts.
- **Payments Tab**: Displays immutable transaction receipts with reference numbers, payment methods, dates, and amounts.

---

## 🔐 Permission & Authorization Matrix

| Endpoint / Capability | Anonymous | Customer | Staff | Admin |
| :--- | :---: | :---: | :---: | :---: |
| `/` (Dashboard / Portal) | 302 (Login) | 200 (Customer Portal) | 200 (Executive View) | 200 (Executive View) |
| `/accounts/login/` | 200 | 302 (Dashboard) | 302 (Dashboard) | 302 (Dashboard) |
| `/accounts/register/` | 200 | 302 (Dashboard) | 302 (Dashboard) | 302 (Dashboard) |
| `/accounts/profile/` | 302 (Login) | 200 | 200 | 200 |
| `/accounts/staff/create/` | 302 (Login) | **403 Forbidden** | **403 Forbidden** | 200 |
| `/accounts/users/` | 302 (Login) | **403 Forbidden** | **403 Forbidden** | 200 |
| `/customers/` | 302 (Login) | 200 (Own Record Only) | 200 (Full Directory) | 200 (Full Directory) |
| `/customers/create/` | 302 (Login) | **403 Forbidden** | 200 | 200 |
| `/customers/<pk>/` | 302 (Login) | 200 (Own) / **404 (Other)** | 200 (Any) | 200 (Any) |
| `/customers/<pk>/status/` | 302 (Login) | **403 Forbidden** | 200 | 200 |
| `/billing/` (Invoices) | 302 (Login) | 200 (Own Invoices) | 200 (All Invoices) | 200 (All Invoices) |
| `/payments/` | 302 (Login) | 200 (Own Payments) | 200 (All Payments) | 200 (All Payments) |
| `/payments/create/` | 302 (Login) | **403 Forbidden** | 200 | 200 |
| `/analytics/` | 302 (Login) | **403 Forbidden** | 200 | 200 |

---

## 🏁 Quickstart Guide

### 1. Prerequisites
- Python 3.11 or higher
- Git

### 2. Setup Virtual Environment
```powershell
# Clone the repository
git clone https://github.com/georgybenoy/subscript.git
cd subscript

# Create and activate virtual environment
python -m venv venv
.\venv\Scripts\Activate.ps1
```

### 3. Install Dependencies
```powershell
pip install -r requirements.txt
```

### 4. Configure Environment Secrets
Create a local `.env` file (gitignored) based on `.env.example`:
```powershell
Copy-Item .env.example .env
```
Ensure your `.env` contains:
```env
SECRET_KEY=subscript-dev-secret-key-change-in-production
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1,testserver
EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend
DEFAULT_FROM_EMAIL=Subscript Billing <billing@subscript.local>
```

### 5. Apply Migrations & Create Superuser
```powershell
python manage.py migrate
python manage.py createsuperuser
```

### 6. Run the Development Server
```powershell
python manage.py runserver
```
Visit `http://127.0.0.1:8000/` in your browser.

---

## 🧪 Running Automated Tests

Run the full automated test suite (all 58 tests passing):
```powershell
python manage.py test tests.test_phase1 tests.test_phase4 tests.test_permissions_matrix accounts customers
```

Run specific test modules:
```powershell
# RBAC Permissions Matrix & IDOR Audit
python manage.py test tests.test_permissions_matrix

# Authentication, Password Complexity & Rate-Limiting
python manage.py test accounts

# Customer CRM, Search Filters & Scoping
python manage.py test customers

# Phase 1 & 4 Foundations & Security Hardening
python manage.py test tests.test_phase1 tests.test_phase4
```

Run Django system and deployment checks:
```powershell
python manage.py check
python manage.py check --deploy
```

---

## 📚 Technical Documentation & Integration Contracts

Detailed architectural specifications and cross-team contracts are located in the `docs/` directory:
- [**Database Schema Contract (`docs/DATABASE.md`)**](docs/DATABASE.md): Specifications for all 11 shared models, `DecimalField(12, 2)` monetary requirements, string FK conventions, and ASCII domain relationships.
- [**Architecture & Developer Guide (`docs/ARCHITECTURE.md`)**](docs/ARCHITECTURE.md): Service layer design patterns, complete 80-route URL resolution map, RBAC matrix, and `scope_queryset_for_user` integration examples.
- [**Team Workflow & Git Protocols (`docs/WORKFLOW.md`)**](docs/WORKFLOW.md): Branching conventions, semantic commit standards, migration order rules, and pull request procedures.
