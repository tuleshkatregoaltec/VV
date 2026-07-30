from datetime import date

from app.crm.import_service import (
    ParsedContact,
    _apply_evidence,
    _dedupe_candidates,
    _heuristic_mapping,
    _normalize_phone,
    _normalize_unit,
    _owner_filter_sql,
    _owner_scope_clause,
    _unique_headers,
)


def _contact(**overrides) -> ParsedContact:
    values = {
        "source_sheet": "Sheet1",
        "source_row_number": 2,
        "contact_name": "Example Owner",
        "phone_primary": "+971501234567",
        "phone_alternate": None,
        "email_primary": "owner@example.com",
        "area_name": "Business Bay",
        "project_name": "Executive Towers",
        "building_name": "Aspect Tower",
        "unit_number": "602",
        "property_type": "Apartment",
        "transaction_date": date(2025, 1, 31),
        "transaction_price_aed": 2_250_000,
        "party_role": "Buyer",
        "procedure_type": "Sale",
        "row_fingerprint": "fingerprint",
    }
    values.update(overrides)
    return ParsedContact(**values)


def test_known_transaction_export_maps_owner_property_and_sale_fields():
    headers = _unique_headers(
        [
            "Regis",
            "ProcedureValue",
            "Master Project",
            "Project",
            "BuildingNameEn",
            "UnitNumber",
            "ProcedurePartyTypeNameEn",
            "NameEn",
            "Mobile",
            "ProcedureNameEn",
        ]
    )

    mapping, family, warnings = _heuristic_mapping(
        headers,
        filename="Business Bay 2024 SVR.xlsx",
        sheet_name="Sheet1",
    )

    assert family == "transaction_party"
    assert mapping["transaction_date"] == "Regis"
    assert mapping["transaction_price_aed"] == "ProcedureValue"
    assert mapping["building_name"] == "BuildingNameEn"
    assert mapping["unit_number"] == "UnitNumber"
    assert mapping["contact_name"] == "NameEn"
    assert not warnings


def test_placeholder_columns_are_pruned_and_elan_uses_compound_villa_identifier():
    headers = _unique_headers(
        [
            "VILLA NUMBER",
            "UNIT NUMBER PROXY",
            "VILLA NUMBER",
            "NAME",
            "PHONE",
            "Column2",
            "Column999",
        ]
    )

    mapping, family, _ = _heuristic_mapping(
        headers,
        filename="Tilal Al Ghaf - ELAN(923).xlsx",
        sheet_name="Sheet1",
    )

    assert [header.key for header in headers] == [
        "VILLA NUMBER",
        "UNIT NUMBER PROXY",
        "VILLA NUMBER__2",
        "NAME",
        "PHONE",
    ]
    assert family == "contact_list"
    assert mapping["unit_number"] == "VILLA NUMBER__2"
    assert _normalize_unit("TAG-ELAN-B359") == "B359"


def test_uae_phone_numbers_are_normalized_without_inventing_short_numbers():
    assert _normalize_phone("050 123 4567") == "+971501234567"
    assert _normalize_phone("971501234567") == "+971501234567"
    assert _normalize_phone("123") is None


def test_exact_latest_sale_date_and_price_verifies_current_owner():
    contact = _contact()
    sales = {
        contact.property_key: [
            {
                "transaction_date": date(2025, 1, 31),
                "sale_amount_aed": 2_250_000,
            }
        ]
    }
    rentals = {
        contact.property_key: {
            "event_key": "lead-1",
            "unit_candidate_key": "candidate-1",
            "lease_end": date(2026, 3, 31),
            "annual_rent_aed": 240_000,
        }
    }

    _apply_evidence(contact, sales=sales, rentals=rentals)

    assert contact.ownership_status == "verified_current_owner"
    assert contact.confidence_score == 98
    assert contact.lead_id == "lead-1"
    assert contact.unit_candidate_key == "candidate-1"


def test_later_sale_marks_uploaded_buyer_as_former_owner():
    contact = _contact(
        transaction_date=date(2018, 9, 4),
        transaction_price_aed=1_300_000,
    )
    sales = {
        contact.property_key: [
            {
                "transaction_date": date(2018, 9, 4),
                "sale_amount_aed": 1_300_000,
            },
            {
                "transaction_date": date(2025, 1, 31),
                "sale_amount_aed": 2_250_000,
            },
        ]
    }

    _apply_evidence(contact, sales=sales, rentals={})

    assert contact.ownership_status == "former_owner"
    assert contact.later_sale_date == date(2025, 1, 31)
    assert "later sale" in contact.match_reason.lower()


def test_contact_only_row_remains_unverified_even_with_exact_unit():
    contact = _contact(
        transaction_date=None,
        transaction_price_aed=None,
        party_role="",
        procedure_type="",
    )
    sales = {
        contact.property_key: [
            {
                "transaction_date": date(2025, 1, 31),
                "sale_amount_aed": 2_250_000,
            }
        ]
    }

    _apply_evidence(contact, sales=sales, rentals={})

    assert contact.ownership_status == "unit_linked_unverified"
    assert "does not provide an acquisition date" in contact.match_reason


def test_duplicate_owner_property_rows_collapse_to_strongest_evidence():
    verified_one = _contact(
        source_row_number=2157,
        transaction_date=date(2024, 2, 20),
        ownership_status="verified_current_owner",
        confidence_score=98,
    )
    verified_two = _contact(
        source_row_number=2184,
        transaction_date=date(2024, 2, 20),
        ownership_status="verified_current_owner",
        confidence_score=98,
    )
    probable_one = _contact(
        source_row_number=1739,
        transaction_date=date(2024, 2, 26),
        ownership_status="probable_current_owner",
        confidence_score=72,
    )
    probable_two = _contact(
        source_row_number=1765,
        transaction_date=date(2024, 2, 26),
        ownership_status="probable_current_owner",
        confidence_score=72,
    )

    unique, collapsed = _dedupe_candidates([verified_one, verified_two, probable_one, probable_two])

    assert collapsed == 3
    assert len(unique) == 1
    assert unique[0].ownership_status == "verified_current_owner"
    assert unique[0].confidence_score == 98
    assert unique[0].evidence["duplicate_count"] == 4
    assert unique[0].evidence["source_rows"] == [
        "Sheet1:1739",
        "Sheet1:1765",
        "Sheet1:2157",
        "Sheet1:2184",
    ]


def test_same_contact_across_two_properties_remains_two_property_claims():
    first = _contact(unit_number="602", row_fingerprint="first")
    second = _contact(unit_number="603", row_fingerprint="second")

    unique, collapsed = _dedupe_candidates([first, second])

    assert collapsed == 0
    assert len(unique) == 2


def test_prior_owners_are_separated_from_current_owner_registry():
    prior_clause = _owner_scope_clause("prior_owners")
    registry_clause = _owner_scope_clause("registry")

    assert "ownership_status = 'former_owner'" in prior_clause
    assert "ownership_status <> 'former_owner'" in registry_clause
    assert "verified_current_owner" in registry_clause


def test_owner_filters_cover_lease_rent_and_value_ranges():
    clause, parameters = _owner_filter_sql(
        scope="rental_ready",
        status=None,
        search=None,
        lease_window="expiring_60",
        min_rent_aed=100_000,
        max_rent_aed=250_000,
        min_value_aed=1_500_000,
        max_value_aed=4_000_000,
    )

    assert "lease_end" in clause
    assert "annual_rent_aed" in clause
    assert "latest_sale_price_aed" in clause
    assert parameters == {
        "lease_lower_days": 30,
        "lease_upper_days": 60,
        "owner_min_rent": 100_000,
        "owner_max_rent": 250_000,
        "owner_min_value": 1_500_000,
        "owner_max_value": 4_000_000,
    }
