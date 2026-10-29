"""PDF signing core (pypdf + ReportLab only, no web framework). Reused for documents AND equipment handover forms.

Every signature is stamped onto a "Signature record" page appended to the document (4 stamps per page), so the
original content is never covered. Each stamp shows: signature image, name, date/time (Africa/Lagos), IP address,
location and the SHA-256 hash of the document as it was just before that signature.
"""
from __future__ import annotations

import hashlib
import io
from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from pypdf import PdfReader, PdfWriter
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

SLOTS_PER_PAGE = 4
META_KEY = "/GPPSLStamps"


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def stamp_count(pdf_bytes: bytes) -> int:
    meta = PdfReader(io.BytesIO(pdf_bytes)).metadata or {}
    try:
        return int(meta.get(META_KEY, 0))
    except (TypeError, ValueError):
        return 0


def _record_page_heading() -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    w, h = A4
    c.setFont("Helvetica-Bold", 16)
    c.drawString(40, h - 60, "Signature record")
    c.setFont("Helvetica", 9)
    c.setFillGray(0.4)
    c.drawString(40, h - 76, "Each block below was added automatically when the person signed. Hash = SHA-256 of the document before that signature.")
    c.save()
    return buf.getvalue()


def _stamp_overlay(slot: int, name: str, signature_png: Optional[bytes], when: datetime, ip: str, location: str, doc_hash: str,
                   order: Optional[int]) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    w, h = A4
    box_h = 150
    top = h - 100 - slot * (box_h + 12)
    y = top - box_h
    c.setStrokeGray(0.6)
    c.setLineWidth(0.8)
    c.roundRect(40, y, w - 80, box_h, 6)
    if signature_png:
        try:
            c.drawImage(ImageReader(io.BytesIO(signature_png)), 50, y + 40, width=170, height=85, preserveAspectRatio=True, mask="auto")
        except Exception:  # an unreadable image must not block signing; the text stamp still proves it
            c.setFont("Helvetica-Oblique", 9)
            c.drawString(50, y + 90, "(signature image unreadable)")
    c.setStrokeGray(0.8)
    c.line(50, y + 38, 220, y + 38)
    c.setFillGray(0)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(50, y + 24, name[:40])
    c.setFont("Helvetica", 9)
    local = when.astimezone(ZoneInfo("Africa/Lagos"))
    lines = [
        f"Signed{'' if order is None else f' (signer {order})'}: {local.strftime('%d/%m/%Y %H:%M:%S')} WAT",
        f"IP address: {ip or 'unknown'}",
        f"Location: {location or 'not provided'}",
        "Document hash (SHA-256):",
        doc_hash[:32],
        doc_hash[32:],
    ]
    ty = y + box_h - 22
    for i, line in enumerate(lines):
        c.setFont("Courier" if i >= 4 else "Helvetica", 8 if i >= 4 else 9)
        c.drawString(240, ty - i * 15, line)
    c.save()
    return buf.getvalue()


def stamp_pdf(
    pdf_bytes: bytes,
    signer_name: str,
    signature_png: Optional[bytes],
    ip: str = "",
    location: str = "",
    when: Optional[datetime] = None,
    order: Optional[int] = None,
) -> tuple[bytes, str]:
    """Return (new_pdf_bytes, hash_of_document_before_this_signature)."""
    when = when or datetime.now(timezone.utc)
    doc_hash = sha256_hex(pdf_bytes)
    reader = PdfReader(io.BytesIO(pdf_bytes))
    n = stamp_count(pdf_bytes)
    slot = n % SLOT_COUNT

    writer = PdfWriter()
    for page in reader.pages:
        writer.add_page(page)
    if slot == 0:  # start a fresh signature-record page
        writer.add_page(PdfReader(io.BytesIO(_record_page_heading())).pages[0])
    last = writer.pages[-1]
    last.merge_page(PdfReader(io.BytesIO(_stamp_overlay(slot, signer_name, signature_png, when, ip, location, doc_hash, order))).pages[0])

    meta = {k: v for k, v in (reader.metadata or {}).items() if isinstance(v, str)}
    meta[META_KEY] = str(n + 1)
    writer.add_metadata(meta)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue(), doc_hash


SLOT_COUNT = SLOTS_PER_PAGE


def make_simple_pdf(title: str, rows: list[tuple[str, str]], footer: str = "") -> bytes:
    """A clean one-page form (used for equipment handover forms)."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    w, h = A4
    c.setFont("Helvetica-Bold", 18)
    c.drawString(40, h - 60, title)
    c.setStrokeGray(0.7)
    c.line(40, h - 70, w - 40, h - 70)
    y = h - 100
    for label, value in rows:
        c.setFont("Helvetica-Bold", 10)
        c.drawString(40, y, label)
        c.setFont("Helvetica", 10)
        text = str(value)
        for part in [text[i:i + 80] for i in range(0, max(len(text), 1), 80)]:
            c.drawString(190, y, part)
            y -= 15
        y -= 4
        if y < 80:
            c.showPage()
            y = h - 60
    if footer:
        c.setFont("Helvetica-Oblique", 8)
        c.setFillGray(0.4)
        c.drawString(40, 40, footer)
    c.save()
    return buf.getvalue()


def extract_text(pdf_bytes: bytes) -> str:
    """PyMuPDF when installed (better layout), otherwise pypdf."""
    try:
        import fitz  # PyMuPDF

        with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
            return "\n".join(page.get_text() for page in doc)
    except ImportError:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        return "\n".join((p.extract_text() or "") for p in reader.pages)


def make_text_pdf(title: str, paragraphs: list[str]) -> bytes:
    """A multi-paragraph text document (used for sample/seed documents)."""
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

    buf = io.BytesIO()
    styles = getSampleStyleSheet()
    story = [Paragraph(title, styles["Title"]), Spacer(1, 12)]
    for p in paragraphs:
        story += [Paragraph(p, styles["BodyText"]), Spacer(1, 8)]
    SimpleDocTemplate(buf, pagesize=A4, title=title, leftMargin=50, rightMargin=50, topMargin=50, bottomMargin=50).build(story)
    return buf.getvalue()
