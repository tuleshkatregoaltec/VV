import importlib.util
import json
import os
from datetime import date
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from tests.test_market_release import _settings, database  # noqa: F401

live = pytest.mark.skipif(
    os.environ.get("HOLOCRON_CLICKHOUSE_INTEGRATION") != "1",
    reason="set HOLOCRON_CLICKHOUSE_INTEGRATION=1 with local ClickHouse",
)


def _load_script(name: str) -> ModuleType:
    path = Path(__file__).parents[1] / "scripts" / name
    spec = importlib.util.spec_from_file_location(name.removesuffix(".py"), path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeClient:
    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []

    def insert(self, table: str, rows: list[list[object]], *, column_names: list[str]) -> None:
        self.rows.extend(dict(zip(column_names, row, strict=True)) for row in rows)


def _sale(search: tuple[int, int], *, unit: str = "", url: str = "", building: str) -> dict:
    """A scraper record: one row of DXBI's sales report for one day and price range."""
    return {
        "transaction_type": "sales",
        "bucket_date": "2026-06-20",
        "bucket_min_price": search[0],
        "bucket_max_price": search[1],
        "unit_number": unit,
        "location_text": f"{building}, Dubai Hills Estate Offplan Villa",
        "amount_text": "AED 4,000,000 (-) AED 1,000 /sqft",
        "specs_text": "4,000 sqft 4 Beds",
        "date_text": "20, Jun 2026 Developer",
        "detail_url": url,
    }


def test_sales_without_a_unit_are_loaded_and_identical_ones_stay_apart(tmp_path: Path) -> None:
    """A developer can sell two identical villas on one day at one price; with the units hidden
    DXBI lists two rows with the same terms, and both are sales. The scraper splits each day by
    price, and neighbouring price ranges share their boundary price, so the same sale can also come
    back from two searches: it must load once."""
    loader = _load_script("load_dxbi_sales_units.py")
    first, neighbour = (3_500_000, 4_000_000), (4_000_000, 4_500_000)
    path = tmp_path / "dxbi_sales_dynamic_2026-06-21.jsonl"
    rows = [
        _sale(first, building="Elie Saab"),
        _sale(first, building="Elie Saab"),
        _sale(neighbour, building="Elie Saab"),
        _sale(
            neighbour, unit="V-12", url="https://dxbinteract.com/sold/t-v12", building="Elie Saab"
        ),
        {"unit_number": "", "location_text": "", "amount_text": "", "date_text": ""},
    ]
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    client = FakeClient()

    totals = loader.load_files([path], client=client, batch_size=100)

    assert totals == {"loaded": 4, "skipped": 1, "errors": 0, "without_unit": 3}
    hidden = [row["sale_key"] for row in client.rows if row["unit_number"] == ""]
    assert len(hidden) == 3
    assert len(set(hidden)) == 2  # two sales: the neighbouring search repeats the first
    assert hidden[1] == f"{hidden[0]}-2"
    assert hidden[2] == hidden[0]


@live
def test_a_reloaded_sale_with_a_corrected_building_is_kept_once(database: str) -> None:  # noqa: F811
    """The table's sort key holds the building, so FINAL keeps the agent-glued and the corrected
    versions of one sale side by side; the Radar's activity counts would count it twice."""
    import clickhouse_connect

    loader = _load_script("load_dxbi_sales_units.py")
    settings = _settings(database)
    client = clickhouse_connect.get_client(
        host=settings.clickhouse_host,
        port=settings.clickhouse_port,
        username=settings.clickhouse_user,
        password=settings.clickhouse_password,
        database=database,
    )
    client.command(loader.CREATE_SALES_SQL)
    columns = ["sale_key", "transaction_date", "unit_number", "building_name", "building_key"]
    day = date(2026, 6, 20)
    client.insert(
        loader.SALES_TABLE,
        [
            ["k1", day, "1203", "Hajar Binghatti Royale", "hajarbinghattiroyale"],
            ["k2", day, "604", "Tower One", "towerone"],
        ],
        column_names=columns,
    )
    client.insert(
        loader.SALES_TABLE,
        [["k1", day, "1203", "Binghatti Royale", "binghattiroyale"]],
        column_names=columns,
    )
    client.command(f"OPTIMIZE TABLE {loader.SALES_TABLE} FINAL")

    assert loader.remove_superseded_sales(client) == 1
    assert client.query(
        f"SELECT sale_key, building_name FROM {loader.SALES_TABLE} FINAL ORDER BY sale_key"
    ).result_rows == [("k1", "Binghatti Royale"), ("k2", "Tower One")]
    assert loader.remove_superseded_sales(client) == 0


@live
def test_a_complete_rescrape_replaces_its_window(database: str) -> None:  # noqa: F811
    """August 1-10 came from DXBI's CSV export: no units and some dates a day off, under keys no
    scraped row shares. DXBI also moves sales between days: on 2026-09-13 (a Sunday) the old load
    held 29 sales DXBI now dates Monday, and lists none that day. A complete re-scrape of a window
    must replace all of it, empty days included, and leave other dates alone."""
    import clickhouse_connect

    loader = _load_script("load_dxbi_sales_units.py")
    settings = _settings(database)
    client = clickhouse_connect.get_client(
        host=settings.clickhouse_host,
        port=settings.clickhouse_port,
        username=settings.clickhouse_user,
        password=settings.clickhouse_password,
        database=database,
    )
    client.command(loader.CREATE_SALES_SQL)
    columns = ["sale_key", "transaction_date", "unit_number", "building_name", "building_key"]
    client.insert(
        loader.SALES_TABLE,
        [
            ["csv-1", date(2026, 8, 1), "", "Tower One", "towerone"],
            ["moved", date(2026, 8, 2), "1503", "15 Cascade", "15cascade"],
            ["kept", date(2026, 7, 31), "604", "Tower One", "towerone"],
        ],
        column_names=columns,
    )
    started = loader.load_clock(client)
    client.insert(
        loader.SALES_TABLE,
        [["t-abc", date(2026, 8, 1), "1203", "Tower One", "towerone"]],
        column_names=columns,
    )

    removed = loader.replace_window(
        client, loaded_since=started, first=date(2026, 8, 1), last=date(2026, 8, 2)
    )

    assert removed == 2
    assert client.query(
        f"SELECT sale_key FROM {loader.SALES_TABLE} FINAL ORDER BY sale_key"
    ).result_rows == [("kept",), ("t-abc",)]
