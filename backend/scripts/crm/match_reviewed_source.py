#!/usr/bin/env python3
"""Compare a frozen reviewed source and warehouse bundle; persist only with --apply."""

from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import text

from app.crm.source_audit import SourceAuditPayload
from app.crm.source_matching import MATCH_VERSION, match_source_payload


def write_artifacts(payload, result, output: Path):
    output.mkdir(parents=True, exist_ok=True)
    (output / "matching-results.json").write_text(json.dumps(result, separators=(",", ":")))
    (output / "matching-summary.json").write_text(
        json.dumps(
            {key: value for key, value in result.items() if key not in {"rows", "references"}},
            indent=2,
        )
    )
    first = {}
    for row in payload.rows:
        first.setdefault(row.reference_id, row)
    associations = {}
    for row in payload.rows:
        r = result["rows"][str(row.cleaned_row_number)]
        if r["owner_category"]:
            associations.setdefault(row.reference_id, set()).add(
                (r["canonical_owner_key"], r["owner_category"])
            )
    with (output / "property-matching-audit.csv").open(
        "w", newline="", encoding="utf-8-sig"
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "reference_id",
                "source_key",
                "project",
                "building_name",
                "building_number",
                "unit_number",
                "land_number",
                "dm_sub_number",
                "property_type",
                "status",
                "reason",
                "property_key",
                "latest_sale_date",
                "current_associations",
                "former_associations",
            ],
        )
        writer.writeheader()
        for ref in payload.references:
            row, matched = first[ref.reference_id], result["references"][ref.reference_id]
            writer.writerow(
                {
                    "reference_id": ref.reference_id,
                    "source_key": json.dumps(ref.source_key, ensure_ascii=False),
                    **{
                        k: getattr(row, k)
                        for k in [
                            "project",
                            "building_name",
                            "building_number",
                            "unit_number",
                            "land_number",
                            "dm_sub_number",
                            "property_type",
                        ]
                    },
                    **{
                        k: matched[k]
                        for k in ["status", "reason", "property_key", "latest_sale_date"]
                    },
                    "current_associations": sum(
                        category == "current"
                        for _, category in associations.get(ref.reference_id, [])
                    ),
                    "former_associations": sum(
                        category == "former"
                        for _, category in associations.get(ref.reference_id, [])
                    ),
                }
            )


async def apply_results(payload, result, *, source_bytes, organization_id, import_id, output):
    """Apply only to the original tenant/source in one transaction, preserving audit."""
    from app.postgres.client import get_postgres_engine

    engine = get_postgres_engine()
    now = datetime.now(timezone.utc)
    source_hash = hashlib.sha256(source_bytes).hexdigest()
    result_hash = hashlib.sha256(
        json.dumps(result, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    async with engine.begin() as connection:
        record = (
            (
                await connection.execute(
                    text(
                        "SELECT mapping, summary FROM crm_contact_imports WHERE id=:id AND organization_id=:org FOR UPDATE"
                    ),
                    {"id": import_id, "org": organization_id},
                )
            )
            .mappings()
            .one_or_none()
        )
        if record is None:
            raise ValueError("Import does not belong to the requested organization")
        mapping = dict(record["mapping"])
        if (
            mapping.get("dataset_id") != payload.dataset_id
            or mapping.get("payload_sha256") != source_hash
        ):
            raise ValueError(
                "Source dataset or payload checksum differs from the persisted reviewed import"
            )
        if mapping.get("mode") not in {"source_only", "source_transaction_matched"}:
            raise ValueError("Import is not a reviewed source snapshot")
        existing = (
            (
                await connection.execute(
                    text(
                        "SELECT source_row_number, evidence->'source_audit'->>'reference_id' AS reference_id FROM crm_property_contact_claims WHERE import_id=:id AND organization_id=:org"
                    ),
                    {"id": import_id, "org": organization_id},
                )
            )
            .mappings()
            .all()
        )
        membership = {row.cleaned_row_number: row.reference_id for row in payload.rows}
        if len(existing) != len(membership) or any(
            membership.get(row["source_row_number"]) != row["reference_id"] for row in existing
        ):
            raise ValueError(
                "Persisted source row/reference membership differs from reviewed payload"
            )
        if mapping.get("transaction_match_result_sha256") == result_hash:
            return {
                "import_id": import_id,
                "organization_id": organization_id,
                "result_sha256": result_hash,
                "idempotent": True,
                "updated_rows": 0,
                "summary": result["summary"],
            }
        backup = output / "pre-match-import-metadata.json"
        if not backup.exists():
            backup.write_text(
                json.dumps(
                    {
                        "import_id": import_id,
                        "organization_id": organization_id,
                        "mapping": mapping,
                        "summary": record["summary"],
                    },
                    indent=2,
                    default=str,
                )
            )
        items = list(result["rows"].items())
        updated = 0
        for start in range(0, len(items), 1000):
            updates = [
                {"source_row_number": int(number), "match_json": value}
                for number, value in items[start : start + 1000]
            ]
            response = await connection.execute(
                text("""UPDATE crm_property_contact_claims AS claim
                SET evidence=jsonb_set(claim.evidence::jsonb, '{source_audit,transaction_match}', changes.match_json, true)::json,
                    updated_at=:now
                FROM jsonb_to_recordset(CAST(:updates AS jsonb)) AS changes(source_row_number integer, match_json jsonb)
                WHERE claim.import_id=:id AND claim.organization_id=:org AND claim.source_row_number=changes.source_row_number"""),
                {
                    "updates": json.dumps(updates),
                    "id": import_id,
                    "org": organization_id,
                    "now": now,
                },
            )
            updated += response.rowcount
        if updated != len(payload.rows):
            raise ValueError("Not every source row was updated; transaction rolled back")
        mapping.update(
            mode="source_transaction_matched",
            transaction_match_result_sha256=result_hash,
            transaction_match_version=MATCH_VERSION,
            transaction_match_captured_at=result.get("captured_at"),
            transaction_match_warehouse_fingerprint=result.get("warehouse_fingerprint"),
        )
        summary = dict(record["summary"])
        summary["transaction_matching"] = result["summary"]
        source_summary = dict(summary.get("source_audit") or {})
        counts = result["summary"]
        source_summary.update(
            mode="source_transaction_matched",
            matched_reference_count=counts["matched_reference_count"],
            matched_registry_property_count=counts["matched_property_count"],
            unmatched_reference_count=counts["unmatched_reference_count"],
            ambiguous_reference_count=counts["ambiguous_reference_count"],
            excluded_match_reference_count=counts["excluded_reference_count"],
            current_owner_association_count=counts["current_association_count"],
            former_owner_association_count=counts["former_association_count"],
        )
        summary["source_audit"] = source_summary
        await connection.execute(
            text(
                "UPDATE crm_contact_imports SET mapping=CAST(:mapping AS json), summary=CAST(:summary AS json) WHERE id=:id AND organization_id=:org"
            ),
            {
                "mapping": json.dumps(mapping),
                "summary": json.dumps(summary),
                "id": import_id,
                "org": organization_id,
            },
        )
        await connection.execute(
            text(
                "UPDATE crm_contact_lists SET updated_at=:now WHERE source_import_id=:id AND organization_id=:org"
            ),
            {"id": import_id, "org": organization_id, "now": now},
        )
    return {
        "import_id": import_id,
        "organization_id": organization_id,
        "result_sha256": result_hash,
        "idempotent": False,
        "updated_rows": updated,
        "summary": result["summary"],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--import-id", type=int, default=20)
    parser.add_argument("--organization-id")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    source_bytes = args.source.read_bytes()
    payload = SourceAuditPayload.model_validate_json(source_bytes)
    bundle = json.loads(args.bundle.read_text())
    result = match_source_payload(payload, bundle, import_id=args.import_id)
    write_artifacts(payload, result, args.output)
    if args.apply:
        if not args.organization_id:
            parser.error("--apply requires an explicit --organization-id")
        receipt = asyncio.run(
            apply_results(
                payload,
                result,
                source_bytes=source_bytes,
                organization_id=args.organization_id,
                import_id=args.import_id,
                output=args.output,
            )
        )
        (args.output / "publication-receipt.json").write_text(json.dumps(receipt, indent=2))
        print(json.dumps(receipt))
    else:
        print(json.dumps(result["summary"]))


if __name__ == "__main__":
    main()
