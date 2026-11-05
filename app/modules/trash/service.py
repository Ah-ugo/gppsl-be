"""Trash management service: 30-day lifecycle, soft delete, restore, and permanent deletion."""
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from app.core.common import clean, clean_many, scoped_branch_query, utcnow, utcnow_iso
from app.core.db import get_db
from app.logic._util import to_datetime
from app.modules.audit import log


async def purge_expired() -> int:
    """Auto-delete items in trash older than 30 days."""
    now_iso = utcnow_iso()
    res = await get_db().trash.delete_many({"expires_at": {"$lt": now_iso}})
    return res.deleted_count


async def move_to_trash(
    collection_name: str,
    item_id: str,
    user: dict[str, Any],
    entity_type: str,
    title: str,
    subtitle: str = "",
    branch: Optional[str] = None,
    client_ip_addr: str = "internal",
) -> dict[str, Any]:
    db = get_db()
    col = db[collection_name]
    item = await col.find_one({"_id": item_id})
    if not item:
        raise ValueError(f"Item {item_id} not found in {collection_name}")

    now = utcnow()
    resolved_branch = branch or item.get("branch") or user.get("branch") or "Port Harcourt HQ"
    trash_id = f"{entity_type}_{item_id}"

    trash_doc = {
        "_id": trash_id,
        "item_id": item_id,
        "collection": collection_name,
        "entity_type": entity_type,
        "title": title,
        "subtitle": subtitle,
        "branch": resolved_branch,
        "deleted_at": now.isoformat(),
        "expires_at": (now + timedelta(days=30)).isoformat(),
        "deleted_by": {
            "id": user.get("id") or user.get("_id"),
            "name": user.get("name") or "User",
            "email": user.get("email"),
            "role": user.get("role"),
        },
        "data": item,
    }

    await db.trash.replace_one({"_id": trash_id}, trash_doc, upsert=True)
    await col.delete_one({"_id": item_id})

    await log(
        user,
        "delete",
        entity_type,
        item_id,
        f"Moved {entity_type} '{title}' to trash (30 days remaining)",
        client_ip_addr,
    )
    return trash_doc


async def list_trash(
    user: dict[str, Any],
    entity_type: Optional[str] = None,
    search: Optional[str] = None,
    branch: Optional[str] = None,
) -> list[dict[str, Any]]:
    import re
    await purge_expired()
    db = get_db()
    q: dict[str, Any] = {}

    if entity_type and entity_type.lower() not in ("all", ""):
        q["entity_type"] = entity_type

    bq = scoped_branch_query(user, branch)
    if bq:
        q.update(bq)

    if search and search.strip():
        s = search.strip()
        q["$or"] = [
            {"title": re.compile(re.escape(s), re.I)},
            {"subtitle": re.compile(re.escape(s), re.I)},
            {"entity_type": re.compile(re.escape(s), re.I)},
        ]

    rows = await db.trash.find(q).sort("deleted_at", -1).to_list(1000)
    now = utcnow()
    out = []
    for r in rows:
        c = clean(r)
        del_at = to_datetime(r.get("deleted_at"))
        if del_at:
            if del_at.tzinfo is None:
                del_at = del_at.replace(tzinfo=timezone.utc)
            elapsed_days = int((now - del_at).total_seconds() / 86400)
            c["days_left"] = max(0, 30 - elapsed_days)
        else:
            c["days_left"] = 30
        c.pop("data", None)  # Don't send whole payload in list view
        out.append(c)
    return out


async def restore_from_trash(
    trash_id: str,
    user: dict[str, Any],
    client_ip_addr: str = "internal",
) -> dict[str, Any]:
    db = get_db()
    item = await db.trash.find_one({"_id": trash_id})
    if not item:
        raise ValueError("Item not found in trash")

    target_col = db[item["collection"]]
    data = item.get("data", {})
    item_id = item["item_id"]

    data["_id"] = item_id
    data.pop("deleted_at", None)

    await target_col.replace_one({"_id": item_id}, data, upsert=True)
    await db.trash.delete_one({"_id": trash_id})

    await log(
        user,
        "restore",
        item.get("entity_type", "item"),
        item_id,
        f"Restored {item.get('entity_type')} '{item.get('title')}' from trash",
        client_ip_addr,
    )
    return {"ok": True, "restored_id": item_id, "entity_type": item.get("entity_type")}


async def permanently_delete(
    trash_id: str,
    user: dict[str, Any],
    client_ip_addr: str = "internal",
) -> dict[str, Any]:
    db = get_db()
    item = await db.trash.find_one({"_id": trash_id})
    if not item:
        raise ValueError("Item not found in trash")

    await db.trash.delete_one({"_id": trash_id})
    # ensure it's also deleted from the collection
    await db[item["collection"]].delete_one({"_id": item["item_id"]})

    await log(
        user,
        "permanent_delete",
        item.get("entity_type", "item"),
        item["item_id"],
        f"Permanently purged {item.get('entity_type')} '{item.get('title')}'",
        client_ip_addr,
    )
    return {"ok": True, "purged_id": item["item_id"]}


async def empty_trash(
    user: dict[str, Any],
    client_ip_addr: str = "internal",
) -> dict[str, Any]:
    db = get_db()
    count = await db.trash.count_documents({})
    await db.trash.delete_many({})
    await log(
        user,
        "empty_trash",
        "trash",
        "all",
        f"Emptied trash ({count} items deleted permanently)",
        client_ip_addr,
    )
    return {"ok": True, "purged_count": count}

