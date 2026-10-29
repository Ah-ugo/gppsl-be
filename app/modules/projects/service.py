from typing import Any, Optional

from app.core.common import clean, today
from app.core.db import get_db
from app.logic import project_colour, timeline_pct

MONEY_ROLES = ("md", "admin", "finance")
APPROVED = ("approved", "paid")


async def project_cost(project_id: str) -> float:
    """Approved expenses plus fuel logged against the project."""
    db = get_db()
    exp = await db.expenses.find({"project_id": project_id, "status": {"$in": list(APPROVED)}}).to_list(5000)
    fuel = await db.fuel_logs.find({"project_id": project_id}).to_list(5000)
    return round(sum(float(e.get("amount_ngn") or e.get("amount") or 0) for e in exp)
                 + sum(float(f.get("cost") or 0) for f in fuel), 2)


async def view(project: dict[str, Any], role: str, client_names: Optional[dict[str, str]] = None,
               cost: Optional[float] = None) -> dict[str, Any]:
    out = clean(project)
    if client_names is not None:
        out["client_name"] = client_names.get(project.get("client_id") or "")
    cost = await project_cost(project["_id"]) if cost is None else cost
    t = today()
    out["timeline_pct"] = round(timeline_pct(project.get("start"), project.get("end"), t), 1)
    out["colour"] = project_colour(project.get("budget", 0), cost, project.get("progress", 0),
                                   project.get("start"), project.get("end"), t)
    if role in MONEY_ROLES:
        budget = float(project.get("budget") or 0)
        out["cost"] = cost
        out["cost_pct"] = round(100.0 * cost / budget, 1) if budget else 0
    else:
        out.pop("budget", None)
    return out


async def client_name_map() -> dict[str, str]:
    rows = await get_db().clients.find({}, {"name": 1}).to_list(1000)
    return {r["_id"]: r["name"] for r in rows}
