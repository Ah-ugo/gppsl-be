"""Documents: upload, text extraction, chunks, role-filtered reads, signature requests, reminders."""
import io
from datetime import datetime, timezone
from typing import Any, Optional

import httpx
from fastapi import HTTPException

from app.core.common import clean, new_id, today, utcnow, utcnow_iso
from app.core.config import get_settings
from app.core.db import get_db
from app.core.storage import read_local, save_bytes
from app.modules.notifications import notify

from . import embeddings, pdfsign

ALWAYS_ALL = ("md", "admin")  # may read every document
ALL_ROLES = ["md", "admin", "finance", "supervisor", "storekeeper", "hr"]


async def load_bytes(url: str) -> bytes:
    data = read_local(url)
    if data is not None:
        return data

    # For Cloudinary URLs, use SDK authentication to bypass 401 errors
    if "res.cloudinary.com" in url:
        cloudinary_data = await _cloudinary_fetch(url)
        if cloudinary_data is not None:
            return cloudinary_data

    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as c:
        r = await c.get(url)
        r.raise_for_status()
        return r.content


async def _cloudinary_fetch(url: str) -> bytes | None:
    """Use Cloudinary SDK credentials to fetch a protected resource."""
    try:
        import asyncio
        import io
        import os

        import cloudinary
        import cloudinary.api
        import cloudinary.uploader
        import cloudinary.utils

        from app.core.config import get_settings

        s = get_settings()
        if not s.cloudinary_url:
            return None

        os.environ["CLOUDINARY_URL"] = s.cloudinary_url
        cloudinary.reset_config()
        cloudinary.config(secure=True)

        # Parse public_id and resource_type from the URL
        # URL pattern: https://res.cloudinary.com/<cloud>/image/upload/v.../gppsl/...
        import re

        m = re.match(
            r"https://res\.cloudinary\.com/([^/]+)/([^/]+)/upload/(.+)",
            url,
        )
        if not m:
            return None

        resource_type = m.group(2)  # "image", "video", "raw"
        rest = m.group(3)
        # Remove version prefix if present (v123456789/)
        rest_no_ver = re.sub(r"^v\d+/", "", rest)
        # public_id is the rest without extension for images, keep for raw
        public_id = rest_no_ver

        # Generate a signed URL (expiry 1 hour) to bypass access controls
        signed_url, _ = await asyncio.to_thread(
            cloudinary.utils.cloudinary_url,
            public_id,
            resource_type=resource_type,
            type="upload",
            sign_url=True,
            secure=True,
        )

        if not signed_url:
            return None

        async with httpx.AsyncClient(timeout=60, follow_redirects=True) as c:
            r = await c.get(signed_url)
            if r.status_code == 200:
                return r.content

        # Last resort: try Admin API download link
        result = await asyncio.to_thread(
            cloudinary.utils.cloudinary_url,
            public_id,
            resource_type=resource_type,
            attachment=True,
            sign_url=True,
            secure=True,
        )
        fallback_url = result[0] if isinstance(result, tuple) else result
        if fallback_url:
            async with httpx.AsyncClient(timeout=60, follow_redirects=True) as c:
                r = await c.get(fallback_url)
                if r.status_code == 200:
                    return r.content

        return None
    except Exception:  # noqa: BLE001
        return None


async def can_read(doc: dict[str, Any], user: dict[str, Any]) -> bool:
    """allowed_roles filter applied on EVERY read. A named signer can always read the document they must sign."""
    if user["role"] in ALWAYS_ALL or user["role"] in (doc.get("allowed_roles") or []):
        return True
    return await get_db().signature_requests.find_one({"document_id": doc["_id"], "signers.user_id": user["id"]}) is not None


def view(doc: dict[str, Any]) -> dict[str, Any]:
    out = clean(doc)
    out.pop("text", None)  # keep list payloads small
    out["has_text"] = bool(doc.get("text"))
    return out


async def index_text(doc_id: str, text: str, allowed_roles: list[str]) -> int:
    db = get_db()
    await db.document_chunks.delete_many({"document_id": doc_id})
    s = get_settings()
    n = 0
    for i, ch in enumerate(embeddings.chunk_text(text)):
        vec, provider = await embeddings.embed(ch, s.google_api_key, s.gemini_embedding_model)
        await db.document_chunks.insert_one({"_id": new_id(), "document_id": doc_id, "idx": i, "text": ch, "embedding": vec,
                                             "provider": provider, "allowed_roles": allowed_roles})
        n += 1
    return n


async def create_document(name: str, folder: str, data: bytes, content_type: str, allowed_roles: list[str], user: dict[str, Any],
                          status: str = "Draft", text: Optional[str] = None) -> dict[str, Any]:
    stored = await save_bytes(data, name, content_type)
    if text is None:
        lower = name.lower()
        if lower.endswith(".pdf"):
            try:
                text = pdfsign.extract_text(data)
            except Exception:  # noqa: BLE001
                text = ""
        elif lower.endswith((".txt", ".md", ".csv")):
            text = data.decode("utf-8", errors="ignore")
        else:
            text = ""
    doc = {"_id": new_id(), "name": name, "folder": folder or "General", "file_url": stored["url"], "storage": stored["storage"],
           "content_type": content_type, "text": text, "allowed_roles": allowed_roles, "status": status,
           "sha256": pdfsign.sha256_hex(data), "size": len(data), "versions": [{"url": stored["url"], "at": utcnow_iso(), "note": "Uploaded"}],
           "created_by": {"id": user["id"], "name": user["name"]}, "created_at": utcnow_iso()}
    await get_db().documents.insert_one(doc)
    doc["chunks"] = await index_text(doc["_id"], text or "", allowed_roles) if text else 0
    return doc


async def search_chunks(question: str, user: dict[str, Any], k: int = 4) -> list[dict[str, Any]]:
    """Top-k chunks the caller is allowed to read, by cosine similarity."""
    s = get_settings()
    qvec, provider = await embeddings.embed(question, s.google_api_key, s.gemini_embedding_model)
    db = get_db()
    scored = []
    for ch in await db.document_chunks.find({}).to_list(20000):
        if ch.get("provider") != provider:  # never compare vectors from different embedding models
            continue
        if user["role"] not in ALWAYS_ALL and user["role"] not in (ch.get("allowed_roles") or []):
            continue
        scored.append((embeddings.cosine(qvec, ch["embedding"]), ch))
    scored.sort(key=lambda x: x[0], reverse=True)
    out = []
    for score, ch in scored[:k]:
        if score < 0.40:
            continue
        doc = await db.documents.find_one({"_id": ch["document_id"]}, {"name": 1})
        out.append({"document_id": ch["document_id"], "name": doc["name"] if doc else "?", "text": ch["text"], "score": round(score, 3)})
    return out


# ---- Signing --------------------------------------------------------------------------------
def data_url_to_bytes(data_url: str) -> bytes:
    import base64

    try:
        return base64.b64decode(data_url.split(",", 1)[1] if "," in data_url else data_url)
    except Exception:  # noqa: BLE001
        raise HTTPException(422, "Signature image is not valid base64")


async def apply_signature(doc: dict[str, Any], signer_name: str, signature_png: Optional[bytes], ip: str, location: str,
                          order: Optional[int]) -> tuple[bytes, str]:
    """THE signing function. Stamp, store the new file version, point the document at it. Reused for handover forms."""
    pdf = await load_bytes(doc["file_url"])
    if not doc.get("name", "").lower().endswith(".pdf") and doc.get("content_type") != "application/pdf":
        raise HTTPException(422, "Only PDF documents can be signed")
    new_pdf, prior_hash = pdfsign.stamp_pdf(pdf, signer_name, signature_png, ip, location, utcnow(), order)
    stored = await save_bytes(new_pdf, doc["name"], "application/pdf")
    await get_db().documents.update_one({"_id": doc["_id"]}, {
        "$set": {"file_url": stored["url"], "sha256": pdfsign.sha256_hex(new_pdf), "size": len(new_pdf)},
        "$push": {"versions": {"url": stored["url"], "at": utcnow_iso(), "note": f"Signed by {signer_name}", "prior_sha256": prior_hash}}})
    return new_pdf, prior_hash


async def remind_pending_signers() -> int:
    """Scheduler job: nudge whoever's turn it is, at most once per day per request."""
    from app.logic import next_signer

    db = get_db()
    sent = 0
    t = today().isoformat()
    for req in await db.signature_requests.find({"status": "Awaiting signature"}).to_list(1000):
        nxt = next_signer(req["signers"])
        if not nxt or req.get("last_reminder") == t:
            continue
        doc = await db.documents.find_one({"_id": req["document_id"]}, {"name": 1})
        await notify([nxt["user_id"]], "Document waiting for your signature", doc["name"] if doc else "A document", f"/documents?open={req['document_id']}", email=True)
        await db.signature_requests.update_one({"_id": req["_id"]}, {"$set": {"last_reminder": t}})
        sent += 1
    return sent
