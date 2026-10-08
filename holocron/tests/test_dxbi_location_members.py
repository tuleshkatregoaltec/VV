import gzip
import importlib.util
import json
import os
from datetime import date
from pathlib import Path
from types import ModuleType

import pytest

from tests.test_market_release import _settings, database  # noqa: F401


def _load_script(name: str) -> ModuleType:
    path = Path(__file__).parents[1] / "scripts" / name
    spec = importlib.util.spec_from_file_location(name.removesuffix(".py"), path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# A slice of DXBI's location list (property/website/DLDLOV), read 2026-10-07.
TREE = [
    {"id": 1, "name": "Dubai", "parent_id": None, "flag": "C", "dv": "Dubai", "slug": "dubai"},
    {"id": 31498, "name": "Al Barsha South Fourth", "parent_id": 1, "flag": "A",
     "dv": "Al Barsha South Fourth", "slug": "al-barsha-south-fourth"},
    {"id": 36510, "name": "Jumeirah Village Circle", "parent_id": 31498, "flag": "M",
     "dv": "Jumeirah Village Circle (JVC)", "slug": "jumeirah-village-circle"},
    {"id": 50441, "name": "Binghatti Royale", "parent_id": 36510, "flag": "B",
     "dv": "Binghatti Royale", "slug": "binghatti-royale"},
]  # fmt: skip


def test_each_area_and_community_knows_the_areas_above_it() -> None:
    """A JVC sale is on DXBI's JVC page and on its DLD area's page, Al Barsha South Fourth. A row
    printed "Al Barsha South 4" finds that area by its key."""
    loader = _load_script("load_dxbi_location_members.py")
    rows = {row[0]: dict(zip(loader.LOCATION_COLUMNS, row, strict=True)) for row in
            loader.location_rows(TREE, "run")}  # fmt: skip

    assert set(rows) == {31498, 36510}  # buildings and the city are not Location choices
    assert rows[36510]["lineage"] == ["Jumeirah Village Circle", "Al Barsha South Fourth"]
    assert rows[36510]["display_name"] == "Jumeirah Village Circle (JVC)"
    assert rows[31498]["lineage"] == ["Al Barsha South Fourth"]
    assert rows[31498]["name_key"] == "albarshasouth4"


def test_swept_sales_are_recorded_under_the_location_that_returned_them(tmp_path: Path) -> None:
    loader = _load_script("load_dxbi_location_members.py")
    record = {
        "transaction_type": "sales",
        "source_location": {"id": "36510", "text": "Jumeirah Village Circle (JVC)"},
        "window": {"start": "2025-10-01", "end": "2026-10-07"},
        "columns": [
            {
                "id": "PATH_NAME",
                "text": "Buyer's agent Hajar Binghatti Royale, Al Barsha South 4 Ready Apartment, "
                "Floor u-hidden, No. 1203",
                "html": '<span class="bold-title" title="Binghatti Royale, Al Barsha South 4">',
                "links": [{"href": "https://dxbinteract.com/sold/t-abc"}],
            },
            {"id": "TOTAL_PRICE", "text": "AED 1,050,000 (+5%) AED 1,500 /sqft"},
            {"id": "BEDROOM", "text": "700 sqft 1 Bed"},
            {"id": "SOLD_BY", "text": "20, Jun 2026 Individual (2 Times)"},
        ],
    }
    with gzip.open(tmp_path / "location=36510.jsonl.gz", "wt") as handle:
        handle.write(json.dumps(record) + "\n")
        handle.write(json.dumps({**record, "columns": []}) + "\n")

    rows, skipped = loader.member_rows(tmp_path, {36510: "Jumeirah Village Circle"}, "run")

    assert skipped == 1
    member = dict(zip(loader.MEMBER_COLUMNS, rows[0], strict=True))
    assert member["location_name"] == "Jumeirah Village Circle"
    assert (member["building_key"], member["area_key"]) == ("binghattiroyale", "albarshasouth4")
    assert member["transaction_date"] == date(2026, 6, 20)
    assert member["window_end"] == date(2026, 10, 7)


def test_a_swept_lease_has_the_contract_key_the_lease_load_gives_it(tmp_path: Path) -> None:
    """DXBI's rental area pages group leases their own way too; the sweep records them by the
    lease's contract key, so the key must be the one the daily lease load stores."""
    from holocron.sources.dxbi.rental_events import normalize_rental_rows

    loader = _load_script("load_dxbi_location_members.py")
    columns = [
        {
            "id": "PATH_NAME",
            "text": "Binghatti Royale, Jumeirah Village Circle Apartment, No. 1203",
        },
        {"id": "PROP_SIZES", "text": "1 Bed 700 sqft"},
        {"id": "TOTAL_PRICES", "text": "65,000 New"},
        {"id": "START_DATE", "text": "20 Aug, 2026 - 19 Aug, 2027 12 Months"},
    ]
    daily = {
        "source_account": "account-c",
        "filter_profile": {"id": "broad"},
        "source_location": {"id": "1", "text": "Dubai", "slug": "dubai"},
        "configuration_hash": "95e10242d34cd34fd5d4",
        "shard": {"date": "2026-08-20"},
        "source_run_id": "2026-10-07-aug-oct",
        "columns": columns,
    }
    stored = normalize_rental_rows([(daily, "/r/date=2026-08-20/a.jsonl.gz", "account-c")])
    swept = {
        "transaction_type": "rentals",
        "source_location": {"id": "36510", "text": "Jumeirah Village Circle (JVC)"},
        "window": {"start": "2025-10-01", "end": "2026-10-07"},
        "columns": columns,
    }
    with gzip.open(tmp_path / "location=36510.jsonl.gz", "wt") as handle:
        handle.write(json.dumps(swept) + "\n")

    rows, skipped = loader.lease_member_rows(tmp_path, {36510: "Jumeirah Village Circle"}, "run")

    assert skipped == 0
    member = dict(zip(loader.LEASE_MEMBER_COLUMNS, rows[0], strict=True))
    assert member["contract_key"] == stored.events[0]["contract_key"]
    assert (member["location_name"], member["lease_start"]) == (
        "Jumeirah Village Circle",
        date(2026, 8, 20),
    )


def _sweep_dir(tmp_path: Path, name: str, window: tuple[str, str], **summary) -> Path:
    run = tmp_path / f"run={name}"
    run.mkdir()
    (run / "_SUCCESS").touch()
    (run / "summary.json").write_text(
        json.dumps({"window": {"start": window[0], "end": window[1]}, "incomplete": [], **summary})
    )
    (run / "locations.json").write_text(json.dumps({"items": TREE}))
    return run


def test_only_a_whole_sweep_may_replace_members(tmp_path: Path) -> None:
    """A nightly run that stopped early, or lost a location, must not replace two weeks of
    membership with part of it."""
    import pytest

    loader = _load_script("load_dxbi_location_members.py")
    whole = _sweep_dir(tmp_path, "whole", ("2026-09-24", "2026-10-07"), report="rentals")
    assert loader.read_sweep(whole).report == "rentals"
    assert (loader.read_sweep(whole).first, loader.read_sweep(whole).last) == (
        date(2026, 9, 24),
        date(2026, 10, 7),
    )

    unfinished = _sweep_dir(tmp_path, "unfinished", ("2026-09-24", "2026-10-07"))
    (unfinished / "_SUCCESS").unlink()
    with pytest.raises(SystemExit, match="no _SUCCESS"):
        loader.read_sweep(unfinished)

    partial = _sweep_dir(tmp_path, "partial", ("2026-09-24", "2026-10-07"), incomplete=["36510"])
    with pytest.raises(SystemExit, match="incomplete"):
        loader.read_sweep(partial)


@pytest.mark.skipif(
    os.environ.get("HOLOCRON_CLICKHOUSE_INTEGRATION") != "1",
    reason="set HOLOCRON_CLICKHOUSE_INTEGRATION=1 with local ClickHouse",
)
def test_a_nightly_sweep_replaces_its_window_and_keeps_the_year(
    tmp_path: Path,
    database: str,  # noqa: F811
) -> None:
    """The first sweep covers a year; each night covers the last two weeks. A night replaces the
    members dated in its window (DXBI may regroup a recent sale) and keeps every older date;
    loading the same night twice changes nothing."""
    import clickhouse_connect

    loader = _load_script("load_dxbi_location_members.py")
    settings = _settings(database)
    client = clickhouse_connect.get_client(
        host=settings.clickhouse_host,
        port=settings.clickhouse_port,
        username=settings.clickhouse_user,
        password=settings.clickhouse_password,
        database=database,
    )

    def member(key: str, day: date, location: str) -> list[object]:
        return [36510, location, key, day, "b", "a", date(2025, 10, 1), date(2026, 10, 7), "r"]

    client.command(loader.CREATE_MEMBERS_SQL)
    client.insert(
        loader.MEMBERS_TABLE,
        [
            member("old", date(2026, 3, 1), "Jumeirah Village Circle"),
            member("recent", date(2026, 10, 1), "Jumeirah Village Circle"),
            member("gone", date(2026, 10, 2), "Jumeirah Village Circle"),
        ],
        column_names=loader.MEMBER_COLUMNS,
    )
    night = loader.Sweep(tmp_path, "sales", date(2026, 9, 24), date(2026, 10, 7))
    tonight = [member("recent", date(2026, 10, 1), "Al Barsha South Fourth")]

    assert loader.replace_window(client, night, tonight) == 2
    assert loader.replace_window(client, night, tonight) == 1  # the same night again
    assert client.query(
        f"SELECT sale_key, location_name FROM {loader.MEMBERS_TABLE} FINAL ORDER BY sale_key"
    ).result_rows == [("old", "Jumeirah Village Circle"), ("recent", "Al Barsha South Fourth")]
