"""Scope regressions executed in an isolated ClickHouse database."""

import pytest

from app.clickhouse.client import query


@pytest.mark.parametrize("master_project", [None, "Master A"])
async def test_project_stock_excludes_sibling_projects(
    warehouse, monkeypatch, install_serving, master_project
):
    """A project's unit mix is its own stock row: a sibling project of the master never adds."""
    await install_serving(
        tables=("analytics_projects", "analytics_project_keys", "analytics_unit_stock"), views=()
    )
    for key, name in (("towera", "Tower A"), ("towerb", "Tower B")):
        await warehouse.command(
            "INSERT INTO analytics_projects (project_key, project_name, scope_kind, master_key,"
            f" master_name) VALUES ('{key}', '{name}', 'Project', 'mastera', 'Master A')"
        )
    await warehouse.command(
        "INSERT INTO analytics_unit_stock (scope_level, scope_id, units, units_source, mix_rooms,"
        " mix_units, mix_median_sqft) VALUES"
        " ('project', 'towera', 1, 'dld_units', ['1 B/R'], [1], [538]),"
        " ('project', 'towerb', 1, 'dld_units', ['1 B/R'], [1], [1615])"
    )
    from app.analytics import queries, service

    async def empty(*args, **kwargs):
        return []

    # Exercise the actual service parameter flow for direct and drill-down selections.
    for name in dir(queries):
        if name.startswith("fetch_project_"):
            monkeypatch.setattr(queries, name, empty)

    async def empty_bundle(*args, **kwargs):
        return ([], [], [], [], [], [], [])

    monkeypatch.setattr(queries, "fetch_project_sales_bundle", empty_bundle)
    summary = await service.get_project_summary("Tower A", "project", master_project)
    assert [(u.rooms, u.count, u.avg_unit_size_sqft) for u in summary.unit_composition] == [
        ("1 B/R", 1, 538)
    ]
    assert summary.project.no_of_units == 1


async def test_search_excludes_dld_only_launches(warehouse, install_serving):
    """Search lists the hierarchy Holocron builds from DXBI records: a project only DLD's
    register holds (a launch with no sale or lease) is not a scope."""
    from app.analytics.queries import search_projects

    await install_serving(tables=("analytics_projects", "analytics_buildings"), views=())
    await warehouse.command("CREATE TABLE ch_projects (project_name_en String) ENGINE = Memory")
    await warehouse.insert("ch_projects", [["New Launch"]], column_names=["project_name_en"])
    await warehouse.command(
        "INSERT INTO analytics_projects (project_key, project_name, scope_kind, master_key,"
        " master_name, sales, leases) VALUES"
        " ('23marina', '23 Marina', 'Project', 'dubaimarina', 'Dubai Marina', 1, 0),"
        " ('rentaltower', 'Rental Tower', 'Project', 'dubaimarina', 'Dubai Marina', 0, 1)"
    )
    rows = await query(search_projects(), {"search_pattern": "%marina%", "limit": 50})
    assert {(row["name"], row["filter_type"], row["scope_kind"]) for row in rows} == {
        ("23 Marina", "project", "Project"),
        ("Rental Tower", "project", "Project"),
        ("Dubai Marina", "master", "Master"),
    }
    rows = await query(search_projects(), {"search_pattern": "%", "limit": 50})
    assert "Rental Tower" in {row["name"] for row in rows}
    assert "New Launch" not in {row["name"] for row in rows}
