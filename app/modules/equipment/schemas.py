from typing import Literal, Optional

from pydantic import BaseModel, Field

Status = Literal["available", "deployed", "in_transit", "maintenance"]


class Certificate(BaseModel):
    name: str
    expiry_date: str = Field(description="YYYY-MM-DD")
    file_url: Optional[str] = None


class EquipmentCreate(BaseModel):
    name: str
    category: str
    serial: str
    branch: str
    status: Status = "available"
    purchase_cost: float = 0
    photos: list[str] = []
    run_hours: float = 0
    service_interval_hours: float = 500
    last_service_hours: float = 0
    certificates: list[Certificate] = []


class EquipmentUpdate(BaseModel):
    name: Optional[str] = None
    category: Optional[str] = None
    serial: Optional[str] = None
    branch: Optional[str] = None
    status: Optional[Status] = None
    purchase_cost: Optional[float] = None
    photos: Optional[list[str]] = None
    run_hours: Optional[float] = None
    service_interval_hours: Optional[float] = None
    last_service_hours: Optional[float] = None
    certificates: Optional[list[Certificate]] = None


class CheckoutIn(BaseModel):
    client_id: Optional[str] = None
    project_id: Optional[str] = None
    rate_type: Literal["daily", "weekly", "monthly", "fixed"] = "daily"
    rate: float = 0
    start_date: Optional[str] = None
    expected_return: Optional[str] = None
    receiver_name: str = Field(description="Person who receives the equipment and signs")
    condition: dict = Field(default_factory=dict, description="Checklist: {item: true/false}, notes")
    handover_photos: list[str] = Field(default_factory=list)
    signature_url: Optional[str] = None


class CheckinIn(BaseModel):
    return_hours: Optional[float] = Field(None, description="Run-hour meter reading at return")
    condition: dict = Field(default_factory=dict)
    flag_for_maintenance: bool = False
    photos: list[str] = Field(default_factory=list)
    signature_url: Optional[str] = None
    returned_by: Optional[str] = None


class MaintenanceCreate(BaseModel):
    equipment_id: str
    type: Literal["service", "repair", "inspection"] = "service"
    description: str = ""
    scheduled_date: Optional[str] = None
    cost: float = 0
    start_now: bool = False


class MaintenanceComplete(BaseModel):
    cost: Optional[float] = None
    notes: Optional[str] = None
    hours_at_service: Optional[float] = None


class FuelLogCreate(BaseModel):
    equipment_id: str
    project_id: Optional[str] = None
    litres: float = Field(gt=0)
    cost: float = Field(ge=0)
    date: Optional[str] = None
    station: Optional[str] = None


class RentalRequestCreate(BaseModel):
    equipment_id: str
    project_id: Optional[str] = None
    client_id: Optional[str] = None
    client_name: Optional[str] = None
    start_date: str = Field(description="YYYY-MM-DD")
    expected_return: str = Field(description="YYYY-MM-DD")
    rate_type: Literal["daily", "weekly", "monthly", "fixed"] = "daily"
    daily_rate: float = Field(0, ge=0)
    receiver_name: Optional[str] = None
    purpose: Optional[str] = None
    site_location: Optional[str] = None
    notes: Optional[str] = None


class RentalRequestDecision(BaseModel):
    decision: Literal["approve", "reject"]
    notes: Optional[str] = None

