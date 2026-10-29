from typing import Literal, Optional

from pydantic import BaseModel, Field


class ClientIn(BaseModel):
    name: str
    contact_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    payment_terms_days: int = 90


class ClientUpdate(BaseModel):
    name: Optional[str] = None
    contact_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    payment_terms_days: Optional[int] = None


class Coordinates(BaseModel):
    lat: float
    lng: float


class ProjectIn(BaseModel):
    client_id: str
    name: str
    location: str
    coordinates: Optional[Coordinates] = None
    branch: str
    budget: float = Field(ge=0)
    status: Literal["active", "completed", "on_hold"] = "active"
    progress: float = Field(0, ge=0, le=100)
    start: str
    end: str


class ProjectUpdate(BaseModel):
    client_id: Optional[str] = None
    name: Optional[str] = None
    location: Optional[str] = None
    coordinates: Optional[Coordinates] = None
    branch: Optional[str] = None
    budget: Optional[float] = Field(None, ge=0)
    status: Optional[Literal["active", "completed", "on_hold"]] = None
    progress: Optional[float] = Field(None, ge=0, le=100)
    start: Optional[str] = None
    end: Optional[str] = None
