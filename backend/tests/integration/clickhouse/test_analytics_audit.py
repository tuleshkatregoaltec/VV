"""Scope regressions executed in an isolated ClickHouse database."""

import pytest

from app.analytics.queries import project_units_composition
from app.clickhouse.client import query


@pytest.mark.parametrize("master_project", [None, "Master A"])
async def test_project_stock_excludes_sibling_projects(warehouse, monkeypatch, master_project):
    await warehouse.command("""
        CREATE TABLE ch_units (
            project_name_en String, master_project_en String,
            rooms_en String, actual_area Float64
        ) ENGINE = Memory
    """)
    await warehouse.insert(
        "ch_units",
        [["Tower A", "Master A", "1 B/R", 50], ["Tower B", "Master A", "1 B/R", 150]],
        column_names=["project_name_en", "master_project_en", "rooms_en", "actual_area"],
    )
    from app.analytics import queries, service

    async def empty(*args, **kwargs):
        return []

    # Exercise the actual service parameter flow for direct and drill-down selections.
    for name in dir(queries):
        if name.startswith("fetch_project_") and name != "fetch_project_units_composition":
            monkeypatch.setattr(queries, name, empty)
    summary = await service.get_project_summary("Tower A", "project", master_project)
    assert len(summary.unit_composition) == 1
    assert summary.unit_composition[0].count == 1
    assert summary.unit_composition[0].avg_unit_size_sqft == pytest.approx(538.2, abs=0.01)
    master = await query(project_units_composition("master"), {"project_name": "Master A"})
    assert master[0]["unit_count"] == 2


async def test_search_returns_market_names_masters_and_projects_without_sales(warehouse):
    from app.analytics.queries import search_projects

    for table in ("ch_transactions", "ch_rent_contracts", "ch_projects", "ch_units"):
        await warehouse.command(
            f"CREATE TABLE {table} (project_name_en String, master_project_en String) ENGINE = Memory"
        )
    await warehouse.insert("ch_transactions", [["23 MARINA", "Dubai Marina"]])
    await warehouse.insert("ch_rent_contracts", [["Rental Tower", "Dubai Marina"]])
    await warehouse.insert("ch_projects", [["New Launch", "Dubai Marina"]])
    rows = await query(search_projects(), {"search_pattern": "%marina%", "limit": 50})
    assert {tuple(row.values()) for row in rows} == {
        ("23 MARINA", "project"),
        ("Dubai Marina", "master"),
    }
    rows = await query(search_projects(), {"search_pattern": "%", "limit": 50})
    assert {row["name"] for row in rows} >= {"Rental Tower", "New Launch"}
