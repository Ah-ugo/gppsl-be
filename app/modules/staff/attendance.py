"""Selfie + GPS attendance. A failed face match NEVER auto-penalises: it is flagged for supervisor review."""
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response

from app.core.common import clean, clean_many, new_id, today, utcnow, utcnow_iso
from app.core.db import get_db
from app.core.deps import client_ip, get_current_user, require_roles
from app.modules.audit import log
from app.modules.notifications import notify, notify_roles

from pydantic import BaseModel, Field

from . import service
from .schemas import ClockIn, ManualIn, ReviewIn

router = APIRouter(tags=["attendance"], dependencies=[Depends(get_current_user)])
ALL = ("md", "admin", "finance", "supervisor", "storekeeper", "hr", "branch_manager")
SUPERVISE = ("md", "admin", "hr", "supervisor", "branch_manager")


class RosterWorkerItem(BaseModel):
    staff_id: str
    status: str = "verified"  # verified (present), absent, on_leave, late
    notes: Optional[str] = None


class RosterCheckIn(BaseModel):
    date: Optional[str] = None
    branch: str
    site_name: Optional[str] = None
    supervisor_note: Optional[str] = None
    workers: list[RosterWorkerItem]


def card(staff: dict[str, Any], rec: dict[str, Any], ev_doc: dict[str, Any], status: str, flags: list[str], duplicate: bool = False) -> dict[str, Any]:
    return {"ok": True, "duplicate": duplicate, "status": status, "flags": flags,
            "greeting": f"{service.greeting_for(ev_doc.get('local_time'))}, {staff['name']}", "name": staff["name"],
            "site_name": ev_doc.get("site_name"), "distance_m": ev_doc.get("distance_m"), "time": ev_doc.get("local_time") or ev_doc.get("time"),
            "selfie_url": ev_doc.get("selfie_url"), "match_score": ev_doc.get("match_score"), "record_id": rec["_id"]}


@router.post("/attendance/clock-in", status_code=201)
async def clock_in(body: ClockIn, request: Request, response: Response, user: dict = Depends(get_current_user)):
    db = get_db()
    staff = await service.my_staff(user)
    dup = await db.attendance.find_one({"staff_id": staff["_id"], "clock_in.client_id": body.id})
    if dup:  # offline retry of something we already stored: same answer, no second record
        response.status_code = 200
        return card(staff, dup, dup["clock_in"], dup["status"], dup["clock_in"]["flags"], duplicate=True)
    server_time = utcnow()
    ev = await service.evaluate(staff, body, server_time)
    day = service.lagos(ev["phone_time"]).date().isoformat() if ev["phone_time"] else today().isoformat()
    existing = await db.attendance.find_one({"staff_id": staff["_id"], "date": day})
    if existing and existing.get("clock_in"):
        raise HTTPException(409, "You have already clocked in today")
    doc_ci = service.event_doc(body, ev, server_time)
    status = "flagged" if ev["flags"] else "verified"
    rec = {"_id": new_id(), "staff_id": staff["_id"], "staff_name": staff["name"], "branch": staff.get("branch"), "date": day,
           "clock_in": doc_ci, "clock_out": None, "status": status, "review": None, "created_at": utcnow_iso()}
    await db.attendance.insert_one(rec)
    await log(user, "clock-in", "attendance", rec["_id"],
              f"{staff['name']} clocked in at {doc_ci['site_name'] or 'unknown site'} ({status}{': ' + ', '.join(ev['flags']) if ev['flags'] else ''})"
              + (" [synced from offline]" if body.offline else ""), client_ip(request))
    if ev["flags"]:
        await notify_roles(["supervisor"], "Clock-in needs review", f"{staff['name']}: {', '.join(ev['flags'])}", "/attendance")
    return card(staff, rec, doc_ci, status, ev["flags"])


@router.post("/attendance/clock-out", status_code=201)
async def clock_out(body: ClockIn, request: Request, response: Response, user: dict = Depends(get_current_user)):
    db = get_db()
    staff = await service.my_staff(user)
    dup = await db.attendance.find_one({"staff_id": staff["_id"], "clock_out.client_id": body.id})
    if dup:
        response.status_code = 200
        return card(staff, dup, dup["clock_out"], dup["status"], dup["clock_out"]["flags"], duplicate=True)
    server_time = utcnow()
    ev = await service.evaluate(staff, body, server_time)
    day = service.lagos(ev["phone_time"]).date().isoformat() if ev["phone_time"] else today().isoformat()
    rec = await db.attendance.find_one({"staff_id": staff["_id"], "date": day})
    if not rec or not rec.get("clock_in"):
        raise HTTPException(409, "You have not clocked in today")
    if rec.get("clock_out"):
        raise HTTPException(409, "You have already clocked out today")
    doc_co = service.event_doc(body, ev, server_time)
    patch: dict[str, Any] = {"clock_out": doc_co}
    if ev["flags"] and rec["status"] == "verified":
        patch["status"] = "flagged"  # clock-out problems also go to review
    await db.attendance.update_one({"_id": rec["_id"]}, {"$set": patch})
    status = patch.get("status", rec["status"])
    await log(user, "clock-out", "attendance", rec["_id"], f"{staff['name']} clocked out ({status})" + (" [synced from offline]" if body.offline else ""), client_ip(request))
    return card(staff, rec, doc_co, status, ev["flags"])


@router.get("/attendance/mine")
async def mine(user: dict = Depends(get_current_user)):
    s = await service.my_staff(user)
    rows = await get_db().attendance.find({"staff_id": s["_id"]}).sort("date", -1).limit(31).to_list(31)
    return clean_many(rows)


@router.get("/attendance/today")
async def live(branch: Optional[str] = None, _: dict = Depends(require_roles(*SUPERVISE))):
    """Live board: who is in, late, absent, flagged, with selfie thumbnails."""
    db = get_db()
    t = today().isoformat()
    hour, grace = await service.shift_cfg()
    staff = await db.staff.find({"branch": branch} if branch else {}).sort("name", 1).to_list(5000)
    recs = {r["staff_id"]: r for r in await db.attendance.find({"date": t}).to_list(5000)}
    rows = []
    for s in staff:
        r = recs.get(s["_id"])
        if r and r.get("clock_in") and r["status"] != "rejected":
            late = service.is_record_late(r, hour, grace)
            state = "flagged" if r["status"] == "flagged" else "late" if late else "present"
        else:
            state = "absent"
        rows.append({"staff_id": s["_id"], "name": s["name"], "position": s.get("position"), "branch": s.get("branch"), "state": state,
                     "record_id": r["_id"] if r else None, "clock_in": r.get("clock_in") if r else None, "clock_out": r.get("clock_out") if r else None,
                     "status": r["status"] if r else None})
    summary = {k: sum(1 for x in rows if x["state"] == k) for k in ("present", "late", "absent", "flagged")}
    summary["in_total"] = summary["present"] + summary["late"] + summary["flagged"]
    return {"date": t, "summary": summary, "rows": rows}


@router.get("/attendance/flagged")
async def flagged(_: dict = Depends(require_roles(*SUPERVISE))):
    rows = await get_db().attendance.find({"status": "flagged"}).sort("date", -1).to_list(500)
    return clean_many(rows)


@router.post("/attendance/{record_id}/review")
async def review(record_id: str, body: ReviewIn, request: Request, user: dict = Depends(require_roles(*SUPERVISE))):
    db = get_db()
    rec = await db.attendance.find_one({"_id": record_id})
    if not rec:
        raise HTTPException(404, "Record not found")
    if rec["status"] != "flagged":
        raise HTTPException(409, f"Record is already {rec['status']}")
    if body.decision == "reject" and not (body.comment or "").strip():
        raise HTTPException(422, "Please give a reason when rejecting")
    status = "verified" if body.decision == "approve" else "rejected"
    await db.attendance.update_one({"_id": record_id}, {"$set": {"status": status, "review": {"by": user["name"], "decision": body.decision, "comment": body.comment, "at": utcnow_iso()}}})
    await log(user, "review", "attendance", record_id, f"{user['name']} {body.decision}d clock-in of {rec['staff_name']} ({', '.join(rec['clock_in']['flags'])})", client_ip(request))
    staff = await db.staff.find_one({"_id": rec["staff_id"]})
    if staff and staff.get("user_id"):
        await notify([staff["user_id"]], f"Attendance {status}", body.comment or f"Your clock-in on {rec['date']} was {status}", "/attendance")
    return clean(await db.attendance.find_one({"_id": record_id}))


@router.post("/attendance/manual", status_code=201)
async def manual(body: ManualIn, request: Request, user: dict = Depends(require_roles(*SUPERVISE))):
    """Emergency manual clock-in by a supervisor. Recorded as source=manual with the supervisor's name."""
    db = get_db()
    staff = await db.staff.find_one({"_id": body.staff_id})
    if not staff:
        raise HTTPException(404, "Staff not found")
    now = service.to_datetime(body.time) if body.time else utcnow()
    day = service.lagos(now).date().isoformat()
    if await db.attendance.find_one({"staff_id": staff["_id"], "date": day, "clock_in": {"$ne": None}}):
        raise HTTPException(409, "Already clocked in on that day")
    ci = {"time": now.isoformat(), "local_time": service.lagos(now).replace(tzinfo=None).isoformat(), "server_time": utcnow_iso(), "lat": None, "lng": None,
          "accuracy": None, "selfie_url": None, "match_score": None, "flags": [], "source": "manual", "manual_by": user["name"], "note": body.note,
          "site_name": None, "distance_m": None, "client_id": new_id(), "offline": False}
    rec = {"_id": new_id(), "staff_id": staff["_id"], "staff_name": staff["name"], "branch": staff.get("branch"), "date": day, "clock_in": ci,
           "clock_out": None, "status": "verified", "review": None, "created_at": utcnow_iso()}
    await db.attendance.insert_one(rec)
    await log(user, "clock-in", "attendance", rec["_id"], f"MANUAL clock-in of {staff['name']} by {user['name']}: {body.note}", client_ip(request))
    return clean(rec)


@router.get("/attendance")
async def history(staff_id: Optional[str] = None, month: Optional[str] = Query(None, pattern=r"^\d{4}-\d{2}$"), status: Optional[str] = None,
                  _: dict = Depends(require_roles(*SUPERVISE))):
    q: dict[str, Any] = {}
    if staff_id:
        q["staff_id"] = staff_id
    if month:
        q["date"] = {"$regex": f"^{month}"}
    if status:
        q["status"] = status
    return clean_many(await get_db().attendance.find(q).sort("date", -1).to_list(3000))


@router.post("/attendance/roster-checkin", status_code=201)
async def roster_checkin(body: RosterCheckIn, request: Request, user: dict = Depends(require_roles(*SUPERVISE))):
    """Supervisor shift check-in for cleaners, yard workers, drivers, and field staff without individual app accounts."""
    db = get_db()
    day = body.date or today().isoformat()
    updated_records = []
    for item in body.workers:
        s = await db.staff.find_one({"_id": item.staff_id})
        if not s:
            continue
        existing = await db.attendance.find_one({"staff_id": item.staff_id, "date": day})
        status_val = "verified" if item.status in ("verified", "present") else item.status
        is_attending = status_val in ("verified", "late")

        doc_event = {
            "time": utcnow_iso(),
            "local_time": utcnow_iso(),
            "site_name": body.site_name or s.get("branch") or body.branch,
            "distance_m": 0.0,
            "match_score": 1.0,
            "selfie_url": None,
            "flags": [],
            "verified_by": f"{user['name']} ({user['role']})",
            "method": "supervisor_roster",
            "notes": item.notes or body.supervisor_note,
        }

        if existing:
            patch = {
                "status": status_val,
                "clock_in": doc_event if is_attending else None,
                "supervisor_review": {
                    "by": user["name"],
                    "role": user["role"],
                    "at": utcnow_iso(),
                    "note": body.supervisor_note,
                },
            }
            await db.attendance.update_one({"_id": existing["_id"]}, {"$set": patch})
            updated_records.append(str(existing["_id"]))
        else:
            rec = {
                "_id": new_id(),
                "staff_id": s["_id"],
                "staff_name": s["name"],
                "branch": s.get("branch") or body.branch,
                "department": s.get("department") or "General Services",
                "employment_type": s.get("employment_type") or "cleaner",
                "date": day,
                "clock_in": doc_event if is_attending else None,
                "clock_out": None,
                "status": status_val,
                "review": None,
                "supervisor_note": body.supervisor_note,
                "created_at": utcnow_iso(),
            }
            await db.attendance.insert_one(rec)
            updated_records.append(rec["_id"])

    await log(
        user,
        "roster-checkin",
        "attendance",
        body.branch,
        f"{user['name']} submitted roster attendance for {len(updated_records)} workers at {body.branch} ({day}): {body.supervisor_note or 'Shift attendance verified'}",
        client_ip(request),
    )
    return {
        "ok": True,
        "date": day,
        "branch": body.branch,
        "processed_count": len(updated_records),
        "message": f"Recorded attendance for {len(updated_records)} workers",
    }
