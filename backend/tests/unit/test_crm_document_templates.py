import pytest
from crm_document_helpers import listing

from app.crm.document_models import DocumentFields
from app.crm.document_templates import TEMPLATES, build_snapshot, missing_fields

FULL = DocumentFields.model_validate(
    {
        "owner": {
            "full_name": "Aisha Khan",
            "phone": "+971500000001",
            "email": "aisha@example.com",
            "title_deed_number": "TD-2024-1",
            "id_number": "784-1990-1234567-1",
        },
        "lease": {
            "tenant_name": "Omar Ali",
            "tenant_phone": "+971500000002",
            "start_date": "2026-12-01",
            "end_date": "2027-11-30",
            "annual_rent_aed": 120000,
            "cheques": 4,
            "security_deposit_aed": 6000,
        },
        "a2a": {
            "other_brokerage": "Partner Realty",
            "other_broker_name": "Sara",
            "other_broker_brn": "BRN-1",
            "commission_split_pct": "50",
            "valid_until": "2027-01-31",
        },
        "marketing": {"description": "Sea view"},
    }
)


def snapshot(doc_type, fields=FULL):
    return build_snapshot(listing(), fields, doc_type)


def test_every_document_type_has_a_draft_template():
    assert set(TEMPLATES) == {"noc", "brochure", "lease", "a2a"}
    assert all(spec.version == "draft-1" for spec in TEMPLATES.values())


@pytest.mark.parametrize("doc_type", ["noc", "brochure", "lease", "a2a"])
def test_complete_information_has_nothing_missing(doc_type):
    assert missing_fields(doc_type, snapshot(doc_type)) == []


def test_noc_without_title_deed_is_blocked():
    fields = FULL.model_copy(deep=True)
    fields.owner.title_deed_number = None
    assert missing_fields("noc", snapshot("noc", fields)) == ["owner.title_deed_number"]


def test_blank_text_counts_as_missing():
    # Whitespace must never render as an empty legal clause.
    fields = DocumentFields.model_validate(
        {**FULL.model_dump(mode="json"), "owner": {**FULL.owner.model_dump(), "id_number": "   "}}
    )
    assert "owner.id_number" in missing_fields("noc", snapshot("noc", fields))


def test_lease_lists_every_missing_term_in_order():
    missing = missing_fields("lease", snapshot("lease", DocumentFields()))
    assert missing[:2] == ["owner.full_name", "lease.tenant_name"]
    assert "lease.annual_rent_aed" in missing and "lease.tenant_email" not in missing


def test_brochure_needs_only_listing_fields():
    assert missing_fields("brochure", snapshot("brochure", DocumentFields())) == []


def test_brochure_snapshot_carries_no_private_data():
    assert set(snapshot("brochure")) == {"listing", "marketing"}


def test_a2a_snapshot_carries_no_owner_or_lease_data():
    assert set(snapshot("a2a")) == {"listing", "a2a"}


def test_snapshot_is_plain_json():
    lease = snapshot("lease")
    assert lease["lease"]["start_date"] == "2026-12-01"
    assert lease["listing"]["reference"] == "PF-123"
