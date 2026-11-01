"""Do the live (ClickHouse-scoped) matcher input and the offline snapshot give the same outcomes?

Reads one owner workbook, builds each row's matcher source with the importer's parser, and matches
it twice: once through ``load_sales_index`` (the scoped ClickHouse queries a live import runs) and
once over the offline snapshot of all DXBI events and Transactions rows that the shadow run uses.
Both runs end with the same learned-alias post-pass. Touches neither Postgres nor any model.

    cd backend && set -a && . ../.env.dev && set +a && \
      uv run --with pyarrow python -m scripts.crm.compare_owner_match_paths "<workbook.xlsx>"

Prints the share of rows with the same outcome and the same matched sale, the biggest differences,
and the time and peak memory of the live matching stage.
"""

from __future__ import annotations

import argparse
import asyncio
import collections
import json
import resource
import sys
import time
from pathlib import Path
from typing import Any

from app.crm.import_mapping import apply_saved_mapping, saved_sheet_for
from app.crm.import_parsing import _inspect_xlsx, _parse_xlsx
from app.crm.owner_match_loader import load_sales_index, match_sources
from app.crm.owner_matcher import MatchResult, SalesIndex
from scripts.crm import shadow_owner_matching as shadow


def _peak_mb() -> float:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024  # Linux: kilobytes


def _sale_id(result: MatchResult) -> str:
    sale = shadow.sale_view(result.sale)
    return str(sale.get("key") or "")


def live_sources(path: Path, saved: list[dict[str, Any]] | None) -> dict[tuple[str, int], dict]:
    data = path.read_bytes()
    profiles = _inspect_xlsx(data, path.name)
    for profile in profiles:
        sheet = saved_sheet_for(saved, profile)
        if sheet:
            apply_saved_mapping(profile, sheet, replace=True, source="reused")
    candidates, _ = _parse_xlsx(data, path.name, profiles)
    return {(c.source_sheet, c.source_row_number): c.evidence["matcher_source"] for c in candidates}


async def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("workbook", type=Path)
    parser.add_argument("--data-root", type=Path, default=shadow.DEFAULT_DATA)
    parser.add_argument("--limit", type=int, default=0, help="only the first N rows (debug)")
    args = parser.parse_args(argv)
    root = args.data_root
    mappings = root / "mappings-v2.json"
    saved = json.loads(mappings.read_text()).get(args.workbook.name) if mappings.exists() else None

    sources = live_sources(args.workbook, saved)
    keys = list(sources)[: args.limit or None]
    rows = [sources[key] for key in keys]
    print(f"{len(rows):,} named rows", flush=True)

    started, before = time.monotonic(), _peak_mb()
    index = await load_sales_index(rows)
    loaded = time.monotonic()
    live = match_sources(index, rows)
    live_done = time.monotonic()
    live_peak = _peak_mb()
    print(
        f"live stage: load {loaded - started:.1f}s + match {live_done - loaded:.1f}s = "
        f"{live_done - started:.1f}s; peak RSS {live_peak:.0f} MB (before {before:.0f} MB)",
        flush=True,
    )
    del index

    events, _ = shadow.load_events(root / "dxbi/snapshot.sqlite", set())
    registry = shadow.load_transactions(root / "transactions.parquet")
    places = shadow.load_places(root / "building-keys.json")
    offline_index = SalesIndex(events, places, registry)
    # the offline side reads the workbook with the shadow run's own reader
    shadow_rows = {
        (sheet.name, item.row): item.source
        for sheet in shadow.read_workbook(args.workbook, saved)
        for item in sheet.rows
    }
    offline = match_sources(offline_index, [shadow_rows[key] for key in keys])

    same_outcome = sum(a.outcome == b.outcome for a, b in zip(live, offline, strict=True))
    same_sale = sum(
        a.outcome == b.outcome and _sale_id(a) == _sale_id(b)
        for a, b in zip(live, offline, strict=True)
    )
    total = len(rows)
    print(f"same outcome: {same_outcome:,}/{total:,} = {100 * same_outcome / total:.2f}%")
    print(f"same outcome and sale: {same_sale:,}/{total:,} = {100 * same_sale / total:.2f}%")
    pairs = collections.Counter(
        (a.outcome, b.outcome) for a, b in zip(live, offline, strict=True) if a.outcome != b.outcome
    )
    for (mine, theirs), count in pairs.most_common(10):
        print(f"  live {mine} vs offline {theirs}: {count}")
    shown = 0
    for key, a, b in zip(keys, live, offline, strict=True):
        if a.outcome != b.outcome and shown < 5:
            print(
                f"  e.g. {key}: live {a.outcome} {a.reasons[:1]} / offline {b.outcome} {b.reasons[:1]}"
            )
            shown += 1
    return 0 if same_outcome / total >= 0.99 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
