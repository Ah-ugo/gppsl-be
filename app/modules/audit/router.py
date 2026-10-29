from typing import Any, Optional

from fastapi import APIRouter, Depends, Query

from app.core.common import clean_many
from app.core.db import get_db
from app.core.deps import require_roles

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("")
async def list_audit(
    user_id: Optional[str] = None,
    action: Optional[str] = None,
    entity: Optional[str] = None,
    entity_id: Optional[str] = None,
    date_from: Optional[str] = Query(None, description="YYYY-MM-DD"),
    date_to: Optional[str] = Query(None, description="YYYY-MM-DD"),
    limit: int = Query(100, le=500),
    skip: int = 0,
    _: dict[str, Any] = Depends(require_roles("md", "admin")),
):
    q: dict[str, Any] = {}
    if user_id:
        q["user.id"] = user_id
    if action:
        q["action"] = action
    if entity:
        q["entity"] = entity
    if entity_id:
        q["entity_id"] = entity_id
    if date_from or date_to:
        q["timestamp"] = {}
        if date_from:
            q["timestamp"]["$gte"] = date_from
        if date_to:
            q["timestamp"]["$lte"] = date_to + "T23:59:59.999999+00:00"
    db = get_db()
    total = await db.audit_log.count_documents(q)
    rows = await db.audit_log.find(q).sort("timestamp", -1).skip(skip).limit(limit).to_list(limit)
    return {"total": total, "items": clean_many(rows)}
