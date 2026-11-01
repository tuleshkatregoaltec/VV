#!/usr/bin/env python3
"""Evaluate original owner files locally without model calls or persistence.

Run from backend with ``uv run python -m scripts.crm.audit_owner_import FILE ...``.
Only aggregate JSON goes to stdout; source/contact rows are never emitted or saved.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import time
from collections import Counter
from pathlib import Path
from typing import Any

import clickhouse_connect

from app.clickhouse import client as warehouse
from app.config import settings
from app.crm import import_context, import_events, import_parsing, ownership, registry_fallback
from app.crm.cadastral import resolve_cadastral_plots
from app.crm.identity import ParsedContact, _normalize_unit
from app.crm.import_inventory import SourcePropertyInventory
from app.crm.owner_match_stage import run_owner_matching


async def resolve_candidates(candidates: list[ParsedContact]) -> None:
    """Use the deterministic import/replay stages in their application order."""
    await import_context.prepare_file_context(candidates)
    await ownership._recover_property_identity_from_transaction(candidates)
    await ownership._recover_property_identity_from_near_transaction(candidates)
    await import_context.recover_from_file_context(candidates)
    ownership._reuse_mortgage_property_from_sale_anchors(candidates)
    sales = await ownership._sales_evidence(candidates)
    await registry_fallback._apply_registry_unit_fallbacks(candidates, sales)
    rentals = await ownership._rental_evidence(candidates)
    await resolve_cadastral_plots(candidates)
    await run_owner_matching(candidates)
    for candidate in candidates:
        ownership._apply_evidence(candidate, sales=sales, rentals=rentals)


def aggregate_candidates(candidates: list[ParsedContact]) -> dict[str, Any]:
    """Count review signals; these are not labelled classification accuracy."""
    signals: Counter[str] = Counter()
    for candidate in candidates:
        for signal, prefix in (
            (
                "multiple_last_day_registrations",
                "More than one registration exists on the last observed sale date.",
            ),
            ("multiple_acquisition_events", "Multiple sale events fit the supplied acquisition;"),
            (
                "source_type_requires_review",
                "The source property type conflicts with the registry history",
            ),
            (
                "share_or_subunit_requires_review",
                "The source unit contains a share or subunit qualifier.",
            ),
        ):
            signals[signal] += candidate.match_reason.startswith(prefix)
        signals["scoped_identity_collision"] += bool(
            candidate.evidence.get("scoped_identity_collision")
        )
        high = candidate.confidence_score >= 90
        current = candidate.ownership_status in {"verified_current_owner", "probable_current_owner"}
        source = candidate.evidence.get("source_fields", {})
        source_unit = _normalize_unit(source.get("unit_number", ""))
        if source_unit in {"", "0"}:
            signals["blank_source_unit"] += 1
            signals["blank_source_unit_high_confidence_current"] += high and current
        if high:
            signals["high_confidence"] += 1
            signals["high_confidence_without_property_key"] += not candidate.property_key
            signals["high_confidence_non_sale_ownership"] += not import_events.has_sale_evidence(
                candidate
            ) and candidate.ownership_status in {
                "verified_current_owner",
                "probable_current_owner",
                "former_owner",
            }
        if high and current:
            signals["high_confidence_current"] += 1
            signals["high_confidence_current_with_later_sale"] += bool(
                candidate.latest_sale_date
                and candidate.transaction_date
                and candidate.latest_sale_date > candidate.transaction_date
            )
            signals["high_confidence_current_price_conflict"] += bool(
                candidate.latest_sale_price_aed
                and candidate.transaction_price_aed
                and abs(candidate.latest_sale_price_aed - candidate.transaction_price_aed)
                / candidate.latest_sale_price_aed
                > 0.02
            )
        lookup = candidate.evidence.get("sales_lookup", {})
        signals["ambiguous_registry_location"] += lookup.get("status") == "ambiguous_location"
        signals["ambiguous_high_confidence"] += (
            high and lookup.get("status") == "ambiguous_location"
        )
        observed = str(candidate.evidence.get("sales_match", {}).get("property_type", "")).lower()
        explicit = str(source.get("property_type", "")).lower()
        incompatible = (
            explicit in {"villa", "villas", "townhouse", "townhouses"}
            and observed in {"apartment", "apartments", "flat"}
        ) or (
            explicit in {"apartment", "apartments", "flat"}
            and observed in {"villa", "villas", "townhouse", "townhouses"}
        )
        signals["explicit_property_type_conflict"] += incompatible
        signals["high_confidence_property_type_conflict"] += high and incompatible
    return {
        "statuses": dict(sorted(Counter(c.ownership_status for c in candidates).items())),
        "event_families": dict(
            sorted(
                Counter(str(c.evidence.get("event_family", "legacy")) for c in candidates).items()
            )
        ),
        "identity_methods": dict(
            sorted(
                Counter(
                    str(c.evidence.get("property_identity_resolution", {}).get("method", "none"))
                    for c in candidates
                ).items()
            )
        ),
        "blank_property_keys": sum(not c.property_key for c in candidates),
        "distinct_property_keys": len({c.property_key for c in candidates if c.property_key}),
        "rental_linked": sum(bool(c.lead_id) for c in candidates),
        "review_signals": dict(sorted(signals.items())),
    }


async def evaluate_file(path: Path) -> dict[str, Any]:
    started = time.monotonic()
    data = path.read_bytes()
    inspector, parser = (
        (import_parsing._inspect_csv, import_parsing._parse_csv)
        if path.suffix.lower() == ".csv"
        else (import_parsing._inspect_xlsx, import_parsing._parse_xlsx)
    )
    profiles = await asyncio.to_thread(inspector, data, path.name)
    dropped: list[dict[str, Any]] = []
    candidates, total = await asyncio.to_thread(parser, data, path.name, profiles, dropped)
    inventory = SourcePropertyInventory()
    for profile in profiles:
        inventory.merge(profile.property_inventory)
    await resolve_candidates(candidates)
    if total != len(candidates) + len(dropped):
        raise RuntimeError("Source-row accounting failed")
    return {
        "file": path.name,
        "sha256": hashlib.sha256(data).hexdigest(),
        "size_bytes": len(data),
        "source_rows": total,
        "candidate_rows": len(candidates),
        "dropped_by_reason": dict(sorted(Counter(r["reason"] for r in dropped).items())),
        "source_inventory": inventory.summary().model_dump(),
        **aggregate_candidates(candidates),
        "elapsed_seconds": round(time.monotonic() - started, 3),
    }


async def warehouse_fingerprint() -> list[dict[str, Any]]:
    """Logical aggregate fingerprints survive merges and reveal changed input data."""
    tables = (
        "dxbi_sales_unit_events",
        "dxbi_rental_unit_candidates",
        "dxbi_rental_sale_matches",
        "dld_od_lands_bronze",
        "analytics_building_keys",
    )
    engines = {
        row["name"]: row["engine"]
        for row in await warehouse.query(
            "SELECT name, engine FROM system.tables WHERE database=currentDatabase()"
        )
    }
    result = []
    for table in tables:
        final = " FINAL" if "ReplacingMergeTree" in engines.get(table, "") else ""
        rows = await warehouse.query(
            f"SELECT count() AS rows, sum(cityHash64(toString(tuple(*)))) AS content_hash FROM {table}{final}"
        )
        result.append({"table": table, **rows[0]})
    return result


def source_fingerprint() -> str:
    digest = hashlib.sha256()
    root = Path(import_parsing.__file__).parents[1]
    for path in sorted(root.rglob("*.py")):
        digest.update(str(path.relative_to(root)).encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="+", type=Path)
    parser.add_argument("--label", default="current")
    args = parser.parse_args()
    for path in args.files:
        if not path.is_file() or path.suffix.lower() not in {".csv", ".xlsx"}:
            parser.error("Every input must be an existing CSV or XLSX file")
    # readonly=2 forbids writes while allowing the production queries' resource SETTINGS.
    warehouse._client = await clickhouse_connect.get_async_client(
        host=settings.CLICKHOUSE_HOST,
        port=settings.CLICKHOUSE_PORT,
        username=settings.CLICKHOUSE_USER,
        password=settings.CLICKHOUSE_PASSWORD,
        database=settings.CLICKHOUSE_DATABASE,
        secure=settings.CLICKHOUSE_SECURE,
        settings={"readonly": 2},
        send_receive_timeout=300,
        query_retries=2,
    )
    try:
        before = await warehouse_fingerprint()
        print(
            json.dumps(
                {
                    "event": "start",
                    "label": args.label,
                    "resolver_version": import_events.IMPORT_RESOLVER_VERSION,
                    "app_python_sha256": source_fingerprint(),
                    "warehouse": before,
                }
            ),
            flush=True,
        )
        for path in args.files:
            result = await evaluate_file(path)
            print(json.dumps({"event": "file", "label": args.label, **result}), flush=True)
        after = await warehouse_fingerprint()
        print(
            json.dumps(
                {
                    "event": "finish",
                    "label": args.label,
                    "warehouse": after,
                    "warehouse_unchanged": before == after,
                }
            ),
            flush=True,
        )
        if before != after:
            raise RuntimeError("Warehouse changed during evaluation; rerun for comparison")
    finally:
        await warehouse.close_clickhouse()


if __name__ == "__main__":
    asyncio.run(main())
