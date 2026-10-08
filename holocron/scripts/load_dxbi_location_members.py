#!/usr/bin/env python3
"""Load a DXBI location sweep: DXBI's locations and the records each location's search returned.

The input is one completed run of ``scripts/dxbi_location_sweep.py`` (``_SUCCESS``,
``locations.json`` and ``location=<id>.jsonl.gz``). A sales sweep fills ``dxbi_location_members``,
a rentals sweep ``dxbi_location_lease_members``; ``dxbi_locations`` is refreshed either way. Each
table is replaced whole and atomically.

Each run replaces only the members dated inside its own window and keeps the rest, so a nightly
sweep of the last two weeks adds to a year-long first run, and a re-run is harmless. Runs given
together load oldest first. A run without ``_SUCCESS``, with an incomplete location or with no
records is refused before anything changes.
"""

from __future__ import annotations

import argparse
import gzip
import json
import logging
import os
from datetime import date
from pathlib import Path
from typing import Any, NamedTuple

import clickhouse_connect

from holocron.sources.dxbi.rental_events import canonical_area_name, normalize_rental_rows
from holocron.sources.dxbi.sales_units import compact_payload, location_key, normalize_sales_row

logger = logging.getLogger("dxbi_location_members_loader")

# DXBI's flags: A = DLD area, U = sub-area, M = master community; the Location choices.
LOCATION_FLAGS = ("A", "U", "M")
LOCATIONS_TABLE = "dxbi_locations"
MEMBERS_TABLE = "dxbi_location_members"
CREATE_LOCATIONS_SQL = """
CREATE TABLE IF NOT EXISTS dxbi_locations (
    location_id   UInt32,
    name          String,
    display_name  String DEFAULT '',
    slug          String DEFAULT '',
    flag          LowCardinality(String) DEFAULT '',
    parent_id     UInt32 DEFAULT 0,
    name_key      String DEFAULT '',
    lineage       Array(String),
    source_run_id String DEFAULT '',
    loaded_at     DateTime64(3, 'UTC') DEFAULT now64(3)
) ENGINE = ReplacingMergeTree(loaded_at)
ORDER BY location_id
"""
CREATE_MEMBERS_SQL = """
CREATE TABLE IF NOT EXISTS dxbi_location_members (
    location_id      UInt32,
    location_name    String,
    sale_key         String,
    transaction_date Date,
    building_key     String DEFAULT '',
    area_key         String DEFAULT '',
    window_start     Date,
    window_end       Date,
    source_run_id    String DEFAULT '',
    loaded_at        DateTime64(3, 'UTC') DEFAULT now64(3)
) ENGINE = ReplacingMergeTree(loaded_at)
ORDER BY (location_id, sale_key)
"""
LEASE_MEMBERS_TABLE = "dxbi_location_lease_members"
CREATE_LEASE_MEMBERS_SQL = """
CREATE TABLE IF NOT EXISTS dxbi_location_lease_members (
    location_id      UInt32,
    location_name    String,
    contract_key     String,
    lease_start      Date,
    window_start     Date,
    window_end       Date,
    source_run_id    String DEFAULT '',
    loaded_at        DateTime64(3, 'UTC') DEFAULT now64(3)
) ENGINE = ReplacingMergeTree(loaded_at)
ORDER BY (location_id, contract_key)
"""
LEASE_MEMBER_COLUMNS = [
    "location_id", "location_name", "contract_key", "lease_start", "window_start",
    "window_end", "source_run_id",
]  # fmt: skip
LOCATION_COLUMNS = [
    "location_id", "name", "display_name", "slug", "flag", "parent_id", "name_key", "lineage",
    "source_run_id",
]  # fmt: skip
MEMBER_COLUMNS = [
    "location_id", "location_name", "sale_key", "transaction_date", "building_key", "area_key",
    "window_start", "window_end", "source_run_id",
]  # fmt: skip


def location_rows(items: list[dict[str, Any]], run_id: str) -> list[list[object]]:
    """One row per area, sub-area and master community, with the areas above it.

    ``name_key`` is how a row's printed area finds its DXBI location: "Al Barsha South Fourth"
    and a printed "Al Barsha South 4" share one key.
    """
    by_id = {item["id"]: item for item in items}
    rows: list[list[object]] = []
    for item in items:
        if item.get("flag") not in LOCATION_FLAGS:
            continue
        lineage: list[str] = []
        node: dict[str, Any] | None = item
        while node and node.get("flag") in LOCATION_FLAGS:
            lineage.append(str(node["name"]))
            node = by_id.get(node.get("parent_id"))
        rows.append(
            [
                int(item["id"]),
                str(item["name"]),
                str(item.get("dv") or ""),
                str(item.get("slug") or ""),
                str(item["flag"]),
                int(item.get("parent_id") or 0),
                location_key(canonical_area_name(str(item["name"]))),
                lineage,
                run_id,
            ]
        )
    return rows


def member_rows(
    run_dir: Path, names: dict[int, str], run_id: str
) -> tuple[list[list[object]], int]:
    """Each swept sale with the location whose search returned it, and the rows not read."""
    rows: list[list[object]] = []
    skipped = 0
    for path in sorted(run_dir.glob("location=*.jsonl.gz")):
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            for line in handle:
                record = json.loads(line)
                event = normalize_sales_row(compact_payload(line))
                if not event:
                    skipped += 1
                    continue
                location_id = int(record["source_location"]["id"])
                rows.append(
                    [
                        location_id,
                        names[location_id],
                        event["sale_key"],
                        event["transaction_date"],
                        event["building_key"],
                        event["area_key"],
                        date.fromisoformat(record["window"]["start"]),
                        date.fromisoformat(record["window"]["end"]),
                        run_id,
                    ]
                )
    return rows, skipped


def lease_member_rows(
    run_dir: Path, names: dict[int, str], run_id: str
) -> tuple[list[list[object]], int]:
    """Each swept lease, keyed as the lease loader keys it, with the location that returned it.

    A location's rows are normalized together, so identical leases on one day take the same
    occurrence numbers (and contract keys) as in the daily load.
    """
    rows: list[list[object]] = []
    skipped = 0
    for path in sorted(run_dir.glob("location=*.jsonl.gz")):
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            records = [json.loads(line) for line in handle]
        if not records:
            continue
        location_id = int(records[0]["source_location"]["id"])
        window = records[0]["window"]
        result = normalize_rental_rows([(record, str(path), "") for record in records])
        skipped += len(result.quarantined)
        rows.extend(
            [
                location_id,
                names[location_id],
                event["contract_key"],
                event["lease_start"],
                date.fromisoformat(window["start"]),
                date.fromisoformat(window["end"]),
                run_id,
            ]
            for event in result.events
        )
    return rows, skipped


def replace_table(
    client: Any, table: str, create_sql: str, rows: list[list[object]], columns: list[str]
) -> None:
    """Swap in the new rows in one step; readers see the old table or the new, never a mix."""
    staging = f"{table}_load"
    client.command(create_sql)
    client.command(f"DROP TABLE IF EXISTS {staging}")
    client.command(create_sql.replace(f"EXISTS {table} ", f"EXISTS {staging} ", 1))
    for offset in range(0, len(rows), 50_000):
        client.insert(staging, rows[offset : offset + 50_000], column_names=columns)
    client.command(f"EXCHANGE TABLES {table} AND {staging}")
    client.command(f"DROP TABLE {staging}")


def replace_window(
    client: Any,
    sweep: Sweep,
    rows: list[list[object]],
) -> int:
    """Replace the members dated inside the sweep's window, keep every other date; one swap.

    A nightly sweep covers the last two weeks, a first run a year: either way earlier history
    stays, and loading the same run twice gives the same table. Returns the rows replaced.
    """
    table, create_sql, columns, dated = _TARGETS[sweep.report]
    staging = f"{table}_load"
    window = {"first": sweep.first, "last": sweep.last}
    inside = f"{dated} BETWEEN {{first:Date}} AND {{last:Date}}"
    client.command(create_sql)
    replaced = int(
        client.query(
            f"SELECT count() FROM {table} FINAL WHERE {inside}", parameters=window
        ).result_rows[0][0]
    )
    client.command(f"DROP TABLE IF EXISTS {staging}")
    client.command(create_sql.replace(f"EXISTS {table} ", f"EXISTS {staging} ", 1))
    client.command(
        f"INSERT INTO {staging} SELECT * FROM {table} FINAL WHERE NOT ({inside})",
        parameters=window,
    )
    for offset in range(0, len(rows), 50_000):
        client.insert(staging, rows[offset : offset + 50_000], column_names=columns)
    client.command(f"EXCHANGE TABLES {table} AND {staging}")
    client.command(f"DROP TABLE {staging}")
    return replaced


class Sweep(NamedTuple):
    """One completed sweep run: what it searched and over which dates."""

    path: Path
    report: str
    first: date
    last: date


def read_sweep(run_dir: Path) -> Sweep:
    """A completed, whole sweep run, or SystemExit: an incomplete one must not replace anything."""
    if not (run_dir / "_SUCCESS").is_file():
        raise SystemExit(f"{run_dir} is not a completed sweep (no _SUCCESS)")
    summary = json.loads((run_dir / "summary.json").read_text())
    if summary.get("incomplete"):
        raise SystemExit(f"{run_dir}: locations {summary['incomplete']} are incomplete")
    window = summary["window"]
    return Sweep(
        path=run_dir,
        report=str(summary.get("report") or _report_from_records(run_dir)),
        first=date.fromisoformat(window["start"]),
        last=date.fromisoformat(window["end"]),
    )


def _report_from_records(run_dir: Path) -> str:
    # Runs written before summary.json named the report: the first record that exists says.
    for path in sorted(run_dir.glob("location=*.jsonl.gz")):
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            line = handle.readline()
        if line:
            return str(json.loads(line).get("transaction_type") or "sales")
    raise SystemExit(f"{run_dir}: the sweep returned no records at all")


def load_sweep(client: Any, sweep: Sweep) -> dict[str, int]:
    run_id = sweep.path.name.removeprefix("run=")
    items = json.loads((sweep.path / "locations.json").read_text())["items"]
    names = {
        int(item["id"]): str(item["name"]) for item in items if item.get("flag") in LOCATION_FLAGS
    }
    read = lease_member_rows if sweep.report == "rentals" else member_rows
    members, skipped = read(sweep.path, names, run_id)
    if not members:
        # DXBI lists sales and leases every week; a whole sweep with none is a failed session.
        raise SystemExit(f"{sweep.path}: no {sweep.report} in {sweep.first}..{sweep.last}")
    replace_table(
        client,
        LOCATIONS_TABLE,
        CREATE_LOCATIONS_SQL,
        location_rows(items, run_id),
        LOCATION_COLUMNS,
    )
    replaced = replace_window(client, sweep, members)
    logger.info(
        "sweep %s report=%s window=%s..%s members=%s replaced=%s skipped=%s",
        run_id, sweep.report, sweep.first, sweep.last, len(members), replaced, skipped,
    )  # fmt: skip
    return {"members": len(members), "replaced": replaced, "skipped": skipped}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dirs", nargs="+", type=Path)
    parser.add_argument("--host", default=os.getenv("CLICKHOUSE_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("CLICKHOUSE_PORT", "8123")))
    parser.add_argument("--database", default=os.getenv("CLICKHOUSE_DATABASE", "vitevue"))
    parser.add_argument("--username", default=os.getenv("CLICKHOUSE_USER", "default"))
    parser.add_argument("--password", default=os.getenv("CLICKHOUSE_PASSWORD", ""))
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    # Read every run first: one bad run stops the batch before anything changes.
    sweeps = [read_sweep(run_dir) for run_dir in sorted(args.run_dirs)]
    client = clickhouse_connect.get_client(
        host=args.host,
        port=args.port,
        database=args.database,
        username=args.username,
        password=args.password,
    )
    totals = {"runs": 0, "members": 0, "replaced": 0, "skipped": 0}
    for sweep in sweeps:  # oldest first: a later run's window wins where two overlap
        for name, value in load_sweep(client, sweep).items():
            totals[name] += value
        totals["runs"] += 1
    logger.info(
        "Location members loaded %s", " ".join(f"{name}={value}" for name, value in totals.items())
    )


_TARGETS = {
    "sales": (MEMBERS_TABLE, CREATE_MEMBERS_SQL, MEMBER_COLUMNS, "transaction_date"),
    "rentals": (LEASE_MEMBERS_TABLE, CREATE_LEASE_MEMBERS_SQL, LEASE_MEMBER_COLUMNS, "lease_start"),
}


if __name__ == "__main__":
    main()
