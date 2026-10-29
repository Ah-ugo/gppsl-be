import base64
import io

from PIL import Image
from pypdf import PdfReader

from app.core.db import get_db
from app.modules.documents.pdfsign import extract_text, make_simple_pdf


def sig_data_url():
    b = io.BytesIO()
    Image.new("RGBA", (200, 80), (10, 30, 80, 255)).save(b, format="PNG")
    return "data:image/png;base64," + base64.b64encode(b.getvalue()).decode()


async def upload(client, auth, role="md", roles="md,admin,finance"):
    pdf = make_simple_pdf("Service Agreement", [("Client", "Placeholder Client A")])
    r = await client.post("/documents", files={"file": ("agreement.pdf", pdf, "application/pdf")}, data={"folder": "Contracts", "allowed_roles": roles}, headers=auth(role))
    assert r.status_code == 201, r.text
    return r.json()


async def test_upload_extracts_text_and_indexes_chunks(client, auth):
    d = await upload(client, auth)
    assert d["has_text"] and d["status"] == "Draft"
    assert await get_db().document_chunks.count_documents({"document_id": d["id"]}) >= 1


async def test_allowed_roles_filter_on_every_read(client, auth):
    d = await upload(client, auth, roles="md,admin,finance")
    assert any(x["id"] == d["id"] for x in (await client.get("/documents", headers=auth("finance"))).json())
    assert not any(x["id"] == d["id"] for x in (await client.get("/documents", headers=auth("storekeeper"))).json())
    assert (await client.get(f"/documents/{d['id']}", headers=auth("storekeeper"))).status_code == 404
    assert (await client.get(f"/documents/{d['id']}/download", headers=auth("storekeeper"))).status_code == 404
    assert (await client.get(f"/documents/{d['id']}/download", headers=auth("finance"))).status_code == 200


async def test_two_people_sign_in_order_and_pdf_has_both_stamps(client, auth, users):
    d = await upload(client, auth)
    req = await client.post("/signatures", json={"document_id": d["id"], "signer_ids": [users["finance"]["_id"], users["md"]["_id"]]}, headers=auth("md"))
    assert req.status_code == 201
    rid = req.json()["id"]
    assert (await client.get(f"/documents/{d['id']}", headers=auth("md"))).json()["status"] == "Awaiting signature"
    assert any(n["title"] == "Please sign a document" for n in (await client.get("/notifications", headers=auth("finance"))).json()["items"])
    # MD (second) cannot jump the queue
    early = await client.post(f"/signatures/{rid}/sign", json={"signature_image": sig_data_url()}, headers=auth("md"))
    assert early.status_code == 409 and "Not your turn" in early.json()["detail"]
    # a stranger cannot sign
    assert (await client.post(f"/signatures/{rid}/sign", json={"signature_image": sig_data_url()}, headers=auth("hr"))).status_code in (403, 404)
    ok1 = await client.post(f"/signatures/{rid}/sign", json={"signature_image": sig_data_url(), "lat": 4.8156, "lng": 7.0498}, headers=auth("finance"))
    assert ok1.status_code == 200 and ok1.json()["status"] == "Awaiting signature"
    assert (await client.post(f"/signatures/{rid}/sign", json={"signature_image": sig_data_url()}, headers=auth("finance"))).status_code == 409  # already signed
    ok2 = await client.post(f"/signatures/{rid}/sign", json={"signature_image": sig_data_url()}, headers=auth("md"))
    assert ok2.status_code == 200 and ok2.json()["status"] == "Signed"
    assert (await client.get(f"/documents/{d['id']}", headers=auth("md"))).json()["status"] == "Signed"
    pdf = (await client.get(f"/documents/{d['id']}/download", headers=auth("md"))).content
    text = extract_text(pdf)
    assert "Test Finance" in text and "Test Md" in text and "4.81560, 7.04980" in text and "Service Agreement" in text
    assert len(PdfReader(io.BytesIO(pdf)).pages) == 2
    audit = (await client.get("/audit", headers=auth("md"), params={"action": "sign"})).json()
    assert audit["total"] >= 3  # two signatures + the fully-signed document entry


async def test_cannot_open_second_request_while_awaiting(client, auth, users):
    d = await upload(client, auth)
    body = {"document_id": d["id"], "signer_ids": [users["md"]["_id"]]}
    assert (await client.post("/signatures", json=body, headers=auth("md"))).status_code == 201
    assert (await client.post("/signatures", json=body, headers=auth("md"))).status_code == 409


async def test_equipment_checkout_creates_signed_handover_form(client, auth, world):
    r = await client.post(f"/equipment/{world['ok']['_id']}/checkout", headers=auth("storekeeper"),
                          json={"project_id": world["project"]["_id"], "client_id": world["client"]["_id"], "rate": 1000, "receiver_name": "Emeka Okafor"})
    assert r.status_code == 201 and r.json().get("handover_document_id")
    doc = (await client.get(f"/documents/{r.json()['handover_document_id']}", headers=auth("md"))).json()
    assert doc["status"] == "Signed" and doc["folder"] == "Equipment handovers"
    text = extract_text((await client.get(f"/documents/{doc['id']}/download", headers=auth("md"))).content)
    assert "Equipment Handover Form" in text and "Emeka Okafor" in text and "Signature record" in text


async def test_reminder_job_nudges_current_signer_once_a_day(client, auth, users):
    from app.modules.documents.service import remind_pending_signers

    d = await upload(client, auth)
    await client.post("/signatures", json={"document_id": d["id"], "signer_ids": [users["finance"]["_id"]]}, headers=auth("md"))
    assert await remind_pending_signers() == 1
    assert await remind_pending_signers() == 0
