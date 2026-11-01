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
