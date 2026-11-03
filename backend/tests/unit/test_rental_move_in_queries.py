import asyncio
from datetime import date

from app.crm import opportunities, opportunity_queries
from app.listings import queries as listing_queries
from app.listings import service as listing_service


def _capture(monkeypatch, module, rows):
    calls = []

    async def query(sql, params):
        calls.append((sql, params))
        return rows

    monkeypatch.setattr(module, "query", query)
    return calls


def test_move_in_caps_the_lease_window(monkeypatch):
    # Leases up to 90 days past move-in are fetched so matching can count what frees up too late.
    calls = _capture(monkeypatch, opportunity_queries, [])
    asyncio.run(opportunities.list_matching_rental_opportunities("JVC", "", date(2027, 1, 31)))
    sql, params = calls[0]
    assert params["move_by"] == date(2027, 1, 31)
    assert "ifNull({move_by:Nullable(Date)}, today()) + 90" in sql


def test_lease_unit_number_is_returned_beside_the_sale_match_unit(monkeypatch):
    # The lease records its own unit; the existing unit_number (from the sale match) is kept as is.
    calls = _capture(monkeypatch, opportunity_queries, [])
    asyncio.run(opportunities.list_matching_rental_opportunities("JVC", ""))
    sql = calls[0][0]
    assert "c.unit_number AS lease_unit_number" in sql
    assert "m.unit_number," in sql


def test_without_move_in_the_window_stays_90_days(monkeypatch):
    calls = _capture(monkeypatch, opportunity_queries, [])
    asyncio.run(opportunities.list_matching_rental_opportunities("JVC", ""))
    sql, params = calls[0]
    assert params["move_by"] is None
    assert "ifNull({move_by:Nullable(Date)}, today()) + 90" in sql


def test_descriptions_are_keyed_by_listing_id(monkeypatch):
    calls = _capture(
        monkeypatch,
        listing_queries,
        [
            {"listing_id": "a", "description": "Available from 1 Dec"},
            {"listing_id": "b", "description": ""},
        ],
    )
    result = asyncio.run(listing_service.get_listing_descriptions(["a", "b"]))
    assert result == {"a": "Available from 1 Dec", "b": ""}
    assert calls[0][1] == {"ids": ["a", "b"]}


def test_no_listing_ids_means_no_query(monkeypatch):
    calls = _capture(monkeypatch, listing_queries, [])
    assert asyncio.run(listing_service.get_listing_descriptions([])) == {}
    assert calls == []
