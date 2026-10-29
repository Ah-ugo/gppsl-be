"""Equipment handover forms reuse the SAME signing function as documents."""
from typing import Any, Optional

from app.core.common import utcnow_iso
from app.core.db import get_db
from app.core.deps import client_ip

from . import pdfsign, service


async def create_handover_document(eq: dict[str, Any], rental: dict[str, Any], user: dict[str, Any], request: Any) -> Optional[str]:
    project = await get_db().projects.find_one({"_id": rental.get("project_id")}) if rental.get("project_id") else None
    rows = [("Equipment", f"{eq['name']}"), ("Serial number", eq["serial"]), ("Category", eq["category"]),
            ("Project / site", project["name"] if project else "-"), ("Issued by", user["name"]), ("Received by", rental["receiver_name"]),
            ("Start date", rental["start_date"]), ("Expected return", rental.get("expected_return") or "-"),
            ("Rate", f"NGN {rental['rate']:,.0f} per {rental['rate_type']}"), ("Run hours at issue", f"{eq.get('run_hours', 0):.0f} h"),
            ("Condition notes", str((rental.get("condition_out") or {}).get("notes") or "None recorded")),
            ("Photos taken", str(len(rental.get("handover_photos") or [])))]
    pdf = pdfsign.make_simple_pdf("Equipment Handover Form", rows, "GPPSL handover form, generated automatically at check-out.")
    doc = await service.create_document(f"Handover {eq['serial']} {rental['start_date']}.pdf", "Equipment handovers", pdf, "application/pdf",
                                        ["md", "admin", "storekeeper", "supervisor"], user, status="Awaiting signature",
                                        text=" ".join(f"{a} {b}" for a, b in rows))
    sig_png: Optional[bytes] = None
    if rental.get("signature_url"):
        try:
            sig_png = await service.load_bytes(rental["signature_url"])
        except Exception:  # noqa: BLE001 - the form is still stamped with the receiver's name
            sig_png = None
    ip = client_ip(request) if request is not None else ""
    await service.apply_signature(doc, rental["receiver_name"], sig_png, ip, "", 1)
    await get_db().documents.update_one({"_id": doc["_id"]}, {"$set": {"status": "Signed", "equipment_id": eq["_id"], "rental_id": rental["_id"]}})
    return doc["_id"]
