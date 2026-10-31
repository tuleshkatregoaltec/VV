from datetime import date
from unittest.mock import AsyncMock

import pytest

from app.crm import owner_queries
from app.crm.identity import ParsedContact, _dedupe_candidates, _normalize_phone, _normalize_unit
from app.crm.ownership import _sales_evidence
from app.market.reference import property_name_lookup_key, unit_lookup_key


@pytest.mark.parametrize(
    "left,right,compatible",
    [
        (("Wadi Al Safa 7", "Arabian Ranches 2"), ("Arabian Ranches 2", "Camelia"), True),
        (("Wadi Al Safa 5", "Arabian Ranches III"), ("Arabian Ranches 3", "Joy"), True),
        (("Damac Hills 2", "DAMAC HILLS (2) - PACIFICA"), ("Damac Hills 2", "Pacifica"), True),
        (
            ("JVC", "Jumeirah Village Circle Phase 1"),
            ("Jumeirah Village Circle", "Jumeirah Village Circle Phase 2"),
            False,
        ),
        (("Wadi Al Safa 7", "Arabian Ranches 2"), ("Arabian Ranches 3", "Camelia"), False),
        (("Dubai Science Park", "Opalz"), ("Greens", "Golf Towers"), False),
    ],
)
def test_scope_comparison_respects_geography_levels_and_numbered_projects(left, right, compatible):
    from app.crm.identity import _property_scopes_compatible

    fields = ("area_name", "project_name")
    assert (
        _property_scopes_compatible(dict(zip(fields, left)), dict(zip(fields, right))) is compatible
    )
    assert (
        _property_scopes_compatible(dict(zip(fields, right)), dict(zip(fields, left))) is compatible
    )


async def test_display_project_fallback_cannot_create_a_registry_scope_collision(monkeypatch):
    rows = [sale(building_name="Tower", building_key="tower", unit_number="101", project_name="")]
    await registry(monkeypatch, rows, [])
    candidates = [
        contact(building_name="Tower", project_name=project)
        for project in ("Master community - Tower", "Master community")
    ]
    evidence = await _sales_evidence(candidates)
    assert evidence[candidates[0].property_key]
    assert all(not c.evidence.get("scoped_identity_collision") for c in candidates)
    assert all(c.evidence["registry_property_scope"]["project_name"] == "" for c in candidates)


async def test_registry_estate_prefixes_cannot_collide_after_legacy_unit_shortening(monkeypatch):
    from app.crm.ownership import _apply_evidence

    rows = [
        sale(
            unit_number=unit,
            unit_key=unit_lookup_key(unit),
            building_name="Alaya",
            building_key="alaya",
            sale_key=unit,
        )
        for unit in ("TAG-AL2-237", "TAG-M1-237")
    ]
    await registry(monkeypatch, rows, [])
    candidates = [contact(building_name="Alaya", unit_number=row["unit_number"]) for row in rows]
    evidence = await _sales_evidence(candidates)
    assert candidates[0].property_key == candidates[1].property_key
    for candidate in candidates:
        _apply_evidence(candidate, sales=evidence, rentals={})
        assert candidate.ownership_status == "conflicting_claim"


@pytest.mark.parametrize(
    "values",
    [
        ("FLAT 00415", "415", "Unit No. 415", "Unit415", "Apartment 415"),
        ("A-0101", "A 101", "a101", "A–٠١٠١", "A\u00a0۱۰۱"),
        ("١٠١.٠", "101.0", "101", "０１０１"),
    ],
)
def test_registry_spellings_share_a_lookup_candidate(values):
    assert len({unit_lookup_key(value) for value in values}) == 1


@pytest.mark.parametrize(
    "left,right",
    [
        ("2510 (Q 3)", "2510"),
        ("2510 (Q 3)", "2510 (Q 4)"),
        ("DH2-XR1139B", "XR1139B"),
        ("DL-K138", "K138"),
        ("101", "1001"),
        ("G101", "A101"),
    ],
)
def test_lookup_does_not_erase_shares_or_estate_identity(left, right):
    assert unit_lookup_key(left) != unit_lookup_key(right)


def test_persisted_property_spelling_keeps_legacy_labels_and_zeroes():
    assert _normalize_unit("Flat 00101") == "FLAT00101"
    assert _normalize_unit("A–٠١٠١") == "A-0101"
    assert _normalize_unit("TAG-AL2-006") == "006"


@pytest.mark.parametrize("value", ["+٩٧١ ٥٠ ١٢٣ ٤٥٦٧", "٠٥٠١٢٣٤٥٦٧", "۰۰۹۷۱۵۰۱۲۳۴۵۶۷"])
def test_unicode_phone_digits_match_the_existing_uae_channel(value):
    assert _normalize_phone(value) == "+971501234567"


def contact(**overrides):
    values = dict(
        source_sheet="Sheet1",
        source_row_number=2,
        contact_name="Example Owner",
        phone_primary="+971501234567",
        phone_alternate=None,
        email_primary=None,
        area_name="Business Bay",
        project_name="",
        building_name="Historic Name",
        unit_number="101",
        property_type="Apartment",
        transaction_date=None,
        transaction_price_aed=None,
        party_role="Buyer",
        procedure_type="Sale",
        row_fingerprint="example",
    )
    return ParsedContact(**(values | overrides))


def sale(**overrides):
    values = dict(
        unit_number="FLAT 00101",
        unit_key="101",
        building_name="Market Tower",
        building_key="markettower",
        area_name="Business Bay",
        area_key="businessbay",
        project_name="",
        transaction_date=date(2024, 1, 1),
        sale_amount_aed=1000000,
        sale_key="sale-one",
    )
    return values | overrides


def key(name, building_id="building-one", area="Business Bay", project=""):
    return dict(
        name_key=property_name_lookup_key(name),
        community_key=property_name_lookup_key(area),
        project_key=property_name_lookup_key(project),
        building_id=building_id,
    )


async def registry(monkeypatch, sales, keys):
    monkeypatch.setattr(owner_queries, "fetch_unit_sales", AsyncMock(return_value=sales))
    monkeypatch.setattr(
        owner_queries, "fetch_canonical_building_keys", AsyncMock(return_value=keys)
    )


async def test_exact_scoped_aliases_link_history_without_rewriting_source_cells(monkeypatch):
    rows = [
        sale(),
        sale(building_name="New Market Tower", building_key="newmarkettower", sale_key="sale-two"),
    ]
    await registry(
        monkeypatch, rows, [key("Historic Name"), key("Market Tower"), key("New Market Tower")]
    )
    candidate = contact()
    evidence = await _sales_evidence([candidate])
    assert {row["sale_key"] for row in evidence[candidate.property_key]} == {"sale-one", "sale-two"}
    assert (
        candidate.evidence["unit_hierarchy_resolution"]["method"]
        == "canonical_building_alias_with_unit"
    )
    assert (
        candidate.evidence["unit_hierarchy_resolution"]["source"]["building_name"]
        == "Historic Name"
    )
    owner_queries.fetch_unit_sales.assert_awaited_once_with({"unit_keys": ["101"]})


async def test_same_building_and_unit_across_areas_cannot_share_owner_history(monkeypatch):
    from app.crm.ownership import _apply_evidence

    rows = [
        sale(building_name="Tower", building_key="tower", unit_number="101"),
        sale(
            building_name="Tower",
            building_key="tower",
            unit_number="101",
            area_name="Dubai Marina",
            area_key="dubaimarina",
            sale_key="marina-sale",
            transaction_date=date(2025, 1, 1),
        ),
    ]
    await registry(
        monkeypatch, rows, [key("Tower"), key("Tower", building_id="marina", area="Dubai Marina")]
    )
    candidates = [
        contact(
            building_name="Tower", transaction_date=date(2024, 1, 1), transaction_price_aed=1000000
        ),
        contact(
            building_name="Tower",
            area_name="Dubai Marina",
            transaction_date=date(2025, 1, 1),
            transaction_price_aed=1000000,
        ),
    ]
    evidence = await _sales_evidence(candidates)
    for candidate in candidates:
        _apply_evidence(
            candidate,
            sales=evidence,
            rentals={candidate.property_key: {"event_key": "wrong-lease"}},
        )
        assert candidate.ownership_status == "conflicting_claim"
        assert candidate.latest_sale_date is None
        assert candidate.unit_candidate_key is None


@pytest.mark.parametrize(
    "case", ["ambiguous", "other_area", "other_project", "unscoped_generic", "inferred_area"]
)
async def test_canonical_alias_needs_independent_unambiguous_scope(monkeypatch, case):
    candidate = contact()
    observed = sale()
    keys = [key("Historic Name"), key("Market Tower")]
    if case == "ambiguous":
        keys.append(key("Historic Name", building_id="building-two"))
    elif case == "other_area":
        observed["area_name"] = "Dubai Marina"
        observed["area_key"] = "dubaimarina"
        keys.append(key("Market Tower", area="Dubai Marina"))
    elif case == "other_project":
        candidate.project_name = "Phase One"
        observed["project_name"] = "Phase Two"
    elif case == "unscoped_generic":
        keys = [key("Historic Name", project="Phase One"), key("Market Tower", project="Phase One")]
    else:
        candidate.evidence["source_fields"] = {"building_name": "Historic Name", "area_name": ""}
    await registry(monkeypatch, [observed], keys)
    assert await _sales_evidence([candidate]) == {}
    assert "unit_hierarchy_resolution" not in candidate.evidence


def test_shared_phone_does_not_merge_distinct_people():
    first, second = contact(contact_name="First Owner"), contact(contact_name="Second Owner")
    unique, collapsed = _dedupe_candidates([first, second])
    assert len(unique) == 2
    assert collapsed == 0


async def test_canonical_alias_cannot_override_explicit_physical_type(monkeypatch):
    await registry(
        monkeypatch, [sale(property_type="Villa")], [key("Historic Name"), key("Market Tower")]
    )
    assert await _sales_evidence([contact(property_type="Apartment")]) == {}


async def test_cached_property_lookup_keeps_each_sources_physical_type(monkeypatch):
    await registry(
        monkeypatch, [sale(property_type="Apartment")], [key("Historic Name"), key("Market Tower")]
    )
    apartment = contact(property_type="Flat")
    villa = contact(property_type="Villa", row_fingerprint="other")
    result = await _sales_evidence([apartment, villa])
    assert apartment.property_key in result
    assert villa.property_key not in result


async def test_generic_building_aliases_require_the_project_scoped_community_key(monkeypatch):
    candidate = contact(project_name="Phase One")
    keys = [key("Historic Name"), key("Market Tower")]
    for item in keys:
        item["community_key"] = "businessbay/phaseone"
    await registry(monkeypatch, [sale(project_name="Phase One")], keys)
    assert await _sales_evidence([candidate])
    assert (
        "businessbay/phaseone"
        in owner_queries.fetch_canonical_building_keys.call_args[0][0]["community_keys"]
    )


async def test_flat_label_does_not_turn_an_ordinary_unit_into_a_distinctive_identifier(monkeypatch):
    await registry(monkeypatch, [sale()], [])
    assert await _sales_evidence([contact(unit_number="FLAT00101")]) == {}
