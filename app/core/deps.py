"""FastAPI dependencies. get_current_user and require_roles guard EVERY router."""
from typing import Any

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .db import get_db
from .security import decode_token

bearer = HTTPBearer(auto_error=False)

ALL_ROLES = ("md", "admin", "finance", "supervisor", "storekeeper", "hr", "branch_manager")


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
    return user


def require_roles(*roles: str):
    """Dependency factory: 403 unless the caller's role is in `roles`. md always passes
    only if listed, so every route states exactly who may call it."""
    allowed = set(roles)

    async def checker(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
        if user["role"] not in allowed:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"Role '{user['role']}' is not allowed here (requires: {', '.join(sorted(allowed))})",
            )
        return user

    return checker
