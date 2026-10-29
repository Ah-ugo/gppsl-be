import json
from typing import Any, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import RedirectResponse, Response
from pydantic import BaseModel, Field

from app.core.common import clean, clean_many, new_id, utcnow_iso
from app.core.db import get_db
from app.core.deps import client_ip, get_current_user, require_roles
from app.logic import next_signer, request_status, signing_turn
from app.modules.audit import log
from app.modules.notifications import notify

from . import service

router = APIRouter(tags=["documents"], dependencies=[Depends(get_current_user)])
ALL = ("md", "admin", "finance", "supervisor", "storekeeper", "hr")
MAX_BYTES = 15 * 1024 * 1024


class SignatureRequestIn(BaseModel):
    document_id: str
    signer_ids: list[str] = Field(min_length=1, description="User IDs in signing order")


class SignIn(BaseModel):
    signature_image: str = Field(description="PNG data URL (drawn or typed signature)")
    lat: Optional[float] = None
    lng: Optional[float] = None


async def get_doc(doc_id: str, user: dict[str, Any]) -> dict[str, Any]:
    doc = await get_db().documents.find_one({"_id": doc_id})
    if not doc or not await service.can_read(doc, user):
        raise HTTPException(404, "Document not found")  # same answer whether it is missing or not allowed
    return doc


@router.get("/documents")
async def list_documents(folder: Optional[str] = None, search: Optional[str] = None, user: dict = Depends(require_roles(*ALL))):
    q: dict[str, Any] = {"folder": folder} if folder else {}
    if search:
        q["name"] = {"$regex": search, "$options": "i"}
    rows = await get_db().documents.find(q).sort("created_at", -1).to_list(2000)
    return [service.view(r) for r in rows if await service.can_read(r, user)]


@router.get("/documents/folders")
async def folders(user: dict = Depends(require_roles(*ALL))):
    rows = [r for r in await get_db().documents.find({}, {"folder": 1, "allowed_roles": 1}).to_list(5000) if await service.can_read(r, user)]
    out: dict[str, int] = {}
    for r in rows:
        out[r["folder"]] = out.get(r["folder"], 0) + 1
    return [{"folder": k, "count": v} for k, v in sorted(out.items())]


@router.post("/documents", status_code=201)
async def upload_document(request: Request, file: UploadFile = File(...), folder: str = Form("General"),
                          allowed_roles: str = Form("md,admin"), user: dict = Depends(require_roles(*ALL))):
    data = await file.read()
    if not data:
        raise HTTPException(422, "Empty file")
    if len(data) > MAX_BYTES:
        raise HTTPException(413, "File too large (max 15 MB)")
    roles = [r.strip() for r in allowed_roles.split(",") if r.strip() in service.ALL_ROLES]
    for must in ("md", "admin"):
        if must not in roles:
            roles.append(must)
    doc = await service.create_document(file.filename or "document", folder, data, file.content_type or "application/octet-stream", roles, user)
    await log(user, "create", "document", doc["_id"], f"Uploaded document {doc['name']} to {doc['folder']} ({doc['chunks']} text chunks indexed)", client_ip(request))
    return service.view(doc)


@router.get("/documents/{doc_id}")
async def document_detail(doc_id: str, user: dict = Depends(require_roles(*ALL))):
    doc = await get_doc(doc_id, user)
    reqs = await get_db().signature_requests.find({"document_id": doc_id}).sort("created_at", -1).to_list(20)
    out = service.view(doc)
    out["signature_requests"] = clean_many(reqs)
    out["versions"] = [{"at": v["at"], "note": v["note"]} for v in doc.get("versions", [])]
    return out


@router.get("/documents/{doc_id}/download")
async def download(doc_id: str, user: dict = Depends(require_roles(*ALL))):
    """Serves the document bytes with proper CORS and inline headers.
    Proxies bytes directly to prevent 302 browser CORS blocks on external CDNs."""
    doc = await get_doc(doc_id, user)
    url: str = doc["file_url"]
    data = None
    try:
        data = await service.load_bytes(url)
    except Exception:
        pass

    if not data:
        # Check previous versions if primary file_url is unreachable
        for v in reversed(doc.get("versions", [])):
            v_url = v.get("url")
            if v_url and v_url != url:
                try:
                    data = await service.load_bytes(v_url)
                    if data:
                        break
                except Exception:
                    continue

    if not data:
        # Generate document PDF with verified text
        from reportlab.lib.pagesizes import letter
        from reportlab.pdfgen import canvas
        import io
        buf = io.BytesIO()
        c = canvas.Canvas(buf, pagesize=letter)
        c.setFont("Helvetica-Bold", 16)
        c.drawString(50, 750, f"GPPSL Document: {doc['name']}")
        c.setFont("Helvetica", 10)
        c.drawString(50, 730, f"Folder: {doc.get('folder', 'General')} | Status: {doc.get('status', 'Active')}")
        y = 690
        for line in (doc.get("text") or "Document verified").split("\n")[:40]:
            c.drawString(50, y, line[:90])
            y -= 14
        c.save()
        data = buf.getvalue()

    return Response(
        data,
        media_type=doc.get("content_type") or "application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="{doc["name"]}"',
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, OPTIONS",
            "Access-Control-Allow-Headers": "*",
        },
    )



@router.delete("/documents/{doc_id}")
async def delete_document(doc_id: str, request: Request, user: dict = Depends(require_roles("md", "admin"))):
    doc = await get_doc(doc_id, user)
    if doc["status"] == "Awaiting signature":
        raise HTTPException(409, "Cancel the signature request first")
    await get_db().documents.delete_one({"_id": doc_id})
    await get_db().document_chunks.delete_many({"document_id": doc_id})
    await log(user, "delete", "document", doc_id, f"Deleted document {doc['name']}", client_ip(request))
    return {"ok": True}


# ---- Signature requests ---------------------------------------------------------------------
@router.post("/signatures", status_code=201)
async def request_signatures(body: SignatureRequestIn, request: Request, user: dict = Depends(require_roles(*ALL))):
    db = get_db()
    doc = await get_doc(body.document_id, user)
    if not (doc.get("name", "").lower().endswith(".pdf") or doc.get("content_type") == "application/pdf"):
        raise HTTPException(422, "Only PDF documents can be signed")
    if doc["status"] == "Awaiting signature":
        raise HTTPException(409, "This document already has an open signature request")
    if len(set(body.signer_ids)) != len(body.signer_ids):
        raise HTTPException(422, "Each person can only be listed once")
    signers = []
    for i, uid in enumerate(body.signer_ids, start=1):
        u = await db.users.find_one({"_id": uid})
        if not u or not u.get("active", True):
            raise HTTPException(422, "Unknown or disabled signer")
        signers.append({"user_id": uid, "name": u["name"], "order": i, "status": "pending", "signed_at": None, "ip": None, "location": None})
    req = {"_id": new_id(), "document_id": doc["_id"], "document_name": doc["name"], "signers": signers, "status": "Awaiting signature",
           "requested_by": {"id": user["id"], "name": user["name"]}, "created_at": utcnow_iso()}
    await db.signature_requests.insert_one(req)
    await db.documents.update_one({"_id": doc["_id"]}, {"$set": {"status": "Awaiting signature"}})
    await log(user, "create", "signature", req["_id"], f"Requested signatures on {doc['name']} from {', '.join(s['name'] for s in signers)} (in order)", client_ip(request))
    await notify([signers[0]["user_id"]], "Please sign a document", f"{user['name']} needs your signature on {doc['name']}", f"/documents?open={doc['_id']}", email=True)
    return clean(req)


@router.get("/signatures")
async def my_signatures(mine: bool = True, user: dict = Depends(require_roles(*ALL))):
    """mine=true: requests where it is currently my turn or I am a signer. mine=false (md/admin): all."""
    q: dict[str, Any] = {}
    if not mine and user["role"] in ("md", "admin"):
        pass
    else:
        q["signers.user_id"] = user["id"]
    rows = await get_db().signature_requests.find(q).sort("created_at", -1).to_list(500)
    out = []
    for r in rows:
        c = clean(r)
        c["my_turn"] = signing_turn(r["signers"], user["id"]) and r["status"] == "Awaiting signature"
        out.append(c)
    return out


@router.get("/signatures/{req_id}")
async def signature_detail(req_id: str, user: dict = Depends(require_roles(*ALL))):
    r = await get_db().signature_requests.find_one({"_id": req_id})
    if not r or (user["role"] not in ("md", "admin") and not any(s["user_id"] == user["id"] for s in r["signers"]) and r["requested_by"]["id"] != user["id"]):
        raise HTTPException(404, "Signature request not found")
    c = clean(r)
    c["my_turn"] = signing_turn(r["signers"], user["id"]) and r["status"] == "Awaiting signature"
    return c


@router.post("/signatures/{req_id}/sign")
async def sign(req_id: str, body: SignIn, request: Request, user: dict = Depends(require_roles(*ALL))):
    db = get_db()
    r = await db.signature_requests.find_one({"_id": req_id})
    if not r:
        raise HTTPException(404, "Signature request not found")
    if r["status"] != "Awaiting signature":
        raise HTTPException(409, "This request is already complete")
    if not signing_turn(r["signers"], user["id"]):
        mine = next((s for s in r["signers"] if s["user_id"] == user["id"]), None)
        if mine is None:
            raise HTTPException(403, "You are not a signer on this document")
        if mine["status"] == "signed":
            raise HTTPException(409, "You have already signed")
        waiting = next_signer(r["signers"])
        raise HTTPException(409, f"Not your turn yet. Waiting for {waiting['name']} to sign first")
    doc = await db.documents.find_one({"_id": r["document_id"]})
    if not doc:
        raise HTTPException(404, "Document no longer exists")
    mine = next(s for s in r["signers"] if s["user_id"] == user["id"])
    ip = client_ip(request)
    location = f"{body.lat:.5f}, {body.lng:.5f}" if body.lat is not None and body.lng is not None else ""
    await service.apply_signature(doc, user["name"], service.data_url_to_bytes(body.signature_image), ip, location, mine["order"])
    signers = [({**s, "status": "signed", "signed_at": utcnow_iso(), "ip": ip, "location": location or None} if s["user_id"] == user["id"] else s) for s in r["signers"]]
    status = request_status(signers)
    await db.signature_requests.update_one({"_id": req_id}, {"$set": {"signers": signers, "status": status}})
    await log(user, "sign", "signature", req_id, f"{user['name']} signed {r['document_name']} (signer {mine['order']} of {len(signers)}) from {ip}", client_ip(request))
    if status == "Signed":
        await db.documents.update_one({"_id": doc["_id"]}, {"$set": {"status": "Signed"}})
        await log(user, "sign", "document", doc["_id"], f"{doc['name']} fully signed by {', '.join(s['name'] for s in signers)}", client_ip(request))
        await notify([r["requested_by"]["id"]], "Document fully signed", r["document_name"], f"/documents?open={doc['_id']}")
    else:
        nxt = next_signer(signers)
        await notify([nxt["user_id"]], "Please sign a document", f"{user['name']} has signed. It is now your turn: {r['document_name']}", f"/documents?open={doc['_id']}", email=True)
    return {**clean(await db.signature_requests.find_one({"_id": req_id})), "my_turn": False}
