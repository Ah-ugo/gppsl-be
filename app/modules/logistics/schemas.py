from typing import Literal, Optional
from pydantic import BaseModel, Field

TripStatus = Literal["planned", "in_progress", "completed", "cancelled"]
VehicleStatus = Literal["available", "in_use", "maintenance", "off_road"]


class VehicleCreate(BaseModel):
    name: str
    plate: str
    type: str = "truck"  # truck, pickup, bus, crane, etc.
    branch: Optional[str] = None
    status: VehicleStatus = "available"
    capacity_kg: Optional[float] = None
    fuel_type: str = "diesel"
    driver_id: Optional[str] = None
    driver_name: Optional[str] = None
    notes: Optional[str] = None


class VehicleUpdate(BaseModel):
    name: Optional[str] = None
    plate: Optional[str] = None
    status: Optional[VehicleStatus] = None
    driver_id: Optional[str] = None
    driver_name: Optional[str] = None
    branch: Optional[str] = None
    notes: Optional[str] = None


class TripCreate(BaseModel):
    vehicle_id: str
    driver_id: Optional[str] = None
    driver_name: Optional[str] = None
    project_id: Optional[str] = None
    origin: str
    destination: str
    cargo_description: Optional[str] = None
    cargo_weight_kg: Optional[float] = None
    planned_date: Optional[str] = None
    notes: Optional[str] = None


class TripUpdate(BaseModel):
    status: Optional[TripStatus] = None
    departure_time: Optional[str] = None
    arrival_time: Optional[str] = None
    odometer_start: Optional[float] = None
    odometer_end: Optional[float] = None
    fuel_cost: Optional[float] = None
    driver_allowance: Optional[float] = None
    notes: Optional[str] = None
    delay_reason: Optional[str] = None


class FuelLogIn(BaseModel):
    vehicle_id: str
    project_id: Optional[str] = None
    litres: float = Field(gt=0)
    cost: float = Field(ge=0)
    date: Optional[str] = None
    station: Optional[str] = None
