"""Matching must preserve property scope and support, rather than invent, named owners."""

import pytest

from app.crm.source_audit import SourceAuditPayload
from app.crm.source_matching import is_financial_party, match_source_payload


def source(rows=None, references=None):
    row = dict(
        cleaned_row_number=2,
        original_rows=[2],
        reference_id="ref1",
        recorded_at="2020-01-01",
        amount_aed="1,000,000",
        size_sqm="100",
        project="Project",
        building_name="Tower 1",
        building_number="1",
        unit_number="0101.0",
        land_number="",
        dm_sub_number="",
        property_type="Flat",
        party_role="Buyer",
        contact_name="Named Buyer",
        phone="0501234567",
        country="UAE",
        source_values=[None, None, "Dubai Hills Estate"],
    )
    # Payload numeric fields are already cleaned; alternate formatting is tested
    # by the matcher as well to avoid accidentally using legacy integer values.
    row["amount_aed"] = "1000000.25"
    reference = dict(
        reference_id="ref1",
        source_key=["unit", "Tower 1", "101"],
        disposition="latest_recorded_buyer_candidate",
        review_required=False,
        decision_basis="Reviewed",
        owner_candidate_groups=[[2]],
        previous_nonbank_candidate_rows=[],
    )
    return SourceAuditPayload.model_validate(
        dict(
            schema_version="owner-source-audit/1",
            dataset_id="fixture",
            original_filename="fixture.xlsx",
            source_sha256="a" * 64,
            cleaned_sha256="b" * 64,
            rows=rows or [row],
            references=references or [reference],
        )
    )


def sale(**changes):
    result = dict(
        sale_key="sale1",
        transaction_date="2020-01-01",
        sale_amount_aed=1000000,
        size_sqft=1076.391041671,
        area_name="Dubai Hills Estate",
        area_key="dubaihillsestate",
        building_name="Tower 1",
        building_key="tower1",
        project_name="Project",
        unit_number="101",
        property_type="Apartment",
    )
    return result | changes


def matched(payload=None, sales=None):
    return match_source_payload(
        payload or source(),
        {"sales": sales or [sale()], "aliases": [], "captured_at": "2026-10-27T00:00:00Z"},
    )


def test_unicode_unit_and_rounding_support_acquisition_without_changing_recorded_amount():
    payload = source()
    payload.rows[0].unit_number = "APT ０１０１"
    result = matched(payload)
    assert result["references"]["ref1"]["status"] == "matched"
    assert result["rows"]["2"]["acquisition_sale_keys"] == ["sale1"]
    assert payload.rows[0].amount_aed == "1000000.25"


def test_same_unit_in_other_area_or_numbered_tower_cannot_match():
    result = matched(
        sales=[
            sale(area_name="Palm Jumeirah"),
            sale(sale_key="sale2", building_name="Tower 2", building_key="tower2"),
        ]
    )
    assert result["references"]["ref1"]["status"] == "unmatched"


def test_generic_tower_requires_same_project_even_in_same_community():
    p = source()
    p.rows[0].building_name = "Tower A"
    assert (
        matched(p, [sale(building_name="Tower A", project_name="Other")])["summary"][
            "matched_reference_count"
        ]
        == 0
    )


def test_size_alone_never_links_property_and_wrong_amount_never_supports_acquisition():
    result = matched(sales=[sale(unit_number="102", building_name="Other")])
    assert result["references"]["ref1"]["status"] == "unmatched"
    result = matched(sales=[sale(sale_amount_aed=100000)])
    assert result["references"]["ref1"]["status"] == "matched"
    assert result["rows"]["2"]["acquisition_sale_keys"] == []


@pytest.mark.parametrize("physical_type", ["Land", "Plot", "Villa", "Building"])
def test_flat_never_matches_other_physical_types_even_with_same_signature(physical_type):
    result = matched(sales=[sale(property_type=physical_type)])
    assert result["summary"]["matched_reference_count"] == 0


def test_later_sale_makes_acquired_buyer_former_and_does_not_invent_successor():
    result = matched(sales=[sale(), sale(sale_key="later", transaction_date="2021-01-01")])
    assert result["rows"]["2"]["owner_category"] == "former"
    assert result["rows"]["2"]["later_sale_date"] == "2021-01-01"
    assert result["summary"]["current_association_count"] == 0


def test_reviewed_buyer_before_later_sale_remains_visible_without_inventing_acquisition():
    result = matched(
        sales=[sale(sale_amount_aed=100000), sale(sale_key="later", transaction_date="2021-01-01")]
    )
    row = result["rows"]["2"]
    assert row["owner_category"] == "former"
    assert row["acquisition_sale_keys"] == []
    assert row["later_sale_date"] == "2021-01-01"
    assert row["reason"].startswith("Unverified former owner:")
    assert result["summary"]["current_association_count"] == 0


def test_unverified_former_fallback_does_not_promote_unapproved_bank_context_buyers():
    payload = source()
    payload.references[0].disposition = "possible_mortgage_or_bank_acquisition"
    payload.references[0].owner_candidate_groups = []
    result = matched(payload, [sale(transaction_date="2021-01-01")])
    assert result["rows"]["2"]["owner_category"] is None
    assert result["rows"]["2"]["acquisition_sale_keys"] == []


def test_reacquisition_assigns_one_current_category_to_whole_party_history():
    p = source()
    historic = p.rows[0].model_copy(
        update={
            "cleaned_row_number": 3,
            "original_rows": [3],
            "recorded_at": __import__("datetime").date(2019, 1, 1),
        }
    )
    p.rows.append(historic)
    result = matched(p, [sale(), sale(sale_key="older", transaction_date="2019-01-01")])
    assert (
        result["rows"]["2"]["owner_category"] == result["rows"]["3"]["owner_category"] == "current"
    )
    assert result["summary"]["current_association_count"] == 1


def test_seller_only_and_bank_parties_never_appear_as_owners():
    p = source()
    p.rows[0].contact_name = "Amlak Finance Company"
    assert matched(p)["rows"]["2"]["owner_category"] is None
    p.rows[0].party_role = "Seller"
    p.references[0].owner_candidate_groups = []
    assert matched(p)["rows"]["2"]["owner_category"] is None
    assert not is_financial_party("Bankole Person")


def test_conflicting_villa_identifiers_need_transaction_anchor_even_if_only_one_observed():
    p = source()
    r = p.rows[0]
    r.project, r.building_name, r.building_number, r.unit_number, r.property_type = (
        "Club Villas",
        "101",
        "102",
        "",
        "Building",
    )
    p.references[0].source_key = ["named_villa_or_building", "Club Villas", "101"]
    no_anchor = sale(
        building_name="Club Villas", project_name="", property_type="Villa", sale_amount_aed=999999
    )
    assert matched(p, [no_anchor])["references"]["ref1"]["status"] == "ambiguous"
    anchored = no_anchor | {"sale_amount_aed": 1000000}
    assert matched(p, [anchored])["references"]["ref1"]["status"] == "matched"


def test_explicit_distinct_references_cannot_silently_merge_and_keep_registry_dates():
    p = source()
    p.references.append(
        p.references[0].model_copy(update={"reference_id": "ref2", "owner_candidate_groups": [[3]]})
    )
    p.rows.append(
        p.rows[0].model_copy(
            update={"reference_id": "ref2", "cleaned_row_number": 3, "original_rows": [3]}
        )
    )
    result = matched(p, [sale(), sale(sale_key="later", transaction_date="2021-01-01")])
    assert result["summary"]["matched_property_count"] == 0
    for row in result["rows"].values():
        assert row["status"] == "ambiguous"
        assert row["latest_sale_date"] is None and row["later_sale_date"] is None
        assert row["matched_sale_keys"] == row["acquisition_sale_keys"] == []
        assert row["owner_category"] == "current"


def test_reviewed_extent_remains_excluded_even_when_transaction_signature_matches():
    p = source()
    p.references[0].disposition = "property_extent_requires_review"
    p.references[0].review_required = True
    p.references[0].owner_candidate_groups = []
    result = matched(p)
    assert result["references"]["ref1"]["status"] == "excluded"
    assert result["rows"]["2"]["owner_category"] is None


@pytest.mark.parametrize(
    "source_type,registry_type",
    [
        ("Villa", "Plot"),
        ("Villa", "Shop"),
        ("Shop", "Apartment"),
        ("Shop", "Villa"),
        ("Flat", "Shop"),
    ],
)
def test_explicit_property_families_do_not_cross_even_when_all_other_fields_match(
    source_type, registry_type
):
    p = source()
    p.rows[0].property_type = source_type
    assert (
        matched(p, [sale(property_type=registry_type)])["summary"]["matched_reference_count"] == 0
    )


@pytest.mark.parametrize("later_registry_sale", [False, True])
def test_earlier_workbook_buyer_stays_former_even_when_acquisition_missing_from_registry(
    later_registry_sale,
):
    from datetime import date

    p = source()
    prior = p.rows[0].model_copy(
        update={
            "cleaned_row_number": 3,
            "original_rows": [3],
            "contact_name": "Earlier Buyer",
            "phone": "0507654321",
            "recorded_at": date(2019, 1, 1),
        }
    )
    p.rows.append(prior)
    sales = [sale()]
    if later_registry_sale:
        sales.append(sale(sale_key="later", transaction_date="2021-01-01"))
    result = matched(p, sales)
    assert result["rows"]["3"]["owner_category"] == "former"
    assert result["rows"]["3"]["source_successor_supported"]
    assert result["rows"]["3"]["acquisition_sale_keys"] == []
    assert "source-supported" in result["rows"]["3"]["reason"]


def test_mag_wrong_master_label_recovery_requires_exact_transaction_anchor():
    p = source()
    p.rows[0].project = "MAG Eye Phase 1"
    p.rows[0].building_name = "MAG Eye Townhouses"
    p.rows[0].property_type = "Villa"
    observed = sale(
        building_name="MAG Eye Townhouses",
        building_key="mageyetownhouses",
        project_name="MAG City",
        area_name="Mohammed Bin Rashid City",
        property_type="Villa",
    )
    result = matched(p, [observed])
    assert result["summary"]["matched_reference_count"] == 1
    assert "source master area corrected" in result["references"]["ref1"]["reason"]
    assert (
        matched(p, [observed | {"sale_amount_aed": 999999}])["summary"]["matched_reference_count"]
        == 0
    )
