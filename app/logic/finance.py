"""Finance rules: approval routing, anomaly flags, ageing and cash forecast."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Optional

from ._util import DateLike, to_date

DEFAULT_LIMITS = {"finance_max": 500_000.0}
AGEING_LABELS = ["0-30", "31-60", "61-90", "90+"]
OPEN_STATUSES = {"sent", "overdue", "part_paid", "unpaid", "issued"}


def next_approver(amount: float, limits: Optional[dict[str, float]] = None) -> str:
    """'finance' when amount <= finance_max, otherwise 'md'."""
    limits = {**DEFAULT_LIMITS, **(limits or {})}
    return "finance" if float(amount) <= float(limits["finance_max"]) else "md"


def expense_flags(expense: dict[str, Any], history: list[dict[str, Any]]) -> list[str]:
    """Anomaly flags for a new expense.

    history: existing expenses (the expense itself must not be in it).
    - 'possible duplicate': same vendor + amount + date as an existing record
    - 'unusually high': amount > 3x the average of the same category (needs >= 1 prior)
    """
    flags: list[str] = []
    vendor = (expense.get("vendor") or "").strip().lower()
    amount = float(expense.get("amount") or 0)
    day = to_date(expense.get("date"))
    for other in history:
        if other.get("id") is not None and other.get("id") == expense.get("id"):
            continue
        if (
            (other.get("vendor") or "").strip().lower() == vendor
            and float(other.get("amount") or 0) == amount
            and to_date(other.get("date")) == day
        ):
            flags.append("possible duplicate")
            break

    same_cat = [
        float(o.get("amount") or 0)
        for o in history
        if o.get("category") == expense.get("category")
        and not (o.get("id") is not None and o.get("id") == expense.get("id"))
    ]
    if same_cat:
        average = sum(same_cat) / len(same_cat)
        if average > 0 and amount > 3 * average:
            flags.append("unusually high")
    return flags


def invoice_age_days(invoice: dict[str, Any], today: date) -> int:
    """Age of an invoice in days since its issue date."""
    issued = to_date(invoice.get("issue_date"))
    return (today - issued).days if issued else 0


def is_open(invoice: dict[str, Any]) -> bool:
    return invoice.get("status") not in ("paid", "cancelled", "draft")


def outstanding_amount(invoice: dict[str, Any]) -> float:
    return max(0.0, float(invoice.get("amount") or 0) - float(invoice.get("paid_amount") or 0))


def ageing_buckets(invoices: list[dict[str, Any]], today: date) -> dict[str, float]:
    """Outstanding amount per age bucket, age counted from the issue date.

    Paid, cancelled and draft invoices are ignored. Returns all four buckets.
    """
    buckets = {label: 0.0 for label in AGEING_LABELS}
    for inv in invoices:
        if not is_open(inv):
            continue
        age = invoice_age_days(inv, today)
        amt = outstanding_amount(inv)
        if age <= 30:
            buckets["0-30"] += amt
        elif age <= 60:
            buckets["31-60"] += amt
        elif age <= 90:
            buckets["61-90"] += amt
        else:
            buckets["90+"] += amt
    return {k: round(v, 2) for k, v in buckets.items()}


def invoices_older_than(invoices: list[dict[str, Any]], today: date, days: int) -> list[dict[str, Any]]:
    """Open invoices strictly older than `days` days (by issue date), oldest first."""
    rows = [i for i in invoices if is_open(i) and invoice_age_days(i, today) > days]
    return sorted(rows, key=lambda i: to_date(i.get("issue_date")))


def expected_receipt_date(
    invoice: dict[str, Any], today: date, typical_days: int = 90
) -> date:
    """When we realistically expect the money.

    Clients in this sector pay 60-120 days after issue, so the expected date is
    issue_date + typical_days (clamped 60-120), never earlier than the due date.
    An invoice whose expected date has already passed is assumed to land in two weeks.
    """
    typical = min(120, max(60, int(typical_days)))
    issued = to_date(invoice.get("issue_date")) or today
    due = to_date(invoice.get("due_date")) or issued
    expected = max(issued + timedelta(days=typical), due)
    if expected < today:
        expected = today + timedelta(days=14)
    return expected


def _week_index(day: date, start: date, weeks: int) -> Optional[int]:
    idx = (day - start).days // 7
    return idx if 0 <= idx < weeks else None


def cash_forecast(
    invoices: list[dict[str, Any]],
    payables: list[dict[str, Any]],
    payroll: float,
    weeks: int,
    today: date,
    opening_cash: float = 0.0,
    typical_days: int = 90,
    payroll_day: int = 25,
) -> list[dict[str, Any]]:
    """Weekly cash projection.

    payroll: monthly payroll amount, charged in the week containing the `payroll_day`
    of each month. Overdue payables fall in week 0.
    """
    weeks = max(1, int(weeks))
    rows = [
        {"week_start": (today + timedelta(days=7 * i)).isoformat(), "receipts": 0.0,
         "payables": 0.0, "payroll": 0.0}
        for i in range(weeks)
    ]
    for inv in invoices:
        if not is_open(inv):
            continue
        idx = _week_index(expected_receipt_date(inv, today, typical_days), today, weeks)
        if idx is not None:
            rows[idx]["receipts"] += outstanding_amount(inv)
    for pay in payables:
        if pay.get("status") == "paid":
            continue
        due = to_date(pay.get("due_date")) or today
        idx = _week_index(max(due, today), today, weeks)
        if idx is not None:
            rows[idx]["payables"] += float(pay.get("amount") or 0)
    if payroll:
        for i in range(weeks * 7):
            d = today + timedelta(days=i)
            if d.day == payroll_day:
                idx = _week_index(d, today, weeks)
                if idx is not None:
                    rows[idx]["payroll"] += float(payroll)

    cumulative = float(opening_cash)
    for row in rows:
        row["net"] = round(row["receipts"] - row["payables"] - row["payroll"], 2)
        cumulative += row["net"]
        row["cumulative"] = round(cumulative, 2)
        for key in ("receipts", "payables", "payroll"):
            row[key] = round(row[key], 2)
    return rows


def vat_amount(net: float, rate: float = 0.075) -> float:
    """VAT as a tracked figure only (7.5%). Not tax advice."""
    return round(net * rate, 2)
