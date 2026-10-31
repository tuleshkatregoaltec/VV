#!/usr/bin/env python3
"""Create a local owner-mapping review using the CRM rules and read-only DXBI evidence.

No model calls, rental lookup, tenant writes or outreach. Source-only chronology
is kept separate from registry-supported assessments and legal title verification.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import json
import logging
from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import date, datetime, timezone
from pathlib import Path

from openpyxl import Workbook

from app.crm import import_parsing, owner_assessment, owner_queries
from app.crm.identity import _candidate_owner_key
from app.crm.import_events import IMPORT_RESOLVER_VERSION
from app.crm.owner_projection import _property_identity
from scripts.crm.clean_owner_workbook import _csv_value, _write_literal_row, load_source
from scripts.crm.inventory_owner_workbook import reference_id, reference_key


def canonical(value) -> str:
    return json.dumps(value, default=str, sort_keys=True, separators=(",", ":"))


def export_import_ready(source: Path, destination: Path, *, size_unit: str) -> None:
    """Make measurement units explicit for the ordinary app's header auto-mapping."""
    if size_unit not in {"sqm", "sqft"} or source.resolve() == destination.resolve():
        raise ValueError("An explicit supported unit and a distinct destination are required")
    headers, records, _ = load_source(source)
    headers = list(headers)
    headers[7] = f"Size ({size_unit})"
    workbook = Workbook(write_only=True)
    sheet = workbook.create_sheet("Sheet1")
    sheet.freeze_panes = "A2"
    _write_literal_row(sheet, headers)
    for _, _, row in records:
        _write_literal_row(sheet, row)
    workbook.save(destination)


def prepare_candidates(source: Path, *, size_unit: str, source_label: str | None = None):
    """Declare this file's user-confirmed units, not a global assumption for generic Size."""
    data = source.read_bytes()
    profiles = import_parsing._inspect_xlsx(data, source.name)
    for profile in profiles:
        size = next((header for header in profile.headers if header.label == "Size"), None)
        if size is None:
            raise ValueError("Expected a Size column for explicit unit declaration")
        for field in ("size_unknown", "size_sqft", "size_sqm"):
            profile.field_map.pop(field, None)
        profile.field_map[f"size_{size_unit}"] = size.key
    dropped = []
    candidates, total = import_parsing._parse_xlsx(data, source.name, profiles, dropped)
    if dropped or total != len(candidates):
        raise ValueError("Cleaned source contains parser-rejected records; inspect cleaning audit")
    _, records, _ = load_source(source)
    values = {number: row for number, _, row in records}
    for candidate in candidates:
        row = values[candidate.source_row_number]
        key = reference_key(row, candidate.source_row_number)
        candidate.evidence["source_inventory_reference"] = {
            "id": reference_id(key),
            "kind": key[0],
            "key": list(key),
        }
        candidate.evidence["source_identity_incomplete"] = key[0] not in {
            "unit",
            "named_villa_or_building",
        }
        candidate.evidence["source_contact_notes"] = str(row[16] or "")
        candidate.evidence["source_size_unit"] = size_unit
        candidate.evidence["size_unit_basis"] = "explicit_user_declaration_for_this_workbook"
        if source_label:
            candidate.evidence["source_filename"] = source_label
    return candidates


async def capture_registry(candidates, path: Path) -> dict:
    """Freeze the exact captured inputs; fingerprint change fails without publishing results."""
    import clickhouse_connect

    from app.clickhouse import client as warehouse
    from app.config import settings

    warehouse._client = await clickhouse_connect.get_async_client(
        host=settings.CLICKHOUSE_HOST,
        port=settings.CLICKHOUSE_PORT,
        username=settings.CLICKHOUSE_USER,
        password=settings.CLICKHOUSE_PASSWORD,
        database=settings.CLICKHOUSE_DATABASE,
        secure=settings.CLICKHOUSE_SECURE,
        settings={"readonly": 2},
        connect_timeout=10,
        send_receive_timeout=300,
    )
    try:
        before = await owner_queries.fetch_assessment_source_fingerprint()
        bundle = await owner_assessment.capture_owner_evidence(candidates)
        after = await owner_queries.fetch_assessment_source_fingerprint()
        if canonical(before) != canonical(after):
            raise RuntimeError("Registry fingerprint changed during capture; retry capture")
        payload = {
            "captured_at_utc": datetime.now(timezone.utc).isoformat(),
            "fingerprint": before,
            "bundle": bundle,
            "scope": "DXBI sales and Analytics building aliases; no rental/agent/title registry",
        }
        path.write_text(canonical(payload), encoding="utf-8")
        return payload
    finally:
        await warehouse._client.close()
        warehouse._client = None


def restore_registry(payload: dict) -> dict:
    bundle = payload["bundle"]
    for row in bundle["sales"]:
        if isinstance(row.get("transaction_date"), str):
            row["transaction_date"] = date.fromisoformat(row["transaction_date"])
    return bundle


def assess(candidates, bundle: dict):
    from app.crm.source_lifecycle import annotate_source_lifecycle

    # Preserve the file-derived story before matching changes geography labels.
    source_timeline = annotate_source_lifecycle(candidates, policy="dated-parties")
    source_timeline = json.loads(canonical(source_timeline))
    rows = [
        {
            **asdict(candidate),
            "id": index + 1,
            "owner_key": _candidate_owner_key(candidate),
            "property_key": candidate.property_key,
            "import_id": 0,
            "event_family": candidate.evidence.get("event_family", "unknown"),
            "claim_resolver_version": IMPORT_RESOLVER_VERSION,
        }
        for index, candidate in enumerate(candidates)
    ]
    valid = [
        (row, candidate)
        for row, candidate in zip(rows, candidates, strict=True)
        if _property_identity(row)
    ]
    sales = owner_assessment.match_owner_evidence([candidate for _, candidate in valid], bundle)
    snapshot = owner_assessment._finish_assessment(
        rows, valid, sales, datetime.now(timezone.utc), "available"
    )
    return snapshot, source_timeline


def original_rows(audit: Path) -> dict[int, list[int]]:
    result = defaultdict(list)
    with audit.open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            if row.get("cleaned_row_number"):
                result[int(row["cleaned_row_number"])].append(int(row["source_row_number"]))
    return result


def export_mapping(snapshot, candidates, timelines, provenance, output: Path, metadata: dict):
    from app.crm.owner_signals import build_owner_signals

    owner_signals = build_owner_signals(snapshot.rows)
    detail, relationships = [], {}
    flag_counts, timeline_counts = Counter(), Counter()
    for row, candidate, timeline in zip(snapshot.rows, candidates, timelines, strict=True):
        source_row = candidate.source_row_number
        if source_row not in provenance:
            raise ValueError("Retained row missing original provenance")
        flags = timeline.get("flags", [])
        flag_counts.update(flags)
        timeline_counts[timeline.get("as_of_file", "not_assessed")] += 1
        source_reference = candidate.evidence["source_inventory_reference"]
        item = {
            "cleaned_row": source_row,
            "original_source_rows": ";".join(map(str, provenance[source_row])),
            "source_reference_id": source_reference["id"],
            "source_reference_kind": source_reference["kind"],
            "contact_name": candidate.contact_name,
            "mobile": candidate.phone_primary or "",
            "contact_notes": candidate.evidence.get("source_contact_notes", ""),
            "party_role": candidate.party_role,
            "date": str(candidate.transaction_date or ""),
            "value_aed": candidate.transaction_price_aed,
            "area": candidate.area_name,
            "project": candidate.project_name,
            "building": candidate.building_name,
            "unit": candidate.unit_number,
            "registry_property_key": candidate.property_key,
            "registry_relationship_status": row["assessed_status"],
            "registry_reason": row.get("assessed_reason", ""),
            "registry_event_status": candidate.ownership_status,
            "registry_event_reason": candidate.match_reason,
            "source_as_of_file": timeline.get("as_of_file", "not_assessed"),
            "source_flags": ";".join(flags),
            "source_reasons": canonical(timeline.get("reasons", [])),
            "registry_inferred_sale": canonical(candidate.evidence.get("registry_inferred_sale")),
            "matched_sale_key": candidate.evidence.get("matched_sale_key", ""),
            "latest_registry_sale_date": str(candidate.latest_sale_date or ""),
            "owner_review_signals": "; ".join(
                owner_signals.get(row["canonical_owner_key"], {}).get("role_signals", [])
            ),
        }
        detail.append(item)
        # Unidentified properties cannot be conflated into one owner's None property.
        identity = row.get("property_identity")
        key = (row["canonical_owner_key"], tuple(identity) if identity else source_reference["id"])
        relation = relationships.setdefault(
            key,
            {
                "owner_id": row["canonical_owner_key"],
                "registry_property_identity": canonical(identity),
                "source_reference_ids": set(),
                "contact_name": candidate.contact_name,
                "mobile": candidate.phone_primary or "",
                "status": row["assessed_status"],
                "reason": row.get("assessed_reason", ""),
                "source_rows": [],
                "flags": set(),
            },
        )
        relation["source_reference_ids"].add(source_reference["id"])
        relation["source_rows"].extend(provenance[source_row])
        relation["flags"].update(flags)
    owners = []
    for relation in relationships.values():
        owners.append(
            {
                **relation,
                "source_reference_ids": ";".join(sorted(relation["source_reference_ids"])),
                "source_rows": ";".join(map(str, sorted(relation["source_rows"]))),
                "flags": ";".join(sorted(relation["flags"])),
            }
        )
    summary = {
        **metadata,
        "retained_party_rows": len(detail),
        "mapped_original_source_rows_including_duplicates": sum(
            len(v) for v in provenance.values()
        ),
        "owner_reference_relationships": len(owners),
        "relationship_status_counts": dict(Counter(row["status"] for row in owners)),
        "party_row_registry_status_counts": dict(
            Counter(row["registry_relationship_status"] for row in detail)
        ),
        "source_as_of_file_row_counts": dict(timeline_counts),
        "source_flag_row_counts_overlapping": dict(flag_counts),
        "assessment": snapshot.summary.model_dump(mode="json"),
        "limits": [
            "Registry confirms property transactions, not the named person's legal title.",
            "Source snapshot ends in 2023; as-of-file inference is not current title in 2026.",
            "Bank, price-drop and absent prior-acquisition signals do not prove mortgage, rent or agent role.",
            "No procedure IDs in this workbook; exact registry sale corroboration is separate from source chronology.",
            "Incomplete parcel/cluster references remain unresolved; no certified physical-property denominator.",
        ],
    }
    for name, records in (
        ("owner-row-mapping.csv", detail),
        ("owner-property-mapping.csv", owners),
    ):
        with (output / name).open("w", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream)
            if records:
                writer.writerow(records[0])
                writer.writerows([_csv_value(value) for value in row.values()] for row in records)
    workbook = Workbook(write_only=True)
    for name, records in (("Owner property mapping", owners), ("Source row mapping", detail)):
        sheet = workbook.create_sheet(name)
        sheet.freeze_panes = "A2"
        if records:
            _write_literal_row(sheet, list(records[0]))
            for row in records:
                _write_literal_row(sheet, list(row.values()))
    workbook.save(output / "owner-mapping-review.xlsx")
    (output / "owner-mapping-metrics.json").write_text(json.dumps(summary, indent=2) + "\n")
    return summary


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--size-unit", choices=("sqm", "sqft"), required=True)
    parser.add_argument("--source-label")
    parser.add_argument("--reuse-evidence", action="store_true")
    args = parser.parse_args()
    logging.disable(logging.CRITICAL)
    args.output.mkdir(parents=True, exist_ok=True)
    export_import_ready(
        args.source, args.output / "owner-import-ready.xlsx", size_unit=args.size_unit
    )
    print(json.dumps({"stage": "parse"}), flush=True)
    candidates = prepare_candidates(
        args.source, size_unit=args.size_unit, source_label=args.source_label
    )
    print(json.dumps({"stage": "capture", "candidates": len(candidates)}), flush=True)
    evidence_file = args.output / "registry-evidence.json"
    if args.reuse_evidence:
        payload = json.loads(evidence_file.read_text())
    else:
        payload = await capture_registry(candidates, evidence_file)
    print(
        json.dumps({"stage": "assess", "registry_sales": len(payload["bundle"]["sales"])}),
        flush=True,
    )
    snapshot, timelines = assess(candidates, restore_registry(payload))
    result = export_mapping(
        snapshot,
        candidates,
        timelines,
        original_rows(args.output / "source-row-provenance.csv"),
        args.output,
        {
            "cleaned_workbook_sha256": hashlib.sha256(args.source.read_bytes()).hexdigest(),
            "evidence_sha256": hashlib.sha256(evidence_file.read_bytes()).hexdigest(),
            "registry_capture_time_utc": payload["captured_at_utc"],
            "size_unit": args.size_unit,
            "matching_scope": payload["scope"],
        },
    )
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
