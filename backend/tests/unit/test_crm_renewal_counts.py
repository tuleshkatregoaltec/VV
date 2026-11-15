"""My-areas counts and the Leads feed count the same units.

Live, /renewal-areas counted every lease ending in 90 days (Al Barsha 5,130) while
/renewal-leads only lists leases tied to a unit number, so an area promised more leads than
the feed could ever show.
"""

from datetime import date

from app.crm import opportunity_queries


async def _sql_of(monkeypatch, call):
    seen = []

    async def query(sql, params=None):
        seen.append(sql)
        return []

    monkeypatch.setattr(opportunity_queries, "query", query)
    await call()
    return seen[-1]


async def test_area_counts_and_the_feed_share_one_unit_rule(monkeypatch):
    rule = opportunity_queries.RENEWAL_LEAD_UNIT_RULE
    areas_sql = await _sql_of(
        monkeypatch, lambda: opportunity_queries.fetch_renewal_areas(date(2026, 11, 15))
    )
    feed_sql = await _sql_of(
        monkeypatch,
        lambda: opportunity_queries.fetch_renewal_leads(
            date(2026, 11, 15), ["Al Barsha"], 90, 30, 100, 0, kind="upcoming"
        ),
    )
    assert rule in feed_sql
    upcoming = areas_sql.split("AS upcoming_90_days")[0]
    assert rule in upcoming


def _row(event_key, lease_end, **counts):
    return {
        "event_key": event_key,
        "lease_end": lease_end,
        "_all": counts.get("all", 3),
        "_upcoming": counts.get("upcoming", 2),
        "_expired": counts.get("expired", 1),
        "_vacant": counts.get("vacant", 1),
        "_entered_today": counts.get("entered_today", 0),
    }


async def test_the_feed_lists_upcoming_renewals_first_by_soonest_end(monkeypatch):
    seen = []

    async def query(sql, params=None):
        seen.append((sql, params))
        return [_row("soon", date(2026, 11, 16)), _row("later", date(2026, 12, 1))]

    monkeypatch.setattr(opportunity_queries, "query", query)
    rows, counts = await opportunity_queries.fetch_renewal_leads(
        date(2026, 11, 15), ["Al Barsha"], 60, 30, 100, 0
    )
    sql = seen[0][0]
    order = sql.split("ORDER BY")[-1]
    # Running leases first, the soonest end on top; then ended ones, most recent first.
    assert order.index("lease_end < {as_of:Date}") < order.index("raw_score")
    assert counts == [
        {"total": 3, "upcoming": 2, "expired": 1, "vacant": 1, "entered_today": 0, "all": 3}
    ]


async def test_expired_leads_are_their_own_page_with_their_own_total(monkeypatch):
    seen = []

    async def query(sql, params=None):
        seen.append(sql)
        return [_row("ended", date(2026, 11, 10))]

    monkeypatch.setattr(opportunity_queries, "query", query)
    _, counts = await opportunity_queries.fetch_renewal_leads(
        date(2026, 11, 15), ["Al Barsha"], 60, 30, 100, 0, kind="expired"
    )
    outer, order = seen[0].rsplit("ORDER BY", 1)
    assert "WHERE lease_end < {as_of:Date}" in outer[-120:]
    assert "lease_end DESC" in order
    assert counts[0]["total"] == 1  # the expired count, not the whole window


async def test_a_page_past_the_end_still_reports_the_real_totals(monkeypatch):
    seen = []

    async def query(sql, params=None):
        seen.append(sql)
        if len(seen) == 1:
            return []
        return [_row("count-only", None, all=4452, upcoming=3657, expired=795, vacant=500)]

    monkeypatch.setattr(opportunity_queries, "query", query)
    rows, counts = await opportunity_queries.fetch_renewal_leads(
        date(2026, 11, 15), ["Al Barsha"], 60, 30, 100, 9_000, kind="upcoming"
    )
    assert rows == []
    assert counts[0]["total"] == 3657
    assert counts[0]["all"] == 4452
