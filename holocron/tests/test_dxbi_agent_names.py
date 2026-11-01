from __future__ import annotations

from datetime import UTC, date, datetime

from holocron.sources.dxbi import agent_names
from tests.test_market_release import database, live, warehouse  # noqa: F401  (fixtures)


def test_a_prefix_is_removed_only_with_evidence() -> None:
    # Stripping words on a guess would damage real names ("Hillsedge", "Golden Dream"), so the
    # rest must be a building DXBI lists more often and the prefix must read as a person.
    sql = agent_names.FIND_REPAIRS_SQL
    assert "known.sales >= 3 * s.sales AND known.sales >= 5" in sql
    assert "NOT IN (SELECT name_key FROM known_names)" in sql
    assert "buildings >= 3" in sql
    # One word alone never qualifies in the second pass: "Hamza Tower" is a building.
    assert "k >= 2 AND arrayAll" in agent_names.FIND_RARE_REPAIRS_SQL


def test_every_sales_load_repairs_agent_names() -> None:
    from pathlib import Path

    loader = Path(__file__).parents[1] / "scripts" / "load_dxbi_sales_units.py"
    assert "repair_agent_names(client)" in loader.read_text()


def _sale(key: str, building: str, n: int = 1) -> list[list[object]]:
    return [
        [
            f"{key}-{i}",
            date(2025, 7, 1),
            building,
            building.lower().replace(" ", ""),
            "Dubai Marina",
            "dubaimarina",
            800.0,
            1_000_000 + i,
            datetime(2026, 7, 1, tzinfo=UTC),
        ]
        for i in range(n)
    ]


@live
def test_an_agents_name_leaves_the_building_and_real_names_stay(warehouse) -> None:  # noqa: F811
    columns = [
        "sale_key", "transaction_date", "building_name", "building_key", "area_name", "area_key",
        "size_sqft", "sale_amount_aed", "loaded_at",
    ]  # fmt: skip
    rows = (
        _sale("a", "Lakeshore Tower 1", 6)
        + _sale("b", "Sheetal Lakeshore Tower 1")
        + _sale("c", "Sheetal Marina Tower")
        + _sale("d", "Marina Tower", 6)
        + _sale("e", "Sheetal Dubai Star")
        + _sale("f", "Dubai Star", 6)
        + _sale("g", "Hillsedge Tower")
        + _sale("h", "Tower", 6)
        + _sale("i", "Binghatti Aquarise Tower C")
        + _sale("j", "Tower C", 6)
    )
    warehouse.insert_rows(table="dxbi_sales_unit_events", rows=rows, column_names=columns)
    # "Hillsedge" and "Binghatti Aquarise" are place names DLD knows.
    warehouse.insert_rows(
        table="dld_od_transactions_bronze",
        rows=[["t1", "HILLSEDGE", "BINGHATTI AQUARISE"]],
        column_names=["row_key", "building_name_en", "project_en"],
    )

    first = agent_names.repair_agent_names(warehouse)
    names = {
        row[0]: row[1]
        for row in warehouse.query(
            "SELECT sale_key, building_name FROM dxbi_sales_unit_events FINAL"
        ).result_rows
    }
    assert names["b-0"] == "Lakeshore Tower 1"
    assert names["c-0"] == "Marina Tower"
    assert names["e-0"] == "Dubai Star"
    assert names["g-0"] == "Hillsedge Tower"
    assert names["i-0"] == "Binghatti Aquarise Tower C"
    assert first["rows_rewritten"] == 3
    # Each sale is still there once, and a second run has nothing left to do.
    assert len(names) == len(rows)
    assert agent_names.repair_agent_names(warehouse)["rows_rewritten"] == 0


def test_one_confirmed_word_is_never_enough() -> None:
    # "Maz" was confirmed in front of 15 buildings, yet one word alone must not strip a name.
    assert "k >= 2 AND prefix IN (SELECT prefix FROM agents) AS confirmed_agent" in (
        agent_names.FIND_RARE_REPAIRS_SQL
    )
    # Weaker repairs do not confirm further agents.
    assert f"AND NOT {agent_names.DOUBTFUL}" in agent_names.FIND_RARE_REPAIRS_SQL


@live
def test_a_reviewed_real_building_gets_its_raw_name_back(warehouse) -> None:  # noqa: F811
    columns = [
        "sale_key", "transaction_date", "building_name", "building_key", "area_name", "area_key",
        "size_sqft", "sale_amount_aed", "loaded_at",
    ]  # fmt: skip
    rows = _sale("t", "Tower", 6) + _sale("j", "Jamal Tower") + _sale("k", "Jamal Tower")
    warehouse.insert_rows(table="dxbi_sales_unit_events", rows=rows, column_names=columns)

    def names() -> dict[str, str]:
        return {
            str(row[0]): str(row[1])
            for row in warehouse.query(
                "SELECT sale_key, building_name FROM dxbi_sales_unit_events FINAL"
            ).result_rows
        }

    agent_names.repair_agent_names(warehouse)
    assert names()["j-0"] == "Tower"
    # The repair records the sales it changed.
    keys = warehouse.query(
        f"SELECT sale_keys FROM {agent_names.REPAIRS_TABLE} WHERE raw_building_name = 'Jamal Tower'"
    ).result_rows[0][0]
    assert sorted(keys) == ["j-0", "k-0"]

    # A review finds "Jamal Tower" is a real building.
    warehouse.command(
        f"INSERT INTO {agent_names.REPAIRS_TABLE} ({agent_names.INSERT_COLUMNS}) VALUES "
        "('dubai marina', 'Jamal Tower', 'Jamal Tower', 'Jamal', 'reviewed', 2, now64(3), "
        "['j-0', 'k-0'])"
    )
    result = agent_names.repair_agent_names(warehouse)
    after = names()
    assert after["j-0"] == "Jamal Tower" and after["k-0"] == "Jamal Tower"
    assert result["rows_restored"] == 2 and len(after) == len(rows)
    assert agent_names.repair_agent_names(warehouse)["rows_restored"] == 0
    unserved = {row[0] for row in warehouse.query(agent_names.UNSERVED_NAMES_SQL).result_rows}
    assert "Jamal Tower" not in unserved


def test_the_title_check_tells_a_reload_from_a_rescrape(tmp_path) -> None:
    import importlib.util
    import json
    from pathlib import Path

    script = Path(__file__).parents[1] / "scripts" / "check_dxbi_sales_titles.py"
    spec = importlib.util.spec_from_file_location("check_dxbi_sales_titles", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    text = "Buyer's agent Sheetal Lakeshore Tower 1, Al Thanyah Fifth Ready Apartment, Floor 3, No. 301"

    def row(html: str, key: str) -> str:
        return json.dumps(
            {
                "transaction_type": "sales", "unit_number": "301", "location_text": text,
                "amount_text": "AED 1,050,000 AED 1,500 /sqft", "specs_text": "700 sqft 1 Bed",
                "date_text": "20, Jun 2024 Individual", "detail_url": f"https://x/sold/t-{key}",
                "columns": [{"id": "PATH_NAME", "text": text, "html": html}],
            }
        )  # fmt: skip

    titled = tmp_path / "titled.jsonl"
    titled.write_text(
        row('<span class="bold-title" title="Lakeshore Tower 1, Al Thanyah Fifth">x</span>', "a")
    )
    untitled = tmp_path / "untitled.jsonl"
    untitled.write_text(row("", "b"))
    # A title fixes the building; a row without one must be re-scraped.
    assert module.check(titled) == {
        "rows": 1, "sales": 1, "with_title": 1, "building_changes": 1, "unreadable": 0
    }  # fmt: skip
    assert module.check(untitled)["with_title"] == 0
