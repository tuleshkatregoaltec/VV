#!/usr/bin/env python3
"""Can DXBI sales files be re-loaded as they are, or must their dates be re-scraped?

The loader takes a sale's building from the title of DXBI's location cell (``location_title``,
read from the ``PATH_NAME`` cell's HTML). Rows parsed from the cell's text instead carry the
hidden buyer's or seller's agent in front of the building ("Sheetal Lakeshore Tower 1"). For each
file this counts the rows, the rows whose HTML gives a title, and the rows whose building the
title changes (what a re-load fixes). Nothing is written.

    python scripts/check_dxbi_sales_titles.py /path/to/sales-dynamic/dxbi_sales_dynamic_2026-07-*.jsonl

A file whose rows all have a title is re-loaded as it is (``load_dxbi_sales_units.py``); the
dates of a file without titles are re-scraped (holocron/docs/runbooks/dxbi-july-sales-rescrape.md).
"""

from __future__ import annotations

import argparse
import gzip
import sys
from collections.abc import Iterator
from pathlib import Path

from holocron.sources.dxbi.sales_units import compact_payload, normalize_sales_row


def _lines(path: Path) -> Iterator[str]:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as handle:
        yield from handle


def check(path: Path) -> dict[str, int]:
    counts = {"rows": 0, "sales": 0, "with_title": 0, "building_changes": 0, "unreadable": 0}
    for line in _lines(path):
        if not line.strip():
            continue
        counts["rows"] += 1
        try:
            payload = compact_payload(line)
            titled = normalize_sales_row(payload, source_file=path.name)
            untitled = normalize_sales_row(
                {k: v for k, v in payload.items() if k != "location_title"}, source_file=path.name
            )
        except (TypeError, ValueError):
            counts["unreadable"] += 1
            continue
        if not titled:
            continue
        counts["sales"] += 1
        if payload.get("location_title"):
            counts["with_title"] += 1
            if untitled and untitled["building_name"] != titled["building_name"]:
                counts["building_changes"] += 1
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("files", nargs="+", type=Path)
    args = parser.parse_args()
    total = dict.fromkeys(("rows", "sales", "with_title", "building_changes", "unreadable"), 0)
    print("file\trows\tsales\twith_title\tbuilding_changes\tunreadable")
    for path in sorted(args.files):
        counts = check(path)
        for key, value in counts.items():
            total[key] += value
        print(path.name, *counts.values(), sep="\t")
    print("TOTAL", *total.values(), sep="\t")
    untitled = total["sales"] - total["with_title"]
    print(
        f"\n{total['with_title']:,} of {total['sales']:,} sales have DXBI's title "
        f"({untitled:,} without); a re-load changes {total['building_changes']:,} buildings."
    )
    return 0 if total["sales"] and not untitled else 1


if __name__ == "__main__":
    sys.exit(main())
