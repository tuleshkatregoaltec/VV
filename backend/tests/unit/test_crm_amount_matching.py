"""Amount/location identity is evidence, never a shortcut to an owner assertion."""

from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from app.crm import owner_queries
from app.crm.identity import ParsedContact
from app.crm.ownership import _apply_evidence, _recover_property_identity_from_transaction
from app.crm.transaction_matching import AmountFirstIndex, amounts_match, sizes_match


@pytest.fixture(autouse=True)
def no_live_source_catalog(monkeypatch):
    monkeypatch.setattr(owner_queries, "fetch_registry_places", AsyncMock(return_value=[]))


def source(**changes):
    return {
        "amount_aed": "1,000,000.50",
        "unit_number": "101",
        "building_name": "Alpha Tower 1",
        "project_name": "Alpha",
        "area_name": "Business Bay",
        "property_type": "Apartment",
        "transaction_date": "2024-01-01",
        "event_family": "sale",
        **changes,
    }


def event(**changes):
    return {
        "sale_key": "sale-1",
        "sale_amount_aed": "1000000.50",
        "unit_number": "101",
        "building_name": "Alpha Tower 1",
        "project_name": "Alpha",
        "area_name": "Business Bay",
        "property_type": "Apartment",
        "transaction_date": date(2024, 1, 1),
        **changes,
    }


def contact(**changes):
    values = dict(
        source_sheet="Owners",
        source_row_number=2,
        contact_name="Example",
        phone_primary=None,
        phone_alternate=None,
        email_primary=None,
        area_name="Business Bay",
        project_name="Alpha",
        building_name="Alpha Tower 1",
        unit_number="101",
        property_type="Apartment",
        transaction_date=date(2024, 1, 1),
        transaction_price_aed=1_000_001,
        party_role="Buyer",
        procedure_type="Sale",
        row_fingerprint="example",
        evidence={"source_fields": {"transaction_price_aed": "1,000,000.50"}},
    )
    return ParsedContact(**(values | changes))


@pytest.mark.parametrize(
    "delta,match",
    [("0.50", True), ("2", True), ("2.0000000001", False), ("-2", True), ("-2.0000000001", False)],
)
def test_money_tolerance_uses_decimal_before_any_rounding(delta, match):
    observed = Decimal("1000000.50") + Decimal(delta)
    result = AmountFirstIndex([event(sale_amount_aed=observed)]).match(source())
    assert (result.status == "matched") is match
    assert amounts_match("1,000,000.50", observed) is match


def test_percentage_price_similarity_cannot_prove_same_transaction():
    assert not amounts_match(1_000_000, 1_000_003)
    assert not amounts_match(None, 1_000_000)


@pytest.mark.parametrize("observed,match", [("1050", True), ("1050.0001", False), ("10200", False)])
def test_size_is_supporting_with_absolute_floor(observed, match):
    assert sizes_match("1000", observed) is match
    assert sizes_match("10000", "10200")


def test_identical_price_different_flat_is_never_overwritten_by_location():
    result = AmountFirstIndex([event(unit_number="102")]).match(source())
    assert result.status == "unmatched" and result.property_identity is None


def test_price_collision_is_selected_by_property_location():
    result = AmountFirstIndex(
        [event(), event(sale_key="other", building_name="Beta Tower 1", unit_number="101")]
    ).match(source())
    assert result.status == "matched" and result.event["sale_key"] == "sale-1"
    assert result.candidate_event_count == 2 and result.exact_transaction


@pytest.mark.parametrize("building", ["Alpha Tower 2", "Beta House"])
def test_area_and_project_cannot_erase_an_explicit_building_conflict(building):
    result = AmountFirstIndex([event(building_name=building)]).match(source())
    assert result.status == "unmatched"


def test_size_and_date_cannot_rescue_explicit_flat_conflict():
    result = AmountFirstIndex([event(unit_number="102", size_sqft=1000)]).match(
        source(size_sqft=1000)
    )
    assert result.status == "unmatched"


def test_duplicate_observations_are_one_event_but_independent_registrations_remain_ambiguous():
    duplicate = AmountFirstIndex([event(), event()]).match(source())
    assert duplicate.exact_transaction and duplicate.candidate_event_count == 1
    competing = AmountFirstIndex([event(), event(sale_key="sale-2")]).match(source())
    assert competing.status == "matched" and competing.property_count == 1
    assert competing.event is None and not competing.exact_transaction
    assert competing.flags == ("ambiguous_transaction",)


def test_matching_date_does_not_force_a_tie_between_properties():
    result = AmountFirstIndex(
        [event(), event(sale_key="sale-2", unit_number="102", transaction_date=date(2025, 1, 1))]
    ).match(source(unit_number=""))
    assert result.status == "ambiguous" and result.event is None


def test_date_only_conflict_links_identity_without_exact_transaction():
    result = AmountFirstIndex([event(transaction_date=date(2026, 1, 1))]).match(source())
    assert result.status == "matched" and result.property_identity
    assert result.flags == ("date_conflict",) and not result.exact_transaction
    assert result.evidence["date_used_as_filter"] is False


def test_villa_number_requires_its_named_namespace():
    villa = event(
        unit_number="DE Sidra 2-V-117",
        building_name="Sidra 2",
        project_name="Sidra Villas",
        property_type="Villa",
    )
    row = source(
        unit_number="",
        building_number="117",
        building_name="",
        project_name="Sidra 2",
        property_type="Villa",
    )
    assert AmountFirstIndex([villa]).match(row).status == "matched"
    other = villa | {"unit_number": "DE Maple 2-V-117"}
    assert AmountFirstIndex([other]).match(row).status == "unmatched"


def test_full_plot_code_cannot_match_a_numeric_suffix_or_villa():
    row = source(unit_number="", plot_number="Fairways_R.023", property_type="Land")
    assert (
        AmountFirstIndex([event(unit_number="23", property_type="Land")]).match(row).status
        == "unmatched"
    )
    assert (
        AmountFirstIndex([event(unit_number="Fairways-023", property_type="Land")])
        .match(row)
        .status
        == "unmatched"
    )
    assert (
        AmountFirstIndex([event(unit_number="Fairways_R.023", property_type="Land")])
        .match(row)
        .status
        == "matched"
    )
    assert (
        AmountFirstIndex([event(unit_number="23", property_type="Villa")]).match(row).status
        == "unmatched"
    )


def test_land_without_a_villa_identifier_does_not_auto_merge_to_villa():
    assert (
        AmountFirstIndex([event(property_type="Villa")]).match(source(property_type="Land")).status
        == "unmatched"
    )


def test_sale_and_rental_consideration_never_substitute_for_each_other():
    rental = event(
        sale_key="",
        event_key="rent-1",
        event_family="rental",
        sale_amount_aed=0,
        contract_amount_aed="1000000.50",
        annual_rent_aed="500000.25",
    )
    index = AmountFirstIndex([rental])
    assert index.match(source()).status == "unmatched"
    match = index.match(source(event_family="rental", amount_basis="contract_amount_aed"))
    assert match.status == "matched" and "rental_review_required" in match.flags
    assert not match.exact_transaction
    assert (
        index.match(
            source(
                event_family="rental", amount_aed="500000.25", amount_basis="contract_amount_aed"
            )
        ).status
        == "unmatched"
    )
    assert (
        AmountFirstIndex([rental | {"purchase_price_aed": "750000"}])
        .match(source(amount_aed="750000", event_family="unknown"))
        .status
        == "unmatched"
    )


def test_annualized_only_and_unknown_family_remain_review_evidence():
    rental = event(event_family="rental", annual_rent_aed="1000000.50", sale_amount_aed=0)
    result = AmountFirstIndex([rental]).match(source(event_family="unknown"))
    assert result.status == "matched" and not result.exact_transaction
    assert {"annualized_amount_basis", "unknown_source_event_family"} <= set(result.flags)


async def test_import_lookup_preserves_raw_fraction_and_has_no_date_parameter(monkeypatch):
    monkeypatch.setattr(
        owner_queries, "fetch_property_identity_candidates", AsyncMock(return_value=[])
    )
    row = contact()
    query = AsyncMock(return_value=[event(sale_amount_aed="1000002.75")])
    monkeypatch.setattr(owner_queries, "fetch_transaction_signatures", query)
    await _recover_property_identity_from_transaction([row])
    assert query.await_args.args[0] == {"prices": ["1000000.50"]}
    assert row.evidence["amount_first_match"]["status"] == "unmatched"
    assert row.unit_number == "101"


async def test_query_fetches_complete_sales_and_contract_bands_without_limit(monkeypatch):
    query = AsyncMock(return_value=[])
    monkeypatch.setattr(owner_queries, "query", query)
    await owner_queries.fetch_transaction_signatures({"prices": ["100.50"]})
    sql, parameters = query.await_args.args
    assert parameters == {"amount_buckets": [98, 99, 100, 101, 102]}
    assert "dxbi_sales_unit_events FINAL" in sql and "dxbi_rental_events FINAL" in sql
    assert "transaction_date IN" not in sql and "LIMIT" not in sql


def test_later_sale_prevents_current_owner_despite_exact_acquisition():
    row = contact()
    earlier = event(sale_amount_aed="1000000.50")
    later = event(sale_key="later", sale_amount_aed="2000000", transaction_date=date(2025, 1, 1))
    _apply_evidence(row, sales={row.property_key: [earlier, later]}, rentals={})
    assert row.ownership_status == "former_owner" and row.later_sale_date == date(2025, 1, 1)


def test_exact_date_resolves_same_property_repeat_price_years_apart():
    row = contact()
    _apply_evidence(
        row,
        sales={
            row.property_key: [event(sale_key="older", transaction_date=date(2020, 1, 1)), event()]
        },
        rentals={},
    )
    assert row.ownership_status == "verified_current_owner"
    assert row.evidence["date_event_resolution"] == "unique_exact_date_without_nearby_competitor"


@pytest.mark.parametrize("procedure", ["Rent", "Mortgage Registration"])
def test_non_sale_relationship_never_establishes_current_owner(procedure):
    row = contact(procedure_type=procedure)
    _apply_evidence(row, sales={row.property_key: [event()]}, rentals={})
    assert row.ownership_status == "unit_linked_unverified"


async def test_rematching_requeries_and_replaces_previous_match_evidence(monkeypatch):
    monkeypatch.setattr(
        owner_queries, "fetch_property_identity_candidates", AsyncMock(return_value=[])
    )
    row = contact()
    query = AsyncMock(side_effect=[[event()], []])
    monkeypatch.setattr(owner_queries, "fetch_transaction_signatures", query)
    await _recover_property_identity_from_transaction([row])
    assert "property_identity_resolution" in row.evidence
    await _recover_property_identity_from_transaction([row])
    assert query.await_count == 2 and "property_identity_resolution" not in row.evidence
    assert row.evidence["amount_first_match"]["status"] == "unmatched"


def test_land_villa_with_explicit_identifier_stays_provisional():
    result = AmountFirstIndex([event(property_type="Villa")]).match(
        source(property_type="Land", building_number="101")
    )
    assert result.status == "matched" and not result.exact_transaction
    assert "type_mismatch_review_required" in result.flags
    row = contact(
        property_type="Land", evidence={"amount_first_match": {"flags": list(result.flags)}}
    )
    _apply_evidence(row, sales={row.property_key: [event(property_type="Villa")]}, rentals={})
    assert row.ownership_status == "unit_linked_unverified"


def test_repeated_building_name_cannot_erase_incompatible_geography():
    result = AmountFirstIndex([event(area_name="Downtown Dubai")]).match(source())
    assert result.status == "matched" and not result.exact_transaction
    assert "geography_review_required" in result.flags
    row = contact(evidence={"amount_first_match": {"flags": list(result.flags)}})
    _apply_evidence(row, sales={row.property_key: [event()]}, rentals={})
    assert row.ownership_status == "unit_linked_unverified"


def test_conflicting_explicit_villa_unit_and_building_number_never_select_one():
    villa = event(unit_number="DE-Sidra2-V-118", building_name="Sidra 2", property_type="Villa")
    result = AmountFirstIndex([villa]).match(
        source(
            unit_number="DE-Sidra2-V-117",
            building_number="118",
            building_name="Sidra 2",
            project_name="Sidra 2",
            property_type="Villa",
        )
    )
    assert result.status == "unmatched"


def test_known_size_can_support_a_unique_transaction_but_missing_size_cannot_exclude_a_competitor():
    first = event(size_sqft=1000)
    second = event(sale_key="second", size_sqft=1200)
    result = AmountFirstIndex([first, second]).match(source(size_sqft=1000))
    assert result.exact_transaction and result.event["sale_key"] == "sale-1"
    result = AmountFirstIndex([first, second | {"size_sqft": 0}]).match(source(size_sqft=1000))
    assert result.event is None and "ambiguous_transaction" in result.flags


async def test_blank_procedure_property_recovery_is_provisional_and_cannot_infer_owner(monkeypatch):
    row = contact(procedure_type="", evidence={"event_family": "contact_snapshot"})
    monkeypatch.setattr(
        owner_queries, "fetch_transaction_signatures", AsyncMock(return_value=[event()])
    )
    await _recover_property_identity_from_transaction([row])
    assert row.evidence["amount_first_match"]["status"] == "matched"
    assert "unknown_source_event_family" in row.evidence["amount_first_match"]["flags"]
    _apply_evidence(row, sales={row.property_key: [event()]}, rentals={})
    assert row.ownership_status == "unit_linked_unverified"


def test_property_only_result_retains_every_material_review_flag():
    rows = [
        event(property_type="Villa", area_name="Downtown Dubai"),
        event(sale_key="other", property_type="Villa", area_name="Downtown Dubai"),
    ]
    result = AmountFirstIndex(rows).match(
        source(event_family="unknown", property_type="Land", building_number="101")
    )
    assert result.event is None and result.status == "matched"
    assert {
        "ambiguous_transaction",
        "unknown_source_event_family",
        "type_mismatch_review_required",
        "geography_review_required",
    } <= set(result.flags)


@pytest.mark.parametrize("source_type, observed_type", [("Shop", "Apartment"), ("Office", "Shop")])
def test_shared_flat_number_namespace_does_not_equate_explicit_property_uses(
    source_type, observed_type
):
    result = AmountFirstIndex([event(property_type=observed_type)]).match(
        source(property_type=source_type)
    )
    assert result.status == "matched" and not result.exact_transaction
    assert "type_mismatch_review_required" in result.flags
    row = contact(property_type=source_type)
    _apply_evidence(row, sales={row.property_key: [event(property_type=observed_type)]}, rentals={})
    assert row.ownership_status == "conflicting_claim"


@pytest.mark.parametrize(
    "other_date, exact",
    [("2020-01-01", True), ("2024-01-01", False), ("2024-01-15", False), (None, False)],
)
def test_exact_date_is_event_support_only_when_no_nearby_or_undated_competitor(other_date, exact):
    index = AmountFirstIndex([event(), event(sale_key="other", transaction_date=other_date)])
    result = index.match(source())
    assert result.status == "matched" and result.exact_transaction is exact
    if exact:
        assert result.event["sale_key"] == "sale-1"
        assert (
            result.evidence["date_event_resolution"]
            == "unique_exact_date_without_nearby_competitor"
        )
    else:
        assert result.event is None and "ambiguous_transaction" in result.flags
    missing_date = index.match(source(transaction_date=None))
    assert missing_date.event is None and not missing_date.exact_transaction


def test_registry_catalog_recovers_only_blank_labels_and_never_changes_unit():
    from app.crm.registry_locations import RegistryLocationIndex, normalize_registry_locations

    places = [
        dict(
            location_id=1,
            path_key="alpharesidencebusinessbay",
            building_key="alpharesidence",
            area_key="businessbay",
            match_rank=1,
            building_label="Alpha Residence",
            project_label="Alpha",
            area_label="Business Bay",
        )
    ]
    raw = event(
        building_name="",
        project_name="",
        area_name="",
        location_name="Alpha Residences Business Bay",
        unit_number="Full-Plot_023",
    )
    fixed = normalize_registry_locations(raw, RegistryLocationIndex(places))
    assert fixed["building_name"] == "Alpha Residence" and fixed["project_name"] == "Alpha"
    assert fixed["area_name"] == "Business Bay" and fixed["unit_number"] == "Full-Plot_023"
    assert (
        raw["building_name"] == ""
        and fixed["registry_location_resolution"]["raw_fields"]["building_name"] == ""
    )
    explicit = normalize_registry_locations(raw | {"building_name": "Explicit Other"}, places)
    assert explicit["building_name"] == "Explicit Other"
    collision = places + [places[0] | {"location_id": 2, "building_label": "Other"}]
    assert normalize_registry_locations(raw, collision)["building_name"] == ""


async def test_import_match_reuses_parser_embedded_villa_code_without_inventing_tower_conflict(
    monkeypatch,
):
    row = contact(
        building_name="Sidra 2",
        project_name="Sidra 2",
        unit_number="DE Sidra 2-V-117",
        property_type="Villa",
        evidence={
            "source_fields": {"building_name": "DE Sidra 2-V-117", "project_name": "Sidra 2"},
            "address_recovery": {
                "method": "embedded_villa_identifier",
                "resolved_building_name": "Sidra 2",
                "resolved_unit_number": "DE Sidra 2-V-117",
            },
        },
    )
    observed = event(
        building_name="Sidra 2",
        project_name="Sidra Villas",
        unit_number="DE Sidra 2-V-117",
        property_type="Villa",
    )
    monkeypatch.setattr(
        owner_queries, "fetch_transaction_signatures", AsyncMock(return_value=[observed])
    )
    await _recover_property_identity_from_transaction([row])
    assert row.evidence["amount_first_match"]["status"] == "matched"


def test_missing_amount_can_link_scoped_full_unit_identity_but_not_transaction():
    from app.crm.transaction_matching import match_property

    result = match_property(
        source(amount_aed=None), [event(), event(sale_key="other", transaction_date="2020-01-01")]
    )
    assert result.status == "matched" and result.event is None and not result.exact_transaction
    assert {"identity_only", "missing_positive_amount"} <= set(result.flags)
    assert result.evidence["identifier_supported"] is True
    assert (
        match_property(source(amount_aed=None), [event(building_name="Beta House")]).status
        == "unmatched"
    )
    assert (
        match_property(source(amount_aed=None), [event(area_name="Downtown Dubai")]).status
        == "unmatched"
    )
    assert (
        match_property(
            source(unit_number="", building_number="101", amount_aed=None), [event()]
        ).status
        == "unmatched"
    )


def test_property_fallback_never_collapses_full_plot_code_or_scoped_number():
    from app.crm.transaction_matching import match_property

    row = source(
        unit_number="", plot_number="Fairways_R.023", property_type="Land", amount_aed=None
    )
    assert (
        match_property(row, [event(unit_number="23", property_type="Land")]).status == "unmatched"
    )
    assert (
        match_property(row, [event(unit_number="Fairways_R.023", property_type="Land")]).status
        == "matched"
    )


def test_ambiguous_transaction_retains_size_conflict_only_when_all_sizes_contradict():
    rows = [event(size_sqft=1200), event(sale_key="other", size_sqft=1300)]
    result = AmountFirstIndex(rows).match(source(size_sqft=1000))
    assert result.event is None and "size_conflict" in result.flags
    result = AmountFirstIndex([rows[0], rows[1] | {"size_sqft": 0}]).match(source(size_sqft=1000))
    assert result.event is None and "size_conflict" not in result.flags


async def test_actual_import_missing_amount_uses_identity_only_lookup_without_owner(monkeypatch):
    row = contact(transaction_price_aed=None, evidence={})
    monkeypatch.setattr(
        owner_queries, "fetch_property_identity_candidates", AsyncMock(return_value=[event()])
    )
    result = await _recover_property_identity_from_transaction([row])
    assert (
        result["property_only"] == 1
        and row.evidence["property_identity_match"]["status"] == "matched"
    )
    assert row.evidence["property_identity_resolution"]["exact_transaction"] is False
    _apply_evidence(row, sales={row.property_key: [event()]}, rentals={})
    assert row.ownership_status not in {"verified_current_owner", "probable_current_owner"}


def test_filename_context_requires_unique_exact_catalog_building_and_retains_phase():
    from app.crm.registry_locations import RegistryLocationIndex, infer_source_file_context

    place = dict(
        location_id=1,
        path_key="bellarose",
        building_key="bellarose",
        area_key="dubaisciencepark",
        match_rank=1,
        building_label="Bella Rose",
        project_label="Bella Rose",
        area_label="Dubai Science Park",
    )
    catalog = RegistryLocationIndex([place])
    original = dict(
        building_name="",
        project_name="",
        area_name="",
        source_filename="Bella Rose owners updated 28.10.2026.xlsx",
    )
    fixed = infer_source_file_context(original, catalog)
    assert (
        fixed["building_name"] == "Bella Rose"
        and fixed["inferred_file_context"]["location_id"] == 1
    )
    assert original["building_name"] == ""
    assert "inferred_file_context" not in infer_source_file_context(
        original | {"source_filename": "Bella Rose 2.xlsx"}, catalog
    )
    assert "inferred_file_context" not in infer_source_file_context(
        original | {"building_name": "Explicit"}, catalog
    )
    repeated = RegistryLocationIndex([place, place | {"location_id": 2, "area_label": "Other"}])
    assert "inferred_file_context" not in infer_source_file_context(original, repeated)


def test_project_filename_context_preserves_two_towers_and_strips_month_year_only():
    from app.crm.registry_locations import RegistryLocationIndex, infer_source_file_context

    places = [
        dict(
            location_id=1,
            match_rank=1,
            building_label="One Za’Abeel Tower",
            project_label="One Za’Abeel",
            area_label="Trade Centre",
        ),
        dict(
            location_id=2,
            match_rank=1,
            building_label="One Za’Abeel The Residences",
            project_label="One Za’Abeel",
            area_label="Trade Centre",
        ),
    ]
    result = infer_source_file_context(
        dict(source_filename="One Zabeel_March2025.xlsx", building_name="", project_name=""),
        RegistryLocationIndex(places),
    )
    assert result["project_name"] == "One Za’Abeel" and result["building_name"] == ""
    assert result["inferred_file_context"]["method"] == "filename_exact_dxbi_project"
    from app.crm.transaction_matching import match_property

    rows = [
        event(
            building_name=place["building_label"],
            project_name=place["project_label"],
            area_name=place["area_label"],
        )
        for place in places
    ]
    assert match_property(result | {"unit_number": "101"}, rows).status == "ambiguous"


async def test_rematch_drops_unreconfirmed_filename_context_instead_of_reusing_registry_labels(
    monkeypatch,
):
    row = contact(
        evidence={
            "source_fields": {"building_name": "", "project_name": "", "unit_number": "101"},
            "source_filename": "Bella Rose.xlsx",
            "inferred_file_context": {
                "raw_fields": {"building_name": "", "project_name": "", "area_name": ""},
                "resolved_fields": {
                    "building_name": "Alpha Tower 1",
                    "project_name": "Alpha",
                    "area_name": "Business Bay",
                },
            },
        }
    )
    monkeypatch.setattr(owner_queries, "fetch_registry_places", AsyncMock(return_value=[]))
    monkeypatch.setattr(
        owner_queries, "fetch_transaction_signatures", AsyncMock(return_value=[event()])
    )
    monkeypatch.setattr(
        owner_queries, "fetch_property_identity_candidates", AsyncMock(return_value=[event()])
    )
    await _recover_property_identity_from_transaction([row])
    assert "inferred_file_context" not in row.evidence
    assert "property_identity_resolution" not in row.evidence


def scoped_places():
    return [
        dict(
            location_id=31743,
            area_key="albarshaasouth2",
            area_label="Dubiotech",
            building_key="bellarose",
            building_label="",
            project_label="Bella Rose",
            match_rank=1,
            path_key="bellarosealbarshaasouthsecond",
        ),
        dict(
            location_id=31680,
            area_key="jabalali1",
            area_label="Al Furjan",
            building_key="alfurjan",
            building_label="",
            project_label="",
            match_rank=2,
            path_key="alfurjanjabalalifirst",
        ),
        dict(
            location_id=34059,
            area_key="alfurjan",
            area_label="Al Furjan",
            building_key="azizistarhotelapartment",
            building_label="",
            project_label="Azizi Star Hotel Apartments",
            match_rank=1,
            path_key="azizistarhotelapartmentalfurjan",
        ),
    ]


def test_live_bella_rose_place_aligns_legal_area_suffix_only_inside_named_project():
    from app.crm.registry_locations import RegistryLocationIndex, normalize_registry_locations
    from app.crm.transaction_matching import match_property

    catalog = RegistryLocationIndex(scoped_places())
    raw = dict(
        unit_number="1001",
        building_name="Bella Rose",
        project_name="Bella Rose",
        area_name="Al Barshaa South 2",
    )
    aligned = normalize_registry_locations(raw, catalog)
    assert aligned["area_name"] == "Dubiotech" and raw["area_name"] == "Al Barshaa South 2"
    proof = aligned["registry_location_resolution"]
    assert proof["raw_fields"]["area_name"] == "Al Barshaa South 2"
    assert proof["area_alignment"]["provider_place_evidence_ids"] == [31743]
    inverse = normalize_registry_locations(raw | {"area_name": "Al Barshaa South Second"}, catalog)
    assert inverse["area_name"] == aligned["area_name"]
    result = match_property(aligned, [inverse])
    assert result.status == "matched" and not result.exact_transaction
    assert (
        normalize_registry_locations(raw | {"area_name": "Unknown Legal Area"}, catalog)[
            "area_name"
        ]
        == "Unknown Legal Area"
    )
    assert (
        normalize_registry_locations(
            raw | {"project_name": "Other", "building_name": "Other"}, catalog
        )["area_name"]
        == "Al Barshaa South 2"
    )


def test_azizi_area_equivalence_requires_specific_place_and_provider_community_bridge():
    from app.crm.registry_locations import RegistryLocationIndex, normalize_registry_locations

    catalog = RegistryLocationIndex(scoped_places())
    legal = dict(
        unit_number="101",
        building_name="AZIZI STAR",
        project_name="Azizi Star Hotel Apartments",
        area_name="Jabal Ali First",
    )
    aligned = normalize_registry_locations(legal, catalog)
    assert aligned["area_name"] == "Al Furjan" and legal["area_name"] == "Jabal Ali First"
    from app.crm.transaction_matching import match_property

    canonical_event = legal | {"area_name": "Al Furjan"}
    assert (
        match_property(aligned, [normalize_registry_locations(canonical_event, catalog)]).status
        == "matched"
    )
    assert (
        match_property(canonical_event, [normalize_registry_locations(legal, catalog)]).status
        == "matched"
    )
    assert aligned["registry_location_resolution"]["area_alignment"][
        "provider_place_evidence_ids"
    ] == [31680, 34059]
    assert (
        normalize_registry_locations(
            legal | {"building_name": "Building 1", "project_name": "Unknown Project"}, catalog
        )["area_name"]
        == "Jabal Ali First"
    )
    assert (
        normalize_registry_locations(legal | {"area_name": "Jabal Ali Second"}, catalog)[
            "area_name"
        ]
        == "Jabal Ali Second"
    )
    assert (
        normalize_registry_locations(legal, RegistryLocationIndex(scoped_places()[::2]))[
            "area_name"
        ]
        == "Jabal Ali First"
    )


def test_provider_community_bridge_is_not_a_global_area_alias():
    from app.crm.registry_locations import RegistryLocationIndex, normalize_registry_locations

    row = dict(
        building_name="", project_name="Al Furjan", area_name="Jabal Ali First", unit_number="101"
    )
    assert (
        normalize_registry_locations(row, RegistryLocationIndex(scoped_places()))["area_name"]
        == "Jabal Ali First"
    )


def test_zero_plot_placeholder_cannot_mask_conflicting_full_explicit_unit():
    row = source(property_type="Land", plot_number="0", unit_number="Fairways_R.023")
    assert (
        AmountFirstIndex([event(property_type="Land", unit_number="Other_Plot_023")])
        .match(row)
        .status
        == "unmatched"
    )
    matched = AmountFirstIndex([event(property_type="Land", unit_number="Fairways_R.023")]).match(
        row
    )
    assert matched.status == "matched" and matched.evidence["identifier_supported"]


def test_shared_scope_prefilter_matches_property_helper_alias_and_number_rules():
    from app.crm.transaction_matching import property_scope, property_scope_matches

    assert property_scope(source()) == ("Alpha Tower 1", "Alpha")
    assert property_scope_matches("Jumeirah Gate Tower 1", "The Address JBR 1")
    assert not property_scope_matches("Alpha Tower 1", "Alpha Tower 2")


async def test_actual_import_aligns_source_legal_area_from_same_named_catalog_scope(monkeypatch):
    row = contact(
        building_name="AZIZI STAR",
        project_name="Azizi Star Hotel Apartments",
        area_name="Jabal Ali First",
        evidence={
            "source_fields": {
                "building_name": "AZIZI STAR",
                "project_name": "Azizi Star Hotel Apartments",
                "area_name": "Jabal Ali First",
            }
        },
    )
    monkeypatch.setattr(
        owner_queries, "fetch_registry_places", AsyncMock(return_value=scoped_places())
    )
    observed = event(
        building_name="AZIZI STAR",
        project_name="Azizi Star Hotel Apartments",
        area_name="Al Furjan",
    )
    monkeypatch.setattr(
        owner_queries, "fetch_transaction_signatures", AsyncMock(return_value=[observed])
    )
    await _recover_property_identity_from_transaction([row])
    assert row.evidence["amount_first_match"]["status"] == "matched"
    assert (
        row.evidence["source_registry_location_resolution"]["raw_fields"]["area_name"]
        == "Jabal Ali First"
    )
    assert row.evidence["source_fields"]["area_name"] == "Jabal Ali First"


def test_qualified_project_uses_exact_catalog_area_and_preserves_other_phases():
    from app.crm.registry_locations import RegistryLocationIndex, normalize_registry_locations

    places = [
        dict(
            location_id=47215,
            area_key="damachills2",
            area_label="Damac Hills 2",
            building_key="camelia",
            building_label="",
            project_label="Camelia",
            match_rank=1,
        ),
        dict(
            location_id=32955,
            area_key="wadialsafa5",
            area_label="Arabian Ranches 3",
            building_key="sun",
            building_label="",
            project_label="Sun",
            match_rank=1,
        ),
    ]
    catalog = RegistryLocationIndex(places)
    raw = dict(
        building_name="",
        project_name="Damac Hills (2) - Camelia",
        area_name="Damac Hills 2",
        unit_number="117",
    )
    fixed = normalize_registry_locations(raw, catalog)
    assert fixed["project_name"] == "Camelia" and fixed["building_name"] == ""
    assert (
        fixed["registry_location_resolution"]["raw_fields"]["project_name"] == raw["project_name"]
    )
    sun = normalize_registry_locations(
        raw | {"project_name": "Arabian Ranches III - Sun", "area_name": "Arabian Ranches III"},
        catalog,
    )
    assert sun["project_name"] == "Sun"
    assert (
        normalize_registry_locations(raw | {"project_name": "Damac Hills - Camelia"}, catalog)[
            "project_name"
        ]
        == "Damac Hills - Camelia"
    )
    assert (
        normalize_registry_locations(raw | {"project_name": "Damac Hills (1) - Camelia"}, catalog)[
            "project_name"
        ]
        == "Damac Hills (1) - Camelia"
    )


def test_generic_tower_unit_cannot_cross_projects_or_collapse_property_identity():
    from app.crm.transaction_matching import match_property, property_identity

    row = source(building_name="Tower 1", project_name="Project Alpha")
    wrong = event(building_name="Tower 1", project_name="Project Beta")
    assert AmountFirstIndex([wrong]).match(row).status == "unmatched"
    assert match_property(row, [wrong]).status == "unmatched"
    right = wrong | {"project_name": "Project Alpha"}
    assert property_identity(right) != property_identity(wrong)
    assert AmountFirstIndex([right, wrong]).match(row).event["project_name"] == "Project Alpha"
    broad = AmountFirstIndex([right]).match(row | {"project_name": "Business Bay"})
    assert broad.status == "matched" and not broad.exact_transaction
    assert "generic_building_project_review" in broad.flags
    wrong_area = right | {"area_name": "Downtown Dubai"}
    reviewed = AmountFirstIndex([wrong_area]).match(row)
    assert reviewed.status == "matched" and not reviewed.exact_transaction
    assert "geography_review_required" in reviewed.flags
    assert match_property(row, [wrong_area]).status == "unmatched"


@pytest.mark.parametrize(
    "unit, source_type",
    [
        ("Flat 901", "Apartment"),
        ("901", "Apartment"),
        ("17", "Land"),
        ("1", "Land"),
        ("1", "Residential"),
        ("1", "Commercial"),
    ],
)
def test_parent_plot_never_replaces_a_different_explicit_unit(unit, source_type):
    from app.crm.transaction_matching import match_property

    row = source(unit_number=unit, plot_pre_reg_number="AFRA040", property_type=source_type)
    observed = event(unit_number="AFRA040", property_type="Plot")
    amount = AmountFirstIndex([observed]).match(row)
    identity = match_property(row, [observed])
    assert amount.status == identity.status == "unmatched"
    assert amount.event is None and amount.property_identity is None
    assert identity.event is None and identity.property_identity is None


def test_same_full_explicit_unit_and_plot_reference_remains_valid():
    from app.crm.transaction_matching import match_property

    row = source(unit_number="AFRA040", plot_pre_reg_number="AFRA040", property_type="Land")
    observed = event(unit_number="AFRA040", property_type="Plot")
    amount = AmountFirstIndex([observed]).match(row)
    identity = match_property(row, [observed])
    assert amount.status == identity.status == "matched"
    assert amount.exact_transaction and amount.evidence["identifier_supported"]
    assert identity.event is None and not identity.exact_transaction
