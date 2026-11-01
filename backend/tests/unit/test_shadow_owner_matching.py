"""The shadow run must show the user what the new matcher would do, without hiding anything.

Fixture world: one Damac Hills 2 tower (Navitas E, unit 1410, sold twice), a same-price sale of a
different unit elsewhere, and a DLD-only Transactions sale. Five workbook rows exercise each
colour; the baseline file holds one old accepted link per row, one for each comparison category.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from openpyxl import Workbook, load_workbook

from app.crm.owner_matcher import MatchResult
from scripts.crm import shadow_owner_matching as shadow

FILENAME = "Fixture Tower.xlsx"
SHEET = "Sheet1"
OWNER = "Zainab Fixture-Owner"
PHONE = "0501234567"
NAVITAS = "NAVITAS ( E )@AKOYA OXYGEN"
COMMUNITIES = ("damachills2", "damachills", "alfurjan")
# Analytics buildings: a sheet label restricts the place only when it is one of these.
BUILDINGS = (
    ("damachills2", "navitastowere"),
    ("damachills2", "viridisa"),
    ("damachills2", "viridisb"),
)

HEADERS = [
    "NameEn",
    "Mobile",
    "Project",
    "BuildingNameEn",
    "UnitNumber",
    "Size",
    "ProcedureValue",
    "Regis",
    "ProcedurePartyTypeNameEn",
    "ProcedureNameEn",
]
# row 2 matched_sale, 3 property only, 4 size conflict (no sale at its price), 5 no place, 6 only Transactions has it
ROWS = [
    [
        OWNER,
        PHONE,
        "DAMAC HILLS 2",
        NAVITAS,
        1410,
        31.01,
        460000,
        datetime(2022, 5, 20),
        "Buyer",
        "Sell",
    ],
    [
        OWNER,
        PHONE,
        "DAMAC HILLS 2",
        NAVITAS,
        1410,
        31.01,
        999000,
        datetime(2022, 5, 20),
        "Buyer",
        "Sell",
    ],
    [
        OWNER,
        PHONE,
        "DAMAC HILLS 2",
        NAVITAS,
        1410,
        100,
        999000,
        datetime(2022, 5, 20),
        "Buyer",
        "Sell",
    ],
    [OWNER, PHONE, None, None, None, None, 460000, datetime(2022, 5, 20), "Buyer", "Sell"],
    [
        OWNER,
        PHONE,
        "DAMAC HILLS 2",
        NAVITAS,
        2222,
        31.0,
        510000,
        datetime(2022, 5, 20),
        "Buyer",
        "Sell",
    ],
]
WANT = {
    2: "matched_sale",
    3: "property_confirmed_no_sale",
    4: "rejected",
    5: "no_evidence",
    6: "matched_registry_sale",
}


def key(row: int) -> str:
    return shadow.row_key(FILENAME, SHEET, row)


def event(family: str, amount: float, day: str, ekey: str, **fields: Any) -> dict[str, Any]:
    payload = {
        "event_key": ekey,
        "unit_number": "1410",
        "building_name": "Navitas Tower E",
        "project_name": "Navitas",
        "area_name": "Damac Hills 2",
        "size_sqft": 334.0,
        "property_type": "Apartment",
        "transaction_date": day,
        **fields,
    }
    return {"family": family, "amount": amount, "event_date": day, "payload": payload}


EVENTS = [
    event("sale", 441750, "2016-10-06", "k1"),
    event("sale", 460000, "2022-05-20", "k2"),
    event(
        "sale",
        750000,
        "2026-09-18",
        "k3",
        building_name="Viridis A",
        project_name="Viridis",
        size_sqft=804.0,
    ),
    event("rental", 30000, "2025-01-01", "k4"),
    event(
        "sale",
        460000,
        "2021-01-01",
        "k5",
        building_name="Golf Vita - A",
        project_name="Golf Vita",
        area_name="Damac Hills",
        size_sqft=428.0,
    ),
    event(
        "sale",
        800000,
        "2020-01-01",
        "k6",
        building_name="Viridis B",
        project_name="Viridis",
        size_sqft=804.0,
        unit_number="77",
    ),
]
REGISTRY = [
    {
        "instance_date": "2023-08-28",
        "procedure_name_en": "Sell",
        "actual_worth": 510000,
        "procedure_area": 31.0,
        "property_type_en": "Unit",
        "area_name_en": "Wadi Al Safa 5",
        "master_project_en": "DAMAC HILLS 2",
        "project_name_en": "NAVITAS",
        "building_name_en": "Navitas Tower E",
        "unit_number": "",
        "community_name": "Damac Hills 2",
        "match_status": "dld_only",
        "dxbi_sale_key": "",
        "transaction_id": "t-1",
    },
    {  # a mortgage at the same price must never be a sale
        "instance_date": "2023-09-01",
        "procedure_name_en": "Mortgage Registration",
        "actual_worth": 510000,
        "procedure_area": 31.0,
        "property_type_en": "Unit",
        "area_name_en": "Wadi Al Safa 5",
        "master_project_en": "DAMAC HILLS 2",
        "project_name_en": "NAVITAS",
        "building_name_en": "Navitas Tower E",
        "unit_number": "",
        "community_name": "Damac Hills 2",
        "match_status": "dld_only",
        "dxbi_sale_key": "",
        "transaction_id": "t-2",
    },
    {  # a row without a price can never be matched on price
        "instance_date": "2023-09-02",
        "procedure_name_en": "Sell",
        "actual_worth": 0,
        "procedure_area": 31.0,
        "property_type_en": "Unit",
        "area_name_en": "Wadi Al Safa 5",
        "master_project_en": "DAMAC HILLS 2",
        "project_name_en": "NAVITAS",
        "building_name_en": "Navitas Tower E",
        "unit_number": "",
        "community_name": "Damac Hills 2",
        "match_status": "dld_only",
        "dxbi_sale_key": "",
        "transaction_id": "t-3",
    },
]
# one old accepted link per row; k2 is the 2022 sale, k3 is a different unit's sale
BASELINE = {2: "k2", 3: "k1", 4: "k2", 5: "k2", 6: "k3"}
BASELINE_WANT = {
    2: "same_sale",
    3: "now_property_only",
    4: "now_rejected",
    5: "now_no_evidence",
    6: "different_sale",
}
BUCKETS = {
    2: "identified_property_no_sale_within_2_aed",
    3: "identified_property_no_sale_within_2_aed",
}


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "wt", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row) + "\n")


@pytest.fixture
def data(tmp_path: Path) -> Path:
    root = tmp_path / "data"
    (root / "sources").mkdir(parents=True)
    (root / "dxbi").mkdir()
    (root / "experiment").mkdir()
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = SHEET
    sheet.append(HEADERS)
    for row in ROWS:
        sheet.append(row)
    workbook.save(root / "sources" / FILENAME)

    database = sqlite3.connect(root / "dxbi" / "snapshot.sqlite")
    database.execute(
        "CREATE TABLE event(family TEXT, amount REAL, identity TEXT, event_date TEXT, payload TEXT)"
    )
    for item in EVENTS:
        database.execute(
            "INSERT INTO event VALUES (?, ?, '[]', ?, ?)",
            (item["family"], item["amount"], item["event_date"], json.dumps(item["payload"])),
        )
    database.commit()
    database.close()

    write_jsonl(root / "transactions.jsonl", REGISTRY)
    (root / "transactions.meta.json").write_text(
        json.dumps({"row_count": 3, "max_built_at": "2026-10-21 14:08:31.475"})
    )
    (root / "building-keys.json").write_text(
        json.dumps(
            [{"name_key": c, "community_key": c} for c in COMMUNITIES]
            + [{"name_key": name, "community_key": community} for community, name in BUILDINGS]
        )
    )
    write_jsonl(
        root / "experiment" / "baseline-matched.jsonl",
        [
            {
                "row_key": key(row),
                "filename": FILENAME,
                "sheet": SHEET,
                "row": row,
                "current_match": {"status": "matched", "selected_event_key": f"sale:{old}"},
            }
            for row, old in BASELINE.items()
        ],
    )
    write_jsonl(
        root / "experiment" / "all-rows.jsonl",
        [
            {
                "row_key": key(row),
                "filename": FILENAME,
                "sheet": SHEET,
                "row": row,
                "current_status": "former_owner",
                "primary_cause": BUCKETS.get(row),
            }
            for row in range(2, 7)
        ],
    )
    write_jsonl(
        root / "experiment" / "final-row-results.jsonl.gz",
        [{"row_key": key(row), "report_status": "tentative"} for row in BUCKETS],
    )
    return root


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_events_load_as_slim_dicts_and_baseline_events_are_remembered(data: Path) -> None:
    events, remembered = shadow.load_events(data / "dxbi" / "snapshot.sqlite", {"k1"})
    assert len(events) == 6
    sale = next(e for e in events if e["event_key"] == "k2")
    assert (sale["family"], sale["amount"], sale["event_date"]) == ("sale", 460000.0, "2022-05-20")
    assert (sale["unit_number"], sale["building_name"], sale["size_sqft"]) == (
        "1410",
        "Navitas Tower E",
        334.0,
    )
    assert set(remembered) == {"k1"}  # only the events an old link points at, not all 6


def test_transactions_drop_financing_and_rows_without_a_price(data: Path) -> None:
    rows = shadow.load_transactions(data / "transactions.jsonl")
    assert [r["transaction_id"] for r in rows] == ["t-1"]


def test_workbook_rows_carry_property_fields_but_never_owner_fields_to_the_matcher(
    data: Path,
) -> None:
    sheets = shadow.read_workbook(data / "sources" / FILENAME, saved=None)
    (sheet,) = sheets
    assert [r.row for r in sheet.rows] == [2, 3, 4, 5, 6]
    first = sheet.rows[0]
    assert first.source["building_name"] == NAVITAS
    assert first.source["unit_number"] == "1410"
    assert first.source["transaction_price_aed"] == "460000"
    assert first.source["transaction_date"] == "2022-05-20"
    assert first.source["size_unknown"] == "31.01"
    assert first.source["procedure_type"] == "Sell"  # the matcher needs it to spot financing rows
    assert OWNER not in json.dumps(first.source) and PHONE not in json.dumps(first.source)
    assert first.columns["NameEn"] == OWNER  # but the review workbook keeps the original columns


def test_a_financing_procedure_reaches_the_matcher_and_the_row_links_no_sale(
    data: Path, tmp_path: Path
) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = SHEET
    sheet.append(HEADERS)
    # dated on a day the unit did not sell, so the same-day mortgage rule does not apply
    sheet.append([*ROWS[0][:7], datetime(2021, 3, 1), "Buyer", "Mortgage Registration"])
    path = tmp_path / FILENAME
    workbook.save(path)
    (rows,) = shadow.read_workbook(path, saved=None)
    (row,) = rows.rows
    assert row.source["procedure_type"] == "Mortgage Registration"
    events, _ = shadow.load_events(data / "dxbi" / "snapshot.sqlite", set())
    index = shadow.SalesIndex(events, shadow.load_places(data / "building-keys.json"), [])
    result = shadow.match_row(row.source, index)
    assert result.outcome == "property_confirmed_no_sale" and result.sale is None
    assert "financing_row" in result.reasons


def test_mapping_is_saved_then_reused(data: Path) -> None:
    (sheet,) = shadow.read_workbook(data / "sources" / FILENAME, saved=None)
    saved = [sheet.mapping]
    assert sheet.mapping["field_map"]["transaction_price_aed"] == "ProcedureValue"
    (again,) = shadow.read_workbook(data / "sources" / FILENAME, saved=saved)
    assert again.mapping["field_map"] == sheet.mapping["field_map"]
    assert again.profile.mapping_source != "heuristic"


@pytest.mark.parametrize(
    ("old", "outcome", "sale_key", "expected"),
    [
        ("k2", "matched_sale", "k2", "same_sale"),
        ("k2", "matched_sale_review", "k9", "different_sale"),
        ("k2", "matched_registry_sale", "k2", "same_sale"),
        ("k2", "property_confirmed_no_sale", None, "now_property_only"),
        ("k2", "rejected", None, "now_rejected"),
        ("k2", "no_evidence", None, "now_no_evidence"),
    ],
)
def test_baseline_categories(old: str, outcome: str, sale_key: str | None, expected: str) -> None:
    sale = {"event_key": sale_key, "dxbi_sale_key": sale_key} if sale_key else None
    result = MatchResult(outcome, None, sale)  # type: ignore[arg-type]
    assert shadow.compare_baseline(old, result) == expected


def test_a_registry_sale_is_the_same_sale_when_it_carries_the_dxbi_key() -> None:
    sale = {"actual_worth": 5, "dxbi_sale_key": "k2", "transaction_id": "t-9"}
    assert shadow.compare_baseline("k2", MatchResult("matched_registry_sale", None, sale)) == (
        "same_sale"
    )


def run(data: Path, tmp_path: Path, acceptance: Any = None) -> Path:
    output = tmp_path / "out" / "owner-import-matching-v2"
    shadow.main(
        [
            "--data-root",
            str(data),
            "--transactions",
            str(data / "transactions.jsonl"),
            "--output",
            str(output),
        ],
        acceptance=acceptance if acceptance is not None else ACCEPTANCE,
    )
    return output


ACCEPTANCE = [
    shadow.Acceptance(
        FILENAME, SHEET, 2, "matched_sale", sale_amount=460000, sale_date="2022-05-20"
    ),
    shadow.Acceptance(
        FILENAME,
        SHEET,
        6,
        "matched_registry_sale",
        sale_amount=510000,
        sale_date="2023-08-28",
        never_text=("Viridis",),
    ),
    shadow.Acceptance(FILENAME, SHEET, 3, "matched_sale"),  # deliberately wrong: must report fail
]


def test_shadow_run_writes_colours_and_acceptance_rows(data: Path, tmp_path: Path) -> None:
    output = run(data, tmp_path)

    workbook = load_workbook(output / "Owner-Matching-v2.xlsx", read_only=False)
    assert workbook.sheetnames == ["Summary", "All rows", "Baseline check"]
    lines = dict(workbook["Summary"].iter_rows(values_only=True))
    assert lines["Bucket: identified_property_no_sale_within_2_aed"] == (
        "2 rows; old matched 0; new matched 1; new review 0"
    )
    rows = list(workbook["All rows"].iter_rows())
    header = [c.value for c in rows[0]]
    outcome_col = header.index("Outcome")
    got = {r[header.index("Row")].value: r[outcome_col] for r in rows[1:]}
    assert {row: cell.value for row, cell in got.items()} == WANT
    colour = {row: cell.fill.fgColor.rgb[-6:] for row, cell in got.items()}
    assert colour[2] == shadow.COLOURS["matched_sale"][-6:]
    assert colour[6] == shadow.COLOURS["matched_registry_sale"][-6:]
    assert colour[3] == shadow.COLOURS["property_confirmed_no_sale"][-6:]
    assert colour[4] == shadow.COLOURS["rejected"][-6:]
    assert colour[5] == shadow.COLOURS["no_evidence"][-6:]
    assert colour[2] == colour[6]  # both are sales found in a registry
    assert len({colour[r] for r in (2, 3, 4, 5)}) == 4
    row2 = {h: c.value for h, c in zip(header, rows[1], strict=False)}
    assert row2["Matched unit"] == "1410" and row2["Matched building"] == "Navitas Tower E"
    assert row2["Matched amount AED"] == 460000 and row2["Matched date"] == "2022-05-20"
    assert row2["Matched sqft"] == 334 and row2["Matched source"] == "DXBI"
    assert row2["Old status"] == "former_owner" and row2["NameEn"] == OWNER
    row6 = {h: c.value for h, c in zip(header, rows[5], strict=False)}
    assert row6["Matched source"] == "Transactions dld_only" and row6["Matched unit"] in (None, "")
    row3 = {h: c.value for h, c in zip(header, rows[2], strict=False)}
    assert row3["Original bucket"] == "identified_property_no_sale_within_2_aed"
    assert row3["Old experiment status"] == "tentative"

    baseline = list(workbook["Baseline check"].iter_rows(values_only=True))
    names = list(baseline[0])
    by_row = {r[names.index("Row")]: r[names.index("Comparison")] for r in baseline[1:]}
    assert by_row == BASELINE_WANT
    different = next(r for r in baseline[1:] if r[names.index("Row")] == 6)
    assert different[names.index("Old building")] == "Viridis A"
    assert different[names.index("New building")] == "Navitas Tower E"


def test_summary_json_counts_and_acceptance_and_no_owner_values(data: Path, tmp_path: Path) -> None:
    output = run(data, tmp_path)
    text = (output / "summary.json").read_text()
    assert OWNER not in text and PHONE not in text and "Fixture-Owner" not in text
    summary = json.loads(text)
    assert summary["outcomes"] == {
        "matched_sale": 1,
        "property_confirmed_no_sale": 1,
        "rejected": 1,
        "no_evidence": 1,
        "matched_registry_sale": 1,
    }
    assert summary["rows"] == 5
    assert summary["baseline"] == {
        "same_sale": 1,
        "now_property_only": 1,
        "now_rejected": 1,
        "now_no_evidence": 1,
        "different_sale": 1,
    }
    bucket = summary["buckets"]["identified_property_no_sale_within_2_aed"]
    assert bucket["rows"] == 2
    assert bucket["old"] == {"tentative": 2}
    assert bucket["new"] == {"matched_sale": 1, "property_confirmed_no_sale": 1}
    assert summary["focus"]["rows"] == 2
    assert summary["focus"]["old_matched"] == 0 and summary["focus"]["new_matched"] == 1
    assert [e["row"] for e in summary["examples"]["different_sale"]] == [6]
    assert [e["row"] for e in summary["examples"]["now_rejected"]] == [4]
    verdicts = {a["row"]: a["pass"] for a in summary["acceptance"]}
    assert verdicts == {2: True, 6: True, 3: False}
    assert summary["transactions"]["export_row_count"] == 3
    assert summary["transactions"]["max_built_at"] == "2026-10-21 14:08:31.475"
    assert summary["fingerprints"]["sources"][FILENAME] == sha(data / "sources" / FILENAME)
    assert summary["runtime_seconds"] >= 0
    assert summary["matcher_version"] == "property-first-2"


def test_output_folder_is_never_overwritten(data: Path, tmp_path: Path) -> None:
    output = run(data, tmp_path)
    with pytest.raises(FileExistsError):
        run(data, tmp_path)
    assert (output / "summary.json").exists()


def test_mappings_are_written_once_beside_the_data(data: Path, tmp_path: Path) -> None:
    run(data, tmp_path)
    saved = json.loads((data / "mappings-v2.json").read_text())
    assert saved[FILENAME][0]["field_map"]["contact_name"] == "NameEn"


def test_the_seven_trial_rows_are_the_acceptance_table() -> None:
    rows = {(a.filename, a.row): a.outcome for a in shadow.R3_ACCEPTANCE}
    assert len(rows) == 7
    assert rows[("Furjan JAN 2025.xlsx", 5261)] == "matched_registry_sale"
    assert rows[("Arabian Ranches 3 F April 2024 SVR.xlsx", 6494)] == "matched_sale_review"
    assert rows[("Damac hills 2 April 2024.xlsx", 18611)] == "matched_sale_inferred_unit"


def test_cached_places_answer_exactly_like_the_plain_place_index(data: Path) -> None:
    """The cache is only a speed-up: a different answer would change which sale a row matches."""
    from app.crm.owner_places import PlaceIndex, load_place_aliases

    projects, masters = load_place_aliases()
    keys = [{"name_key": c, "community_key": c} for c in COMMUNITIES] + [
        {"name_key": name, "community_key": community} for community, name in BUILDINGS
    ]
    plain, cached = (
        PlaceIndex(keys, projects, masters),
        shadow.load_places(data / "building-keys.json"),
    )
    events, _ = shadow.load_events(data / "dxbi" / "snapshot.sqlite", set())
    sources = [
        {"project_name": "DAMAC HILLS 2", "building_name": NAVITAS},
        {"area_name": "Damac Hills"},
    ]
    for _ in range(2):  # the second round answers from the cache
        for source in sources:
            for event in events:
                expected = plain.same_place(plain.source_place(source), plain.event_place(event))
                got = cached.same_place(cached.source_place(source), cached.event_place(event))
                assert got == expected
    assert cached.same_place_hits > 0


def test_a_mortgage_row_on_the_day_of_the_units_sale_is_green_via_mortgage(
    data: Path, tmp_path: Path
) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = SHEET
    sheet.append(HEADERS)
    sheet.append([*ROWS[0][:-1], "Mortgage Registration"])  # dated 2022-05-20, the day of k2
    path = tmp_path / FILENAME
    workbook.save(path)
    (rows,) = shadow.read_workbook(path, saved=None)
    events, _ = shadow.load_events(data / "dxbi" / "snapshot.sqlite", set())
    index = shadow.SalesIndex(events, shadow.load_places(data / "building-keys.json"), [])
    result = shadow.match_row(rows.rows[0].source, index)
    assert result.outcome == "matched_sale_via_mortgage"
    assert shadow.COLOURS[result.outcome] == shadow.COLOURS["matched_sale"]
    assert result.outcome in shadow.MATCHED


def test_the_shadow_run_applies_the_learned_alias_post_pass_per_workbook() -> None:
    from app.crm.owner_matcher import MatchResult

    sale = {"event_key": "k", "unit_number": "715", "building_name": "B5", "amount": 1}
    review = MatchResult("matched_sale_review", None, sale, ["unit differs: x"])
    pair = ({"building_name": "B5", "unit_number": "102"}, review)
    assert shadow.promote_learned_aliases([pair])[0] is review  # one sale is not enough
