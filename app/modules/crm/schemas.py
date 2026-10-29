from typing import Literal, Optional
from pydantic import BaseModel, EmailStr, Field

Stage = Literal["lead", "qualified", "proposal", "negotiation", "won", "lost"]
ClientType = Literal["company", "individual"]


class ContactIn(BaseModel):
    name: str
    title: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    is_primary: bool = False


class ClientCreate(BaseModel):
    name: str
    type: ClientType = "company"
    industry: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    website: Optional[str] = None
    vat_number: Optional[str] = None
    contacts: list[ContactIn] = []
    notes: Optional[str] = None
    branch: Optional[str] = None


class ClientUpdate(BaseModel):
    name: Optional[str] = None
    industry: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    website: Optional[str] = None
    vat_number: Optional[str] = None
    contacts: Optional[list[ContactIn]] = None
    notes: Optional[str] = None
    branch: Optional[str] = None


class InteractionIn(BaseModel):
    client_id: str
    type: Literal["call", "email", "meeting", "site_visit", "other"] = "call"
    summary: str
    date: Optional[str] = None
    next_action: Optional[str] = None
    next_action_date: Optional[str] = None


class LeadCreate(BaseModel):
    title: str
    client_id: Optional[str] = None
    client_name_free: Optional[str] = None  # if not yet a client
    stage: Stage = "lead"
    value_ngn: float = 0
    probability_pct: float = 50
    owner_id: Optional[str] = None
    owner_name: Optional[str] = None
    expected_close: Optional[str] = None
    source: Optional[str] = None
    notes: Optional[str] = None


class LeadUpdate(BaseModel):
    title: Optional[str] = None
    stage: Optional[Stage] = None
    value_ngn: Optional[float] = None
    probability_pct: Optional[float] = None
    expected_close: Optional[str] = None
    notes: Optional[str] = None
    owner_id: Optional[str] = None
    owner_name: Optional[str] = None
