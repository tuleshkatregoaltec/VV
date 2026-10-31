"""Export the frozen five-group remainder, with every original source column.

This reads local files only. A rejected candidate is never labelled as a match.
Original owner/contact columns remain local and are not printed to the console.
"""

from __future__ import annotations

import argparse
import collections
import gzip
import hashlib
import json
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

REPO = Path(__file__).resolve().parents[3]
DEFAULT_DATA = REPO / ".local/owner-recovery/2026-10-29"
UNRESOLVED_STATUSES = {"unresolved", "tentative", "tentative_high_risk"}
EXCLUDED_STATUSES = {
    "already_live_recovered",
    "extra_conditional_support",
    "new_conservative_support",
}
CAUSES = {
    "no_original_role_correct_full_identifier": "Missing original unit/villa/plot identifier",
    "named_location_label_absent_catalog": "Unrecognised location label",
    "identified_property_no_sale_within_2_aed": "Property found, no sale within ±2 AED",
    "original_address_codes_contradict": "Conflicting address identifiers",
    "full_identifier_not_in_same_price_scoped_sales": "Same-price sales, different identifier",
}
EXPECTED = dict(zip(CAUSES, [10962, 7844, 6041, 5341, 3130], strict=True))


def is_unresolved(row: dict) -> bool:
    status = row["report_status"]
    if status not in UNRESOLVED_STATUSES | EXCLUDED_STATUSES:
        raise ValueError(f"Unknown report status: {status}")
    return status in UNRESOLVED_STATUSES


def read_rows(path: Path):
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as stream:
        for line in stream:
            yield json.loads(line)


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def cell(ws, value, number_format=None):
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False, default=str)
    result = WriteOnlyCell(ws, value=value)
    # Preserve formula-looking source text without executing it on export.
    if isinstance(value, str):
        result.data_type = "s"
    if number_format:
        result.number_format = number_format
    return result


def sheet(wb, name, headers):
    ws = wb.create_sheet(name)
    ws.freeze_panes = "A2"
    cells = []
    for i, header in enumerate(headers, 1):
        c = cell(ws, header)
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="234A62")
        cells.append(c)
        ws.column_dimensions[get_column_letter(i)].width = min(48, max(16, len(str(header)) + 2))
    ws.append(cells)
    return ws


def append(ws, values):
    ws.append([cell(ws, value) for value in values])


def export(data_root: Path, output: Path, expected: dict | None = EXPECTED) -> dict:
    if output.exists():
        raise FileExistsError(f"Refusing to overwrite existing output: {output}")
    ledger = data_root / "experiment/final-row-results.jsonl.gz"
    rows = {}
    excluded = collections.Counter()
    for row in read_rows(ledger):
        if not is_unresolved(row):
            excluded[row["report_status"]] += 1
            continue
        key = row["row_key"]
        if key in rows:
            raise ValueError("Duplicate original row key in the ledger")
        rows[key] = {
            k: row.get(k)
            for k in (
                "row_key",
                "filename",
                "sheet",
                "row",
                "primary_cause",
                "report_status",
                "reason",
                "original_engine_reason",
                "source_event_id",
                "source_unit_id",
                "raw_fields",
                "selected",
                "conditional_profile_diagnostics",
            )
        }
    counts = collections.Counter(row["primary_cause"] for row in rows.values())
    if expected is not None and dict(counts) != expected:
        raise ValueError(f"Frozen remainder changed: {dict(counts)}")
    mappings = json.loads((data_root / "parser-mappings.json").read_text())
    manifest = {
        v["filename"]: v for v in json.loads((data_root / "source-workbooks.json").read_text())
    }
    groups = collections.defaultdict(dict)
    for row in rows.values():
        group = groups[(row["filename"], row["sheet"])]
        if row["row"] in group:
            raise ValueError("Duplicate source file/sheet/row reference")
        group[row["row"]] = row
    for filename in {k[0] for k in groups}:
        if sha(data_root / "sources" / filename) != manifest[filename]["sha256"]:
            raise ValueError(f"Original workbook hash mismatch: {filename}")

    wb = Workbook(write_only=True)
    info = sheet(wb, "Read me", ["Topic", "Meaning"])
    for topic, meaning in [
        ("Scope", f"{len(rows):,} remaining rows from the fixed 36,102-row experiment."),
        (
            "Excluded",
            "Eight previously matched rows and 2,776 conditional proposals are excluded. The proposals are NOT confirmed matches.",
        ),
        (
            "Two views",
            "All unresolved has one row per original row. Source tabs repeat those same rows with ALL original workbook columns; do not add the two views together.",
        ),
        (
            "Original columns",
            "Source tabs preserve original values, column positions, duplicate/blank headers and number formats. Formula cells are literal formula text, not executable formulas.",
        ),
        (
            "Candidates",
            "Any DXBI candidate shown is REJECTED/UNCONFIRMED, not an accepted transaction or owner assignment.",
        ),
        (
            "Reasons",
            "The original bucket stays fixed. After-repair reasons and per-profile diagnostics explain newer failures.",
        ),
        (
            "Privacy",
            "Source tabs contain original company owner/contact columns. This workbook is a local handoff, not a public artifact.",
        ),
    ]:
        append(info, [topic, meaning])
    summary = sheet(wb, "Summary", ["Original problem", "Unresolved rows"])
    for cause, label in CAUSES.items():
        append(summary, [label, counts[cause]])
    append(summary, ["TOTAL", len(rows)])
    source_map = sheet(
        wb,
        "Source index",
        [
            "Tab",
            "Original file",
            "Original sheet",
            "Original header row",
            "Rows",
            "Original column count",
            "Source SHA256",
        ],
    )
    headers = [
        "Row key",
        "File",
        "Sheet",
        "Original row",
        "Original problem",
        "Review status",
        "Latest reason",
        "Earlier engine reason",
        "Original data tab",
        "Source event ID",
        "Source unit ID",
        "Original amount AED",
        "Original date",
        "Original unit",
        "Original building number",
        "Original plot",
        "Original property number",
        "Original master project",
        "Original building",
        "Original type",
        "Original size",
        "Rejected candidate event (NOT MATCHED)",
        "Candidate area",
        "Candidate project",
        "Candidate building",
        "Candidate unit",
        "Candidate amount AED",
        "Candidate date",
        "Candidate sqft",
        "All tested profile reasons",
    ]
    main = sheet(wb, "All unresolved", headers)
    exported = set()
    raw_count = 0
    for index, ((filename, source_sheet), wanted) in enumerate(sorted(groups.items()), 1):
        tab = f"Source {index:02d}"
        config = next(m for m in mappings[filename] if m["sheet"] == source_sheet)
        original = load_workbook(data_root / "sources" / filename, read_only=True, data_only=False)
        ws = original[source_sheet]
        header_number = config["header_row"]
        header_cells = next(ws.iter_rows(min_row=header_number, max_row=header_number))
        original_headers = [
            c.value if c.value is not None else f"(blank column {i})"
            for i, c in enumerate(header_cells, 1)
        ]
        audit_headers = ["Audit row key", "Original row", "Original problem", "Unresolved reason"]
        dest = sheet(wb, tab, audit_headers + original_headers)
        local_count = 0
        for source_row, cells in enumerate(
            ws.iter_rows(min_row=header_number + 1, max_row=max(wanted)), header_number + 1
        ):
            row = wanted.get(source_row)
            if row is None:
                continue
            prefix = [row["row_key"], source_row, CAUSES[row["primary_cause"]], row["reason"]]
            dest.append(
                [cell(dest, v) for v in prefix]
                + [cell(dest, c.value, c.number_format) for c in cells]
            )
            local_count += 1
            raw_count += 1
            row["original_tab"] = tab
            row["original_export_row"] = local_count + 1
            exported.add(row["row_key"])
        original.close()
        if local_count != len(wanted):
            raise ValueError(f"Source rows missing from {filename} / {source_sheet}")
        dest.auto_filter.ref = (
            f"A1:{get_column_letter(len(audit_headers) + len(original_headers))}{local_count + 1}"
        )
        append(
            source_map,
            [
                tab,
                filename,
                source_sheet,
                header_number,
                local_count,
                len(original_headers),
                manifest[filename]["sha256"],
            ],
        )
    if exported != rows.keys() or raw_count != len(rows):
        raise ValueError("Original source row reconciliation failed")
    for row in rows.values():
        raw = row["raw_fields"] or {}
        candidate = row["selected"] or {}
        target = candidate.get("target") or {}
        values = [
            row["row_key"],
            row["filename"],
            row["sheet"],
            row["row"],
            CAUSES[row["primary_cause"]],
            "UNRESOLVED — candidate not accepted",
            row["reason"],
            row["original_engine_reason"],
            row["original_tab"],
            row["source_event_id"],
            row["source_unit_id"],
            *[
                raw.get(k)
                for k in [
                    "transaction_price_aed",
                    "transaction_date",
                    "unit_number",
                    "building_number",
                    "plot_number",
                    "property_number",
                    "master_project",
                    "building_name",
                    "property_type",
                ]
            ],
            raw.get("size_unknown") or raw.get("size_sqft") or raw.get("size_sqm"),
            candidate.get("event_key"),
            *[target.get(k) for k in ["area_name", "project_name", "building_name", "unit_number"]],
            target.get("sale_amount_aed") or target.get("amount_aed"),
            target.get("transaction_date"),
            target.get("size_sqft"),
            row["conditional_profile_diagnostics"],
        ]
        assert len(values) == len(headers)
        cells = [cell(main, v) for v in values]
        cells[8].hyperlink = f"#'{row['original_tab']}'!A{row['original_export_row']}"
        main.append(cells)
    main.auto_filter.ref = f"A1:{get_column_letter(len(headers))}{len(rows) + 1}"
    output.parent.mkdir(parents=True, exist_ok=True)
    wb.save(output)
    check = load_workbook(output, read_only=True, data_only=False)
    actual_keys = {v[0] for v in check["All unresolved"].iter_rows(min_row=2, values_only=True)}
    check.close()
    if actual_keys != exported:
        raise ValueError("Saved workbook row keys failed round-trip verification")
    result = {
        "rows": len(rows),
        "categories": dict(counts),
        "excluded": dict(excluded),
        "original_rows_exported": raw_count,
        "source_tabs": len(groups),
        "source_workbooks": len({k[0] for k in groups}),
        "all_original_columns_included": True,
        "output_sha256": sha(output),
        "row_keys_sha256": hashlib.sha256("\n".join(sorted(exported)).encode()).hexdigest(),
    }
    output.with_suffix(".audit.json").write_text(json.dumps(result, indent=2))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(export(args.data_root.resolve(), args.output.resolve())))


if __name__ == "__main__":
    main()
