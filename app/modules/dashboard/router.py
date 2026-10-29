from typing import Optional

from fastapi import APIRouter, Depends

from app.core.deps import get_current_user, require_roles

from . import service

router = APIRouter(tags=["dashboard"], dependencies=[Depends(get_current_user)])


@router.get("/dashboard")
async def dashboard(branch: Optional[str] = None, user: dict = Depends(require_roles("md", "admin", "finance"))):
    return await service.build(user["role"], branch or None)


@router.get("/dashboard/summary")
async def summary(branch: Optional[str] = None, _: dict = Depends(require_roles("md", "admin"))):
    return {"text": await service.daily_summary(branch or None), "source": "data"}
