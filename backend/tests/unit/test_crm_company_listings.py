from datetime import datetime, timezone

import pytest

from app.crm import company_listings


@pytest.mark.asyncio
async def test_agent_inventory_carries_each_agents_phone_and_email(monkeypatch):
    seen: dict[str, str] = {}

    async def fake_query(sql, parameters):
        seen["sql"] = sql
        return [
            {
                "agent_id": "a1",
                "display_name": "Navi Singh",
                "listings": 50,
                "agent_phone": "+971500000001",
                "agent_email": "navi@example.com",
            },
            # Agents without published contacts still list, with no phone or email.
            {
                "agent_id": None,
                "display_name": "Agent not listed",
                "listings": 2,
                "agent_phone": "",
                "agent_email": "",
            },
        ]

    monkeypatch.setattr(company_listings, "query", fake_query)
    agents = await company_listings._agent_inventory("broker-1")

    assert agents[0].phone == "+971500000001"
    assert agents[0].email == "navi@example.com"
    assert agents[1].phone is None and agents[1].email is None
    # Property Finder publishes the agent's number in the listing's contact options, not agent_json.
    assert "contact_options" in seen["sql"]


@pytest.mark.asyncio
async def test_listing_search_matches_title_building_or_area_and_counts_matches(monkeypatch):
    calls: list[tuple[str, dict]] = []

    async def fake_query(sql, parameters):
        calls.append((sql, parameters))
        return [{"matched_total": 12}]

    monkeypatch.setattr(company_listings, "query", fake_query)
    rows = await company_listings._company_rows(
        "broker-1", limit=100, offset=0, search="  marina gate "
    )

    sql, parameters = calls[0]
    assert parameters["search"] == "marina gate"
    for column in ("title", "building_name", "area_name"):
        assert column in sql.split("WHERE", 1)[1]
    # The total shown while searching is the number of matching listings, not the company's.
    assert rows[0]["matched_total"] == 12 and "count() OVER ()" in sql


class _FakeSession:
    def __init__(self):
        self.deleted: list[object] = []
        self.statements: list[object] = []
        self.committed = False

    async def delete(self, record):
        self.deleted.append(record)

    async def exec(self, statement):
        self.statements.append(statement)

    async def commit(self):
        self.committed = True


@pytest.mark.asyncio
async def test_clearing_the_source_stops_company_matching_and_reruns_buyer_matches(monkeypatch):
    record = object()

    async def selected(db, organization_id):
        return record

    monkeypatch.setattr(company_listings, "_selected_source", selected)
    db = _FakeSession()
    await company_listings.clear_company_source(db, organization_id="org")

    assert db.deleted == [record] and db.committed
    # Buyers' stored matches re-run, so company listings drop out of them.
    assert len(db.statements) == 1


@pytest.mark.asyncio
async def test_clearing_with_no_source_does_nothing(monkeypatch):
    async def selected(db, organization_id):
        return None

    monkeypatch.setattr(company_listings, "_selected_source", selected)
    db = _FakeSession()
    await company_listings.clear_company_source(db, organization_id="org")
    assert db.deleted == [] and db.statements == [] and not db.committed


def _pf_row(broker_id: str = "B1") -> dict:
    return {
        "property_key": "pk-123",
        "listing_id": "123",
        "title": "Marina Gate 2BR",
        "mode": "sale",
        "property_type": "Apartment",
        "bedrooms": "2",
        "size_sqft": 1200,
        "price_aed": 2500000,
        "area_name": "Dubai Marina",
        "building_name": "Marina Gate",
        "broker_id": broker_id,
        "broker_name": "Big Firm",
        "agent_name": "Navi Singh",
        "agent_phone": "",
        "listed_at": None,
    }


def _source(broker_id: str):
    from app.crm.models import CrmCompanyListingSource

    return CrmCompanyListingSource(
        organization_id="org-1",
        broker_id=broker_id,
        broker_name="Big Firm",
        selected_by_user_id="u",
    )


def _patch_detail(monkeypatch, rows, source):
    seen: dict = {}

    async def fake_query(sql, parameters):
        seen["sql"], seen["parameters"] = sql, parameters
        return rows

    async def fake_source(db, organization_id):
        return source

    monkeypatch.setattr(company_listings, "query", fake_query)
    monkeypatch.setattr(company_listings, "_selected_source", fake_source)
    return seen


@pytest.mark.asyncio
async def test_listing_of_the_connected_company_is_managed(monkeypatch):
    seen = _patch_detail(monkeypatch, [_pf_row("B1")], _source("B1"))

    detail = await company_listings.get_company_listing(None, "org-1", "123")

    assert (detail.reference, detail.listing_key, detail.managed) == ("PF-123", "123", True)
    assert (detail.broker_id, detail.broker_name) == ("B1", "Big Firm")
    # The listing is looked up by its Property Finder id, never by its title.
    assert seen["parameters"]["listing_key"] == "123"


@pytest.mark.asyncio
async def test_another_companys_listing_is_visible_but_not_managed(monkeypatch):
    # Browsing another company is allowed; its private documents are not.
    _patch_detail(monkeypatch, [_pf_row("B2")], _source("B1"))

    detail = await company_listings.get_company_listing(None, "org-1", "123")

    assert detail.managed is False


@pytest.mark.asyncio
async def test_listing_is_not_managed_without_a_connected_company(monkeypatch):
    _patch_detail(monkeypatch, [_pf_row("B1")], None)

    assert (await company_listings.get_company_listing(None, "org-1", "123")).managed is False


@pytest.mark.asyncio
async def test_listing_no_longer_published_returns_none(monkeypatch):
    _patch_detail(monkeypatch, [], _source("B1"))

    assert await company_listings.get_company_listing(None, "org-1", "123") is None


def _keys_row(key: str, broker_id: str = "B1") -> dict:
    return {
        **_pf_row(broker_id),
        "listing_id": key,
        "images_json": '[{"medium_url": "https://img/a.jpg"}, {"nope": 1}, {"url": "https://img/b.jpg"}]',
        "description": " Sea view ",
        "scraped_at_dt": datetime(2026, 11, 10, 8, 0),
    }


@pytest.mark.asyncio
async def test_listings_by_keys_single_query(monkeypatch):
    calls = []

    async def fake_query(sql, parameters):
        calls.append((sql, parameters))
        return [_keys_row("1"), _keys_row("3", "B2")]

    async def fake_source(db, organization_id):
        return _source("B1")

    monkeypatch.setattr(company_listings, "query", fake_query)
    monkeypatch.setattr(company_listings, "_selected_source", fake_source)
    found = await company_listings.listings_by_keys(None, "org", ["1", "2", "3", "1"])

    assert len(calls) == 1
    assert "listing_id IN {keys:Array(String)}" in calls[0][0] and "is_available = 1" in calls[0][0]
    assert calls[0][1] == {"keys": ["1", "2", "3"]}
    assert set(found) == {"1", "3"}  # "2" is not published
    assert found["1"].managed and not found["3"].managed
    assert found["1"].photos == ["https://img/a.jpg", "https://img/b.jpg"]
    assert found["1"].description == "Sea view"
    assert found["1"].updated_at == datetime(2026, 11, 10, 8, 0, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_listings_by_keys_empty_input_skips_query(monkeypatch):
    async def fail(*args, **kwargs):
        raise AssertionError("no query expected")

    monkeypatch.setattr(company_listings, "query", fail)
    assert await company_listings.listings_by_keys(None, "org", []) == {}
