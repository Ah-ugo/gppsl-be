"""notify(): in-app notification, optionally also emailed."""
from typing import Any, Iterable, Optional

from app.core.common import new_id, utcnow_iso
from app.core.db import get_db
from app.core.mailer import send_email


async def notify(
    user_ids: Iterable[str],
    title: str,
    body: str,
    link: Optional[str] = None,
    email: bool = False,
) -> int:
    db = get_db()
    count = 0
    for uid in {u for u in user_ids if u}:
        await db.notifications.insert_one(
            {"_id": new_id(), "user_id": uid, "title": title, "body": body, "link": link,
             "read": False, "created_at": utcnow_iso()}
        )
        count += 1
        if email:
            user = await db.users.find_one({"_id": uid})
            if user and user.get("email"):
                await send_email(user["email"], title, body)
    return count


async def user_ids_by_role(*roles: str) -> list[str]:
    rows = await get_db().users.find({"role": {"$in": list(roles)}, "active": {"$ne": False}}).to_list(500)
    return [r["_id"] for r in rows]


async def notify_roles(roles: Iterable[str], title: str, body: str, link: Optional[str] = None,
                       email: bool = False) -> int:
    return await notify(await user_ids_by_role(*roles), title, body, link, email)
