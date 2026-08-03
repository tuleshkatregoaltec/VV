from app.crm.inbound_service import (
    _bedroom_fit,
    _best_header,
    _budget_fit,
    _deterministic_criteria,
    _file_rows,
    _location_fit,
    _normalize_intent,
    _redact,
    _violates_strict_fields,
)


def test_deterministic_extraction_understands_common_campaign_message():
    criteria = _deterministic_criteria(
        {},
        "Looking to buy a 2 bedroom apartment in JBR with a budget up to 3m",
    )

    assert criteria["locations"] == ["JBR"]
    assert criteria["bedrooms_min"] == 2
    assert criteria["bedrooms_max"] == 2
    assert criteria["budget_max_aed"] == 3_000_000
    assert _normalize_intent("", "Looking to buy a 2 bedroom in JBR") == "buy"


def test_campaign_context_can_guide_sparse_contacts_without_forcing_ambiguous_intent():
    assert (
        _normalize_intent(
            "",
            "Meta valuation campaign shown to Business Bay property owners",
        )
        == "sell"
    )
    assert (
        _normalize_intent(
            "",
            "The form did not ask whether the person wants to buy, sell, rent, or let",
        )
        is None
    )


def test_redaction_removes_contact_identity_before_ai_extraction():
    redacted = _redact(
        "Call Jane Example on +971 50 123 4567 or jane@example.com, Emirates ID 784123456789012",
        ["Jane Example"],
    )

    assert "Jane Example" not in redacted
    assert "jane@example.com" not in redacted
    assert "501234567" not in redacted.replace(" ", "")
    assert "784123456789012" not in redacted
    assert "[REDACTED]" in redacted
    assert "[EMAIL]" in redacted
    assert "[PHONE]" in redacted
    assert "[ID]" in redacted


def test_header_detection_skips_export_title_and_blank_preamble():
    rows = [
        ("Meta campaign export", None, None),
        (None, None, None),
        ("Lead Name", "Mobile Number", "Requirements"),
        ("Maya", "+971501234567", "2 bed JBR"),
    ]

    index, _, mapping = _best_header(rows)

    assert index == 2
    assert mapping == {"full_name": 0, "phone": 1, "notes": 2}


def test_csv_mapping_preserves_source_row_and_header_audit():
    rows, audit = _file_rows(
        b"Campaign leads,,\n\nLead Name,Mobile,Looking For,Requirements\nMaya,0501234567,Buyer,2 bed JBR\n",
        "summer-campaign.csv",
    )

    assert len(rows) == 1
    assert rows[0][1] == 4
    assert rows[0][2]["full_name"] == "Maya"
    assert rows[0][2]["intent"] == "Buyer"
    assert audit["sheets"][0]["header_row"] == 3


def test_match_scoring_distinguishes_exact_flexible_and_outside():
    criteria = {
        "locations": ["JBR"],
        "bedrooms_min": 2,
        "budget_min_aed": 2_500_000,
        "budget_max_aed": 3_000_000,
    }

    assert _location_fit(criteria, "Jumeirah Beach Residence (JBR)")[0] == 20
    assert _bedroom_fit(criteria, "2 Bed")[0] == 10
    assert _budget_fit(criteria, 2_900_000)[0] == 15
    assert _budget_fit(criteria, 3_150_000)[0] == 9
    assert _budget_fit(criteria, 4_000_000)[0] == 0


def test_hard_criteria_exclude_matches_while_flexible_fields_only_reduce_score():
    assert _violates_strict_fields(
        ["locations"],
        location_points=0,
        budget_points=15,
        bedroom_points=10,
        property_points=10,
    )
    assert not _violates_strict_fields(
        [],
        location_points=0,
        budget_points=0,
        bedroom_points=0,
        property_points=0,
    )
