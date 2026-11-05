"""FastAPI dependencies. get_current_user and require_roles guard EVERY router."""
from typing import Any

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .db import get_db
from .security import decode_token

bearer = HTTPBearer(auto_error=False)

ALL_ROLES = ("md", "admin", "finance", "supervisor", "storekeeper", "hr", "branch_manager", "staff")


def client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


async def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> dict[str, Any]:
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    try:
        payload = decode_token(creds.credentials, "access")
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token")
    user = await get_db().users.find_one({"_id": payload["sub"]})
    if not user or not user.get("active", True):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found or disabled")
    user["id"] = user["_id"]
    if "roles" not in user or not user["roles"]:
        user["roles"] = [user["role"]] if user.get("role") else ["staff"]
    if not user.get("role"):
        user["role"] = user["roles"][0]

    # Ensure branch_access is resolved and present
    user_roles = set(user.get("roles") or [])
    is_super = bool(user_roles & {"md", "admin", "director"})
    if "branch_access" not in user or not user["branch_access"]:
        staff_rec = await get_db().staff.find_one({"$or": [{"user_id": user["_id"]}, {"email": user.get("email")}]})
        if staff_rec and staff_rec.get("branch_access"):
            user["branch_access"] = staff_rec["branch_access"]
        elif is_super:
            user["branch_access"] = ["all"]
        elif user.get("branch"):
            user["branch_access"] = [user["branch"]]
        else:
            user["branch_access"] = ["all"] if is_super else ["Port Harcourt HQ"]

    return user


def require_roles(*roles: str):
    """Dependency factory: 403 unless the caller's role is in `roles`. md always passes
    only if listed, so every route states exactly who may call it."""
    allowed = set(roles)

    async def checker(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
        user_roles = set(user.get("roles") or [])
        if user.get("role"):
            user_roles.add(user["role"])
        if not (user_roles & allowed):
            display_role = ", ".join(sorted(user_roles)) if user_roles else user.get("role", "none")
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"Role '{display_role}' is not allowed here (requires: {', '.join(sorted(allowed))})",
            )
        return user

    return checker
