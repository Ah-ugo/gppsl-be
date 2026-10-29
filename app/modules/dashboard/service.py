"""Owner dashboard: everything in one call. Sections for modules that have no data yet come back empty."""
from datetime import timedelta
from typing import Any, Optional

from app.core.common import clean_many, today
from app.core.db import get_db
from app.core.settings_store import get_settings_doc
from app.logic import certificate_status, utilisation_pct
from app.logic.equipment import overdue_rentals
from app.logic.finance import ageing_buckets, invoice_age_days, is_open, outstanding_amount
from app.modules.finance import service as fin
from app.modules.projects import service as proj


def _sev(level: str) -> int:
    return {"high": 0, "medium": 1, "low": 2}[level]


async def alerts(branch: Optional[str] = None) -> list[dict[str, Any]]:
    db = get_db()
    t = today()
    out: list[dict[str, Any]] = []
    eq_q = {"branch": branch} if branch else {}
    equipment = await db.equipment.find(eq_q).to_list(2000)
    for e in equipment:
        interval = float(e.get("service_interval_hours") or 0)
        if interval and float(e.get("run_hours") or 0) - float(e.get("last_service_hours") or 0) >= interval:
            out.append({"type": "service_overdue", "severity": "high", "title": f"{e['name']}: service overdue",
                        "detail": "Cannot be deployed until serviced", "link": f"/equipment/{e['_id']}"})
        for c in e.get("certificates") or []:
            st = certificate_status(c.get("expiry_date"), t)
            if st in ("red", "amber"):
                out.append({"type": "equipment_certificate", "severity": "high" if st == "red" else "medium",
                            "title": f"{e['name']}: {c['name']} {'expired' if st == 'red' else 'expiring'}",
                            "detail": f"Expiry {c['expiry_date']}", "link": f"/equipment/{e['_id']}"})
    for r in overdue_rentals(await db.rentals.find({"actual_return": None}).to_list(5000), t):
        out.append({"type": "rental_overdue", "severity": "medium", "title": f"{r.get('equipment_name', 'Equipment')} not returned",
                    "detail": f"Expected back {r['expected_return']}", "link": f"/equipment/{r['equipment_id']}"})
    for inv in await db.invoices.find({}).to_list(20000):
        if is_open(inv) and inv.get("due_date", "9999") < t.isoformat() and invoice_age_days(inv, t) > 60:
            out.append({"type": "invoice_overdue", "severity": "high" if invoice_age_days(inv, t) > 90 else "medium",
                        "title": f"Invoice {inv.get('number')} overdue {invoice_age_days(inv, t)} days",
                        "detail": f"₦{outstanding_amount(inv):,.0f} outstanding", "link": "/finance"})
    staff_q = {"branch": branch} if branch else {}
    for s in await db.staff.find(staff_q).to_list(2000):
        for c in s.get("certifications") or []:
            st = certificate_status(c.get("expiry"), t)
            if st in ("red", "amber"):
                out.append({"type": "staff_certificate", "severity": "high" if st == "red" else "low",
                            "title": f"{s.get('name', 'Staff')}: {c['type']} {'expired' if st == 'red' else 'expiring'}",
                            "detail": f"Expiry {c['expiry']}", "link": "/staff"})
    flagged = await db.attendance.count_documents({"date": t.isoformat(), "status": "flagged"})
    if flagged:
        out.append({"type": "attendance_flagged", "severity": "medium", "title": f"{flagged} flagged clock-in(s) today",
                    "detail": "Waiting for supervisor review", "link": "/attendance"})
    out.sort(key=lambda a: _sev(a["severity"]))
    return out


async def attendance_summary(branch: Optional[str] = None) -> dict[str, Any]:
    db = get_db()
    t = today().isoformat()
    cfg = await get_settings_doc()
    staff = await db.staff.find({"branch": branch} if branch else {}).to_list(5000)
    ids = {s["_id"] for s in staff}
    recs = [r for r in await db.attendance.find({"date": t}).to_list(5000) if r["staff_id"] in ids]
    present = [r for r in recs if r.get("clock_in") and r.get("status") != "rejected"]
    from app.logic.attendance import is_late
    from app.logic._util import to_datetime
    late = 0
    for r in present:
        ct = to_datetime(r["clock_in"].get("local_time") or r["clock_in"].get("time"))
        if ct and is_late(ct, cfg["shift_start_hour"], cfg["late_grace_minutes"]):
            late += 1
    flagged = sum(1 for r in recs if r.get("status") == "flagged")
    out = {"total_staff": len(staff), "present": len(present), "late": late, "flagged": flagged,
           "absent": max(0, len(staff) - len(present)), "by_branch": {}}
    names = {s["_id"]: s.get("branch") for s in staff}
    all_staff = await db.staff.find({}).to_list(5000)
    for b in sorted({s.get("branch") for s in all_staff if s.get("branch")}):
        out["by_branch"][b] = sum(1 for r in present if names.get(r["staff_id"]) == b) if not branch else (len(present) if b == branch else 0)
    out["text"] = f"Today: {out['present']} present, {out['late']} late, {out['absent']} absent, {out['flagged']} flagged"
    return out


async def build(role: str, branch: Optional[str] = None) -> dict[str, Any]:
    db = get_db()
    t = today()
    eq_q = {"branch": branch} if branch else {}
    equipment = await db.equipment.find(eq_q).to_list(2000)
    counts = {s: 0 for s in ("available", "deployed", "in_transit", "maintenance")}
    for e in equipment:
        counts[e.get("status", "available")] = counts.get(e.get("status", "available"), 0) + 1

    proj_q: dict[str, Any] = {"status": "active"}
    if branch:
        proj_q["branch"] = branch
    projects = await db.projects.find(proj_q).to_list(500)
    names = await proj.client_name_map()
    active_projects = []
    for p in projects:
        active_projects.append(await proj.view(p, "md", names))
    order = {"RED": 0, "AMBER": 1, "GREEN": 2}
    active_projects.sort(key=lambda p: order[p["colour"]])

    project_ids = {p["_id"] for p in await db.projects.find({"branch": branch} if branch else {}).to_list(1000)}
    invoices = await db.invoices.find({}).to_list(20000)
    if branch:
        invoices = [i for i in invoices if i.get("project_id") in project_ids]

    pending = await db.expenses.find({"status": "pending", "required_approver": "md" if role in ("md", "admin") else role}).sort("created_at", 1).to_list(50)
    pnames = {p["_id"]: p["name"] for p in await db.projects.find({}, {"name": 1}).to_list(1000)}
    from app.modules.finance.service import view as expense_view

    recent = await db.audit_log.find({}).sort("timestamp", -1).limit(12).to_list(12)
    al = await alerts(branch)
    return {
        "generated_at": t.isoformat(),
        "branch": branch or "All branches",
        "cash": await fin.cash_position(),
        "receivables": round(sum(outstanding_amount(i) for i in invoices if is_open(i)), 2),
        "payables": await fin.payables_total(),
        "utilisation_pct": utilisation_pct(equipment),
        "equipment_counts": counts,
        "equipment_total": len(equipment),
        "ageing": ageing_buckets(invoices, t),
        "active_projects": active_projects,
        "pending_approvals": [expense_view(e, pnames) for e in pending],
        "alerts": al,
        "alert_counts": {s: sum(1 for a in al if a["severity"] == s) for s in ("high", "medium", "low")},
        "attendance": await attendance_summary(branch),
        "recent_activity": clean_many(recent),
    }


async def daily_summary(branch: Optional[str] = None) -> str:
    """Deterministic plain-text summary built from real data. The AI module can rewrite it in prose."""
    d = await build("md", branch)
    lines = [f"GPPSL daily summary, {d['generated_at'][8:10]}/{d['generated_at'][5:7]}/{d['generated_at'][:4]} ({d['branch']})",
             f"Cash ₦{d['cash']:,.0f}. Receivables ₦{d['receivables']:,.0f} (90+ days: ₦{d['ageing']['90+']:,.0f}). Payables ₦{d['payables']:,.0f}.",
             f"Equipment: {d['equipment_counts']['deployed']} deployed, {d['equipment_counts']['available']} available, "
             f"{d['equipment_counts']['maintenance']} in maintenance ({d['utilisation_pct']}% utilisation).",
             d["attendance"]["text"] + ".",
             f"{len(d['pending_approvals'])} expense(s) waiting for your approval."]
    risky = [p for p in d["active_projects"] if p["colour"] != "GREEN"]
    if risky:
        lines.append("Projects needing attention: " + "; ".join(f"{p['name']} ({'at risk' if p['colour'] == 'RED' else 'watch'})" for p in risky) + ".")
    high = [a for a in d["alerts"] if a["severity"] == "high"][:5]
    if high:
        lines.append("Top alerts: " + "; ".join(a["title"] for a in high) + ".")
    return "\n".join(lines)
