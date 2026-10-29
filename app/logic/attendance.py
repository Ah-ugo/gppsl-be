"""Attendance rules: geofence, face matching, flags, payroll days. Standard library only."""
from __future__ import annotations

import math
from datetime import datetime
from typing import Any, Optional

from ._util import naive_utc, to_datetime

EARTH_RADIUS_M = 6_371_000.0
POOR_ACCURACY_M = 100.0
MAX_SPEED_KMH = 250.0
MAX_TIME_DRIFT_SECONDS = 300
FACE_THRESHOLD = 0.6


def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance in metres."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = p2 - p1
    dlmb = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


def geofence_check(
    lat: float,
    lng: float,
    accuracy: Optional[float],
    site: dict[str, Any],
    previous: Optional[dict[str, Any]] = None,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """Is the point inside the site radius, and does the GPS look trustworthy?

    previous: {lat, lng, time} of the last known fix, used to spot impossible jumps.
    Returns {inside, distance_m, flags}.
    """
    distance = haversine_m(lat, lng, float(site["lat"]), float(site["lng"]))
    flags: list[str] = []
    if accuracy is None or accuracy > POOR_ACCURACY_M:
        flags.append("poor_gps_accuracy")
    if previous and now is not None:
        prev_time = to_datetime(previous.get("time"))
        if prev_time is not None:
            seconds = max(1.0, (naive_utc(now) - naive_utc(prev_time)).total_seconds())
            km = haversine_m(lat, lng, float(previous["lat"]), float(previous["lng"])) / 1000.0
            if km > 1.0 and (km / (seconds / 3600.0)) > MAX_SPEED_KMH:
                flags.append("impossible_jump")
    return {"inside": distance <= float(site["radius_m"]), "distance_m": round(distance, 1), "flags": flags}


def nearest_site(lat: float, lng: float, sites: list[dict[str, Any]]) -> Optional[tuple[dict[str, Any], float]]:
    """Closest site and its distance in metres, or None when there are no sites."""
    best = None
    for site in sites:
        d = haversine_m(lat, lng, float(site["lat"]), float(site["lng"]))
        if best is None or d < best[1]:
            best = (site, d)
    return best


def euclidean(a: list[float], b: list[float]) -> float:
    if len(a) != len(b):
        raise ValueError("Descriptors must have the same length")
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def face_match(
    descriptor: list[float], templates: list[list[float]], threshold: float = FACE_THRESHOLD
) -> tuple[bool, Optional[float]]:
    """(matched, best_distance). No templates means (False, None). Lower distance is better."""
    if not templates or not descriptor:
        return False, None
    best = min(euclidean(descriptor, t) for t in templates)
    return best < threshold, round(best, 4)


def attendance_flags(
    clock_in: dict[str, Any],
    server_time: datetime,
    previous: Optional[dict[str, Any]] = None,
    offline: bool = False,
) -> list[str]:
    """Flags for a clock-in attempt.

    clock_in: {face_matched: bool|None, inside: bool, geo_flags: [...], phone_time: datetime|str}
    previous: today's existing record for this person, if any (duplicate check).
    offline: queued entries are uploaded later, so the phone-vs-server drift check is skipped.
    A face mismatch only adds a flag; it never penalises on its own.
    """
    flags: list[str] = []
    if clock_in.get("face_matched") is False:
        flags.append("face_mismatch")
    if clock_in.get("inside") is False:
        flags.append("outside_site")
    geo = clock_in.get("geo_flags") or []
    if "poor_gps_accuracy" in geo or "impossible_jump" in geo:
        flags.append("suspicious_gps")
    if not offline:
        phone_time = to_datetime(clock_in.get("phone_time"))
        if phone_time is not None:
            drift = abs((naive_utc(server_time) - naive_utc(phone_time)).total_seconds())
            if drift > MAX_TIME_DRIFT_SECONDS:
                flags.append("time_drift")
    if previous:
        flags.append("duplicate")
    return flags


def is_late(clock_in_time: datetime, shift_start_hour: int = 8, grace_minutes: int = 15) -> bool:
    """Late when clocking in more than `grace_minutes` after the shift start (local time)."""
    start_minutes = shift_start_hour * 60 + grace_minutes
    return clock_in_time.hour * 60 + clock_in_time.minute > start_minutes


def payroll_days(attendance: list[dict[str, Any]], month: str) -> dict[str, int]:
    """Days present per staff_id for 'YYYY-MM', counting VERIFIED records only.

    A record is verified when status == 'verified' (set automatically when there are no
    flags, or by a supervisor approving a flagged one). Flagged and rejected do not count.
    """
    days: dict[str, set[str]] = {}
    for rec in attendance:
        date_str = str(rec.get("date", ""))
        if not date_str.startswith(month):
            continue
        if rec.get("status") != "verified" or not rec.get("clock_in"):
            continue
        days.setdefault(str(rec["staff_id"]), set()).add(date_str)
    return {staff_id: len(d) for staff_id, d in days.items()}
