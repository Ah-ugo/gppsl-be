"""HSE: incidents, corrective actions, risk assessments, permits to work, audits."""
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.core.common import clean, clean_many, new_id, today, utcnow_iso
from app.core.db import get_db
from app.core.deps import client_ip, get_current_user, require_roles
from app.modules.audit import log
from app.modules.notifications import notify_roles

from .schemas import (CorrectiveActionIn, CorrectiveActionUpdate, HSEAuditCreate,
                       HSEIncidentCreate, PermitToWorkCreate, PermitToWorkUpdate,
                       RiskAssessmentCreate)

ALL = ("md", "admin", "supervisor", "storekeeper", "finance", "hr")
HSE_W = ("md", "admin", "supervisor")

router = APIRouter(tags=["hse"], dependencies=[Depends(get_current_user)])


# ── Incidents ─────────────────────────────────────────────────────────────────

@router.get("/hse/incidents")
async def list_incidents(severity: Optional[str] = None, project_id: Optional[str] = None,
                          type: Optional[str] = None, _: dict = Depends(require_roles(*ALL))):
    q: dict[str, Any] = {}
    if severity:
        q["severity"] = severity
    if project_id:
        q["project_id"] = project_id
    if type:
        q["type"] = type
    rows = await get_db().hse_incidents.find(q).sort("date", -1).to_list(500)
    return clean_many(rows)


@router.post("/hse/incidents", status_code=201)
async def report_incident(body: HSEIncidentCreate, request: Request, user: dict = Depends(require_roles(*ALL))):
    doc = {
        "_id": new_id(), **body.model_dump(),
        "date": body.date or today().isoformat(),
        "status": "open",
        "reported_by": {"id": user["id"], "name": user["name"]},
        "created_at": utcnow_iso(),
    }
    await get_db().hse_incidents.insert_one(doc)
    if body.severity in ("high", "critical"):
        await notify_roles(["md", "admin"], f"HSE {body.severity.upper()} incident",
                           f"{body.type}: {body.title} at {body.location}", "/hse")
    await log(user, "create", "hse_incident", doc["_id"],
              f"Reported {body.type}: {body.title} (severity: {body.severity})", client_ip(request))
    return clean(doc)


@router.patch("/hse/incidents/{incident_id}")
async def update_incident(incident_id: str, body: dict, request: Request,
                           user: dict = Depends(require_roles(*HSE_W))):
    inc = await get_db().hse_incidents.find_one({"_id": incident_id})
    if not inc:
        raise HTTPException(404, "Incident not found")
    allowed = {"root_cause", "immediate_actions", "status", "injuries", "investigation_notes"}
    patch = {k: v for k, v in body.items() if k in allowed}
    if not patch:
        raise HTTPException(422, "No valid fields to update")
    patch["updated_at"] = utcnow_iso()
    await get_db().hse_incidents.update_one({"_id": incident_id}, {"$set": patch})
    await log(user, "update", "hse_incident", incident_id, f"Updated incident {inc['title']}", client_ip(request))
    return clean(await get_db().hse_incidents.find_one({"_id": incident_id}))


# ── Corrective actions ────────────────────────────────────────────────────────

@router.get("/hse/corrective-actions")
async def list_corrective_actions(status: Optional[str] = None, incident_id: Optional[str] = None,
                                   overdue: bool = False, _: dict = Depends(require_roles(*ALL))):
    q: dict[str, Any] = {}
    if status:
        q["status"] = status
    if incident_id:
        q["incident_id"] = incident_id
    if overdue:
        q["due_date"] = {"$lt": today().isoformat()}
        q["status"] = {"$in": ["open", "in_progress"]}
    return clean_many(await get_db().hse_corrective_actions.find(q).sort("due_date", 1).to_list(500))


@router.post("/hse/corrective-actions", status_code=201)
async def create_corrective_action(body: CorrectiveActionIn, request: Request,
                                    user: dict = Depends(require_roles(*HSE_W))):
    doc = {
        "_id": new_id(), **body.model_dump(), "status": "open",
        "created_by": {"id": user["id"], "name": user["name"]}, "created_at": utcnow_iso(),
    }
    await get_db().hse_corrective_actions.insert_one(doc)
    await log(user, "create", "hse_corrective_action", doc["_id"],
              f"Corrective action: {body.description[:60]}", client_ip(request))
    return clean(doc)


@router.patch("/hse/corrective-actions/{action_id}")
async def update_corrective_action(action_id: str, body: CorrectiveActionUpdate, request: Request,
                                    user: dict = Depends(require_roles(*HSE_W))):
    action = await get_db().hse_corrective_actions.find_one({"_id": action_id})
    if not action:
        raise HTTPException(404, "Corrective action not found")
    patch = body.model_dump(exclude_none=True)
    if patch.get("status") == "closed" and not patch.get("resolution"):
        raise HTTPException(422, "Provide a resolution when closing an action")
    if patch.get("status") == "closed":
        patch["closed_date"] = patch.get("closed_date") or today().isoformat()
        patch["closed_by"] = user["name"]
    patch["updated_at"] = utcnow_iso()
    await get_db().hse_corrective_actions.update_one({"_id": action_id}, {"$set": patch})
    await log(user, "update", "hse_corrective_action", action_id,
              f"Action status → {patch.get('status', 'updated')}", client_ip(request))
    return clean(await get_db().hse_corrective_actions.find_one({"_id": action_id}))


# ── Risk assessments ──────────────────────────────────────────────────────────

@router.get("/hse/risk-assessments")
async def list_risk_assessments(project_id: Optional[str] = None, _: dict = Depends(require_roles(*ALL))):
    q: dict[str, Any] = {}
    if project_id:
        q["project_id"] = project_id
    return clean_many(await get_db().hse_risk_assessments.find(q).sort("created_at", -1).to_list(200))


@router.post("/hse/risk-assessments", status_code=201)
async def create_risk_assessment(body: RiskAssessmentCreate, request: Request,
                                  user: dict = Depends(require_roles(*HSE_W))):
    doc = {
        "_id": new_id(), **body.model_dump(), "status": "active",
        "created_by": {"id": user["id"], "name": user["name"]}, "created_at": utcnow_iso(),
    }
    await get_db().hse_risk_assessments.insert_one(doc)
    await log(user, "create", "hse_risk_assessment", doc["_id"], f"Risk assessment: {body.title}", client_ip(request))
    return clean(doc)


@router.delete("/hse/risk-assessments/{ra_id}")
async def delete_risk_assessment(ra_id: str, request: Request, user: dict = Depends(require_roles("md", "admin"))):
    ra = await get_db().hse_risk_assessments.find_one({"_id": ra_id})
    if not ra:
        raise HTTPException(404, "Risk assessment not found")
    await get_db().hse_risk_assessments.delete_one({"_id": ra_id})
    await log(user, "delete", "hse_risk_assessment", ra_id, f"Deleted RA: {ra['title']}", client_ip(request))
    return {"ok": True}


# ── Permits to work ───────────────────────────────────────────────────────────

@router.get("/hse/permits")
async def list_permits(status: Optional[str] = None, project_id: Optional[str] = None,
                        _: dict = Depends(require_roles(*ALL))):
    q: dict[str, Any] = {}
    if status:
        q["status"] = status
    if project_id:
        q["project_id"] = project_id
    return clean_many(await get_db().hse_permits.find(q).sort("start_datetime", -1).to_list(200))


@router.post("/hse/permits", status_code=201)
async def create_permit(body: PermitToWorkCreate, request: Request, user: dict = Depends(require_roles(*HSE_W))):
    doc = {
        "_id": new_id(), **body.model_dump(), "status": "draft",
        "issued_by": body.issued_by or user["name"],
        "created_by": {"id": user["id"], "name": user["name"]}, "created_at": utcnow_iso(),
    }
    await get_db().hse_permits.insert_one(doc)
    await log(user, "create", "hse_permit", doc["_id"],
              f"PTW ({body.type}): {body.title} at {body.location}", client_ip(request))
    return clean(doc)


@router.patch("/hse/permits/{permit_id}")
async def update_permit(permit_id: str, body: PermitToWorkUpdate, request: Request,
                         user: dict = Depends(require_roles(*HSE_W))):
    permit = await get_db().hse_permits.find_one({"_id": permit_id})
    if not permit:
        raise HTTPException(404, "Permit not found")
    patch = body.model_dump(exclude_none=True)
    if patch.get("status") == "closed":
        patch["closed_at"] = patch.get("closed_at") or utcnow_iso()
        patch["closed_by"] = user["name"]
    patch["updated_at"] = utcnow_iso()
    await get_db().hse_permits.update_one({"_id": permit_id}, {"$set": patch})
    await log(user, "update", "hse_permit", permit_id,
              f"Permit {permit['title']} → {patch.get('status', 'updated')}", client_ip(request))
    return clean(await get_db().hse_permits.find_one({"_id": permit_id}))


# ── Safety audits ─────────────────────────────────────────────────────────────

@router.get("/hse/audits")
async def list_audits(project_id: Optional[str] = None, _: dict = Depends(require_roles(*ALL))):
    q: dict[str, Any] = {}
    if project_id:
        q["project_id"] = project_id
    return clean_many(await get_db().hse_audits.find(q).sort("date", -1).to_list(200))


@router.post("/hse/audits", status_code=201)
async def create_audit(body: HSEAuditCreate, request: Request, user: dict = Depends(require_roles(*HSE_W))):
    doc = {
        "_id": new_id(), **body.model_dump(),
        "date": body.date or today().isoformat(),
        "created_by": {"id": user["id"], "name": user["name"]}, "created_at": utcnow_iso(),
    }
    await get_db().hse_audits.insert_one(doc)
    await log(user, "create", "hse_audit", doc["_id"], f"HSE audit: {body.title}", client_ip(request))
    return clean(doc)


# ── Dashboard ─────────────────────────────────────────────────────────────────

@router.get("/hse/dashboard")
async def hse_dashboard(_: dict = Depends(require_roles(*ALL))):
    db = get_db()
    t = today().isoformat()
    open_incidents = await db.hse_incidents.count_documents({"status": "open"})
    open_actions = await db.hse_corrective_actions.count_documents({"status": {"$in": ["open", "in_progress"]}})
    overdue_actions = await db.hse_corrective_actions.count_documents(
        {"due_date": {"$lt": t}, "status": {"$in": ["open", "in_progress"]}}
    )
    active_permits = await db.hse_permits.count_documents({"status": {"$in": ["issued", "active"]}})
    recent_incidents = await db.hse_incidents.find({}).sort("date", -1).to_list(5)
    upcoming_actions = await db.hse_corrective_actions.find(
        {"status": {"$in": ["open", "in_progress"]}, "due_date": {"$gte": t}}
    ).sort("due_date", 1).to_list(5)
    return {
        "open_incidents": open_incidents,
        "open_corrective_actions": open_actions,
        "overdue_actions": overdue_actions,
        "active_permits": active_permits,
        "recent_incidents": clean_many(recent_incidents),
        "upcoming_actions": clean_many(upcoming_actions),
    }
