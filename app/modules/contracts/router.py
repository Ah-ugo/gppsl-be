"""Contracts, Tenders, and Quotations router."""
from datetime import timedelta
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.core.common import clean, clean_many, new_id, today, utcnow_iso
from app.core.db import get_db
from app.core.deps import client_ip, get_current_user, require_roles
from app.modules.audit import log
from app.modules.notifications import notify_roles

from .schemas import (ContractCreate, ContractUpdate, QuotationCreate, QuotationUpdate,
                      TenderCreate, TenderUpdate, VariationOrderIn)

ALL = ("md", "admin", "finance", "supervisor", "storekeeper", "hr")
SALES = ("md", "admin", "finance")

router = APIRouter(tags=["contracts"], dependencies=[Depends(get_current_user)])


# ── Tenders ───────────────────────────────────────────────────────────────────

@router.get("/tenders")
async def list_tenders(status: Optional[str] = None, branch: Optional[str] = None,
                        _: dict = Depends(require_roles(*SALES))):
    q: dict[str, Any] = {}
    if status:
        q["status"] = status
    if branch:
        q["branch"] = branch
    rows = await get_db().tenders.find(q).sort("submission_deadline", 1).to_list(500)
    t = today()
    result = []
    for r in rows:
        v = clean(r)
        dl = r.get("submission_deadline")
        v["days_to_deadline"] = (
            (today().__class__.fromisoformat(dl) - t).days if dl else None
        )
        result.append(v)
    return result


@router.post("/tenders", status_code=201)
async def create_tender(body: TenderCreate, request: Request, user: dict = Depends(require_roles(*SALES))):
    doc = {"_id": new_id(), **body.model_dump(), "created_by": user["name"], "created_at": utcnow_iso()}
    await get_db().tenders.insert_one(doc)
    await log(user, "create", "tender", doc["_id"], f"Tracking tender: {body.title}", client_ip(request))
    return clean(doc)


@router.patch("/tenders/{tender_id}")
async def update_tender(tender_id: str, body: TenderUpdate, request: Request,
                         user: dict = Depends(require_roles(*SALES))):
    tender = await _get_or_404(get_db().tenders, tender_id, "Tender")
    patch = body.model_dump(exclude_none=True)
    if not patch:
        raise HTTPException(422, "Nothing to update")
    patch["updated_at"] = utcnow_iso()
    await get_db().tenders.update_one({"_id": tender_id}, {"$set": patch})
    await log(user, "update", "tender", tender_id, f"Updated tender {tender['title']}", client_ip(request))
    return clean(await get_db().tenders.find_one({"_id": tender_id}))


@router.delete("/tenders/{tender_id}")
async def delete_tender(tender_id: str, request: Request, user: dict = Depends(require_roles("md", "admin"))):
    tender = await _get_or_404(get_db().tenders, tender_id, "Tender")
    await get_db().tenders.delete_one({"_id": tender_id})
    await log(user, "delete", "tender", tender_id, f"Deleted tender {tender['title']}", client_ip(request))
    return {"ok": True}


# ── Contracts ─────────────────────────────────────────────────────────────────

@router.get("/contracts")
async def list_contracts(status: Optional[str] = None, client_id: Optional[str] = None,
                          expiring_days: Optional[int] = None, _: dict = Depends(require_roles(*SALES))):
    q: dict[str, Any] = {}
    if status:
        q["status"] = status
    if client_id:
        q["client_id"] = client_id
    if expiring_days is not None:
        cutoff = (today() + timedelta(days=expiring_days)).isoformat()
        q["end_date"] = {"$lte": cutoff, "$gte": today().isoformat()}
        q["status"] = "active"
    rows = await get_db().contracts.find(q).sort("end_date", 1).to_list(500)
    t = today()
    result = []
    for r in rows:
        v = clean(r)
        end = r.get("end_date")
        v["days_to_expiry"] = (
            (today().__class__.fromisoformat(end) - t).days if end else None
        )
        # total contract value including variations
        variations_total = sum(float(vo.get("value_ngn") or 0) for vo in r.get("variation_orders") or [])
        v["total_value"] = float(r.get("value_ngn") or 0) + variations_total
        result.append(v)
    return result


@router.post("/contracts", status_code=201)
async def create_contract(body: ContractCreate, request: Request, user: dict = Depends(require_roles(*SALES))):
    doc = {"_id": new_id(), **body.model_dump(), "created_by": user["name"], "created_at": utcnow_iso()}
    await get_db().contracts.insert_one(doc)
    await log(user, "create", "contract", doc["_id"], f"Created contract: {body.title} ₦{body.value_ngn:,.0f}", client_ip(request))
    return clean(doc)


@router.patch("/contracts/{contract_id}")
async def update_contract(contract_id: str, body: ContractUpdate, request: Request,
                           user: dict = Depends(require_roles(*SALES))):
    contract = await _get_or_404(get_db().contracts, contract_id, "Contract")
    patch = body.model_dump(exclude_none=True)
    if not patch:
        raise HTTPException(422, "Nothing to update")
    patch["updated_at"] = utcnow_iso()
    await get_db().contracts.update_one({"_id": contract_id}, {"$set": patch})
    await log(user, "update", "contract", contract_id, f"Updated contract {contract['title']}", client_ip(request))
    return clean(await get_db().contracts.find_one({"_id": contract_id}))


@router.post("/contracts/{contract_id}/variations", status_code=201)
async def add_variation(contract_id: str, body: VariationOrderIn, request: Request,
                         user: dict = Depends(require_roles(*SALES))):
    contract = await _get_or_404(get_db().contracts, contract_id, "Contract")
    vo = {**body.model_dump(), "added_by": user["name"], "added_at": utcnow_iso()}
    await get_db().contracts.update_one({"_id": contract_id}, {"$push": {"variation_orders": vo}})
    await log(user, "update", "contract", contract_id,
              f"Added variation ₦{body.value_ngn:,.0f}: {body.description}", client_ip(request))
    return clean(await get_db().contracts.find_one({"_id": contract_id}))


@router.delete("/contracts/{contract_id}")
async def delete_contract(contract_id: str, request: Request, user: dict = Depends(require_roles("md", "admin"))):
    contract = await _get_or_404(get_db().contracts, contract_id, "Contract")
    await get_db().contracts.delete_one({"_id": contract_id})
    await log(user, "delete", "contract", contract_id, f"Deleted contract {contract['title']}", client_ip(request))
    return {"ok": True}


# ── Quotations ────────────────────────────────────────────────────────────────

@router.get("/quotations")
async def list_quotations(status: Optional[str] = None, client_id: Optional[str] = None,
                           _: dict = Depends(require_roles(*SALES))):
    q: dict[str, Any] = {}
    if status:
        q["status"] = status
    if client_id:
        q["client_id"] = client_id
    return clean_many(await get_db().quotations.find(q).sort("created_at", -1).to_list(500))


@router.post("/quotations", status_code=201)
async def create_quotation(body: QuotationCreate, request: Request, user: dict = Depends(require_roles(*SALES))):
    db = get_db()
    subtotal = sum(l.qty * l.unit_price for l in body.lines)
    discount = subtotal * (body.discount_pct / 100)
    net = subtotal - discount
    vat = net * (body.vat_pct / 100)
    total = net + vat
    valid_until = (today() + timedelta(days=body.validity_days)).isoformat()
    q_number = f"Q-{await db.quotations.count_documents({}) + 1:04d}"

    doc = {
        "_id": new_id(), "number": q_number, **body.model_dump(),
        "lines": [l.model_dump() for l in body.lines],
        "subtotal": subtotal, "discount": discount, "net": net, "vat": vat, "total": total,
        "valid_until": valid_until, "status": "draft",
        "version": 1, "created_by": {"id": user["id"], "name": user["name"]},
        "created_at": utcnow_iso(),
    }
    await db.quotations.insert_one(doc)
    await log(user, "create", "quotation", doc["_id"], f"Created quotation {q_number} ₦{total:,.0f}", client_ip(request))
    return clean(doc)


@router.patch("/quotations/{quotation_id}")
async def update_quotation(quotation_id: str, body: QuotationUpdate, request: Request,
                            user: dict = Depends(require_roles(*SALES))):
    q = await _get_or_404(get_db().quotations, quotation_id, "Quotation")
    patch = body.model_dump(exclude_none=True)

    # Recompute totals if lines changed
    if "lines" in patch:
        lines = patch["lines"]
        disc_pct = patch.get("discount_pct", q.get("discount_pct", 0))
        vat_pct = q.get("vat_pct", 7.5)
        subtotal = sum(l["qty"] * l["unit_price"] for l in lines)
        discount = subtotal * (disc_pct / 100)
        net = subtotal - discount
        vat = net * (vat_pct / 100)
        patch.update({"subtotal": subtotal, "discount": discount, "net": net, "vat": vat, "total": net + vat,
                      "version": q.get("version", 1) + 1})

    patch["updated_at"] = utcnow_iso()
    await get_db().quotations.update_one({"_id": quotation_id}, {"$set": patch})
    await log(user, "update", "quotation", quotation_id, f"Updated quotation {q['number']}", client_ip(request))
    return clean(await get_db().quotations.find_one({"_id": quotation_id}))


@router.delete("/quotations/{quotation_id}")
async def delete_quotation(quotation_id: str, request: Request, user: dict = Depends(require_roles("md", "admin"))):
    q = await _get_or_404(get_db().quotations, quotation_id, "Quotation")
    await get_db().quotations.delete_one({"_id": quotation_id})
    await log(user, "delete", "quotation", quotation_id, f"Deleted quotation {q['number']}", client_ip(request))
    return {"ok": True}


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _get_or_404(collection: Any, doc_id: str, label: str) -> dict[str, Any]:
    doc = await collection.find_one({"_id": doc_id})
    if not doc:
        raise HTTPException(404, f"{label} not found")
    return doc
