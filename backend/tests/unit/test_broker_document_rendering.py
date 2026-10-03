from datetime import datetime, timezone
from decimal import Decimal
from io import BytesIO

import pytest
from PIL import Image
from pydantic import ValidationError
from pypdf import PdfReader

from app.crm.document_models import (
    BrokerDocumentCreate,
    BrokerDocumentData,
    DocumentField,
    DocumentMedia,
    DocumentProperty,
    QuotationCharge,
)
from app.crm.document_rendering import quotation, render_pdf, sanitize_media


def test_independent_quotation_totals_distinguish_missing_estimates_and_rounding():
    charges = [
        QuotationCharge(label="Brokerage", percent_of_asking=Decimal("2"), status="known"),
        QuotationCharge(label="Administration", amount=Decimal("500.50"), status="estimate"),
    ]
    quote = quotation("1100000.00", "sell", charges, ["Transfer charge"])
    assert quote.lines[1].amount == "22000.00"
    assert quote.known_total == "1122000.00"
    assert quote.estimated_total == "500.50"
    assert quote.total is None  # Unknown charges must not become zero or a misleading final total.
    assert quote.missing_charges == ["Transfer charge"]
    complete = quotation("1100000.00", "sell", charges, [])
    assert complete.total == "1122500.50"
    fractional = quotation(
        "999.99",
        "sell",
        [QuotationCharge(label="Fee", percent_of_asking=Decimal("2.5"), status="known")],
        [],
    )
    assert fractional.lines[1].amount == "25.00"
    assert fractional.total == "1024.99"
    missing = quotation(None, "sell", charges, [])
    assert missing.total is None
    assert (
        missing.lines[1].status == "missing"
    )  # No percentage multiplication using an invented price.


def test_pdf_contains_exact_preview_figures_and_never_fetches_source_urls(tmp_path):
    image = BytesIO()
    Image.new("RGB", (80, 50), "navy").save(image, "PNG")
    approved = sanitize_media(image.getvalue())
    doc = BrokerDocumentData(
        brand="Fixture Brokerage",
        title="Draft property quotation",
        reference="Q-2026-001",
        version=2,
        valid_until=None,
        prepared_at=datetime(2026, 10, 3, tzinfo=timezone.utc),
        properties=[
            DocumentProperty(
                reference="PF-FIXTURE-1",
                title="Apartment in Dubai Marina",
                facts=[DocumentField(label="Bedrooms", value="2")],
                evidence_date="2026-10-02",
                asking_price="1100000.00",
                currency="AED",
                price_unit="sell",
                selling_points=["Bedrooms: 2"],
                trade_offs=["Availability requires confirmation"],
                missing_information=["Floor plan not supplied"],
                media=[
                    DocumentMedia(
                        id="approved-1", kind="image", caption="Broker-approved property image"
                    )
                ],
            )
        ],
        quotation=quotation(
            "1100000.00",
            "sell",
            [
                QuotationCharge(label="Brokerage", amount=Decimal("22000"), status="known"),
                QuotationCharge(
                    label="Administration", amount=Decimal("500.50"), status="estimate"
                ),
            ],
            ["Transfer charge"],
        ),
        limitations=["Internal notes and contacts are excluded"],
    )
    pdf = render_pdf(doc, {"approved-1": approved})
    assert pdf.startswith(b"%PDF-")
    reader = PdfReader(BytesIO(pdf))
    text = "\n".join(page.extract_text() for page in reader.pages)
    for value in (
        "Q-2026-001",
        "Version 2",
        "1100000.00",
        "22000.00",
        "500.50",
        "1122000.00",
        "Transfer charge",
        "Complete total unavailable",
    ):
        assert value in text
    assert sum(len(page.images) for page in reader.pages) == 1
    assert all("/Annots" not in page for page in reader.pages)
    (tmp_path / "demonstrated-quotation.pdf").write_bytes(pdf)


@pytest.mark.parametrize(
    "value",
    [
        b'<svg><image href="http://169.254.169.254/"/></svg>',
        b"http://example.org/image.jpg",
        b"not an image",
    ],
)
def test_approved_media_accepts_only_decoded_raster_bytes(value):
    with pytest.raises(Exception):
        sanitize_media(value)


def test_quotation_rejects_invented_zero_missing_fees_and_multi_property_total():
    with pytest.raises(ValidationError):
        QuotationCharge(label="Unknown fee", status="missing", amount=0)
    with pytest.raises(ValidationError):
        QuotationCharge(label="Fee", status="known")
    with pytest.raises(ValidationError):
        BrokerDocumentCreate(
            enquiry_id=1, kind="quotation", match_ids=[1, 2], reference="Q1", idempotency_key="q1"
        )


def test_quotation_model_cannot_introduce_fees_absent_from_broker_instruction():
    from fastapi import HTTPException

    from app.chat.broker_scope import verify_quotation_charges

    charges = [
        QuotationCharge(label="Brokerage", percent_of_asking=Decimal("2"), status="known"),
        QuotationCharge(label="Administration", amount=Decimal("500.50"), status="estimate"),
    ]
    verify_quotation_charges(
        charges, "Prepare a quotation. Brokerage: 2%; Administration (estimate): AED 500.50"
    )
    for message in (
        None,
        "Prepare a quotation",
        "Brokerage: 3%; Administration (estimate): AED 500.50",
        "Brokerage: 2%; Administration: AED 500.50",
    ):
        with pytest.raises(HTTPException):
            verify_quotation_charges(charges, message)


def test_duplicate_charges_cannot_double_count_a_single_broker_fee():
    with pytest.raises(ValidationError, match="distinct"):
        BrokerDocumentCreate(
            enquiry_id=1,
            kind="quotation",
            match_ids=[1],
            reference="Q1",
            idempotency_key="q1",
            charges=[
                {"label": "Brokerage", "amount": "22000", "status": "known"},
                {"label": " brokerage ", "amount": "22000", "status": "known"},
            ],
        )


def test_missing_charges_cannot_be_silently_removed_from_chat_quotation():
    from fastapi import HTTPException

    from app.chat.broker_scope import verify_quotation_charges

    with pytest.raises(HTTPException):
        verify_quotation_charges([], "Please prepare a quotation", [])
    verify_quotation_charges([], "Charges complete: yes", [])
