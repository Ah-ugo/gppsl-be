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
    roles = user.get("roles") or ([user["role"]] if user.get("role") else ["staff"])
    primary_role = user.get("role") or (roles[0] if roles else "staff")
    is_super = primary_role in {"admin", "md", "director"} or any(r in {"admin", "md", "director"} for r in roles)
    branch_access = user.get("branch_access")
    if not branch_access:
        branch_access = ["all"] if is_super else ([user.get("branch")] if user.get("branch") else ["all"])
    return {
        "id": user.get("_id") or user.get("id"),
        "name": user.get("name"),
        "email": user.get("email"),
        "role": primary_role,
        "roles": roles,
        "branch": user.get("branch"),
        "branch_access": branch_access,
        "phone": user.get("phone"),
        "active": user.get("active", True),
    }


def issue_tokens(user: dict[str, Any]) -> dict[str, Any]:
    uid = user.get("_id") or user.get("id")
    primary_role = user.get("role") or (user.get("roles", ["staff"])[0])
    return {
        "access_token": create_access_token(uid, primary_role),
        "refresh_token": create_refresh_token(uid, primary_role),
        "token_type": "bearer",
        "user": public_user(user),
    }


async def authenticate(email: str, password: str) -> Optional[dict[str, Any]]:
    user = await get_db().users.find_one({"email": email.strip().lower()})
    if not user or not user.get("active", True):
        return None
    return user if verify_password(password, user["password_hash"]) else None
