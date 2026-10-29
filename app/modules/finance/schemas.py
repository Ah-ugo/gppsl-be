from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

CATEGORIES = [
    "fuel", "materials", "transport", "accommodation", "meals",
    "equipment", "maintenance", "labour", "office", "other"
]


class ExpenseIn(BaseModel):
    project_id: Optional[str] = None
    category: str = "other"
    amount: float = Field(gt=0)
    currency: Literal["NGN", "USD"] = "NGN"
    vendor: str
    date: Optional[str] = None
    receipt_url: Optional[str] = None
    notes: Optional[str] = None


class DecisionIn(BaseModel):
    comment: Optional[str] = None


class InvoiceItem(BaseModel):
    description: str
    quantity: float = Field(1.0, ge=0)
    unit: str = "unit"
    rate: float = Field(0.0, ge=0)
    amount: float = Field(0.0, ge=0)


class InvoiceIn(BaseModel):
    client_id: str
    project_id: Optional[str] = None
    service_type: Optional[str] = "Services rendered"
    number: Optional[str] = None
    amount: float = Field(gt=0)
    subtotal: Optional[float] = None
    vat_included: bool = True
    vat_rate: Optional[float] = 0.075
    wht_rate: Optional[float] = 0.0
    items: list[InvoiceItem] = []
    currency: Literal["NGN", "USD"] = "NGN"
    issue_date: str
    due_date: str
    payment_terms: Optional[str] = "Payment within 30 days of invoice date"
    notes: Optional[str] = None
    bank_details: Optional[dict[str, Any]] = None
    status: Literal["draft", "sent", "part_paid", "paid", "overdue"] = "sent"


class InvoiceUpdate(BaseModel):
    client_id: Optional[str] = None
    project_id: Optional[str] = None
    service_type: Optional[str] = None
    number: Optional[str] = None
    amount: Optional[float] = Field(None, gt=0)
    subtotal: Optional[float] = None
    vat_included: Optional[bool] = None
    vat_rate: Optional[float] = None
    wht_rate: Optional[float] = None
    items: Optional[list[InvoiceItem]] = None
    currency: Optional[Literal["NGN", "USD"]] = None
    issue_date: Optional[str] = None
    due_date: Optional[str] = None
    payment_terms: Optional[str] = None
    notes: Optional[str] = None
    bank_details: Optional[dict[str, Any]] = None
    status: Optional[Literal["draft", "sent", "part_paid", "paid", "overdue"]] = None


class PayIn(BaseModel):
    amount: Optional[float] = Field(None, gt=0, description="Omit to mark fully paid")
    payment_method: str = "Bank Transfer"
    reference: Optional[str] = None
    date: Optional[str] = None
    notes: Optional[str] = None


class ReceiptIn(BaseModel):
    invoice_id: str
    client_id: Optional[str] = None
    amount: float = Field(gt=0)
    payment_method: str = "Bank Transfer"
    reference: Optional[str] = None
    date: Optional[str] = None
    notes: Optional[str] = None


class ReminderIn(BaseModel):
    to: Optional[str] = None
    subject: Optional[str] = None
    body: Optional[str] = None


class PayableIn(BaseModel):
    vendor: str
    amount: float = Field(gt=0)
    due_date: str
    description: Optional[str] = None
    category: Optional[str] = "materials"
    status: Literal["unpaid", "paid"] = "unpaid"


class PayableUpdate(BaseModel):
    vendor: Optional[str] = None
    amount: Optional[float] = Field(None, gt=0)
    due_date: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    status: Optional[Literal["unpaid", "paid"]] = None
