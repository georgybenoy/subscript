"""
Financial Analytics and Intelligence Services.

Specifications:
- Strict database aggregation only (no iterating model instances in Python)
- MRR calculated by summing active subscription items and normalizing by frequency:
    * DAILY: * (365 / 12)
    * WEEKLY: * (52 / 12)
    * MONTHLY: * 1
    * YEARLY / ANNUAL: / 12
    * Gross list value (gross of discounts)
- ARR: exactly MRR * 12
- Collected revenue: sum of Payment.amount in period
- Outstanding balance: sum of (total_amount - paid_amount) over CONFIRMED invoices
- Overdue invoice count: reused from Invoice.objects.overdue().count()
- Chart trends: database-grouped intervals formatted for Chart.js
- All money returned as 2-decimal strings
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, Optional

from django.db import models
from django.db.models import Count, DecimalField, F, Sum, Value
from django.db.models.functions import Coalesce, TruncDay, TruncMonth, TruncWeek
from django.utils import timezone

from billing.integrations import Subscription, SubscriptionItem
from billing.models import Invoice, InvoiceStatus
from billing.money import quantize_money
from payments.models import Payment


def _parse_date(val: Optional[Any]) -> Optional[date]:
    if val is None or val == "":
        return None
    if isinstance(val, date):
        return val
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, str):
        try:
            return date.fromisoformat(val.strip())
        except ValueError:
            return None
    return None


def calculate_mrr_and_arr() -> tuple[Decimal, Decimal]:
    """
    Computes MRR and ARR using database-level GROUP BY aggregation.
    Excludes paused, quotation, closed, or draft subscriptions.
    Normalizes frequencies to monthly run rate:
    - DAILY: * 365 / 12
    - WEEKLY: * 52 / 12
    - MONTHLY: * 1
    - YEARLY / ANNUAL: / 12
    """
    freq_totals: Dict[str, Decimal] = {
        "DAILY": Decimal("0.00"),
        "WEEKLY": Decimal("0.00"),
        "MONTHLY": Decimal("0.00"),
        "YEARLY": Decimal("0.00"),
    }

    # 1. Aggregate from SubscriptionItem lines on ACTIVE subscriptions
    item_aggregates = (
        SubscriptionItem.objects.filter(subscription__status="ACTIVE")
        .values("subscription__plan__billing_frequency")
        .annotate(
            total=Coalesce(
                Sum(F("quantity") * F("unit_price")),
                Value(Decimal("0.00")),
                output_field=DecimalField(max_digits=12, decimal_places=2),
            )
        )
    )

    for row in item_aggregates:
        raw_freq = row.get("subscription__plan__billing_frequency") or "MONTHLY"
        freq = str(raw_freq).strip().upper()
        if freq in ["ANNUAL", "ANNUALLY", "YEAR"]:
            freq = "YEARLY"
        elif freq not in freq_totals:
            freq = "MONTHLY"
        freq_totals[freq] += quantize_money(row["total"] or Decimal("0.00"))

    # 2. For ACTIVE subscriptions without explicit SubscriptionItem lines, include Plan price
    subs_with_items = SubscriptionItem.objects.filter(
        subscription__status="ACTIVE"
    ).values_list("subscription_id", flat=True)

    plan_aggregates = (
        Subscription.objects.filter(status="ACTIVE")
        .exclude(id__in=subs_with_items)
        .values("plan__billing_frequency")
        .annotate(
            total=Coalesce(
                Sum("plan__price"),
                Value(Decimal("0.00")),
                output_field=DecimalField(max_digits=12, decimal_places=2),
            )
        )
    )

    for row in plan_aggregates:
        raw_freq = row.get("plan__billing_frequency") or "MONTHLY"
        freq = str(raw_freq).strip().upper()
        if freq in ["ANNUAL", "ANNUALLY", "YEAR"]:
            freq = "YEARLY"
        elif freq not in freq_totals:
            freq = "MONTHLY"
        freq_totals[freq] += quantize_money(row["total"] or Decimal("0.00"))

    # 3. Frequency normalization multipliers
    daily_mrr = freq_totals["DAILY"] * Decimal("365") / Decimal("12")
    weekly_mrr = freq_totals["WEEKLY"] * Decimal("52") / Decimal("12")
    monthly_mrr = freq_totals["MONTHLY"]
    yearly_mrr = freq_totals["YEARLY"] / Decimal("12")

    mrr = quantize_money(daily_mrr + weekly_mrr + monthly_mrr + yearly_mrr)
    arr = quantize_money(mrr * Decimal("12"))
    return mrr, arr


def get_dashboard_context(
    date_from: Optional[Any] = None,
    date_to: Optional[Any] = None,
    group_by: str = "month",
) -> Dict[str, Any]:
    """
    Assembles comprehensive financial intelligence KPIs and chart data.
    All database operations use strict aggregations.
    All monetary outputs are formatted as 2-decimal strings.
    """
    d_from = _parse_date(date_from)
    d_to = _parse_date(date_to)

    # 1. Active Subscriptions Count
    active_subscriptions = Subscription.objects.filter(status="ACTIVE").count()

    # 2. MRR & ARR Run Rates
    mrr_val, arr_val = calculate_mrr_and_arr()

    # 3. Collected Revenue (Sum of settled payments)
    payments_qs = Payment.objects.all()
    if d_from:
        payments_qs = payments_qs.filter(payment_date__gte=d_from)
    if d_to:
        payments_qs = payments_qs.filter(payment_date__lte=d_to)

    collected_rev_val = payments_qs.aggregate(
        total=Coalesce(
            Sum("amount"),
            Value(Decimal("0.00")),
            output_field=DecimalField(max_digits=12, decimal_places=2),
        )
    )["total"]
    collected_revenue = str(quantize_money(collected_rev_val))

    # 4. Outstanding Balance over CONFIRMED invoices
    confirmed_invoices = Invoice.objects.filter(status=InvoiceStatus.CONFIRMED).with_outstanding()
    if d_from:
        confirmed_invoices = confirmed_invoices.filter(issue_date__gte=d_from)
    if d_to:
        confirmed_invoices = confirmed_invoices.filter(issue_date__lte=d_to)

    outstanding_val = confirmed_invoices.aggregate(
        total=Coalesce(
            Sum("outstanding"),
            Value(Decimal("0.00")),
            output_field=DecimalField(max_digits=12, decimal_places=2),
        )
    )["total"]
    outstanding_balance = str(quantize_money(outstanding_val))

    # 5. Overdue Invoices Count (reusing Invoice.objects.overdue())
    overdue_qs = Invoice.objects.overdue()
    if d_from:
        overdue_qs = overdue_qs.filter(issue_date__gte=d_from)
    if d_to:
        overdue_qs = overdue_qs.filter(issue_date__lte=d_to)
    overdue_invoice_count = overdue_qs.count()

    # 6. Chart Visualizations
    trunc_map = {
        "day": TruncDay,
        "week": TruncWeek,
        "month": TruncMonth,
    }
    trunc_fn = trunc_map.get(group_by.lower(), TruncMonth)

    # A. Collection Trend
    coll_trend = (
        payments_qs.annotate(period=trunc_fn("payment_date"))
        .values("period")
        .annotate(
            total=Coalesce(
                Sum("amount"),
                Value(Decimal("0.00")),
                output_field=DecimalField(max_digits=12, decimal_places=2),
            )
        )
        .order_by("period")
    )
    coll_labels = [
        row["period"].strftime("%Y-%m") if hasattr(row["period"], "strftime") else str(row["period"])
        for row in coll_trend
        if row["period"]
    ]
    coll_data = [str(quantize_money(row["total"])) for row in coll_trend if row["period"]]

    collection_chart = {
        "labels": coll_labels,
        "data": coll_data,
    }

    # B. Revenue Chart (collected revenue trend series)
    revenue_chart = {
        "labels": coll_labels,
        "data": coll_data,
    }

    # C. Invoiced Chart (billed invoices by period)
    invoices_qs = Invoice.objects.exclude(status=InvoiceStatus.CANCELLED)
    if d_from:
        invoices_qs = invoices_qs.filter(issue_date__gte=d_from)
    if d_to:
        invoices_qs = invoices_qs.filter(issue_date__lte=d_to)

    inv_trend = (
        invoices_qs.annotate(period=trunc_fn("issue_date"))
        .values("period")
        .annotate(
            total=Coalesce(
                Sum("total_amount"),
                Value(Decimal("0.00")),
                output_field=DecimalField(max_digits=12, decimal_places=2),
            )
        )
        .order_by("period")
    )
    inv_labels = [
        row["period"].strftime("%Y-%m") if hasattr(row["period"], "strftime") else str(row["period"])
        for row in inv_trend
        if row["period"]
    ]
    inv_data = [str(quantize_money(row["total"])) for row in inv_trend if row["period"]]

    invoiced_chart = {
        "labels": inv_labels,
        "data": inv_data,
    }

    # D. Subscription Growth Chart (new subscriptions by period)
    sub_qs = Subscription.objects.all()
    if d_from:
        sub_qs = sub_qs.filter(start_date__gte=d_from)
    if d_to:
        sub_qs = sub_qs.filter(start_date__lte=d_to)

    sub_trend = (
        sub_qs.annotate(period=trunc_fn("start_date"))
        .values("period")
        .annotate(count=Count("id"))
        .order_by("period")
    )
    sub_labels = [
        row["period"].strftime("%Y-%m") if hasattr(row["period"], "strftime") else str(row["period"])
        for row in sub_trend
        if row["period"]
    ]
    sub_data = [row["count"] for row in sub_trend if row["period"]]

    subscription_chart = {
        "labels": sub_labels,
        "data": sub_data,
    }

    return {
        "active_subscriptions": active_subscriptions,
        "mrr": str(mrr_val),
        "arr": str(arr_val),
        "collected_revenue": collected_revenue,
        "outstanding_balance": outstanding_balance,
        "overdue_invoice_count": overdue_invoice_count,
        "revenue_chart": revenue_chart,
        "subscription_chart": subscription_chart,
        "collection_chart": collection_chart,
        "invoiced_chart": invoiced_chart,
    }
