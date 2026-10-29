"""Append-only audit trail. There is deliberately no update or delete function."""
from typing import Any, Optional

from app.core.common import new_id, utcnow_iso
from app.core.db import get_db


async def log(
    user: Optional[dict[str, Any]],
    action: str,
    entity: str,
    entity_id: Optional[str],
    summary: str,
    ip: Optional[str] = None,
) -> None:
    """Record who did what. Called on every create, update, approve, check-out, clock-in, sign."""
    await get_db().audit_log.insert_one(
        {
            "_id": new_id(),
            "user": {"id": user.get("id") or user.get("_id"), "name": user.get("name"), "role": user.get("role")}
            if user
            else {"id": None, "name": "system", "role": "system"},
            "action": action,
            "entity": entity,
            "entity_id": entity_id,
            "timestamp": utcnow_iso(),
            "ip": ip,
            "summary": summary,
        }
    )
