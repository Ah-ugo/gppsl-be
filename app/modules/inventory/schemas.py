from typing import Literal, Optional
from pydantic import BaseModel, Field

ItemType = Literal["material", "spare_part", "tool", "consumable", "other"]
MovementType = Literal["receipt", "issue", "return", "adjustment", "transfer"]


class StockItemCreate(BaseModel):
    name: str
    code: Optional[str] = None
    type: ItemType = "material"
    unit: str = "pcs"
    qty_on_hand: float = 0
    reorder_level: float = 0
    unit_cost: float = 0
    location: Optional[str] = None  # warehouse/branch
    branch: Optional[str] = None
    notes: Optional[str] = None


class StockItemUpdate(BaseModel):
    name: Optional[str] = None
    unit: Optional[str] = None
    reorder_level: Optional[float] = None
    unit_cost: Optional[float] = None
    location: Optional[str] = None
    branch: Optional[str] = None
    notes: Optional[str] = None


class MovementIn(BaseModel):
    item_id: str
    type: MovementType
    qty: float = Field(gt=0)
    project_id: Optional[str] = None
    reference: Optional[str] = None  # PO number, GRN number, etc.
    notes: Optional[str] = None
    unit_cost: Optional[float] = None


class SupplierCreate(BaseModel):
    name: str
    contact_name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    category: Optional[str] = None  # materials, services, equipment
    notes: Optional[str] = None


class SupplierUpdate(BaseModel):
    name: Optional[str] = None
    contact_name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    category: Optional[str] = None
    notes: Optional[str] = None


class POLineIn(BaseModel):
    item_id: Optional[str] = None
    description: str
    qty: float
    unit: str = "pcs"
    unit_price: float


class PurchaseOrderCreate(BaseModel):
    supplier_id: str
    lines: list[POLineIn]
    project_id: Optional[str] = None
    notes: Optional[str] = None
    delivery_address: Optional[str] = None
    expected_delivery: Optional[str] = None


class GoodsReceiptIn(BaseModel):
    po_id: str
    lines: list[dict]  # [{line_index, qty_received, condition_ok, notes}]
    received_by: Optional[str] = None
    received_date: Optional[str] = None
    notes: Optional[str] = None
