"""The area list reads ch_area_fact (a view over ~30M warehouse rows) once per page."""

from typing import get_args

from app.area import queries, router


async def test_area_page_and_total_share_one_warehouse_read(monkeypatch):
    calls = []

    async def fake_query(sql, params):
        calls.append(sql)
        return [{"area_name_en": "Dubai Marina", "total": 7}]

    monkeypatch.setattr(queries, "query", fake_query)

    rows, total = await queries.fetch_areas(limit=1, offset=0, search=None, sort_by="units")

    assert len(calls) == 1
    assert "count() OVER ()" in calls[0]
    assert total == [{"total": 7}]
    assert rows[0]["area_name_en"] == "Dubai Marina"


async def test_area_page_past_the_end_still_reports_the_total(monkeypatch):
    calls = []

    async def fake_query(sql, params):
        calls.append(sql)
        return [] if len(calls) == 1 else [{"total": 7}]

    monkeypatch.setattr(queries, "query", fake_query)

    rows, total = await queries.fetch_areas(limit=50, offset=100, search=None, sort_by="units")

    assert rows == []
    assert total == [{"total": 7}]
    assert len(calls) == 2


def test_area_sort_choices_are_exactly_the_supported_orders():
    sort_by = router.areas_list.__wrapped__.__annotations__["sort_by"]

    assert set(get_args(sort_by)) == set(queries._SORT_OPTIONS)
