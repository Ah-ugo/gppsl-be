from typing import Literal, Optional
from pydantic import BaseModel, Field

TenderStatus = Literal["tracking", "submitted", "shortlisted", "won", "lost", "withdrawn"]
ContractStatus = Literal["draft", "active", "expired", "terminated", "renewed"]
ContractType = Literal["lump_sum", "reimbursable", "frame_agreement", "rental", "service", "other"]


class TenderCreate(BaseModel):
    title: str
    client_id: Optional[str] = None
    client_name: Optional[str] = None
    reference: Optional[str] = None
    status: TenderStatus = "tracking"
    value_ngn: float = 0
    submission_deadline: Optional[str] = None
    decision_date: Optional[str] = None
    requirements: Optional[str] = None
    notes: Optional[str] = None
    branch: Optional[str] = None


class TenderUpdate(BaseModel):
    title: Optional[str] = None
    status: Optional[TenderStatus] = None
    value_ngn: Optional[float] = None
    submission_deadline: Optional[str] = None
    decision_date: Optional[str] = None
    notes: Optional[str] = None


class ContractCreate(BaseModel):
    title: str
    client_id: Optional[str] = None
    client_name: Optional[str] = None
    project_id: Optional[str] = None
    tender_id: Optional[str] = None
    type: ContractType = "lump_sum"
    status: ContractStatus = "draft"
    value_ngn: float = 0
    currency: str = "NGN"
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    scope: Optional[str] = None
    deliverables: Optional[str] = None
    payment_terms: Optional[str] = None
    retention_pct: float = 0
    variation_orders: list[dict] = []  # [{description, value, approved_date}]
    document_url: Optional[str] = None
    notes: Optional[str] = None
    branch: Optional[str] = None


class ContractUpdate(BaseModel):
    title: Optional[str] = None
    status: Optional[ContractStatus] = None
    value_ngn: Optional[float] = None
    end_date: Optional[str] = None
    scope: Optional[str] = None
    deliverables: Optional[str] = None
    payment_terms: Optional[str] = None
    notes: Optional[str] = None


class VariationOrderIn(BaseModel):
    description: str
    value_ngn: float
    approved_date: Optional[str] = None


class QuotationLineIn(BaseModel):
    description: str
    unit: str = "item"
    qty: float = 1
    unit_price: float


class QuotationCreate(BaseModel):
    client_id: Optional[str] = None
    client_name: Optional[str] = None
    tender_id: Optional[str] = None
    project_id: Optional[str] = None
    title: str
    lines: list[QuotationLineIn]
    validity_days: int = 30
    discount_pct: float = 0
    vat_pct: float = 7.5
    payment_terms: Optional[str] = None
    notes: Optional[str] = None
    branch: Optional[str] = None


class QuotationUpdate(BaseModel):
    lines: Optional[list[QuotationLineIn]] = None
    discount_pct: Optional[float] = None
    validity_days: Optional[int] = None
    payment_terms: Optional[str] = None
    notes: Optional[str] = None
    status: Optional[Literal["draft", "sent", "accepted", "rejected", "expired"]] = None
