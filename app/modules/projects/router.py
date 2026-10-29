from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request

from app.core.common import clean, clean_many, new_id, utcnow_iso
from app.core.db import get_db
from app.core.deps import client_ip, get_current_user, require_roles
from app.modules.audit import log

from . import service
from .schemas import ClientIn, ClientUpdate, ProjectIn, ProjectUpdate

router = APIRouter(tags=["projects"], dependencies=[Depends(get_current_user)])

ALL = ("md", "admin", "finance", "supervisor", "storekeeper", "hr")
MANAGE = ("md", "admin")


# ---- Clients --------------------------------------------------------------------------------
@router.get("/clients")
async def list_clients(_: dict = Depends(require_roles(*ALL))):
    return clean_many(await get_db().clients.find({}).sort("name", 1).to_list(1000))


@router.post("/clients", status_code=201)
async def create_client(body: ClientIn, request: Request, user: dict = Depends(require_roles("md", "admin", "finance"))):
    doc = {"_id": new_id(), **body.model_dump(), "created_at": utcnow_iso()}
    await get_db().clients.insert_one(doc)
    await log(user, "create", "client", doc["_id"], f"Added client {body.name}", client_ip(request))
    return clean(doc)


@router.patch("/clients/{client_id}")
async def update_client(client_id: str, body: ClientUpdate, request: Request,
                        user: dict = Depends(require_roles("md", "admin", "finance"))):
    patch = body.model_dump(exclude_none=True)
    res = await get_db().clients.update_one({"_id": client_id}, {"$set": patch})
    if res.matched_count == 0:
        raise HTTPException(404, "Client not found")
    await log(user, "update", "client", client_id, f"Updated client: {', '.join(patch)}", client_ip(request))
    return clean(await get_db().clients.find_one({"_id": client_id}))


# ---- Projects -------------------------------------------------------------------------------
@router.get("/projects")
async def list_projects(status: Optional[str] = None, branch: Optional[str] = None, user: dict = Depends(require_roles(*ALL))):
    q: dict[str, Any] = {}
    if status:
        q["status"] = status
    if branch:
        q["branch"] = branch
    rows = await get_db().projects.find(q).sort("name", 1).to_list(1000)
    names = await service.client_name_map()
    return [await service.view(r, user["role"], names) for r in rows]


@router.post("/projects", status_code=201)
async def create_project(body: ProjectIn, request: Request, user: dict = Depends(require_roles(*MANAGE))):
    if not await get_db().clients.find_one({"_id": body.client_id}):
        raise HTTPException(422, "Unknown client")
    doc = {"_id": new_id(), **body.model_dump(), "created_at": utcnow_iso()}
    await get_db().projects.insert_one(doc)
    await log(user, "create", "project", doc["_id"], f"Created project {body.name}", client_ip(request))
    return await service.view(doc, user["role"], await service.client_name_map())


@router.get("/projects/{project_id}")
async def get_project(project_id: str, user: dict = Depends(require_roles(*ALL))):
    p = await get_db().projects.find_one({"_id": project_id})
    if not p:
        raise HTTPException(404, "Project not found")
    return await service.view(p, user["role"], await service.client_name_map())


@router.patch("/projects/{project_id}")
async def update_project(project_id: str, body: ProjectUpdate, request: Request,
                         user: dict = Depends(require_roles("md", "admin", "supervisor"))):
    patch = body.model_dump(exclude_none=True)
    if user["role"] == "supervisor":  # supervisors may only update progress and status
        patch = {k: v for k, v in patch.items() if k in ("progress", "status")}
    if not patch:
        raise HTTPException(422, "Nothing to update")
    res = await get_db().projects.update_one({"_id": project_id}, {"$set": patch})
    if res.matched_count == 0:
        raise HTTPException(404, "Project not found")
    await log(user, "update", "project", project_id, f"Updated project: {', '.join(patch)}", client_ip(request))
    p = await get_db().projects.find_one({"_id": project_id})
    return await service.view(p, user["role"], await service.client_name_map())


@router.delete("/projects/{project_id}")
async def delete_project(project_id: str, request: Request, user: dict = Depends(require_roles(*MANAGE))):
    p = await get_db().projects.find_one({"_id": project_id})
    if not p:
        raise HTTPException(404, "Project not found")
    if await get_db().rentals.find_one({"project_id": project_id, "actual_return": None}):
        raise HTTPException(409, "Project has equipment still deployed")
    await get_db().projects.delete_one({"_id": project_id})
    await log(user, "delete", "project", project_id, f"Deleted project {p['name']}", client_ip(request))
    return {"ok": True}
