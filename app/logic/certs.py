"""Certificate status and assignment eligibility."""
from __future__ import annotations

from datetime import date
from typing import Any

from ._util import DateLike, to_date


def certificate_status(expiry: DateLike, today: date) -> str:
    """'green' (> 60 days left), 'amber' (<= 60 days left, still valid), 'red' (expired)."""
    exp = to_date(expiry)
    if exp is None:
        return "red"
    days_left = (exp - today).days
    if days_left < 0:
        return "red"
    if days_left <= 60:
        return "amber"
    return "green"


def can_assign(staff: dict[str, Any], required_certs: list[str], today: date) -> tuple[bool, list[str]]:
    """Reject when any required certificate is expired or missing. Returns (ok, reasons)."""
    held = {c.get("type"): c for c in staff.get("certifications") or []}
    reasons: list[str] = []
    for req in required_certs or []:
        cert = held.get(req)
        if cert is None:
            reasons.append(f"Missing required certificate: {req}")
            continue
        exp = to_date(cert.get("expiry"))
        if exp is None or exp < today:
            when = exp.strftime("%d/%m/%Y") if exp else "unknown date"
            reasons.append(f"{req} certificate expired on {when}")
    return (len(reasons) == 0, reasons)
