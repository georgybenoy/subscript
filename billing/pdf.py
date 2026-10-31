"""
PDF invoice generation module using ReportLab.

Specifications:
- Renders only from stored invoice, item, and payment records
- Universal font compatibility: uses 'INR' currency prefix for guaranteed rendering
- Permitted strictly for CONFIRMED and PAID invoices
"""

import io
from decimal import Decimal
from django.core.exceptions import ValidationError
from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
from .models import Invoice, InvoiceStatus


CURRENCY_PREFIX = "INR "


def generate_invoice_pdf(invoice: Invoice) -> bytes:
    """
    Renders an authoritative PDF statement for an invoice.
    Raises ValidationError if invoice is DRAFT or CANCELLED.
    """
    if invoice.status not in [InvoiceStatus.CONFIRMED, InvoiceStatus.PAID]:
        raise ValidationError(
            f"PDF invoice download is only permitted for CONFIRMED or PAID invoices (current: {invoice.status})."
        )

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        leftMargin=36,
        rightMargin=36,
        topMargin=36,
        bottomMargin=36,
    )

    styles = getSampleStyleSheet()

    # Custom styles
    brand_style = ParagraphStyle(
        "BrandHeader",
        parent=styles["Heading1"],
        fontName="Helvetica-Bold",
        fontSize=20,
        leading=24,
        textColor=colors.HexColor("#0d6efd"),
    )
    meta_title_style = ParagraphStyle(
        "MetaTitle",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=12,
        leading=16,
        alignment=2,  # Right
        textColor=colors.HexColor("#212529"),
    )
    meta_text_style = ParagraphStyle(
        "MetaText",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=9,
        leading=13,
        alignment=2,  # Right
        textColor=colors.HexColor("#6c757d"),
    )
    section_title = ParagraphStyle(
        "SectionTitle",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=9,
        leading=12,
        textColor=colors.HexColor("#6c757d"),
    )
    body_bold = ParagraphStyle(
        "BodyBold",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=10,
        leading=14,
        textColor=colors.HexColor("#212529"),
    )
    body_text = ParagraphStyle(
        "BodyText",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=9,
        leading=13,
        textColor=colors.HexColor("#495057"),
    )
    table_header = ParagraphStyle(
        "TableHeader",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=9,
        leading=12,
        textColor=colors.HexColor("#ffffff"),
    )
    table_cell = ParagraphStyle(
        "TableCell",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=9,
        leading=12,
        textColor=colors.HexColor("#212529"),
    )
    table_cell_right = ParagraphStyle(
        "TableCellRight",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=9,
        leading=12,
        alignment=2,
        textColor=colors.HexColor("#212529"),
    )

    elements = []

    # 1. Header (Brand vs Invoice Number)
    header_data = [
        [
            Paragraph("<b>SUBSCRIPT</b>", brand_style),
            Paragraph(f"<b>INVOICE #{invoice.invoice_number}</b>", meta_title_style),
        ],
        [
            Paragraph("Subscript Billing Platform Inc.<br/>Tax ID: SUBSCRIPT-GST-9921", body_text),
            Paragraph(
                f"Issue Date: {invoice.issue_date.strftime('%b %d, %Y')}<br/>"
                f"Due Date: {invoice.due_date.strftime('%b %d, %Y')}<br/>"
                f"Billing Period: {invoice.billing_period_start.strftime('%b %d')} - {invoice.billing_period_end.strftime('%b %d, %Y')}<br/>"
                f"Status: <b>{invoice.status}</b>",
                meta_text_style,
            ),
        ],
    ]
    header_table = Table(header_data, colWidths=[270, 270])
    header_table.setStyle(
        TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ])
    )
    elements.append(header_table)
    elements.append(Spacer(1, 16))
    elements.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#dee2e6"), spaceAfter=14))

    # 2. Bill To & Subscription details
    cust = invoice.customer
    cust_name = cust.name if cust else "Valued Subscriber"
    cust_company = cust.company_name if cust and cust.company_name else ""
    cust_email = cust.email if cust else ""
    cust_address = cust.billing_address if cust and cust.billing_address else ""
    cust_tax = f"Tax ID / GSTIN: {cust.tax_id}" if cust and cust.tax_id else ""

    bill_to_text = f"<b>{cust_name}</b><br/>"
    if cust_company:
        bill_to_text += f"{cust_company}<br/>"
    if cust_email:
        bill_to_text += f"{cust_email}<br/>"
    if cust_address:
        bill_to_text += f"{cust_address}<br/>"
    if cust_tax:
        bill_to_text += f"{cust_tax}<br/>"

    sub_number = invoice.subscription.subscription_number if invoice.subscription else "N/A"
    sub_text = (
        f"<b>Subscription:</b> {sub_number}<br/>"
        f"<b>Plan:</b> {invoice.subscription.plan.name if invoice.subscription and invoice.subscription.plan else 'Custom Agreement'}<br/>"
        f"<b>Payment Terms:</b> {getattr(invoice.subscription, 'payment_terms', 15)} days"
    )

    client_table_data = [
        [Paragraph("BILLED TO", section_title), Paragraph("SUBSCRIPTION DETAILS", section_title)],
        [Paragraph(bill_to_text, body_text), Paragraph(sub_text, body_text)],
    ]
    client_table = Table(client_table_data, colWidths=[300, 240])
    client_table.setStyle(
        TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ])
    )
    elements.append(client_table)
    elements.append(Spacer(1, 18))

    # 3. Line Items Table
    item_rows = [
        [
            Paragraph("Item Description", table_header),
            Paragraph("Qty", table_header),
            Paragraph("Unit Price", table_header),
            Paragraph("Tax", table_header),
            Paragraph("Line Total", table_header),
        ]
    ]

    for item in invoice.items.all():
        desc = item.description or (item.product.name if item.product else "Service Item")
        item_rows.append([
            Paragraph(desc, table_cell),
            Paragraph(str(item.quantity), table_cell),
            Paragraph(f"{CURRENCY_PREFIX}{item.unit_price}", table_cell_right),
            Paragraph(f"{item.tax_rate}%", table_cell_right),
            Paragraph(f"{CURRENCY_PREFIX}{item.line_total}", table_cell_right),
        ])

    items_table = Table(item_rows, colWidths=[220, 45, 95, 70, 110])
    items_table.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#212529")),
            ("ALIGN", (1, 0), (1, -1), "CENTER"),
            ("ALIGN", (2, 0), (-1, -1), "RIGHT"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.HexColor("#f8f9fa"), colors.HexColor("#ffffff")]),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e9ecef")),
        ])
    )
    elements.append(items_table)
    elements.append(Spacer(1, 14))

    # 4. Totals Summary Table
    paid_amt = invoice.paid_amount
    balance_due = invoice.outstanding_balance

    totals_data = [
        [Paragraph("Subtotal:", table_cell_right), Paragraph(f"{CURRENCY_PREFIX}{invoice.subtotal}", table_cell_right)],
        [Paragraph("Discount Applied:", table_cell_right), Paragraph(f"-{CURRENCY_PREFIX}{invoice.discount_amount}", table_cell_right)],
        [Paragraph("Applicable Tax:", table_cell_right), Paragraph(f"{CURRENCY_PREFIX}{invoice.tax_amount}", table_cell_right)],
        [Paragraph("<b>Total Amount:</b>", table_cell_right), Paragraph(f"<b>{CURRENCY_PREFIX}{invoice.total_amount}</b>", table_cell_right)],
        [Paragraph("Total Amount Paid:", table_cell_right), Paragraph(f"{CURRENCY_PREFIX}{paid_amt}", table_cell_right)],
        [Paragraph("<b>Balance Due:</b>", table_cell_right), Paragraph(f"<b>{CURRENCY_PREFIX}{balance_due}</b>", table_cell_right)],
    ]
    totals_table = Table(totals_data, colWidths=[410, 130])
    totals_table.setStyle(
        TableStyle([
            ("ALIGN", (0, 0), (-1, -1), "RIGHT"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("LINEABOVE", (0, 3), (1, 3), 1, colors.HexColor("#212529")),
            ("LINEBELOW", (0, 3), (1, 3), 1, colors.HexColor("#212529")),
            ("LINEABOVE", (0, 5), (1, 5), 1, colors.HexColor("#0d6efd")),
        ])
    )
    elements.append(totals_table)
    elements.append(Spacer(1, 24))

    # 5. Footer & Audit Note
    elements.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#ced4da"), spaceAfter=8))
    footer_text = (
        "Thank you for choosing Subscript. All recurring fees are billed per terms of agreement.<br/>"
        "For billing inquiries or wire reconciliation, contact support@subscript.local."
    )
    elements.append(Paragraph(footer_text, body_text))

    doc.build(elements)
    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes
