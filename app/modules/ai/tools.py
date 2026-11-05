"""AI tools: plain async functions over the REAL database, filtered by the caller's role.
Each returns {"data": ..., "text": human-readable answer part, "sources": [{type,id,label}], "table"?: {...}, "chart"?: {...}}.
"""

import inspect
import logging
import re
from datetime import timedelta
from typing import Any, Optional

from app.core.common import branch_query, clean, clean_many, resolve_branch, today, utcnow_iso  # noqa: F401
from app.core.db import get_db
from app.logic import certificate_status, invoices_older_than
from app.logic.finance import ageing_buckets, invoice_age_days, outstanding_amount  # noqa: F401
from app.modules.finance import service as fin

log = logging.getLogger(__name__)

MONEY = ("md", "admin", "finance")

ROLE_RULES = {
    "get_overdue_invoices": MONEY,
    "find_equipment": ("md", "admin", "storekeeper", "supervisor", "branch_manager"),
    "get_project_summary": ("md", "admin", "supervisor", "finance", "branch_manager"),
    "get_expiring_certificates": ("md", "admin", "hr", "supervisor", "branch_manager"),
    "get_cash_position": MONEY,
    "get_reports": ("md", "admin", "supervisor", "finance", "branch_manager"),
    "get_attendance_today": ("md", "admin", "hr", "supervisor", "branch_manager"),
    "get_staff_count": ("md", "admin", "hr", "supervisor", "branch_manager"),
    "get_customer_count": ("md", "admin", "finance", "supervisor"),
    "get_sales_this_month": MONEY,
    "get_expenses_summary": (
        "md", "admin", "finance", "supervisor", "storekeeper", "hr", "branch_manager",
    ),
    "search_live_records": "*",  # per-collection access is enforced inside the tool
    "get_best_staff": ("md", "admin", "hr", "supervisor", "branch_manager"),
    "update_project_progress": ("md", "admin", "supervisor", "branch_manager", "ops_manager"),
    "get_executive_summary": ("md", "admin", "branch_manager"),
    "search_documents": "*",
}

TOOL_SPECS = [
    {
        "name": "update_project_progress",
        "description": "WRITES to the database. Update a project's progress % (0-100), optional status and note. Call ONLY when the user explicitly asked for the change AND gave both project and value; otherwise ask them.",
        "parameters": {
            "type": "object",
            "properties": {
                "project": {"type": "string", "description": "Project name or ID"},
                "progress": {"type": "integer", "description": "New progress percentage from 0 to 100"},
                "status": {
                    "type": "string",
                    "enum": ["active", "completed", "on_hold", "delayed"],
                    "description": "Optional status update",
                },
                "note": {"type": "string", "description": "Optional progress or milestone note"},
            },
            "required": ["project", "progress"],
        },
    },
    {
        "name": "get_overdue_invoices",
        "description": "Open customer invoices older than N days (age counted from issue date), grouped by client.",
        "parameters": {
            "type": "object",
            "properties": {
                "days": {"type": "integer", "description": "Minimum age in days, 0 for all outstanding"}
            },
            "required": ["days"],
        },
    },
    {
        "name": "find_equipment",
        "description": "Find equipment by name/category/serial, branch, or by status (available, deployed, in_transit, maintenance). Shows where it is deployed.",
        "parameters": {
            "type": "object",
            "properties": {
                "name_or_status": {"type": "string"},
                "branch": {"type": "string", "description": "Optional branch filter like Warri, Port Harcourt, Abuja"},
            },
            "required": ["name_or_status"],
        },
    },
    {
        "name": "get_project_summary",
        "description": "Status, progress, cost vs budget (finance roles only), recent reports and equipment for one project.",
        "parameters": {
            "type": "object",
            "properties": {"project": {"type": "string", "description": "Project name or part of it"}},
            "required": ["project"],
        },
    },
    {
        "name": "get_expiring_certificates",
        "description": "Staff and equipment certificates expired or expiring within N days.",
        "parameters": {
            "type": "object",
            "properties": {"days": {"type": "integer"}},
            "required": ["days"],
        },
    },
    {
        "name": "get_cash_position",
        "description": "Cash, receivables, payables and ageing buckets.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "get_reports",
        "description": "Daily field reports for a branch and date range (YYYY-MM-DD).",
        "parameters": {
            "type": "object",
            "properties": {"branch": {"type": "string"}, "from": {"type": "string"}, "to": {"type": "string"}},
            "required": [],
        },
    },
    {
        "name": "get_attendance_today",
        "description": "Today's attendance: present, late, absent, flagged, optionally for one branch.",
        "parameters": {"type": "object", "properties": {"branch": {"type": "string"}}, "required": []},
    },
    {
        "name": "get_staff_count",
        "description": "Total staff headcount and active staff count from the live staff table.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_customer_count",
        "description": "Total customer or client count from the live clients table.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_sales_this_month",
        "description": "Total sales or revenue issued in the current calendar month from the live invoice table.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "search_live_records",
        "description": "Search live records of one collection (staff, projects, equipment, clients, invoices, expenses, attendance, daily_reports) by keyword. Use for lookups of a specific person, project, unit or invoice.",
        "parameters": {
            "type": "object",
            "properties": {
                "collection": {
                    "type": "string",
                    "enum": [
                        "staff", "projects", "equipment", "clients",
                        "invoices", "expenses", "attendance", "daily_reports",
                    ],
                },
                "query": {"type": "string"},
            },
            "required": ["collection", "query"],
        },
    },
    {
        "name": "get_expenses_summary",
        "description": "List expenditures or expenses raised by the user or across the company.",
        "parameters": {
            "type": "object",
            "properties": {
                "scope": {
                    "type": "string",
                    "enum": ["mine", "all"],
                    "description": "mine for user's own expenses, all for company expenses",
                },
                "category": {"type": "string", "description": "Optional category filter like Diesel, Transport, etc."},
            },
            "required": [],
        },
    },
    {
        "name": "get_best_staff",
        "description": "Ranks staff by attendance consistency and performance metrics. Use when asked about best staff, top performer, most reliable worker, MVP, hardest working, most punctual, or who never misses work.",
        "parameters": {
            "type": "object",
            "properties": {
                "branch": {"type": "string", "description": "Optional: filter by branch name"},
                "metric": {
                    "type": "string",
                    "enum": ["attendance", "punctuality", "overall"],
                    "description": "Ranking metric: attendance (most days present), punctuality (fewest late), overall (combined score)",
                },
                "top_n": {"type": "integer", "description": "How many top staff to return (default 5)"},
            },
            "required": [],
        },
    },
    {
        "name": "get_executive_summary",
        "description": "Cross-department executive pulse: projects, attendance, equipment, finance and alerts for the whole company or one branch. Use for 'how is the business', MD briefings, 'how is Warri doing'.",
        "parameters": {"type": "object", "properties": {"branch": {"type": "string"}}, "required": []},
    },
    {
        "name": "search_documents",
        "description": "Search company SOPs, HSE manuals, hydrotest/nitrogen procedures, policies and contracts. Use for how-to, safety, standards and policy questions.",
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string"}, "k": {"type": "integer"}},
            "required": ["query"],
        },
    },
]


def naira(n: float) -> str:
    return f"₦{n:,.0f}"


def dmy(iso: Optional[str]) -> str:
    return f"{iso[8:10]}/{iso[5:7]}/{iso[:4]}" if iso else "-"


def allowed(tool: str, user: dict[str, Any]) -> bool:
    rule = ROLE_RULES.get(tool, ())
    if rule == "*":
        return True
    user_roles = set(user.get("roles") or ([user.get("role")] if user.get("role") else []))
    return bool(user_roles & set(rule))


async def run(tool: str, args: dict[str, Any], user: dict[str, Any]) -> dict[str, Any]:
    fn = TOOLS.get(tool)
    if not fn:
        return {"data": {"error": f"Unknown tool {tool}"}, "text": "I couldn't find that.", "sources": []}
    if not allowed(tool, user):
        return {
            "data": {"error": "Not permitted for this role"},
            "text": f"Your role ({user.get('role')}) is not allowed to see this information.",
            "sources": [],
            "denied": True,
        }
    params = inspect.signature(fn).parameters
    takes_kw = any(p.kind is p.VAR_KEYWORD for p in params.values())
    # The LLM may send extra/empty args; never let that crash a tool.
    safe_args = {
        k: v
        for k, v in (args or {}).items()
        if k != "user" and v is not None and v != "" and (takes_kw or k in params)
    }
    try:
        return await fn(user=user, **safe_args)
    except Exception as exc:
        log.exception("tool %s failed", tool)
        return {
            "data": {"error": str(exc)},
            "text": "I hit a problem reading that data. Please try rephrasing.",
            "sources": [],
        }


async def get_overdue_invoices(user: dict, days: int = 0) -> dict[str, Any]:
    db = get_db()
    t = today()
    days = int(days or 0)
    clients = {c["_id"]: c["name"] for c in await db.clients.find({}).to_list(1000)}
    invoices = await db.invoices.find({}).to_list(20000)
    rows = invoices_older_than(invoices, t, days if days > 0 else -1)  # strictly older than N days
    by: dict[str, dict[str, Any]] = {}
    for i in rows:
        c = by.setdefault(
            i["client_id"],
            {
                "client": clients.get(i["client_id"], "?"),
                "client_id": i["client_id"],
                "invoices": 0,
                "outstanding": 0.0,
                "oldest_days": 0,
                "numbers": [],
            },
        )
        c["invoices"] += 1
        c["outstanding"] += outstanding_amount(i)
        c["oldest_days"] = max(c["oldest_days"], invoice_age_days(i, t))
        c["numbers"].append(i.get("number"))
    groups = sorted(by.values(), key=lambda g: g["outstanding"], reverse=True)
    total = sum(g["outstanding"] for g in groups)
    label = f"over {days} days" if days > 0 else "outstanding"
    if not groups:
        return {"data": {"clients": []}, "text": f"No invoices {label}.", "sources": []}
    text = (
        f"{len(groups)} client(s) have invoices {label}, totalling {naira(total)}:\n"
        + "\n".join(
            f"- {g['client']}: {naira(g['outstanding'])} across {g['invoices']} invoice(s), oldest {g['oldest_days']} days"
            for g in groups
        )
    )
    sources = [{"type": "client", "id": g["client_id"], "label": g["client"]} for g in groups] + [
        {
            "type": "invoice",
            "id": i["_id"],
            "label": f"{i.get('number')} ({clients.get(i['client_id'], '?')})",
        }
        for i in rows[:12]
    ]
    return {
        "data": {"days": days, "total": total, "clients": groups},
        "text": text,
        "sources": sources,
        "table": {
            "title": f"Clients with invoices {label}",
            "columns": ["Client", "Invoices", "Outstanding", "Oldest (days)"],
            "rows": [[g["client"], g["invoices"], naira(g["outstanding"]), g["oldest_days"]] for g in groups],
        },
        "chart": {
            "title": "Outstanding by client (₦)",
            "data": [{"name": g["client"].split("(")[0].strip(), "value": g["outstanding"]} for g in groups],
        },
    }


STATUSES = {"available", "deployed", "in_transit", "maintenance"}


async def find_equipment(user: dict, name_or_status: str, branch: Optional[str] = None) -> dict[str, Any]:
    db = get_db()
    term = (name_or_status or "").strip().lower()
    if term.replace(" ", "_") in STATUSES:
        term = term.replace(" ", "_")
    q: dict[str, Any]
    if term in STATUSES:
        q = {"status": term}
    else:
        resolved_term_branch = resolve_branch(term)
        rx = re.escape(term)
        if resolved_term_branch and not branch:
            q = branch_query(resolved_term_branch)
        else:
            q = {
                "$or": [
                    {"name": {"$regex": rx, "$options": "i"}},
                    {"category": {"$regex": rx, "$options": "i"}},
                    {"serial": {"$regex": rx, "$options": "i"}},
                    {"branch": {"$regex": rx, "$options": "i"}},
                ]
            }
    if branch:
        q.update(branch_query(branch))
    items = await db.equipment.find(q).sort("name", 1).to_list(60)
    if not items:
        return {
            "data": {"items": []},
            "text": f'I couldn\'t find any equipment matching "{name_or_status}".',
            "sources": [],
        }
    projects = {p["_id"]: p["name"] for p in await db.projects.find({}, {"name": 1}).to_list(1000)}
    lines, rows = [], []
    for e in items[:25]:
        where = (
            f"deployed at {projects.get(e.get('current_job_id'), 'a site')}"
            if e.get("status") == "deployed"
            else str(e.get("status", "unknown")).replace("_", " ")
        )
        lines.append(f"- {e['name']} ({e.get('serial', '-')}, {e.get('branch', '-')}): {where}")
        rows.append([e["name"], e.get("serial", "-"), e.get("branch", "-"), where])
    return {
        "data": {
            "items": [
                {
                    "name": e["name"],
                    "serial": e.get("serial"),
                    "status": e.get("status"),
                    "branch": e.get("branch"),
                    "project": projects.get(e.get("current_job_id")),
                }
                for e in items
            ]
        },
        "text": f"{len(items)} item(s) found:\n" + "\n".join(lines),
        "sources": [{"type": "equipment", "id": e["_id"], "label": e["name"]} for e in items[:10]],
        "table": {"title": "Equipment", "columns": ["Name", "Serial", "Branch", "Where"], "rows": rows},
    }


async def get_project_summary(user: dict, project: str) -> dict[str, Any]:
    from app.modules.projects import service as proj

    db = get_db()
    p = await db.projects.find_one({"name": {"$regex": re.escape(project), "$options": "i"}})
    if not p:
        for w in re.findall(r"[A-Za-z]{4,}", project):
            p = await db.projects.find_one({"name": {"$regex": re.escape(w), "$options": "i"}})
            if p:
                break
    if not p:
        return {"data": {}, "text": f'I couldn\'t find a project called "{project}".', "sources": []}
    v = await proj.view(p, user["role"], await proj.client_name_map())
    since = (today() - timedelta(days=7)).isoformat()
    reports = await db.daily_reports.find({"project_id": p["_id"], "date": {"$gte": since}}).to_list(100)
    rentals = await db.rentals.find({"project_id": p["_id"], "actual_return": None}).to_list(100)
    issues = [r["issues"] for r in reports if r.get("issues")]
    colour = {
        "RED": "at risk (red)",
        "AMBER": "needs watching (amber)",
        "GREEN": "on track (green)",
    }.get(v["colour"], v["colour"])
    text = (
        f"{p['name']} for {v['client_name']} at {p['location']} is {colour}. Progress {p['progress']:.0f}% against a planned {v['timeline_pct']:.0f}%. "
        f"Ends {dmy(p['end'])}. Last 7 days: {len(reports)} report(s)"
        + (
            f", average {sum(r['headcount'] for r in reports) / len(reports):.0f} people on site"
            if reports
            else ""
        )
        + f". {len(rentals)} equipment item(s) on site."
    )
    if "cost" in v:
        text += f" Cost {naira(v['cost'])} of {naira(p['budget'])} budget ({v['cost_pct']:.0f}%)."
    if issues:
        text += " Issues raised: " + "; ".join(issues[:3]) + "."
    return {
        "data": {
            "project": v,
            "reports_7d": len(reports),
            "issues": issues,
            "equipment_on_site": len(rentals),
        },
        "text": text,
        "sources": [{"type": "project", "id": p["_id"], "label": p["name"]}],
    }


async def get_expiring_certificates(user: dict, days: int = 60) -> dict[str, Any]:
    db = get_db()
    t = today()
    days = int(days or 60)
    limit = (t + timedelta(days=days)).isoformat()
    rows = []
    for s in await db.staff.find({}).to_list(2000):
        for c in s.get("certifications") or []:
            if c.get("expiry") and c["expiry"] <= limit:
                rows.append(
                    (c["expiry"], f"{s['name']}: {c['type']}", certificate_status(c["expiry"], t), "staff", s["_id"], s["name"])
                )
    for e in await db.equipment.find({}).to_list(2000):
        for c in e.get("certificates") or []:
            if c.get("expiry_date") and c["expiry_date"] <= limit:
                rows.append(
                    (c["expiry_date"], f"{e['name']}: {c['name']}", certificate_status(c["expiry_date"], t), "equipment", e["_id"], e["name"])
                )
    rows.sort()
    if not rows:
        return {"data": {"items": []}, "text": f"Nothing is expired or expiring within {days} days.", "sources": []}
    text = f"{len(rows)} certificate(s) expired or expiring within {days} days:\n" + "\n".join(
        f"- {r[1]}: {'EXPIRED' if r[2] == 'red' else 'expires'} {dmy(r[0])}" for r in rows[:30]
    )
    return {
        "data": {"items": [{"what": r[1], "expiry": r[0], "status": r[2]} for r in rows[:60]]},
        "text": text,
        "sources": [{"type": r[3], "id": r[4], "label": r[5]} for r in rows[:10]],
        "table": {
            "title": "Certificates",
            "columns": ["Certificate", "Expiry", "Status"],
            "rows": [[r[1], dmy(r[0]), "Expired" if r[2] == "red" else "Expiring"] for r in rows[:40]],
        },
    }


async def get_cash_position(user: dict) -> dict[str, Any]:
    cash, rec, pay = await fin.cash_position(), await fin.receivables_total(), await fin.payables_total()
    ag = await fin.ageing()
    text = (
        f"Cash position {naira(cash)}. Receivables {naira(rec)} (0-30 days {naira(ag['0-30'])}, 31-60 {naira(ag['31-60'])}, "
        f"61-90 {naira(ag['61-90'])}, 90+ {naira(ag['90+'])}). Payables {naira(pay)}."
    )
    return {
        "data": {"cash": cash, "receivables": rec, "payables": pay, "ageing": ag},
        "text": text,
        "sources": [{"type": "finance", "id": "overview", "label": "Finance overview"}],
        "chart": {
            "title": "Receivables by age (₦)",
            "data": [{"name": f"{k} days", "value": v} for k, v in ag.items()],
        },
    }


async def get_sales_this_month(user: dict) -> dict[str, Any]:
    db = get_db()
    month_start = today().replace(day=1).isoformat()
    rows = await db.invoices.find({"issue_date": {"$gte": month_start}}).to_list(20000)
    total = round(sum(float(r.get("amount") or 0) for r in rows), 2)
    text = f"Total sales this month: {naira(total)} across {len(rows)} invoice(s)."
    return {
        "data": {
            "month_start": month_start,
            "total": total,
            "count": len(rows),
            "invoices": [{"number": r.get("number"), "amount": r.get("amount")} for r in rows[:15]],
        },
        "text": text,
        "sources": [{"type": "finance", "id": "sales-this-month", "label": "Sales this month"}],
        "table": {
            "title": "Sales this month",
            "columns": ["Month start", "Invoice count", "Total sales"],
            "rows": [[month_start, len(rows), naira(total)]],
        },
    }


async def get_reports(user: dict, branch: Optional[str] = None, **kw: Any) -> dict[str, Any]:
    db = get_db()
    t = today()
    date_from = kw.get("from") or (t - timedelta(days=6)).isoformat()
    date_to = kw.get("to") or t.isoformat()
    q: dict[str, Any] = {"date": {"$gte": date_from, "$lte": date_to}}
    q.update(branch_query(branch))
    reports = await db.daily_reports.find(q).sort("date", 1).to_list(2000)
    resolved_b = resolve_branch(branch)
    if not reports:
        return {
            "data": {"reports": 0},
            "text": f"I couldn't find any field reports{' for ' + resolved_b if resolved_b else ''} between {dmy(date_from)} and {dmy(date_to)}.",
            "sources": [],
        }
    names = {p["_id"]: p["name"] for p in await db.projects.find({}, {"name": 1}).to_list(1000)}
    per: dict[str, list] = {}
    for r in reports:
        per.setdefault(r["project_id"], []).append(r)
    lines, rows, sources = [], [], []
    for pid, rs in per.items():
        issues = [r["issues"] for r in rs if r.get("issues")]
        avg = sum(r.get("headcount", 0) for r in rs) / len(rs)
        lines.append(
            f"- {names.get(pid, '?')}: {len(rs)} report(s), progress now {rs[-1].get('progress', 0):.0f}%, average {avg:.0f} on site"
            + (f". Issues: {'; '.join(issues[:2])}" if issues else ". No issues raised")
        )
        rows.append([names.get(pid, "?"), len(rs), f"{rs[-1].get('progress', 0):.0f}%", f"{avg:.0f}", len(issues)])
        sources.append({"type": "project", "id": pid, "label": names.get(pid, "?")})
    scope = branch or "all branches"
    return {
        "data": {"reports": len(reports), "projects": len(per), "summary": lines},
        "text": f"{len(reports)} report(s) for {scope}, {dmy(date_from)} to {dmy(date_to)}:\n" + "\n".join(lines),
        "sources": sources,
        "table": {
            "title": f"Field reports, {scope}",
            "columns": ["Project", "Reports", "Progress", "Avg people", "Issues"],
            "rows": rows,
        },
    }


async def get_attendance_today(user: dict, branch: Optional[str] = None) -> dict[str, Any]:
    from app.modules.dashboard.service import attendance_summary

    resolved = resolve_branch(branch)
    a = await attendance_summary(resolved)
    db = get_db()
    flag_q: dict[str, Any] = {"date": today().isoformat(), "status": "flagged"}
    flag_q.update(branch_query(resolved))
    flagged = await db.attendance.find(flag_q).to_list(100)
    scope = f" ({resolved})" if resolved else ""
    text = a["text"] + scope + "."
    if flagged:
        text += " Flagged: " + ", ".join(f.get("staff_name", "?") for f in flagged[:6]) + "."
    return {
        "data": a,
        "text": text,
        "sources": [{"type": "attendance", "id": today().isoformat(), "label": "Attendance today"}],
    }


async def get_staff_count(user: dict) -> dict[str, Any]:
    db = get_db()
    total = await db.staff.count_documents({})
    active = await db.staff.count_documents({"active": True})
    by_role = []
    for row in await db.staff.aggregate(
        [{"$group": {"_id": "$role", "count": {"$sum": 1}}}, {"$sort": {"count": -1, "_id": 1}}]
    ).to_list(20):
        by_role.append({"role": row["_id"], "count": row["count"]})
    text = f"You have {total} staff in total, with {active} active staff records."
    if by_role:
        text += " Breakdown: " + "; ".join(f"{r['role']}: {r['count']}" for r in by_role) + "."
    return {
        "data": {"total": total, "active": active, "by_role": by_role},
        "text": text,
        "sources": [{"type": "staff", "id": "summary", "label": "Staff summary"}],
        "table": {
            "title": "Staff count",
            "columns": ["Role", "Count"],
            "rows": [[r["role"], r["count"]] for r in by_role],
        },
    }


async def get_customer_count(user: dict) -> dict[str, Any]:
    total = await get_db().clients.count_documents({})
    return {
        "data": {"total": total},
        "text": f"You have {total} customer(s) in total.",
        "sources": [{"type": "client", "id": "summary", "label": "Customer summary"}],
        "table": {"title": "Customer count", "columns": ["Customers"], "rows": [[total]]},
    }


COLLECTION_ACCESS = {
    "staff": ("md", "admin", "hr", "supervisor", "branch_manager"),
    "projects": ("md", "admin", "finance", "supervisor", "branch_manager", "ops_manager"),
    "equipment": ("md", "admin", "storekeeper", "supervisor", "branch_manager"),
    "clients": ("md", "admin", "finance", "supervisor"),
    "invoices": MONEY,
    "expenses": MONEY,
    "attendance": ("md", "admin", "hr", "supervisor", "branch_manager"),
    "daily_reports": ("md", "admin", "supervisor", "finance", "branch_manager"),
}
SEARCH_FIELDS = {
    "staff": ["name", "email", "role", "position", "branch"],
    "projects": ["name", "location", "status"],
    "equipment": ["name", "serial", "category", "branch", "status"],
    "clients": ["name", "email", "contact"],
    "invoices": ["number", "client_name", "status"],
    "expenses": ["vendor", "description", "category", "status"],
    "attendance": ["staff_name", "branch", "status"],
    "daily_reports": ["branch", "issues", "summary"],
}
SENSITIVE_KEYS = {
    "password", "password_hash", "hashed_password", "hash", "token", "refresh_token",
    "face_template", "face_embedding", "face_descriptor", "salary", "bank_account",
}
_SEARCH_STOP = {"find", "show", "search", "list", "get", "the", "a", "an", "of", "for", "in", "at", "me", "all", "any"}


def _flat_safe(doc: dict[str, Any]) -> dict[str, Any]:
    """Only top-level scalar fields, with anything sensitive removed."""
    return {
        k: v
        for k, v in doc.items()
        if k.lower() not in SENSITIVE_KEYS and isinstance(v, (str, int, float, bool, type(None)))
    }


async def search_live_records(user: dict, collection: str, query: str) -> dict[str, Any]:
    if collection not in COLLECTION_ACCESS:
        return {
            "data": {"collection": collection, "matches": []},
            "text": f"I can't search a '{collection}' collection.",
            "sources": [],
        }
    user_roles = set(user.get("roles") or ([user.get("role")] if user.get("role") else []))
    if not (user_roles & set(COLLECTION_ACCESS[collection])):
        return {
            "data": {"error": "Not permitted for this role"},
            "text": f"Your role ({user.get('role')}) is not allowed to see {collection} records.",
            "sources": [],
            "denied": True,
        }

    term = (query or "").strip()
    if collection == "staff" and re.search(r"\b(best|top|reliable|punctual|hardest|mvp|star|rank)\b", term, re.I):
        return await get_best_staff(user=user, branch=None, metric="overall", top_n=5)

    words = [w for w in re.findall(r"[A-Za-z0-9@.\-]{2,}", term) if w.lower() not in _SEARCH_STOP]
    q: dict[str, Any] = {}
    if words:
        q = {
            "$or": [
                {f: {"$regex": re.escape(w), "$options": "i"}}
                for w in words
                for f in SEARCH_FIELDS[collection]
            ]
        }
    raw = await getattr(get_db(), collection).find(q).limit(10).to_list(10)
    rows = [{**_flat_safe(r), "_id": str(r.get("_id"))} for r in raw]

    def label(r: dict) -> str:
        return str(r.get("name") or r.get("number") or r.get("vendor") or r.get("staff_name") or r["_id"])

    text = (
        f'{len(rows)} {collection} record(s) matching "{term}":\n' + "\n".join(f"- {label(r)}" for r in rows)
        if rows
        else f'No {collection} records matched "{term}".'
    )
    return {
        "data": {"collection": collection, "matches": rows},
        "text": text,
        "sources": [{"type": collection, "id": r["_id"], "label": label(r)} for r in rows],
    }


async def get_expenses_summary(
    user: dict[str, Any], scope: str = "mine", category: Optional[str] = None
) -> dict[str, Any]:
    db = get_db()
    q: dict[str, Any] = {}
    user_roles = set(user.get("roles") or ([user.get("role")] if user.get("role") else []))
    is_mgmt = bool(user_roles & {"md", "admin", "finance"})
    user_id = user.get("id") or user.get("_id")
    mine = scope == "mine" or not is_mgmt
    if mine:
        q["$or"] = [
            {"requester.id": user_id},
            {"requester.email": user.get("email")},
            {"user_id": user_id},
        ]
    if category:
        q["category"] = category

    rows = await db.expenses.find(q).sort("created_at", -1).limit(20).to_list(20)
    total_val = sum(r.get("amount_ngn", 0) for r in rows)
    label = "Your expenses / expenditures" if mine else "Company expenditures"

    if not rows:
        return {
            "data": {"count": 0, "total": 0, "rows": []},
            "text": f"{label}: No expenditure records found in the database.",
            "sources": [],
        }

    table_rows = [
        [
            r.get("date") or str(r.get("created_at", ""))[:10],
            r.get("vendor") or r.get("description") or "Expense",
            r.get("category", "General"),
            naira(r.get("amount_ngn", 0)),
            (r.get("status") or "pending").title(),
        ]
        for r in rows
    ]
    return {
        "data": {"count": len(rows), "total": total_val, "expenses": clean_many(rows)},
        "text": f"{label}: Found {len(rows)} expenditure record(s) totalling {naira(total_val)}.",
        "sources": [
            {
                "type": "expense",
                "id": str(r["_id"]),
                "label": f"{r.get('vendor') or 'Expense'} ({naira(r.get('amount_ngn', 0))})",
            }
            for r in rows[:6]
        ],
        "table": {
            "title": label,
            "columns": ["Date", "Vendor / Purpose", "Category", "Amount", "Status"],
            "rows": table_rows,
        },
    }


async def get_best_staff(
    user: dict, branch: Optional[str] = None, metric: str = "overall", top_n: int = 5
) -> dict[str, Any]:
    """Ranks staff by attendance, punctuality, and days present from real attendance records."""
    db = get_db()
    resolved = resolve_branch(branch)
    since = (today() - timedelta(days=30)).isoformat()
    q: dict[str, Any] = {"date": {"$gte": since}}
    q.update(branch_query(resolved))
    records = await db.attendance.find(q).to_list(50000)

    stats: dict[str, dict] = {}
    for r in records:
        sid = r.get("staff_id") or r.get("user_id") or r.get("staff_name")
        if not sid:
            continue
        s = stats.setdefault(
            sid,
            {
                "id": sid,
                "name": r.get("staff_name", str(sid)),
                "branch": r.get("branch", branch or "?"),
                "present": 0,
                "late": 0,
                "flagged": 0,
                "total": 0,
            },
        )
        s["total"] += 1
        status = (r.get("status") or "").lower()
        if status in ("present", "verified", "on_time"):
            s["present"] += 1
        elif status == "late":
            s["present"] += 1
            s["late"] += 1
        elif status == "flagged":
            s["present"] += 1
            s["flagged"] += 1

    top_n = max(int(top_n or 5), 1)
    if not stats:
        all_staff = await db.staff.find(branch_query(resolved)).to_list(200)
        if not all_staff:
            return {
                "data": {"staff": []},
                "text": "I don't have enough attendance data yet to rank staff performance. As staff clock in daily, rankings will build up.",
                "sources": [],
            }
        all_staff.sort(key=lambda x: x.get("date_joined") or "")
        top = all_staff[:top_n]
        text = (
            f"I don't have attendance records yet to compute rankings, but here are {len(top)} longest-serving staff members:\n"
            + "\n".join(f"- {s['name']} ({s.get('position', 'N/A')}, {s.get('branch', '?')})" for s in top)
        )
        return {
            "data": {"staff": [{"name": s["name"], "position": s.get("position"), "branch": s.get("branch")} for s in top]},
            "text": text,
            "sources": [{"type": "staff", "id": s["_id"], "label": s["name"]} for s in top],
        }

    for s in stats.values():
        total = max(s["total"], 1)
        attendance_pct = (s["present"] / total) * 100
        punctuality_pct = ((s["present"] - s["late"]) / total) * 100
        s["attendance_pct"] = round(attendance_pct, 1)
        s["punctuality_pct"] = round(punctuality_pct, 1)
        s["overall_score"] = round(attendance_pct * 0.6 + punctuality_pct * 0.4, 1)

    sort_key = {"attendance": "attendance_pct", "punctuality": "punctuality_pct"}.get(metric, "overall_score")
    ranked = sorted(stats.values(), key=lambda x: (x[sort_key], x["present"]), reverse=True)
    top = ranked[:top_n]

    scope = f" at {branch}" if branch else ""
    lines = [
        f"{i}. **{s['name']}** ({s['branch']}): {s['present']} days present in last 30 days "
        f"({s['attendance_pct']}% attendance), {s['late']} late day(s), score {s['overall_score']}/100"
        for i, s in enumerate(top, 1)
    ]
    text = (
        f"### 🏆 Top {len(top)} Performing Staff{scope} (last 30 days)\n\n"
        + "\n".join(lines)
        + "\n\n_Ranked by overall score: attendance weight 60%, punctuality weight 40%._"
    )
    return {
        "data": {"metric": metric, "staff": top},
        "text": text,
        "sources": [{"type": "staff", "id": s["id"], "label": s["name"]} for s in top],
        "table": {
            "title": f"Top Staff{scope}",
            "columns": ["Rank", "Name", "Branch", "Days Present", "Attendance %", "Late Days", "Score"],
            "rows": [
                [i, s["name"], s["branch"], s["present"], f"{s['attendance_pct']}%", s["late"], s["overall_score"]]
                for i, s in enumerate(top, 1)
            ],
        },
    }


async def update_project_progress(
    user: dict,
    project: str,
    progress: int,
    status: Optional[str] = None,
    note: Optional[str] = None,
) -> dict[str, Any]:
    """Updates progress (0-100), optional status, and update note directly in db.projects."""
    db = get_db()
    key = str(project).strip()
    p = await db.projects.find_one({"_id": key})
    if not p:
        matches = await db.projects.find({"name": {"$regex": re.escape(key), "$options": "i"}}).to_list(5)
        exact = [m for m in matches if m["name"].lower() == key.lower()]
        if len(exact) == 1:
            p = exact[0]
        elif len(matches) == 1:
            p = matches[0]
        elif len(matches) > 1:
            names = ", ".join(m["name"] for m in matches)
            return {
                "data": {"error": "Ambiguous project", "candidates": [m["name"] for m in matches]},
                "text": f"'{project}' matches several projects ({names}). Please say which one.",
                "sources": [],
            }
    if not p:
        return {
            "data": {"error": "Project not found"},
            "text": f"I couldn't find an active project matching '{project}'.",
            "sources": [],
        }

    progress_clamped = max(0, min(100, int(progress)))
    now = utcnow_iso()
    patch: dict[str, Any] = {
        "progress": progress_clamped,
        "updated_at": now,
        "last_progress_update": {
            "by": user.get("name"),
            "at": now,
            "progress": progress_clamped,
            "note": note,
        },
    }
    if status in ("active", "completed", "on_hold", "delayed"):
        patch["status"] = status
    if note:
        patch["latest_note"] = note

    await db.projects.update_one({"_id": p["_id"]}, {"$set": patch})

    status_str = f" Status is now **{status}**." if status else ""
    note_str = f"\nNote logged: *\"{note}\"*" if note else ""
    return {
        "data": {
            "project_id": p["_id"],
            "name": p["name"],
            "previous_progress": p.get("progress"),
            "progress": progress_clamped,
            "status": patch.get("status", p.get("status")),
            "note": note,
        },
        "text": f"✅ Updated project **{p['name']}** completion progress to **{progress_clamped}%**.{status_str}{note_str}",
        "sources": [{"type": "project", "id": p["_id"], "label": p["name"]}],
    }


async def get_executive_summary(user: dict, branch: Optional[str] = None) -> dict[str, Any]:
    from app.modules.dashboard import service as dash

    text = await dash.daily_summary(branch)
    return {
        "data": {"branch": branch, "summary": text},
        "text": text,
        "sources": [{"type": "system", "id": "dashboard", "label": "Live operations dashboard"}],
    }


async def search_documents(user: dict, query: str, k: int = 4) -> dict[str, Any]:
    from app.modules.documents import service as docs

    excerpts = await docs.search_chunks(query, user, k=max(1, min(int(k or 4), 6)))
    if not excerpts:
        return {"data": {"excerpts": []}, "text": "No matching company documents found.", "sources": []}
    return {
        "data": {"excerpts": [{"document": e["name"], "text": e["text"][:1200]} for e in excerpts]},
        "text": "\n".join(f"[{e['name']}] {e['text'][:300].strip()}" for e in excerpts),
        "sources": [{"type": "document", "id": e["document_id"], "label": e["name"]} for e in excerpts],
    }


TOOLS = {
    "get_overdue_invoices": get_overdue_invoices,
    "find_equipment": find_equipment,
    "get_project_summary": get_project_summary,
    "get_expiring_certificates": get_expiring_certificates,
    "get_cash_position": get_cash_position,
    "get_sales_this_month": get_sales_this_month,
    "get_reports": get_reports,
    "get_attendance_today": get_attendance_today,
    "get_staff_count": get_staff_count,
    "get_customer_count": get_customer_count,
    "search_live_records": search_live_records,
    "get_expenses_summary": get_expenses_summary,
    "get_best_staff": get_best_staff,
    "update_project_progress": update_project_progress,
    "get_executive_summary": get_executive_summary,
    "search_documents": search_documents,
}