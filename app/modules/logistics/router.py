"""Logistics and Fleet router."""
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request

from app.core.common import clean, clean_many, new_id, today, utcnow_iso
from app.core.db import get_db
from app.core.deps import client_ip, get_current_user, require_roles
from app.modules.audit import log

from .schemas import FuelLogIn, TripCreate, TripUpdate, VehicleCreate, VehicleUpdate

ALL = ("md", "admin", "supervisor", "storekeeper", "finance", "hr")
OPS = ("md", "admin", "supervisor", "storekeeper")

router = APIRouter(tags=["logistics"], dependencies=[Depends(get_current_user)])


# ── Vehicles ──────────────────────────────────────────────────────────────────

@router.get("/vehicles")
async def list_vehicles(status: Optional[str] = None, branch: Optional[str] = None,
                         _: dict = Depends(require_roles(*ALL))):
    q: dict[str, Any] = {}
    if status:
        q["status"] = status
    if branch:
        q["branch"] = branch
    rows = await get_db().vehicles.find(q).sort("name", 1).to_list(200)
    return clean_many(rows)


@router.post("/vehicles", status_code=201)
async def create_vehicle(body: VehicleCreate, request: Request, user: dict = Depends(require_roles(*OPS))):
    db = get_db()
    if await db.vehicles.find_one({"plate": body.plate}):
        raise HTTPException(409, f"A vehicle with plate {body.plate} already exists")
    doc = {"_id": new_id(), **body.model_dump(), "created_by": user["name"], "created_at": utcnow_iso()}
    await db.vehicles.insert_one(doc)
    await log(user, "create", "vehicle", doc["_id"], f"Added vehicle {doc['name']} ({doc['plate']})", client_ip(request))
    return clean(doc)


@router.patch("/vehicles/{vehicle_id}")
async def update_vehicle(vehicle_id: str, body: VehicleUpdate, request: Request,
                          user: dict = Depends(require_roles(*OPS))):
    vehicle = await _vehicle_or_404(vehicle_id)
    patch = body.model_dump(exclude_none=True)
    if not patch:
        raise HTTPException(422, "Nothing to update")
    await get_db().vehicles.update_one({"_id": vehicle_id}, {"$set": patch})
    await log(user, "update", "vehicle", vehicle_id, f"Updated vehicle {vehicle['name']}", client_ip(request))
    return clean(await get_db().vehicles.find_one({"_id": vehicle_id}))


@router.delete("/vehicles/{vehicle_id}")
async def delete_vehicle(vehicle_id: str, request: Request, user: dict = Depends(require_roles("md", "admin"))):
    vehicle = await _vehicle_or_404(vehicle_id)
    if vehicle.get("status") == "in_use":
        raise HTTPException(409, "Cannot delete a vehicle that is in use")
    await get_db().vehicles.delete_one({"_id": vehicle_id})
    await log(user, "delete", "vehicle", vehicle_id, f"Deleted vehicle {vehicle['name']}", client_ip(request))
    return {"ok": True}


# ── Trips ─────────────────────────────────────────────────────────────────────

@router.get("/trips")
async def list_trips(status: Optional[str] = None, vehicle_id: Optional[str] = None,
                      project_id: Optional[str] = None, _: dict = Depends(require_roles(*ALL))):
    q: dict[str, Any] = {}
    if status:
        q["status"] = status
    if vehicle_id:
        q["vehicle_id"] = vehicle_id
    if project_id:
        q["project_id"] = project_id
    rows = await get_db().trips.find(q).sort("planned_date", -1).to_list(500)
    return clean_many(rows)


@router.post("/trips", status_code=201)
async def create_trip(body: TripCreate, request: Request, user: dict = Depends(require_roles(*OPS))):
    vehicle = await _vehicle_or_404(body.vehicle_id)
    if vehicle.get("status") == "in_use":
        raise HTTPException(409, f"Vehicle {vehicle['name']} is already in use")
    doc = {
        "_id": new_id(), **body.model_dump(),
        "vehicle_name": vehicle["name"], "plate": vehicle["plate"],
        "status": "planned", "planned_date": body.planned_date or today().isoformat(),
        "created_by": {"id": user["id"], "name": user["name"]}, "created_at": utcnow_iso(),
    }
    await get_db().trips.insert_one(doc)
    await log(user, "create", "trip", doc["_id"],
              f"Trip: {body.origin} → {body.destination} ({vehicle['name']})", client_ip(request))
    return clean(doc)


@router.patch("/trips/{trip_id}")
async def update_trip(trip_id: str, body: TripUpdate, request: Request,
                       user: dict = Depends(require_roles(*OPS))):
    trip = await _trip_or_404(trip_id)
    patch = body.model_dump(exclude_none=True)
    if not patch:
        raise HTTPException(422, "Nothing to update")

    new_status = patch.get("status")
    # Update vehicle status based on trip status
    if new_status == "in_progress":
        await get_db().vehicles.update_one({"_id": trip["vehicle_id"]}, {"$set": {"status": "in_use"}})
    elif new_status in ("completed", "cancelled"):
        await get_db().vehicles.update_one({"_id": trip["vehicle_id"]}, {"$set": {"status": "available"}})
        if new_status == "completed" and patch.get("odometer_start") and patch.get("odometer_end"):
            km = patch["odometer_end"] - patch["odometer_start"]
            patch["distance_km"] = km

    patch["updated_at"] = utcnow_iso()
    await get_db().trips.update_one({"_id": trip_id}, {"$set": patch})
    await log(user, "update", "trip", trip_id,
              f"Trip {trip['origin']}→{trip['destination']} → {new_status or 'updated'}", client_ip(request))
    return clean(await get_db().trips.find_one({"_id": trip_id}))


# ── Fuel logs ─────────────────────────────────────────────────────────────────

@router.get("/vehicle-fuel")
async def list_vehicle_fuel(vehicle_id: Optional[str] = None, _: dict = Depends(require_roles(*ALL))):
    q: dict[str, Any] = {}
    if vehicle_id:
        q["vehicle_id"] = vehicle_id
    rows = await get_db().vehicle_fuel.find(q).sort("date", -1).to_list(1000)
    total = sum(float(r.get("cost") or 0) for r in rows)
    return {"items": clean_many(rows), "total_cost": total}


@router.post("/vehicle-fuel", status_code=201)
async def log_vehicle_fuel(body: FuelLogIn, request: Request, user: dict = Depends(require_roles(*OPS))):
    vehicle = await _vehicle_or_404(body.vehicle_id)
    doc = {
        "_id": new_id(), **body.model_dump(),
        "vehicle_name": vehicle["name"], "plate": vehicle["plate"],
        "date": body.date or today().isoformat(),
        "logged_by": {"id": user["id"], "name": user["name"]},
        "created_at": utcnow_iso(),
    }
    await get_db().vehicle_fuel.insert_one(doc)
    await log(user, "create", "vehicle_fuel", doc["_id"],
              f"Fuel {body.litres:.0f}L ₦{body.cost:,.0f} for {vehicle['name']}", client_ip(request))
    return clean(doc)


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _vehicle_or_404(vehicle_id: str) -> dict[str, Any]:
    v = await get_db().vehicles.find_one({"_id": vehicle_id})
    if not v:
        raise HTTPException(404, "Vehicle not found")
    return v


async def _trip_or_404(trip_id: str) -> dict[str, Any]:
    t = await get_db().trips.find_one({"_id": trip_id})
    if not t:
        raise HTTPException(404, "Trip not found")
    return t
