"""CRM router: clients, contacts, interaction history, sales pipeline."""
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.core.common import clean, clean_many, new_id, today, utcnow_iso
from app.core.db import get_db
from app.core.deps import client_ip, get_current_user, require_roles
from app.modules.audit import log

from .schemas import ClientCreate, ClientUpdate, InteractionIn, LeadCreate, LeadUpdate

ALL = ("md", "admin", "finance", "supervisor", "storekeeper", "hr")
SALES = ("md", "admin", "finance")

router = APIRouter(tags=["crm"], dependencies=[Depends(get_current_user)])


# ── Clients ──────────────────────────────────────────────────────────────────

@router.get("/clients")
async def list_clients(
    search: Optional[str] = None,
    branch: Optional[str] = None,
    limit: int = Query(500, le=1000),
    _: dict = Depends(require_roles(*ALL)),
):
    q: dict[str, Any] = {}
    if branch:
        q["branch"] = branch
    if search:
        q["$or"] = [
            {"name": {"$regex": search, "$options": "i"}},
            {"email": {"$regex": search, "$options": "i"}},
            {"phone": {"$regex": search, "$options": "i"}},
        ]
    rows = await get_db().clients.find(q).sort("name", 1).to_list(limit)
    return clean_many(rows)


@router.post("/clients", status_code=201)
async def create_client(body: ClientCreate, request: Request, user: dict = Depends(require_roles(*SALES))):
    db = get_db()
    if body.email and await db.clients.find_one({"email": body.email}):
        raise HTTPException(409, f"A client with email {body.email} already exists")
    doc = {"_id": new_id(), **body.model_dump(), "created_by": user["name"], "created_at": utcnow_iso()}
    await db.clients.insert_one(doc)
    await log(user, "create", "client", doc["_id"], f"Added client {doc['name']}", client_ip(request))
    return clean(doc)


@router.get("/clients/{client_id}")
async def get_client(client_id: str, _: dict = Depends(require_roles(*ALL))):
    doc = await _get_or_404(client_id)
    db = get_db()
    interactions = await db.crm_interactions.find({"client_id": client_id}).sort("date", -1).to_list(200)
    invoices = await db.invoices.find({"client_id": client_id}).sort("issue_date", -1).to_list(100)
    projects = await db.projects.find({"client_id": client_id}).to_list(100)
    leads = await db.crm_leads.find({"client_id": client_id}).sort("created_at", -1).to_list(50)
    result = clean(doc)
    result["interactions"] = clean_many(interactions)
    result["invoices_summary"] = [{"id": str(i["_id"]), "number": i.get("number"), "amount": i.get("amount"),
                                   "status": i.get("status"), "issue_date": i.get("issue_date")} for i in invoices]
    result["projects_summary"] = [{"id": str(p["_id"]), "name": p.get("name"), "status": p.get("status")} for p in projects]
    result["leads"] = clean_many(leads)
    # outstanding balance
    from app.logic.finance import is_open, outstanding_amount
    result["outstanding_balance"] = sum(outstanding_amount(i) if is_open(i) else 0 for i in invoices)
    return result


@router.patch("/clients/{client_id}")
async def update_client(client_id: str, body: ClientUpdate, request: Request, user: dict = Depends(require_roles(*SALES))):
    await _get_or_404(client_id)
    patch = body.model_dump(exclude_none=True)
    if not patch:
        raise HTTPException(422, "Nothing to update")
    await get_db().clients.update_one({"_id": client_id}, {"$set": patch})
    await log(user, "update", "client", client_id, f"Updated client fields: {', '.join(patch)}", client_ip(request))
    return clean(await get_db().clients.find_one({"_id": client_id}))


@router.delete("/clients/{client_id}")
async def delete_client(client_id: str, request: Request, user: dict = Depends(require_roles("md", "admin"))):
    doc = await _get_or_404(client_id)
    # check no open invoices
    open_inv = await get_db().invoices.find_one({"client_id": client_id, "status": {"$in": ["unpaid", "part_paid"]}})
    if open_inv:
        raise HTTPException(409, "Cannot delete a client with open invoices")
    await get_db().clients.delete_one({"_id": client_id})
    await log(user, "delete", "client", client_id, f"Deleted client {doc['name']}", client_ip(request))
    return {"ok": True}


# ── Interaction history ───────────────────────────────────────────────────────

@router.get("/crm/interactions")
async def list_interactions(client_id: Optional[str] = None, _: dict = Depends(require_roles(*SALES))):
    q: dict[str, Any] = {}
    if client_id:
        q["client_id"] = client_id
    rows = await get_db().crm_interactions.find(q).sort("date", -1).to_list(500)
    return clean_many(rows)


@router.post("/crm/interactions", status_code=201)
async def log_interaction(body: InteractionIn, request: Request, user: dict = Depends(require_roles(*SALES))):
    await _get_or_404(body.client_id)
    doc = {
        "_id": new_id(), **body.model_dump(),
        "date": body.date or today().isoformat(),
        "logged_by": {"id": user["id"], "name": user["name"]},
        "created_at": utcnow_iso(),
    }
    await get_db().crm_interactions.insert_one(doc)
    await log(user, "create", "crm_interaction", doc["_id"],
              f"Logged {body.type} with client {body.client_id}: {body.summary[:60]}", client_ip(request))
    return clean(doc)


@router.delete("/crm/interactions/{interaction_id}")
async def delete_interaction(interaction_id: str, request: Request, user: dict = Depends(require_roles("md", "admin"))):
    doc = await get_db().crm_interactions.find_one({"_id": interaction_id})
    if not doc:
        raise HTTPException(404, "Interaction not found")
    await get_db().crm_interactions.delete_one({"_id": interaction_id})
    await log(user, "delete", "crm_interaction", interaction_id, "Deleted interaction", client_ip(request))
    return {"ok": True}


# ── Sales pipeline / leads ────────────────────────────────────────────────────

@router.get("/crm/leads")
async def list_leads(stage: Optional[str] = None, owner_id: Optional[str] = None,
                     _: dict = Depends(require_roles(*SALES))):
    q: dict[str, Any] = {}
    if stage:
        q["stage"] = stage
    if owner_id:
        q["owner_id"] = owner_id
    rows = await get_db().crm_leads.find(q).sort("created_at", -1).to_list(1000)
    return clean_many(rows)


@router.post("/crm/leads", status_code=201)
async def create_lead(body: LeadCreate, request: Request, user: dict = Depends(require_roles(*SALES))):
    doc = {
        "_id": new_id(), **body.model_dump(),
        "owner_id": body.owner_id or user["id"],
        "owner_name": body.owner_name or user["name"],
        "created_by": user["name"], "created_at": utcnow_iso(),
    }
    await get_db().crm_leads.insert_one(doc)
    await log(user, "create", "lead", doc["_id"], f"Created lead: {body.title}", client_ip(request))
    return clean(doc)


@router.patch("/crm/leads/{lead_id}")
async def update_lead(lead_id: str, body: LeadUpdate, request: Request, user: dict = Depends(require_roles(*SALES))):
    doc = await get_db().crm_leads.find_one({"_id": lead_id})
    if not doc:
        raise HTTPException(404, "Lead not found")
    patch = body.model_dump(exclude_none=True)
    if not patch:
        raise HTTPException(422, "Nothing to update")
    patch["updated_at"] = utcnow_iso()
    await get_db().crm_leads.update_one({"_id": lead_id}, {"$set": patch})
    await log(user, "update", "lead", lead_id, f"Updated lead stage/value: {', '.join(patch)}", client_ip(request))
    return clean(await get_db().crm_leads.find_one({"_id": lead_id}))


@router.delete("/crm/leads/{lead_id}")
async def delete_lead(lead_id: str, request: Request, user: dict = Depends(require_roles("md", "admin"))):
    doc = await get_db().crm_leads.find_one({"_id": lead_id})
    if not doc:
        raise HTTPException(404, "Lead not found")
    await get_db().crm_leads.delete_one({"_id": lead_id})
    await log(user, "delete", "lead", lead_id, f"Deleted lead {doc['title']}", client_ip(request))
    return {"ok": True}


@router.get("/crm/pipeline")
async def pipeline_summary(_: dict = Depends(require_roles(*SALES))):
    """Kanban-friendly summary: count + total value per stage."""
    leads = await get_db().crm_leads.find({}).to_list(5000)
    stages = ["lead", "qualified", "proposal", "negotiation", "won", "lost"]
    result = {s: {"count": 0, "value": 0.0, "leads": []} for s in stages}
    for lead in leads:
        s = lead.get("stage", "lead")
        if s in result:
            result[s]["count"] += 1
            result[s]["value"] += float(lead.get("value_ngn") or 0)
            result[s]["leads"].append(clean(lead))
    return result


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _get_or_404(client_id: str) -> dict[str, Any]:
    doc = await get_db().clients.find_one({"_id": client_id})
    if not doc:
        raise HTTPException(404, "Client not found")
    return doc
