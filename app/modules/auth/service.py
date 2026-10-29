import re
import time
from collections import defaultdict, deque
from typing import Any, Optional

from app.core.config import get_settings
from app.core.db import get_db
from app.core.security import create_access_token, create_refresh_token, verify_password

_attempts: dict[str, deque] = defaultdict(deque)

NG_PHONE = re.compile(r"^(?:\+234|234|0)[789][01]\d{8}$")


def valid_ng_phone(phone: str) -> bool:
    return bool(NG_PHONE.match(re.sub(r"[\s\-()]", "", phone or "")))


def rate_limited(key: str) -> bool:
    """Sliding window: at most N login attempts per minute per key."""
    limit = get_settings().login_rate_limit_per_minute
    now = time.monotonic()
    q = _attempts[key]
    while q and now - q[0] > 60:
        q.popleft()
    if len(q) >= limit:
        return True
    q.append(now)
    return False


def reset_rate_limits() -> None:
    _attempts.clear()


def public_user(user: dict[str, Any]) -> dict[str, Any]:
    return {k: user.get(k) for k in ("name", "email", "role", "branch", "phone", "active")} | {
        "id": user.get("_id") or user.get("id")
    }


def issue_tokens(user: dict[str, Any]) -> dict[str, Any]:
    uid = user.get("_id") or user.get("id")
    return {
        "access_token": create_access_token(uid, user["role"]),
        "refresh_token": create_refresh_token(uid, user["role"]),
        "token_type": "bearer",
        "user": public_user(user),
    }


async def authenticate(email: str, password: str) -> Optional[dict[str, Any]]:
    user = await get_db().users.find_one({"email": email.strip().lower()})
    if not user or not user.get("active", True):
        return None
    return user if verify_password(password, user["password_hash"]) else None
