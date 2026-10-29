"""Inventory, Stores, and Procurement router."""
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.core.common import clean, clean_many, new_id, today, utcnow_iso
from app.core.db import get_db
from app.core.deps import client_ip, get_current_user, require_roles
from app.modules.audit import log
from app.modules.notifications import notify_roles

from .schemas import (GoodsReceiptIn, MovementIn, POLineIn, PurchaseOrderCreate,
                      StockItemCreate, StockItemUpdate, SupplierCreate, SupplierUpdate)

ALL = ("md", "admin", "supervisor", "storekeeper", "finance", "hr")
STORE = ("md", "admin", "storekeeper")
FIN = ("md", "admin", "finance")

router = APIRouter(tags=["inventory"], dependencies=[Depends(get_current_user)])


# ── Stock items ───────────────────────────────────────────────────────────────

@router.get("/stock")
async def list_stock(
    search: Optional[str] = None, type: Optional[str] = None,
    low_stock: bool = False, branch: Optional[str] = None,
    _: dict = Depends(require_roles(*ALL)),
):
    q: dict[str, Any] = {}
    if type:
        q["type"] = type
    if branch:
        q["branch"] = branch
    if search:
        q["$or"] = [{"name": {"$regex": search, "$options": "i"}},
                    {"code": {"$regex": search, "$options": "i"}}]
    rows = await get_db().stock_items.find(q).sort("name", 1).to_list(2000)
    if low_stock:
        rows = [r for r in rows if float(r.get("qty_on_hand") or 0) <= float(r.get("reorder_level") or 0)]
    return clean_many(rows)


@router.post("/stock", status_code=201)
async def create_stock_item(body: StockItemCreate, request: Request, user: dict = Depends(require_roles(*STORE))):
    doc = {"_id": new_id(), **body.model_dump(), "created_by": user["name"], "created_at": utcnow_iso()}
    await get_db().stock_items.insert_one(doc)
    await log(user, "create", "stock_item", doc["_id"], f"Added stock item {doc['name']}", client_ip(request))
    return clean(doc)


@router.patch("/stock/{item_id}")
async def update_stock_item(item_id: str, body: StockItemUpdate, request: Request,
                             user: dict = Depends(require_roles(*STORE))):
    item = await _item_or_404(item_id)
    patch = body.model_dump(exclude_none=True)
    if not patch:
        raise HTTPException(422, "Nothing to update")
    await get_db().stock_items.update_one({"_id": item_id}, {"$set": patch})
    await log(user, "update", "stock_item", item_id, f"Updated {item['name']}", client_ip(request))
    return clean(await get_db().stock_items.find_one({"_id": item_id}))


@router.delete("/stock/{item_id}")
async def delete_stock_item(item_id: str, request: Request, user: dict = Depends(require_roles("md", "admin"))):
    item = await _item_or_404(item_id)
    await get_db().stock_items.delete_one({"_id": item_id})
    await log(user, "delete", "stock_item", item_id, f"Deleted {item['name']}", client_ip(request))
    return {"ok": True}


# ── Stock movements ───────────────────────────────────────────────────────────

@router.get("/stock/movements")
async def list_movements(item_id: Optional[str] = None, project_id: Optional[str] = None,
                          limit: int = Query(200, le=1000), _: dict = Depends(require_roles(*ALL))):
    q: dict[str, Any] = {}
    if item_id:
        q["item_id"] = item_id
    if project_id:
        q["project_id"] = project_id
    rows = await get_db().stock_movements.find(q).sort("created_at", -1).to_list(limit)
    return clean_many(rows)


@router.post("/stock/movements", status_code=201)
async def record_movement(body: MovementIn, request: Request, user: dict = Depends(require_roles(*STORE))):
    item = await _item_or_404(body.item_id)
    db = get_db()
    current_qty = float(item.get("qty_on_hand") or 0)
    # direction
    if body.type in ("issue",):
        if current_qty < body.qty:
            raise HTTPException(409, f"Insufficient stock: {current_qty} {item['unit']} available")
        new_qty = current_qty - body.qty
    elif body.type in ("receipt", "return"):
        new_qty = current_qty + body.qty
    elif body.type == "adjustment":
        new_qty = body.qty  # absolute value
    elif body.type == "transfer":
        new_qty = current_qty - body.qty  # transfer out; destination creates receipt
    else:
        new_qty = current_qty

    doc = {
        "_id": new_id(), **body.model_dump(),
        "item_name": item["name"], "unit": item["unit"],
        "qty_before": current_qty, "qty_after": new_qty,
        "unit_cost": body.unit_cost or item.get("unit_cost"),
        "date": today().isoformat(),
        "recorded_by": {"id": user["id"], "name": user["name"]},
        "created_at": utcnow_iso(),
    }
    await db.stock_movements.insert_one(doc)
    await db.stock_items.update_one({"_id": body.item_id}, {"$set": {"qty_on_hand": new_qty}})

    # low-stock alert
    if new_qty <= float(item.get("reorder_level") or 0) and body.type in ("issue", "transfer", "adjustment"):
        await notify_roles(["md", "admin", "storekeeper"], "Low stock alert",
                           f"{item['name']} is at {new_qty} {item['unit']} (reorder at {item.get('reorder_level')})",
                           "/inventory")

    await log(user, "movement", "stock", doc["_id"],
              f"{body.type.upper()} {body.qty} {item['unit']} of {item['name']}", client_ip(request))
    return clean(doc)


# ── Suppliers ─────────────────────────────────────────────────────────────────

@router.get("/suppliers")
async def list_suppliers(search: Optional[str] = None, _: dict = Depends(require_roles(*ALL))):
    q: dict[str, Any] = {}
    if search:
        q["$or"] = [{"name": {"$regex": search, "$options": "i"}},
                    {"category": {"$regex": search, "$options": "i"}}]
    return clean_many(await get_db().suppliers.find(q).sort("name", 1).to_list(500))


@router.post("/suppliers", status_code=201)
async def create_supplier(body: SupplierCreate, request: Request, user: dict = Depends(require_roles(*STORE))):
    doc = {"_id": new_id(), **body.model_dump(), "created_by": user["name"], "created_at": utcnow_iso()}
    await get_db().suppliers.insert_one(doc)
    await log(user, "create", "supplier", doc["_id"], f"Added supplier {doc['name']}", client_ip(request))
    return clean(doc)


@router.patch("/suppliers/{supplier_id}")
async def update_supplier(supplier_id: str, body: SupplierUpdate, request: Request,
                           user: dict = Depends(require_roles(*STORE))):
    sup = await get_db().suppliers.find_one({"_id": supplier_id})
    if not sup:
        raise HTTPException(404, "Supplier not found")
    patch = body.model_dump(exclude_none=True)
    await get_db().suppliers.update_one({"_id": supplier_id}, {"$set": patch})
    await log(user, "update", "supplier", supplier_id, f"Updated supplier {sup['name']}", client_ip(request))
    return clean(await get_db().suppliers.find_one({"_id": supplier_id}))


@router.delete("/suppliers/{supplier_id}")
async def delete_supplier(supplier_id: str, request: Request, user: dict = Depends(require_roles("md", "admin"))):
    sup = await get_db().suppliers.find_one({"_id": supplier_id})
    if not sup:
        raise HTTPException(404, "Supplier not found")
    await get_db().suppliers.delete_one({"_id": supplier_id})
    await log(user, "delete", "supplier", supplier_id, f"Deleted supplier {sup['name']}", client_ip(request))
    return {"ok": True}


# ── Purchase Orders ───────────────────────────────────────────────────────────

@router.get("/purchase-orders")
async def list_pos(status: Optional[str] = None, supplier_id: Optional[str] = None,
                   _: dict = Depends(require_roles(*ALL))):
    q: dict[str, Any] = {}
    if status:
        q["status"] = status
    if supplier_id:
        q["supplier_id"] = supplier_id
    return clean_many(await get_db().purchase_orders.find(q).sort("created_at", -1).to_list(500))


@router.post("/purchase-orders", status_code=201)
async def create_po(body: PurchaseOrderCreate, request: Request, user: dict = Depends(require_roles(*STORE))):
    db = get_db()
    sup = await db.suppliers.find_one({"_id": body.supplier_id})
    if not sup:
        raise HTTPException(422, "Supplier not found")
    total = sum(l.qty * l.unit_price for l in body.lines)
    po_number = f"PO-{await db.purchase_orders.count_documents({}) + 1:04d}"
    doc = {
        "_id": new_id(), "number": po_number, "supplier_id": body.supplier_id,
        "supplier_name": sup["name"], "lines": [l.model_dump() for l in body.lines],
        "total": total, "project_id": body.project_id, "notes": body.notes,
        "delivery_address": body.delivery_address, "expected_delivery": body.expected_delivery,
        "status": "draft", "raised_by": {"id": user["id"], "name": user["name"]},
        "created_at": utcnow_iso(),
    }
    await db.purchase_orders.insert_one(doc)
    await notify_roles(["md", "finance"], "Purchase Order raised",
                       f"{po_number} for ₦{total:,.0f} to {sup['name']}", "/inventory")
    await log(user, "create", "purchase_order", doc["_id"], f"Created {po_number} ₦{total:,.0f}", client_ip(request))
    return clean(doc)


@router.patch("/purchase-orders/{po_id}/status")
async def update_po_status(po_id: str, body: dict, request: Request, user: dict = Depends(require_roles(*FIN))):
    po = await get_db().purchase_orders.find_one({"_id": po_id})
    if not po:
        raise HTTPException(404, "PO not found")
    new_status = body.get("status")
    if new_status not in ("draft", "approved", "sent", "received", "cancelled"):
        raise HTTPException(422, "Invalid status")
    await get_db().purchase_orders.update_one({"_id": po_id},
                                               {"$set": {"status": new_status, "updated_at": utcnow_iso()}})
    await log(user, "update", "purchase_order", po_id, f"PO {po['number']} → {new_status}", client_ip(request))
    return clean(await get_db().purchase_orders.find_one({"_id": po_id}))


# ── Goods Receipt ─────────────────────────────────────────────────────────────

@router.post("/goods-receipts", status_code=201)
async def receive_goods(body: GoodsReceiptIn, request: Request, user: dict = Depends(require_roles(*STORE))):
    db = get_db()
    po = await db.purchase_orders.find_one({"_id": body.po_id})
    if not po:
        raise HTTPException(404, "PO not found")
    if po["status"] not in ("approved", "sent"):
        raise HTTPException(409, f"PO is {po['status']} — can only receive against approved/sent orders")

    # Update stock for items with item_id
    for line in body.lines:
        idx = line.get("line_index")
        if idx is None or idx >= len(po["lines"]):
            continue
        po_line = po["lines"][idx]
        qty = float(line.get("qty_received") or 0)
        item_id = po_line.get("item_id")
        if item_id and qty > 0:
            item = await db.stock_items.find_one({"_id": item_id})
            if item:
                new_qty = float(item.get("qty_on_hand") or 0) + qty
                await db.stock_items.update_one({"_id": item_id}, {"$set": {"qty_on_hand": new_qty}})
                await db.stock_movements.insert_one({
                    "_id": new_id(), "item_id": item_id, "item_name": item["name"],
                    "unit": item.get("unit", "pcs"), "type": "receipt",
                    "qty": qty, "qty_before": float(item.get("qty_on_hand") or 0), "qty_after": new_qty,
                    "reference": po["number"], "project_id": po.get("project_id"),
                    "unit_cost": po_line.get("unit_price"), "date": body.received_date or today().isoformat(),
                    "recorded_by": {"id": user["id"], "name": user["name"]}, "created_at": utcnow_iso(),
                })

    grn_number = f"GRN-{await db.goods_receipts.count_documents({}) + 1:04d}"
    doc = {
        "_id": new_id(), "number": grn_number, **body.model_dump(),
        "po_number": po["number"], "received_by": body.received_by or user["name"],
        "received_date": body.received_date or today().isoformat(),
        "recorded_by": {"id": user["id"], "name": user["name"]}, "created_at": utcnow_iso(),
    }
    await db.goods_receipts.insert_one(doc)
    await db.purchase_orders.update_one({"_id": body.po_id},
                                         {"$set": {"status": "received", "grn_id": doc["_id"]}})
    await log(user, "create", "goods_receipt", doc["_id"], f"Received goods {grn_number} for {po['number']}", client_ip(request))
    return clean(doc)


@router.get("/goods-receipts")
async def list_grns(po_id: Optional[str] = None, _: dict = Depends(require_roles(*ALL))):
    q: dict[str, Any] = {}
    if po_id:
        q["po_id"] = po_id
    return clean_many(await get_db().goods_receipts.find(q).sort("created_at", -1).to_list(500))


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _item_or_404(item_id: str) -> dict[str, Any]:
    item = await get_db().stock_items.find_one({"_id": item_id})
    if not item:
        raise HTTPException(404, "Stock item not found")
    return item
