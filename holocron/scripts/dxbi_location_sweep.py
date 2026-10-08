#!/usr/bin/env python3
"""Record the sales or leases DXBInteract's search returns for each of its areas and communities.

DXBI's area pages group sales by its own locations: the DLD area, and the master community or
sub-area inside it. A row prints the location DXBI knows its building by, which can differ from
the page that counts it (JVC's page counts buildings printed only as "Al Barsha South 4"). For
each area, sub-area and master community in DXBI's location list this collects every sale
DXBI returns over a window and writes the rows, tagged with that location, to
``<output-dir>/location=<id>.jsonl.gz``. ``load_dxbi_location_members.py`` turns them into the
membership the Transactions Location filter uses.

Credentials, browser and storage state work as in ``dxbi_rental_backfill.py``; finished
locations are skipped on a re-run, and ``_SUCCESS`` is written once every location is complete.
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import random
import tempfile
import time
from collections.abc import Callable
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from dxbi_rental_backfill import (
    DEFAULT_FILTER_OVERRIDES,
    DEFAULT_LOCATION,
    FETCH_EVAL_TIMEOUT_MS,
    PAGE_SIZE,
    REPORTS,
    USER_AGENT,
    atomic_json,
    capture_template,
    fetch_rows,
    login,
    split_capped_shard,
    utc_now,
    virtual_display,
)
from playwright.sync_api import sync_playwright

LOCATION_LIST_URL = "https://dxbinteract.com/property/website/DLDLOV?RETURN_COLUMN=LOCATION_URL"
# DXBI's flags: A = DLD area, U = sub-area (JLT, JBR), M = master community (JVC, Dubai Marina).
# Projects (P) and buildings (B) sit inside these and are not separate Location choices.
SWEPT_FLAGS = ("A", "U", "M")


def location_list(page: Any) -> list[dict[str, Any]]:
    """DXBI's location tree, as its own search box loads it."""
    payload = page.evaluate(
        """async url => {
            const response = await fetch(url, {headers: {Accept: 'application/json'}});
            return {status: response.status, body: await response.text()};
        }""",
        LOCATION_LIST_URL,
    )
    if payload["status"] != 200:
        raise RuntimeError(f"DXBI location list returned HTTP {payload['status']}")
    return list(json.loads(payload["body"])["items"])


def write_location(
    path: Path,
    location: dict[str, Any],
    window: dict[str, str],
    rows: list[dict[str, Any]],
    report: str = "sales",
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as raw_handle:
        temporary = Path(raw_handle.name)
    try:
        with gzip.open(temporary, "wt", encoding="utf-8") as handle:
            for index, row in enumerate(rows, start=1):
                record = {
                    "transaction_type": report,
                    "source_location": location,
                    "window": window,
                    "row_index_in_location": index,
                    "columns": row["columns"],
                    "scraped_at": utc_now(),
                }
                handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
                handle.write("\n")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def split_window(shard: dict[str, Any]) -> list[dict[str, Any]]:
    """Halve a capped search's dates; a capped single day is split by price, then size."""
    first, last = date.fromisoformat(shard["date"]), date.fromisoformat(shard["end_date"])
    if first == last:
        return split_capped_shard(shard)
    middle = first + (last - first) // 2
    return [
        {**shard, "end_date": middle.isoformat()},
        {**shard, "date": (middle + timedelta(days=1)).isoformat()},
    ]


def sweep_location(
    *,
    page: Any,
    session: dict[str, Any],
    location: dict[str, Any],
    window: dict[str, str],
    report: dict[str, str],
    relogin: Callable[[], None],
    delay: tuple[float, float],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Every row DXBI returns for one location over the window.

    DXBI returns at most 300 rows per search and offers no next page, so a search that comes back
    full is split (``split_window``) until each part returns fewer; only those parts' rows are
    kept. ``session["template"]`` is the captured APEX request; ``relogin`` signs in again and
    replaces it when DXBI ends the session.
    """
    filters = {**DEFAULT_FILTER_OVERRIDES, "P74_DEAL": report["deal"]}
    target = {"id": str(location["id"]), "text": location["dv"], "slug": location["slug"]}
    rows: list[dict[str, Any]] = []
    requests, unsplittable = 0, 0
    queue: list[dict[str, Any]] = [
        {
            "date": window["start"],
            "end_date": window["end"],
            "min_price": Decimal("0"),
            "max_price": None,
            "min_size": None,
            "max_size": None,
        }
    ]
    while queue:
        shard = queue.pop(0)
        response: dict[str, Any] = {}
        for attempt in range(1, 4):
            try:
                response = fetch_rows(page, session["template"], shard, filters, target, report)
            except Exception as error:  # a timed-out page evaluation is retried like a 598
                response = {"status": 598, "login_redirect": False, "rows": [], "error": str(error)}
            requests += 1
            if response["login_redirect"]:
                relogin()
                continue
            if response["status"] < 400:
                break
            time.sleep(random.uniform(10 * attempt, 20 * attempt))
        if response.get("login_redirect") or response.get("status", 599) >= 400:
            raise RuntimeError(f"location {location['id']} {shard}: {response.get('error')}")
        time.sleep(random.uniform(*delay))
        if len(response["rows"]) < PAGE_SIZE:
            rows.extend(response["rows"])
            continue
        children = split_window(shard)
        if children:
            queue = children + queue
        else:
            rows.extend(response["rows"])
            unsplittable += 1
    return rows, {
        "rows": len(rows),
        "requests": requests,
        "unsplittable": unsplittable,
        "complete": unsplittable == 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Record the sales or leases DXBInteract returns for each of its areas."
    )
    parser.add_argument("--credentials", required=True)
    parser.add_argument("--storage-state", required=True)
    parser.add_argument("--browser", required=True)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--template-date", default="2025-07-01")
    parser.add_argument("--delay-min", type=float, default=3.0)
    parser.add_argument("--delay-max", type=float, default=6.0)
    parser.add_argument(
        "--report",
        choices=tuple(REPORTS),
        default="sales",
        help="Sales or rentals: DXBI's area pages count each with its own search.",
    )
    args = parser.parse_args()

    report = REPORTS[args.report]
    window = {"start": args.start_date, "end": args.end_date}
    credentials = json.loads(Path(args.credentials).read_text())
    output_dir: Path = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    (output_dir / "_SUCCESS").unlink(missing_ok=True)
    storage_path = Path(args.storage_state)
    summary_path = output_dir / "summary.json"
    summary: dict[str, Any] = (
        json.loads(summary_path.read_text()) if summary_path.exists() else {"locations": {}}
    )

    with virtual_display(), sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=args.browser,
            headless=False,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
        )
        context_kwargs: dict[str, Any] = {"user_agent": USER_AGENT}
        if storage_path.exists():
            context_kwargs["storage_state"] = str(storage_path)
        context = browser.new_context(**context_kwargs)
        page = context.new_page()
        page.set_default_timeout(FETCH_EVAL_TIMEOUT_MS)
        try:
            login(page, credentials, report)
            context.storage_state(path=storage_path)
            storage_path.chmod(0o600)
            filters = {**DEFAULT_FILTER_OVERRIDES, "P74_DEAL": report["deal"]}

            session = {
                "template": capture_template(
                    page, args.template_date, filters, report, DEFAULT_LOCATION
                )
            }

            def relogin() -> None:
                login(page, credentials, report)
                context.storage_state(path=storage_path)
                session["template"] = capture_template(
                    page, args.template_date, filters, report, DEFAULT_LOCATION
                )

            tree = location_list(page)
            atomic_json(output_dir / "locations.json", {"fetched_at": utc_now(), "items": tree})
            swept = [item for item in tree if item.get("flag") in SWEPT_FLAGS]
            for number, location in enumerate(swept, start=1):
                path = output_dir / f"location={location['id']}.jsonl.gz"
                if path.exists():
                    continue
                rows, stats = sweep_location(
                    page=page,
                    session=session,
                    location=location,
                    window=window,
                    report=report,
                    relogin=relogin,
                    delay=(args.delay_min, args.delay_max),
                )
                write_location(path, location, window, rows, args.report)
                summary["locations"][str(location["id"])] = {
                    "name": location["dv"],
                    "flag": location["flag"],
                    **stats,
                }
                atomic_json(summary_path, summary)
                print(
                    f"LOCATION {number}/{len(swept)} {location['id']} {location['dv']!r} "
                    f"rows={stats['rows']} requests={stats['requests']} "
                    f"unsplittable={stats['unsplittable']}",
                    flush=True,
                )
        finally:
            context.close()
            browser.close()

    incomplete = [key for key, value in summary["locations"].items() if not value["complete"]]
    summary.update(
        {
            "report": args.report,
            "window": window,
            "finished_at": utc_now(),
            "incomplete": incomplete,
        }
    )
    atomic_json(summary_path, summary)
    if not incomplete:
        (output_dir / "_SUCCESS").touch()
    print(json.dumps({"locations": len(summary["locations"]), "incomplete": incomplete}))
    return 0 if not incomplete else 2


if __name__ == "__main__":
    raise SystemExit(main())
