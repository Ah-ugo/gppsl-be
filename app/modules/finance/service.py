from typing import Any, Optional

from app.core.common import clean, new_id, today, utcnow_iso
from app.core.db import get_db
from app.core.settings_store import get_settings_doc
from app.logic import ageing_buckets, cash_forecast, expense_flags, next_approver
from app.logic.finance import invoice_age_days, is_open, outstanding_amount


async def create_expense(body: Any, user: dict[str, Any]) -> dict[str, Any]:
    db = get_db()
    cfg = await get_settings_doc()
    day = body.date or today().isoformat()
    amount_ngn = body.amount * (cfg["usd_rate"] if body.currency == "USD" else 1)
    exp = {
        "_id": new_id(), "requester": {"id": user["id"], "name": user["name"], "role": user["role"]},
        "project_id": body.project_id, "category": body.category, "amount": body.amount, "currency": body.currency,
        "amount_ngn": round(amount_ngn, 2), "usd_rate": cfg["usd_rate"] if body.currency == "USD" else None,
        "vendor": body.vendor.strip(), "date": day, "receipt_url": body.receipt_url, "notes": body.notes,
        "status": "pending", "required_approver": next_approver(amount_ngn, cfg["approval_limits"]),
        "approval_trail": [], "created_at": utcnow_iso(),
    }
    history = await db.expenses.find({}).to_list(20000)
    # compare in naira so USD and NGN items are comparable
    hist = [{**h, "amount": h.get("amount_ngn", h.get("amount"))} for h in history]
    exp["flags"] = expense_flags({**exp, "amount": amount_ngn}, hist)
    await db.expenses.insert_one(exp)
    return exp


async def decide(expense_id: str, user: dict[str, Any], approve: bool, comment: Optional[str]) -> dict[str, Any]:
    from fastapi import HTTPException

    db = get_db()
    exp = await db.expenses.find_one({"_id": expense_id})
    if not exp:
        raise HTTPException(404, "Expense not found")
    if exp["status"] != "pending":
        raise HTTPException(409, f"Expense is already {exp['status']}")
    if user["role"] != exp["required_approver"]:
        raise HTTPException(403, f"This expense must be decided by: {exp['required_approver'].upper()}")
    if exp["requester"]["id"] == user["id"]:
        raise HTTPException(403, "You cannot decide your own expense")
    status = "approved" if approve else "rejected"
    step = {"user_id": user["id"], "name": user["name"], "role": user["role"], "decision": status,
            "comment": comment, "timestamp": utcnow_iso()}
    await db.expenses.update_one({"_id": expense_id}, {"$set": {"status": status}, "$push": {"approval_trail": step}})
    return await db.expenses.find_one({"_id": expense_id})


def view(exp: dict[str, Any], project_names: Optional[dict[str, str]] = None) -> dict[str, Any]:
    out = clean(exp)
    if project_names is not None:
        out["project_name"] = project_names.get(exp.get("project_id") or "")
    return out


async def open_invoices() -> list[dict[str, Any]]:
    rows = await get_db().invoices.find({}).to_list(20000)
    return rows


async def ageing() -> dict[str, Any]:
    invoices = await open_invoices()
    return ageing_buckets(invoices, today())


async def receivables_total() -> float:
    return round(sum(outstanding_amount(i) for i in await open_invoices() if is_open(i)), 2)


async def payables_total() -> float:
    rows = await get_db().payables.find({"status": {"$ne": "paid"}}).to_list(20000)
    return round(sum(float(r.get("amount") or 0) for r in rows), 2)


async def cash_position() -> float:
    """Opening cash (settings) + paid invoices - paid payables - approved expenses."""
    db = get_db()
    cfg = await get_settings_doc()
    paid_in = sum(float(i.get("paid_amount") or 0) for i in await db.invoices.find({}).to_list(20000))
    paid_out = sum(float(p.get("amount") or 0) for p in await db.payables.find({"status": "paid"}).to_list(20000))
    spent = sum(float(e.get("amount_ngn") or 0) for e in await db.expenses.find({"status": "approved"}).to_list(20000))
    return round(float(cfg.get("opening_cash", 0)) + paid_in - paid_out - spent, 2)


async def forecast(weeks: int) -> list[dict[str, Any]]:
    db = get_db()
    cfg = await get_settings_doc()
    return cash_forecast(await open_invoices(), await db.payables.find({}).to_list(20000),
                         float(cfg.get("payroll_monthly", 0)), weeks, today(), opening_cash=await cash_position())


def reminder_text(inv: dict[str, Any], client: dict[str, Any]) -> dict[str, str]:
    age = invoice_age_days(inv, today())
    num = inv.get("number") or inv["_id"][:8]
    out = f"₦{outstanding_amount(inv):,.0f}"
    return {
        "to": client.get("email") or "",
        "subject": f"Payment reminder: invoice {num} ({out} outstanding)",
        "body": (f"Dear {client.get('contact_name') or client.get('name')},\n\nOur records show invoice {num} for {out} "
                 f"issued on {inv['issue_date'][8:10]}/{inv['issue_date'][5:7]}/{inv['issue_date'][:4]} ({age} days ago) remains unpaid.\n"
                 "Kindly arrange payment or let us know the expected payment date.\n\nThank you,\nAccounts, GPPSL"),
    }
