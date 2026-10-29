"""Equipment business operations. Rules come from app.logic; this file adds the database work."""
from datetime import date
from typing import Any, Optional

from app.core.common import clean, new_id, today, utcnow_iso
from app.core.db import get_db
from app.logic import can_deploy, certificate_status, rental_income, service_hours_remaining
from app.logic.equipment import overdue_rentals


async def open_bookings(equipment_id: str) -> list[dict[str, Any]]:
    """Rentals of this item that have not been returned yet."""
    return await get_db().rentals.find({"equipment_id": equipment_id, "actual_return": None}).to_list(500)


async def readiness(equipment: dict[str, Any], start: Optional[str] = None, end: Optional[str] = None) -> list[str]:
    bookings = await open_bookings(equipment["_id"])
    return can_deploy(equipment, today(), bookings, start, end)


def view(eq: dict[str, Any], project_names: Optional[dict[str, str]] = None) -> dict[str, Any]:
    """API representation with computed fields (service progress, certificate colours)."""
    out = clean(eq)
    interval = float(eq.get("service_interval_hours") or 0)
    remaining = service_hours_remaining(eq)
    used = interval - remaining
    out["service_hours_remaining"] = round(remaining, 1)
    out["service_pct"] = round(min(100.0, max(0.0, 100.0 * used / interval)), 1) if interval else 0
    out["service_overdue"] = bool(interval and remaining <= 0)
    t = today()
    out["certificates"] = [
        {**c, "status": certificate_status(c.get("expiry_date"), t)} for c in eq.get("certificates") or []
    ]
    out["has_expired_certificate"] = any(c["status"] == "red" for c in out["certificates"])
    if project_names is not None:
        out["current_project_name"] = project_names.get(eq.get("current_job_id") or "")
    return out


async def project_name_map() -> dict[str, str]:
    rows = await get_db().projects.find({}, {"name": 1}).to_list(1000)
    return {r["_id"]: r["name"] for r in rows}


async def get_or_404(equipment_id: str) -> dict[str, Any]:
    from fastapi import HTTPException

    eq = await get_db().equipment.find_one({"_id": equipment_id})
    if not eq:
        raise HTTPException(404, "Equipment not found")
    return eq


async def do_checkout(eq: dict[str, Any], body: Any, user: dict[str, Any]) -> dict[str, Any]:
    """Create the rental and flip the status to deployed. Caller has already checked readiness."""
    db = get_db()
    start = body.start_date or today().isoformat()
    rental = {
        "_id": new_id(), "equipment_id": eq["_id"], "equipment_name": eq["name"],
        "client_id": body.client_id, "project_id": body.project_id,
        "rate_type": body.rate_type, "rate": body.rate, "start_date": start,
        "expected_return": body.expected_return, "actual_return": None, "income": 0.0,
        "receiver_name": body.receiver_name, "condition_out": body.condition,
        "handover_photos": body.handover_photos, "signature_url": body.signature_url,
        "issued_by": {"id": user["id"], "name": user["name"]}, "created_at": utcnow_iso(),
        "run_hours_out": eq.get("run_hours", 0),
    }
    await db.rentals.insert_one(rental)
    await db.equipment.update_one(
        {"_id": eq["_id"]},
        {"$set": {"status": "deployed", "current_job_id": body.project_id, "current_rental_id": rental["_id"]}},
    )
    return rental


async def do_checkin(eq: dict[str, Any], body: Any, user: dict[str, Any]) -> dict[str, Any]:
    from fastapi import HTTPException

    db = get_db()
    rental = await db.rentals.find_one({"_id": eq.get("current_rental_id")}) if eq.get("current_rental_id") else None
    if not rental:
        rental = await db.rentals.find_one({"equipment_id": eq["_id"], "actual_return": None})
    if not rental:
        raise HTTPException(409, "This item has no open rental to check in")
    returned = today().isoformat()
    income = rental_income(rental["rate_type"], rental["rate"], rental["start_date"], returned)
    new_hours = body.return_hours if body.return_hours is not None else eq.get("run_hours", 0)
    if new_hours < float(eq.get("run_hours") or 0):
        raise HTTPException(422, f"Return hours ({new_hours}) cannot be lower than the current meter ({eq.get('run_hours', 0)})")
    interval = float(eq.get("service_interval_hours") or 0)
    due_for_service = bool(interval and (new_hours - float(eq.get("last_service_hours") or 0)) >= interval)
    new_status = "maintenance" if (body.flag_for_maintenance or due_for_service) else "available"
    await db.rentals.update_one(
        {"_id": rental["_id"]},
        {"$set": {"actual_return": returned, "income": income, "condition_in": body.condition,
                  "return_photos": body.photos, "return_signature_url": body.signature_url,
                  "returned_by": body.returned_by, "run_hours_in": new_hours,
                  "received_by": {"id": user["id"], "name": user["name"]}}},
    )
    await db.equipment.update_one(
        {"_id": eq["_id"]},
        {"$set": {"status": new_status, "run_hours": new_hours, "current_job_id": None, "current_rental_id": None}},
    )
    rental.update({"actual_return": returned, "income": income})
    return {"rental": clean(rental), "new_status": new_status, "service_due": due_for_service}


async def income_for(equipment_id: str) -> float:
    rows = await get_db().rentals.find({"equipment_id": equipment_id}).to_list(5000)
    return round(sum(float(r.get("income") or 0) for r in rows), 2)


async def overdue_list() -> list[dict[str, Any]]:
    open_rentals = await get_db().rentals.find({"actual_return": None}).to_list(5000)
    return overdue_rentals(open_rentals, today())
