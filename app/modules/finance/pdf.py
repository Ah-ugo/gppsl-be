"""Professional invoice and client statement PDF generation matching corporate institutional styling.
Produces a fully data-driven vector PDF adhering to the reference statement layout.
"""
from __future__ import annotations

import io
from datetime import date, datetime
from typing import Any, Optional


def _naira(v: float) -> str:
    return f"NGN {v:,.2f}"


def _safe(v: Any, default: str = "N/A") -> str:
    return str(v).strip() if v is not None and str(v).strip() else default


async def build_invoice_pdf(
    invoice: dict,
    client: Optional[dict],
    receipts: list[dict],
    company: dict,
) -> bytes:
    """Generates an institutional A4 PDF invoice / statement matching the reference design."""
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
        raise RuntimeError("reportlab is required for PDF generation. Install it: pip install reportlab")

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        rightMargin=1.2 * cm,
        leftMargin=1.2 * cm,
        topMargin=1.2 * cm,
        bottomMargin=1.2 * cm,
    )

    styles = getSampleStyleSheet()
    DARK = colors.HexColor("#1A1A1A")
    MUTED = colors.HexColor("#555555")
    LIGHT_GRAY = colors.HexColor("#EAEAEA")
    BORDER_GRAY = colors.HexColor("#CCCCCC")
    WHITE = colors.white
    PRIMARY = colors.HexColor("#0B3B24")

    # Typography styles
    title_style = ParagraphStyle("title", parent=styles["Normal"], fontSize=13, fontName="Helvetica-Bold", alignment=1, textColor=DARK)
    meta_label = ParagraphStyle("meta_lbl", parent=styles["Normal"], fontSize=8, fontName="Helvetica-Bold", textColor=DARK)
    meta_val = ParagraphStyle("meta_val", parent=styles["Normal"], fontSize=8, fontName="Helvetica", textColor=DARK)
    meta_val_right = ParagraphStyle("meta_val_r", parent=styles["Normal"], fontSize=8, fontName="Helvetica", alignment=2, textColor=DARK)
    tbl_hdr = ParagraphStyle("tbl_hdr", parent=styles["Normal"], fontSize=7.5, fontName="Helvetica-Bold", textColor=DARK)
    tbl_hdr_right = ParagraphStyle("tbl_hdr_r", parent=styles["Normal"], fontSize=7.5, fontName="Helvetica-Bold", alignment=2, textColor=DARK)
    tbl_cell = ParagraphStyle("tbl_cell", parent=styles["Normal"], fontSize=7.5, fontName="Helvetica", textColor=DARK)
    tbl_cell_right = ParagraphStyle("tbl_cell_r", parent=styles["Normal"], fontSize=7.5, fontName="Helvetica", alignment=2, textColor=DARK)
    tbl_bold_right = ParagraphStyle("tbl_b_r", parent=styles["Normal"], fontSize=8, fontName="Helvetica-Bold", alignment=2, textColor=DARK)
    footer_hdr = ParagraphStyle("f_hdr", parent=styles["Normal"], fontSize=7.5, fontName="Helvetica-Bold", textColor=DARK)
    footer_text = ParagraphStyle("f_txt", parent=styles["Normal"], fontSize=6.5, fontName="Helvetica", textColor=MUTED, leading=8.5)
    footer_contact = ParagraphStyle("f_cnt", parent=styles["Normal"], fontSize=7, fontName="Helvetica", textColor=MUTED, alignment=1)

    elements: list = []

    # ── 1. Top Section: Official Company Stamp (Left) + Corporate Brand (Right) ────
    stamp_content = [
        [Paragraph("<b>GLOBAL PROCESS & PIPELINE</b>", ParagraphStyle("st1", parent=styles["Normal"], fontSize=8, fontName="Helvetica-Bold", alignment=1, textColor=colors.HexColor("#2B4C7E")))],
        [Paragraph("<b>SERVICES CO. LTD</b>", ParagraphStyle("st2", parent=styles["Normal"], fontSize=8, fontName="Helvetica-Bold", alignment=1, textColor=colors.HexColor("#2B4C7E")))],
        [Paragraph("Plot 17, Trans-Amadi Industrial Layout", ParagraphStyle("st3", parent=styles["Normal"], fontSize=6.5, alignment=1, textColor=colors.HexColor("#333333")))],
        [Paragraph("Port Harcourt, Rivers State, Nigeria", ParagraphStyle("st4", parent=styles["Normal"], fontSize=6.5, alignment=1, textColor=colors.HexColor("#333333")))],
    ]
    stamp_table = Table(stamp_content, colWidths=[6.2 * cm])
    stamp_table.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#8DA4C4")),
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F8FAFC")),
        ("PADDING", (0, 0), (-1, -1), 3),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))

    brand_content = [
        [Paragraph("<font size='22'><b>GPPSL</b></font>", ParagraphStyle("logo_big", parent=styles["Normal"], alignment=2, fontName="Helvetica-Bold", textColor=PRIMARY))],
        [Table([[Paragraph("<b>OILFIELD SERVICES & ENGINEERING</b>", ParagraphStyle("sub_b", parent=styles["Normal"], fontSize=6.5, fontName="Helvetica-Bold", textColor=WHITE, alignment=1))]],
               colWidths=[5.5 * cm],
               style=TableStyle([("BACKGROUND", (0, 0), (-1, -1), DARK), ("PADDING", (0, 0), (-1, -1), 2)]))],
    ]
    brand_table = Table(brand_content, colWidths=[8.5 * cm], hAlign="RIGHT")
    brand_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (0, 0), (-1, -1), "RIGHT"),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))

    top_row = Table([[stamp_table, brand_table]], colWidths=[8.5 * cm, 9.8 * cm])
    top_row.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (1, 0), (1, 0), "RIGHT"),
        ("PADDING", (0, 0), (-1, -1), 0),
    ]))
    elements.append(top_row)
    elements.append(Spacer(1, 0.25 * cm))

    # ── 2. Client Statement / Invoice Title with Double Rules ───────────────────────
    elements.append(HRFlowable(width="100%", thickness=1.2, color=DARK, spaceBefore=2, spaceAfter=2))
    elements.append(Paragraph("Client Statement / Official Invoice", title_style))
    elements.append(HRFlowable(width="100%", thickness=1.2, color=DARK, spaceBefore=2, spaceAfter=5))

    # ── 3. Metadata Section (2-Column Grid) ─────────────────────────────────────────
    cl = client or {}
    cl_code = _safe(cl.get("code") or invoice.get("client_code"), "GPPSL-CL-001")
    cl_name = _safe(cl.get("name") or invoice.get("client_name"), "Valued Client")
    inv_num = _safe(invoice.get("number"), "INV-0001")
    cl_email = _safe(cl.get("email"), "accounts@client.com").upper()
    cl_phone = _safe(cl.get("phone"), "+234 000 000 0000")
    inv_date = _safe(invoice.get("issue_date"), str(date.today()))
    due_date = _safe(invoice.get("due_date"), "")
    account_mgr = _safe(invoice.get("project_manager") or invoice.get("account_manager"), "Increase George")
    print_date = datetime.now().strftime("%d/%m/%Y %I:%M %p")

    meta_left = [
        [Paragraph(f"<b>{cl_code} - {cl_name.upper()}</b>", meta_label)],
        [Paragraph(f"<b>Account / Invoice No</b>   {inv_num}", meta_val)],
        [Paragraph(f"<b>Email Address</b>   {cl_email}", meta_val)],
        [Paragraph(f"<b>Phone No</b>   {cl_phone}", meta_val)],
    ]
    meta_right = [
        [Paragraph(f"Print Date: {print_date}", meta_val_right)],
        [Paragraph(f"<b>Account / Project Lead</b>   {account_mgr}", meta_val_right)],
        [Paragraph(f"Reporting Period: {inv_date} to {due_date or 'On Completion'}", meta_val_right)],
        [Paragraph(f"Payment Terms: {_safe(invoice.get('payment_terms'), 'Net 30 Days')}", meta_val_right)],
    ]
    meta_table = Table([[Table(meta_left, colWidths=[9.5 * cm], style=TableStyle([("PADDING", (0, 0), (-1, -1), 1)])),
                         Table(meta_right, colWidths=[8.8 * cm], style=TableStyle([("PADDING", (0, 0), (-1, -1), 1)]))]],
                       colWidths=[9.5 * cm, 8.8 * cm])
    meta_table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("PADDING", (0, 0), (-1, -1), 0)]))
    elements.append(meta_table)
    elements.append(Spacer(1, 0.25 * cm))

    # ── 4. Valuation & Summary Highlight Box ───────────────────────────────────────
    amount = float(invoice.get("amount") or 0)
    subtotal = float(invoice.get("subtotal") or amount)
    vat_amount = float(invoice.get("vat_amount") or 0)
    paid = float(invoice.get("paid_amount") or 0)
    outstanding = max(0.0, amount - paid)

    fund_rows = [
        [Paragraph("<b>FUND / SERVICE PARTICULARS</b>", tbl_hdr), Paragraph("<b>VALUE</b>", tbl_hdr_right)],
        [Paragraph(_safe(invoice.get("service_type"), "Core Pipeline & Process Operations"), tbl_cell), Paragraph(_naira(subtotal), tbl_cell_right)],
        [Paragraph("VAT & Statutory Charges (7.5%)", tbl_cell), Paragraph(_naira(vat_amount), tbl_cell_right)],
        [Paragraph("Penalties / Administrative Charges", tbl_cell), Paragraph("NGN 0.00", tbl_cell_right)],
        [Paragraph("<b>TOTAL VALUATION</b>", tbl_hdr), Paragraph(f"<b>{_naira(amount)}</b>", tbl_hdr_right)],
    ]
    fund_table = Table(fund_rows, colWidths=[4.8 * cm, 3.2 * cm])
    fund_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), LIGHT_GRAY),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#D8D8D8")),
        ("LINEBELOW", (0, 0), (-1, 0), 0.5, BORDER_GRAY),
        ("LINEABOVE", (0, -1), (-1, -1), 0.8, DARK),
        ("PADDING", (0, 0), (-1, -1), 2.5),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))

    summary_rows = [
        [Paragraph("Total Amount Invoiced:", tbl_cell), Paragraph(f"<b>{_naira(amount)}</b>", tbl_cell_right)],
        [Paragraph("Total Amount Received:", tbl_cell), Paragraph(f"<b>{_naira(paid)}</b>", tbl_cell_right)],
        [Paragraph("<b>Balance Outstanding:</b>", tbl_hdr), Paragraph(f"<b>{_naira(outstanding)}</b>", tbl_hdr_right)],
        [Paragraph("Status:", tbl_cell), Paragraph(f"<b>{_safe(invoice.get('status'), 'SENT').upper()}</b>", tbl_cell_right)],
    ]
    summary_table = Table(summary_rows, colWidths=[4.8 * cm, 3.5 * cm])
    summary_table.setStyle(TableStyle([
        ("PADDING", (0, 0), (-1, -1), 3),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LINEBELOW", (0, 2), (-1, 2), 0.5, BORDER_GRAY),
    ]))

    val_box = Table([[fund_table, summary_table]], colWidths=[8.5 * cm, 9.8 * cm])
    val_box.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("PADDING", (0, 0), (-1, -1), 0),
    ]))
    elements.append(val_box)
    elements.append(Spacer(1, 0.3 * cm))

    # ── 5. Detailed Line Items Table ───────────────────────────────────────────────
    items = invoice.get("items") or []
    if not items:
        items = [{"description": invoice.get("service_type") or "Oilfield Services & Engineering Support",
                  "quantity": 1, "unit": "Unit", "rate": subtotal, "amount": subtotal}]

    line_headers = [
        Paragraph("<b>DATE</b>", tbl_hdr),
        Paragraph("<b>TRANS / SERVICE TYPE</b>", tbl_hdr),
        Paragraph("<b>AMOUNT</b>", tbl_hdr_right),
        Paragraph("<b>PRICE</b>", tbl_hdr_right),
        Paragraph("<b>UNITS</b>", tbl_hdr_right),
        Paragraph("<b>TOTAL</b>", tbl_hdr_right),
        Paragraph("<b>VALUE REF / DETAILS</b>", tbl_hdr),
    ]

    table_data = [line_headers]
    # Opening balance line
    table_data.append([
        Paragraph(inv_date, tbl_cell),
        Paragraph("<b>OPENING BAL</b>", tbl_cell),
        Paragraph("0.00", tbl_cell_right),
        Paragraph("1.00", tbl_cell_right),
        Paragraph("0.00", tbl_cell_right),
        Paragraph("0.00", tbl_cell_right),
        Paragraph("Opening ledger balance", tbl_cell),
    ])

    cumulative_units = 0.0
    for it in items:
        qty = float(it.get("quantity") or it.get("qty") or 1)
        rate = float(it.get("rate") or it.get("unit_price") or 0)
        it_amount = float(it.get("amount") or (qty * rate))
        cumulative_units += qty
        table_data.append([
            Paragraph(inv_date, tbl_cell),
            Paragraph(_safe(it.get("description")), tbl_cell),
            Paragraph(f"{it_amount:,.2f}", tbl_cell_right),
            Paragraph(f"{rate:,.2f}", tbl_cell_right),
            Paragraph(f"{qty:g}", tbl_cell_right),
            Paragraph(f"{it_amount:,.2f}", tbl_cell_right),
            Paragraph(f"{inv_num} | {_safe(it.get('unit'), 'Job')}", tbl_cell),
        ])

    # Closing balance line
    table_data.append([
        Paragraph("", tbl_cell),
        Paragraph("<b>CLOSING BAL</b>", tbl_hdr),
        Paragraph(f"<b>{subtotal:,.2f}</b>", tbl_bold_right),
        Paragraph("1.00", tbl_cell_right),
        Paragraph(f"<b>{cumulative_units:g}</b>", tbl_bold_right),
        Paragraph(f"<b>{subtotal:,.2f}</b>", tbl_bold_right),
        Paragraph(f"<b>Total Settled: {paid:,.2f}</b>", tbl_hdr),
    ])

    line_table = Table(
        table_data,
        colWidths=[1.8 * cm, 4.8 * cm, 2.2 * cm, 1.8 * cm, 1.5 * cm, 2.4 * cm, 3.8 * cm],
    )
    line_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#D8D8D8")),
        ("LINEBELOW", (0, 0), (-1, 0), 1, DARK),
        ("PADDING", (0, 0), (-1, -1), 2.2),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEABOVE", (0, -1), (-1, -1), 0.8, DARK),
        ("BACKGROUND", (0, -1), (-1, -1), LIGHT_GRAY),
    ]))
    elements.append(line_table)
    elements.append(Spacer(1, 0.4 * cm))

    # ── 6. Multi-Branch Address Footer ─────────────────────────────────────────────
    footer_cols = [
        [
            Paragraph("<b>Lagos</b>", footer_hdr),
            Paragraph("1, Mekunwen Road, Off Oyinkan Abayomi Drive, Ikoyi, Lagos State", footer_text),
        ],
        [
            Paragraph("<b>Port Harcourt HQ</b>", footer_hdr),
            Paragraph("Plot 17 Trans-Amadi Industrial Layout, Port Harcourt, Rivers State", footer_text),
        ],
        [
            Paragraph("<b>Abuja</b>", footer_hdr),
            Paragraph("129, Adetokunbo Ademola Crescent, Wuse II, Abuja FCT", footer_text),
        ],
        [
            Paragraph("<b>Warri</b>", footer_hdr),
            Paragraph("Enerhen Junction Industrial Yard, Airport Road, Warri, Delta State", footer_text),
        ],
    ]

    branch_table = Table(
        [[Table(c, colWidths=[4.4 * cm], style=TableStyle([("PADDING", (0, 0), (-1, -1), 1)])) for c in footer_cols]],
        colWidths=[4.5 * cm, 4.6 * cm, 4.5 * cm, 4.5 * cm],
    )
    branch_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("PADDING", (0, 0), (-1, -1), 0),
    ]))
    elements.append(branch_table)
    elements.append(Spacer(1, 0.15 * cm))

    elements.append(HRFlowable(width="100%", thickness=0.5, color=BORDER_GRAY, spaceBefore=2, spaceAfter=3))
    elements.append(Paragraph(
        "For enquiries: Please contact the support and finance unit at <u>accounts@gppsl.com</u> or call us on <b>+234 84 463 800</b>",
        footer_contact,
    ))

    doc.build(elements)
    return buf.getvalue()
