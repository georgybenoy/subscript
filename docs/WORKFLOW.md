# Subscript Team Collaboration & Git Workflow

This document establishes the official collaboration rules, branching model, pull-request ordering, and migration safety protocols for the Make-a-ton hackathon.

---

## 1. Branching Strategy

| Branch | Description | Policy |
| :--- | :--- | :--- |
| `main` | Production-ready baseline | **Protected**. Never push directly. Merges only via reviewed Pull Requests. |
| `feature/accounts-customers` | Auth, Identity, Customer registry, Core settings | Owned by **Backend Lead**. First branch in PR merge sequence. |
| `feature/ui-templates` | Bootstrap 5 layout, HTMX interactions, visual styling | Owned by **Member 2**. |
| `feature/products-subscriptions`| Catalog, pricing plans, subscriptions, coupons | Owned by **Member 3**. |
| `feature/billing-payments-analytics`| Invoices, ReportLab PDF export, payment records, analytics | Owned by **Member 4**. |

---

## 2. PR & Merge Sequence

To prevent merge and migration dependency cycles, integration into `main` follows this strict order:
1. **Merge `feature/accounts-customers` first**:
   - Establishes `AUTH_USER_MODEL`, `accounts.User`, `customers.Customer`, permissions, and project foundation.
2. **Rebase feature branches on latest `main`**:
   - `git fetch origin`
   - `git rebase origin/main`
3. **Merge `feature/products-subscriptions`**:
   - Introduces products, plans, and subscriptions depending on `customers.Customer`.
4. **Merge `feature/billing-payments-analytics`**:
   - Introduces invoices and payments depending on `customers.Customer` and `subscriptions.Subscription`.
5. **Merge `feature/ui-templates`**:
   - Polishes all templates, replaces bare functional placeholders, and injects final branding.

---

## 3. Commit Message Conventions

Commit messages must use standard semantic prefixes:
- `feat:` A new feature or capability (e.g. `feat: add customer filtering`).
- `fix:` A bug fix or access patch (e.g. `fix: prevent IDOR on customer update`).
- `docs:` Documentation updates only (e.g. `docs: add database schema diagram`).
- `test:` Adding or updating unit tests (e.g. `test: verify login rate limiting`).
- `chore:` Configuration, environment, or dependency adjustments (e.g. `chore: update requirements`).

---

## 4. Pull-Before-Push & Conflict Resolution

1. **Pull before push**:
   - Always run `git pull --rebase origin <branch>` before pushing your branch to remote.
2. **Never push broken code without documenting the issue**:
   - All tests (`python manage.py test`) and system checks (`python manage.py check`) MUST pass before pushing.
   - If a blocker arises, document the issue clearly in commit notes or team chat before pushing.

---

## 5. Database Migration Rules

1. **App-Specific Migrations Only**:
   - Run `python manage.py makemigrations <your_app>`. Never run `makemigrations` without an app name.
2. **Never Edit Other Members' Migrations**:
   - Do NOT edit, delete, or squash migration files created by teammates.
3. **Conflict Resolution**:
   - If two branches create competing migrations in the same app, resolve via:
     `python manage.py makemigrations --merge <app_name>`
   - Coordinate with the app owner before committing the merge migration.

---

## 6. File & Directory Ownership Matrix

| Directory / Files | Primary Owner | Read / Write Rules for Others |
| :--- | :--- | :--- |
| `config/` | Backend Lead | Shared configuration. Coordinate before changing middleware or base settings. |
| `accounts/` | Backend Lead | Read-only. Auth and permissions logic. |
| `customers/` | Backend Lead | Read-only. Call via `customers.services`. |
| `templates/accounts/` | Member 2 | Functional placeholders created by Lead; Member 2 owns final markup & styling. |
| `templates/customers/` | Member 2 | Functional placeholders created by Lead; Member 2 owns final markup & styling. |
| `templates/base.html` | Member 2 | Core layout. Contains `{% block content %}` and HTMX CSRF headers. |
| `products/` | Member 3 | Member 3 exclusive. |
| `subscriptions/` | Member 3 | Member 3 exclusive. |
| `discounts/` | Member 3 | Member 3 exclusive. |
| `billing/` | Member 4 | Member 4 exclusive. |
| `payments/` | Member 4 | Member 4 exclusive. |
| `analytics/` | Member 4 | Member 4 exclusive. |
| `docs/` | Backend Lead | Authoritative project documentation & contracts. |
