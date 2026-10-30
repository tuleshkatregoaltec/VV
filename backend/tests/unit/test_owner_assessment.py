"""A named source party is not proof of title; registry evidence must support the sale."""

from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

from app.crm import owner_assessment
from app.crm.identity import ParsedContact
from app.crm.owner_history import project_owner_history
from app.crm.owner_queries import fetch_assessment_source_fingerprint
from app.crm.ownership import _apply_evidence


@pytest.fixture(autouse=True)
def stable_assessment_metadata(monkeypatch):
    from app.crm import owner_queries

    monkeypatch.setattr(owner_assessment, "_recent", None)
    monkeypatch.setattr(
        owner_assessment.owner_repository, "owner_sources_only", AsyncMock(return_value=False)
    )
    monkeypatch.setattr(
        owner_queries, "fetch_assessment_source_fingerprint", AsyncMock(return_value="warehouse")
    )


def contact(**changes):
    values = dict(
        source_sheet="Sheet",
        source_row_number=2,
        contact_name="Synthetic Buyer",
        phone_primary=None,
        phone_alternate=None,
        email_primary=None,
        area_name="Business Bay",
        project_name="Executive Towers",
        building_name="Aspect Tower",
        unit_number="602",
        property_type="Apartment",
        transaction_date=date(2024, 1, 10),
        transaction_price_aed=1000000,
        party_role="Buyer",
        procedure_type="Sale",
        row_fingerprint="test",
        evidence={"source_fields": {"size_sqft": "1,000"}, "event_family": "sale"},
    )
    return ParsedContact(**{**values, **changes})


def sale(**changes):
    return {
        **dict(
            transaction_date=date(2024, 1, 10),
            sale_amount_aed=1000000,
            size_sqft=1000,
            sale_key="sale-a",
        ),
        **changes,
    }


def assess(candidate, *sales):
    _apply_evidence(candidate, sales={candidate.property_key: list(sales)}, rentals={})
    return candidate.ownership_status


def test_latest_seller_requires_registry_match_and_describes_disposal():
    assert assess(contact(party_role="Seller")) == "unverified_former_owner"
    assert (
        assess(contact(party_role="Seller"), sale(sale_amount_aed=2000000))
        == "unverified_former_owner"
    )
    seller = contact(party_role="Seller")
    assert assess(seller, sale()) == "former_owner"
    assert seller.confidence_score == 95


@pytest.mark.parametrize("days", [5, 7, -5, -7])
def test_unique_shifted_registration_uses_size_to_increase_confidence(days):
    observed = sale(transaction_date=date(2024, 1, 10) + timedelta(days=days))
    assert assess(contact(), observed) == "probable_current_owner"
    without_size = contact(evidence={"event_family": "sale"})
    assert assess(without_size, observed) == "probable_current_owner"
    assert without_size.confidence_score == 75


def test_exact_date_does_not_override_another_registration_with_matching_terms():
    assert (
        assess(contact(), sale(), sale(sale_key="sale-b", transaction_date=date(2024, 1, 15)))
        == "conflicting_claim"
    )


def test_size_conflict_and_out_of_window_date_cannot_verify_acquisition():
    assert assess(contact(), sale(size_sqft=1500)) == "conflicting_claim"
    assert assess(contact(), sale(transaction_date=date(2024, 1, 18))) == "unit_linked_unverified"


def test_later_sale_does_not_verify_a_mismatched_claim_of_former_ownership():
    assert (
        assess(
            contact(),
            sale(sale_amount_aed=2000000),
            sale(transaction_date=date(2025, 1, 1), sale_key="new"),
        )
        != "former_owner"
    )
    assert (
        assess(contact(), sale(), sale(transaction_date=date(2025, 1, 1), sale_key="new"))
        == "former_owner"
    )


def row(number=1, **changes):
    item = contact()
    return {
        **vars(item),
        "id": number,
        "owner_key": "source-owner",
        "property_key": item.property_key,
        "import_id": 1,
        "ownership_status": "verified_current_owner",
        "confidence_score": 98,
        "match_reason": "Matched",
        "latest_sale_date": item.transaction_date,
        "event_family": "sale",
        **changes,
    }


@pytest.mark.parametrize("family", ["gift", "inheritance", "ownership_transfer", "property_change"])
def test_later_transfer_for_same_identity_makes_sale_based_current_owner_uncertain(family):
    buyer = row()
    transfer = row(
        2,
        event_family=family,
        procedure_type=family,
        ownership_status="unit_linked_unverified",
        transaction_date=date(2025, 1, 1),
    )
    summary, _ = project_owner_history([buyer, transfer], [buyer, transfer])
    assert summary.verified_current_count == 0
    assert summary.unresolved_count == 1


async def test_warehouse_failure_does_not_fall_back_to_saved_current_status(monkeypatch):
    monkeypatch.setattr(
        owner_assessment.owner_repository,
        "list_owner_history_rows",
        AsyncMock(return_value=[row()]),
    )
    monkeypatch.setattr(
        owner_assessment, "_fresh_sales", AsyncMock(side_effect=RuntimeError("Unavailable"))
    )
    snapshot = await owner_assessment._build(None, "tenant")
    assert snapshot.warehouse_status == "unavailable"
    assert snapshot.summary.verified_current_count == 0
    assert snapshot.rows[0]["ownership_status"] == "verified_current_owner"
    assert snapshot.rows[0]["assessed_status"] == "unit_linked_unverified"


def test_cache_roundtrip_preserves_dates_and_scoped_property_identity():
    source = row(
        assessed_status="verified_current_owner",
        assessed_reason="Matched",
        assessed_confidence_score=98,
    )
    snapshot = owner_assessment._project([source], datetime.now(timezone.utc), "available")
    restored = owner_assessment._decode(owner_assessment._encode(snapshot))
    assert restored.rows == snapshot.rows
    assert restored.summary == snapshot.summary


async def test_fresh_registry_lookup_requires_location_scope_and_batches_once(monkeypatch):
    from app.crm import owner_queries

    registry = [
        {
            **sale(),
            "building_name": "Aspect Tower",
            "unit_number": "602",
            "area_name": "Business Bay",
            "project_name": "Executive Towers",
            "property_type": "Apartment",
        },
        {
            **sale(sale_key="different-area", transaction_date=date(2025, 1, 1)),
            "building_name": "Aspect Tower",
            "unit_number": "602",
            "area_name": "Dubai Marina",
            "project_name": "Marina",
            "property_type": "Apartment",
        },
    ]
    monkeypatch.setattr(
        owner_queries, "fetch_assessment_building_aliases", AsyncMock(return_value=[])
    )
    query = AsyncMock(return_value=registry)
    monkeypatch.setattr(owner_queries, "fetch_assessment_sales", query)
    candidate = contact()
    result = await owner_assessment._fresh_sales([(row(), candidate)])
    assert [event["sale_key"] for event in result[candidate.property_key]] == ["sale-a"]
    assert query.await_count == 1
    assert assess(candidate, *result[candidate.property_key]) == "verified_current_owner"


def test_explicit_square_metres_convert_without_guessing_source_units():
    candidate = contact(
        evidence={"event_family": "sale", "source_fields": {"size_sqm": "92.90304"}}
    )
    assert assess(candidate, sale(transaction_date=date(2024, 1, 15))) == "probable_current_owner"


@pytest.mark.parametrize("conflict_date", [None, date(2025, 1, 1)])
def test_newer_or_undated_conflicting_same_party_claim_prevents_current_projection(conflict_date):
    buyer = row()
    conflict = row(
        2,
        ownership_status="conflicting_claim",
        transaction_date=conflict_date,
        latest_sale_date=None,
    )
    summary, _ = project_owner_history([buyer, conflict], [buyer, conflict])
    assert summary.verified_current_count == 0
    assert summary.unresolved_count == 1


async def test_type_change_cannot_hide_later_same_property_sale(monkeypatch):
    from app.crm import owner_queries

    base = {
        **sale(),
        "building_name": "Aspect Tower",
        "unit_number": "602",
        "area_name": "Business Bay",
        "project_name": "Executive Towers",
        "property_type": "Apartment",
    }
    later = {
        **base,
        "sale_key": "later",
        "transaction_date": date(2025, 1, 1),
        "property_type": "Villa",
    }
    monkeypatch.setattr(
        owner_queries, "fetch_assessment_building_aliases", AsyncMock(return_value=[])
    )
    monkeypatch.setattr(
        owner_queries, "fetch_assessment_sales", AsyncMock(return_value=[base, later])
    )
    candidate = contact()
    result = await owner_assessment._fresh_sales([(row(), candidate)])
    assert len(result[candidate.property_key]) == 2
    assert assess(candidate, *result[candidate.property_key]) == "conflicting_claim"


async def test_bulk_property_lookup_uses_typed_external_table_without_sql_interpolation(
    monkeypatch,
):
    from app.crm import owner_queries

    query = AsyncMock(return_value=[])
    monkeypatch.setattr(owner_queries, "query", query)
    await owner_queries.fetch_assessment_sales({"properties": [("synthetictower", "602")]})
    args, kwargs = query.call_args
    assert "synthetictower" not in args[0]
    external = kwargs["external_data"].files[0]
    assert external.structure == "location String, unit String"
    assert b'"location": "synthetictower"' in external.data


async def test_warehouse_adapter_preserves_external_table_through_observability(monkeypatch):
    from types import SimpleNamespace

    from app.clickhouse import client

    execute = AsyncMock(return_value=SimpleNamespace(column_names=["count"], result_rows=[[1]]))
    monkeypatch.setattr(
        client, "get_client", AsyncMock(return_value=SimpleNamespace(query=execute))
    )
    marker = object()
    assert await client.query("SELECT count FROM scoped", external_data=marker) == [{"count": 1}]
    assert execute.call_args.kwargs["external_data"] is marker


async def test_shared_cache_is_tenant_scoped_and_source_changes_invalidate(monkeypatch):
    from types import SimpleNamespace

    values = {}
    revision = "first"

    async def get(key):
        return values.get(key)

    async def set_value(key, value, **kwargs):
        values[key] = value

    async def source_revision(db, organization_id):
        return revision

    builds = []

    async def build(db, organization_id, **kwargs):
        builds.append(organization_id)
        event = row(
            owner_key=organization_id,
            assessed_status="unit_linked_unverified",
            assessed_reason="Synthetic",
            assessed_confidence_score=20,
        )
        return owner_assessment._project([event], datetime.now(timezone.utc), "available")

    monkeypatch.setattr(owner_assessment, "_recent", None)
    monkeypatch.setattr(owner_assessment, "_source_revision", source_revision)
    monkeypatch.setattr(owner_assessment, "_build", build)
    monkeypatch.setattr(
        owner_assessment, "_cache_client", lambda: SimpleNamespace(get=get, set=set_value)
    )
    first = await owner_assessment.get_owner_assessment(None, organization_id="tenant-a")
    second = await owner_assessment.get_owner_assessment(None, organization_id="tenant-b")
    assert first.rows[0]["owner_key"] == "tenant-a"
    assert second.rows[0]["owner_key"] == "tenant-b"
    await owner_assessment.get_owner_assessment(None, organization_id="tenant-a")
    assert builds == ["tenant-a", "tenant-b"]
    revision = "second"
    await owner_assessment.get_owner_assessment(None, organization_id="tenant-a")
    assert builds == ["tenant-a", "tenant-b", "tenant-a"]


async def test_unavailable_cached_assessment_expires_after_short_failure_window(monkeypatch):
    from types import SimpleNamespace

    snapshot = owner_assessment._project(
        [
            row(
                assessed_status="unit_linked_unverified",
                assessed_reason="Unavailable",
                assessed_confidence_score=0,
            )
        ],
        datetime.now(timezone.utc) - timedelta(seconds=20),
        "unavailable",
    )
    build = AsyncMock(
        return_value=owner_assessment._project([], datetime.now(timezone.utc), "available")
    )
    monkeypatch.setattr(owner_assessment, "_recent", None)
    monkeypatch.setattr(owner_assessment, "_source_revision", AsyncMock(return_value="revision"))
    monkeypatch.setattr(owner_assessment, "_build", build)
    monkeypatch.setattr(
        owner_assessment,
        "_cache_client",
        lambda: SimpleNamespace(
            get=AsyncMock(return_value=owner_assessment._encode(snapshot)), set=AsyncMock()
        ),
    )
    result = await owner_assessment.get_owner_assessment(None, organization_id="tenant")
    assert result.warehouse_status == "available"
    assert build.await_count == 1


@pytest.mark.parametrize(
    "header, expected",
    [
        ("Size", "unknown"),
        ("PropertySize", "unknown"),
        ("AreaSqft", "sqft"),
        ("Size (m²)", "sqm"),
        ("AreaSqm", "sqm"),
    ],
)
def test_legacy_size_header_units_are_declared_not_inferred_from_value(header, expected):
    from app.crm.import_events import source_size_unit

    assert source_size_unit({"size_sqft": header}) == expected


def test_ambiguous_legacy_size_allows_lower_scored_shifted_date_contact():
    candidate = contact(
        evidence={
            "event_family": "sale",
            "source_size_unit": "unknown",
            "source_fields": {"size_sqft": "92.90304"},
        }
    )
    assert assess(candidate, sale()) == "verified_current_owner"
    assert assess(candidate, sale(transaction_date=date(2024, 1, 15))) == "probable_current_owner"
    assert candidate.confidence_score == 75
    assert "declared unit" in candidate.match_reason
    assert candidate.evidence["source_fields"]["size_sqft"] == "92.90304"


def test_explicit_legacy_sqm_header_corrects_prior_sqft_mapping_without_guessing():
    candidate = contact(
        evidence={
            "event_family": "sale",
            "source_size_unit": "sqm",
            "source_fields": {"size_sqft": "92.90304"},
        }
    )
    assert assess(candidate, sale(transaction_date=date(2024, 1, 15))) == "probable_current_owner"


def test_explicit_size_column_takes_precedence_over_ambiguous_size_column():
    from app.crm.import_events import source_size_unit

    assert source_size_unit({"size_unknown": "Size", "size_sqm": "AreaSqm"}) == "sqm"
    assert source_size_unit({"size_sqft": "Size", "size_sqm": "AreaSqm"}) == "sqm"
    candidate = contact(
        evidence={
            "event_family": "sale",
            "source_fields": {"size_unknown": "9000", "size_sqm": "92.90304"},
        }
    )
    assert assess(candidate, sale(transaction_date=date(2024, 1, 15))) == "probable_current_owner"


def snapshot(candidates, sales):
    rows = [
        row(
            index,
            **vars(candidate),
            property_key=candidate.property_key,
            event_family=candidate.evidence.get("event_family", "sale"),
        )
        for index, candidate in enumerate(candidates, 1)
    ]
    valid = [(item, owner_assessment._candidate(item)) for item in rows]
    return owner_assessment._finish_assessment(
        rows,
        valid,
        {candidates[0].property_key: sales},
        datetime.now(timezone.utc),
        "available",
    )


def park_party(role="Buyer", **changes):
    return contact(
        **{
            "contact_name": f"Synthetic {role}",
            "party_role": role,
            "building_name": "Park Heights 1",
            "unit_number": "909",
            "transaction_date": date(2024, 3, 27),
            "transaction_price_aed": 858888,
            "evidence": {"event_family": "sale", "source_size_unit": "unknown"},
            **changes,
        }
    )


def park_sale(**changes):
    return sale(**{"transaction_date": date(2018, 9, 27), "sale_amount_aed": 858888, **changes})


def test_distant_anchor_separates_possible_buyer_from_source_seller_disposal():
    result = snapshot([park_party(), park_party("Seller")], [park_sale()])
    assert result.summary.probable_current_count == 1
    assert result.summary.former_count == 1
    assert result.summary.verified_current_count == 0
    assert [item["assessed_confidence_score"] for item in result.rows] == [65, 65]
    assert [item["party_role"] for item in result.rows] == ["Buyer", "Seller"]
    assert all(item["transaction_date"] == date(2024, 3, 27) for item in result.rows)
    assert all(item["sale_anchor_date"] == date(2018, 9, 27) for item in result.rows)
    assert owner_assessment._decode(owner_assessment._encode(result)).rows == result.rows


def test_lime_gardens_812_one_day_offset_and_unknown_size_remains_possible_current():
    buyer = contact(
        building_name="Lime Gardens",
        unit_number="812",
        property_type="Unit",
        transaction_date=date(2024, 3, 27),
        transaction_price_aed=1946170,
        evidence={
            "event_family": "sale",
            "source_size_unit": "unknown",
            "source_fields": {"size_unknown": "62"},
        },
    )
    assert (
        assess(
            buyer,
            sale(
                transaction_date=date(2024, 3, 28),
                sale_amount_aed=1946170,
                property_type="Apartment",
            ),
        )
        == "probable_current_owner"
    )
    assert buyer.confidence_score == 75


@pytest.mark.parametrize("price", [None, 0, -1, 900000])
@pytest.mark.parametrize("role", ["Buyer", "Seller"])
def test_absence_of_later_sale_never_substitutes_for_positive_matching_price(price, role):
    assert assess(park_party(role, transaction_price_aed=price), park_sale()) not in {
        "verified_current_owner",
        "probable_current_owner",
    }


def test_repeated_matching_amount_cannot_uniquely_anchor_a_distant_source_date():
    buyer = park_party()
    assert (
        assess(buyer, park_sale(transaction_date=date(2015, 1, 1), sale_key="older"), park_sale())
        != "probable_current_owner"
    )
    # Repeated materializations of the same registry event are not competing events.
    assert assess(park_party(), park_sale(), park_sale()) == "probable_current_owner"


@pytest.mark.parametrize("role", ["Buyer", "Seller"])
def test_known_size_contradiction_blocks_distant_current_inference(role):
    candidate = park_party(
        role, evidence={"event_family": "sale", "source_fields": {"size_sqft": 1500}}
    )
    assert assess(candidate, park_sale(size_sqft=1000)) not in {
        "verified_current_owner",
        "probable_current_owner",
    }


@pytest.mark.parametrize("role", ["Buyer", "Seller"])
def test_earlier_matched_sale_with_later_registry_event_remains_former(role):
    candidate = contact(party_role=role)
    assert (
        assess(
            candidate,
            sale(),
            sale(transaction_date=date(2025, 1, 1), sale_key="later", sale_amount_aed=1200000),
        )
        == "former_owner"
    )
    assert "sale_anchor_key" not in candidate.evidence


@pytest.mark.parametrize("competing_role", ["Buyer", "Seller"])
def test_only_competing_buyers_create_current_ownership_ties(competing_role):
    parties = [
        park_party(),
        park_party("Seller"),
        park_party(competing_role, contact_name="Third Synthetic Party"),
    ]
    result = snapshot(parties, [park_sale()])
    assert result.summary.probable_current_count == (0 if competing_role == "Buyer" else 1)
    assert result.summary.unresolved_count == (2 if competing_role == "Buyer" else 0)
    assert result.summary.former_count == (1 if competing_role == "Buyer" else 2)


@pytest.mark.parametrize("family", ["gift", "ownership_transfer"])
def test_intervening_transfer_blocks_distant_anchor_even_before_source_file_date(family):
    transfer = park_party(
        procedure_type=family, transaction_date=date(2020, 1, 1), evidence={"event_family": family}
    )
    result = snapshot([park_party(), park_party("Seller"), transfer], [park_sale()])
    assert result.summary.probable_current_count == 0


def test_shifted_source_seller_does_not_displace_buyer_anchored_to_same_registry_event():
    result = snapshot(
        [park_party(), park_party("Seller", transaction_date=date(2024, 4, 1))], [park_sale()]
    )
    assert result.summary.probable_current_count == 1
    assert result.summary.former_count == 1


def test_former_seller_cannot_become_current_from_an_arbitrary_anchor_key():
    buyer, seller = park_party(), park_party("Seller")
    result = snapshot([buyer, seller], [park_sale()])
    result.rows[1]["sale_anchor_key"] = "different-registration"
    result = owner_assessment._project(result.rows, result.checked_at, "available")
    assert result.summary.probable_current_count == 1
    assert result.summary.former_count == 1


def test_latest_same_identity_disposal_uses_its_supporting_score():
    older = contact(transaction_date=date(2020, 1, 1), transaction_price_aed=800000)
    seller = contact(party_role="Seller")
    result = snapshot(
        [older, seller],
        [sale(transaction_date=date(2020, 1, 1), sale_amount_aed=800000, sale_key="older"), sale()],
    )
    assert result.summary.probable_current_count == 0
    assert result.summary.former_count == 1
    assert [item["event_assessed_status"] for item in result.rows] == [
        "former_owner",
        "former_owner",
    ]
    assert [item["event_assessed_confidence_score"] for item in result.rows] == [99, 95]
    assert all(item["assessed_confidence_score"] == 95 for item in result.rows)


def install_assessment_cache(monkeypatch):
    from types import SimpleNamespace

    values = {}

    async def get(key):
        return values.get(key)

    async def set_value(key, value, **kwargs):
        values[key] = value

    cache = SimpleNamespace(get=AsyncMock(side_effect=get), set=AsyncMock(side_effect=set_value))
    monkeypatch.setattr(owner_assessment, "_cache_client", lambda: cache)
    monkeypatch.setattr(owner_assessment, "_source_revision", AsyncMock(return_value="source"))
    return cache, values


def confirmed_snapshot():
    return owner_assessment._project(
        [
            row(
                assessed_status="verified_current_owner",
                assessed_reason="Matched",
                assessed_confidence_score=98,
            )
        ],
        datetime.now(timezone.utc),
        "available",
    )


async def test_slow_build_gets_full_cache_lifetime_without_relabeling_evidence_time(monkeypatch):
    cache, _ = install_assessment_cache(monkeypatch)
    observed = confirmed_snapshot()
    observed.checked_at -= timedelta(minutes=5)
    observed.summary.checked_at = observed.checked_at
    capture_time = observed.checked_at
    build = AsyncMock(return_value=observed)
    monkeypatch.setattr(owner_assessment, "_build", build)
    first = await owner_assessment.get_owner_assessment(None, organization_id="tenant")
    cached_at = first.cached_at
    second = await owner_assessment.get_owner_assessment(None, organization_id="tenant")
    assert first is second
    assert build.await_count == 1
    assert cache.set.call_args.kwargs["expire"] >= 119
    assert second.checked_at == second.summary.checked_at == capture_time
    assert second.cached_at == cached_at


async def test_warehouse_write_invalidates_confirmed_cached_assessment(monkeypatch):
    from app.crm import owner_queries

    _, values = install_assessment_cache(monkeypatch)
    fingerprint = AsyncMock(return_value="before-write")
    monkeypatch.setattr(owner_queries, "fetch_assessment_source_fingerprint", fingerprint)
    build = AsyncMock(side_effect=lambda *args, **kwargs: confirmed_snapshot())
    monkeypatch.setattr(owner_assessment, "_build", build)
    await owner_assessment.get_owner_assessment(None, organization_id="tenant")
    fingerprint.return_value = "after-write"
    await owner_assessment.get_owner_assessment(None, organization_id="tenant")
    assert build.await_count == 2
    assert len(values) == 2


async def test_metadata_failure_cannot_reuse_cached_verified_labels(monkeypatch):
    from app.crm import owner_queries

    install_assessment_cache(monkeypatch)
    monkeypatch.setattr(owner_assessment, "_source_rows", AsyncMock(side_effect=lambda *a: [row()]))
    fresh = AsyncMock(side_effect=lambda candidates: {candidates[0][1].property_key: [sale()]})
    monkeypatch.setattr(owner_assessment, "_fresh_sales", fresh)
    first = await owner_assessment.get_owner_assessment(None, organization_id="tenant")
    assert first.rows[0]["assessed_status"] == "verified_current_owner"
    monkeypatch.setattr(
        owner_queries, "fetch_assessment_source_fingerprint", AsyncMock(side_effect=TimeoutError)
    )
    failed = await owner_assessment.get_owner_assessment(None, organization_id="tenant")
    assert failed.warehouse_status == "unavailable"
    assert failed.summary.verified_current_count == 0
    assert failed.rows[0]["assessed_status"] == "unit_linked_unverified"
    assert fresh.await_count == 1


@pytest.mark.parametrize("changed", ["source", "warehouse"])
async def test_change_during_build_returns_unresolved_and_never_caches_confirmation(
    monkeypatch, changed
):
    from app.crm import owner_queries

    cache, values = install_assessment_cache(monkeypatch)
    if changed == "source":
        monkeypatch.setattr(
            owner_assessment, "_source_revision", AsyncMock(side_effect=["first", "second"])
        )
    else:
        monkeypatch.setattr(
            owner_queries,
            "fetch_assessment_source_fingerprint",
            AsyncMock(side_effect=["first", "second"]),
        )
    monkeypatch.setattr(owner_assessment, "_build", AsyncMock(return_value=confirmed_snapshot()))
    result = await owner_assessment.get_owner_assessment(None, organization_id="tenant")
    assert result.warehouse_status == "unavailable"
    assert result.summary.verified_current_count == 0
    assert result.rows[0]["sale_anchor_key"] is None
    assert values == {}
    assert cache.set.await_count == 0


async def test_simultaneous_requests_build_once_per_tenant(monkeypatch):
    import asyncio

    install_assessment_cache(monkeypatch)

    async def build(*args, **kwargs):
        await asyncio.sleep(0.01)
        return confirmed_snapshot()

    builds = AsyncMock(side_effect=build)
    monkeypatch.setattr(owner_assessment, "_build", builds)
    first, second = await asyncio.gather(
        owner_assessment.get_owner_assessment(None, organization_id="tenant"),
        owner_assessment.get_owner_assessment(None, organization_id="tenant"),
    )
    assert first is second
    assert builds.await_count == 1


def test_fast_cache_codec_preserves_decimal_and_legacy_json_wire():
    import base64
    import json
    import zlib
    from decimal import Decimal

    observed = confirmed_snapshot()
    observed.rows[0]["transaction_price_aed"] = Decimal("123456.50")
    observed.cached_at = datetime.now(timezone.utc)
    payload = owner_assessment._encode(observed)
    legacy = json.loads(zlib.decompress(base64.b64decode(payload)))
    assert legacy["rows"][0]["transaction_price_aed"] == 123456.5
    restored = owner_assessment._decode(
        base64.b64encode(zlib.compress(json.dumps(legacy).encode())).decode()
    )
    assert restored.rows[0]["transaction_date"] == observed.rows[0]["transaction_date"]
    assert restored.rows[0]["property_identity"] == observed.rows[0]["property_identity"]
    assert restored.cached_at == observed.cached_at


@pytest.mark.parametrize("broken", ["missing", "mutating", "view"])
async def test_physical_fingerprint_requires_both_stable_warehouse_inputs(monkeypatch, broken):
    from app.crm import owner_queries

    metadata = [
        {"name": name, "uuid": name, "engine": "MergeTree", "parts": [], "pending": 0}
        for name in ["analytics_building_keys", "dxbi_sales_unit_events"]
    ]
    if broken == "missing":
        metadata.pop()
    elif broken == "mutating":
        metadata[0]["pending"] = 1
    else:
        metadata[0]["engine"] = "View"
    monkeypatch.setattr(owner_queries, "query", AsyncMock(return_value=metadata))
    with pytest.raises(RuntimeError, match="missing or mutating"):
        await fetch_assessment_source_fingerprint()


async def test_unchanged_evidence_reuses_available_snapshot_past_local_expiry(monkeypatch):
    import time

    install_assessment_cache(monkeypatch)
    build = AsyncMock(return_value=confirmed_snapshot())
    monkeypatch.setattr(owner_assessment, "_build", build)
    first = await owner_assessment.get_owner_assessment(None, organization_id="tenant")
    original_capture = first.checked_at
    original_cache_time = first.cached_at
    key, _, snapshot_value = owner_assessment._recent
    monkeypatch.setattr(owner_assessment, "_recent", (key, time.monotonic() - 1, snapshot_value))
    second = await owner_assessment.get_owner_assessment(None, organization_id="tenant")
    assert second is first
    assert build.await_count == 1
    assert second.checked_at == original_capture
    assert second.cached_at == original_cache_time


def matched_party(role="Buyer", name="Synthetic Buyer", outcome="matched_sale", **changes):
    from app.crm.owner_match_status import owner_match_evidence
    from app.crm.owner_matcher import MatchResult

    sale_event = {
        "family": "sale",
        "event_key": "k",
        "event_date": "2024-01-10",
        "amount": 1000000,
        "unit_number": "602",
        "building_name": "Aspect Tower",
    }
    verdict = MatchResult(outcome, ("aspecttower", "602"), sale_event, ["unit 602"])  # type: ignore[arg-type]
    return contact(
        contact_name=name,
        party_role=role,
        evidence={
            "event_family": "sale",
            "owner_match": owner_match_evidence(verdict, later_sale_date=None),
        },
        **changes,
    )


def test_the_stored_property_first_verdict_decides_the_assessed_event_and_is_listed_on_the_row():
    result = snapshot([matched_party()], [])  # the legacy registry lookup found no sale at all
    (item,) = result.rows
    assert item["assessed_status"] == "verified_current_owner"
    assert (item["match_outcome"], item["match_colour"]) == ("matched_sale", "green")
    assert "evidence" not in item


def test_a_lender_row_reports_the_final_outcome_not_the_matchers_raw_one():
    lender = matched_party(
        name="Mashreq Bank PSC",
        outcome="matched_sale_via_mortgage",
        procedure_type="Mortgage Registration",
    )
    (item,) = snapshot([lender], []).rows
    assert (item["match_outcome"], item["match_colour"]) == ("lender", "grey")
    assert item["assessed_status"] != "verified_current_owner"


def test_a_row_with_no_verdict_lists_no_match_fields():
    (item,) = snapshot([contact()], []).rows
    assert item["match_outcome"] is None and item["match_colour"] is None
