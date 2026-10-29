from typing import Any

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request

from app.core.common import clean, clean_many, new_id, utcnow_iso
from app.core.config import get_settings
from app.core.db import get_db
from app.core.deps import client_ip, get_current_user, require_roles
from app.core.security import decode_token, hash_password
from app.modules.audit import log

from . import service
from .schemas import DemoLoginIn, LoginIn, RefreshIn, TokenOut, UserCreate, UserUpdate

router = APIRouter(prefix="/auth", tags=["auth"])
users_router = APIRouter(prefix="/users", tags=["users"], dependencies=[Depends(get_current_user)])

DEMO_PASSWORD = "Demo@1234"


@router.post("/login", response_model=TokenOut)
async def login(body: LoginIn, request: Request):
    ip = client_ip(request)
    if service.rate_limited(f"{ip}:{body.email.lower()}"):
        raise HTTPException(429, "Too many login attempts. Wait a minute and try again.")
    user = await service.authenticate(body.email, body.password)
    if not user:
        raise HTTPException(401, "Incorrect email or password")
    await log(user | {"id": user["_id"]}, "login", "user", user["_id"], f"{user['name']} signed in", ip)
    return service.issue_tokens(user)


@router.post("/refresh", response_model=TokenOut)
async def refresh(body: RefreshIn):
    try:
        payload = decode_token(body.refresh_token, "refresh")
    except jwt.PyJWTError:
        raise HTTPException(401, "Invalid or expired refresh token")
    user = await get_db().users.find_one({"_id": payload["sub"]})
    if not user or not user.get("active", True):
        raise HTTPException(401, "User not found or disabled")
    return service.issue_tokens(user)


@router.get("/me")
async def me(user: dict[str, Any] = Depends(get_current_user)):
    return service.public_user(user)


@router.get("/demo-accounts")
async def demo_accounts():
    """Public list for the login page selector. Only available while DEMO_MODE=true."""
    if not get_settings().demo_mode:
        raise HTTPException(404, "Demo mode is off")
    rows = await get_db().users.find({"demo": True}).to_list(20)
    order = ["md", "admin", "finance", "supervisor", "storekeeper", "hr"]
    rows.sort(key=lambda r: order.index(r["role"]) if r["role"] in order else 99)
    return [{"role": r["role"], "name": r["name"], "email": r["email"]} for r in rows]


@router.post("/demo-login", response_model=TokenOut)
async def demo_login(body: DemoLoginIn, request: Request):
    if not get_settings().demo_mode:
        raise HTTPException(404, "Demo mode is off")
    user = await get_db().users.find_one({"role": body.role, "demo": True})
    if not user:
        raise HTTPException(404, f"No demo account for role {body.role}. Run seed.py")
    await log(user | {"id": user["_id"]}, "login", "user", user["_id"],
              f"{user['name']} signed in (demo)", client_ip(request))
    return service.issue_tokens(user)


# ---- User management (Settings page) -------------------------------------------------------
@users_router.get("")
async def list_users(_: dict = Depends(require_roles("md", "admin", "hr"))):
    rows = await get_db().users.find({}).sort("name", 1).to_list(1000)
    return clean_many(rows)


@users_router.post("", status_code=201)
async def create_user(body: UserCreate, request: Request, actor: dict = Depends(require_roles("md", "admin"))):
    db = get_db()
    email = body.email.strip().lower()
    if await db.users.find_one({"email": email}):
        raise HTTPException(409, "A user with that email already exists")
    if body.phone and not service.valid_ng_phone(body.phone):
        raise HTTPException(422, "Phone must be a Nigerian number, e.g. 0803 123 4567 or +234 803 123 4567")
    doc = {"_id": new_id(), "email": email, "name": body.name, "role": body.role, "branch": body.branch,
           "phone": body.phone, "active": True, "password_hash": hash_password(body.password),
           "created_at": utcnow_iso()}
    await db.users.insert_one(doc)
    await log(actor, "create", "user", doc["_id"], f"Created user {body.name} ({body.role})", client_ip(request))
    return clean(doc)


@users_router.patch("/{user_id}")
async def update_user(user_id: str, body: UserUpdate, request: Request,
                      actor: dict = Depends(require_roles("md", "admin"))):
    db = get_db()
    patch = body.model_dump(exclude_none=True)
    if "phone" in patch and not service.valid_ng_phone(patch["phone"]):
        raise HTTPException(422, "Phone must be a Nigerian number")
    if "password" in patch:
        patch["password_hash"] = hash_password(patch.pop("password"))
    if not patch:
        raise HTTPException(422, "Nothing to update")
    res = await db.users.update_one({"_id": user_id}, {"$set": patch})
    if res.matched_count == 0:
        raise HTTPException(404, "User not found")
    await log(actor, "update", "user", user_id, f"Updated user fields: {', '.join(k for k in patch if k != 'password_hash')}",
              client_ip(request))
    return clean(await db.users.find_one({"_id": user_id}))
