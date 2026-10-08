import gzip
import importlib.util
import json
from datetime import date
from pathlib import Path
from types import ModuleType


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
