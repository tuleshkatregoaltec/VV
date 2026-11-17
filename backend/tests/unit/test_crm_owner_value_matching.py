"""Buyers are matched to owners on today's estimated value (client call, 5 Nov 2026).

The owner file only knows what each owner paid, often years ago. Prices have risen since, so
matching on the purchase price hides owners whose home now fits the buyer's budget.
"""

from datetime import date, datetime, timezone

import pytest

from app.crm import company_listings, match_repository, matching
from app.crm.import_models import CrmPropertyContactClaim
from app.crm.inbound_models import CrmInboundEnquiry
from app.crm.matching_policy import _owner_budget_band, _owner_value_fit
from app.listings.models import ListingListResponse

NOW = datetime(2026, 11, 5, 9, 0, tzinfo=timezone.utc)
AREA = "Town Square"


def test_estimate_inside_budget_scores_15():
    fit = _owner_value_fit(
        {"budget_min_aed": 2_000_000, "budget_max_aed": 2_500_000}, 2_400_000, 2_200_000, 2_600_000
    )
    assert fit == (15, "Est. value AED 2,400,000, within budget")


def test_range_overlap_scores_9():
    # The buyer tops out at 2.0M; the home is valued 2.3M but could sell from 2.1M.
    fit = _owner_value_fit({"budget_max_aed": 2_000_000}, 2_300_000, 2_100_000, 2_500_000)
    assert fit == (9, "Est. range AED 2,100,000–2,500,000 overlaps budget")


def test_outside_range_scores_0():
    fit = _owner_value_fit({"budget_max_aed": 2_000_000}, 4_000_000, 3_600_000, 4_400_000)
    assert fit == (0, "Outside budget")


def test_band_with_only_min_or_only_max():
    low, high = _owner_budget_band({"budget_min_aed": 1_000_000})
    assert low == 900_000 and high >= 10**12
    assert _owner_budget_band({"budget_max_aed": 2_000_000}) == (0, 2_200_000)
    assert _owner_budget_band({}) is None


def _enquiry(intent="buy", strict=None, **criteria) -> CrmInboundEnquiry:
    return CrmInboundEnquiry(
        id=9,
        organization_id="org",
        contact_id=1,
        created_by_user_id="user",
        record_kind="opportunity",
        intent=intent,
        status="qualified",
        source="Manual",
        criteria={"locations": [AREA], "property_type": "Villa", **criteria},
        strict_fields=strict or [],
        enquiry_date=NOW,
        created_at=NOW,
        updated_at=NOW,
    )


def _claim(*, paid=1_700_000, estimate=None, beds=None, rent=None) -> CrmPropertyContactClaim:
    return CrmPropertyContactClaim(
        organization_id="org",
        import_id=1,
        list_id=1,
        source_sheet="Owners",
        source_row_number=1,
        row_fingerprint="row-1",
        owner_key="owner-1",
        property_key="p-1",
        contact_name="Owner Example",
        phone_primary="+971500000001",
        ownership_status="verified_current_owner",
        confidence_score=95,
        match_reason="Registry evidence",
        area_name=AREA,
        building_name="Reem Townhouses",
        unit_number="187",
        property_type="Villa",
        latest_sale_date=date(2022, 3, 1),
        latest_sale_price_aed=paid,
        annual_rent_aed=rent,
        estimated_value_aed=estimate,
        estimated_value_low_aed=estimate and estimate - 200_000,
        estimated_value_high_aed=estimate and estimate + 200_000,
        valuation={"bedrooms": beds, "confidence": "high"} if beds or estimate else {},
        created_at=NOW,
        updated_at=NOW,
    )


class _Db:
    async def commit(self):
        return None


@pytest.fixture
def world(monkeypatch):
    state = {"enquiry": None, "saved": [], "owners": [], "band": "unset"}

    async def get_enquiry(db, key):
        return state["enquiry"]

    async def noop(*args, **kwargs):
        return None

    async def owners(db, organization_id, locations, budget_band=None):
        state["band"] = budget_band
        return state["owners"]

    async def find_target(db, enquiry, target_key, target_type):
        return next((m for m in state["saved"] if m.target_key == target_key), None)

    def save(db, record):
        if record.__class__.__name__ == "CrmInboundMatch" and record not in state["saved"]:
            state["saved"].append(record)

    async def by_score(db, enquiry_id):
        return state["saved"]

    async def empty(*args, **kwargs):
        return []

    async def freshness():
        return NOW, True

    async def listings(**kwargs):
        return ListingListResponse(listings=[], total=0, limit=60, offset=0)

    monkeypatch.setattr(matching, "_utcnow", lambda: NOW)
    monkeypatch.setattr(match_repository, "get_crm_inbound_enquiry", get_enquiry)
    monkeypatch.setattr(match_repository, "mark_refreshable_matches_stale", noop)
    monkeypatch.setattr(match_repository, "find_owner_candidates", owners)
    monkeypatch.setattr(match_repository, "find_target_match", find_target)
    monkeypatch.setattr(match_repository, "save", save)
    monkeypatch.setattr(match_repository, "mark_algorithm_version", noop)
    monkeypatch.setattr(match_repository, "list_matches_by_score", by_score)
    monkeypatch.setattr(match_repository, "set_match_hidden_after", noop)
    monkeypatch.setattr(match_repository, "list_reverse_demand", empty)
    monkeypatch.setattr(company_listings, "find_matching_company_listings", empty)
    monkeypatch.setattr(matching, "list_matching_rental_opportunities", empty)
    monkeypatch.setattr(matching, "list_matching_projects", empty, raising=False)
    monkeypatch.setattr(matching, "get_inventory_freshness", freshness)
    monkeypatch.setattr(matching, "get_catalog_freshness", noop)
    monkeypatch.setattr(matching, "list_listings_from_clickhouse", listings)
    monkeypatch.setattr(matching, "get_listing_descriptions", lambda ids: noop())
    return state


async def _refresh(world, enquiry):
    world["enquiry"] = enquiry
    response = await matching.refresh_inbound_matches(_Db(), enquiry_id=9, organization_id="org")
    return response.lanes.get("owners", [])


async def test_stale_purchase_price_no_longer_hides_owner(world):
    # Paid 1.7M in 2022, worth 2.6M today: squarely in a 2.5M-3.0M buyer's range.
    world["owners"] = [_claim(paid=1_700_000, estimate=2_600_000)]
    owners = await _refresh(world, _enquiry(budget_min_aed=2_500_000, budget_max_aed=3_000_000))
    assert len(owners) == 1
    assert "Est. value AED 2,600,000, within budget" in owners[0].reasons
    assert "Est. AED 2,600,000" in owners[0].subtitle
    assert owners[0].snapshot["estimated_value_aed"] == 2_600_000
    assert world["band"] == (2_250_000, 3_300_000)


async def test_strict_bedrooms_excludes_owner_with_known_mismatch(world):
    world["owners"] = [_claim(estimate=2_600_000, beds="1 Bed")]
    owners = await _refresh(
        world,
        _enquiry(strict=["bedrooms_min"], bedrooms_min=3, budget_max_aed=3_000_000),
    )
    assert owners == []


async def test_strict_bedrooms_keeps_owner_with_unknown_bedrooms(world):
    world["owners"] = [_claim(estimate=2_600_000)]
    owners = await _refresh(
        world,
        _enquiry(strict=["bedrooms_min"], bedrooms_min=3, budget_max_aed=3_000_000),
    )
    assert len(owners) == 1


async def test_no_estimate_falls_back_with_label(world):
    world["owners"] = [_claim(paid=2_600_000, estimate=None)]
    owners = await _refresh(world, _enquiry(budget_max_aed=3_000_000))
    assert len(owners) == 1
    assert "Within stated budget (last sale, no estimate)" in owners[0].reasons


async def test_rent_intent_unchanged(world):
    world["owners"] = [_claim(estimate=2_600_000, rent=150_000)]
    owners = await _refresh(world, _enquiry(intent="rent", budget_max_aed=160_000))
    assert world["band"] is None
    assert "Within stated budget" in owners[0].reasons
