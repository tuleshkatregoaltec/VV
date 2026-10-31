#!/usr/bin/env python3
"""Report which workbook columns the real CRM owner-import parser maps, and which it drops.

Per sheet: the mapped canonical fields, the unmapped headers with their fill rate, the parser's
own warnings, and how many parsed rows ended with a project / area. Header names and fill rates
only; headers that look like owner or contact data are counted but never named, and no cell
values are printed.

Run from backend/:  uv run python -I -m scripts.crm.report_header_coverage <dir-or-xlsx> [...]
"""

from __future__ import annotations

import argparse
import io
import re
from pathlib import Path

import openpyxl

from app.crm import import_parsing
from app.crm.import_parsing import SheetProfile

_PII_HEADER = re.compile(
    r"name|phone|mobile|email|mail|nation|passport|birth|dob|emirates|eid|tel|contact|whatsapp"
    r"|gender|visa|owner|identity|^id$|uid|card",
    re.IGNORECASE,
)
_LOCATION_HEADER = re.compile(r"build|project|area|communit|unit|master", re.IGNORECASE)


def _is_pii(label: str) -> bool:
    return bool(_PII_HEADER.search(label)) and not _LOCATION_HEADER.search(label)


def _fill_rates(data: bytes, profile: SheetProfile) -> tuple[int, dict[str, int]]:
    """Non-blank cell counts per header key over the sheet's data rows."""
    workbook = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    filled = {header.key: 0 for header in profile.headers}
    rows = 0
    try:
        sheet = next(s for s in workbook.worksheets if (s.title.strip() or "Sheet") == profile.name)
        width = max((header.index for header in profile.headers), default=0) + 1
        for row in sheet.iter_rows(
            min_row=profile.header_row + 1,
            max_row=profile.last_data_row,
            max_col=width,
            values_only=True,
        ):
            if not any(value not in (None, "") for value in row):
                continue
            rows += 1
            for header in profile.headers:
                if header.index < len(row) and str(row[header.index] or "").strip():
                    filled[header.key] += 1
    finally:
        workbook.close()
    return rows, filled


def report_workbook(path: Path) -> None:
    data = path.read_bytes()
    profiles = import_parsing._inspect_xlsx(data, path.name)
    candidates, _ = import_parsing._parse_xlsx(data, path.name, profiles)
    by_sheet: dict[str, list] = {}
    for candidate in candidates:
        by_sheet.setdefault(candidate.source_sheet, []).append(candidate)
    print(f"== {path.name}")
    for profile in profiles:
        rows, filled = _fill_rates(data, profile)
        mapped = set(profile.field_map.values())
        parsed = by_sheet.get(profile.name, [])
        print(f"  -- sheet {profile.name!r}: header_row={profile.header_row} data_rows={rows}")
        print(
            "     mapped: " + ", ".join(f"{k}<-{v}" for k, v in sorted(profile.field_map.items()))
        )
        unmapped = [header for header in profile.headers if header.key not in mapped]
        shown = [h for h in unmapped if not _is_pii(h.label)]
        print(f"     unmapped ({len(shown)} shown, {len(unmapped) - len(shown)} PII-like hidden):")
        for header in shown:
            rate = 100 * filled[header.key] / rows if rows else 0
            print(f"       {header.label!r}: {rate:.1f}% filled")
        with_project = sum(bool(c.project_name) for c in parsed)
        with_area = sum(bool(c.area_name) for c in parsed)
        print(f"     parsed_rows={len(parsed)} with_project={with_project} with_area={with_area}")
        for warning in profile.warnings:
            print(f"     warning: {warning}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", type=Path, help="xlsx files or directories of them")
    args = parser.parse_args()
    files = sorted(
        file
        for path in args.paths
        for file in (path.glob("*.xlsx") if path.is_dir() else [path])
        if not file.name.startswith("~$")
    )
    for file in files:
        report_workbook(file)


if __name__ == "__main__":
    main()
