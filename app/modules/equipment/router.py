import io
from typing import Any, Optional

import qrcode
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response

from app.core.common import clean, clean_many, new_id, today, utcnow_iso
from app.core.db import get_db
from app.core.deps import client_ip, get_current_user, require_roles
from app.modules.audit import log
from app.modules.notifications import notify_roles

from . import service
from .schemas import (CheckinIn, CheckoutIn, EquipmentCreate, EquipmentUpdate, FuelLogCreate,
                      MaintenanceComplete, MaintenanceCreate, RentalRequestCreate, RentalRequestDecision)

READ = ("md", "admin", "storekeeper", "supervisor")
WRITE = ("md", "admin", "storekeeper")

router = APIRouter(tags=["equipment"], dependencies=[Depends(get_current_user)])


# ---- Inventory ------------------------------------------------------------------------------
@router.get("/equipment")
async def list_equipment(
    search: Optional[str] = None, status: Optional[str] = None, category: Optional[str] = None,
    branch: Optional[str] = None, limit: int = Query(500, le=1000),
    _: dict = Depends(require_roles(*READ)),
):
    q: dict[str, Any] = {}
    if status:
        q["status"] = status
    if category:
        q["category"] = category
    if branch:
        q["branch"] = branch
    if search:
        q["$or"] = [{"name": {"$regex": search, "$options": "i"}}, {"serial": {"$regex": search, "$options": "i"}},
                    {"category": {"$regex": search, "$options": "i"}}]
    rows = await get_db().equipment.find(q).sort("name", 1).to_list(limit)
    names = await service.project_name_map()
    return [service.view(r, names) for r in rows]


@router.post("/equipment", status_code=201)
async def create_equipment(body: EquipmentCreate, request: Request, user: dict = Depends(require_roles(*WRITE))):
    db = get_db()
    if await db.equipment.find_one({"serial": body.serial}):
        raise HTTPException(409, f"Serial number {body.serial} already exists")
    doc = {"_id": new_id(), **body.model_dump(), "current_job_id": None, "current_rental_id": None,
           "created_at": utcnow_iso()}
    await db.equipment.insert_one(doc)
    await log(user, "create", "equipment", doc["_id"], f"Added equipment {doc['name']} ({doc['serial']})", client_ip(request))
    return service.view(doc)


@router.get("/equipment/availability")
async def availability(
    date_from: str = Query(..., alias="from"), date_to: str = Query(..., alias="to"),
    category: Optional[str] = None, _: dict = Depends(require_roles(*READ)),
):
    """Which items are free for the whole window, plus the bookings that block the others."""
    from app.logic._util import to_date

    start, end = to_date(date_from), to_date(date_to)
    if not start or not end or end < start:
        raise HTTPException(422, "Provide a valid from/to date range")
    db = get_db()
    q: dict[str, Any] = {"category": category} if category else {}
    items = await db.equipment.find(q).sort("name", 1).to_list(1000)
    rentals = await db.rentals.find({"actual_return": None}).to_list(5000)
    by_item: dict[str, list] = {}
    for r in rentals:
        rs, re_ = to_date(r.get("start_date")), to_date(r.get("expected_return"))
        if rs and rs <= end and (re_ is None or re_ >= start):
            by_item.setdefault(r["equipment_id"], []).append(
                {"start": r["start_date"], "end": r.get("expected_return"), "project_id": r.get("project_id"), "rental_id": r["_id"]}
            )
    out = []
    for eq in items:
        reasons = [x for x in await service.readiness(eq, date_from, date_to) if not x.startswith("Equipment is already deployed")]
        bookings = by_item.get(eq["_id"], [])
        out.append({**service.view(eq), "free": not reasons and not bookings, "bookings": bookings, "blocking_reasons": reasons})
    return out


@router.get("/equipment/{equipment_id}")
async def get_equipment(equipment_id: str, _: dict = Depends(require_roles(*READ))):
    eq = await service.get_or_404(equipment_id)
    names = await service.project_name_map()
    v = service.view(eq, names)
    v["total_rental_income"] = await service.income_for(equipment_id)
    return v


@router.patch("/equipment/{equipment_id}")
async def update_equipment(equipment_id: str, body: EquipmentUpdate, request: Request, user: dict = Depends(require_roles(*WRITE))):
    await service.get_or_404(equipment_id)
    patch = body.model_dump(exclude_none=True)
    if not patch:
        raise HTTPException(422, "Nothing to update")
    await get_db().equipment.update_one({"_id": equipment_id}, {"$set": patch})
    await log(user, "update", "equipment", equipment_id, f"Updated equipment fields: {', '.join(patch)}", client_ip(request))
    return service.view(await service.get_or_404(equipment_id), await service.project_name_map())


@router.delete("/equipment/{equipment_id}")
async def delete_equipment(equipment_id: str, request: Request, user: dict = Depends(require_roles("md", "admin"))):
    eq = await service.get_or_404(equipment_id)
    if eq.get("status") == "deployed":
        raise HTTPException(409, "Cannot delete equipment that is currently deployed")
    await get_db().equipment.delete_one({"_id": equipment_id})
    await log(user, "delete", "equipment", equipment_id, f"Deleted equipment {eq['name']} ({eq['serial']})", client_ip(request))
    return {"ok": True}


@router.get("/equipment/{equipment_id}/qr")
async def equipment_qr(equipment_id: str, _: dict = Depends(require_roles(*READ))):
    """PNG QR code whose content is the equipment ID (what the scanner reads)."""
    await service.get_or_404(equipment_id)
    img = qrcode.make(equipment_id, box_size=10, border=2)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return Response(buf.getvalue(), media_type="image/png")


@router.get("/equipment/{equipment_id}/readiness")
async def equipment_readiness(equipment_id: str, start: Optional[str] = None, end: Optional[str] = None,
                              _: dict = Depends(require_roles(*READ))):
    """Right after a QR scan: green OK to deploy, or the exact reasons it cannot be."""
    eq = await service.get_or_404(equipment_id)
    reasons = await service.readiness(eq, start, end)
    names = await service.project_name_map()
    return {"ok": not reasons, "reasons": reasons, "equipment": service.view(eq, names)}


# ---- Check-out / check-in -------------------------------------------------------------------
@router.post("/equipment/{equipment_id}/checkout", status_code=201)
async def checkout(equipment_id: str, body: CheckoutIn, request: Request, user: dict = Depends(require_roles(*WRITE))):
    eq = await service.get_or_404(equipment_id)
    reasons = await service.readiness(eq, body.start_date, body.expected_return)
    if reasons:
        raise HTTPException(409, detail={"message": "Cannot deploy this equipment", "reasons": reasons})
    rental = await service.do_checkout(eq, body, user)
    proj = await get_db().projects.find_one({"_id": body.project_id}) if body.project_id else None
    where = proj["name"] if proj else "a site"
    await log(user, "check-out", "equipment", equipment_id,
              f"Checked out {eq['name']} to {where} (received by {body.receiver_name})", client_ip(request))
    await notify_roles(["md"], "Equipment deployed", f"{eq['name']} deployed at {where}", "/equipment/" + equipment_id)
    # Phase 8 hook: the same signing function creates the handover form PDF
    try:
        from app.modules.documents.handover import create_handover_document

        doc_id = await create_handover_document(eq, rental, user, request)
        if doc_id:
            await get_db().rentals.update_one({"_id": rental["_id"]}, {"$set": {"handover_document_id": doc_id}})
            rental["handover_document_id"] = doc_id
    except ImportError:
        pass
    return clean(rental)


@router.post("/equipment/{equipment_id}/checkin")
async def checkin(equipment_id: str, body: CheckinIn, request: Request, user: dict = Depends(require_roles(*WRITE))):
    eq = await service.get_or_404(equipment_id)
    result = await service.do_checkin(eq, body, user)
    await log(user, "check-in", "equipment", equipment_id,
              f"Checked in {eq['name']}; status now {result['new_status']}; income {result['rental']['income']:.0f}", client_ip(request))
    if result["new_status"] == "maintenance":
        await notify_roles(["md", "storekeeper"], "Equipment needs service", f"{eq['name']} returned and moved to maintenance", "/equipment/" + equipment_id)
    return result


@router.get("/equipment/{equipment_id}/rentals")
async def equipment_rentals(equipment_id: str, _: dict = Depends(require_roles(*READ))):
    rows = await get_db().rentals.find({"equipment_id": equipment_id}).sort("start_date", -1).to_list(500)
    return clean_many(rows)


@router.get("/rentals")
async def list_rentals(status: Optional[str] = Query(None, description="open | overdue | returned"),
                       project_id: Optional[str] = None, _: dict = Depends(require_roles(*READ))):
    if status == "overdue":
        return clean_many(await service.overdue_list())
    q: dict[str, Any] = {}
    if status == "open":
        q["actual_return"] = None
    elif status == "returned":
        q["actual_return"] = {"$ne": None}
    if project_id:
        q["project_id"] = project_id
    return clean_many(await get_db().rentals.find(q).sort("start_date", -1).to_list(1000))


# ---- Rental Requests & Seamless Approvals ---------------------------------------------------
@router.post("/rentals/requests", status_code=201)
async def create_rental_request(body: RentalRequestCreate, request: Request, user: dict = Depends(require_roles(*READ))):
    """Submits a rental request for an equipment unit. Notifies ops manager and MD."""
    db = get_db()
    eq = await service.get_or_404(body.equipment_id)
    proj = await db.projects.find_one({"_id": body.project_id}) if body.project_id else None
    client = await db.clients.find_one({"_id": body.client_id}) if body.client_id else None
    client_name = body.client_name or (client["name"] if client else (proj["client_name"] if proj else None))

    req_doc = {
        "_id": new_id(),
        **body.model_dump(),
        "client_name": client_name,
        "equipment_name": eq["name"],
        "equipment_serial": eq.get("serial"),
        "equipment_branch": eq.get("branch"),
        "project_name": proj["name"] if proj else None,
        "status": "pending_approval",
        "requested_by": {"id": user["id"], "name": user.get("name"), "role": user.get("role")},
        "created_at": utcnow_iso(),
    }
    await db.rental_requests.insert_one(req_doc)
    await log(user, "create", "rental_request", req_doc["_id"], f"Requested rental for {eq['name']} ({body.start_date} to {body.expected_return})", client_ip(request))
    await notify_roles(["md", "storekeeper", "admin"], "New Rental Request", f"{user.get('name')} requested {eq['name']} for {client_name or 'project'}", "/equipment")
    return clean(req_doc)


@router.get("/rentals/requests")
async def list_rental_requests(status: Optional[str] = Query(None, description="pending_approval | approved | rejected"), _: dict = Depends(require_roles(*READ))):
    """Lists rental requests."""
    db = get_db()
    q: dict[str, Any] = {}
    if isinstance(status, str) and status:
        q["status"] = status
    items = await db.rental_requests.find(q).sort("created_at", -1).to_list(500)
    return clean_many(items)


@router.post("/rentals/requests/{request_id}/decision")
async def decide_rental_request(request_id: str, body: RentalRequestDecision, request: Request, user: dict = Depends(require_roles(*WRITE))):
    """Approves or rejects a rental request.
    On approval, automatically executes check-out and deploys the equipment seamlessly."""
    db = get_db()
    req_doc = await db.rental_requests.find_one({"_id": request_id})
    if not req_doc:
        raise HTTPException(404, "Rental request not found")

    if req_doc.get("status") != "pending_approval":
        raise HTTPException(409, f"Request has already been {req_doc.get('status')}")

    if body.decision == "approve":
        eq = await service.get_or_404(req_doc["equipment_id"])
        # Check readiness
        reasons = await service.readiness(eq, req_doc["start_date"], req_doc["expected_return"])
        # Allow deployment if only reason is 'already deployed' on the same job
        real_blockers = [r for r in reasons if not r.startswith("Equipment is already deployed") or eq.get("status") != "available"]
        if real_blockers:
            raise HTTPException(409, detail={"message": "Cannot deploy this equipment", "reasons": real_blockers})

        checkout_in = CheckoutIn(
            client_id=req_doc.get("client_id"),
            project_id=req_doc.get("project_id"),
            rate_type=req_doc.get("rate_type", "daily"),
            rate=req_doc.get("daily_rate", 0),
            start_date=req_doc.get("start_date"),
            expected_return=req_doc.get("expected_return"),
            receiver_name=req_doc.get("receiver_name") or req_doc["requested_by"].get("name") or "Authorized Client Rep",
            condition={"status": "Good", "approved_rental": True},
        )
        rental = await service.do_checkout(eq, checkout_in, user)

        await db.rental_requests.update_one(
            {"_id": request_id},
            {
                "$set": {
                    "status": "approved",
                    "approved_by": {"id": user["id"], "name": user["name"], "at": utcnow_iso()},
                    "rental_id": rental["_id"],
                    "notes": body.notes or req_doc.get("notes"),
                }
            },
        )
        await log(user, "approve", "rental_request", request_id, f"Approved rental request for {eq['name']}; deployed to rental {rental['_id']}", client_ip(request))
        return {"ok": True, "status": "approved", "rental_id": rental["_id"]}

    # Reject
    await db.rental_requests.update_one(
        {"_id": request_id},
        {
            "$set": {
                "status": "rejected",
                "rejected_by": {"id": user["id"], "name": user["name"], "at": utcnow_iso()},
                "notes": body.notes,
            }
        },
    )
    await log(user, "reject", "rental_request", request_id, f"Rejected rental request: {body.notes or 'No reason provided'}", client_ip(request))
    return {"ok": True, "status": "rejected"}



# ---- Maintenance ----------------------------------------------------------------------------
@router.get("/maintenance")
async def list_maintenance(equipment_id: Optional[str] = None, status: Optional[str] = None,
                           _: dict = Depends(require_roles(*READ))):
    q: dict[str, Any] = {}
    if equipment_id:
        q["equipment_id"] = equipment_id
    if status:
        q["status"] = status
    return clean_many(await get_db().maintenance.find(q).sort("created_at", -1).to_list(500))


@router.post("/maintenance", status_code=201)
async def create_maintenance(body: MaintenanceCreate, request: Request, user: dict = Depends(require_roles(*WRITE))):
    eq = await service.get_or_404(body.equipment_id)
    db = get_db()
    doc = {"_id": new_id(), "equipment_id": eq["_id"], "equipment_name": eq["name"], "type": body.type,
           "description": body.description, "scheduled_date": body.scheduled_date or today().isoformat(),
           "cost": body.cost, "status": "open", "created_by": user["name"], "created_at": utcnow_iso()}
    await db.maintenance.insert_one(doc)
    if body.start_now:
        if eq.get("status") == "deployed":
            raise HTTPException(409, "Check the item in first, it is currently deployed")
        await db.equipment.update_one({"_id": eq["_id"]}, {"$set": {"status": "maintenance"}})
    await log(user, "create", "maintenance", doc["_id"], f"Opened {body.type} for {eq['name']}", client_ip(request))
    return clean(doc)


@router.patch("/maintenance/{maintenance_id}/complete")
async def complete_maintenance(maintenance_id: str, body: MaintenanceComplete, request: Request,
                               user: dict = Depends(require_roles(*WRITE))):
    db = get_db()
    m = await db.maintenance.find_one({"_id": maintenance_id})
    if not m:
        raise HTTPException(404, "Maintenance record not found")
    if m["status"] == "completed":
        raise HTTPException(409, "Already completed")
    eq = await service.get_or_404(m["equipment_id"])
    hours = body.hours_at_service if body.hours_at_service is not None else eq.get("run_hours", 0)
    await db.maintenance.update_one(
        {"_id": maintenance_id},
        {"$set": {"status": "completed", "completed_at": utcnow_iso(), "completed_by": user["name"],
                  "hours_at_service": hours, "notes": body.notes,
                  **({"cost": body.cost} if body.cost is not None else {})}},
    )
    patch: dict[str, Any] = {"last_service_hours": hours}  # resets the service counter
    if eq.get("status") == "maintenance":
        patch["status"] = "available"
    await db.equipment.update_one({"_id": eq["_id"]}, {"$set": patch})
    await log(user, "update", "maintenance", maintenance_id, f"Completed {m['type']} on {eq['name']} at {hours:.0f} h", client_ip(request))
    return clean(await db.maintenance.find_one({"_id": maintenance_id}))


# ---- Fuel logs ------------------------------------------------------------------------------
@router.get("/fuel-logs")
async def list_fuel(project_id: Optional[str] = None, equipment_id: Optional[str] = None,
                    _: dict = Depends(require_roles("md", "admin", "storekeeper", "supervisor", "finance"))):
    q: dict[str, Any] = {}
    if project_id:
        q["project_id"] = project_id
    if equipment_id:
        q["equipment_id"] = equipment_id
    rows = await get_db().fuel_logs.find(q).sort("date", -1).to_list(1000)
    return {"items": clean_many(rows), "total_cost": sum(float(r.get("cost") or 0) for r in rows),
            "total_litres": sum(float(r.get("litres") or 0) for r in rows)}


@router.post("/fuel-logs", status_code=201)
async def add_fuel(body: FuelLogCreate, request: Request, user: dict = Depends(require_roles("md", "admin", "storekeeper", "supervisor"))):
    eq = await service.get_or_404(body.equipment_id)
    project_id = body.project_id or eq.get("current_job_id")
    doc = {"_id": new_id(), **body.model_dump(), "project_id": project_id, "equipment_name": eq["name"],
           "date": body.date or today().isoformat(), "logged_by": user["name"], "created_at": utcnow_iso()}
    await get_db().fuel_logs.insert_one(doc)
    await log(user, "create", "fuel_log", doc["_id"], f"Logged {body.litres:.0f} L fuel for {eq['name']}", client_ip(request))
    return clean(doc)
