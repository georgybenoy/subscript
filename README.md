# Subscript

> **Subscription Management and Recurring Billing Platform**  
> *Developed for the Make-a-ton Hackathon*

Subscript is a high-performance, modular Django monolith platform designed for full-lifecycle subscription management, recurring billing, customer registries, and SaaS financial analytics.

---

## 🛠️ Tech Stack & Architecture Constraints

- **Backend Framework**: Python 3.11+, Django 5.2, Django ORM, SQLite
- **Frontend & Interaction**: Django Templates, Bootstrap 5, HTMX, Chart.js
- **Reporting & Statements**: ReportLab (PDF invoicing engine), Pillow
- **Environment & Secrets**: python-dotenv (`.env` configuration)
- **Architectural Rules**: Strict modular monolith. **Forbidden**: React, FastAPI, Redis, Celery, Docker, microservices. All monetary fields enforce `DecimalField(max_digits=12, decimal_places=2)`.

---

## 🏛️ Domain Architecture & Module Ownership

Subscript is architected as an interconnected modular monolith where domain boundaries communicate via explicit service layers (`services.py`):

| App / Domain | Owning Member | Responsibilities |
| :--- | :--- | :--- |
| `config/` | **Lead Backend Engineer** | Root URL routing, centralized settings, security middleware, environment config, dashboard view. |
| `accounts/` | **Lead Backend Engineer** | Custom email-based User model, RBAC authorization, password reset workflows, brute-force throttling. |
| `customers/` | **Lead Backend Engineer** | Customer registry, business profiles, IDOR prevention, HTMX live search, tenant scoping helpers. |
| `docs/` & `tests/` | **Lead Backend Engineer** | Database contract (`DATABASE.md`), Architecture (`ARCHITECTURE.md`), Permission matrix tests. |
| `products/` | Member 3 | Product catalog, tiered SKUs (`ProductVariant`), recurring billing plans (`Plan`). |
| `subscriptions/`| Member 3 | Subscription lifecycle, billing intervals, plan attachments, line items. |
| `discounts/` | Member 3 | Promotional coupons, percentage & fixed discounts, redemption rules. |
| `billing/` | Member 4 | Invoices (`Invoice`), statement items, ReportLab PDF statement generation. |
| `payments/` | Member 4 | Transaction ledger, payment recording, settlement status. |
| `analytics/` | Member 4 | SaaS metrics (MRR, ARR, overdue balance, collections), Chart.js data endpoints. |
| `templates/` & `static/` | Member 2 | Bootstrap 5 theme, HTMX reactive components, dashboard cards, custom CSS. |

---

## 👤 My Contributions (Lead Backend Engineer)

As the **Lead Backend Engineer**, I was responsible for designing, implementing, and securing the foundation, identity, customer lifecycle, cross-app integration, and RBAC governance of the Subscript platform across all 5 project phases:

### 1. Platform Foundation & Database Contracts (Phase 1)
- Initialized repository architecture, virtual environment specifications, and strict `.gitignore` / `.env.example` configurations.
- Engineered single-source settings in `config/settings.py` (Asia/Kolkata timezone, SQLite, console email backend, authentication redirects).
- Authored [**`docs/DATABASE.md`**](docs/DATABASE.md): Designed technical specifications for all 11 cross-team models, strict `DecimalField(12, 2)` monetary rules, string-based FK references, and ASCII relationship diagrams.
- Created bootable skeletons across all 8 monolith apps so teammates could work in parallel without merge blockers.

### 2. Authentication, Identity & RBAC Engine (Phase 2)
- Built custom user model `accounts.models.User` with case-insensitive lowercase email authentication (`USERNAME_FIELD = "email"`).
- Implemented `SubscriptPasswordValidator` enforcing strong password criteria ($\ge 9$ characters, uppercase, lowercase, special character).
- Developed login rate-limiting in cache: 5 consecutive failed attempts lock the email/IP pair for 5 minutes to eliminate credential stuffing.
- Established a single-source-of-truth RBAC framework in `accounts/permissions.py`:
  - Decorators: `@admin_required`, `@staff_or_admin_required`, `@customer_required`, `@role_required(*roles)`.
  - CBV Mixins: `AdminRequiredMixin`, `StaffOrAdminRequiredMixin`, `RoleRequiredMixin`.
  - Enforced server-side role assignment (role is strictly set on the backend, never accepted from user POST payloads).

### 3. Customer Registry, Live Filtering & IDOR Defense (Phase 3)
- Implemented complete customer management in `customers/`:
  - Model `Customer` capturing billing contact, address, tax ID/VAT, and one-to-one portal user link.
  - Multi-criteria search and filtering (by name, company, email, phone, tax ID, city, state, country) using optimized `Q` queries.
  - Reactive HTMX partial updates via `_customer_table.html` enabling instant live search without page reloads.
  - Custom filter-retaining pagination controls.
- Prevented Insecure Direct Object Reference (IDOR) vulnerabilities through `get_customer_for_user_or_404()`.
- Designed the universal tenant-scoping helper `scope_queryset_for_user(qs, user, customer_lookup)` utilized by teammate apps to isolate tenant data.

### 4. Self-Service Security & Production Hardening (Phase 4)
- Implemented full self-service password recovery workflows with Django auth views and console email backend:
  - `password_reset`, `password_reset_done`, `password_reset_confirm`, and `password_reset_complete`.
  - Zero user enumeration: identical response returned regardless of whether the email exists.
  - Authenticated password change (`password_change`, `password_change_done`) with active session invalidation protection.
- Hardened HTTP security headers: `SESSION_COOKIE_HTTPONLY`, `CSRF_COOKIE_HTTPONLY`, `SECURE_CONTENT_TYPE_NOSNIFF`, `X_FRAME_OPTIONS = "DENY"`.
- Created custom brand-aligned error templates: `403.html` (Forbidden), `404.html` (Not Found), `500.html` (Server Error).
- Authored [**`docs/ARCHITECTURE.md`**](docs/ARCHITECTURE.md) and [**`docs/WORKFLOW.md`**](docs/WORKFLOW.md).

### 5. Cross-Team Integration & RBAC Permission Audit (Phase 5)
- **Migration Conflict Resolution**:
  - Diagnosed and fixed broken migration dependencies in `billing/migrations/0001_initial.py` by adding `("products", "0001_initial")`, enabling clean fresh migrations across all apps.
- **Contract Verification & Teammate Gap Analysis**:
  - Audited all teammate models against `docs/DATABASE.md` and compiled an explicit mismatch report.
- **URL Routing Governance**:
  - Validated root route conventions and verified zero URL shadowing across 80 resolved endpoints, documented in `docs/ARCHITECTURE.md`.
- **Role-Aware Executive & Customer Portal Dashboard (`/`)**:
  - Engineered `config.views.dashboard_view` delivering executive financial KPIs (total customers, active subscriptions, MRR/ARR, overdue invoices) to Admin/Staff, and personalized portal summaries (my subscriptions, unpaid invoices, balance) to Customers.
- **Customer Detail Integration**:
  - Implemented safe lazy query helpers (`get_customer_subscriptions`, `get_customer_invoices`, `get_customer_payments`) evaluating into lists inside `try...except` blocks with logger warnings, ensuring unbuilt teammate models never crash customer detail views.
  - Integrated Payments tab in `templates/customers/customer_detail.html` displaying transaction receipts and status badges.
- **Automated RBAC Permission Matrix Test Suite (`tests/test_permissions_matrix.py`)**:
  - Engineered an automated permission test suite verifying:
    - Anonymous users $\rightarrow$ 302 redirect to login on protected routes, 200 on public auth endpoints.
    - Customer role $\rightarrow$ 403 Forbidden on administrative/staff endpoints; 200 on self-service portal.
    - Staff role $\rightarrow$ 200 on operational endpoints; 403 Forbidden on admin-only user management.
    - Admin role $\rightarrow$ 200 full platform access.
    - Cross-tenant IDOR protection $\rightarrow$ Customer A cannot access Customer B's records (404/403).

---

## 🚀 Quickstart Guide

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
ALLOWED_HOSTS=localhost,127.0.0.1
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

Run all test suites owned by the Lead Backend Engineer (**58 tests passing, 0 failures, 100% pass rate**):
```powershell
python manage.py test tests.test_phase1 tests.test_phase4 tests.test_permissions_matrix accounts customers
```

Run specific test modules:
```powershell
# Authentication & RBAC tests
python manage.py test accounts

# Customer CRUD & IDOR tests
python manage.py test customers

# Automated RBAC Permission Matrix audit
python manage.py test tests.test_permissions_matrix

# Foundation & security hardening tests
python manage.py test tests.test_phase1 tests.test_phase4
```

Run system security & deployment checks:
```powershell
python manage.py check
python manage.py check --deploy
```

---

## 🧭 Smoke Test & RBAC Verification Matrix

| Route | Namespace / Name | Anonymous | Customer | Staff | Admin |
| :--- | :--- | :---: | :---: | :---: | :---: |
| `/` | `dashboard` | **302** (Login) | **200** (Portal) | **200** (Executive) | **200** (Executive) |
| `/accounts/login/` | `accounts:login` | **200** (Public) | **302** (Dashboard) | **302** (Dashboard) | **302** (Dashboard) |
| `/accounts/register/` | `accounts:register` | **200** (Public) | **302** (Dashboard) | **302** (Dashboard) | **302** (Dashboard) |
| `/accounts/profile/` | `accounts:profile` | **302** (Login) | **200** | **200** | **200** |
| `/accounts/staff/create/` | `accounts:staff_create` | **302** (Login) | **403** (Forbidden) | **403** (Forbidden) | **200** |
| `/accounts/users/` | `accounts:user_list` | **302** (Login) | **403** (Forbidden) | **403** (Forbidden) | **200** |
| `/customers/` | `customers:list` | **302** (Login) | **200** (Own record) | **200** (Directory) | **200** (Directory) |
| `/customers/create/` | `customers:create` | **302** (Login) | **403** (Forbidden) | **200** | **200** |
| `/customers/<pk>/` | `customers:detail` | **302** (Login) | **200** (Own) / **404** (Other) | **200** | **200** |
| `/billing/` | `billing:invoice_list` | **302** (Login) | **200** (Own invoices) | **200** (All invoices) | **200** (All invoices) |
| `/payments/` | `payments:payment_list` | **302** (Login) | **200** (Own payments) | **200** (All payments) | **200** (All payments) |
| `/analytics/` | `analytics:dashboard` | **302** (Login) | **403** (Forbidden) | **200** | **200** |

---

## 📚 Technical Documentation

Comprehensive architectural guidelines and team contracts are maintained in `docs/`:
- [**Database Schema Contract (`docs/DATABASE.md`)**](docs/DATABASE.md): Specifications for all 11 models, `DecimalField(12, 2)` monetary rules, string foreign key conventions, and ASCII relationship diagram.
- [**Architecture & Developer Guide (`docs/ARCHITECTURE.md`)**](docs/ARCHITECTURE.md): Cross-app service layer rules, resolved 80-route URL routing table, permission matrix, and `scope_queryset_for_user` integration guide.
- [**Team Workflow & Git Protocols (`docs/WORKFLOW.md`)**](docs/WORKFLOW.md): Branching model, semantic commit standards, PR merge order, and migration safety rules.
