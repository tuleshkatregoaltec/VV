"""The dashboard ranks the lease relation once instead of five times.

Live it ran five full-ranking queries one after another (~13.5M rows, 1 GiB read, 2.35 GiB
peak, ~15 s). One pass now yields the summary, breakdown, asset classes, filter options and the
page's keys; the page's full rows come from a lookup by key.
"""

from datetime import date

from crm_rental_sql import CANDIDATE_SOURCE

from app.crm import opportunity_queries


def _combined_row():
    return {
        "total": 5,
        "urgent": 2,
        "expired": 1,
        "expiring_30": 1,
        "expiring_60": 2,
        "expiring_90": 1,
        "sale_candidates": 1,
        "annual_rent_at_risk": 900,
        "page": [
            [-94, date(2026, 11, 1), -500, "e2", "k2"],
            [-88, date(2026, 11, 2), -100, "e1", "k1"],
        ],
        "breakdown": [
            ["Al Barsha", "", "JVC"],
            [2, 1, 2],
            [0, 1, 2],
            [1, 0, 0],
            [1, 0, 0],
            [0, 1, 1],
            [0, 0, 1],
            [300, 100, 500],
        ],
        "asset_residential": [4, 2, 3, 800, ["Apartment", "Villa"]],
        "asset_commercial": [0, 0, 0, 0, []],
        "asset_other": [1, 0, 1, 100, ["Other"]],
        "rows": 100,
        "exact_unit_matches": 40,
        "min_date": date(2024, 1, 1),
        "max_date": date(2026, 11, 1),
        "data_complete_through": date(2026, 11, 10),
        "areas": ["Al Barsha", "JVC"],
        "projects": [],
        "buildings": [],
    }


async def test_one_ranking_pass_and_one_lookup_by_key_build_the_dashboard(monkeypatch):
    calls = []

    async def query(sql, params=None):
        calls.append((sql, dict(params or {})))
        if "groupArraySortedIf" in sql:
            return [_combined_row()]
        return [{"event_key": "e1", "x": 1}, {"event_key": "e2", "x": 2}]

    monkeypatch.setattr(opportunity_queries, "query", query)
    leads, summary, breakdown, assets, metadata = await opportunity_queries.fetch_dashboard(
        date(2026, 11, 15),
        None,
        None,
        "area",
        None,
        365,
        2,
        0,
        None,
        None,
        None,
        None,
        None,
    )
    assert len(calls) == 2
    ranking_sql, _ = calls[0]
    assert CANDIDATE_SOURCE in ranking_sql  # one canonical pass over every lease
    assert CANDIDATE_SOURCE not in calls[1][0]  # the page is looked up by key
    assert calls[1][1]["event_keys"] == ["e2", "e1"]
    assert [row["event_key"] for row in leads] == ["e2", "e1"]
    assert summary == [
        {
            key: _combined_row()[key]
            for key in (
                "total",
                "urgent",
                "expired",
                "expiring_30",
                "expiring_60",
                "expiring_90",
                "sale_candidates",
                "annual_rent_at_risk",
            )
        }
    ]
    # Ordered by urgent, then total; an empty label is the unresolved hierarchy.
    assert [row["label"] for row in breakdown] == ["JVC", "Unresolved hierarchy", "Al Barsha"]
    assert breakdown[0] == {
        "label": "JVC",
        "total": 2,
        "urgent": 2,
        "expired": 0,
        "expiring_30": 0,
        "expiring_60": 1,
        "expiring_90": 1,
        "potential_value": 500,
    }
    # Asset classes with no leases are left out, in residential/commercial/other order.
    assert [row["asset_class"] for row in assets] == ["residential", "other"]
    assert assets[0] == {
        "asset_class": "residential",
        "total": 4,
        "urgent": 2,
        "exact_unit_matches": 3,
        "annual_rent_at_risk": 800,
        "property_types": ["Apartment", "Villa"],
    }
    assert metadata[0]["areas"] == ["Al Barsha", "JVC"]
    assert metadata[0]["rows"] == 100


async def test_breakdown_keeps_the_top_twelve(monkeypatch):
    labels = [f"Area {i:02d}" for i in range(20)]
    row = _combined_row()
    row["breakdown"] = [labels, *[[i for i in range(20)] for _ in range(6)], [0] * 20]

    async def query(sql, params=None):
        return [row] if "groupArraySortedIf" in sql else []

    monkeypatch.setattr(opportunity_queries, "query", query)
    _, _, breakdown, _, _ = await opportunity_queries.fetch_dashboard(
        date(2026, 11, 15), None, None, "area", None, 365, 50, 0, None, None, None, None, None
    )
    assert [item["label"] for item in breakdown] == labels[::-1][:12]


async def test_a_deep_page_falls_back_to_a_keys_only_ranking(monkeypatch):
    calls = []

    async def query(sql, params=None):
        calls.append(sql)
        if "groupArraySortedIf" in sql:
            row = _combined_row()
            row["page"] = []
            return [row]
        if "SELECT event_key" in sql and "OFFSET" in sql:
            return [{"event_key": "deep"}]
        return [{"event_key": "deep"}]

    monkeypatch.setattr(opportunity_queries, "query", query)
    leads, *_ = await opportunity_queries.fetch_dashboard(
        date(2026, 11, 15), None, None, "area", None, 365, 50, 100_000, None, None, None, None, None
    )
    assert [row["event_key"] for row in leads] == ["deep"]
    assert any("OFFSET" in sql for sql in calls)


async def test_assets_renewals_rank_once_and_look_the_page_up_by_key(monkeypatch):
    calls = []

    async def query(sql, params=None):
        calls.append((sql, dict(params or {})))
        if "groupArraySortedIf" in sql:
            return [
                {
                    "total": 3,
                    "page": [
                        [-94, date(2026, 11, 1), -1, "e3"],
                        [-90, date(2026, 11, 2), -1, "e1"],
                    ],
                    "property_types": ["Apartment"],
                    "projects": ["P"],
                    "buildings": [],
                }
            ]
        return [{"event_key": "e1"}, {"event_key": "e3"}]

    monkeypatch.setattr(opportunity_queries, "query", query)
    rows, total, facets = await opportunity_queries.fetch_renewals(
        date(2026, 11, 15),
        status=None,
        unlet_only=False,
        expired_days=365,
        area="Al Barsha",
        property_type=None,
        project=None,
        building=None,
        limit=2,
        offset=0,
    )
    assert len(calls) == 2
    assert [row["event_key"] for row in rows] == ["e3", "e1"]
    assert total == 3
    assert facets == {"property_types": ["Apartment"], "projects": ["P"], "buildings": []}
    page_sql, page_params = calls[1]
    # The page lookup keeps the area narrowing the ranking used.
    assert "display_area_name" in page_sql.split("FROM dxbi_rental_unit_candidates AS c2")[0]
    assert page_params["areas"] == ["Al Barsha"]
