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

    for table in ("ch_rent_contracts", "ch_projects", "ch_units"):
        await warehouse.command(
            f"CREATE TABLE {table} (project_name_en String, master_project_en String) ENGINE = Memory"
        )
    await warehouse.command(
        "CREATE TABLE ch_transactions (project_name_en String, master_project_en String,"
        " building_name_en String) ENGINE = Memory"
    )
    await warehouse.insert("ch_transactions", [["23 MARINA", "Dubai Marina", "23 Marina Tower"]])
    await warehouse.insert("ch_rent_contracts", [["Rental Tower", "Dubai Marina"]])
    await warehouse.insert("ch_projects", [["New Launch", "Dubai Marina"]])
    rows = await query(search_projects(), {"search_pattern": "%marina%", "limit": 50})
    assert {tuple(row.values()) for row in rows} == {
        ("23 MARINA", "project"),
        ("Dubai Marina", "master"),
    }
    rows = await query(search_projects(), {"search_pattern": "%", "limit": 50})
    assert {row["name"] for row in rows} >= {"Rental Tower", "New Launch"}


async def test_search_finds_buildings_beside_many_project_names(warehouse, monkeypatch):
    from app.analytics import service

    for table in ("ch_rent_contracts", "ch_projects", "ch_units"):
        await warehouse.command(
            f"CREATE TABLE {table} (project_name_en String, master_project_en String) ENGINE = Memory"
        )
    await warehouse.command(
        "CREATE TABLE ch_transactions (project_name_en String, master_project_en String,"
        " building_name_en String) ENGINE = Memory"
    )
    # Sixty projects match "lake" by name; the building's sales are in a project that does not.
    await warehouse.insert(
        "ch_transactions",
        [[f"LAKE PROJECT {i:02}", "", ""] for i in range(60)]
        + [["JLT CLUSTER X", "Jumeirah Lake Towers", "Lake Shore Tower"]] * 2,
    )
    monkeypatch.setattr(service, "_building_projects", (0.0, []))
    found = (await service.get_project_search("lake", limit=50)).projects
    assert len(found) == 50
    # The building keeps its place in the list and opens its project.
    assert [(p.name, p.building) for p in found if p.building] == [
        ("JLT CLUSTER X", "Lake Shore Tower")
    ]
    # An empty search lists projects only.
    assert not any(p.building for p in (await service.get_project_search("", limit=50)).projects)


async def test_project_meta_fills_from_the_units_register_then_dxbis_building_list(warehouse):
    import json

    from app.analytics import service

    await warehouse.command(
        "CREATE TABLE dxbi_heatmap_buildings_bronze (location_id String, status UInt16,"
        " payload_json String) ENGINE = Memory"
    )

    def card(location_id, name, units, kind="B", kids=(), project="Lake Shore Tower"):
        building = {
            "location": name, "project": project, "area_name": "Al Thanyah Fifth",
            "dev": "Al Bodor", "completion_date": "2012-01-21T20:00:00Z",
            "completion_percent": 100, "unit_count": units, "display_as": kind,
            "building_csv": list(kids),
        }  # fmt: skip
        return [location_id, 200, json.dumps({"Building": building})]

    # DXBI's project card repeats the totals of the building cards it lists; a card read twice
    # is one card.
    await warehouse.insert(
        "dxbi_heatmap_buildings_bronze",
        [card("1", "Lake Shore Tower", 477, "P", kids=[2])]
        + [card("2", "Lakeshore Tower 1", 477)] * 2
        + [card("3", "Sky Courts Tower A", 400, project="Sky Courts")]
        + [card("4", "Sky Courts Tower B", 350, project="Sky Courts")],
    )
    # DLD's "SKY COURTS" is DXBI's Sky Courts towers by their paired sales.
    await warehouse.command(
        "CREATE TABLE dxbi_sale_profile (sale_key String, building_name String,"
        " project_name String, project_source String) ENGINE = Memory"
    )
    await warehouse.insert(
        "dxbi_sale_profile",
        [[f"a{i}", "Sky Courts Tower A", "SKY COURTS", "dld_pair"] for i in range(3)]
        + [[f"b{i}", "Sky Courts Tower B", "SKY COURTS", "dld_pair"] for i in range(3)],
    )
    sky = await service._fill_project_meta(None, "SKY COURTS", register_units=0)
    assert (sky.no_of_units, sky.no_of_buildings) == (750, 2)
    # LAKE SHORE TOWER is not in DLD's projects register: every value names its source.
    meta = await service._fill_project_meta(None, "LAKE SHORE TOWER", register_units=0)
    assert meta is not None
    assert (meta.developer_name, str(meta.completion_date), meta.no_of_units) == (
        "Al Bodor",
        "2012-01-21",
        477,
    )
    assert meta.no_of_buildings == 1  # the building is listed once, however often it was read
    assert set(meta.field_sources.values()) == {"dxbi_buildings"}
    # DLD's units register counts units before DXBI does; DLD's own values are never replaced.
    registered = service.ProjectMeta(project_name="LAKE SHORE TOWER", developer_name="DLD Dev")
    meta = await service._fill_project_meta(registered, "LAKE SHORE TOWER", register_units=480)
    assert (meta.developer_name, meta.no_of_units) == ("DLD Dev", 480)
    assert meta.field_sources["no_of_units"] == "dld_units"
    assert "developer_name" not in meta.field_sources
    # Nothing anywhere: no metadata at all.
    assert await service._fill_project_meta(None, "UNKNOWN PLACE", register_units=0) is None
