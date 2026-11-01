#!/usr/bin/env python3
"""Deterministic private corpus evaluation; SELECT-only warehouse access, no imports.

Run from backend: uv run python -m scripts.crm.evaluate_owner_corpus --source DIR
Evidence contains private names and must remain in a restricted local directory.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import re
import shutil
import sqlite3
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

import openpyxl

from app.crm import import_parsing
from app.crm.import_events import event_family
from app.crm.import_normalization import positive_decimal

SEED = "vv-owner-corpus-2026-10-28"
TABLE_COLUMNS = {
    "dxbi_sales_unit_events": [
        "sale_key",
        "transaction_date",
        "unit_number",
        "building_name",
        "project_name",
        "area_name",
        "property_type",
        "size_sqft",
        "sale_amount_aed",
        "building_key",
        "area_key",
    ],
    "dxbi_rental_events": [
        "contract_key",
        "unit_candidate_key",
        "location_name",
        "unit_number",
        "building_name",
        "project_name",
        "area_name",
        "property_type",
        "size_sqft",
        "contract_amount_aed",
        "annual_rent_aed",
        "purchase_price_aed",
        "lease_start",
        "lease_end",
    ],
}

PLACE_COLUMNS = [
    "location_id",
    "path_key",
    "building_key",
    "area_key",
    "match_rank",
    "building_label",
    "project_label",
    "area_label",
]


def snapshot_queries():
    return {
        **{
            table: f"SELECT {', '.join(cols)} FROM {table} FINAL"
            for table, cols in TABLE_COLUMNS.items()
        },
        "dxbi_places": f"SELECT {', '.join(PLACE_COLUMNS)} FROM dxbi_places",
    }


def canonical(value):
    return json.dumps(value, default=str, sort_keys=True, separators=(",", ":"))


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def file_hash(path):
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def inventory(source):
    return [
        {"name": p.name, "bytes": p.stat().st_size, "sha256": file_hash(p)}
        for p in sorted(source.glob("*.xlsx"), key=lambda p: (p.stat().st_size, p.name))
    ]


def select_files(items):
    """Five contiguous equal-count size strata, four seeded hash ranks per stratum."""
    if len(items) < 20:
        raise ValueError("The deterministic sample requires at least 20 workbooks")
    selected = []
    for index in range(5):
        group = items[len(items) * index // 5 : len(items) * (index + 1) // 5]
        ranked = sorted(
            group, key=lambda row: hashlib.sha256(f"{SEED}:{row['name']}".encode()).hexdigest()
        )
        selected.extend({**row, "size_bin": index + 1} for row in ranked[:4])
    return selected


def token(value):
    text = re.sub(r"\s+", " ", str(value or "").strip().casefold())
    return "" if text in {"", "0", "null", "none", "n/a", "na", "-", "unknown", "#ref!"} else text


def source_identity(source, provenance):
    """Keep all four scopes; parcel-only and unkeyable references remain uncertain."""
    scope = tuple(
        token(source.get(field)) for field in ("area_name", "project_name", "building_name")
    )
    unit = token(source.get("unit_number"))
    plot = token(source.get("plot_number") or source.get("property_number"))
    if unit and any(scope):
        return ("unit", *scope, unit), False
    if plot and any(scope):
        return ("plot_reference", *scope, plot), True
    building_number = token(source.get("building_number"))
    if building_number and any(scope):
        return ("building_reference", *scope, building_number), True
    return ("unkeyable", *scope, *provenance), True


def event_identity(unit_key, source, provenance):
    # Missing transaction evidence cannot establish that two physical rows are one event.
    when, amount = source.get("transaction_date"), source.get("amount_aed")
    if not when or amount is None:
        return (*unit_key, "incomplete_event", *provenance)
    return (
        *unit_key,
        source.get("event_family"),
        str(when),
        str(amount),
        str(source.get("size_sqft") or ""),
        str(source.get("size_unknown") or ""),
    )


def parse_workbook(path, row_stream, source_context_index=None):
    data = path.read_bytes()
    profiles = import_parsing._inspect_xlsx(data, path.name)
    profile_by_name = {p.name: p for p in profiles}
    workbook = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    stats = Counter()
    units, events = {}, {}
    try:
        for sheet in workbook.worksheets:
            profile = profile_by_name[sheet.title.strip() or "Sheet"]
            date_index = import_parsing._date_column_index(profile)
            if date_index is not None:
                import_parsing._read_dates_by_column_order(
                    profile,
                    (
                        row[0] if row else None
                        for row in sheet.iter_rows(
                            min_row=profile.header_row + 1,
                            max_row=profile.last_data_row,
                            min_col=date_index + 1,
                            max_col=date_index + 1,
                            values_only=True,
                        )
                    ),
                )
            # Read all columns and all populated rows, including unsupported columns.
            last = max(import_parsing._populated_xlsx_rows(workbook, sheet), default=0)
            for number, row in enumerate(sheet.iter_rows(max_row=last, values_only=True), 1):
                stats["physical_rows"] += 1
                nonblank = any(value not in (None, "") for value in row)
                if not nonblank:
                    stats["blank_rows"] += 1
                    continue
                if number <= profile.header_row:
                    stats["header_or_preamble_rows"] += 1
                    continue
                stats["nonblank_data_rows"] += 1
                provenance = (path.name, sheet.title, number)
                fields = {
                    key: import_parsing._text(import_parsing._field_value(row, profile, key))
                    for key in profile.field_map
                }
                dropped = []
                candidate = None
                reason = None
                if stats["nonblank_data_rows"] > import_parsing._MAX_ROWS:
                    reason = "application_max_rows_exceeded"
                else:
                    try:
                        candidate = import_parsing._candidate_from_row(
                            row,
                            profile=profile,
                            filename=path.name,
                            row_number=number,
                            dropped=dropped,
                        )
                    except (ValueError, TypeError, OverflowError) as exc:
                        reason = f"parser_{type(exc).__name__}"
                if candidate is not None:
                    stats["accepted_rows"] += 1
                    source = {
                        field: getattr(candidate, field)
                        for field in (
                            "area_name",
                            "project_name",
                            "building_name",
                            "unit_number",
                            "property_type",
                            "transaction_date",
                        )
                    }
                    source.update(candidate.evidence.get("source_identifiers", {}))
                    source["amount_aed"] = positive_decimal(fields.get("transaction_price_aed"))
                    source["event_family"] = candidate.evidence.get("event_family", "unknown")
                    source["source_area_field"] = candidate.evidence.get("source_area_field")
                    source["raw_location_fields"] = {
                        key: fields.get(key, "")
                        for key in ("building_name", "project_name", "area_name")
                    }
                    source["source_filename"] = path.name
                    source["size_sqft"] = positive_decimal(fields.get("size_sqft"))
                    sqm = positive_decimal(fields.get("size_sqm"))
                    if sqm is not None:
                        source["size_sqft"] = float(sqm) * 10.76391041671
                    source["size_unknown"] = fields.get("size_unknown")
                    party = {
                        "provenance": provenance,
                        "name": candidate.contact_name,
                        "role": candidate.party_role,
                        "date": candidate.transaction_date,
                    }
                    reason = "accepted"
                else:
                    reason = reason or (
                        dropped[0]["reason"] if dropped else "parser_rejected_without_reason"
                    )
                    stats["rejected_rows"] += 1
                    stats[f"rejected:{reason}"] += 1
                    source = {
                        **fields,
                        "amount_aed": positive_decimal(fields.get("transaction_price_aed")),
                        "transaction_date": import_parsing._parse_date(
                            fields.get("transaction_date"), profile.date_order
                        ),
                        "event_family": event_family(fields.get("procedure_type", "")),
                    }
                    party = None
                source.setdefault("source_filename", path.name)
                source.setdefault(
                    "raw_location_fields",
                    {
                        key: fields.get(key, "")
                        for key in ("building_name", "project_name", "area_name")
                    },
                )
                raw_identity, _ = source_identity(source, provenance)
                if source_context_index is not None:
                    from app.crm.registry_locations import (
                        infer_source_file_context,
                        normalize_registry_locations,
                    )

                    source = infer_source_file_context(source, source_context_index)
                    source = normalize_registry_locations(source, source_context_index)
                identity, uncertain = source_identity(source, provenance)
                raw_unit_id = digest(raw_identity)
                unit_id = digest(identity)
                event_id = digest(event_identity(identity, source, provenance))
                unit = units.setdefault(
                    unit_id,
                    {
                        "source_unit_id": unit_id,
                        "identity": identity,
                        "uncertain": uncertain,
                        "provenance": [],
                        "event_ids": [],
                        "raw_source_unit_ids": [],
                    },
                )
                unit["provenance"].append(provenance)
                if raw_unit_id not in unit["raw_source_unit_ids"]:
                    unit["raw_source_unit_ids"].append(raw_unit_id)
                if event_id not in unit["event_ids"]:
                    unit["event_ids"].append(event_id)
                event = events.setdefault(
                    event_id,
                    {
                        "source_event_id": event_id,
                        "source_unit_id": unit_id,
                        "source": source,
                        "provenance": [],
                        "parties": [],
                        "accepted_rows": 0,
                        "rejected_rows": 0,
                    },
                )
                event["provenance"].append(provenance)
                event["accepted_rows" if candidate else "rejected_rows"] += 1
                if party and party not in event["parties"]:
                    event["parties"].append(party)
                row_stream.write(
                    canonical(
                        {
                            "provenance": provenance,
                            "disposition": reason,
                            "source_unit_id": unit_id,
                            "raw_source_unit_id": raw_unit_id,
                            "raw_source_identity": raw_identity,
                            "inferred_file_context": source.get("inferred_file_context"),
                            "registry_location_resolution": source.get(
                                "registry_location_resolution"
                            ),
                            "source_event_id": event_id,
                        }
                    )
                    + "\n"
                )
            stats["sheets"] += 1
        assert (
            stats["physical_rows"]
            == stats["blank_rows"] + stats["header_or_preamble_rows"] + stats["nonblank_data_rows"]
        )
        assert stats["nonblank_data_rows"] == stats["accepted_rows"] + stats["rejected_rows"]
        return (
            units,
            events,
            dict(stats),
            [
                {
                    "sheet": p.name,
                    "header_row": p.header_row,
                    "field_map": p.field_map,
                    "warnings": p.warnings,
                    "date_order": p.date_order,
                }
                for p in profiles
            ],
        )
    finally:
        workbook.close()


def connect_warehouse():
    import clickhouse_connect

    from app.config import settings

    return clickhouse_connect.get_client(
        host=settings.CLICKHOUSE_HOST,
        port=settings.CLICKHOUSE_PORT,
        username=settings.CLICKHOUSE_USER,
        password=settings.CLICKHOUSE_PASSWORD,
        database=settings.CLICKHOUSE_DATABASE,
        secure=settings.CLICKHOUSE_SECURE,
        settings={"readonly": 2},
        connect_timeout=10,
        send_receive_timeout=600,
    )


def warehouse_fingerprint(client):
    result = {}
    for table, columns in {**TABLE_COLUMNS, "dxbi_places": PLACE_COLUMNS}.items():
        final = " FINAL" if table in TABLE_COLUMNS else ""
        expression = ",".join(columns)
        row = client.query(
            f"SELECT count(), sum(cityHash64(tuple({expression}))), groupBitXor(cityHash64(tuple({expression}))) FROM {table}{final} SETTINGS max_threads=2"
        ).result_rows[0]
        result[table] = {"rows": row[0], "sum_hash64": str(row[1]), "xor_hash64": str(row[2])}
    return result


def capture_snapshot(client, db, output):
    from app.crm.registry_locations import RegistryLocationIndex, normalize_registry_locations
    from app.crm.transaction_matching import property_identity

    before = warehouse_fingerprint(client)
    catalog = [
        dict(zip(PLACE_COLUMNS, values, strict=True))
        for values in client.query(snapshot_queries()["dxbi_places"]).result_rows
    ]
    (output / "places-snapshot.json").write_text(canonical(catalog))
    locations = RegistryLocationIndex(catalog)
    db.execute(
        "CREATE TABLE event(family TEXT, amount REAL, identity TEXT, event_date TEXT, payload TEXT)"
    )
    counts = Counter()
    unit_eligible, raw_unit_eligible, enriched_counts = Counter(), Counter(), Counter()
    raw_stream_hash = hashlib.sha256()
    stream_hash = hashlib.sha256()
    for table, columns in TABLE_COLUMNS.items():
        family = "sale" if table == "dxbi_sales_unit_events" else "rental"
        with client.query_rows_stream(
            f"SELECT {', '.join(columns)} FROM {table} FINAL SETTINGS max_threads=2, max_block_size=8192"
        ) as stream:
            batch = []
            for values in stream:
                event = dict(zip(columns, values, strict=True))
                event["event_family"] = family
                event["event_key"] = event.get("sale_key") or event["contract_key"]
                event["transaction_date"] = event.get("transaction_date") or event.get(
                    "lease_start"
                )
                # Contract amounts are not annual rents or purchase-price attributes.
                event["amount_aed"] = (
                    event.get("sale_amount_aed")
                    if family == "sale"
                    else event.get("contract_amount_aed")
                )
                raw_payload = canonical(event)
                raw_stream_hash.update((raw_payload + "\n").encode())
                raw_identity = property_identity(event)
                raw_unit_eligible[family] += bool(raw_identity[1] and raw_identity[2])
                event = normalize_registry_locations(event, locations)
                enriched_counts[family] += bool(event.get("registry_location_resolution"))
                payload = canonical(event)
                stream_hash.update(payload.encode())
                stream_hash.update(b"\n")
                identity = property_identity(event)
                unit_eligible[family] += bool(identity[1] and identity[2])
                batch.append(
                    (
                        family,
                        event["amount_aed"],
                        canonical(identity),
                        str(event["transaction_date"]),
                        payload,
                    )
                )
                counts[family] += 1
                if len(batch) >= 8192:
                    db.executemany("INSERT INTO event VALUES (?,?,?,?,?)", batch)
                    db.commit()
                    batch.clear()
            if batch:
                db.executemany("INSERT INTO event VALUES (?,?,?,?,?)", batch)
                db.commit()
        print(
            canonical({"stage": "snapshot", "family": family, "rows": counts[family]}), flush=True
        )
    after = warehouse_fingerprint(client)
    if before != after:
        raise RuntimeError("Canonical DXBI rows changed during read-only capture; evidence invalid")
    assert sum(counts.values()) == sum(before[table]["rows"] for table in TABLE_COLUMNS)
    db.execute("CREATE INDEX event_amount ON event(amount)")
    db.execute("CREATE INDEX event_identity ON event(identity, family, event_date)")
    db.commit()
    result = {
        "before": before,
        "after": after,
        "captured_rows": dict(counts),
        "unit_identity_eligible_rows": dict(unit_eligible),
        "raw_unit_identity_eligible_rows": dict(raw_unit_eligible),
        "registry_location_enriched_rows": dict(enriched_counts),
        "raw_stream_sha256": raw_stream_hash.hexdigest(),
        "catalog_sha256": file_hash(output / "places-snapshot.json"),
        "stream_sha256": stream_hash.hexdigest(),
        "queries": snapshot_queries(),
    }
    (output / "snapshot.json").write_text(canonical(result))
    return result


def merge_groups(target, source, list_fields):
    for key, item in source.items():
        if key not in target:
            target[key] = item
            continue
        for field in list_fields:
            target[key][field].extend(
                value for value in item[field] if value not in target[key][field]
            )
        for field in ("accepted_rows", "rejected_rows"):
            if field in item:
                target[key][field] += item[field]


def ensure_property_lookup(db):
    """Bounded local retrieval index; shared matcher verifies every identifier/scope."""
    from app.crm.transaction_matching import property_scope_matches

    db.create_function(
        "owner_property_scope_matches", 2, property_scope_matches, deterministic=True
    )
    if db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='property_lookup'"
    ).fetchone():
        return
    db.execute(
        "CREATE TABLE property_lookup(identifier TEXT, villa_number TEXT, event_rowid INTEGER)"
    )
    batch = []
    for rowid, unit, kind in db.execute(
        "SELECT rowid, json_extract(identity, '$[2]'), lower(json_extract(payload, '$.property_type')) FROM event"
    ):
        suffix = (
            re.search(r"(\d+)$", unit or "")
            if kind in {"villa", "villas", "townhouse", "townhouses"}
            else None
        )
        batch.append((unit, suffix.group(1) if suffix else "", rowid))
        if len(batch) >= 8192:
            db.executemany("INSERT INTO property_lookup VALUES (?,?,?)", batch)
            batch.clear()
    if batch:
        db.executemany("INSERT INTO property_lookup VALUES (?,?,?)", batch)
    db.execute("CREATE INDEX property_lookup_identifier ON property_lookup(identifier)")
    db.execute("CREATE INDEX property_lookup_villa_number ON property_lookup(villa_number)")
    db.commit()


def property_candidate_rows(db, source):
    """Prefilter complete identifier candidates with the shared exact scope predicate."""
    from app.crm.transaction_matching import property_lookup_identifiers, property_scope

    keys = property_lookup_identifiers(source)
    building, project = property_scope(source)
    if not keys or not (building or project):
        return []
    numeric = tuple(key for key in keys if key.isdigit())
    identifiers = f"p.identifier IN ({','.join('?' for _ in keys)})"
    parameters = list(keys)
    if numeric:
        identifiers += f" OR p.villa_number IN ({','.join('?' for _ in numeric)})"
        parameters.extend(numeric)
    if building:
        scope = "owner_property_scope_matches(?, json_extract(e.payload, '$.building_name'))"
        parameters.append(building)
    else:
        scope = "(owner_property_scope_matches(?, json_extract(e.payload, '$.project_name')) OR owner_property_scope_matches(?, json_extract(e.payload, '$.building_name')))"
        parameters.extend((project, project))
    query = f"SELECT e.payload FROM event AS e JOIN property_lookup AS p ON e.rowid=p.event_rowid WHERE ({identifiers}) AND {scope}"
    return db.execute(query, parameters)


def strong_property_link(result):
    return (
        result.status == "matched"
        and result.evidence.get("identifier_supported", False)
        and not (
            {
                "location_review_required",
                "generic_building_project_review",
                "type_mismatch_review_required",
                "geography_review_required",
                "missing_target_area",
                "size_conflict",
            }
            & set(result.flags)
        )
    )


def plot_guard_replay_required(source):
    from app.crm.transaction_matching import identifier

    unit = identifier(str(source.get("unit_number") or ""))
    plot = identifier(str(source.get("plot_number") or "")) or identifier(
        str(source.get("plot_pre_reg_number") or "")
    )
    return bool(unit and plot and unit != plot)


def matching_issues(evidence, flags, coverage_flags, issues):
    if evidence.get("global_amount_candidate_count") == 0:
        issues["no_dxbi_amount_candidate"] += 1
        if coverage_flags:
            issues["no_amount_candidate_and_date_outside_snapshot_possible_coverage_gap"] += 1
    elif evidence.get("location_candidate_count") == 0:
        issues["amount_candidates_without_compatible_property_evidence"] += 1
    issues.update(flags)


def evaluate_property_links(events, db, previous_results=None, affected_ids=frozenset()):
    from app.crm.transaction_matching import match_property, property_lookup_identifiers

    ensure_property_lookup(db)
    cache, counts = {}, Counter()
    for number, event in enumerate(events.values(), 1):
        if previous_results is not None and event["source_event_id"] not in affected_ids:
            prior = previous_results[event["source_event_id"]].get("property_result")
            if prior is not None:
                event["property_result"] = prior
                counts[prior["status"]] += 1
            continue
        if event["result"]["status"] == "matched":
            continue
        source = event["source"]
        keys = property_lookup_identifiers(source)
        if not keys:
            continue
        fields = (
            "unit_number",
            "plot_number",
            "plot_pre_reg_number",
            "property_number",
            "building_number",
            "building_name",
            "project_name",
            "area_name",
            "property_type",
            "size_sqft",
            "event_family",
            "source_area_field",
        )
        cache_key = canonical(
            [
                {field: source.get(field) for field in fields},
                positive_decimal(source.get("amount_aed")) is not None,
            ]
        )
        if cache_key not in cache:
            candidates = (json.loads(row[0]) for row in property_candidate_rows(db, source))
            result = match_property(source, candidates)
            assert result.event is None and not result.exact_transaction
            cache[cache_key] = {
                **asdict(result),
                "strong_property_link": strong_property_link(result),
            }
        event["property_result"] = cache[cache_key]
        counts[event["property_result"]["status"]] += 1
        if number % 10000 == 0:
            print(
                canonical(
                    {
                        "stage": "identity_only_properties",
                        "completed_event_references": number,
                        "total_event_references": len(events),
                    }
                ),
                flush=True,
            )
    return counts


def evaluate(events, units, db, output, previous_results=None, affected_ids=frozenset()):
    from app.crm.transaction_matching import AmountFirstIndex

    catalog_path = output / "places-snapshot.json"
    if catalog_path.exists():
        from app.crm.registry_locations import (
            RegistryLocationIndex,
            infer_source_file_context,
            normalize_registry_locations,
        )

        catalog = RegistryLocationIndex(json.loads(catalog_path.read_text()))
        for event in events.values():
            event["source"] = normalize_registry_locations(
                infer_source_file_context(event["source"], catalog), catalog
            )
    db.execute(
        "CREATE INDEX IF NOT EXISTS event_annual_amount ON event(CAST(json_extract(payload, '$.annual_rent_aed') AS REAL))"
    )
    db.commit()
    rules, issues = Counter(), Counter()
    bounds = {
        family: (start, end)
        for family, start, end in db.execute(
            "SELECT family, min(event_date), max(event_date) FROM event GROUP BY family"
        )
    }
    previous_amount, matcher = None, None
    ordered = sorted(
        events.values(), key=lambda event: float(event["source"].get("amount_aed") or 0)
    )
    for index, event in enumerate(ordered, 1):
        source = event["source"]
        if source.get("inferred_file_context"):
            issues["source_filename_catalog_context_inferred"] += 1
        if source.get("event_family") == "rental":
            source["amount_basis"] = "contract_amount_aed"
        coverage_flags = []
        source_day = str(source.get("transaction_date") or "")[:10]
        if not source_day:
            issues["missing_source_event_date"] += 1
        if not any(
            source.get(field)
            for field in ("unit_number", "plot_number", "property_number", "building_number")
        ):
            issues["missing_source_property_identifier"] += 1
        for family, (start, end) in bounds.items():
            if source_day and source.get("event_family") in {
                family,
                "contact_snapshot",
                "unknown",
                "",
            }:
                if source_day < start:
                    coverage_flags.append(f"source_event_date_before_snapshot_start:{family}")
                if source_day > end:
                    coverage_flags.append(f"source_event_date_after_snapshot_end:{family}")
        event["snapshot_coverage_flags"] = coverage_flags
        issues.update(coverage_flags)
        amount = source.get("amount_aed")
        if amount is None or float(amount) <= 0:
            event["result"] = {
                "status": "unmatched",
                "reason": "missing_positive_amount",
                "exact_transaction": False,
            }
            issues["missing_positive_amount"] += 1
            rules["unmatched"] += 1
            continue
        if previous_results is not None and (
            event["source_event_id"] not in affected_ids
            or source.get("event_family")
            not in {"sale", "rental", "unknown", "contact_snapshot", ""}
        ):
            event["result"] = previous_results[event["source_event_id"]]["result"]
            rules[event["result"]["status"]] += 1
            matching_issues(
                event["result"].get("evidence", {}),
                event["result"].get("flags", []),
                coverage_flags,
                issues,
            )
            continue
        if previous_amount != amount:
            candidates = [
                json.loads(row[0])
                for row in db.execute(
                    "SELECT payload FROM event WHERE amount BETWEEN ? AND ? OR CAST(json_extract(payload, '$.annual_rent_aed') AS REAL) BETWEEN ? AND ?",
                    (float(amount) - 2, float(amount) + 2, float(amount) - 2, float(amount) + 2),
                )
            ]
            matcher = AmountFirstIndex(candidates)
            previous_amount = amount
        result = matcher.match(source)
        matching_issues(result.evidence, result.flags, coverage_flags, issues)
        matched_event = result.event
        strict = result.status == "matched" and result.exact_transaction
        if matched_event:
            assert any(
                abs(float(amount) - float(matched_event.get(field) or 0)) <= 2
                for field in result.evidence.get("matching_amount_fields", ["amount_aed"])
            )
        event["result"] = {
            "status": result.status,
            "exact_transaction": result.exact_transaction,
            "strict": strict,
            "strong_property_link": strong_property_link(result),
            "property_identity": result.property_identity,
            "event": matched_event,
            "candidate_event_count": result.candidate_event_count,
            "property_count": result.property_count,
            "flags": result.flags,
            "evidence": result.evidence,
        }
        rules[result.status] += 1
        if index % 2000 == 0:
            print(
                canonical(
                    {"stage": "matching", "completed_events": index, "total_events": len(events)}
                ),
                flush=True,
            )
    property_counts = evaluate_property_links(events, db, previous_results, affected_ids)
    issues.update(
        {f"identity_only_property_{status}": count for status, count in property_counts.items()}
    )
    with (output / "events.jsonl").open("w") as stream:
        for event in events.values():
            stream.write(canonical(event) + "\n")
    for unit in units.values():
        unit.pop("latest_source_buyers", None)
        unit.pop("observed_sale_history", None)
        observations = [events[key] for key in unit["event_ids"]]
        matches = [event for event in observations if event["result"]["status"] == "matched"]
        property_links = [
            event["property_result"]
            for event in observations
            if event.get("property_result", {}).get("status") == "matched"
        ]
        links = [event["result"] for event in matches] + property_links
        identities = {canonical(link["property_identity"]) for link in links}
        unit["identity_only_match"] = bool(property_links)
        unit["identity_only_without_amount_match"] = bool(property_links) and not matches
        unit["property_conflict"] = len(identities) > 1
        unit["strict_match"] = (
            bool(matches)
            and not unit["property_conflict"]
            and not unit["uncertain"]
            and any(event["result"].get("strict") for event in matches)
        )
        unit["provisional_match"] = bool(links) and not unit["property_conflict"]
        unit["strong_property_match"] = (
            bool(links)
            and not unit["property_conflict"]
            and any(link.get("strong_property_link") for link in links)
        )
        unit["owner_status"] = "no_registry_supported_buyer"
        buyers = []
        for event in matches:
            result = event["result"]
            observed = result.get("event") or {}
            if not result.get("strict") or observed.get("event_family") != "sale":
                continue
            for party in event["parties"]:
                if party["role"].casefold() == "buyer":
                    buyers.append(
                        (str(observed["transaction_date"]), party, result["property_identity"])
                    )
        if buyers and not unit["property_conflict"]:
            latest_date = max(row[0] for row in buyers)
            latest = [row for row in buyers if row[0] == latest_date]
            unit["latest_source_buyers"] = [row[1] for row in latest]
            history = [
                json.loads(row[0])
                for row in db.execute(
                    "SELECT payload FROM event WHERE identity=? AND family='sale' ORDER BY event_date",
                    (canonical(latest[0][2]),),
                )
            ]
            unit["observed_sale_history"] = history
            later = any(str(row["transaction_date"]) > latest_date for row in history)
            same_day_keys = {
                row["event_key"] for row in history if str(row["transaction_date"]) == latest_date
            }
            unit["owner_status"] = (
                "later_unknown_owner"
                if later
                else "ambiguous_latest_registration"
                if len(same_day_keys) > 1
                else "latest_observed_source_buyers"
            )
    with (output / "units.jsonl").open("w") as stream:
        for unit in units.values():
            stream.write(canonical(unit) + "\n")
    return dict(rules), dict(issues)


def coverage(unit_values, event_values):
    us, es = list(unit_values), list(event_values)
    counts = {
        "source_units": len(us),
        "identity_only_linked_references": sum(
            u["identity_only_match"] and not u["property_conflict"] for u in us
        ),
        "identity_only_without_amount_linked_references": sum(
            u["identity_only_without_amount_match"] and not u["property_conflict"] for u in us
        ),
        "strong_property_matched_references": sum(u["strong_property_match"] for u in us),
        "identifiable_source_units": sum(not u["uncertain"] for u in us),
        "uncertain_source_unit_references": sum(u["uncertain"] for u in us),
        "strict_matched_units": sum(u["strict_match"] for u in us),
        "provisional_matched_units": sum(u["provisional_match"] for u in us),
        "conflicting_unit_mappings": sum(u["property_conflict"] for u in us),
        "source_event_groups": len(es),
        "strict_matched_events": sum(e["result"].get("strict", False) for e in es),
        "provisional_matched_events": sum(e["result"]["status"] == "matched" for e in es),
    }
    counts["review_only_matched_units"] = (
        counts["provisional_matched_units"] - counts["strict_matched_units"]
    )
    counts["review_only_matched_events"] = (
        counts["provisional_matched_events"] - counts["strict_matched_events"]
    )
    counts["property_linked_identifiable_units"] = sum(
        u["provisional_match"] and not u["uncertain"] for u in us
    )
    counts["distinct_matched_dxbi_properties"] = len(
        {
            canonical(link["property_identity"])
            for e in es
            for link in (e["result"], e.get("property_result", {}))
            if link.get("status") == "matched"
        }
    )
    counts["distinct_matched_dxbi_event_keys"] = len(
        {
            (e["result"].get("event") or {}).get("event_family", "")
            + ":"
            + (e["result"].get("event") or {}).get("event_key", "")
            for e in es
            if e["result"].get("event")
        }
    )
    counts["distinct_strict_dxbi_event_keys"] = len(
        {
            (e["result"].get("event") or {}).get("event_family", "")
            + ":"
            + (e["result"].get("event") or {}).get("event_key", "")
            for e in es
            if e["result"].get("strict")
        }
    )
    counts["strong_property_coverage_pct"] = (
        round(100 * counts["strong_property_matched_references"] / len(us), 4) if us else 0
    )
    counts["strict_unit_coverage_pct"] = (
        round(100 * counts["strict_matched_units"] / len(us), 4) if us else 0
    )
    counts["provisional_unit_coverage_pct"] = (
        round(100 * counts["provisional_matched_units"] / len(us), 4) if us else 0
    )
    counts["strict_event_coverage_pct"] = (
        round(100 * counts["strict_matched_events"] / len(es), 4) if es else 0
    )
    counts["provisional_event_coverage_pct"] = (
        round(100 * counts["provisional_matched_events"] / len(es), 4) if es else 0
    )
    return counts


def run(
    source, output, *, selection_only=False, reuse_staging=False, stage_only=False, replay_from=None
):
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(output, 0o700)
    items = inventory(source)
    selected = select_files(items)
    manifest = {
        "seed": SEED,
        "algorithm": "sort (bytes,name), five contiguous equal-count size bins, four SHA256(seed:filename) ranks per bin",
        "inventory": items,
        "selected": selected,
    }
    manifest_path = output / "manifest.json"
    if manifest_path.exists() and json.loads(manifest_path.read_text()) != manifest:
        raise RuntimeError("Existing frozen selection differs; use a new evidence directory")
    manifest_path.write_text(canonical(manifest))
    if selection_only:
        print(
            canonical(
                {
                    "inventory_files": len(items),
                    "selected_files": len(selected),
                    "manifest": str(manifest_path),
                }
            )
        )
        return
    previous_results, affected_ids, replay_provenance = None, frozenset(), None
    if replay_from is not None:
        base = replay_from.resolve()
        if base == output.resolve():
            raise ValueError("Guard replay requires a distinct output directory")
        base_summary = json.loads((base / "summary.json").read_text())
        if json.loads((base / "manifest.json").read_text()) != manifest or base_summary[
            "source_sha256_before"
        ] != digest(items):
            raise RuntimeError("Guard replay source inventory or selection changed")
        for name in (
            "snapshot.json",
            "places-snapshot.json",
            "parsed-staging.json",
            "row-accounting.jsonl",
            "parser-mappings.json",
        ):
            shutil.copyfile(base / name, output / name)
        snapshot_link = output / "snapshot.sqlite"
        if not snapshot_link.exists():
            snapshot_link.symlink_to((base / "snapshot.sqlite").resolve())
        elif snapshot_link.resolve() != (base / "snapshot.sqlite").resolve():
            raise RuntimeError("Replay snapshot path differs from its frozen base")
        previous_results, affected = {}, set()
        prior_statuses = Counter()
        with (base / "events.jsonl").open() as stream:
            for line in stream:
                prior = json.loads(line)
                key = prior["source_event_id"]
                previous_results[key] = {
                    field: prior[field] for field in ("result", "property_result") if field in prior
                }
                if plot_guard_replay_required(prior["source"]):
                    affected.add(key)
                    prior_statuses[prior["result"]["status"]] += 1
        affected_ids = frozenset(affected)
        replay_provenance = {
            "base_directory": str(base),
            "base_summary_sha256": file_hash(base / "summary.json"),
            "base_code_sha256": base_summary["code_sha256"],
            "selection": "All source groups with normalized nonempty UnitNumber and first valid PlotNumber/PlotPreRegNumber different; includes prior ambiguous/unmatched groups.",
            "replayed_event_groups": len(affected_ids),
            "prior_amount_status_counts": dict(prior_statuses),
            "unchanged_event_groups_reused": len(previous_results) - len(affected_ids),
            "affected_source_event_ids": sorted(affected_ids),
        }
        (output / "replay-provenance.json").write_text(canonical(replay_provenance))
        print(
            canonical(
                {
                    "stage": "strict_unit_guard_replay",
                    "affected_source_event_groups": len(affected_ids),
                    "unchanged_source_event_groups": len(previous_results) - len(affected_ids),
                }
            ),
            flush=True,
        )
        reuse_staging = True
    if not (output / "snapshot.json").exists():
        capture_db = sqlite3.connect(output / "snapshot.sqlite")
        client = connect_warehouse()
        try:
            capture_snapshot(client, capture_db, output)
        finally:
            client.close()
            capture_db.close()
    from app.crm.registry_locations import RegistryLocationIndex

    source_context_index = RegistryLocationIndex(
        json.loads((output / "places-snapshot.json").read_text())
    )
    import inspect

    extraction_hash = digest(
        [inspect.getsource(fn) for fn in (parse_workbook, source_identity, event_identity, token)]
        + [
            file_hash(Path(import_parsing.__file__)),
            file_hash(Path(import_parsing.__file__).parent / "identity.py"),
            file_hash(output / "places-snapshot.json"),
            file_hash(Path(__file__).parents[2] / "app/crm/registry_locations.py"),
        ]
    )
    staging_path = output / "parsed-staging.json"
    if reuse_staging:
        staged = json.loads(staging_path.read_text())
        if (
            staged["manifest_sha256"] != file_hash(manifest_path)
            or staged["extraction_sha256"] != extraction_hash
        ):
            raise RuntimeError("Staged parser or source manifest changed; refuse cache reuse")
        units, events, per_file, mappings = (
            staged[key] for key in ("units", "events", "per_file", "mappings")
        )
    else:
        units, events, per_file, mappings = {}, {}, {}, {}
        with (output / "row-accounting.jsonl").open("w") as rows:
            for selected_file in selected:
                name = selected_file["name"]
                file_units, file_events, stats, profiles = parse_workbook(
                    source / name, rows, source_context_index
                )
                per_file[name] = {
                    "filename": name,
                    "size_bin": selected_file["size_bin"],
                    **stats,
                    "unit_ids": list(file_units),
                    "event_ids": list(file_events),
                }
                mappings[name] = profiles
                merge_groups(units, file_units, ("provenance", "event_ids", "raw_source_unit_ids"))
                merge_groups(events, file_events, ("provenance", "parties"))
                print(
                    canonical(
                        {
                            "stage": "parsed",
                            "file_number": len(per_file),
                            "nonblank_rows": stats.get("nonblank_data_rows", 0),
                            "accepted_rows": stats.get("accepted_rows", 0),
                            "units": len(file_units),
                            "events": len(file_events),
                        }
                    ),
                    flush=True,
                )
        (output / "parser-mappings.json").write_text(canonical(mappings))
        staging_path.write_text(
            canonical(
                {
                    "manifest_sha256": file_hash(manifest_path),
                    "extraction_sha256": extraction_hash,
                    "units": units,
                    "events": events,
                    "per_file": per_file,
                    "mappings": mappings,
                }
            )
        )
    db_path = output / "snapshot.sqlite"
    db = (
        sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        if replay_from is not None
        else sqlite3.connect(db_path)
    )
    try:
        if (output / "snapshot.json").exists():
            snapshot = json.loads((output / "snapshot.json").read_text())
        else:
            client = connect_warehouse()
            try:
                snapshot = capture_snapshot(client, db, output)
            finally:
                client.close()
        if "unit_identity_eligible_rows" not in snapshot:
            snapshot["unit_identity_eligible_rows"] = {
                family: count
                for family, count in db.execute(
                    "SELECT family, sum(json_extract(identity, '$[1]') != '' AND json_extract(identity, '$[2]') != '') FROM event GROUP BY family"
                )
            }
        snapshot["date_bounds"] = {
            family: {"first_event_date": start, "latest_event_date": end}
            for family, start, end in db.execute(
                "SELECT family, min(event_date), max(event_date) FROM event GROUP BY family"
            )
        }
        expected_queries = snapshot_queries()
        if snapshot["queries"] != expected_queries:
            raise RuntimeError("Snapshot source universe differs from requested canonical tables")
        if stage_only:
            print(
                canonical(
                    {
                        "stage": "ready",
                        "source_units": len(units),
                        "source_event_groups": len(events),
                        "snapshot": snapshot["captured_rows"],
                    }
                ),
                flush=True,
            )
            return
        code_paths = {
            "evaluator": Path(__file__),
            "parser": Path(import_parsing.__file__),
            "identity": Path(import_parsing.__file__).parent / "identity.py",
            "matcher": Path(__file__).parents[2] / "app/crm/transaction_matching.py",
            "registry_locations": Path(__file__).parents[2] / "app/crm/registry_locations.py",
        }
        code_before = {name: file_hash(path) for name, path in code_paths.items()}
        (output / "rules-frozen.json").write_text(canonical(code_before))
        rules, issues = evaluate(events, units, db, output, previous_results, affected_ids)
        if code_before != {name: file_hash(path) for name, path in code_paths.items()}:
            raise RuntimeError(
                "Evaluation rules changed during matching; rerun from validated staging"
            )
    finally:
        db.close()
    after = inventory(source)
    if items != after:
        raise RuntimeError("Source corpus changed during evaluation; evidence invalid")
    rows = []
    for name, stats in per_file.items():
        unit_ids, event_ids = stats.pop("unit_ids"), stats.pop("event_ids")
        rows.append(
            {
                **stats,
                **coverage((units[key] for key in unit_ids), (events[key] for key in event_ids)),
            }
        )
    fieldnames = sorted(set().union(*(row.keys() for row in rows)))
    with (output / "per-file.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    totals = Counter()
    for row in rows:
        totals.update(
            {
                key: row.get(key, 0)
                for key in (
                    "physical_rows",
                    "nonblank_data_rows",
                    "accepted_rows",
                    "rejected_rows",
                    "blank_rows",
                    "header_or_preamble_rows",
                )
            }
        )
    summary = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "seed": SEED,
        "selected_files": len(selected),
        "inventory_files": len(items),
        "source_sha256_before": digest(items),
        "source_sha256_after": digest(after),
        "manifest_sha256": file_hash(manifest_path),
        "snapshot": snapshot,
        "code_sha256": {
            "evaluator": file_hash(Path(__file__)),
            "parser": file_hash(Path(import_parsing.__file__)),
            "identity": file_hash(Path(import_parsing.__file__).parent / "identity.py"),
            "matcher": file_hash(Path(__file__).parents[2] / "app/crm/transaction_matching.py"),
            "registry_locations": file_hash(
                Path(__file__).parents[2] / "app/crm/registry_locations.py"
            ),
        },
        "replay_provenance": replay_provenance,
        "row_accounting": dict(totals),
        "denominator_provenance": "All physical source rows and the deterministic 20-file manifest are fixed. Distinct unit/event groups use corrected production parser aliases and exact catalog-verified filename context before grouping; pre-parser baseline percentages are not directly comparable.",
        "global": coverage(units.values(), events.values()),
        "per_file_sum_source_units": sum(row["source_units"] for row in rows),
        "per_file_sum_event_groups": sum(row["source_event_groups"] for row in rows),
        "metric_definitions": {
            "source_units": "Identifiable source units plus uncertain/unkeyable source references; denominator fixed before matching.",
            "provisional_matched_units": "Inclusive unique property links from amount evidence or independent exact scoped identity-only evidence, including strict matches; no transaction or owner is asserted by identity-only links.",
            "identity_only_without_amount_linked_references": "Disjoint additional property references linked using full scoped identifiers without an amount-based property link; no event selected and no owner inferred.",
            "strong_property_matched_references": "Unique property links supported by explicit source identifiers and no geography/type/location/size review; full plot namespaces included even when source unit_number blank. Independent of exact dates or family.",
            "strict_matched_units": "Identifiable source units with at least one exact shared-engine event match and no conflicting property identities.",
            "source_event_groups": "Distinct property-scope/date/amount/size/family source groups; incomplete event evidence remains separate per provenance.",
            "provisional_matched_events": "Inclusive unique-property links for source event groups, even when a unique transaction is not established.",
        },
        "parser_rejection_counts": dict(
            Counter(
                {
                    key: sum(row.get(key, 0) for row in rows)
                    for key in fieldnames
                    if key.startswith("rejected:")
                }
            )
        ),
        "rule_counts": rules,
        "issue_counts": issues,
        "owner_status_counts": dict(Counter(unit["owner_status"] for unit in units.values())),
        "source_reference_kinds": {
            kind: {
                "references": sum(unit["identity"][0] == kind for unit in units.values()),
                "strong_property_links": sum(
                    unit["identity"][0] == kind and unit["strong_property_match"]
                    for unit in units.values()
                ),
            }
            for kind in sorted({unit["identity"][0] for unit in units.values()})
        },
        "limitations": [
            "No legal-title or current-owner verification; latest observed source buyers are bounded by captured sales history.",
            "Unknown-size units remain unknown; generic Size is not assumed sqm or sqft.",
            "Rejected rows and uncertain property references remain in denominators.",
            "Private local evidence only; no tenant writes, models, uploads, or outreach.",
            "No inferred rental unit IDs: snapshot retains actual source unit IDs only.",
            "Warehouse history is a captured local observation, not a complete live DXBI website history. Dates outside snapshot bounds remain in every denominator; missing amount candidates may reflect coverage gaps rather than address normalization.",
        ],
    }
    assert totals["nonblank_data_rows"] == totals["accepted_rows"] + totals["rejected_rows"]
    assert (
        totals["physical_rows"]
        == totals["nonblank_data_rows"] + totals["blank_rows"] + totals["header_or_preamble_rows"]
    )
    assert len(selected) == len(rows) == 20
    (output / "summary.json").write_text(canonical(summary))
    print(
        canonical(
            {
                "summary": str(output / "summary.json"),
                "global": summary["global"],
                "row_accounting": summary["row_accounting"],
                "owner_status_counts": summary["owner_status_counts"],
            }
        ),
        flush=True,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("/tmp") / SEED)
    parser.add_argument("--selection-only", action="store_true")
    parser.add_argument("--reuse-staging", action="store_true")
    parser.add_argument("--stage-only", action="store_true")
    parser.add_argument("--replay-from", type=Path)
    args = parser.parse_args()
    run(
        args.source,
        args.output,
        selection_only=args.selection_only,
        reuse_staging=args.reuse_staging,
        stage_only=args.stage_only,
        replay_from=args.replay_from,
    )


if __name__ == "__main__":
    main()
