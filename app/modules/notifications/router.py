from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from app.core.common import clean_many
from app.core.db import get_db
from app.core.deps import get_current_user

router = APIRouter(prefix="/notifications", tags=["notifications"], dependencies=[Depends(get_current_user)])


@router.get("")
async def my_notifications(limit: int = 50, user: dict[str, Any] = Depends(get_current_user)):
    db = get_db()
    rows = await db.notifications.find({"user_id": user["id"]}).sort("created_at", -1).limit(limit).to_list(limit)
    unread = await db.notifications.count_documents({"user_id": user["id"], "read": False})
    return {"unread": unread, "items": clean_many(rows)}


@router.post("/read-all")
async def read_all(user: dict[str, Any] = Depends(get_current_user)):
    await get_db().notifications.update_many({"user_id": user["id"], "read": False}, {"$set": {"read": True}})
    return {"ok": True}


@router.post("/{notification_id}/read")
async def read_one(notification_id: str, user: dict[str, Any] = Depends(get_current_user)):
    res = await get_db().notifications.update_one(
        {"_id": notification_id, "user_id": user["id"]}, {"$set": {"read": True}}
    )
    if res.matched_count == 0:
        raise HTTPException(404, "Notification not found")
    return {"ok": True}
