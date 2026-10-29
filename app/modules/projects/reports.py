"""Daily field reports and incidents. POST endpoints take a client-generated UUID and are IDEMPOTENT,
so an offline outbox can safely retry without creating duplicates."""
from datetime import timedelta
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field

from app.core.common import clean, clean_many, today, utcnow_iso
from app.core.db import get_db
from app.core.deps import client_ip, get_current_user, require_roles
from app.modules.audit import log
from app.modules.notifications import notify_roles

from . import service

router = APIRouter(tags=["reports"], dependencies=[Depends(get_current_user)])
WRITE = ("md", "admin", "supervisor")
READ = ("md", "admin", "supervisor", "finance")


class GPS(BaseModel):
    lat: float
    lng: float
    accuracy: Optional[float] = None


class ReportIn(BaseModel):
    id: str = Field(min_length=8, description="Client-generated UUID (idempotency key)")
    project_id: str
    date: Optional[str] = None
    progress: float = Field(ge=0, le=100)
    headcount: int = Field(ge=0, le=5000)
    equipment_used: list[str] = []
    issues: Optional[str] = None
    notes: Optional[str] = None
    photos: list[str] = []
    gps: Optional[GPS] = None
    created_offline: bool = False
    client_created_at: Optional[str] = None


class IncidentIn(BaseModel):
    id: str = Field(min_length=8)
    project_id: str
    severity: Literal["low", "medium", "high"]
    description: str
    photos: list[str] = []
    gps: Optional[GPS] = None
    client_created_at: Optional[str] = None


@router.post("/reports", status_code=201)
async def submit_report(body: ReportIn, request: Request, response: Response, user: dict = Depends(require_roles(*WRITE))):
    db = get_db()
    existing = await db.daily_reports.find_one({"_id": body.id})
    if existing:  # already received (offline retry): succeed without creating a second copy
        response.status_code = 200
        return {**clean(existing), "duplicate": True}
    project = await db.projects.find_one({"_id": body.project_id})
    if not project:
        raise HTTPException(422, "Unknown project")
    report_date = body.date or today().isoformat()
    headcount = body.headcount
    if not headcount:
        # Automatically get people on site today from attendance
        att_q = {"date": report_date, "status": {"$in": ["present", "verified", "on_time", "late", "flagged"]}}
        if project.get("branch"):
            att_q["branch"] = project["branch"]
        headcount = await db.attendance.count_documents(att_q)
        if not headcount and project.get("branch"):
            headcount = await db.attendance.count_documents({"date": report_date, "status": {"$in": ["present", "verified", "on_time", "late", "flagged"]}})

    doc = {"_id": body.id, **body.model_dump(exclude={"id"}), "headcount": headcount or body.headcount, "date": report_date,
           "author": {"id": user["id"], "name": user["name"]}, "branch": project.get("branch"), "received_at": utcnow_iso()}
    try:
        await db.daily_reports.insert_one(doc)
    except Exception:  # noqa: BLE001 - lost a race with a parallel retry of the same UUID
        again = await db.daily_reports.find_one({"_id": body.id})
        if again:
            response.status_code = 200
            return {**clean(again), "duplicate": True}
        raise
    # keep the project's headline progress current (only if this is the newest report)
    latest = project.get("last_report_date") or ""
    if doc["date"] >= latest:
        await db.projects.update_one({"_id": project["_id"]}, {"$set": {"progress": body.progress, "last_report_date": doc["date"]}})
    await log(user, "create", "report", body.id,
              f"Daily report for {project['name']}: {body.progress:.0f}% complete, {body.headcount} on site"
              + (" (synced from offline)" if body.created_offline else ""), client_ip(request))
    if body.issues and body.issues.strip():
        await notify_roles(["md"], "Issue reported on site", f"{project['name']}: {body.issues[:140]}", f"/projects/{project['_id']}")
    return {**clean(doc), "duplicate": False}


@router.get("/reports")
async def list_reports(project_id: Optional[str] = None, branch: Optional[str] = None,
                       date_from: Optional[str] = Query(None, alias="from"), date_to: Optional[str] = Query(None, alias="to"),
                       limit: int = Query(200, le=1000), _: dict = Depends(require_roles(*READ))):
    q: dict[str, Any] = {}
    if project_id:
        q["project_id"] = project_id
    if branch:
        q["branch"] = branch
    if date_from or date_to:
        q["date"] = {**({"$gte": date_from} if date_from else {}), **({"$lte": date_to} if date_to else {})}
    rows = await get_db().daily_reports.find(q).sort("date", -1).to_list(limit)
    names = {p["_id"]: p["name"] for p in await get_db().projects.find({}, {"name": 1}).to_list(1000)}
    return [{**clean(r), "project_name": names.get(r["project_id"])} for r in rows]


@router.post("/incidents", status_code=201)
async def submit_incident(body: IncidentIn, request: Request, response: Response, user: dict = Depends(require_roles(*WRITE))):
    db = get_db()
    existing = await db.incidents.find_one({"_id": body.id})
    if existing:
        response.status_code = 200
        return {**clean(existing), "duplicate": True}
    project = await db.projects.find_one({"_id": body.project_id})
    if not project:
        raise HTTPException(422, "Unknown project")
    doc = {"_id": body.id, **body.model_dump(exclude={"id"}), "date": today().isoformat(),
           "reporter": {"id": user["id"], "name": user["name"]}, "received_at": utcnow_iso()}
    await db.incidents.insert_one(doc)
    await log(user, "create", "incident", body.id, f"{body.severity.upper()} incident at {project['name']}: {body.description[:80]}", client_ip(request))
    if body.severity == "high":
        await notify_roles(["md"], "HIGH severity incident", f"{project['name']}: {body.description[:160]}", f"/projects/{project['_id']}", email=True)
    return {**clean(doc), "duplicate": False}


@router.get("/incidents")
async def list_incidents(project_id: Optional[str] = None, _: dict = Depends(require_roles(*READ))):
    q = {"project_id": project_id} if project_id else {}
    return clean_many(await get_db().incidents.find(q).sort("date", -1).to_list(200))


@router.get("/projects/{project_id}/summary")
async def project_summary(project_id: str, user: dict = Depends(require_roles("md", "admin", "supervisor", "finance"))):
    db = get_db()
    p = await db.projects.find_one({"_id": project_id})
    if not p:
        raise HTTPException(404, "Project not found")
    view = await service.view(p, user["role"], await service.client_name_map())
    since = (today() - timedelta(days=7)).isoformat()
    reports = await db.daily_reports.find({"project_id": project_id, "date": {"$gte": since}}).sort("date", -1).to_list(100)
    open_rentals = await db.rentals.find({"project_id": project_id, "actual_return": None}).to_list(200)
    incidents = await db.incidents.find({"project_id": project_id}).sort("date", -1).limit(10).to_list(10)
    out: dict[str, Any] = {
        "project": view,
        "last_7_days": {"reports": clean_many(reports), "count": len(reports),
                        "avg_headcount": round(sum(r["headcount"] for r in reports) / len(reports), 1) if reports else 0,
                        "issues": [r["issues"] for r in reports if r.get("issues")]},
        "equipment_on_site": [{"id": r["equipment_id"], "name": r.get("equipment_name"), "since": r["start_date"],
                               "expected_return": r.get("expected_return"), "rental_id": r["_id"]} for r in open_rentals],
        "recent_incidents": clean_many(incidents),
    }
    if user["role"] in service.MONEY_ROLES:
        cost = view.get("cost", 0)
        budget = float(p.get("budget") or 0)
        exp = await db.expenses.find({"project_id": project_id, "status": {"$in": ["approved", "paid"]}}).sort("date", -1).to_list(500)
        fuel = await db.fuel_logs.find({"project_id": project_id}).to_list(500)
        out["costs"] = {"budget": budget, "cost": cost, "remaining": round(budget - cost, 2), "cost_pct": view.get("cost_pct", 0),
                        "fuel_total": sum(float(f.get("cost") or 0) for f in fuel),
                        "by_category": _by_category(exp), "expenses": [clean(e) for e in exp[:50]]}
    return out


def _by_category(expenses: list[dict[str, Any]]) -> dict[str, float]:
    out: dict[str, float] = {}
    for e in expenses:
        out[e["category"]] = out.get(e["category"], 0) + float(e.get("amount_ngn") or 0)
    return {k: round(v, 2) for k, v in out.items()}
