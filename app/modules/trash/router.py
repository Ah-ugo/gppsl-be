"""Trash router for viewing, restoring, and permanently purging deleted items."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.core.deps import client_ip, get_current_user, require_roles
from app.modules.trash import service

router = APIRouter(prefix="/trash", tags=["trash"], dependencies=[Depends(get_current_user)])

# All staff with management/finance/supervisor roles can access trash
ALLOWED_ROLES = ("md", "admin", "finance", "supervisor", "storekeeper", "hr", "branch_manager")


@router.get("")
async def list_trash(
    type: Optional[str] = Query(None, description="Filter by entity type (invoice, expense, equipment, etc.)"),
    search: Optional[str] = Query(None, description="Search term in title or description"),
    branch: Optional[str] = Query(None, description="Branch filter"),
    user: dict = Depends(require_roles(*ALLOWED_ROLES)),
):
    """List deleted items in trash with days remaining until automatic permanent purge."""
    return await service.list_trash(user, entity_type=type, search=search, branch=branch)


@router.post("/{trash_id}/restore")
async def restore_item(
    trash_id: str,
    request: Request,
    user: dict = Depends(require_roles(*ALLOWED_ROLES)),
):
    """Restore a deleted item back to its active operational collection."""
    try:
        return await service.restore_from_trash(trash_id, user, client_ip(request))
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.delete("/{trash_id}")
async def delete_permanently(
    trash_id: str,
    request: Request,
    user: dict = Depends(require_roles("md", "admin", "finance", "hr")),
):
    """Permanently delete an item immediately before the 30-day window expires."""
    try:
        return await service.permanently_delete(trash_id, user, client_ip(request))
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.post("/empty")
async def empty_trash(
    request: Request,
    user: dict = Depends(require_roles("md", "admin")),
):
    """Empty all items from the trash bin permanently."""
    return await service.empty_trash(user, client_ip(request))

