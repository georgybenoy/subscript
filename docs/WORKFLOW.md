# Subscript Multi-Member Collaboration Workflow

This document records the ownership agreements, placeholder management, and branch workflow for the **Subscript** modular Django monolith platform.

---

## 1. Domain & Codebase Ownership

| Member | Domain & Modules | Allowed Actions by Other Members |
| :--- | :--- | :--- |
| **Backend Lead (You)** | `config/`, `accounts/`, `customers/`, `docs/`, shared settings, core permissions | Read-only. Other members must not alter models or auth rules. |
| **Member 2** | `templates/`, `static/`, UI integration, styling | Other members create only bare-bones placeholder templates required to boot & test functional views. Marked with `<!-- PLACEHOLDER - owned by Member 2 -->`. |
| **Member 3** | `products/`, `subscriptions/`, `discounts/` | Lead created bare skeletons (`apps.py`, empty `models.py`, `urls.py`, `views.py`). Member 3 implements plans, catalog, subscriptions, coupons. |
| **Member 4** | `billing/`, `payments/`, `analytics/` | Lead created bare skeletons. Member 4 implements invoice calculations, payment integrations, and reporting. |

---

## 2. Shared Contracts & Rules

1. **Money Calculations**:
   - `models.DecimalField(max_digits=12, decimal_places=2)` for all monetary values.
2. **Cross-App Foreign Keys**:
   - String references only (e.g. `"customers.Customer"`, `settings.AUTH_USER_MODEL`). Never direct model imports between apps.
3. **Backend-Enforced Authorization**:
   - Never rely on hiding UI buttons. Enforce role checks in `accounts/permissions.py` (`@admin_required`, `@staff_or_admin_required`, `@customer_required`).
4. **Service Layer Isolation**:
   - Keep business logic in `services.py` inside each app.
   - Views handle only HTTP parsing, form submission, and redirection.
5. **Secrets & Environment**:
   - Sensitive credentials loaded via `.env` (gitignored).
   - `.env.example` committed to git.

---

## 3. Template Placeholder Notice (Member 2 Ownership)

The following templates were provided as minimal functional placeholders with Bootstrap 5 CDN and standard block hooks to enable automated testing and user auth:
- `templates/base.html`
- `templates/dashboard.html`
- `templates/accounts/login.html`
- `templates/accounts/register.html`
- `templates/accounts/profile.html`
- `templates/accounts/staff_create.html`
- `templates/accounts/user_list.html`

Member 2 is responsible for final UI styling, HTMX interactive widgets, custom brand assets, and mobile responsive polishing.
