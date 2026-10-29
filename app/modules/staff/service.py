"""Staff, sites, assignments, attendance rules wired to the pure logic layer."""
from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

from fastapi import HTTPException

from app.core.common import clean, new_id, today, utcnow, utcnow_iso
from app.core.config import get_settings
from app.core.db import get_db
from app.core.settings_store import get_settings_doc
from app.logic import attendance_flags, face_match, geofence_check, is_late
from app.logic._util import naive_utc, to_datetime
from app.logic.attendance import nearest_site
from app.logic.certs import certificate_status


def lagos(dt: datetime) -> datetime:
    """Aware datetime in Africa/Lagos (naive input is assumed UTC)."""
    if dt.tzinfo is None:
        from datetime import timezone
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(ZoneInfo(get_settings().timezone))


def public_staff(s: dict[str, Any], include_templates: bool = False) -> dict[str, Any]:
    out = clean(s)
    out["face_registered"] = bool(s.get("face_template"))
    if "branch_access" not in out or not out["branch_access"]:
        out["branch_access"] = ["all"]
    if not include_templates:
        out.pop("face_template", None)  # biometric descriptors never leave the server in lists
        out.pop("face_pending", None)
    return out


async def my_staff(user: dict[str, Any]) -> dict[str, Any]:
    s = await get_db().staff.find_one({"user_id": user["id"]})
    if not s:
        raise HTTPException(404, "No staff profile is linked to your account. Ask HR to create one.")
    return s


async def candidate_sites(staff: dict[str, Any]) -> list[dict[str, Any]]:
    """Sites in the person's branch, plus the location of projects they are currently assigned to."""
    db = get_db()
    sites = await db.sites.find({"branch": staff.get("branch")}).to_list(100)
    t = today().isoformat()
    for a in await db.assignments.find({"staff_id": staff["_id"]}).to_list(200):
        if a.get("end") and a["end"] < t:
            continue
        p = await db.projects.find_one({"_id": a["project_id"]})
        if p and p.get("coordinates"):
            sites.append({"name": p["name"], "lat": p["coordinates"]["lat"], "lng": p["coordinates"]["lng"], "radius_m": 300})
    return sites or await db.sites.find({}).to_list(100)


async def last_fix(staff_id: str) -> Optional[dict[str, Any]]:
    rec = await get_db().attendance.find({"staff_id": staff_id}).sort("date", -1).limit(1).to_list(1)
    if not rec:
        return None
    ci = rec[0].get("clock_out") or rec[0].get("clock_in") or {}
    if ci.get("lat") is None:
        return None
    return {"lat": ci["lat"], "lng": ci["lng"], "time": ci.get("time")}


async def evaluate(staff: dict[str, Any], body: Any, server_time: datetime) -> dict[str, Any]:
    """Run face match + geofence + flag rules for one clock event."""
    try:
        phone_time = to_datetime(body.phone_time)
    except ValueError:
        raise HTTPException(422, "phone_time must be an ISO date-time")
    templates = staff.get("face_template") if staff.get("face_status") == "approved" else []
    flags: list[str] = []
    matched: Optional[bool] = None
    score: Optional[float] = None
    if templates:
        if body.descriptor:
            matched, score = face_match(body.descriptor, templates, get_settings().face_threshold)
        else:
            matched = False  # a selfie with no usable face counts as a failed match, goes to review
    else:
        flags.append("no_face_template")  # not registered/approved yet: supervisor reviews instead
    geo = {"inside": True, "distance_m": None, "flags": []}
    site_name = None
    if body.lat is not None and body.lng is not None:
        near = nearest_site(body.lat, body.lng, await candidate_sites(staff))
        if near:
            site, _ = near
            geo = geofence_check(body.lat, body.lng, body.accuracy, site, await last_fix(staff["_id"]), phone_time)
            site_name = site["name"]
    else:
        geo = {"inside": False, "distance_m": None, "flags": ["poor_gps_accuracy"]}
    base = attendance_flags({"face_matched": matched, "inside": geo["inside"], "geo_flags": geo["flags"], "phone_time": phone_time},
                            server_time, None, offline=body.offline)
    if not body.liveness:
        base.append("liveness_failed")
    flags += base
    return {"flags": flags, "match_score": score, "site_name": site_name, "distance_m": geo["distance_m"], "inside": geo["inside"],
            "phone_time": phone_time}


def event_doc(body: Any, ev: dict[str, Any], server_time: datetime, source: str = "self") -> dict[str, Any]:
    pt = ev["phone_time"]
    return {"time": pt.isoformat() if pt else server_time.isoformat(), "local_time": lagos(pt).replace(tzinfo=None).isoformat() if pt else None,
            "server_time": server_time.isoformat(), "lat": body.lat, "lng": body.lng, "accuracy": body.accuracy,
            "selfie_url": body.selfie_url, "match_score": ev["match_score"], "flags": ev["flags"], "source": source,
            "site_name": ev["site_name"], "distance_m": ev["distance_m"], "client_id": body.id, "offline": body.offline}


def greeting_for(local_iso: Optional[str]) -> str:
    h = int(local_iso[11:13]) if local_iso else lagos(utcnow()).hour
    return "Good morning" if h < 12 else "Good afternoon" if h < 17 else "Good evening"


async def shift_cfg() -> tuple[int, int]:
    c = await get_settings_doc()
    return c["shift_start_hour"], c["late_grace_minutes"]


def is_record_late(rec: dict[str, Any], hour: int, grace: int) -> bool:
    ci = rec.get("clock_in") or {}
    lt = to_datetime(ci.get("local_time") or ci.get("time"))
    return bool(lt and is_late(lt, hour, grace))


def cert_matrix_row(s: dict[str, Any]) -> dict[str, Any]:
    t = today()
    held = {c["type"]: c for c in s.get("certifications") or []}
    row = {}
    for ctype in ("BOSIET", "HUET", "H2S", "First aid", "Medical", "Equipment licence"):
        c = held.get(ctype)
        row[ctype] = {"expiry": c["expiry"], "status": certificate_status(c["expiry"], t)} if c else {"expiry": None, "status": "none"}
    return row
