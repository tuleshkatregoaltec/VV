"""A disposable full production dependency graph proves ranking, windows and output parity."""

import asyncio
import json
import math
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from crm_rental_sql import (
    AREA_LEAD_CTE,
    BASE_TABLE,
    DEPENDENCY_STATE_SQL,
    LIVE_LEAD_CTE,
    PHYSICAL_DEPENDENCIES,
    VIEW_DEPENDENCIES,
    base_lead_cte,
    dependency_revision,
)

from app.clickhouse.client import query
from app.crm import opportunities, opportunity_queries, renewal_leads, rental_base

ANCHOR = date(2026, 10, 9)
AREA = "Al Barsha South 1"
REGISTRY_ALIAS = "Al Barshaa South 1"
LIMITS = {"max_threads": 2, "max_memory_usage": 3_000_000_000, "max_execution_time": 60}
SCHEMA = Path(__file__).parents[4] / "holocron/holocron/lib/sql/clickhouse_schema.sql"


@pytest.fixture
async def rental_graph(warehouse, install_serving, monkeypatch):
    await install_serving(tables=(*PHYSICAL_DEPENDENCIES, "dxbi_sales_unit_events"), views=())
    # Freeze only disposable fixture parts so background merges cannot race equivalence proof.
    for table in PHYSICAL_DEPENDENCIES:
        await warehouse.command(f"SYSTEM STOP MERGES {table}")
    text = SCHEMA.read_text()
    for name in VIEW_DEPENDENCIES:
        statement = re.search(rf"^CREATE OR REPLACE VIEW {name}\b.*?;", text, re.S | re.M)
        assert statement
        await warehouse.command(statement.group().rstrip(";"))
    now = datetime(2026, 10, 1, tzinfo=timezone.utc)
    candidates = []
    matches = []
    # Both date-window edges, stable/ownership-review/sold, unresolved, commercial and villas.
    for i, days in enumerate([-1826, -365, -60, -30, -1, 0, 30, 31, 60, 61, 90, 91]):
        for area_index, area in enumerate((AREA, REGISTRY_ALIAS, "Dubai Marina")):
            key = f"{area}-{days}"
            end = ANCHOR + timedelta(days=days)
            candidates.append(
                [
                    key,
                    key,
                    "cohort-" + key,
                    area,
                    "Project",
                    "Tower",
                    "Apartment",
                    "U-" + key,
                    end - timedelta(days=365),
                    end,
                    80_000 + i + area_index * 1_000,
                    now,
                ]
            )
            matches.append([key, "U-" + key, date(2020, 1, 1), "unique", None])
    # Saved older alias and its latest lease refer to the same known physical unit.
    for key, start, end in (
        ("saved-alias", date(2024, 10, 1), date(2025, 10, 1)),
        ("current-alias", date(2025, 10, 1), date(2026, 10, 30)),
    ):
        candidates.append(
            [
                key,
                key,
                "alias-cohort",
                REGISTRY_ALIAS,
                "Project",
                "Tower",
                "Apartment",
                "U-alias",
                start,
                end,
                95_000,
                now,
            ]
        )
        matches.append([key, "U-alias", date(2020, 1, 1), "unique", None])
    for key, kind, unit, purchase, status in (
        ("sold", "Apartment", "U-sold", date(2026, 11, 1), "unique"),
        ("during", "Commercial", "U-during", date(2026, 2, 1), "unique"),
        ("unresolved", "Villa", "", date(1970, 1, 1), "unresolved"),
        ("nonfinite", "Apartment", "U-nonfinite", date(2020, 1, 1), "unique"),
    ):
        candidates.append(
            [
                key,
                key,
                key,
                AREA,
                "Project",
                "Tower",
                kind,
                unit,
                date(2025, 10, 1),
                date(2026, 10, 30),
                80_000,
                now,
            ]
        )
        matches.append([key, unit, purchase, status, float("nan") if key == "nonfinite" else None])
    await warehouse.insert(
        "dxbi_rental_unit_candidates",
        candidates,
        column_names=[
            "contract_key",
            "unit_candidate_key",
            "unit_cohort_key",
            "area_name",
            "project_name",
            "building_name",
            "property_type",
            "unit_number",
            "lease_start",
            "lease_end",
            "annual_rent_aed",
            "last_scraped_at",
        ],
    )
    await warehouse.insert(
        "dxbi_rental_sale_matches",
        matches,
        column_names=[
            "unit_candidate_key",
            "unit_number",
            "last_purchase_date",
            "match_status",
            "latest_capital_gain_pct",
        ],
    )
    await warehouse.insert(
        "dxbi_rental_events",
        [["coverage", "coverage", "coverage", ANCHOR]],
        column_names=["contract_key", "unit_candidate_key", "unit_cohort_key", "source_shard_date"],
    )
    # The production hierarchy view applies its canonical spelling to this registry signature.
    await warehouse.insert(
        "geo_source_signatures",
        [["dxbi_rentals", "alias-address", "building", REGISTRY_ALIAS, "Project", "Tower"]],
        column_names=[
            "source_system",
            "source_key",
            "source_grain",
            "raw_area_name",
            "raw_project_name",
            "raw_building_name",
        ],
    )
    await warehouse.insert(
        "geo_entity_links",
        [["dxbi_rentals", "alias-address", "unmapped"]],
        column_names=["source_system", "source_key", "status"],
    )
    monkeypatch.syspath_prepend(str(Path(__file__).parents[4] / "holocron"))
    from holocron.assets.crm_rental_base import publish_rental_base

    # Serialize all test API queries; every query is bounded even outside request middleware.
    gate = asyncio.Semaphore(1)

    async def bounded_query(sql, parameters=None):
        async with gate:
            result = await warehouse.query(sql, parameters=parameters or {}, settings=LIMITS)
            return [dict(zip(result.column_names, row)) for row in result.result_rows]

    monkeypatch.setattr(opportunity_queries, "query", bounded_query)
    before = dependency_revision(await query(DEPENDENCY_STATE_SQL))
    marker = await asyncio.to_thread(publish_rental_base, warehouse.client)
    assert marker["source"] == before == dependency_revision(await query(DEPENDENCY_STATE_SQL))
    monkeypatch.setattr(rental_base.settings, "CRM_RENTAL_BASE_ENABLED", True)
    assert BASE_TABLE in await rental_base.lead_cte(bounded_query)
    return bounded_query, publish_rental_base


def _comparable(value):
    # Preserve the category/sign of every nonfinite value instead of silently dropping it.
    if isinstance(value, float) and not math.isfinite(value):
        return "NaN" if math.isnan(value) else "+Inf" if value > 0 else "-Inf"
    if isinstance(value, dict):
        return {key: _comparable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_comparable(item) for item in value]
    return value


async def test_named_as_of_window_area_matrix_preserves_every_column(rental_graph):
    bounded, _ = rental_graph
    cases = 0
    for anchor in (date(2025, 10, 9), ANCHOR, date(2027, 1, 1)):
        for expired in (0, 30, 60, 365, 1825):
            for areas in (None, [AREA], ["Dubai Marina"], [AREA, "Dubai Marina"], ["Missing"]):
                params = {"as_of": anchor, "expired_days": expired, "areas": areas or []}
                suffix = " SELECT * FROM leads"
                if areas is not None:
                    suffix += " WHERE has({areas:Array(String)}, area_name)"
                suffix += " ORDER BY property_identity_key"
                live = await bounded(
                    (AREA_LEAD_CTE if areas is not None else LIVE_LEAD_CTE) + suffix, params
                )
                base = await bounded(base_lead_cte(areas=areas is not None) + suffix, params)
                assert _comparable(base) == _comparable(live), (anchor, expired, areas)
                cases += 1
    assert cases == 75
    print(f"matrix_cases={cases}; full_row_differences=0")


async def test_actual_dashboard_renewal_and_agent_outputs_match(rental_graph, monkeypatch):
    bounded, _ = rental_graph

    async def outputs():
        dashboard = await opportunity_queries.fetch_dashboard(
            ANCHOR,
            AREA,
            None,
            "area",
            None,
            365,
            100,
            0,
            None,
            None,
            None,
            None,
            None,
        )
        renewals = await renewal_leads.list_renewals(
            window=None,
            area=AREA,
            property_type=None,
            project=None,
            building=None,
            limit=100,
            offset=0,
            as_of=ANCHOR,
        )
        agent = await opportunity_queries.fetch_renewal_leads(ANCHOR, [AREA], 60, 30, 100, 0)
        areas = await opportunity_queries.fetch_renewal_areas(ANCHOR)
        projection = [
            opportunities._lead_from_row(row).model_dump(mode="json") for row in dashboard[0]
        ]
        return _comparable([dashboard, renewals.model_dump(mode="json"), agent, areas, projection])

    monkeypatch.setattr(rental_base.settings, "CRM_RENTAL_BASE_ENABLED", False)
    live = await outputs()
    monkeypatch.setattr(rental_base.settings, "CRM_RENTAL_BASE_ENABLED", True)
    fast = await outputs()
    assert fast == live
    assert any(row["registry_area_name"] == REGISTRY_ALIAS for row in fast[0][0])
    assert any(row["latest_capital_gain_pct"] == "NaN" for row in fast[0][0])
    assert BASE_TABLE in await rental_base.lead_cte(bounded, areas=True)


async def test_saved_alias_remains_live_and_resolves_latest_identity(rental_graph):
    rows = await opportunity_queries.fetch_saved_leads(
        {"candidate_keys": ["saved-alias"], "as_of": ANCHOR, "expired_days": 365}
    )
    assert [(row["saved_candidate_key"], row["event_key"]) for row in rows] == [
        ("saved-alias", "current-alias")
    ]
    assert opportunities._lead_from_row(rows[0]).lead_id == "current-alias"


async def test_source_change_then_failed_build_keeps_old_artifact_and_forces_live(
    rental_graph,
    warehouse,
):
    bounded, publish = rental_graph
    before = await bounded(
        f"SELECT comment FROM system.tables WHERE database=currentDatabase() AND name='{BASE_TABLE}'"
    )
    old_rows = await bounded(
        f"SELECT count() AS rows, sum(cityHash64(event_key)) AS checksum FROM {BASE_TABLE}"
    )
    await warehouse.command(
        "ALTER TABLE dxbi_rental_sale_matches ADD COLUMN correction UInt8 DEFAULT 0"
    )
    assert await rental_base.lead_cte(bounded) == LIVE_LEAD_CTE
    # A failing build has no permission to replace old evidence or its revision.
    await warehouse.command("RENAME TABLE geo_location_closure TO geo_location_closure_unavailable")
    with pytest.raises(ValueError, match="seven"):
        await asyncio.to_thread(publish, warehouse.client)
    after = await bounded(
        f"SELECT comment FROM system.tables WHERE database=currentDatabase() AND name='{BASE_TABLE}'"
    )
    assert before == after
    assert old_rows == await bounded(
        f"SELECT count() AS rows, sum(cityHash64(event_key)) AS checksum FROM {BASE_TABLE}"
    )
    assert await rental_base.lead_cte(bounded) == LIVE_LEAD_CTE


async def test_area_prewhere_reads_fewer_base_rows_and_keeps_registry_alias(
    rental_graph,
    warehouse,
):
    bounded, publish = rental_graph
    # Several granules of an unrelated area expose a full-base scan regression. These rows
    # exist only in this fixture's disposable database, never in an operational warehouse.
    await warehouse.command(
        "INSERT INTO dxbi_rental_unit_candidates "
        "(contract_key, unit_candidate_key, unit_cohort_key, area_name, project_name, "
        "building_name, property_type, lease_start, lease_end, last_scraped_at) "
        "SELECT concat('unrelated-', toString(number)), concat('unrelated-', toString(number)), "
        "toString(number), 'ZZ Unrelated Area', 'Project', 'Tower', 'Apartment', "
        "toDate('2025-10-01'), toDate('2026-10-30'), now64(3) FROM numbers(25000)"
    )
    published = await asyncio.to_thread(publish, warehouse.client)
    previous = await bounded(
        f"SELECT comment, total_rows FROM system.tables "
        f"WHERE database=currentDatabase() AND name='{BASE_TABLE}_previous'"
    )
    old_marker = json.loads(previous[0]["comment"])
    assert old_marker["rows"] == previous[0]["total_rows"] < published["rows"]
    params = {"as_of": ANCHOR, "expired_days": 365, "areas": [AREA]}
    rows = await bounded(base_lead_cte(areas=True) + " SELECT * FROM ranked_unit", params)
    assert rows and {row["area_name"] for row in rows} == {AREA}
    assert REGISTRY_ALIAS in {row["registry_area_name"] for row in rows}
    full = await warehouse.query(f"SELECT * FROM {BASE_TABLE}", settings=LIMITS)
    pruned = await warehouse.query(
        f"SELECT * FROM {BASE_TABLE} PREWHERE area_name IN {{areas:Array(String)}}",
        parameters=params,
        settings=LIMITS,
    )
    assert 0 < int(pruned.summary["read_rows"]) < int(full.summary["read_rows"])
    print(
        f"area_read_rows={pruned.summary['read_rows']}; full_read_rows={full.summary['read_rows']}"
    )
    plan = await bounded(
        f"EXPLAIN indexes=1 SELECT * FROM {BASE_TABLE} "
        "PREWHERE area_name IN {areas:Array(String)}",
        params,
    )
    assert "PrimaryKey" in json.dumps(plan)


async def test_exact_area_identity_collision_refuses_publication_and_keeps_live_area_semantics(
    rental_graph,
    warehouse,
):
    bounded, publish = rental_graph
    marker_sql = (
        f"SELECT comment FROM system.tables "
        f"WHERE database=currentDatabase() AND name='{BASE_TABLE}'"
    )
    checksum_sql = (
        f"SELECT count() AS rows, sum(cityHash64(event_key)) AS checksum FROM {BASE_TABLE}"
    )
    old_marker = await bounded(marker_sql)
    old_rows = await bounded(checksum_sql)
    # Both exact labels normalize to testarea in the canonical property identity. Selecting
    # Test-Area live narrows BEFORE ranking and must retain its older lease, even though the
    # global winner is the newer lease registered under Test Area.
    await warehouse.insert(
        "dxbi_rental_unit_candidates",
        [
            [
                "collision-old",
                "collision-old",
                "collision",
                "Test-Area",
                "Project",
                "Tower",
                "Apartment",
                "101",
                date(2025, 1, 1),
                date(2026, 10, 30),
                datetime(2026, 10, 1, tzinfo=timezone.utc),
            ],
            [
                "collision-new",
                "collision-new",
                "collision",
                "Test Area",
                "Project",
                "Tower",
                "Apartment",
                "101",
                date(2025, 2, 1),
                date(2026, 11, 15),
                datetime(2026, 10, 2, tzinfo=timezone.utc),
            ],
        ],
        column_names=[
            "contract_key",
            "unit_candidate_key",
            "unit_cohort_key",
            "area_name",
            "project_name",
            "building_name",
            "property_type",
            "unit_number",
            "lease_start",
            "lease_end",
            "last_scraped_at",
        ],
    )
    await warehouse.insert(
        "dxbi_rental_sale_matches",
        [[key, "101", date(2020, 1, 1), "unique"] for key in ("collision-old", "collision-new")],
        column_names=["unit_candidate_key", "unit_number", "last_purchase_date", "match_status"],
    )
    params = {"as_of": ANCHOR, "expired_days": 365, "areas": ["Test-Area"]}
    global_winners = await bounded(
        LIVE_LEAD_CTE + " SELECT event_key FROM leads WHERE property_identity_key = "
        "'unit:tower:testarea:101'",
        params,
    )
    assert global_winners == [{"event_key": "collision-new"}]
    with pytest.raises(ValueError, match="distinct exact display areas"):
        await asyncio.to_thread(publish, warehouse.client)
    assert await bounded(marker_sql) == old_marker
    assert await bounded(checksum_sql) == old_rows
    assert await rental_base.lead_cte(bounded, areas=True) == AREA_LEAD_CTE
    selected, counts = await opportunity_queries.fetch_renewal_leads(
        ANCHOR,
        ["Test-Area"],
        90,
        365,
        100,
        0,
    )
    assert [row["event_key"] for row in selected] == ["collision-old"]
    assert counts[0]["total"] == 1
    cleanup = await bounded(
        f"SELECT count() AS count FROM system.tables WHERE database=currentDatabase() "
        f"AND (name='{BASE_TABLE}_publish_guard' OR startsWith(name, '{BASE_TABLE}_staging_'))"
    )
    assert cleanup == [{"count": 0}]
    print(
        "exact_area_collision=rejected; previous_artifact=unchanged; selected_lease=collision-old"
    )


async def test_owner_identity_filter_is_identical_on_live_and_published_ranked_base(
    rental_graph, monkeypatch
):
    options = dict(
        status=None,
        unlet_only=False,
        expired_days=365,
        area=None,
        property_type=None,
        project=None,
        building=None,
        limit=100,
        offset=0,
        unit_keys=["saved-alias"],
    )
    outcomes = []
    for enabled in (False, True):
        monkeypatch.setattr(rental_base.settings, "CRM_RENTAL_BASE_ENABLED", enabled)
        known = await opportunity_queries.fetch_renewals(ANCHOR, **options)
        unknown = await opportunity_queries.fetch_renewals(ANCHOR, **options, exclude_units=True)
        assert [row["event_key"] for row in known[0]] == ["current-alias"]
        assert "current-alias" not in {row["event_key"] for row in unknown[0]}
        outcomes.append(_comparable((known, unknown)))
    assert outcomes[0] == outcomes[1]
