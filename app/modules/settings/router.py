from typing import Any, Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from app.core.deps import client_ip, get_current_user, require_roles
from app.core.settings_store import get_settings_doc, update_settings_doc
from app.modules.audit import log

router = APIRouter(prefix="/settings", tags=["settings"], dependencies=[Depends(get_current_user)])


class CertificateTypeIn(BaseModel):
    name: str
    target: str = Field("both", description="staff, equipment, or both")
    validity_months: int = Field(12, ge=1, le=120)
    description: Optional[str] = None


class CategoryIn(BaseModel):
    name: str


class SettingsPatch(BaseModel):
    approval_limits: Optional[dict[str, float]] = None
    usd_rate: Optional[float] = Field(None, gt=0)
    branches: Optional[list[str]] = None
    notification_schedule: Optional[dict[str, str]] = None
    shift_start_hour: Optional[int] = Field(None, ge=0, le=23)
    late_grace_minutes: Optional[int] = Field(None, ge=0, le=120)
    payroll_monthly: Optional[float] = Field(None, ge=0)
    equipment_categories: Optional[list[str]] = None
    expense_categories: Optional[list[str]] = None
    service_categories: Optional[list[str]] = None
    certificate_types: Optional[list[dict[str, Any]]] = None


@router.get("")
async def read_settings(_: dict = Depends(require_roles("md", "admin", "finance", "hr", "supervisor", "storekeeper", "branch_manager"))):
    return await get_settings_doc()


@router.patch("")
async def patch_settings(body: SettingsPatch, request: Request, actor: dict = Depends(require_roles("md", "admin"))):
    patch = body.model_dump(exclude_none=True)
    result = await update_settings_doc(patch)
    await log(actor, "update", "settings", "main", f"Changed settings: {', '.join(patch)}", client_ip(request))
    return result


@router.get("/categories")
async def get_all_categories(_: dict = Depends(require_roles("md", "admin", "finance", "hr", "supervisor", "storekeeper", "branch_manager"))):
    doc = await get_settings_doc()
    return {
        "equipment": doc.get("equipment_categories", []),
        "expense": doc.get("expense_categories", []),
        "service": doc.get("service_categories", []),
    }


@router.post("/categories/{category_type}")
async def add_category(category_type: str, body: CategoryIn, actor: dict = Depends(require_roles("md", "admin", "supervisor", "branch_manager"))):
    key = f"{category_type}_categories" if not category_type.endswith("_categories") else category_type
    doc = await get_settings_doc()
    current = doc.get(key, [])
    cleaned_name = body.name.strip()
    if not cleaned_name:
        return current
    if cleaned_name not in current:
        current.append(cleaned_name)
        await update_settings_doc({key: current})
    return current


@router.delete("/categories/{category_type}/{category_name}")
async def delete_category(category_type: str, category_name: str, actor: dict = Depends(require_roles("md", "admin"))):
    key = f"{category_type}_categories" if not category_type.endswith("_categories") else category_type
    doc = await get_settings_doc()
    current = doc.get(key, [])
    updated = [c for c in current if c.lower() != category_name.lower().strip()]
    await update_settings_doc({key: updated})
    return updated


@router.get("/certificate-types")
async def list_certificate_types(_: dict = Depends(require_roles("md", "admin", "hr", "supervisor", "branch_manager"))):
    doc = await get_settings_doc()
    return doc.get("certificate_types", [])


@router.post("/certificate-types")
async def add_or_update_certificate_type(body: CertificateTypeIn, actor: dict = Depends(require_roles("md", "admin", "hr"))):
    doc = await get_settings_doc()
    current = doc.get("certificate_types", [])
    entry = body.model_dump()
    existing = [c for c in current if c["name"].lower() != body.name.lower().strip()]
    existing.append(entry)
    await update_settings_doc({"certificate_types": existing})
    return existing


@router.delete("/certificate-types/{name}")
async def delete_certificate_type(name: str, actor: dict = Depends(require_roles("md", "admin", "hr"))):
    doc = await get_settings_doc()
    current = doc.get("certificate_types", [])
    updated = [c for c in current if c["name"].lower() != name.lower().strip()]
    await update_settings_doc({"certificate_types": updated})
    return updated
