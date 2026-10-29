from typing import Literal, Optional

from pydantic import BaseModel, Field

CERT_TYPES = ["BOSIET", "HUET", "H2S", "First aid", "Medical", "Equipment licence"]


class StaffCreate(BaseModel):
    user_id: Optional[str] = None
    staff_id_code: Optional[str] = None
    name: str
    position: str
    branch: str
    branch_access: list[str] = ["all"]
    department: Optional[str] = "Operations"
    employment_type: Literal[
        "permanent", "contract", "technician", "cleaner", "yard_labor", "driver", "security"
    ] = "permanent"
    phone: Optional[str] = None
    email: Optional[str] = None
    gender: Optional[str] = None
    dob: Optional[str] = None
    address: Optional[str] = None
    emergency_contact_name: Optional[str] = None
    emergency_contact_phone: Optional[str] = None
    emergency_contact_relationship: Optional[str] = None
    bank_name: Optional[str] = None
    account_number: Optional[str] = None
    account_name: Optional[str] = None
    daily_rate: float = Field(15000, ge=0)
    home_site: Optional[str] = None
    date_joined: Optional[str] = None
    active: bool = True


class StaffUpdate(BaseModel):
    user_id: Optional[str] = None
    staff_id_code: Optional[str] = None
    name: Optional[str] = None
    position: Optional[str] = None
    branch: Optional[str] = None
    branch_access: Optional[list[str]] = None
    department: Optional[str] = None
    employment_type: Optional[
        Literal["permanent", "contract", "technician", "cleaner", "yard_labor", "driver", "security"]
    ] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    gender: Optional[str] = None
    dob: Optional[str] = None
    address: Optional[str] = None
    emergency_contact_name: Optional[str] = None
    emergency_contact_phone: Optional[str] = None
    emergency_contact_relationship: Optional[str] = None
    bank_name: Optional[str] = None
    account_number: Optional[str] = None
    account_name: Optional[str] = None
    daily_rate: Optional[float] = Field(None, ge=0)
    home_site: Optional[str] = None
    date_joined: Optional[str] = None
    active: Optional[bool] = None


class CertIn(BaseModel):
    type: str
    expiry: str = Field(description="YYYY-MM-DD")


class CertsUpdate(BaseModel):
    certifications: list[CertIn]


class FaceRegisterIn(BaseModel):
    consent: bool
    descriptors: list[list[float]] = Field(description="3 face-api.js descriptors (128 numbers each): front, left, right")


class FaceDecisionIn(BaseModel):
    decision: Literal["approve", "reject"]
    comment: Optional[str] = None


class SiteIn(BaseModel):
    name: str
    branch: str
    location_type: Literal["branch_office", "field_base", "client_site", "rig_offshore", "warehouse", "fabrication_yard"] = "branch_office"
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    radius_m: float = Field(200, ge=20, le=5000)
    address: Optional[str] = None
    contact_person: Optional[str] = None
    contact_phone: Optional[str] = None
    active: bool = True


class SiteUpdate(BaseModel):
    name: Optional[str] = None
    branch: Optional[str] = None
    location_type: Optional[Literal["branch_office", "field_base", "client_site", "rig_offshore", "warehouse", "fabrication_yard"]] = None
    lat: Optional[float] = Field(None, ge=-90, le=90)
    lng: Optional[float] = Field(None, ge=-180, le=180)
    radius_m: Optional[float] = Field(None, ge=20, le=5000)
    address: Optional[str] = None
    contact_person: Optional[str] = None
    contact_phone: Optional[str] = None
    active: Optional[bool] = None


class AssignmentIn(BaseModel):
    staff_id: str
    project_id: str
    role: Optional[str] = None
    required_certs: list[str] = []
    start: Optional[str] = None
    end: Optional[str] = None


class ClockIn(BaseModel):
    id: str = Field(min_length=8, description="Client-generated UUID (idempotency key)")
    descriptor: Optional[list[float]] = None
    selfie_url: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None
    accuracy: Optional[float] = None
    phone_time: str
    liveness: bool = True
    offline: bool = False


class ReviewIn(BaseModel):
    decision: Literal["approve", "reject"]
    comment: Optional[str] = None


class ManualIn(BaseModel):
    staff_id: str
    note: str = Field(min_length=3, description="Why manual (emergency reason)")
    time: Optional[str] = None
