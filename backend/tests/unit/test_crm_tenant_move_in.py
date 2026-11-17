"""Tenant matching against the move-in date (client call, 3 Nov 2026).

A tenant needs a home free by the time they move in: a unit whose lease ends after the move-in
date is disqualified, and so is a listing whose description says it frees up later.
"""

from datetime import date, datetime, timedelta, timezone

import pytest

from app.crm import company_listings, match_repository, matching
from app.crm.assignment import AssignmentScope
from app.crm.import_models import CrmPropertyContactClaim
from app.crm.inbound_models import CrmInboundEnquiry
from app.listings.models import ListingCardResponse, ListingListResponse

# Matching now takes the caller's visibility scope (lead assignment). These tests are about timing
# and value matching, not visibility, so they run as an organization administrator, who sees all.
_ADMIN = AssignmentScope(
    organization_id="org",
    user_id="admin",
    organization_admin=True,
    supervised_team_ids=frozenset(),
    team_members={},
    member_team_ids=frozenset(),
)

JVC = "Jumeirah Village Circle"
NOW = datetime(2026, 11, 3, 9, 0, tzinfo=timezone.utc)


def _enquiry(intent: str = "rent", **criteria) -> CrmInboundEnquiry:
    return CrmInboundEnquiry(
        id=7,
        organization_id="org",
        contact_id=1,
        created_by_user_id="user",
        record_kind="opportunity",
        intent=intent,
        status="qualified",
        source="Property Finder",
        criteria={"locations": [JVC], "property_type": "Apartment", **criteria},
        enquiry_date=NOW,
        created_at=NOW,
        updated_at=NOW,
    )


def _unit(key: str, lease_end: date | None, rent: int = 110_000) -> dict:
    return {
        "unit_candidate_key": key,
        "building_name": "Binghatti Gate",
        "unit_number": key,
        "area_name": JVC,
        "property_type": "Apartment",
        "bedrooms": "2",
        "annual_rent_aed": rent,
        "matched_sale_price": 1_000_000,
        "lease_end": lease_end,
    }


def _owner(lease_end: date) -> CrmPropertyContactClaim:
    claim = CrmPropertyContactClaim(
        organization_id="org",
        import_id=1,
        list_id=1,
        source_sheet="Owners",
        source_row_number=1,
        row_fingerprint="row-1",
        owner_key="owner-1",
        property_key="p-1",
        contact_name="Maya Example",
        phone_primary="+971500000002",
        ownership_status="current",
        confidence_score=98,
        match_reason="Registry evidence",
        area_name=JVC,
        building_name="Binghatti Gate",
        unit_number="1204",
        property_type="Apartment",
        annual_rent_aed=110_000,
        lease_end=lease_end,
        created_at=NOW,
        updated_at=NOW,
    )
    return claim


def _listing(listing_id: str, age_days: int = 10) -> ListingCardResponse:
    return ListingCardResponse(
        listing_id=listing_id,
        listing_mode="rent",
        asset_class="residential",
        title="2BR in JVC",
        property_type="Apartment",
        price_value=110_000,
        price_period="yearly",
        bedrooms="2",
        area_name=JVC,
        listed_date=NOW - timedelta(days=age_days),
        listing_age_days=age_days,
    )


class _Db:
    async def commit(self):
        return None


@pytest.fixture
def world(monkeypatch):
    """A fake store and data sources; tests fill `units`, `owners`, `listings`, `descriptions`."""
    state = {
        "enquiry": None,
        "saved": [],
        "units": [],
        "owners": [],
        "listings": [],
        "descriptions": {},
        "move_by": "unset",
        "hidden_written": None,
        "anchor_written": None,
    }

    async def get_enquiry(db, key):
        # What the database holds: the brief plus any count refresh wrote beside it.
        enquiry = state["enquiry"]
        if state["hidden_written"] is None:
            return enquiry
        stored = {
            **enquiry.criteria,
            "_match_hidden_after": state["hidden_written"],
            "_match_move_in": state["anchor_written"],
        }
        return enquiry.model_copy(update={"criteria": stored})

    async def write_hidden(db, enquiry_id, hidden, *, move_in=None):
        state["hidden_written"] = hidden
        state["anchor_written"] = move_in.isoformat() if move_in else None

    async def noop(*args, **kwargs):
        return None

    async def owners(db, organization_id, locations, budget_band=None):
        return state["owners"]

    async def find_target(db, enquiry, target_key, target_type):
        return next(
            (
                m
                for m in state["saved"]
                if (m.target_key, m.target_type) == (target_key, target_type)
            ),
            None,
        )

    def save(db, record):
        if record.__class__.__name__ == "CrmInboundMatch" and record not in state["saved"]:
            state["saved"].append(record)

    async def mark_version(db, enquiry_id, version):
        for item in state["saved"]:
            item.algorithm_version = version

    async def by_score(db, enquiry_id):
        return sorted(state["saved"], key=lambda m: -m.score)

    async def units(area, property_type, move_by=None):
        state["move_by"] = move_by
        return state["units"]

    async def no_company(*args, **kwargs):
        return []

    async def freshness():
        return NOW, True

    async def no_catalog():
        return None

    async def listings(**kwargs):
        return ListingListResponse(
            listings=state["listings"], total=len(state["listings"]), limit=60, offset=0
        )

    async def descriptions(ids):
        return {i: state["descriptions"].get(i, "") for i in ids}

    monkeypatch.setattr(matching, "_utcnow", lambda: NOW)
    monkeypatch.setattr(match_repository, "get_crm_inbound_enquiry", get_enquiry)
    monkeypatch.setattr(match_repository, "mark_refreshable_matches_stale", noop)
    monkeypatch.setattr(match_repository, "find_owner_candidates", owners)
    monkeypatch.setattr(match_repository, "find_target_match", find_target)
    monkeypatch.setattr(match_repository, "save", save)
    monkeypatch.setattr(match_repository, "mark_algorithm_version", mark_version)
    monkeypatch.setattr(match_repository, "list_matches_by_score", by_score)
    monkeypatch.setattr(match_repository, "set_match_hidden_after", write_hidden)
    monkeypatch.setattr(company_listings, "find_matching_company_listings", no_company)
    monkeypatch.setattr(matching, "list_matching_rental_opportunities", units)
    monkeypatch.setattr(matching, "get_inventory_freshness", freshness)
    monkeypatch.setattr(matching, "get_catalog_freshness", no_catalog)
    monkeypatch.setattr(matching, "list_listings_from_clickhouse", listings)
    monkeypatch.setattr(matching, "get_listing_descriptions", descriptions)
    return state


async def _refresh(world, enquiry):
    world["enquiry"] = enquiry
    return await matching.refresh_inbound_matches(
        _Db(), enquiry_id=7, organization_id="org", scope=_ADMIN
    )


async def test_tenant_unit_with_lease_ending_after_move_in_is_disqualified(world):
    world["units"] = [_unit("A", date(2027, 1, 15)), _unit("B", date(2027, 3, 1))]
    res = await _refresh(world, _enquiry(budget_max_aed=120_000, move_in="2027-02-01"))
    assert [m.target_key for m in res.lanes["units"]] == ["A"]
    assert res.hidden_after == {"units": 1}
    assert res.move_in == date(2027, 2, 1)
    assert world["move_by"] == date(2027, 2, 1)
    assert "Lease ends 15 Jan 2027, before move-in 1 Feb 2027" in res.lanes["units"][0].reasons


async def test_unknown_lease_end_is_kept_for_review(world):
    world["units"] = [_unit("A", None)]
    res = await _refresh(world, _enquiry(budget_max_aed=120_000, move_in="2027-02-01"))
    assert "Lease end unknown, verify" in res.lanes["units"][0].reasons


async def test_tenant_without_move_in_matches_as_before(world):
    world["units"] = [_unit("A", date(2027, 1, 15)), _unit("B", date(2027, 3, 1))]
    res = await _refresh(world, _enquiry(budget_max_aed=120_000))
    assert sorted(m.target_key for m in res.lanes["units"]) == ["A", "B"]
    assert res.hidden_after == {}
    assert res.move_in is None
    assert world["move_by"] is None


async def test_buyer_is_never_timing_gated(world):
    world["units"] = [_unit("B", date(2027, 3, 1))]
    res = await _refresh(world, _enquiry("buy", budget_max_aed=1_100_000, move_in="2027-02-01"))
    assert [m.target_key for m in res.lanes["units"]] == ["B"]
    assert res.move_in is None
    assert world["move_by"] is None


async def test_owner_whose_lease_ends_after_move_in_is_disqualified(world):
    world["owners"] = [_owner(date(2027, 6, 1))]
    res = await _refresh(world, _enquiry(budget_max_aed=120_000, move_in="2027-02-01"))
    assert res.lanes["owners"] == []
    assert res.hidden_after == {"owners": 1}


async def test_owner_free_before_move_in_says_so(world):
    world["owners"] = [_owner(date(2027, 1, 20))]
    res = await _refresh(world, _enquiry(budget_max_aed=120_000, move_in="2027-02-01"))
    assert "Lease ends 20 Jan 2027, before move-in 1 Feb 2027" in res.lanes["owners"][0].reasons


async def test_portal_listing_available_after_move_in_is_disqualified(world):
    world["listings"] = [_listing("late"), _listing("soon")]
    world["descriptions"] = {
        "late": "Lovely 2BR. Available from 1st March 2027.",
        "soon": "Available from 15th Jan, 4 cheques",
    }
    res = await _refresh(world, _enquiry(budget_max_aed=120_000, move_in="2027-02-01"))
    assert [m.target_key for m in res.lanes["listings"]] == ["soon"]
    assert res.hidden_after == {"listings": 1}
    assert "Available from 15 Jan 2027" in res.lanes["listings"][0].reasons


async def test_old_available_now_listing_is_kept_with_a_caveat(world):
    # Property Finder listings can be months old: kept, but the agent is told to confirm.
    world["listings"] = [_listing("old", age_days=120)]
    world["descriptions"] = {"old": "Vacant, ready to move in"}
    res = await _refresh(world, _enquiry(budget_max_aed=120_000, move_in="2027-02-01"))
    reasons = res.lanes["listings"][0].reasons
    assert "Listed 120 days ago, confirm it's still available" in reasons


async def test_past_move_in_keeps_only_ended_leases(world):
    world["units"] = [_unit("ended", date(2026, 8, 1)), _unit("running", date(2026, 12, 1))]
    res = await _refresh(world, _enquiry(budget_max_aed=120_000, move_in="2026-09-01"))
    assert [m.target_key for m in res.lanes["units"]] == ["ended"]
    assert res.hidden_after == {"units": 1}


async def test_hidden_count_survives_a_plain_load_without_rerunning(world, monkeypatch):
    # Opening the Matches tab again must still say how many free up too late, without
    # re-running matching (saving the count must not make the stored list look out of date).
    world["units"] = [_unit("A", date(2027, 1, 15)), _unit("B", date(2027, 3, 1))]
    enquiry = _enquiry(budget_max_aed=120_000, move_in="2027-02-01")
    await _refresh(world, enquiry)

    async def no_rerun(*args, **kwargs):
        raise AssertionError("matching re-ran")

    monkeypatch.setattr(matching, "refresh_inbound_matches", no_rerun)
    res = await matching.get_inbound_matches(_Db(), 7, "org", scope=_ADMIN)
    assert [m.target_key for m in res.lanes["units"]] == ["A"]
    assert res.hidden_after == {"units": 1}
    assert res.move_in == date(2027, 2, 1)


def test_stored_matches_rerun_after_the_unit_number_fix():
    # Stored titles from v8 still read "Unit unresolved"; v9 makes every lead re-match once.
    assert matching._ALGORITHM_VERSION == "inbound-v11"


async def test_listing_age_is_counted_to_today_not_to_the_last_scrape(world, monkeypatch):
    # The catalog's listing_age_days is the age when scraped; a listing posted 200 days ago that
    # was 5 days old at the last scrape is still months old for the tenant.
    monkeypatch.setattr(matching, "_utcnow", lambda: NOW)
    stale = _listing("old", age_days=5)
    stale.listed_date = NOW - timedelta(days=200)
    world["listings"] = [stale]
    world["descriptions"] = {"old": "Vacant"}
    res = await _refresh(world, _enquiry(budget_max_aed=120_000, move_in="2027-02-01"))
    assert "Listed 200 days ago, confirm it's still available" in res.lanes["listings"][0].reasons


async def test_saving_the_count_never_rewrites_the_brief(world):
    # Refresh takes seconds; an agent may edit the brief meanwhile. Writing the whole criteria
    # back from the copy loaded at the start would undo that edit, so only the count is written.
    world["units"] = [_unit("A", date(2027, 1, 15)), _unit("B", date(2027, 3, 1))]
    enquiry = _enquiry(budget_max_aed=120_000, move_in="2027-02-01")
    before = dict(enquiry.criteria)
    await _refresh(world, enquiry)
    assert enquiry.criteria == before
    assert world["hidden_written"] == {"units": 1}


async def test_tenant_unit_shows_the_lease_unit_when_no_sale_is_matched(world):
    # Client (3 Nov): "Unit unresolved" looked wrong; the lease itself records the unit number,
    # only the sale match was missing.
    row = {**_unit("A", date(2027, 1, 15)), "unit_number": "", "lease_unit_number": "805"}
    world["units"] = [row]
    res = await _refresh(world, _enquiry(budget_max_aed=120_000, move_in="2027-02-01"))
    assert res.lanes["units"][0].title == "Binghatti Gate · Unit 805"


async def test_buyer_unit_titles_are_unchanged(world):
    # Buyer and seller matching must stay exactly as it was.
    row = {**_unit("B", date(2027, 3, 1)), "unit_number": "", "lease_unit_number": "805"}
    world["units"] = [row]
    res = await _refresh(world, _enquiry("buy", budget_max_aed=1_100_000))
    assert res.lanes["units"][0].title == "Binghatti Gate · Unit unresolved"


async def test_same_owner_keeps_the_eligible_lower_confidence_property(world):
    late = _owner(date(2027, 3, 1))
    eligible = late.model_copy(
        update={"confidence_score": 95, "lease_end": date(2027, 1, 1), "unit_number": "1205"}
    )
    world["owners"] = [late, eligible]
    result = await _refresh(world, _enquiry(budget_max_aed=120_000, move_in="2027-02-01"))
    assert len(result.lanes["owners"]) == 1
    assert result.lanes["owners"][0].snapshot["unit_number"] == "1205"


async def test_relative_asap_matches_refresh_when_the_resolved_date_changes(world, monkeypatch):
    world["units"] = [_unit("A", date(2026, 11, 2)), _unit("B", date(2026, 11, 4))]
    await _refresh(world, _enquiry(budget_max_aed=120_000, move_in="ASAP"))
    assert world["anchor_written"] == "2026-11-03"
    monkeypatch.setattr(matching, "_utcnow", lambda: NOW + timedelta(days=1))
    result = await matching.get_inbound_matches(_Db(), 7, "org", scope=_ADMIN)
    assert {match.target_key for match in result.lanes["units"]} == {"A", "B"}
    assert result.move_in == date(2026, 11, 4)
    assert result.hidden_after == {}
    assert world["anchor_written"] == "2026-11-04"
