"""A lead, saved lead or page of leads is looked up by key, not by ranking all of Dubai.

Live, /leads/{id} ranked every lease (2.9M rows, 1.7 GiB, ~6 s) before filtering to one event
key, so even an unknown id took 6.5 s and a whole admission slot to answer 404.
"""

from crm_rental_sql import CANDIDATE_SOURCE, LIVE_LEAD_CTE

from app.crm import opportunity_queries


async def _capture(monkeypatch, rows):
    calls = []

    async def query(sql, params=None):
        calls.append((sql, dict(params or {})))
        if "system.tables" in sql:
            return [{"tables": 0}]
        return rows

    monkeypatch.setattr(opportunity_queries, "query", query)
    return calls


def _narrowed(sql: str) -> bool:
    # The ranking is still the canonical one; only its candidate source is narrowed.
    return CANDIDATE_SOURCE not in sql and LIVE_LEAD_CTE.split(CANDIDATE_SOURCE)[1] in sql


async def test_lead_detail_ranks_only_the_leases_that_can_share_its_unit(monkeypatch):
    calls = await _capture(monkeypatch, [{"event_key": "e1"}])
    rows = await opportunity_queries.fetch_lead(
        {"as_of": "2026-11-15", "expired_days": 3650, "lead_id": "e1"}
    )
    assert rows == [{"event_key": "e1"}]
    sql, params = calls[0]
    assert _narrowed(sql)
    assert "c2.event_key = {lead_id:String}" in sql
    assert params["lead_id"] == "e1"


async def test_saved_leads_rank_only_their_own_units(monkeypatch):
    calls = await _capture(monkeypatch, [{"saved_candidate_key": "k1", "l.event_key": "e1"}])
    rows = await opportunity_queries.fetch_saved_leads(
        {"as_of": "2026-11-15", "expired_days": 3650, "candidate_keys": ["k1"]}
    )
    assert rows == [{"saved_candidate_key": "k1", "event_key": "e1"}]
    sql, _ = calls[0]
    assert _narrowed(sql)
    assert "c2.unit_candidate_key IN {candidate_keys:Array(String)}" in sql


async def test_a_page_of_leads_is_fetched_by_event_key_in_page_order(monkeypatch):
    calls = await _capture(monkeypatch, [{"event_key": "b"}, {"event_key": "a"}])
    from datetime import date

    rows = await opportunity_queries.fetch_leads_by_event_keys(
        date(2026, 11, 15), expired_days=365, event_keys=["a", "b", "missing"]
    )
    assert [row["event_key"] for row in rows] == ["a", "b"]
    sql, params = calls[0]
    assert _narrowed(sql)
    assert params["event_keys"] == ["a", "b", "missing"]


async def test_an_empty_page_runs_no_query(monkeypatch):
    calls = await _capture(monkeypatch, [])
    from datetime import date

    assert (
        await opportunity_queries.fetch_leads_by_event_keys(
            date(2026, 11, 15), expired_days=365, event_keys=[]
        )
        == []
    )
    assert calls == []
