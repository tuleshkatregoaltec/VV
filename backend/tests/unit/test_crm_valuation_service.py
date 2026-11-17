"""Valuing stored owner claims: registry join, stale-value clearing and import scope."""

from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.crm import owner_queries, owner_repository, valuation_queries, valuation_service
from app.crm.import_models import CrmPropertyContactClaim

TODAY = date(2026, 11, 5)
NOW = datetime(2026, 11, 5, tzinfo=timezone.utc)
SOLD = date(2023, 3, 1)


def _claim(claim_id: int, *, status="verified_current_owner", import_id=1, unit="187", **extra):
    return CrmPropertyContactClaim(
        id=claim_id,
        organization_id="org",
        import_id=import_id,
        list_id=1,
        source_sheet="Owners",
        source_row_number=claim_id,
        row_fingerprint=f"row-{claim_id}",
        owner_key=f"owner-{claim_id}",
        property_key=f"p-{claim_id}",
        contact_name="Owner Example",
        ownership_status=status,
        confidence_score=90,
        match_reason="Registry evidence",
        area_name="Town Square",
        building_name="Reem Townhouses",
        unit_number=unit,
        latest_sale_date=SOLD,
        latest_sale_price_aed=1_600_000,
        created_at=NOW,
        updated_at=NOW,
        **extra,
    )


def _sale(unit="187", building="reem", size=1000.0, beds="3 Bed", status="Offplan"):
    return {
        "market_status": status,
        "transaction_date": SOLD,
        "sale_amount_aed": 1_600_000,
        "unit_key": unit,
        "building_key": building,
        "area_key": "townsquare",
        "property_type": "Villa",
        "bedrooms": beds,
        "size_sqft": size,
    }


class _Db:
    def add(self, record):
        return None

    async def commit(self):
        return None


@pytest.fixture
def world(monkeypatch):
    state = {"claims": [], "sales": [], "stats": [], "quarters": [], "import_id": "unset"}

    async def claims(db, organization_id, import_id=None, *, generation=None):
        state["import_id"] = import_id
        return [
            (
                c,
                {
                    "assessed_status": c.ownership_status,
                    "latest_sale_date": c.latest_sale_date.isoformat()
                    if c.latest_sale_date
                    else None,
                    "latest_sale_price_aed": c.latest_sale_price_aed,
                    "unit_number": c.unit_number,
                    **state.get("assessment", {}).get(c.id, {}),
                },
            )
            for c in state["claims"]
            if import_id is None or c.import_id == import_id
        ]

    async def sales(parameters):
        return state["sales"]

    async def stats(building_keys, area_keys, since, until, ready_only=True):
        state.setdefault("ready_calls", []).append(ready_only)
        return state["ready_stats" if ready_only and "ready_stats" in state else "stats"]

    async def quarters(area_keys, property_types):
        return state["quarters"]

    monkeypatch.setattr(
        valuation_service,
        "open_store",
        AsyncMock(return_value=SimpleNamespace(state=SimpleNamespace(generation=1))),
    )
    monkeypatch.setattr(owner_repository, "list_claims_for_valuation", claims)
    monkeypatch.setattr(owner_queries, "fetch_owner_property_signatures", sales)
    monkeypatch.setattr(valuation_queries, "fetch_comparable_stats", stats)
    monkeypatch.setattr(valuation_queries, "fetch_area_psf_by_quarter", quarters)
    return state


def _building_stats(count=8, p50=2000.0):
    return {
        "level": "building_type_beds",
        "building_key": "reem",
        "area_key": "",
        "property_type": "Villa",
        "bedrooms": "3 Bed",
        "count": count,
        "psf": [p50 - 200, p50, p50 + 200],
    }


async def _run(import_id=None):
    return await valuation_service.value_owner_claims(
        _Db(), organization_id="org", import_id=import_id, valued_at=TODAY
    )


async def test_values_current_owner_from_unique_registry_row(world):
    claim = _claim(1)
    world["claims"] = [claim]
    world["sales"] = [_sale()]
    world["stats"] = [_building_stats()]
    summary = await _run()
    assert claim.estimated_value_aed == 2_000_000
    assert (claim.estimated_value_low_aed, claim.estimated_value_high_aed) == (1_800_000, 2_200_000)
    assert claim.valuation["confidence"] == "high"
    assert claim.valuation["bedrooms"] == "3 Bed"
    assert summary.valued == 1


async def test_ambiguous_signature_is_skipped(world):
    # Same date, price and unit number in two buildings: guessing would value the wrong home.
    claim = _claim(1)
    world["claims"] = [claim]
    world["sales"] = [_sale(building="reem"), _sale(building="zahra")]
    world["stats"] = [_building_stats()]
    summary = await _run()
    assert claim.estimated_value_aed is None
    assert summary.skipped == {"ambiguous_registry_match": 1}


async def test_former_owner_is_not_valued_and_stale_value_cleared(world):
    claim = _claim(1, status="former_owner", estimated_value_aed=2_000_000)
    world["claims"] = [claim]
    await _run()
    assert claim.estimated_value_aed is None
    assert claim.estimated_value_low_aed is None
    assert claim.valuation["status"] == "not_current_owner"


async def test_missing_registry_size_uses_index_not_source_size(world):
    claim = _claim(1, evidence={"source_fields": {"size_sqft": "174.8"}})
    world["claims"] = [claim]
    world["sales"] = [_sale(size=0)]
    world["stats"] = [
        _building_stats(),
        {
            "level": "area_type",
            "building_key": "",
            "area_key": "townsquare",
            "property_type": "Villa",
            "bedrooms": "",
            "count": 180,
            "psf": [1250.0, 1371.0, 1495.0],
        },
    ]
    world["quarters"] = [
        {
            "area_key": "townsquare",
            "property_type": "Villa",
            "quarter": date(2023, 1, 1),
            "count": 90,
            "p50": 914.0,
        }
    ]
    await _run()
    assert claim.valuation["method"] == "indexed_purchase"
    assert claim.estimated_value_aed == 2_400_000  # 1.6M x 1371 / 914
    assert "size_sqft" not in claim.valuation


async def test_import_scope_only_touches_that_import(world):
    one, two = _claim(1, import_id=1), _claim(2, import_id=2, unit="188")
    world["claims"] = [one, two]
    world["sales"] = [_sale(), _sale(unit="188")]
    world["stats"] = [_building_stats()]
    await _run(import_id=1)
    assert world["import_id"] == 1
    assert one.estimated_value_aed == 2_000_000
    assert two.estimated_value_aed is None


def test_stats_row_carries_price_quartiles():
    stats = valuation_service._stats(
        {"count": 6, "psf": [900.0, 935.0, 980.0], "price": [1_950_000.0, 2_100_000.0, 2_250_000.0]}
    )
    assert (stats.price_p25, stats.price_p50, stats.price_p75) == (1_950_000, 2_100_000, 2_250_000)


async def test_ready_home_is_valued_from_ready_sales_only(world):
    ready, offplan = _claim(1), _claim(2, unit="188")
    world["claims"] = [ready, offplan]
    world["sales"] = [_sale(status="Ready"), _sale(unit="188", status="Offplan")]
    world["stats"] = [_building_stats(p50=3000.0)]  # all sales, off-plan premium included
    world["ready_stats"] = [_building_stats(p50=2000.0)]
    await _run()
    assert ready.estimated_value_aed == 2_000_000
    assert offplan.estimated_value_aed == 3_000_000
    assert sorted(world["ready_calls"]) == [False, True]


async def test_current_assessment_overrides_stale_import_status_and_sale_identity(world):
    former = _claim(1, estimated_value_aed=9_000_000)
    current = _claim(2, status="unit_linked_unverified", unit="wrong-source-unit")
    world["claims"] = [former, current]
    world["assessment"] = {
        1: {"assessed_status": "former_owner"},
        2: {"assessed_status": "verified_current_owner", "unit_number": "187"},
    }
    world["sales"] = [_sale()]
    world["stats"] = [_building_stats()]
    result = await _run()
    assert former.estimated_value_aed is None
    assert former.valuation["status"] == "not_current_owner"
    assert current.estimated_value_aed == 2_000_000
    assert current.ownership_status == "unit_linked_unverified"
    assert current.unit_number == "wrong-source-unit"
    assert result.considered == 1
