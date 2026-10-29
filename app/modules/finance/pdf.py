"""Professional invoice and receipt PDF generation using reportlab.
Produces a fully data-driven PDF — not a screenshot of the UI.
"""
from __future__ import annotations

import io
from datetime import date
from typing import Any, Optional


# ── helpers ────────────────────────────────────────────────────────────────────

def _naira(v: float) -> str:
    return f"\u20a6{v:,.2f}"


def _safe(v: Any, default: str = "N/A") -> str:
    return str(v).strip() if v else default


# ── PDF generator ───────────────────────────────────────────────────────────────

async def build_invoice_pdf(
    invoice: dict,
    client: Optional[dict],
    receipts: list[dict],
    company: dict,
) -> bytes:
    """Generates a professional A4 PDF invoice with optional receipts section."""
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import cm, mm
        from reportlab.platypus import (
            HRFlowable,
            Paragraph,
            SimpleDocTemplate,
            Spacer,
            Table,
            TableStyle,
        )
    except ImportError:
        raise RuntimeError(
            "reportlab is required for PDF generation. "
            "Install it: pip install reportlab"
        )

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        rightMargin=1.5 * cm,
        leftMargin=1.5 * cm,
        topMargin=1.5 * cm,
        bottomMargin=1.5 * cm,
    )

    styles = getSampleStyleSheet()
    # Colour palette
    DARK = colors.HexColor("#1a1a2e")
    ACCENT = colors.HexColor("#1565C0")
    LIGHT = colors.HexColor("#E3F2FD")
    GRAY = colors.HexColor("#78909C")
    WHITE = colors.white
    RED = colors.HexColor("#C62828")
    GREEN = colors.HexColor("#2E7D32")

    h1 = ParagraphStyle("h1", parent=styles["Normal"], fontSize=22, textColor=WHITE, fontName="Helvetica-Bold")
    h2 = ParagraphStyle("h2", parent=styles["Normal"], fontSize=11, textColor=DARK, fontName="Helvetica-Bold")
    body = ParagraphStyle("body", parent=styles["Normal"], fontSize=9, textColor=DARK, leading=13)
    small = ParagraphStyle("small", parent=styles["Normal"], fontSize=8, textColor=GRAY)
    right = ParagraphStyle("right", parent=styles["Normal"], fontSize=9, textColor=DARK, alignment=2)
    bold_right = ParagraphStyle("bold_right", parent=styles["Normal"], fontSize=10, textColor=DARK, fontName="Helvetica-Bold", alignment=2)
    accent_right = ParagraphStyle("accent_right", parent=styles["Normal"], fontSize=12, textColor=ACCENT, fontName="Helvetica-Bold", alignment=2)
    footer_s = ParagraphStyle("footer", parent=styles["Normal"], fontSize=7, textColor=GRAY, alignment=1)

    elements: list = []

    # ── Header Banner ──────────────────────────────────────────────────────────
    co_name = _safe(company.get("name"), "GPPSL Operations Ltd")
    co_address = _safe(company.get("address"), "Port Harcourt, Rivers State, Nigeria")
    co_email = _safe(company.get("email"), "accounts@gppsl.ng")
    co_phone = _safe(company.get("phone"), "+234 000 000 0000")
    co_rc = _safe(company.get("rc_number"), "")
    co_tin = _safe(company.get("tin"), "")

    inv_number = _safe(invoice.get("number"), "INV-0001")
    inv_date = _safe(invoice.get("issue_date"), str(date.today()))
    due_date = _safe(invoice.get("due_date"), "")
    inv_status = _safe(invoice.get("status"), "draft").upper()
    amount = float(invoice.get("amount") or 0)
    paid = float(invoice.get("paid_amount") or 0)
    outstanding = max(0.0, amount - paid)

    status_color = GREEN if inv_status in ("PAID",) else (GRAY if inv_status in ("DRAFT",) else (RED if outstanding > 0 else ACCENT))

    # Header table: company info + invoice meta
    header_data = [
        [
            # Left: company brand
            Table(
                [
                    [Paragraph(co_name, h1)],
                    [Paragraph(f"{co_address}", small)],
                    [Paragraph(f"✉ {co_email}  |  ☎ {co_phone}", small)],
                    [Paragraph(f"RC: {co_rc}  |  TIN: {co_tin}", small) if co_rc or co_tin else Spacer(1, 1)],
                ],
                colWidths=[9 * cm],
                style=TableStyle([
                    ("BACKGROUND", (0, 0), (-1, -1), ACCENT),
                    ("PADDING", (0, 0), (-1, -1), 8),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ]),
            ),
            # Right: INVOICE label + details
            Table(
                [
                    [Paragraph("<b>INVOICE</b>", ParagraphStyle("inv", parent=styles["Normal"], fontSize=28, textColor=ACCENT, fontName="Helvetica-Bold", alignment=2))],
                    [Paragraph(f"<b>{inv_number}</b>", ParagraphStyle("invn", parent=styles["Normal"], fontSize=10, textColor=DARK, fontName="Helvetica-Bold", alignment=2))],
                    [Paragraph(f"Issue Date: {inv_date}", right)],
                    [Paragraph(f"Due Date: {due_date}", right) if due_date else Spacer(1, 1)],
                    [Table([[Paragraph(f"  {inv_status}  ", ParagraphStyle("st", parent=styles["Normal"], fontSize=9, textColor=WHITE, fontName="Helvetica-Bold", alignment=1))]],
                           style=TableStyle([("BACKGROUND", (0, 0), (-1, -1), status_color), ("ROUNDEDCORNERS", (0, 0), (-1, -1), 4), ("PADDING", (0, 0), (-1, -1), 4)]))],
                ],
                colWidths=[7.5 * cm],
                style=TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]),
            ),
        ]
    ]
    header_table = Table(header_data, colWidths=[9.5 * cm, 8 * cm])
    header_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (1, 0), (1, -1), 12),
    ]))
    elements.append(header_table)
    elements.append(Spacer(1, 0.5 * cm))

    # ── Bill To / From ─────────────────────────────────────────────────────────
    cl = client or {}
    cl_name = _safe(cl.get("name"), "Client")
    cl_addr = _safe(cl.get("address"), "")
    cl_email = _safe(cl.get("email"), "")
    cl_phone = _safe(cl.get("phone"), "")

    bill_data = [
        [
            Table([
                [Paragraph("<b>BILL TO</b>", ParagraphStyle("bt", parent=styles["Normal"], fontSize=8, textColor=GRAY, fontName="Helvetica-Bold"))],
                [Paragraph(f"<b>{cl_name}</b>", h2)],
                [Paragraph(cl_addr, body)] if cl_addr else [],
                [Paragraph(f"✉ {cl_email}", small)] if cl_email else [],
                [Paragraph(f"☎ {cl_phone}", small)] if cl_phone else [],
            ], colWidths=[8.5 * cm], style=TableStyle([("TOPPADDING", (0, 0), (-1, -1), 1), ("BOTTOMPADDING", (0, 0), (-1, -1), 1)])),
            Table([
                [Paragraph("<b>PAYMENT DETAILS</b>", ParagraphStyle("pd", parent=styles["Normal"], fontSize=8, textColor=GRAY, fontName="Helvetica-Bold"))],
                [Paragraph(_safe(company.get("bank_name"), "First Bank Nigeria"), body)],
                [Paragraph(f"Account: <b>{_safe(company.get('account_number'), '0123456789')}</b>", body)],
                [Paragraph(f"Account Name: {_safe(company.get('account_name'), co_name)}", body)],
                [Paragraph(f"Sort Code: {_safe(company.get('sort_code'), '011')}", body)],
            ], colWidths=[8.5 * cm], style=TableStyle([("TOPPADDING", (0, 0), (-1, -1), 1), ("BOTTOMPADDING", (0, 0), (-1, -1), 1)])),
        ]
    ]
    bill_table = Table(bill_data, colWidths=[9.5 * cm, 8 * cm])
    bill_table.setStyle(TableStyle([
        ("BOX", (0, 0), (0, 0), 0.5, colors.HexColor("#CFD8DC")),
        ("BOX", (1, 0), (1, 0), 0.5, colors.HexColor("#CFD8DC")),
        ("BACKGROUND", (0, 0), (0, 0), colors.HexColor("#F5F7FA")),
        ("BACKGROUND", (1, 0), (1, 0), colors.HexColor("#EFF8FF")),
        ("PADDING", (0, 0), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    elements.append(bill_table)
    elements.append(Spacer(1, 0.4 * cm))

    # ── Description / Notes ────────────────────────────────────────────────────
    description = invoice.get("description") or invoice.get("notes") or ""
    if description:
        elements.append(Paragraph("<b>Description of Services</b>", h2))
        elements.append(Spacer(1, 0.15 * cm))
        elements.append(Paragraph(description, body))
        elements.append(Spacer(1, 0.3 * cm))

    # ── Line items table ───────────────────────────────────────────────────────
    items = invoice.get("items") or []
    if items:
        elements.append(Paragraph("<b>Services / Items</b>", h2))
        elements.append(Spacer(1, 0.15 * cm))
        item_header = ["#", "Description", "Qty", "Unit Price", "Amount"]
        item_rows = [item_header]
        for i, item in enumerate(items, 1):
            qty = float(item.get("qty") or item.get("quantity") or 1)
            unit = float(item.get("unit_price") or item.get("rate") or 0)
            total_item = qty * unit
            item_rows.append([
                str(i),
                _safe(item.get("description") or item.get("name")),
                f"{qty:g}",
                _naira(unit),
                _naira(total_item),
            ])
        item_table = Table(item_rows, colWidths=[0.6 * cm, 9.5 * cm, 1.5 * cm, 2.8 * cm, 2.8 * cm])
        item_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), ACCENT),
            ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 9),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, colors.HexColor("#F8F9FA")]),
            ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#CFD8DC")),
            ("ALIGN", (2, 0), (-1, -1), "RIGHT"),
            ("FONTSIZE", (0, 1), (-1, -1), 8.5),
            ("PADDING", (0, 0), (-1, -1), 6),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]))
        elements.append(item_table)
        elements.append(Spacer(1, 0.3 * cm))

    # ── Totals ─────────────────────────────────────────────────────────────────
    vat_rate = float(invoice.get("vat_rate") or 0.075)
    wht_rate = float(invoice.get("wht_rate") or 0)
    subtotal = float(invoice.get("subtotal") or amount)
    vat_amount = float(invoice.get("vat_amount") or 0)
    wht_amount = float(invoice.get("wht_amount") or 0)

    totals_data: list[list] = []
    if vat_amount:
        totals_data.append([Paragraph("Sub-Total:", right), Paragraph(_naira(subtotal), right)])
        totals_data.append([Paragraph(f"VAT ({vat_rate*100:.1f}%):", right), Paragraph(_naira(vat_amount), right)])
    if wht_amount:
        totals_data.append([Paragraph(f"WHT ({wht_rate*100:.1f}%):", right), Paragraph(f"({_naira(wht_amount)})", ParagraphStyle("r2", parent=styles["Normal"], fontSize=9, textColor=RED, alignment=2))])
    totals_data.append([Paragraph("<b>TOTAL AMOUNT:</b>", bold_right), Paragraph(f"<b>{_naira(amount)}</b>", bold_right)])
    if paid:
        totals_data.append([Paragraph("Amount Paid:", right), Paragraph(f"({_naira(paid)})", ParagraphStyle("r3", parent=styles["Normal"], fontSize=9, textColor=GREEN, alignment=2))])
    totals_data.append([Paragraph("<b>BALANCE DUE:</b>", ParagraphStyle("bal", parent=styles["Normal"], fontSize=11, textColor=ACCENT, fontName="Helvetica-Bold", alignment=2)),
                        Paragraph(f"<b>{_naira(outstanding)}</b>", accent_right)])

    totals_table = Table(totals_data, colWidths=[10 * cm, 7.2 * cm], hAlign="RIGHT")
    totals_table.setStyle(TableStyle([
        ("LINEABOVE", (0, len(totals_data) - 2), (-1, len(totals_data) - 2), 0.8, ACCENT),
        ("BACKGROUND", (0, len(totals_data) - 1), (-1, -1), LIGHT),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#CFD8DC")),
        ("PADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, len(totals_data) - 1), (-1, -1), 8),
        ("BOTTOMPADDING", (0, len(totals_data) - 1), (-1, -1), 8),
    ]))
    elements.append(totals_table)
    elements.append(Spacer(1, 0.5 * cm))

    # ── Terms / Footer ─────────────────────────────────────────────────────────
    terms = invoice.get("terms") or "Payment due within the agreed terms. Please quote invoice number in all payments."
    elements.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#CFD8DC")))
    elements.append(Spacer(1, 0.15 * cm))
    elements.append(Paragraph("<b>Terms & Conditions</b>", small))
    elements.append(Paragraph(terms, small))
    elements.append(Spacer(1, 0.4 * cm))
    elements.append(Paragraph(
        f"{co_name}  |  RC: {co_rc}  |  TIN: {co_tin}  |  {co_address}  |  {co_email}",
        footer_s,
    ))
    elements.append(Paragraph("Generated by GPPSL Operations Platform · Confidential", footer_s))

    doc.build(elements)
    buf.seek(0)
    return buf.read()


async def build_receipt_pdf(
    receipt: dict,
    invoice: Optional[dict],
    client: Optional[dict],
    company: dict,
) -> bytes:
    """Generates a professional A4 receipt PDF."""
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import cm
        from reportlab.platypus import (
            HRFlowable,
            Paragraph,
            SimpleDocTemplate,
            Spacer,
            Table,
            TableStyle,
        )
    except ImportError:
        raise RuntimeError("reportlab is required for PDF generation.")

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        rightMargin=1.5 * cm,
        leftMargin=1.5 * cm,
        topMargin=1.5 * cm,
        bottomMargin=1.5 * cm,
    )

    styles = getSampleStyleSheet()
    DARK = colors.HexColor("#1a1a2e")
    ACCENT = colors.HexColor("#2E7D32")  # Green for receipts
    LIGHT = colors.HexColor("#E8F5E9")
    GRAY = colors.HexColor("#78909C")
    WHITE = colors.white

    h1 = ParagraphStyle("h1", parent=styles["Normal"], fontSize=22, textColor=WHITE, fontName="Helvetica-Bold")
    h2 = ParagraphStyle("h2", parent=styles["Normal"], fontSize=11, textColor=DARK, fontName="Helvetica-Bold")
    body = ParagraphStyle("body", parent=styles["Normal"], fontSize=9, textColor=DARK, leading=13)
    small = ParagraphStyle("small", parent=styles["Normal"], fontSize=8, textColor=GRAY)
    right = ParagraphStyle("right", parent=styles["Normal"], fontSize=9, textColor=DARK, alignment=2)
    footer_s = ParagraphStyle("footer", parent=styles["Normal"], fontSize=7, textColor=GRAY, alignment=1)

    elements: list = []

    co_name = _safe(company.get("name"), "GPPSL Operations Ltd")
    co_address = _safe(company.get("address"), "Port Harcourt, Rivers State, Nigeria")
    co_email = _safe(company.get("email"), "accounts@gppsl.ng")
    co_phone = _safe(company.get("phone"), "+234 000 000 0000")
    co_rc = _safe(company.get("rc_number"), "")

    rec_num = _safe(receipt.get("receipt_number"), "REC-0001")
    rec_date = _safe(receipt.get("date"), str(date.today()))
    amount_paid = float(receipt.get("amount") or 0)
    payment_method = _safe(receipt.get("payment_method"), "Bank Transfer")
    reference = _safe(receipt.get("reference"), "")
    balance = float(receipt.get("balance_remaining") or 0)

    inv = invoice or {}
    cl = client or {}
    cl_name = _safe(cl.get("name") or receipt.get("client_name"), "Client")

    # Header
    header_data = [[
        Table([
            [Paragraph(co_name, h1)],
            [Paragraph(co_address, small)],
            [Paragraph(f"✉ {co_email}  |  ☎ {co_phone}", small)],
        ], colWidths=[9 * cm], style=TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), ACCENT),
            ("PADDING", (0, 0), (-1, -1), 8),
        ])),
        Table([
            [Paragraph("<b>RECEIPT</b>", ParagraphStyle("r", parent=styles["Normal"], fontSize=28, textColor=ACCENT, fontName="Helvetica-Bold", alignment=2))],
            [Paragraph(f"<b>{rec_num}</b>", ParagraphStyle("rn", parent=styles["Normal"], fontSize=10, textColor=DARK, fontName="Helvetica-Bold", alignment=2))],
            [Paragraph(f"Date: {rec_date}", right)],
            [Paragraph(f"Payment Method: {payment_method}", right)],
            [Paragraph(f"Reference: {reference}", right)] if reference else [Spacer(1, 1)],
        ], colWidths=[7.5 * cm], style=TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ])),
    ]]
    header_table = Table(header_data, colWidths=[9.5 * cm, 8 * cm])
    header_table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (1, 0), (1, -1), 12)]))
    elements.append(header_table)
    elements.append(Spacer(1, 0.5 * cm))

    # Received From / Invoice Ref
    bill_data = [[
        Table([
            [Paragraph("<b>RECEIVED FROM</b>", ParagraphStyle("bt", parent=styles["Normal"], fontSize=8, textColor=GRAY, fontName="Helvetica-Bold"))],
            [Paragraph(f"<b>{cl_name}</b>", h2)],
            [Paragraph(_safe(cl.get("address"), ""), body)] if cl.get("address") else [],
            [Paragraph(f"✉ {cl.get('email', '')}", small)] if cl.get("email") else [],
        ], colWidths=[8.5 * cm], style=TableStyle([("TOPPADDING", (0, 0), (-1, -1), 1), ("BOTTOMPADDING", (0, 0), (-1, -1), 1)])),
        Table([
            [Paragraph("<b>INVOICE REFERENCE</b>", ParagraphStyle("pd", parent=styles["Normal"], fontSize=8, textColor=GRAY, fontName="Helvetica-Bold"))],
            [Paragraph(f"Invoice No: <b>{_safe(receipt.get('invoice_number') or inv.get('number'))}</b>", body)],
            [Paragraph(f"Invoice Amount: {_naira(float(inv.get('amount') or 0))}", body)] if inv else [],
            [Paragraph(f"Previously Paid: {_naira(float(inv.get('paid_amount') or 0) - amount_paid)}", body)] if inv else [],
        ], colWidths=[8.5 * cm], style=TableStyle([("TOPPADDING", (0, 0), (-1, -1), 1), ("BOTTOMPADDING", (0, 0), (-1, -1), 1)])),
    ]]
    bill_table = Table(bill_data, colWidths=[9.5 * cm, 8 * cm])
    bill_table.setStyle(TableStyle([
        ("BOX", (0, 0), (0, 0), 0.5, colors.HexColor("#CFD8DC")),
        ("BOX", (1, 0), (1, 0), 0.5, colors.HexColor("#CFD8DC")),
        ("BACKGROUND", (0, 0), (0, 0), colors.HexColor("#F5F7FA")),
        ("BACKGROUND", (1, 0), (1, 0), colors.HexColor("#F1FFF4")),
        ("PADDING", (0, 0), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    elements.append(bill_table)
    elements.append(Spacer(1, 0.5 * cm))

    # Payment Summary
    payment_rows = [
        [Paragraph("<b>AMOUNT RECEIVED</b>", ParagraphStyle("amt", parent=styles["Normal"], fontSize=14, textColor=ACCENT, fontName="Helvetica-Bold", alignment=2)),
         Paragraph(f"<b>{_naira(amount_paid)}</b>", ParagraphStyle("amtv", parent=styles["Normal"], fontSize=18, textColor=ACCENT, fontName="Helvetica-Bold", alignment=2))],
        [Paragraph("Balance Remaining:", right), Paragraph(f"<b>{_naira(balance)}</b>", ParagraphStyle("bal", parent=styles["Normal"], fontSize=10, textColor=DARK, fontName="Helvetica-Bold", alignment=2))],
        [Paragraph("Payment Method:", right), Paragraph(payment_method, right)],
        [Paragraph("Reference:", right), Paragraph(reference, right)] if reference else [Spacer(1, 1), Spacer(1, 1)],
    ]
    payment_table = Table(payment_rows, colWidths=[10 * cm, 7.2 * cm], hAlign="RIGHT")
    payment_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), LIGHT),
        ("BOX", (0, 0), (-1, -1), 0.8, ACCENT),
        ("LINEBELOW", (0, 0), (-1, 0), 0.8, ACCENT),
        ("PADDING", (0, 0), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    elements.append(payment_table)
    elements.append(Spacer(1, 0.5 * cm))

    # Confirmation stamp area
    if balance == 0:
        stamp = Table([[Paragraph("✓ PAYMENT IN FULL RECEIVED", ParagraphStyle("stamp", parent=styles["Normal"], fontSize=14, textColor=ACCENT, fontName="Helvetica-Bold", alignment=1))]],
                      style=TableStyle([("BACKGROUND", (0, 0), (-1, -1), LIGHT), ("BOX", (0, 0), (-1, -1), 1.5, ACCENT), ("PADDING", (0, 0), (-1, -1), 10)]))
        elements.append(stamp)
        elements.append(Spacer(1, 0.3 * cm))

    # Footer
    elements.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#CFD8DC")))
    elements.append(Spacer(1, 0.15 * cm))
    elements.append(Paragraph(f"{co_name}  |  RC: {co_rc}  |  {co_address}  |  {co_email}", footer_s))
    elements.append(Paragraph("This is an official receipt issued by GPPSL Operations Platform.", footer_s))

    doc.build(elements)
    buf.seek(0)
    return buf.read()
