from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.core.common import clean, clean_many, new_id, today, utcnow_iso
from app.core.config import get_settings
from app.core.db import get_db
from app.core.deps import client_ip, get_current_user, require_roles
from app.logic import can_assign, payroll_days
from app.modules.audit import log
from app.modules.notifications import notify_roles

from . import service
from .schemas import (
    AssignmentIn,
    CertsUpdate,
    FaceDecisionIn,
    FaceRegisterIn,
    SiteIn,
    SiteUpdate,
    StaffCreate,
    StaffUpdate,
)

router = APIRouter(tags=["staff"], dependencies=[Depends(get_current_user)])
ALL = ("md", "admin", "finance", "supervisor", "storekeeper", "hr", "branch_manager")
PEOPLE = ("md", "admin", "hr", "supervisor", "branch_manager")


# ---- Staff ----------------------------------------------------------------------------------
@router.get("/staff")
async def list_staff(branch: Optional[str] = None, _: dict = Depends(require_roles(*PEOPLE))):
    rows = await get_db().staff.find({"branch": branch} if branch else {}).sort("name", 1).to_list(2000)
    return [service.public_staff(r) for r in rows]


@router.post("/staff", status_code=201)
async def create_staff(body: StaffCreate, request: Request, user: dict = Depends(require_roles("md", "admin", "hr", "branch_manager"))):
    doc = {"_id": new_id(), **body.model_dump(), "face_template": [], "face_consent": {"given": False, "date": None},
           "face_status": "none", "certifications": [], "created_at": utcnow_iso()}
    await get_db().staff.insert_one(doc)
    await log(user, "create", "staff", doc["_id"], f"Created staff profile {body.name}", client_ip(request))
    return service.public_staff(doc)


# ---- Certifications (declared before /staff/{staff_id} so path doesn't get shadowed) ---------
@router.get("/staff/certifications")
async def cert_matrix(branch: Optional[str] = None, _: dict = Depends(require_roles(*PEOPLE))):
    rows = await get_db().staff.find({"branch": branch} if branch else {}).sort("name", 1).to_list(2000)
    return [{"id": r["_id"], "name": r["name"], "position": r.get("position"), "branch": r.get("branch"), "certs": service.cert_matrix_row(r)} for r in rows]


@router.get("/staff/{staff_id}")
async def get_staff_detail(staff_id: str, _: dict = Depends(require_roles(*PEOPLE))):
    db = get_db()
    s = await db.staff.find_one({"_id": staff_id})
    if not s:
        raise HTTPException(404, "Staff not found")
    out = service.public_staff(s)
    t = today()
    out["certifications_detailed"] = [
        {**c, "status": certificate_status(c.get("expiry"), t)}
        for c in s.get("certifications", [])
    ]
    out["recent_attendance"] = clean_many(
        await db.attendance.find({"staff_id": staff_id}).sort("date", -1).limit(30).to_list(30)
    )
    out["assignments"] = clean_many(
        await db.assignments.find({"staff_id": staff_id}).sort("start", -1).limit(10).to_list(10)
    )
    return out


@router.patch("/staff/{staff_id}")
async def update_staff(
    staff_id: str,
    body: StaffUpdate,
    request: Request,
    user: dict = Depends(require_roles("md", "admin", "hr", "branch_manager")),
):
    db = get_db()
    s = await db.staff.find_one({"_id": staff_id})
    if not s:
        raise HTTPException(404, "Staff not found")
    patch = body.model_dump(exclude_none=True)
    if not patch:
        raise HTTPException(422, "Nothing to update")
    await db.staff.update_one({"_id": staff_id}, {"$set": patch})
    await log(user, "update", "staff", staff_id, f"Updated staff {s['name']}: {', '.join(patch)}", client_ip(request))
    return service.public_staff(await db.staff.find_one({"_id": staff_id}))


@router.delete("/staff/{staff_id}")
async def delete_staff(
    staff_id: str,
    request: Request,
    user: dict = Depends(require_roles("md", "admin", "hr")),
):
    db = get_db()
    s = await db.staff.find_one({"_id": staff_id})
    if not s:
        raise HTTPException(404, "Staff not found")
    await db.staff.update_one({"_id": staff_id}, {"$set": {"active": False, "deleted_at": utcnow_iso()}})
    await log(user, "delete", "staff", staff_id, f"Deactivated staff {s['name']}", client_ip(request))
    return {"ok": True, "message": f"Staff profile {s['name']} deactivated"}


@router.get("/staff/me")
async def me(user: dict = Depends(get_current_user)):
    s = await service.my_staff(user)
    out = service.public_staff(s)
    out["sites"] = [{"name": x["name"], "lat": x["lat"], "lng": x["lng"], "radius_m": x["radius_m"]} for x in await service.candidate_sites(s)]
    t = today().isoformat()
    rec = await get_db().attendance.find_one({"staff_id": s["_id"], "date": t})
    out["today"] = clean(rec) if rec else None
    out["face_threshold"] = get_settings().face_threshold
    return out


@router.post("/staff/me/face")
async def register_face(body: FaceRegisterIn, request: Request, user: dict = Depends(get_current_user)):
    """Store descriptors ONLY (never photos), with explicit consent. HR must approve before they are used."""
    if not body.consent:
        raise HTTPException(422, "Explicit consent is required to register your face (NDPA 2023)")
    if len(body.descriptors) != 3 or any(len(d) != 128 for d in body.descriptors):
        raise HTTPException(422, "Provide exactly 3 face descriptors of 128 numbers each")
    s = await service.my_staff(user)
    await get_db().staff.update_one({"_id": s["_id"]}, {"$set": {"face_template": body.descriptors, "face_status": "pending",
                                    "face_consent": {"given": True, "date": utcnow_iso(), "purpose": "Attendance verification only"}}})
    await log(user, "create", "staff", s["_id"], f"{s['name']} registered face (consent given), awaiting HR approval", client_ip(request))
    await notify_roles(["hr"], "Face registration to approve", f"{s['name']} registered their face for attendance", "/staff")
    return {"status": "pending", "message": "Saved. HR will approve your registration."}


@router.delete("/staff/me/face")
async def withdraw_face(request: Request, user: dict = Depends(get_current_user)):
    """Right to withdraw: deletes the stored descriptors."""
    s = await service.my_staff(user)
    await get_db().staff.update_one({"_id": s["_id"]}, {"$set": {"face_template": [], "face_status": "none", "face_consent": {"given": False, "date": None}}})
    await log(user, "update", "staff", s["_id"], f"{s['name']} withdrew face consent, descriptors deleted", client_ip(request))
    return {"ok": True}


@router.post("/staff/{staff_id}/face/decision")
async def decide_face(staff_id: str, body: FaceDecisionIn, request: Request, user: dict = Depends(require_roles("hr", "admin"))):
    db = get_db()
    s = await db.staff.find_one({"_id": staff_id})
    if not s:
        raise HTTPException(404, "Staff not found")
    if s.get("face_status") != "pending":
        raise HTTPException(409, "No registration waiting for approval")
    approve = body.decision == "approve"
    patch: dict[str, Any] = {"face_status": "approved" if approve else "rejected"}
    if not approve:
        patch["face_template"] = []
    await db.staff.update_one({"_id": staff_id}, {"$set": patch})
    await log(user, "approve" if approve else "reject", "staff", staff_id, f"Face registration for {s['name']} {patch['face_status']}", client_ip(request))
    if s.get("user_id"):
        from app.modules.notifications import notify

        await notify([s["user_id"]], f"Face registration {patch['face_status']}", body.comment or "", "/attendance")
    return service.public_staff(await db.staff.find_one({"_id": staff_id}))


# ---- Update Certifications ------------------------------------------------------------------
@router.put("/staff/{staff_id}/certifications")
async def set_certs(staff_id: str, body: CertsUpdate, request: Request, user: dict = Depends(require_roles("hr", "admin"))):
    res = await get_db().staff.update_one({"_id": staff_id}, {"$set": {"certifications": [c.model_dump() for c in body.certifications]}})
    if res.matched_count == 0:
        raise HTTPException(404, "Staff not found")
    await log(user, "update", "staff", staff_id, "Updated certifications", client_ip(request))
    return {"ok": True}


# ---- Sites ----------------------------------------------------------------------------------
@router.get("/sites")
async def list_sites(_: dict = Depends(require_roles(*ALL))):
    return clean_many(await get_db().sites.find({}).sort("name", 1).to_list(200))


@router.post("/sites", status_code=201)
async def create_site(body: SiteIn, request: Request, user: dict = Depends(require_roles(*PEOPLE))):
    doc = {"_id": new_id(), **body.model_dump(), "created_at": utcnow_iso()}
    await get_db().sites.insert_one(doc)
    await log(user, "create", "site", doc["_id"], f"Added site {body.name} (radius {body.radius_m:.0f} m)", client_ip(request))
    return clean(doc)


@router.patch("/sites/{site_id}")
async def update_site(site_id: str, body: SiteUpdate, request: Request, user: dict = Depends(require_roles(*PEOPLE))):
    patch = body.model_dump(exclude_none=True)
    patch["updated_at"] = utcnow_iso()
    res = await get_db().sites.update_one({"_id": site_id}, {"$set": patch})
    if res.matched_count == 0:
        raise HTTPException(404, "Site not found")
    await log(user, "update", "site", site_id, f"Updated site: {', '.join(patch)}", client_ip(request))
    return clean(await get_db().sites.find_one({"_id": site_id}))


@router.delete("/sites/{site_id}")
async def delete_site(site_id: str, request: Request, user: dict = Depends(require_roles(*PEOPLE))):
    res = await get_db().sites.delete_one({"_id": site_id})
    if res.deleted_count == 0:
        raise HTTPException(404, "Site not found")
    await log(user, "delete", "site", site_id, "Deleted site", client_ip(request))
    return {"ok": True}


# ---- Assignments ----------------------------------------------------------------------------
@router.get("/assignments")
async def list_assignments(project_id: Optional[str] = None, staff_id: Optional[str] = None, _: dict = Depends(require_roles(*PEOPLE))):
    q = {k: v for k, v in {"project_id": project_id, "staff_id": staff_id}.items() if v}
    return clean_many(await get_db().assignments.find(q).sort("created_at", -1).to_list(1000))


@router.post("/assignments", status_code=201)
async def assign(body: AssignmentIn, request: Request, user: dict = Depends(require_roles(*PEOPLE))):
    db = get_db()
    s = await db.staff.find_one({"_id": body.staff_id})
    p = await db.projects.find_one({"_id": body.project_id})
    if not s or not p:
        raise HTTPException(422, "Unknown staff member or project")
    ok, reasons = can_assign(s, body.required_certs, today())
    if not ok:
        await log(user, "reject", "assignment", None, f"Assignment of {s['name']} to {p['name']} refused: {'; '.join(reasons)}", client_ip(request))
        raise HTTPException(409, detail={"message": f"{s['name']} cannot be assigned", "reasons": reasons})
    doc = {"_id": new_id(), "staff_id": s["_id"], "staff_name": s["name"], "project_id": p["_id"], "project_name": p["name"], "role": body.role,
           "required_certs": body.required_certs, "start": body.start or today().isoformat(), "end": body.end, "created_by": user["name"], "created_at": utcnow_iso()}
    await db.assignments.insert_one(doc)
    await log(user, "create", "assignment", doc["_id"], f"Assigned {s['name']} to {p['name']}", client_ip(request))
    return clean(doc)


# ---- Payroll (figures only; verified attendance only) ---------------------------------------
@router.get("/payroll/summary")
async def payroll_summary(month: str = Query(..., pattern=r"^\d{4}-\d{2}$"), _: dict = Depends(require_roles("md", "admin", "finance", "hr"))):
    db = get_db()
    att = await db.attendance.find({"date": {"$regex": f"^{month}"}}).to_list(50000)
    days = payroll_days(att, month)
    staff = {s["_id"]: s for s in await db.staff.find({}).to_list(5000)}
    rows, total = [], 0.0
    for sid, n in sorted(days.items(), key=lambda kv: staff.get(kv[0], {}).get("name", "")):
        s = staff.get(sid)
        if not s:
            continue
        gross = n * float(s.get("daily_rate") or 0)
        total += gross
        unverified = sum(1 for a in att if a["staff_id"] == sid and a.get("status") != "verified")
        rows.append({"staff_id": sid, "name": s["name"], "branch": s.get("branch"), "days_present": n, "daily_rate": s.get("daily_rate"),
                     "gross": gross, "unverified_days_excluded": unverified})
    return {"month": month, "rows": rows, "total_gross": total,
            "note": "Counts VERIFIED attendance only. PAYE, WHT and pension are tracked by finance as figures, this is not tax advice."}
