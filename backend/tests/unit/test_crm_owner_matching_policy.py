"""Owner uploads must retain ambiguity and learn only from independent evidence."""

import io
from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import UploadFile

from app.crm import imports, owner_queries
from app.crm.identity import ParsedContact
from app.crm.import_models import CrmPropertyContactClaim
from app.crm.owner_assessment import capture_owner_evidence, match_owner_evidence
from app.crm.owner_matching_policy import (
    LookupScopeIndex,
    OwnerMatchIndex,
    PropertyIdentityIndex,
    SheetSizeEvidence,
    lookup_scopes,
)
from app.crm.owner_namespaces import source_namespace
from app.crm.ownership import _apply_evidence, _sales_evidence
from app.crm.registry_locations import RegistryLocationIndex, normalize_registry_locations
from app.crm.transaction_matching import property_identity


def source(**changes):
    return dict(
        amount_aed="1000000.50",
        unit_number="101",
        building_name="Alpha Tower",
        project_name="Alpha",
        area_name="Business Bay",
        property_type="Apartment",
        transaction_date="2024-01-01",
        event_family="sale",
        source_filename="new-upload.csv",
        source_sheet="Owners",
        original_identifiers={"unit_number": "101"},
        **changes,
    )


def event(**changes):
    return dict(
        sale_key="sale-1",
        sale_amount_aed="1000000.50",
        unit_number="101",
        unit_key="101",
        building_name="Alpha Tower",
        project_name="Alpha",
        area_name="Business Bay",
        property_type="Apartment",
        transaction_date=date(2024, 1, 1),
        size_sqft="1076.391041671",
        **changes,
    )


def changed(factory, **changes):
    return factory() | changes


def contact(**changes):
    values = dict(
        source_sheet="Owners",
        source_row_number=2,
        contact_name="Example",
        phone_primary=None,
        phone_alternate=None,
        email_primary=None,
        area_name="Arabian Ranches 3",
        project_name="Arabian Ranches 3",
        building_name="Sun",
        unit_number="141",
        property_type="Villa",
        transaction_date=date(2024, 1, 1),
        transaction_price_aed=1000000,
        party_role="Buyer",
        procedure_type="Sale",
        row_fingerprint="source",
        evidence={"source_fields": {"transaction_price_aed": "1000000.50"}},
    )
    return ParsedContact(**(values | changes))


def test_explicit_flat_unit_authority_cannot_be_borrowed_from_plot_or_tower():
    row = changed(source, original_identifiers={"building_number": "101", "plot_number": "101"})
    assert OwnerMatchIndex([event()]).match(row).status == "unmatched"
    assert PropertyIdentityIndex([event()]).match(row).status == "unmatched"


def test_price_date_size_cannot_erase_explicit_villa_identifier_contradiction():
    row = changed(
        source,
        unit_number="305",
        building_name="Sun",
        project_name="Arabian Ranches 3",
        area_name="Arabian Ranches 3",
        property_type="Land",
        original_identifiers={"unit_number": "305", "building_number": "R3 Sun-V-302"},
    )
    target = changed(
        event,
        unit_number="305",
        building_name="Sun",
        project_name="Arabian Ranches 3",
        area_name="Arabian Ranches 3",
        property_type="Villa",
    )
    assert source_namespace(row, target) is None
    assert OwnerMatchIndex([target]).match(row).status == "unmatched"


def test_only_full_explicit_child_can_bridge_legal_land_to_villa():
    target = changed(event, unit_number="AB-101", property_type="Villa")
    valid = changed(
        source,
        unit_number="AB-101",
        building_number="AB-101",
        property_type="Land",
        original_identifiers={
            "unit_number": "AB-101",
            "building_number": "AB-101",
            "plot_number": "PARENT",
        },
    )
    assert OwnerMatchIndex([target]).match(valid).status == "matched"
    building_only = valid | {
        "unit_number": "",
        "original_identifiers": {"building_number": "AB-101", "plot_number": "PARENT"},
    }
    assert OwnerMatchIndex([target]).match(building_only).status == "matched"
    conflict = valid | {
        "original_identifiers": {"unit_number": "AB-102", "building_number": "AB-101"}
    }
    assert OwnerMatchIndex([target]).match(conflict).status == "unmatched"
    invalid = valid | {"original_identifiers": {"plot_number": "AB-101"}}
    assert OwnerMatchIndex([target]).match(invalid).status == "unmatched"


@pytest.mark.parametrize("suffix,expected", [("21A", "matched"), ("21B", "unmatched")])
def test_citywalk_alias_keeps_building_letter_namespace(suffix, expected):
    row = changed(
        source,
        building_name="Citywalk Residential Building 21A",
        project_name="City Walk",
        area_name="City Walk",
    )
    target = changed(
        event,
        building_name=f"Building{suffix}(CW)",
        project_name="City Walk",
        area_name="City Walk",
    )
    assert OwnerMatchIndex([target]).match(row).status == expected


def test_cross_property_date_tie_needs_independent_size_and_unknown_target_abstains():
    rows = [
        event(),
        changed(event, sale_key="other", area_name="Other Area", transaction_date=date(2020, 1, 1)),
    ]
    # No geography in the source: both properties have the same qualified building.
    row = changed(source, area_name="")
    assert OwnerMatchIndex(rows).match(row).status == "ambiguous"
    result = OwnerMatchIndex([event(), changed(event, sale_key="unknown", size_sqft=None)]).match(
        row | {"size_sqft": "1076"}
    )
    assert result.status == "ambiguous" and result.flags == ("unknown_target_size",)


def test_decimal_boundary_and_close_competing_registration_remain_strict():
    assert (
        OwnerMatchIndex([changed(event, sale_amount_aed=Decimal("1000002.50"))])
        .match(source())
        .status
        == "matched"
    )
    assert (
        OwnerMatchIndex([changed(event, sale_amount_aed=Decimal("1000002.5000001"))])
        .match(source())
        .status
        == "unmatched"
    )
    result = OwnerMatchIndex(
        [event(), changed(event, sale_key="other", transaction_date=date(2024, 1, 2))]
    ).match(source())
    assert result.event is None and "ambiguous_transaction" in result.flags


def anchors(count=11):
    evidence = SheetSizeEvidence()
    for number in range(1, count + 1):
        row = changed(
            source,
            unit_number=str(number),
            original_identifiers={"unit_number": str(number)},
            size_unknown="100",
        )
        index = OwnerMatchIndex([changed(event, unit_number=str(number))])
        evidence.observe(row, index.candidates(row))
    return evidence


def test_size_learning_excludes_all_same_unit_events_and_other_sheets():
    row = changed(
        source, unit_number="1", original_identifiers={"unit_number": "1"}, size_unknown="100"
    )
    assert anchors(10).infer(row) is None  # Ten total anchors are only nine OTHER units.
    assert anchors(11).infer(row)["independent_units"] == 10
    assert anchors(11).infer(row | {"source_sheet": "Other"}) is None
    assert anchors(11).infer(row | {"source_filename": "another.csv"}) is None
    repeated = SheetSizeEvidence()
    index = OwnerMatchIndex([changed(event, unit_number="1")])
    for _ in range(100):
        repeated.observe(row, index.candidates(row))
    assert (
        repeated.infer(row | {"unit_number": "2", "original_identifiers": {"unit_number": "2"}})
        is None
    )


def test_failed_size_votes_count_against_the_95_percent_threshold():
    evidence = anchors(11)
    bad = changed(
        source, unit_number="12", original_identifiers={"unit_number": "12"}, size_unknown="99999"
    )
    index = OwnerMatchIndex([changed(event, unit_number="12")])
    evidence.observe(bad, index.candidates(bad))
    assert evidence.infer(source()) is None  # 11/12 is below 95%; no selection bias.


def test_r3_alias_is_exact_qualified_and_phase_safe():
    row = changed(
        source,
        unit_number="141",
        building_number="R3 Sun-V-141",
        building_name="Sun",
        project_name="Arabian Ranches 3",
        area_name="Arabian Ranches 3",
        property_type="Land",
        original_identifiers={"unit_number": "141", "building_number": "R3 Sun-V-141"},
    )
    numeric = changed(
        event,
        unit_number="141",
        building_name="Sun",
        project_name="Arabian Ranches 3",
        area_name="Arabian Ranches 3",
        property_type="Villa",
    )
    full = numeric | {"unit_number": "R3 Sun-V-141"}
    assert property_identity(numeric) == property_identity(full)
    assert OwnerMatchIndex([numeric]).match(row).status == "matched"
    assert OwnerMatchIndex([full]).match(row).status == "matched"
    for conflict in (
        {"building_name": "Sun Phase 2"},
        {"building_name": "Joy"},
        {"unit_number": "142"},
        {"area_name": "Arabian Ranches 2", "project_name": "Arabian Ranches 2"},
    ):
        assert OwnerMatchIndex([numeric | conflict]).match(row).status == "unmatched"


async def test_alias_history_union_precedes_current_owner_assessment(monkeypatch):
    row = contact()
    old = changed(
        event,
        sale_key="old",
        unit_number="141",
        unit_key="141",
        building_name="Sun",
        project_name="Arabian Ranches 3",
        area_name="Arabian Ranches 3",
        property_type="Villa",
    )
    later = old | {
        "sale_key": "later",
        "unit_number": "R3 Sun-V-141",
        "transaction_date": date(2025, 1, 1),
        "sale_amount_aed": "2000000",
    }
    fetch = AsyncMock(return_value=[old, later])
    monkeypatch.setattr(owner_queries, "fetch_unit_sales", fetch)
    monkeypatch.setattr(owner_queries, "fetch_canonical_building_keys", AsyncMock(return_value=[]))
    sales = await _sales_evidence([row])
    assert {event["sale_key"] for event in sales[row.property_key]} == {"old", "later"}
    assert "r3sunv141" in fetch.await_args.args[0]["unit_keys"]
    _apply_evidence(row, sales=sales, rentals={})
    assert row.ownership_status == "former_owner" and row.later_sale_date == date(2025, 1, 1)
    monkeypatch.setattr(
        owner_queries, "fetch_assessment_building_aliases", AsyncMock(return_value=[])
    )
    refresh = AsyncMock(return_value=[old, later])
    monkeypatch.setattr(owner_queries, "fetch_assessment_sales", refresh)
    refreshed = contact()
    bundle = await capture_owner_evidence([refreshed])
    assert ("sun", "r3sunv141") in refresh.await_args.args[0]["properties"]
    _apply_evidence(refreshed, sales=match_owner_evidence([refreshed], bundle), rentals={})
    assert refreshed.ownership_status == "former_owner"


async def test_scoped_lookup_keeps_numeric_ids_out_of_citywide_queries(monkeypatch):
    assert not lookup_scopes(
        changed(source, building_name="Building 1", project_name="", area_name="")
    )
    query = AsyncMock(return_value=[])
    monkeypatch.setattr(owner_queries, "query", query)
    await owner_queries.fetch_property_identity_candidates(
        {"identifiers": ["1"], "scopes": [("sun", "1")]}
    )
    sql = query.await_args.args[0]
    assert "owner_lookup" in sql and "result_overflow_mode='throw'" in sql
    assert query.await_args.kwargs["external_data"] is not None


def test_catalog_scope_retrieval_includes_the_same_named_alias_as_the_matcher():
    row = changed(
        source,
        unit_number="T2-201",
        building_name="GR PANORAMA",
        project_name="",
        area_name="",
        original_identifiers={"unit_number": "T2-201"},
    )
    target = changed(
        event,
        unit_number="T2-201",
        building_name="Panorama",
        project_name="Panorama",
        area_name="The Views",
    )
    catalog = LookupScopeIndex(
        [{"building_label": "Panorama", "project_label": "Panorama", "area_label": "The Views"}]
    )
    assert ("panorama", "t2201") in lookup_scopes(row, catalog)
    assert OwnerMatchIndex([target]).match(row).event["sale_key"] == target["sale_key"]
    assert ("panorama", "t2201") not in lookup_scopes(row)


def test_jvt_missing_unit_keeps_authoritative_full_building_child_identifier():
    row = changed(
        source,
        unit_number="",
        building_number="JVT2N9B",
        building_name="",
        project_name="Jumeirah Village Triangle",
        area_name="Jumeirah Village Triangle",
        property_type="Land",
        original_identifiers={"unit_number": "", "building_number": "JVT2N9B"},
    )
    target = changed(
        event,
        unit_number="JVT2N9B",
        building_name="Jumeirah Village Triangle (JVT)",
        project_name="",
        area_name="",
        property_type="Villa",
    )
    result = OwnerMatchIndex([target]).match(row)
    assert result.status == "matched" and result.event is not None
    assert not set(result.flags) & {"type_mismatch_review_required", "missing_target_area"}
    assert OwnerMatchIndex([target | {"unit_number": "JVT2N9C"}]).match(row).status == "unmatched"


async def test_accepted_citywalk_hierarchy_is_not_vetoed_by_legacy_file_context(monkeypatch):
    raw = changed(source, building_name="Laurel", project_name="Laurel", area_name="City Walk")
    target = changed(
        event,
        building_name="Laurel",
        project_name="Central Park, City Walk",
        area_name="Central Park",
    )
    result = OwnerMatchIndex([target]).match(raw)
    assert result.event is not None
    row = contact(
        area_name="Central Park",
        project_name="Central Park, City Walk",
        building_name="Laurel",
        unit_number="101",
        property_type="Apartment",
        evidence={
            "source_fields": {
                **{
                    key: raw[key]
                    for key in (
                        "area_name",
                        "project_name",
                        "building_name",
                        "unit_number",
                        "property_type",
                    )
                },
                "transaction_price_aed": "1000000.50",
            },
            "original_identifiers": raw["original_identifiers"],
            "owner_match_policy": "owner-qualified-1",
            "file_context": {"locations": ["City Walk"]},
            "amount_first_match": {
                **result.evidence,
                "status": result.status,
                "flags": list(result.flags),
            },
            "property_identity_resolution": {"resolved": {"sale_key": target["sale_key"]}},
        },
    )
    monkeypatch.setattr(owner_queries, "fetch_unit_sales", AsyncMock(return_value=[target]))
    monkeypatch.setattr(owner_queries, "fetch_canonical_building_keys", AsyncMock(return_value=[]))
    sales = await _sales_evidence([row])
    assert [sale["sale_key"] for sale in sales[row.property_key]] == [target["sale_key"]]
    _apply_evidence(row, sales=sales, rentals={})
    assert row.ownership_status == "verified_current_owner"


@pytest.mark.parametrize(
    "building,project",
    [("Viridis C", "Viridis"), ("Viridis D", "Viridis"), ("Navitas Tower A", "Navitas")],
)
def test_recovered_target_labels_are_catalog_confirmed_on_the_first_pass(building, project):
    catalog = RegistryLocationIndex(
        [
            {
                "building_label": building,
                "project_label": project,
                "area_label": "Damac Hills 2",
                "building_key": building,
                "area_key": "Damac Hills 2",
            }
        ]
    )
    raw = changed(event, building_name=building, project_name="", area_name="Damac Hills 2")
    first = normalize_registry_locations(raw, catalog)
    assert first["project_name"] == project and first["registry_catalog_confirmed"] is True
    assert normalize_registry_locations(first, catalog) == first
    row = changed(source, building_name=building, project_name="0", area_name="DAMAC HILLS 1734")
    result = OwnerMatchIndex([first]).match(row)
    assert result.status == "matched" and result.event is not None
    assert "damachills_numeric_master_exact_catalog_building" in result.evidence["supported_rules"]


def test_catalog_legal_area_prefilter_retains_original_full_plot_identifier():
    places = [
        {
            "building_label": "Amalia Residences",
            "project_label": "Amalia Residences",
            "area_label": "Al Furjan",
            "building_key": "amaliaresidences",
            "area_key": "Jabal Ali First",
        }
    ]
    source_row = changed(
        source,
        unit_number="",
        plot_number="AFC024",
        building_name="null",
        project_name="Al Furjan",
        area_name="Al Furjan",
        property_type="Land",
        original_identifiers={
            "unit_number": "null",
            "plot_number": "AFC024",
            "building_number": "1",
        },
    )
    scopes = lookup_scopes(source_row, LookupScopeIndex(places))
    assert ("jabalali1", "afc24") in scopes and ("jabalalifirst", "afc24") in scopes
    raw = changed(
        event,
        unit_number="AFC024",
        property_type="Plot",
        building_name="Amalia Residences",
        project_name="",
        area_name="Jabal Ali First",
    )
    target = normalize_registry_locations(raw, RegistryLocationIndex(places))
    assert OwnerMatchIndex([target]).match(source_row).event is not None
    unrelated = normalize_registry_locations(
        raw | {"area_name": "Dubai Marina"}, RegistryLocationIndex(places)
    )
    assert OwnerMatchIndex([unrelated]).match(source_row).status == "unmatched"
    conflict = source_row | {
        "unit_number": "901",
        "original_identifiers": {
            "unit_number": "901",
            "plot_number": "AFC024",
            "building_number": "1",
        },
    }
    assert OwnerMatchIndex([target]).match(conflict).status == "unmatched"


def test_audited_unique_date_relaxed_event_is_provisional_in_both_date_directions():
    for year in (2020, 2026):
        target = changed(event, transaction_date=date(year, 1, 1))
        source_row = source()
        result = OwnerMatchIndex([target]).match(source_row)
        row = contact(
            area_name="Business Bay",
            project_name="Alpha",
            building_name="Alpha Tower",
            unit_number="101",
            property_type="Apartment",
            evidence={
                "original_identifiers": {"unit_number": "101"},
                "original_property_fields": {
                    key: source_row[key]
                    for key in (
                        "area_name",
                        "project_name",
                        "building_name",
                        "unit_number",
                        "property_type",
                    )
                },
                "source_fields": {"transaction_price_aed": "1000000.50"},
                "owner_match_policy": "owner-qualified-1",
                "amount_first_match": {
                    **result.evidence,
                    "status": result.status,
                    "flags": list(result.flags),
                },
            },
        )
        _apply_evidence(row, sales={row.property_key: [target]}, rentals={})
        assert row.ownership_status == "probable_current_owner"
        assert "source date differs" in row.match_reason


async def test_actual_upload_parser_shared_matcher_and_persistence_learn_new_sheet(monkeypatch):
    added = []
    db = MagicMock()
    db.add.side_effect = added.append
    db.add_all.side_effect = added.extend

    def ids(*_):
        for number, value in enumerate(added, 1):
            if getattr(value, "id", None) is None:
                value.id = number

    for name in ("commit", "rollback", "delete"):
        setattr(db, name, AsyncMock())
    db.refresh = AsyncMock(side_effect=ids)
    db.flush = AsyncMock(side_effect=ids)
    monkeypatch.setattr(
        imports.import_repository, "find_import_by_digest", AsyncMock(return_value=None)
    )
    monkeypatch.setattr(imports, "_llm_mapping", AsyncMock(side_effect=lambda profile: profile))
    for name in (
        "prepare_file_context",
        "recover_from_file_context",
        "_apply_registry_unit_fallbacks",
        "_enrich_workspaces",
    ):
        monkeypatch.setattr(imports, name, AsyncMock())
    monkeypatch.setattr(imports, "_rental_evidence", AsyncMock(return_value={}))
    monkeypatch.setattr(imports, "save_drop_log", AsyncMock(return_value=True))
    monkeypatch.setattr(imports, "_import_response", AsyncMock(return_value="saved"))
    monkeypatch.setattr(imports, "_invalidate_owner_summary_cache", MagicMock())
    monkeypatch.setattr(owner_queries, "fetch_registry_places", AsyncMock(return_value=[]))
    monkeypatch.setattr(owner_queries, "fetch_canonical_building_keys", AsyncMock(return_value=[]))
    targets = [
        changed(event, unit_number=str(number), unit_key=str(number), sale_key=f"sale-{number}")
        for number in range(101, 113)
    ]
    monkeypatch.setattr(
        owner_queries, "fetch_transaction_signatures", AsyncMock(return_value=targets)
    )
    monkeypatch.setattr(
        owner_queries, "fetch_property_identity_candidates", AsyncMock(return_value=[])
    )
    monkeypatch.setattr(owner_queries, "fetch_unit_sales", AsyncMock(return_value=targets))
    # The property-first matcher runs too, on an empty warehouse: no place, so no confirmed owner.
    for name in (
        "fetch_place_hierarchy",
        "fetch_matcher_places",
        "fetch_matcher_events",
        "fetch_matcher_registry",
    ):
        monkeypatch.setattr(owner_queries, name, AsyncMock(return_value=[]))
    lines = [
        "NameEn,BuildingNameEn,Project,AreaNameEn,UnitNumber,PropertyTypeEn,TransactionDate,ProcedureValue,ProcedurePartyTypeNameEn,ProcedureNameEn,Size"
    ]
    lines += [
        f"Example {number},Alpha Tower,Alpha,Business Bay,{number},Apartment,2024-01-01,1000000.50,Buyer,Sale,100"
        for number in range(101, 113)
    ]
    lines.append(
        "History,Alpha Tower,Alpha,Business Bay,101,Apartment,2024-02-01,500000,Buyer,Mortgage Registration,100"
    )
    result = await imports.process_contact_import(
        db,
        upload=UploadFile(
            file=io.BytesIO(("\n".join(lines)).encode()), filename="never-seen-before.csv"
        ),
        name="New",
        user_id="user",
        organization_id="tenant",
    )
    assert result == "saved"
    claims = [value for value in added if isinstance(value, CrmPropertyContactClaim)]
    assert len(claims) == 13  # Non-sale history is persisted as well as acquisitions.
    acquired = [claim for claim in claims if claim.procedure_type == "Sale"]
    assert len(acquired) == 12
    assert all(claim.evidence["inferred_size_unit"]["unit"] == "sqm" for claim in acquired)
    assert all(
        claim.evidence["inferred_size_unit"]["independent_units"] == 11 for claim in acquired
    )
    assert all(
        claim.evidence["amount_first_match"]["version"] == "owner-qualified-1" for claim in acquired
    )
    assert all(
        claim.evidence["original_identifiers"]["unit_number"] == claim.unit_number
        for claim in acquired
    )
    assert claims[-1].ownership_status not in {"verified_current_owner", "probable_current_owner"}
