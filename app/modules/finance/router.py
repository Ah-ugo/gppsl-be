import base64
import json
import re
from typing import Any, Optional

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile

from app.core.common import clean, clean_many, new_id, today, utcnow_iso
from app.core.config import get_settings
from app.core.db import get_db
from app.core.deps import client_ip, get_current_user, require_roles
from app.core.mailer import send_email
from app.core.storage import save_bytes
from app.logic.finance import invoice_age_days, is_open, outstanding_amount
from app.modules.audit import log
from app.modules.notifications import notify, notify_roles
from app.modules.projects.service import client_name_map

from . import service
from .schemas import (
    CATEGORIES,
    DecisionIn,
    ExpenseIn,
    InvoiceIn,
    InvoiceUpdate,
    PayableIn,
    PayableUpdate,
    PayIn,
    ReceiptIn,
    ReminderIn,
)

router = APIRouter(tags=["finance"], dependencies=[Depends(get_current_user)])
ALL = ("md", "admin", "finance", "supervisor", "storekeeper", "hr")
FIN = ("md", "admin", "finance")


# ---- Expenses -------------------------------------------------------------------------------
@router.get("/expenses/categories")
async def categories(_: dict = Depends(require_roles(*ALL))):
    return CATEGORIES


@router.post("/expenses/scan")
async def scan_receipt(
    file: UploadFile = File(...), _: dict = Depends(require_roles(*ALL))
):
    """Receipt photo -> {amount, vendor, date} for prefill. Uses Mistral when configured; otherwise it stays manual."""
    data = await file.read()
    stored = await save_bytes(
        data, file.filename or "receipt.jpg", file.content_type or "image/jpeg"
    )
    s = get_settings()
    if s.mistral_api_key:
        try:
            prompt = (
                'Read this receipt. Reply with ONLY JSON: {"amount": number, "vendor": string, "date": "YYYY-MM-DD", '
                '"category": one of '
                + ",".join(CATEGORIES)
                + "}. Use null for anything unreadable."
            )
            body = {
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:{file.content_type or 'image/jpeg'};base64,{base64.b64encode(data).decode()}"
                                },
                            },
                        ],
                    }
                ],
                "model": s.mistral_model,
            }
            async with httpx.AsyncClient(timeout=40) as c:
                r = await c.post(
                    "https://api.mistral.ai/v1/chat/completions",
                    headers={"Authorization": f"Bearer {s.mistral_api_key}"},
                    json=body,
                )
                r.raise_for_status()
            text = r.json()["choices"][0]["message"]["content"]
            parsed = json.loads(re.search(r"\{.*\}", text, re.S).group(0))
            return {**parsed, "receipt_url": stored["url"], "source": "mistral"}
        except Exception as exc:  # noqa: BLE001
            return {
                "amount": None,
                "vendor": None,
                "date": None,
                "receipt_url": stored["url"],
                "source": "unavailable",
                "note": f"Could not read the receipt automatically ({exc.__class__.__name__}). Please fill it in.",
            }
    return {
        "amount": None,
        "vendor": None,
        "date": None,
        "receipt_url": stored["url"],
        "source": "MOCK",
        "note": "MOCK: AI receipt scanning is not configured. Please fill in the receipt fields manually.",
    }


@router.post("/expenses", status_code=201)
async def create_expense(
    body: ExpenseIn, request: Request, user: dict = Depends(require_roles(*ALL))
):
    exp = await service.create_expense(body, user)
    approver = exp["required_approver"]
    await log(
        user,
        "create",
        "expense",
        exp["_id"],
        f"Raised expense ₦{exp['amount_ngn']:,.0f} ({body.vendor}) routed to {approver.upper()}"
        + (f"; flags: {', '.join(exp['flags'])}" if exp["flags"] else ""),
        client_ip(request),
    )
    await notify_roles(
        [approver],
        "Expense awaiting approval",
        f"{user['name']} raised ₦{exp['amount_ngn']:,.0f} for {body.vendor}",
        "/approvals",
    )
    return service.view(exp)


@router.get("/expenses")
async def list_expenses(
    status: Optional[str] = None,
    mine: bool = False,
    project_id: Optional[str] = None,
    user: dict = Depends(require_roles(*ALL)),
):
    q: dict[str, Any] = {}
    if mine or user["role"] not in FIN:
        q["requester.id"] = user["id"]
    if status:
        q["status"] = status
    if project_id:
        if user["role"] not in FIN:
            raise HTTPException(
                403, "Project costs are visible to finance and management only"
            )
        q["project_id"] = project_id
    rows = await get_db().expenses.find(q).sort("created_at", -1).to_list(2000)
    names = {
        p["_id"]: p["name"]
        for p in await get_db().projects.find({}, {"name": 1}).to_list(1000)
    }
    return [service.view(r, names) for r in rows]


@router.get("/expenses/pending")
async def inbox(user: dict = Depends(require_roles("md", "finance"))):
    """Approvals inbox: only what this role must decide."""
    rows = (
        await get_db()
        .expenses.find({"status": "pending", "required_approver": user["role"]})
        .sort("created_at", 1)
        .to_list(500)
    )
    names = {
        p["_id"]: p["name"]
        for p in await get_db().projects.find({}, {"name": 1}).to_list(1000)
    }
    return [service.view(r, names) for r in rows]


@router.post("/expenses/{expense_id}/approve")
async def approve(
    expense_id: str,
    body: DecisionIn,
    request: Request,
    user: dict = Depends(require_roles("md", "finance")),
):
    exp = await service.decide(expense_id, user, True, body.comment)
    await log(
        user,
        "approve",
        "expense",
        expense_id,
        f"Approved expense ₦{exp['amount_ngn']:,.0f} ({exp['vendor']})"
        + (f": {body.comment}" if body.comment else ""),
        client_ip(request),
    )
    await notify(
        [exp["requester"]["id"]],
        "Expense approved",
        f"{user['name']} approved ₦{exp['amount_ngn']:,.0f} for {exp['vendor']}",
        "/expenses",
    )
    return service.view(exp)


@router.post("/expenses/{expense_id}/reject")
async def reject(
    expense_id: str,
    body: DecisionIn,
    request: Request,
    user: dict = Depends(require_roles("md", "finance")),
):
    if not (body.comment or "").strip():
        raise HTTPException(422, "Please give a reason when rejecting")
    exp = await service.decide(expense_id, user, False, body.comment)
    await log(
        user,
        "reject",
        "expense",
        expense_id,
        f"Rejected expense ₦{exp['amount_ngn']:,.0f} ({exp['vendor']}): {body.comment}",
        client_ip(request),
    )
    await notify(
        [exp["requester"]["id"]],
        "Expense rejected",
        f"{user['name']}: {body.comment}",
        "/expenses",
    )
    return service.view(exp)


# ---- Invoices / receivables -----------------------------------------------------------------
@router.get("/invoices")
async def list_invoices(
    status: Optional[str] = None,
    client_id: Optional[str] = None,
    open_only: bool = False,
    _: dict = Depends(require_roles(*FIN)),
):
    q: dict[str, Any] = {}
    if client_id:
        q["client_id"] = client_id
    if status:
        q["status"] = status
    rows = await get_db().invoices.find(q).sort("issue_date", 1).to_list(5000)
    names = await client_name_map()
    t = today()
    out = []
    for r in rows:
        if open_only and not is_open(r):
            continue
        v = clean(r)
        v["client_name"] = names.get(r.get("client_id"))
        v["outstanding"] = outstanding_amount(r) if is_open(r) else 0
        v["age_days"] = invoice_age_days(r, t)
        v["overdue"] = is_open(r) and r.get("due_date", "9999") < t.isoformat()
        out.append(v)
    return out


@router.post("/invoices", status_code=201)
async def create_invoice(
    body: InvoiceIn,
    request: Request,
    user: dict = Depends(require_roles("md", "admin", "finance")),
):
    if not await get_db().clients.find_one({"_id": body.client_id}):
        raise HTTPException(422, "Unknown client")
    doc = {
        "_id": new_id(),
        **body.model_dump(),
        "paid_amount": 0.0,
        "reminders": [],
        "created_at": utcnow_iso(),
    }
    doc["number"] = (
        doc["number"] or f"INV-{await get_db().invoices.count_documents({}) + 1:04d}"
    )
    await get_db().invoices.insert_one(doc)
    await log(
        user,
        "create",
        "invoice",
        doc["_id"],
        f"Created invoice {doc['number']} ₦{body.amount:,.0f}",
        client_ip(request),
    )
    return clean(doc)


@router.get("/invoices/{invoice_id}")
async def get_invoice(
    invoice_id: str, _: dict = Depends(require_roles(*FIN))
):
    db = get_db()
    inv = await db.invoices.find_one({"_id": invoice_id})
    if not inv:
        raise HTTPException(404, "Invoice not found")
    client = await db.clients.find_one({"_id": inv.get("client_id")})
    v = clean(inv)
    v["client"] = clean(client) if client else None
    v["client_name"] = client.get("name") if client else None
    t = today()
    v["outstanding"] = outstanding_amount(inv) if is_open(inv) else 0
    v["age_days"] = invoice_age_days(inv, t)
    v["overdue"] = is_open(inv) and inv.get("due_date", "9999") < t.isoformat()
    return v


@router.patch("/invoices/{invoice_id}")
async def update_invoice(
    invoice_id: str,
    body: InvoiceUpdate,
    request: Request,
    user: dict = Depends(require_roles("md", "admin", "finance")),
):
    db = get_db()
    inv = await db.invoices.find_one({"_id": invoice_id})
    if not inv:
        raise HTTPException(404, "Invoice not found")
    patch = body.model_dump(exclude_none=True)
    if "items" in patch:
        patch["items"] = [it if isinstance(it, dict) else it.model_dump() for it in patch["items"]]
    patch["updated_at"] = utcnow_iso()
    await db.invoices.update_one({"_id": invoice_id}, {"$set": patch})
    await log(
        user,
        "update",
        "invoice",
        invoice_id,
        f"Updated invoice {inv.get('number')}: {', '.join(patch.keys())}",
        client_ip(request),
    )
    return await get_invoice(invoice_id, user)


@router.delete("/invoices/{invoice_id}")
async def delete_invoice(
    invoice_id: str,
    request: Request,
    user: dict = Depends(require_roles("md", "admin", "finance")),
):
    db = get_db()
    inv = await db.invoices.find_one({"_id": invoice_id})
    if not inv:
        raise HTTPException(404, "Invoice not found")
    await db.invoices.delete_one({"_id": invoice_id})
    await log(
        user,
        "delete",
        "invoice",
        invoice_id,
        f"Deleted invoice {inv.get('number')}",
        client_ip(request),
    )
    return {"ok": True}


@router.post("/invoices/{invoice_id}/pay")
async def mark_paid(
    invoice_id: str,
    body: PayIn,
    request: Request,
    user: dict = Depends(require_roles("md", "admin", "finance")),
):
    db = get_db()
    inv = await db.invoices.find_one({"_id": invoice_id})
    if not inv:
        raise HTTPException(404, "Invoice not found")
    client = await db.clients.find_one({"_id": inv.get("client_id")})
    add = body.amount if body.amount is not None else outstanding_amount(inv)
    paid = min(float(inv["amount"]), float(inv.get("paid_amount") or 0) + add)
    status = "paid" if paid >= float(inv["amount"]) else "part_paid"
    await db.invoices.update_one(
        {"_id": invoice_id}, {"$set": {"paid_amount": paid, "status": status}}
    )
    
    # Generate an official receipt record
    receipt_count = await db.receipts.count_documents({}) + 1
    receipt_num = f"REC-{today().year}-{receipt_count:04d}"
    receipt_doc = {
        "_id": new_id(),
        "receipt_number": receipt_num,
        "invoice_id": invoice_id,
        "invoice_number": inv.get("number"),
        "client_id": inv.get("client_id"),
        "client_name": client.get("name") if client else "Unknown Client",
        "amount": add,
        "payment_method": body.payment_method,
        "reference": body.reference or f"TXN-{new_id()[:8].upper()}",
        "date": body.date or today().isoformat(),
        "notes": body.notes,
        "balance_remaining": max(0.0, float(inv["amount"]) - paid),
        "recorded_by": {"id": user["id"], "name": user["name"]},
        "created_at": utcnow_iso(),
    }
    await db.receipts.insert_one(receipt_doc)
    
    await log(
        user,
        "update",
        "invoice",
        invoice_id,
        f"Recorded payment ₦{add:,.0f} on {inv.get('number')} ({status}). Issued receipt {receipt_num}",
        client_ip(request),
    )
    return clean(await db.invoices.find_one({"_id": invoice_id}))


@router.get("/invoices/{invoice_id}/reminder-draft")
async def reminder_draft(
    invoice_id: str, _: dict = Depends(require_roles("md", "admin", "finance"))
):
    """Prefilled text for the 'Send reminder' modal."""
    db = get_db()
    inv = await db.invoices.find_one({"_id": invoice_id})
    if not inv:
        raise HTTPException(404, "Invoice not found")
    client = await db.clients.find_one({"_id": inv["client_id"]}) or {}
    return service.reminder_text(inv, client)


@router.post("/invoices/{invoice_id}/remind")
async def remind(
    invoice_id: str,
    body: ReminderIn,
    request: Request,
    user: dict = Depends(require_roles("md", "admin", "finance")),
):
    db = get_db()
    inv = await db.invoices.find_one({"_id": invoice_id})
    if not inv:
        raise HTTPException(404, "Invoice not found")
    if not is_open(inv):
        raise HTTPException(409, "This invoice is not outstanding")
    client = await db.clients.find_one({"_id": inv["client_id"]}) or {}
    draft = service.reminder_text(inv, client)
    to = body.to or draft["to"]
    if not to:
        raise HTTPException(
            422, "No email address for this client. Enter one in the reminder."
        )
    subject, text = body.subject or draft["subject"], body.body or draft["body"]
    result = await send_email(to, subject, text)
    entry = {
        "sent_at": utcnow_iso(),
        "sent_by": user["name"],
        "to": to,
        "subject": subject,
        "status": result["status"],
        "provider": result["provider"],
    }
    await db.invoices.update_one({"_id": invoice_id}, {"$push": {"reminders": entry}})
    await log(
        user,
        "remind",
        "invoice",
        invoice_id,
        f"Reminder for {inv.get('number')} to {to} ({result['status']}, {result['provider']})",
        client_ip(request),
    )
    return entry


# ---- Payables -------------------------------------------------------------------------------
@router.get("/payables")
async def list_payables(_: dict = Depends(require_roles(*FIN))):
    return clean_many(
        await get_db().payables.find({}).sort("due_date", 1).to_list(2000)
    )


@router.post("/payables", status_code=201)
async def create_payable(
    body: PayableIn,
    request: Request,
    user: dict = Depends(require_roles("md", "admin", "finance")),
):
    doc = {"_id": new_id(), **body.model_dump(), "created_at": utcnow_iso()}
    await get_db().payables.insert_one(doc)
    await log(
        user,
        "create",
        "payable",
        doc["_id"],
        f"Added payable ₦{body.amount:,.0f} to {body.vendor}",
        client_ip(request),
    )
    return clean(doc)


@router.patch("/payables/{payable_id}")
async def update_payable(
    payable_id: str,
    body: PayableUpdate,
    request: Request,
    user: dict = Depends(require_roles("md", "admin", "finance")),
):
    db = get_db()
    p = await db.payables.find_one({"_id": payable_id})
    if not p:
        raise HTTPException(404, "Payable not found")
    patch = body.model_dump(exclude_none=True)
    patch["updated_at"] = utcnow_iso()
    await db.payables.update_one({"_id": payable_id}, {"$set": patch})
    await log(
        user,
        "update",
        "payable",
        payable_id,
        f"Updated payable {p.get('vendor')}: {', '.join(patch.keys())}",
        client_ip(request),
    )
    return clean(await db.payables.find_one({"_id": payable_id}))


@router.delete("/payables/{payable_id}")
async def delete_payable(
    payable_id: str,
    request: Request,
    user: dict = Depends(require_roles("md", "admin", "finance")),
):
    db = get_db()
    p = await db.payables.find_one({"_id": payable_id})
    if not p:
        raise HTTPException(404, "Payable not found")
    await db.payables.delete_one({"_id": payable_id})
    await log(
        user,
        "delete",
        "payable",
        payable_id,
        f"Deleted payable to {p.get('vendor')}",
        client_ip(request),
    )
    return {"ok": True}


@router.post("/payables/{payable_id}/pay")
async def mark_payable_paid(
    payable_id: str,
    request: Request,
    user: dict = Depends(require_roles("md", "admin", "finance")),
):
    db = get_db()
    p = await db.payables.find_one({"_id": payable_id})
    if not p:
        raise HTTPException(404, "Payable not found")
    await db.payables.update_one({"_id": payable_id}, {"$set": {"status": "paid", "paid_at": utcnow_iso()}})
    await log(
        user,
        "update",
        "payable",
        payable_id,
        f"Marked payable ₦{p.get('amount', 0):,.0f} to {p.get('vendor')} as paid",
        client_ip(request),
    )
    return clean(await db.payables.find_one({"_id": payable_id}))


# ---- Receipts -------------------------------------------------------------------------------
@router.get("/receipts")
async def list_receipts(
    client_id: Optional[str] = None,
    invoice_id: Optional[str] = None,
    _: dict = Depends(require_roles(*FIN)),
):
    q: dict[str, Any] = {}
    if client_id:
        q["client_id"] = client_id
    if invoice_id:
        q["invoice_id"] = invoice_id
    rows = await get_db().receipts.find(q).sort("created_at", -1).to_list(2000)
    return clean_many(rows)


@router.get("/receipts/{receipt_id}")
async def get_receipt(
    receipt_id: str, _: dict = Depends(require_roles(*FIN))
):
    db = get_db()
    rec = await db.receipts.find_one({"_id": receipt_id})
    if not rec:
        raise HTTPException(404, "Receipt not found")
    inv = await db.invoices.find_one({"_id": rec.get("invoice_id")})
    client = await db.clients.find_one({"_id": rec.get("client_id")})
    v = clean(rec)
    v["invoice"] = clean(inv) if inv else None
    v["client"] = clean(client) if client else None
    return v


@router.post("/receipts", status_code=201)
async def create_receipt(
    body: ReceiptIn,
    request: Request,
    user: dict = Depends(require_roles("md", "admin", "finance")),
):
    db = get_db()
    inv = await db.invoices.find_one({"_id": body.invoice_id})
    if not inv:
        raise HTTPException(404, "Invoice not found")
    client = await db.clients.find_one({"_id": body.client_id or inv.get("client_id")})
    receipt_count = await db.receipts.count_documents({}) + 1
    receipt_num = f"REC-{today().year}-{receipt_count:04d}"
    doc = {
        "_id": new_id(),
        "receipt_number": receipt_num,
        "invoice_id": body.invoice_id,
        "invoice_number": inv.get("number"),
        "client_id": inv.get("client_id"),
        "client_name": client.get("name") if client else "Unknown Client",
        "amount": body.amount,
        "payment_method": body.payment_method,
        "reference": body.reference or f"TXN-{new_id()[:8].upper()}",
        "date": body.date or today().isoformat(),
        "notes": body.notes,
        "balance_remaining": max(0.0, float(inv["amount"]) - float(inv.get("paid_amount") or 0) - body.amount),
        "recorded_by": {"id": user["id"], "name": user["name"]},
        "created_at": utcnow_iso(),
    }
    await db.receipts.insert_one(doc)
    # Also update invoice paid amount
    new_paid = min(float(inv["amount"]), float(inv.get("paid_amount") or 0) + body.amount)
    status = "paid" if new_paid >= float(inv["amount"]) else "part_paid"
    await db.invoices.update_one({"_id": body.invoice_id}, {"$set": {"paid_amount": new_paid, "status": status}})
    await log(
        user,
        "create",
        "receipt",
        doc["_id"],
        f"Issued receipt {receipt_num} ₦{body.amount:,.0f} for {inv.get('number')}",
        client_ip(request),
    )
    return clean(doc)


@router.delete("/receipts/{receipt_id}")
async def delete_receipt(
    receipt_id: str,
    request: Request,
    user: dict = Depends(require_roles("md", "admin", "finance")),
):
    db = get_db()
    rec = await db.receipts.find_one({"_id": receipt_id})
    if not rec:
        raise HTTPException(404, "Receipt not found")
    await db.receipts.delete_one({"_id": receipt_id})
    await log(
        user,
        "delete",
        "receipt",
        receipt_id,
        f"Deleted receipt {rec.get('receipt_number')}",
        client_ip(request),
    )
    return {"ok": True}


# ---- Reports --------------------------------------------------------------------------------
@router.get("/finance/ageing")
async def ageing(_: dict = Depends(require_roles(*FIN))):
    return await service.ageing()


@router.get("/finance/forecast")
async def forecast(
    weeks: int = Query(8, ge=1, le=26), _: dict = Depends(require_roles(*FIN))
):
    return await service.forecast(weeks)


@router.get("/finance/overview")
async def overview(_: dict = Depends(require_roles(*FIN))):
    db = get_db()
    from app.core.settings_store import get_settings_doc

    cfg = await get_settings_doc()
    receivables = await service.receivables_total()
    expenses = await db.expenses.find({}).to_list(20000)
    vat = round(
        sum(
            float(e.get("amount_ngn") or 0)
            for e in expenses
            if e["status"] == "approved"
        )
        * 0.075,
        2,
    )
    return {
        "cash": await service.cash_position(),
        "receivables": receivables,
        "payables": await service.payables_total(),
        "ageing": await service.ageing(),
        "usd_rate": cfg["usd_rate"],
        "pending_approvals": sum(1 for e in expenses if e["status"] == "pending"),
        "tax_figures": {
            "vat_rate": 0.075,
            "vat_on_approved_expenses": vat,
            "note": "Tracked figures only. Not tax advice or filing. WHT and PAYE are recorded by finance.",
        },
    }


# ---- PDF Export ---------------------------------------------------------------
@router.get("/invoices/{invoice_id}/pdf")
async def invoice_pdf(
    invoice_id: str,
    _: dict = Depends(require_roles(*FIN)),
):
    """Generates and returns a professional A4 PDF of the invoice (real data, not a screenshot)."""
    from fastapi.responses import Response as _Response

    from app.core.settings_store import get_settings_doc

    from .pdf import build_invoice_pdf

    db = get_db()
    inv = await db.invoices.find_one({"_id": invoice_id})
    if not inv:
        raise HTTPException(404, "Invoice not found")
    client = await db.clients.find_one({"_id": inv.get("client_id")}) if inv.get("client_id") else None
    receipts = await db.receipts.find({"invoice_id": invoice_id}).to_list(100)
    settings = await get_settings_doc()
    company = settings.get("company") or {}
    try:
        pdf_bytes = await build_invoice_pdf(inv, client, receipts, company)
    except RuntimeError as e:
        raise HTTPException(500, str(e))
    filename = f"Invoice_{inv.get('number', invoice_id)}.pdf"
    return _Response(
        pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/receipts/{receipt_id}/pdf")
async def receipt_pdf(
    receipt_id: str,
    _: dict = Depends(require_roles(*FIN)),
):
    """Generates and returns a professional A4 PDF of the receipt (real data, not a screenshot)."""
    from fastapi.responses import Response as _Response

    from app.core.settings_store import get_settings_doc

    from .pdf import build_receipt_pdf

    db = get_db()
    rec = await db.receipts.find_one({"_id": receipt_id})
    if not rec:
        raise HTTPException(404, "Receipt not found")
    inv = await db.invoices.find_one({"_id": rec.get("invoice_id")}) if rec.get("invoice_id") else None
    client = await db.clients.find_one({"_id": rec.get("client_id")}) if rec.get("client_id") else None
    settings = await get_settings_doc()
    company = settings.get("company") or {}
    try:
        pdf_bytes = await build_receipt_pdf(rec, inv, client, company)
    except RuntimeError as e:
        raise HTTPException(500, str(e))
    filename = f"Receipt_{rec.get('receipt_number', receipt_id)}.pdf"
    return _Response(
        pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/invoices/{invoice_id}/share")
async def share_invoice(
    invoice_id: str,
    request: Request,
    user: dict = Depends(require_roles(*FIN)),
):
    """Emails the invoice PDF to the client's registered email address."""
    db = get_db()
    inv = await db.invoices.find_one({"_id": invoice_id})
    if not inv:
        raise HTTPException(404, "Invoice not found")
    client = await db.clients.find_one({"_id": inv.get("client_id")}) if inv.get("client_id") else None
    if not client or not client.get("email"):
        raise HTTPException(422, "Client has no registered email address. Update the client record first.")

    from app.core.mailer import send_email
    from app.core.settings_store import get_settings_doc

    from .pdf import build_invoice_pdf

    settings = await get_settings_doc()
    company = settings.get("company") or {}
    try:
        pdf_bytes = await build_invoice_pdf(inv, client, [], company)
    except RuntimeError as e:
        raise HTTPException(500, str(e))

    co_name = company.get("name") or "GPPSL Operations Ltd"
    subject = f"Invoice {inv.get('number')} from {co_name}"
    body_text = (
        f"Dear {client.get('contact_name') or client['name']},\n\n"
        f"Please find attached Invoice {inv.get('number')} for ₦{float(inv.get('amount', 0)):,.2f}.\n\n"
        f"Due Date: {inv.get('due_date', 'N/A')}\n\n"
        f"Please contact us if you have any questions.\n\n"
        f"Best regards,\n{co_name}"
    )
    result = await send_email(
        client["email"], subject, body_text,
        attachments=[{"filename": f"Invoice_{inv.get('number')}.pdf", "content": pdf_bytes, "mime_type": "application/pdf"}],
    )
    await log(user, "share", "invoice", invoice_id, f"Emailed invoice {inv.get('number')} to {client['email']} ({result['status']})", client_ip(request))
    return {"ok": True, "status": result["status"], "to": client["email"]}

