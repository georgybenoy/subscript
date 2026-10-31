# Subscript

> **Subscription Management and Recurring Billing Platform**  
> *Developed for the Make-a-ton Hackathon*

Subscript is a robust, modular Django monolith platform designed for modern subscription lifecycle management, recurring customer invoicing, and financial reporting.

---

## 🛠️ Tech Stack & Constraints

- **Backend**: Python 3.11+, Django 5.2, Django ORM, SQLite
- **Frontend**: Django Templates, Bootstrap 5, HTMX, Chart.js
- **Reporting & Media**: ReportLab (PDF invoicing), Pillow
- **Configuration**: python-dotenv (`.env`)
- **Strict Constraints**: No React, FastAPI, Redis, Celery, Docker, or microservices.

---

## 🏛️ Monolith Architecture & Team Ownership

Subscript is structured as a modular monolith where each app represents an isolated domain communicating via thin service layers (`services.py`):

| App / Domain | Owning Member | Responsibilities |
| :--- | :--- | :--- |
| `config/` | **Backend Lead** | Root URL routing, centralized settings, security middleware, logging. |
| `accounts/` | **Backend Lead** | Custom email-based User model, RBAC authorization, password reset, login rate-limiting. |
| `customers/` | **Backend Lead** | Customer directory, business profiles, IDOR protection, HTMX live search, queryset scoping. |
| `products/` | **Member 3** | Product catalog, tiered add-ons (`ProductVariant`), recurring billing plans (`Plan`). |
| `subscriptions/`| **Member 3** | Active subscriptions, billing cycles, plan attachments, line items. |
| `discounts/` | **Member 3** | Promotional coupons, percentage & fixed discounts, redemption limits. |
| `billing/` | **Member 4** | Invoices, statement items, PDF exports via ReportLab, tax calculations. |
| `payments/` | **Member 4** | Payment transactions, payment gateway hooks, status tracking. |
| `analytics/` | **Member 4** | MRR, ARR, churn rate, cohort metrics, visual analytics (Chart.js). |
| `templates/` & `static/` | **Member 2** | UI layouts, Bootstrap 5 styling, HTMX reactive widgets, brand assets. |

---

## 🚀 Key Features Implemented (Phases 1–4)

1. **Custom Authentication & Identity**:
   - Email is the primary identifier (`USERNAME_FIELD = "email"`).
   - Strict password complexity policy (min length 9, uppercase, lowercase, special character).
   - Rate-limiting: 5 consecutive failed attempts lock the account/IP pair for 5 minutes.
2. **Role-Based Access Control (RBAC)**:
   - Three distinct roles: `ADMIN`, `STAFF`, and `CUSTOMER`.
   - Single-source-of-truth decorators (`@admin_required`, `@staff_or_admin_required`, `@customer_required`) and CBV mixins.
   - Inactive accounts automatically treated as unauthenticated.
3. **Customer Management & IDOR Defense**:
   - Full CRUD with multi-criteria search (name, company, email, phone, city, tax ID) and filters.
   - Reactive HTMX table filtering without page reloads.
   - Filter-retaining pagination controls.
   - Backend object-level access control preventing cross-customer data access.
   - Universal helper `scope_queryset_for_user(qs, user, customer_lookup)` for teammate apps.
4. **Self-Service Password Reset & Change**:
   - Complete workflow: `password_reset`, `password_reset_done`, `password_reset_confirm`, `password_reset_complete`.
   - Authenticated password change with active session invalidation protection.
   - Zero user enumeration (identical response whether email exists or not).
5. **Security Hardening**:
   - `SESSION_COOKIE_HTTPONLY`, `CSRF_COOKIE_HTTPONLY`, `SECURE_CONTENT_TYPE_NOSNIFF`, `X_FRAME_OPTIONS = "DENY"`.
   - Automatic CSRF injection into HTMX requests via `hx-headers`.
   - Production SSL/HSTS configuration conditionally activated when `DEBUG=False`.
   - Custom friendly error templates: `403.html`, `404.html`, `500.html`.

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

Run the complete test suite (all 43 tests passing):
```powershell
python manage.py test
```

Run tests for specific applications:
```powershell
python manage.py test accounts
python manage.py test customers
python manage.py test tests
```

Run system security & deployment checks:
```powershell
python manage.py check
python manage.py check --deploy
```

---

## 📚 Technical Documentation

Comprehensive architectural guidelines and team contracts are available in the `docs/` folder:
- [**Database Schema Contract (`docs/DATABASE.md`)**](docs/DATABASE.md): Specifications for all 11 shared platform models, `DecimalField(12, 2)` monetary rules, string foreign key conventions, and ASCII relationship diagram.
- [**Architecture & Developer Guide (`docs/ARCHITECTURE.md`)**](docs/ARCHITECTURE.md): Cross-app service layer rules, URL routing tables, permission matrix, and the `scope_queryset_for_user` integration guide.
- [**Team Workflow & Git Protocols (`docs/WORKFLOW.md`)**](docs/WORKFLOW.md): Branching model, semantic commit standards, PR merge order, and migration safety rules.
