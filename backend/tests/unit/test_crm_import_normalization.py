"""Formatting equivalence must not manufacture transaction or location evidence."""

from decimal import Decimal

import pytest

from app.crm.identity import _property_scopes_compatible
from app.crm.import_normalization import (
    location_evidence,
    normalize_location,
    parse_decimal,
    positive_decimal,
)
from app.crm.import_parsing import _candidate_from_row, _inspect_csv, _parse_amount


@pytest.mark.parametrize(
    "value",
    [
        70000,
        70000.0,
        "70000",
        "70,000",
        "70000.0",
        "70 000",
        "70\u00a0000",
        "70\u202f000",
        " AED ٧٠,٠٠٠.٠ ",
        "７００００ AED",
    ],
)
def test_amount_formatting_is_equivalent_without_float_conversion(value):
    assert parse_decimal(value) == positive_decimal(value) == Decimal("70000")
    assert _parse_amount(value) == 70000


@pytest.mark.parametrize(
    "value",
    [
        None,
        True,
        "",
        "7,00",
        "70 00",
        "70,000 000",
        "price 70000",
        "70-000",
        "1/2",
        "AED70AED",
        "1e5",
        "NaN",
        "Infinity",
        float("nan"),
        float("inf"),
        Decimal("NaN"),
    ],
)
def test_bad_numbers_cannot_become_transaction_evidence(value):
    assert parse_decimal(value) is None
    assert positive_decimal(value) is None
    assert _parse_amount(value) is None


@pytest.mark.parametrize(
    "value", [-70000, "-70,000", "AED -70 000", "−70000", "(70,000)", 0, "0.00"]
)
def test_negative_and_zero_never_flip_to_positive(value):
    assert positive_decimal(value) is None
    assert _parse_amount(value) is None


def test_decimal_precision_and_historical_whole_aed_rounding():
    value = "123456789012345678901234567890.1234567890123456789"
    assert parse_decimal(value) == Decimal(value)
    assert [_parse_amount(item) for item in ("2.5", "3.5", "0.4", "0.6")] == [2, 4, None, 1]


def test_location_aliases_are_explicit_and_levels_keep_tower_and_phase_identity():
    assert normalize_location(" JVC ", area=True) == "jumeirah village circle"
    assert normalize_location(" Dubai  Hills ", area=True) == "dubai hills estate"
    assert normalize_location(" JVC  Tower 2 ", area=True) == "jvc tower 2"
    assert normalize_location(" JVC ") == "jvc"
    assert location_evidence("JVC Tower 2", "Phase 1", "Tower 2")["community_keys"] == [
        "jvc tower 2"
    ]
    assert location_evidence("Dubai Hills", "Phase 1", "Tower 2")["community_keys"] == [
        "dubai hills estate",
        "dubai hills",
    ]
    assert _property_scopes_compatible(
        {"area_name": "Dubai Hills"}, {"area_name": "Dubai Hills Estate"}
    )
    for field, left, right in (
        ("project_name", "Maple Phase 1", "Maple Phase 2"),
        ("area_name", "JVC Tower 2", "JVC"),
    ):
        assert not _property_scopes_compatible({field: left}, {field: right})


def test_live_parser_keeps_contact_only_rows_and_raw_fields_with_invalid_price():
    data = b"Name,Mobile,Area,Project,Building,Unit,Price\nPrivate Person,0501234567,JVC,Phase 1,Tower 2,0012,-70,000\n"
    # Supply exact values directly: comma-bearing amounts are one cell, not CSV columns.
    profile = _inspect_csv(data, "owners.csv")[0]
    row = ("Private Person", "0501234567", "JVC", "Phase 1", "Tower 2", "0012", "-70,000")
    contact = _candidate_from_row(row, profile=profile, filename="owners.csv", row_number=2)
    assert contact is not None and contact.transaction_price_aed is None
    assert contact.unit_number == "0012"
    assert contact.area_name == "JVC" and contact.building_name == "Tower 2"
    assert contact.evidence["source_fields"]["transaction_price_aed"] == "-70,000"
    assert contact.evidence["price_quality"] == "missing_or_invalid"
    assert contact.evidence["location_normalization"]["area"] == "jumeirah village circle"
    assert contact.property_key == "tower2|0012"
    minimal = _candidate_from_row(
        ("Private Person", "0501234567"), profile=profile, filename="owners.csv", row_number=3
    )
    assert minimal is not None and minimal.phone_primary and minimal.transaction_price_aed is None
