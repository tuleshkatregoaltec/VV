"""Offline shadow run of the property-first owner matcher over the real owner workbooks.

Reads local files only; it never calls the model, ClickHouse or Postgres. It writes a colour-coded
review workbook and a summary into a NEW folder, so the user can judge the matcher before the live
importer changes. ``Owner-Matching-v2.xlsx`` keeps the original owner/contact columns for local
review; ``summary.json`` carries no owner or contact values.

    cd backend && uv run --with pyarrow python -m scripts.crm.shadow_owner_matching
"""

from __future__ import annotations

import argparse
import collections
import gzip
import hashlib
import json
import sqlite3
import sys
import time
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

import openpyxl
from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

from app.crm.import_mapping import apply_saved_mapping, saved_sheet_for, saved_sheet_mapping
from app.crm.import_parsing import (
    SheetProfile,
    _inspect_xlsx,
    _parse_xlsx,
    matcher_source,
)
from app.crm.owner_identifiers import unit_key
from app.crm.owner_matcher import (
    _FINANCING,
    MATCHER_VERSION,
    MatchResult,
    SalesIndex,
    match_row,
    promote_learned_aliases,
)
from app.crm.owner_matching_policy import SQM_TO_SQFT
from app.crm.owner_places import CachedPlaceIndex, PlaceIndex, load_place_aliases

REPO = Path(__file__).resolve().parents[3]
DEFAULT_DATA = REPO / ".local/owner-recovery/2026-10-29"

COLOURS = {
    "matched_sale": "C6EFCE",
    "matched_registry_sale": "C6EFCE",
    "matched_sale_via_mortgage": "C6EFCE",
    "matched_sale_inferred_unit": "8ED8CC",
    "matched_registry_sale_no_unit": "8ED8CC",
    "matched_sale_review": "FFEB9C",
    "property_confirmed_no_sale": "BDD7EE",
    "rejected": "FFC7CE",
    "no_evidence": "D9D9D9",
}
MATCHED = (
    "matched_sale",
    "matched_sale_via_mortgage",
    "matched_sale_inferred_unit",
    "matched_registry_sale",
    "matched_registry_sale_no_unit",
)
OLD_MATCHED = ("extra_conditional_support", "already_live_recovered")
BASELINE_COLOURS = {
    "same_sale": "C6EFCE",
    "different_sale": "FFEB9C",
    "now_property_only": "BDD7EE",
    "now_rejected": "FFC7CE",
    "now_no_evidence": "D9D9D9",
}
BASELINE_ORDER = tuple(BASELINE_COLOURS)
EXAMPLES = 20

_TRANSACTION_COLUMNS = (
    "instance_date",
    "procedure_name_en",
    "actual_worth",
    "procedure_area",
    "property_type_en",
    "area_name_en",
    "master_project_en",
    "project_name_en",
    "building_name_en",
    "unit_number",
    "community_name",
    "match_status",
    "dxbi_sale_key",
    "transaction_id",
)
_EVENT_FIELDS = (
    "unit_number",
    "building_name",
    "project_name",
    "area_name",
    "size_sqft",
    "property_type",
)


# --------------------------------------------------------------------------- acceptance rows


@dataclass(frozen=True)
class Acceptance:
    """One row the plan's R3 table says must come out a given way."""

    filename: str
    sheet: str
    row: int
    outcome: str
    sale_amount: int | None = None
    sale_date: str | None = None
    sale_unit: str | None = None  # "" means the sale must carry no unit number
    sale_building: str | None = None  # text the matched sale's building must contain
    sale_sqft: float | None = None
    never_text: tuple[str, ...] = ()  # must appear nowhere in the sale or the rejected list


DAMAC = "Damac hills 2 April 2024.xlsx"
FURJAN = "Furjan JAN 2025.xlsx"
AR3 = "Arabian Ranches 3 F April 2024 SVR.xlsx"
R3_ACCEPTANCE = [
    Acceptance(
        DAMAC,
        "Sheet1",
        17157,
        "matched_sale",
        sale_amount=460000,
        sale_date="2022-05-20",
        sale_unit="1410",
        sale_building="Navitas",
    ),
    Acceptance(
        FURJAN,
        "OLD",
        7698,
        "matched_sale",
        sale_amount=687500,
        sale_date="2023-09-13",
        sale_unit="AFNCTH003",
    ),
    Acceptance(
        AR3,
        "Sheet1",
        166,
        "matched_sale",
        sale_amount=2200888,
        sale_date="2021-08-23",
        sale_unit="357",
        sale_building="Ruba",
    ),
    Acceptance(
        DAMAC,
        "Sheet1",
        18611,
        "matched_sale_inferred_unit",
        sale_amount=370000,
        sale_unit="DH2-XL1282B",
    ),
    Acceptance(
        FURJAN,
        "OLD",
        24336,
        "matched_sale",
        sale_amount=1832447,
        sale_date="2020-11-03",
        sale_unit="AFWBTH023",
    ),
    Acceptance(
        FURJAN,
        "OLD",
        5261,
        "matched_registry_sale",
        sale_amount=386400,
        sale_date="2023-08-28",
        sale_unit="",
        sale_sqft=36.93 * 10.7639104167,
        never_text=(),
    ),
    Acceptance(
        AR3,
        "Sheet1",
        6494,
        "matched_sale_review",
        sale_amount=700000,
        sale_date="2023-01-31",
        sale_unit="122",
        sale_building="Sun",
        never_text=("Liwan", "Qpoint"),
    ),
]


# --------------------------------------------------------------------------- small helpers


def row_key(filename: str, sheet: str, row: int) -> str:
    """The key the experiment files use for a source row."""
    return hashlib.sha256(json.dumps([filename, sheet, row]).encode()).hexdigest()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as stream:
        for line in stream:
            yield json.loads(line)


def log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def _intern(value: Any) -> Any:
    return sys.intern(value) if isinstance(value, str) else value


# --------------------------------------------------------------------------- inputs


def load_events(snapshot: Path, keep: set[str]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Every DXBI sale and rental event as a slim dict, plus the events in ``keep`` by key."""
    events: list[dict[str, Any]] = []
    remembered: dict[str, Any] = {}
    database = sqlite3.connect(f"file:{snapshot}?mode=ro", uri=True)
    try:
        for family, amount, event_date, payload in database.execute(
            "SELECT family, amount, event_date, payload FROM event"
        ):
            body = json.loads(payload)
            item = {
                "family": family,
                "amount": amount,
                "event_date": _intern(event_date),
                "event_key": body.get("event_key"),
            }
            for name in _EVENT_FIELDS:
                item[name] = _intern(body.get(name))
            events.append(item)
            if item["event_key"] in keep:
                remembered[item["event_key"]] = item
    finally:
        database.close()
    return events, remembered


def load_transactions(path: Path) -> list[dict[str, Any]]:
    """Transactions (``market_sale_events``) rows with a price that are not financing."""
    rows: list[dict[str, Any]] = []

    def batches() -> Iterator[list[dict[str, Any]]]:
        if path.suffix == ".parquet":
            import pyarrow.parquet as pq  # not a backend dependency: `uv run --with pyarrow`

            parquet = pq.ParquetFile(path)
            for batch in parquet.iter_batches(
                batch_size=100_000, columns=list(_TRANSACTION_COLUMNS)
            ):
                yield batch.to_pylist()
        else:
            yield list(read_jsonl(path))

    for batch in batches():
        for item in batch:
            worth = item.get("actual_worth")
            if not worth or worth <= 0 or _FINANCING.search(str(item.get("procedure_name_en"))):
                continue
            rows.append({name: _intern(item.get(name)) for name in _TRANSACTION_COLUMNS})
    return rows


def load_places(buildings: Path) -> PlaceIndex:
    project_aliases, master_aliases = load_place_aliases()
    return CachedPlaceIndex(json.loads(buildings.read_text()), project_aliases, master_aliases)


# --------------------------------------------------------------------------- workbooks


@dataclass
class SourceRow:
    row: int
    source: dict[str, str]  # what the matcher sees: property fields only
    columns: dict[str, Any]  # every original column, by header key


@dataclass
class SheetRows:
    name: str
    profile: SheetProfile
    mapping: dict[str, Any]
    rows: list[SourceRow] = field(default_factory=list)


def read_workbook(path: Path, saved: list[dict[str, Any]] | None) -> list[SheetRows]:
    """The named rows of every sheet, parsed with the importer's own parser (no model calls)."""
    data = path.read_bytes()
    profiles = _inspect_xlsx(data, path.name)
    for profile in profiles:
        sheet = saved_sheet_for(saved, profile)
        if sheet:
            apply_saved_mapping(profile, sheet, replace=True, source="reused")
    candidates, _ = _parse_xlsx(data, path.name, profiles)  # also finds autofill runs per sheet
    named = {(c.source_sheet, c.source_row_number) for c in candidates}
    sheets = {p.name: SheetRows(p.name, p, saved_sheet_mapping(p)) for p in profiles}

    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        for worksheet in workbook.worksheets:
            sheet = sheets.get(worksheet.title.strip() or "Sheet")
            if sheet is None:
                continue
            profile = sheet.profile
            width = max((h.index for h in profile.headers), default=0) + 1
            for number, row in enumerate(
                worksheet.iter_rows(
                    min_row=profile.header_row + 1,
                    max_row=profile.last_data_row,
                    max_col=width,
                    values_only=True,
                ),
                start=profile.header_row + 1,
            ):
                if (profile.name, number) not in named:
                    continue
                columns = {
                    h.key: row[h.index]
                    for h in profile.headers
                    if h.index < len(row) and row[h.index] not in (None, "")
                }
                sheet.rows.append(SourceRow(number, matcher_source(row, profile, number), columns))
    finally:
        workbook.close()
    return list(sheets.values())


# --------------------------------------------------------------------------- results


def sale_view(sale: Any) -> dict[str, Any]:
    """The matched sale as report columns, whether it is a DXBI event or a Transactions row."""
    if not sale:
        return {}
    if "family" in sale:
        return {
            "unit": sale.get("unit_number") or "",
            "building": sale.get("building_name") or "",
            "project": sale.get("project_name") or "",
            "area": sale.get("area_name") or "",
            "amount": sale.get("amount"),
            "date": str(sale.get("event_date") or "")[:10],
            "sqft": sale.get("size_sqft"),
            "source": "DXBI",
            "key": sale.get("event_key") or "",
        }
    area = sale.get("procedure_area")
    return {
        "unit": sale.get("unit_number") or "",
        "building": sale.get("building_name_en") or "",
        "project": sale.get("project_name_en") or "",
        "area": sale.get("area_name_en") or sale.get("master_project_en") or "",
        "amount": sale.get("actual_worth"),
        "date": str(sale.get("instance_date") or "")[:10],
        "sqft": round(float(area) * float(SQM_TO_SQFT), 1) if area else None,
        "source": f"Transactions {sale.get('match_status') or ''}".strip(),
        "key": sale.get("dxbi_sale_key") or sale.get("transaction_id") or "",
    }


def compare_baseline(old_key: str, result: MatchResult) -> str:
    """How the new matcher sees an old accepted sale link."""
    if result.outcome == "property_confirmed_no_sale":
        return "now_property_only"
    if result.outcome == "rejected":
        return "now_rejected"
    if result.outcome == "no_evidence" or not result.sale:
        return "now_no_evidence"
    keys = {result.sale.get("event_key"), result.sale.get("dxbi_sale_key")} - {None, ""}
    return "same_sale" if old_key in keys else "different_sale"


def check_acceptance(rule: Acceptance, result: MatchResult | None) -> dict[str, Any]:
    failures: list[str] = []
    view = sale_view(result.sale) if result else {}
    outcome = result.outcome if result else "row_not_found"
    if outcome != rule.outcome:
        failures.append(f"outcome {outcome}, expected {rule.outcome}")
    if (
        rule.sale_amount is not None
        and abs(Decimal(str(view.get("amount") or 0)) - rule.sale_amount) > 2
    ):
        failures.append(f"amount {view.get('amount')}, expected {rule.sale_amount}")
    if rule.sale_date is not None and view.get("date") != rule.sale_date:
        failures.append(f"date {view.get('date')}, expected {rule.sale_date}")
    if rule.sale_unit is not None and unit_key(str(view.get("unit") or "")) != unit_key(
        rule.sale_unit
    ):
        failures.append(f"unit {view.get('unit')!r}, expected {rule.sale_unit!r}")
    if rule.sale_building and rule.sale_building.lower() not in str(view.get("building")).lower():
        failures.append(f"building {view.get('building')!r}, expected {rule.sale_building!r}")
    if rule.sale_sqft is not None and abs(float(view.get("sqft") or 0) - rule.sale_sqft) > 1:
        failures.append(f"sqft {view.get('sqft')}, expected about {rule.sale_sqft:.1f}")
    text = json.dumps([view, result.rejected if result else []], default=str).lower()
    failures += [f"{word!r} appears" for word in rule.never_text if word.lower() in text]
    return {
        "file": rule.filename,
        "sheet": rule.sheet,
        "row": rule.row,
        "expected": rule.outcome,
        "outcome": outcome,
        "pass": not failures,
        "failures": failures,
        "sale": view,
        "reasons": result.reasons if result else [],
        "warnings": result.warnings if result else [],
    }


@dataclass
class Row:
    filename: str
    sheet: str
    row: int
    key: str
    source: dict[str, str]
    columns: dict[str, Any]
    result: MatchResult


def _others(result: MatchResult) -> str:
    parts = []
    for item in result.rejected[:3]:
        where = item.get("building_name") or item.get("project_name") or item.get("area_name")
        parts.append(
            f"{item.get('reason')}: unit {item.get('unit_number') or '-'} {where or ''} "
            f"{item.get('amount')} {str(item.get('event_date') or '')[:10]}".strip()
        )
    extra = len(result.rejected) - 3
    return "; ".join(parts) + (f"; +{extra} more" if extra > 0 else "")


# --------------------------------------------------------------------------- output workbook


def _cell(sheet: Any, value: Any, fill: PatternFill | None = None) -> Any:
    if isinstance(value, (list, dict)):
        value = json.dumps(value, ensure_ascii=False, default=str)
    if fill is None and not (isinstance(value, str) and value.startswith("=")):
        return value
    cell = WriteOnlyCell(sheet, value=value)
    if isinstance(value, str):
        cell.data_type = "s"  # source text that looks like a formula stays text
    if fill is not None:
        cell.fill = fill
    return cell


def _sheet(
    workbook: Workbook, name: str, headers: Sequence[str], widths: dict[str, int] | None = None
):
    sheet = workbook.create_sheet(name)
    sheet.freeze_panes = "A2"
    for index, header in enumerate(headers, 1):
        sheet.column_dimensions[get_column_letter(index)].width = (widths or {}).get(
            header, min(40, max(12, len(str(header)) + 2))
        )
    head = []
    for header in headers:
        cell = WriteOnlyCell(sheet, value=header)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="234A62")
        head.append(cell)
    sheet.append(head)
    return sheet


RESULT_COLUMNS = (
    "Outcome",
    "File",
    "Sheet",
    "Row",
    "Original bucket",
    "Old status",
    "Old experiment status",
    "Reasons",
    "Warnings",
    "Matched unit",
    "Matched building",
    "Matched project",
    "Matched area",
    "Matched amount AED",
    "Matched date",
    "Matched sqft",
    "Matched source",
    "Source amount AED",
    "Source date",
    "Source unit",
    "Source building",
    "Source project",
    "Other candidates",
    "Row key",
)
BASELINE_COLUMNS = (
    "Comparison",
    "File",
    "Sheet",
    "Row",
    "Old status",
    "New outcome",
    "Reasons",
    "Warnings",
    "Old unit",
    "Old building",
    "Old project",
    "Old area",
    "Old amount AED",
    "Old date",
    "Old sqft",
    "Old source",
    "New unit",
    "New building",
    "New project",
    "New area",
    "New amount AED",
    "New date",
    "New sqft",
    "New source",
    "Same unit",
    "Same amount",
    "Old sale key",
    "New sale key",
    "Row key",
)


def _original_columns(rows: Iterable[Row]) -> list[str]:
    names: dict[str, None] = {}
    for item in rows:
        names.update(dict.fromkeys(item.columns))
    return list(names)


def _label_for(name: str) -> str:
    return f"{name} (source)" if name in RESULT_COLUMNS else name


def write_workbook(
    path: Path,
    summary_lines: list[tuple[str, Any]],
    rows: list[Row],
    old: dict[str, tuple[str, str | None]],
    experiment: dict[str, str],
    baseline: list[dict[str, Any]],
) -> None:
    workbook = Workbook(write_only=True)
    summary = _sheet(workbook, "Summary", ["Item", "Value"], {"Item": 52, "Value": 60})
    for label, value in summary_lines:
        summary.append([_cell(summary, label), _cell(summary, value)])

    originals = _original_columns(rows)
    headers = [*RESULT_COLUMNS, *(_label_for(n) for n in originals)]
    widths = {"Reasons": 60, "Warnings": 40, "Other candidates": 60, "Row key": 14, "File": 30}
    all_rows = _sheet(workbook, "All rows", headers, widths)
    fills = {k: PatternFill("solid", fgColor=v) for k, v in COLOURS.items()}
    for item in rows:
        result, view = item.result, sale_view(item.result.sale)
        status, bucket = old.get(item.key, ("not in old run", None))
        fill = fills[result.outcome]
        values = [
            result.outcome,
            item.filename,
            item.sheet,
            item.row,
            bucket,
            status,
            experiment.get(item.key),
            "; ".join(result.reasons),
            "; ".join(result.warnings),
            view.get("unit"),
            view.get("building"),
            view.get("project"),
            view.get("area"),
            view.get("amount"),
            view.get("date"),
            view.get("sqft"),
            view.get("source"),
            item.source.get("transaction_price_aed"),
            item.source.get("transaction_date"),
            item.source.get("unit_number") or item.source.get("plot_number"),
            item.source.get("building_name"),
            item.source.get("project_name") or item.source.get("master_project"),
            _others(result),
            item.key,
        ]
        cells = [_cell(all_rows, value, fill) for value in values]
        cells += [_cell(all_rows, item.columns.get(name)) for name in originals]
        all_rows.append(cells)

    check = _sheet(workbook, "Baseline check", BASELINE_COLUMNS, widths)
    fills = {k: PatternFill("solid", fgColor=v) for k, v in BASELINE_COLOURS.items()}
    for link in baseline:
        old_view, new_view = link["old_sale"], link["new_sale"]
        values = [
            link["comparison"],
            link["file"],
            link["sheet"],
            link["row"],
            link["old_status"],
            link["outcome"],
            "; ".join(link["reasons"]),
            "; ".join(link["warnings"]),
            *(
                old_view.get(n)
                for n in ("unit", "building", "project", "area", "amount", "date", "sqft", "source")
            ),
            *(
                new_view.get(n)
                for n in ("unit", "building", "project", "area", "amount", "date", "sqft", "source")
            ),
            link["same_unit"],
            link["same_amount"],
            old_view.get("key") or link["old_key"],
            new_view.get("key"),
            link["key"],
        ]
        cells = [
            _cell(check, value, fills[link["comparison"]] if i == 0 else None)
            for i, value in enumerate(values)
        ]
        check.append(cells)
    workbook.save(path)


# --------------------------------------------------------------------------- the run


def _example(item: Row, link: dict[str, Any]) -> dict[str, Any]:
    return {
        "key": item.key,
        "file": item.filename,
        "sheet": item.sheet,
        "row": item.row,
        "comparison": link["comparison"],
        "outcome": item.result.outcome,
        "reasons": item.result.reasons,
        "warnings": item.result.warnings,
        "source": item.source,
        "old_sale": link["old_sale"],
        "new_sale": link["new_sale"],
        "other_candidates": item.result.rejected[:3],
    }


def main(
    argv: Sequence[str] | None = None, acceptance: Sequence[Acceptance] = R3_ACCEPTANCE
) -> Path:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--sources", type=Path)
    parser.add_argument("--snapshot", type=Path)
    parser.add_argument("--transactions", type=Path)
    parser.add_argument("--buildings", type=Path)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--all-rows", type=Path)
    parser.add_argument("--old-results", type=Path)
    parser.add_argument("--mappings", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    root = args.data_root
    sources = args.sources or root / "sources"
    snapshot = args.snapshot or root / "dxbi/snapshot.sqlite"
    transactions = args.transactions or root / "transactions.parquet"
    buildings = args.buildings or root / "building-keys.json"
    baseline_path = args.baseline or root / "experiment/baseline-matched.jsonl"
    all_rows_path = args.all_rows or root / "experiment/all-rows.jsonl"
    old_results = args.old_results or root / "experiment/final-row-results.jsonl.gz"
    mappings_path = args.mappings or root / "mappings-v2.json"
    output: Path = args.output
    partial = output.with_name(output.name + ".partial")
    if output.exists() or partial.exists():
        raise FileExistsError(f"Refusing to overwrite existing output: {output}")

    started = time.monotonic()
    phases: dict[str, float] = {}

    def phase(name: str, since: float) -> float:
        now = time.monotonic()
        phases[name] = round(now - since, 1)
        log(f"{name}: {phases[name]}s")
        return now

    tick = time.monotonic()
    saved_mappings = json.loads(mappings_path.read_text()) if mappings_path.exists() else {}
    workbooks = sorted(sources.glob("*.xlsx"))
    parsed: dict[str, list[SheetRows]] = {}
    for workbook_path in workbooks:
        parsed[workbook_path.name] = read_workbook(
            workbook_path, saved_mappings.get(workbook_path.name)
        )
        log(
            f"read {workbook_path.name}: {sum(len(s.rows) for s in parsed[workbook_path.name])} named rows"
        )
    if not mappings_path.exists():
        mappings_path.write_text(
            json.dumps({n: [s.mapping for s in sheets] for n, sheets in parsed.items()}, indent=1)
        )
    tick = phase("read workbooks", tick)

    old: dict[str, tuple[str, str | None]] = {}
    if all_rows_path.exists():
        for item in read_jsonl(all_rows_path):
            old[item["row_key"]] = (item.get("current_status"), item.get("primary_cause"))
    experiment: dict[str, str] = {}
    if old_results.exists():
        experiment = {item["row_key"]: item["report_status"] for item in read_jsonl(old_results)}
    baseline_keys: dict[str, str] = {}
    if baseline_path.exists():
        for item in read_jsonl(baseline_path):
            selected = str(item["current_match"].get("selected_event_key") or "")
            baseline_keys[item["row_key"]] = selected.removeprefix("sale:")
    tick = phase("read old results", tick)

    events, remembered = load_events(snapshot, set(baseline_keys.values()))
    tick = phase(f"load {len(events):,} DXBI events", tick)
    registry = load_transactions(transactions)
    tick = phase(f"load {len(registry):,} Transactions rows", tick)
    places = load_places(buildings)
    index = SalesIndex(events, places, registry)
    tick = phase("build sales index", tick)

    rows: list[Row] = []
    for filename, sheets in parsed.items():
        found = [
            (sheet.name, item, match_row(item.source, index))
            for sheet in sheets
            for item in sheet.rows
        ]
        # the importer learns a sheet's own unit numbering per import (= per workbook)
        promoted = promote_learned_aliases([(item.source, result) for _, item, result in found])
        for (sheet_name, item, _), result in zip(found, promoted, strict=True):
            key = row_key(filename, sheet_name, item.row)
            rows.append(Row(filename, sheet_name, item.row, key, item.source, item.columns, result))
            if len(rows) % 10_000 == 0:
                log(f"matched {len(rows):,} rows after {time.monotonic() - tick:.0f}s")
    tick = phase(f"match {len(rows):,} rows", tick)

    by_key = {item.key: item for item in rows}
    by_position = {(r.filename, r.sheet, r.row): r for r in rows}
    outcomes = collections.Counter(r.result.outcome for r in rows)

    buckets: dict[str, dict[str, Any]] = {}
    focus = collections.Counter()
    for item in rows:
        bucket = old.get(item.key, (None, None))[1]
        if not bucket:
            continue
        entry = buckets.setdefault(
            bucket, {"rows": 0, "old": collections.Counter(), "new": collections.Counter()}
        )
        entry["rows"] += 1
        entry["old"][experiment.get(item.key, "no experiment status")] += 1
        entry["new"][item.result.outcome] += 1
        focus["rows"] += 1
        focus["old_matched"] += experiment.get(item.key) in OLD_MATCHED
        focus["new_matched"] += item.result.outcome in MATCHED
        focus["new_review"] += item.result.outcome == "matched_sale_review"

    links: list[dict[str, Any]] = []
    missing_rows = 0
    for key, old_key in baseline_keys.items():
        item = by_key.get(key)
        if item is None:
            missing_rows += 1
            continue
        old_sale = remembered.get(old_key)
        old_view, new_view = sale_view(old_sale), sale_view(item.result.sale)
        links.append(
            {
                "key": key,
                "file": item.filename,
                "sheet": item.sheet,
                "row": item.row,
                "old_key": old_key,
                "old_status": old.get(key, ("not in old run", None))[0],
                "comparison": compare_baseline(old_key, item.result),
                "outcome": item.result.outcome,
                "reasons": item.result.reasons,
                "warnings": item.result.warnings,
                "old_sale": old_view,
                "new_sale": new_view,
                "same_unit": bool(old_view and new_view)
                and unit_key(str(old_view["unit"])) == unit_key(str(new_view["unit"])),
                "same_amount": bool(old_view and new_view)
                and abs(Decimal(str(old_view["amount"])) - Decimal(str(new_view["amount"]))) <= 2,
            }
        )
    links.sort(key=lambda link: (link["file"], link["sheet"], link["row"]))
    baseline_counts = collections.Counter(link["comparison"] for link in links)

    def examples(kind: str) -> list[dict[str, Any]]:
        chosen = sorted((x for x in links if x["comparison"] == kind), key=lambda x: x["key"])
        return [_example(by_key[x["key"]], x) for x in chosen[:EXAMPLES]]

    verdicts = []
    for rule in acceptance:
        found = by_position.get((rule.filename, rule.sheet, rule.row))
        verdicts.append(check_acceptance(rule, found.result if found else None))

    meta_path = transactions.with_suffix(".meta.json")
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
    fingerprints = {
        "sources": {p.name: sha256(p) for p in workbooks},
        "snapshot.sqlite": sha256(snapshot),
        "transactions": sha256(transactions),
        "building-keys.json": sha256(buildings),
        "baseline-matched.jsonl": sha256(baseline_path) if baseline_path.exists() else None,
        "all-rows.jsonl": sha256(all_rows_path) if all_rows_path.exists() else None,
        "final-row-results.jsonl.gz": sha256(old_results) if old_results.exists() else None,
        "mappings-v2.json": sha256(mappings_path),
    }
    tick = phase("compare and fingerprint", tick)

    summary = {
        "matcher_version": MATCHER_VERSION,
        "rows": len(rows),
        "outcomes": dict(outcomes),
        "matched_total": sum(outcomes[o] for o in MATCHED),
        "buckets": {
            name: {"rows": e["rows"], "old": dict(e["old"]), "new": dict(e["new"])}
            for name, e in sorted(buckets.items())
        },
        "focus": dict(focus),
        "baseline": dict(baseline_counts),
        "baseline_links": len(baseline_keys),
        "baseline_rows_not_parsed": missing_rows,
        "baseline_old_sale_missing_in_snapshot": sum(1 for x in links if not x["old_sale"]),
        "rows_not_in_old_run": sum(1 for r in rows if r.key not in old),
        "old_rows_not_parsed": sum(1 for k in old if k not in by_key),
        "examples": {
            "different_sale": examples("different_sale"),
            "now_rejected": examples("now_rejected"),
        },
        "acceptance": verdicts,
        "transactions": {
            "rows_used": len(registry),
            "export_row_count": meta.get("row_count"),
            "max_built_at": meta.get("max_built_at"),
        },
        "dxbi_events": len(events),
        "phases_seconds": phases,
        "fingerprints": fingerprints,
    }

    lines: list[tuple[str, Any]] = [
        ("Matcher version", MATCHER_VERSION),
        ("Named rows matched", len(rows)),
        *((f"Outcome: {name}", count) for name, count in outcomes.most_common()),
        ("Matched (green and teal)", summary["matched_total"]),
        ("Focus rows (36,102 experiment rows)", focus["rows"]),
        ("Focus rows now matched (green and teal)", focus["new_matched"]),
        ("Focus rows now in review (amber)", focus["new_review"]),
        ("Focus rows the old experiment matched", focus["old_matched"]),
        *(
            (
                f"Bucket: {name}",
                f"{e['rows']} rows; old matched {sum(e['old'][o] for o in OLD_MATCHED)}; "
                f"new matched {sum(e['new'][o] for o in MATCHED)}; "
                f"new review {e['new']['matched_sale_review']}",
            )
            for name, e in sorted(buckets.items())
        ),
        *((f"Baseline: {name}", baseline_counts[name]) for name in BASELINE_ORDER),
        *(
            (
                f"R3 row {v['file']} / {v['sheet']} / {v['row']}",
                "pass" if v["pass"] else "FAIL " + "; ".join(v["failures"]),
            )
            for v in verdicts
        ),
        ("Transactions rows (export)", meta.get("row_count")),
        ("Transactions max built_at", meta.get("max_built_at")),
        (
            "Colours",
            "green matched_sale / matched_registry_sale; teal inferred unit / registry without unit; amber review; blue property only; red rejected; grey no evidence",
        ),
    ]
    partial.mkdir(parents=True)
    write_workbook(partial / "Owner-Matching-v2.xlsx", lines, rows, old, experiment, links)
    tick = phase("write workbook", tick)
    summary["runtime_seconds"] = round(time.monotonic() - started, 1)
    (partial / "summary.json").write_text(json.dumps(summary, indent=1, default=str))
    partial.rename(output)
    log(f"done in {summary['runtime_seconds']}s -> {output}")
    return output


if __name__ == "__main__":
    main()
