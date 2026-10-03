"""Deterministic PDF output from the same structured snapshot shown in chat."""

from decimal import ROUND_HALF_UP, Decimal
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape

import reportlab
from PIL import Image as PILImage
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer

from app.crm.document_models import DocumentQuotation, QuotationLine


def money(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), ".2f")


def quotation(
    asking_price: str | None, price_unit: str, charges, missing_charges
) -> DocumentQuotation:
    asking = Decimal(asking_price) if asking_price is not None else None
    lines = [
        QuotationLine(
            label="Recorded asking price",
            amount=money(asking) if asking is not None else None,
            status="known" if asking is not None else "missing",
            basis=price_unit + "; not a confirmed offer or availability",
        )
    ]
    for charge in charges:
        amount = charge.amount
        basis = "Explicit broker-supplied amount"
        if charge.percent_of_asking is not None:
            amount = asking * charge.percent_of_asking / 100 if asking is not None else None
            basis = f"Explicit broker-supplied {charge.percent_of_asking}% of recorded asking price"
        lines.append(
            QuotationLine(
                label=charge.label,
                amount=money(amount) if amount is not None else None,
                status=charge.status if amount is not None else "missing",
                basis=basis,
            )
        )
    lines.extend(
        QuotationLine(
            label=label, amount=None, status="missing", basis="Not supplied; not treated as zero"
        )
        for label in missing_charges
    )
    known = sum((Decimal(line.amount) for line in lines if line.status == "known"), Decimal(0))
    estimated = sum(
        (Decimal(line.amount) for line in lines if line.status == "estimate"), Decimal(0)
    )
    missing = [line.label for line in lines if line.status == "missing"]
    return DocumentQuotation(
        currency="AED",
        lines=lines,
        known_total=money(known),
        estimated_total=money(estimated),
        total=None if missing else money(known + estimated),
        missing_charges=missing,
    )


def sanitize_media(data: bytes) -> bytes:
    if len(data) > 4 * 1024 * 1024:
        raise ValueError("Image exceeds 4 MiB")
    with PILImage.open(BytesIO(data)) as source:
        if source.format not in {"PNG", "JPEG"} or source.width * source.height > 16_000_000:
            raise ValueError("Only bounded PNG/JPEG images are supported")
        source.load()
        source.thumbnail((1800, 1800))
        output = BytesIO()
        source.convert("RGB").save(output, "JPEG", quality=85)
        return output.getvalue()


def render_pdf(document, media: dict[str, bytes]) -> bytes:
    # ReportLab parses only our escaped paragraphs; it never receives HTML, URLs or file paths.
    font = "BrokerVera"
    if font not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(
            TTFont(font, str(Path(reportlab.__file__).parent / "fonts" / "Vera.ttf"))
        )
    styles = getSampleStyleSheet()
    for style in styles.byName.values():
        style.fontName = font
    styles["Normal"].fontSize = 10
    styles["Normal"].leading = 15
    styles["Heading1"].textColor = colors.HexColor("#17334d")
    story = []

    def paragraph(text, style="Normal"):
        text = str(text)
        glyphs = pdfmetrics.getFont(font).face.charToGlyph
        if any(ord(char) not in glyphs and char not in "\n\r\t" for char in text):
            raise ValueError("unsupported_document_glyph")
        story.append(Paragraph(escape(text).replace("\n", "<br/>"), styles[style]))
        story.append(Spacer(1, 2 * mm))

    paragraph(document.brand, "Title")
    paragraph(document.title, "Heading1")
    paragraph(f"Reference {document.reference} | Version {document.version}")
    paragraph(
        f"Prepared {document.prepared_at.isoformat()} | Valid until {document.valid_until or 'Not specified'}"
    )
    for prop in document.properties:
        paragraph(prop.title, "Heading2")
        paragraph(f"Property reference: {prop.reference} | Evidence: {prop.evidence_date}")
        paragraph(
            f"Recorded asking price: {prop.currency} {prop.asking_price or 'Not recorded'} ({prop.price_unit})"
        )
        for fact in prop.facts:
            paragraph(f"{fact.label}: {fact.value}")
        for title, values in [
            ("Supported facts", prop.selling_points),
            ("Trade-offs", prop.trade_offs),
            ("Missing information", prop.missing_information),
        ]:
            if values:
                paragraph(title, "Heading3")
                for value in values:
                    paragraph(value)
        for item in prop.media:
            raw = media.get(item.id)
            if raw is None:
                raise ValueError("approved_media_unavailable")
            image = Image(BytesIO(raw), width=160 * mm, height=100 * mm, kind="proportional")
            story.append(image)
            paragraph(item.caption)
    for section in document.sections:
        paragraph(section.title, "Heading2")
        for row in section.rows:
            paragraph(f"{row.label}: {row.value}")
    if document.quotation:
        quote = document.quotation
        paragraph("Draft quotation", "Heading2")
        for line in quote.lines:
            paragraph(
                f"{line.label}: {quote.currency} {line.amount if line.amount is not None else 'Missing'} [{line.status}] | {line.basis}"
            )
        paragraph(f"Known subtotal: {quote.currency} {quote.known_total}")
        paragraph(f"Estimated charges subtotal: {quote.currency} {quote.estimated_total}")
        paragraph(
            f"Total including estimates: {quote.currency} {quote.total}"
            if quote.total is not None
            else "Complete total unavailable: charges or asking price are missing."
        )
    paragraph("Evidence and limitations", "Heading2")
    for note in document.limitations:
        paragraph(note)
    output = BytesIO()
    SimpleDocTemplate(
        output,
        pagesize=(210 * mm, 297 * mm),
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title=document.title,
        author=document.brand,
    ).build(story)
    result = output.getvalue()
    if len(result) > 12 * 1024 * 1024:
        raise ValueError("document_size_exceeded")
    return result
