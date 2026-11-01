#!/usr/bin/env python3
"""Read-only, fixed-denominator source-vs-DXBI comparison; safe JSON stdout only."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import io
import json
import logging
import math
import resource
import time
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from zipfile import ZipFile

from app.crm import import_parsing
from app.crm.identity import ParsedContact, _candidate_owner_key, _property_scopes_compatible
from app.crm.import_events import IMPORT_RESOLVER_VERSION, has_sale_evidence
from app.crm.owner_projection import _projection_owner_key, _property_identity

AUTHORIZED_WORKBOOK = Path(
    "/mnt/c/Users/maan3/Downloads/Dubai Hills (Special 2024) (2) (version 1) (version 1).xlsb.xlsx"
)
RULE_VERSION = "source-only-as-of-file-1"
SOURCE_SEMANTICS_RULE = "dated-parties-1"
DATE_FIELDS = {"transaction_date", "latest_sale_date", "later_sale_date", "lease_end"}
RULES = {
    "current_as_of_file_inferred": "Latest dated source Buyer, subject to source uncertainty flags.",
    "former_source_sale_supported": "Source Seller or Buyer preceding another dated source sale.",
    "uncertain_source_parties": "Tied buyers or incompatible Buyer/Seller assertions need review.",
    "uncertain_source_dates": "An undated sale prevents ordering source ownership assertions.",
    "uncertain_source_lifecycle": "A later or undated non-sale event prevents a current inference.",
    "non_sale_source_event": "Retained procedure/role does not establish a sale acquisition/disposal.",
    "missing_source_identity": "No scoped source property identity is available.",
    "source_cutoff": "Unknown; maximum event date is observed, not a publication/capture cutoff.",
}


def canonical(value: Any) -> str:
    return json.dumps(value, default=str, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def row_id(workbook_sha: str, candidate: ParsedContact) -> str:
    return digest([workbook_sha, candidate.source_sheet, candidate.source_row_number])


def source_identity(candidate: ParsedContact) -> tuple[str, str] | None:
    return _property_identity({**vars(candidate), "property_key": candidate.property_key})


def source_person(candidate: ParsedContact) -> str:
    return digest(
        _projection_owner_key(
            {
                **vars(candidate),
                "property_key": candidate.property_key,
                "owner_key": _candidate_owner_key(candidate),
            }
        )
    )


def property_labels(candidate: ParsedContact) -> dict[str, str]:
    return {
        name: getattr(candidate, name)
        for name in ("area_name", "project_name", "building_name", "unit_number", "property_type")
    }


def _restore(payload: str) -> list[ParsedContact]:
    values = json.loads(payload)
    for item in values:
        for field in DATE_FIELDS:
            if item[field]:
                item[field] = date.fromisoformat(item[field])
    return [ParsedContact(**item) for item in values]


def policy_candidates(baseline: Baseline, source_semantics: str) -> list[ParsedContact]:
    """Opt-in inference on a fresh copy; preserve the parser baseline and explicit procedures."""
    if source_semantics not in {"strict", "dated-parties"}:
        raise ValueError("Unsupported source semantics policy")
    candidates = baseline.candidates()
    if source_semantics == "strict":
        return candidates
    for candidate in candidates:
        parsed_family = candidate.evidence.get("event_family")
        if (
            parsed_family == "contact_snapshot"
            and not candidate.procedure_type.strip()
            and candidate.party_role in {"Buyer", "Seller"}
            and isinstance(candidate.transaction_date, date)
            and isinstance(candidate.transaction_price_aed, (int, float))
            and not isinstance(candidate.transaction_price_aed, bool)
            and math.isfinite(candidate.transaction_price_aed)
            and candidate.transaction_price_aed > 0
        ):
            parsed_evidence_sha256 = digest(candidate.evidence)
            candidate.evidence["parsed_event_family"] = parsed_family
            candidate.evidence["source_semantics_inference"] = {
                "policy": source_semantics,
                "rule_version": SOURCE_SEMANTICS_RULE,
                "parsed_event_family": parsed_family,
                "parsed_evidence_sha256": parsed_evidence_sha256,
                "inferred_event_family": "sale",
                "raw_procedure_type": candidate.procedure_type,
                "basis": "Dated Buyer/Seller with positive amount and no explicit procedure",
                "legal_ownership_proof": False,
            }
            candidate.evidence["event_family"] = "sale"
    return candidates


def event_signature(candidate: ParsedContact) -> str:
    return digest(
        [
            source_person(candidate),
            source_identity(candidate),
            candidate.party_role,
            candidate.procedure_type,
            candidate.transaction_date,
            candidate.transaction_price_aed,
            candidate.evidence.get("source_fields", {}),
        ]
    )


@dataclass(frozen=True)
class Baseline:
    original_bytes: bytes
    workbook_sha256: str
    candidates_json: str
    mappings_json: str
    counts_json: str
    parser_sha256: str
    rejected_json: str

    def candidates(self) -> list[ParsedContact]:
        # Serialization, including all nested evidence, prevents cross-arm mutation.
        return _restore(self.candidates_json)


def freeze(
    data: bytes, candidates: list[ParsedContact], *, mappings=None, counts=None, rejected=None
) -> Baseline:
    root = Path(import_parsing.__file__).parent
    parser_files = ("import_parsing.py", "identity.py", "import_events.py", "import_inventory.py")
    parser_hash = digest(
        {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in parser_files}
    )
    return Baseline(
        data,
        hashlib.sha256(data).hexdigest(),
        canonical([asdict(candidate) for candidate in candidates]),
        canonical(mappings or []),
        canonical(
            counts or {"accepted": len(candidates), "nonempty": len(candidates), "rejected": 0}
        ),
        parser_hash,
        canonical(rejected or []),
    )


def parse_workbook(path: Path) -> Baseline:
    if path.resolve() != AUTHORIZED_WORKBOOK.resolve():
        raise ValueError("Only the explicitly authorized workbook is permitted")
    data = path.read_bytes()
    profiles = import_parsing._inspect_xlsx(data, path.name)
    rejected: list[dict[str, Any]] = []
    candidates, nonempty = import_parsing._parse_xlsx(data, path.name, profiles, rejected)
    assert nonempty == len(candidates) + len(rejected), "Source row accounting failed"
    physical = 0
    # Count actual worksheet row elements, including stored blank rows; never dimension padding.
    with ZipFile(io.BytesIO(data)) as archive:
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        targets = {item.attrib["Id"]: item.attrib["Target"] for item in rels}
        sheets = workbook.findall("{*}sheets/{*}sheet")
        for sheet, profile in zip(sheets, profiles, strict=True):
            target = targets[
                sheet.attrib[
                    "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
                ]
            ]
            member = target.lstrip("/") if target.startswith("/") else "xl/" + target
            with archive.open(member) as stream:
                for _, element in ET.iterparse(stream, events=("end",)):
                    if element.tag.endswith("}row"):
                        physical += int(element.attrib["r"]) > profile.header_row
                    element.clear()
    mappings = [
        {
            "sheet_id": digest(profile.name),
            "header_row": profile.header_row,
            "family": profile.sheet_family,
            "fields": {
                field: {
                    "header_sha256": digest(header),
                    "column_index": next(
                        cell.index for cell in profile.headers if cell.key == header
                    ),
                }
                for field, header in profile.field_map.items()
            },
            "date_order": profile.date_order,
        }
        for profile in profiles
    ]
    counts = {
        "raw_physical_data_rows": physical,
        "nonempty": nonempty,
        "accepted": len(candidates),
        "rejected": len(rejected),
        "rejected_by_reason": dict(Counter(row["reason"] for row in rejected)),
    }
    workbook_sha256 = hashlib.sha256(data).hexdigest()
    rejected_provenance = [
        {
            "row_id": digest([workbook_sha256, row["sheet"], row["row"]]),
            "sheet_id": digest(row["sheet"]),
            "physical_row": row["row"],
            "reason": row["reason"],
        }
        for row in rejected
    ]
    return freeze(data, candidates, mappings=mappings, counts=counts, rejected=rejected_provenance)


def _flags(candidates: list[ParsedContact]) -> dict[int, set[str]]:
    flags: dict[int, set[str]] = {index: set() for index in range(len(candidates))}
    signatures: dict[str, list[int]] = defaultdict(list)
    for index, candidate in enumerate(candidates):
        signatures[event_signature(candidate)].append(index)
        if candidate.evidence.get("source_semantics_inference"):
            flags[index].add("source_event_family_inferred")
        if not source_identity(candidate):
            flags[index].add("missing_property_identity")
        if candidate.transaction_date is None:
            flags[index].add("missing_date")
        if not (candidate.phone_primary or candidate.phone_alternate or candidate.email_primary):
            flags[index].add("person_identity_name_and_property_only")
    for indexes in signatures.values():
        if len(indexes) > 1:
            for index in indexes:
                flags[index].add("duplicate_source_event")
    return flags


def source_arm(baseline: Baseline, source_semantics="strict") -> list[dict[str, Any]]:
    candidates = policy_candidates(baseline, source_semantics)
    flags = _flags(candidates)
    grouped: dict[Any, list[tuple[int, ParsedContact]]] = defaultdict(list)
    for index, candidate in enumerate(candidates):
        grouped[source_identity(candidate)].append((index, candidate))
    summaries = {}
    for identity, group in grouped.items():
        if identity is None:
            continue
        sales = [item for _, item in group if has_sale_evidence(item)]
        buyers = [item for item in sales if item.party_role == "Buyer" and item.transaction_date]
        latest_buyer = max((item.transaction_date for item in buyers), default=None)
        roles = defaultdict(set)
        for item in sales:
            roles[(source_person(item), item.transaction_date)].add(item.party_role)
        non_sales = [item for _, item in group if not has_sale_evidence(item)]
        scopes = {(item.area_name, item.project_name) for _, item in group}
        scope_dicts = [
            dict(zip(("area_name", "project_name"), scope, strict=True)) for scope in scopes
        ]
        incompatible_scope = any(
            not _property_scopes_compatible(left, right)
            for i, left in enumerate(scope_dicts)
            for right in scope_dicts[i + 1 :]
        )
        summaries[identity] = {
            "incompatible_scope": incompatible_scope,
            "latest_buyer": latest_buyer,
            "latest_sale": max(
                (item.transaction_date for item in sales if item.transaction_date), default=None
            ),
            "tied": {
                source_person(item) for item in buyers if item.transaction_date == latest_buyer
            },
            "roles": roles,
            "undated_sale": any(not item.transaction_date for item in sales),
            "undated_lifecycle": any(not item.transaction_date for item in non_sales),
            "latest_lifecycle": max(
                (item.transaction_date for item in non_sales if item.transaction_date), default=None
            ),
        }
    result = []
    for index, candidate in enumerate(candidates):
        identity = source_identity(candidate)
        local_flags = flags[index]
        summary = summaries.get(identity, {})
        latest_buyer = summary.get("latest_buyer")
        latest_sale = summary.get("latest_sale")
        tied = summary.get("tied", set())
        same_party_roles = summary.get("roles", {}).get(
            (source_person(candidate), candidate.transaction_date), set()
        )
        if summary.get("incompatible_scope"):
            local_flags.add("incompatible_project_scope")
        if len(tied) > 1:
            local_flags.add("latest_buyer_tie_or_coowners")
        if same_party_roles == {"Buyer", "Seller"}:
            local_flags.add("conflicting_party_roles")
        if summary.get("undated_sale"):
            local_flags.add("undated_sale_on_property")
        latest_lifecycle = summary.get("latest_lifecycle")
        lifecycle = summary.get("undated_lifecycle") or (
            latest_lifecycle
            and (not candidate.transaction_date or latest_lifecycle >= candidate.transaction_date)
        )
        if lifecycle:
            local_flags.add("non_sale_lifecycle_on_property")
        if not identity:
            status = "missing_source_identity"
        elif not has_sale_evidence(candidate):
            status = "non_sale_source_event"
        elif not candidate.transaction_date:
            status = "uncertain_source_dates"
        elif summary.get("incompatible_scope") or same_party_roles == {"Buyer", "Seller"}:
            status = "uncertain_source_parties"
        elif candidate.party_role == "Seller" or (
            latest_sale and candidate.transaction_date < latest_sale
        ):
            status = "former_source_sale_supported"
        elif len(tied) > 1:
            status = "uncertain_source_parties"
        elif "undated_sale_on_property" in local_flags:
            status = "uncertain_source_dates"
        elif lifecycle:
            status = "uncertain_source_lifecycle"
        elif candidate.party_role == "Buyer" and candidate.transaction_date == latest_buyer:
            status = "current_as_of_file_inferred"
        else:
            status = "uncertain_source_parties"
        result.append(
            {
                "row_id": row_id(baseline.workbook_sha256, candidate),
                "person_id": source_person(candidate),
                "property_id": digest(identity) if identity else None,
                "property": property_labels(candidate),
                "original_source_property": {
                    name: str(
                        candidate.evidence.get("source_fields", {}).get(
                            name, getattr(candidate, name)
                        )
                    )
                    for name in property_labels(candidate)
                },
                "sheet_id": digest(candidate.source_sheet),
                "physical_row": candidate.source_row_number,
                "status": status,
                "role": candidate.party_role
                if candidate.party_role in {"Buyer", "Seller"}
                else "Other",
                "event_family": candidate.evidence.get("event_family", "unknown"),
                "parsed_event_family": candidate.evidence.get(
                    "parsed_event_family", candidate.evidence.get("event_family", "unknown")
                ),
                "source_semantics_inference": candidate.evidence.get("source_semantics_inference"),
                "duplicate_group_id": event_signature(candidate)
                if "duplicate_source_event" in local_flags
                else None,
                "date": candidate.transaction_date.isoformat()
                if candidate.transaction_date
                else None,
                "amount_aed": candidate.transaction_price_aed,
                "flags": sorted(local_flags),
            }
        )
    return result


def _assessment_rows(candidates: list[ParsedContact]) -> list[dict[str, Any]]:
    return [
        {
            **asdict(candidate),
            "id": index,
            "owner_key": _candidate_owner_key(candidate),
            "property_key": candidate.property_key,
            "import_id": 1,
            "event_family": candidate.evidence.get("event_family", "unknown"),
            "claim_resolver_version": IMPORT_RESOLVER_VERSION,
        }
        for index, candidate in enumerate(candidates)
    ]


def registry_arm(
    baseline: Baseline, evidence_json: str, source_semantics="strict"
) -> list[dict[str, Any]]:
    from app.crm.owner_assessment import _finish_assessment, match_owner_evidence
    from app.crm.owner_projection import _property_identity

    candidates = policy_candidates(baseline, source_semantics)
    source_evidence = [
        candidate.evidence.get("source_semantics_inference", {}).get("parsed_evidence_sha256")
        or digest(candidate.evidence)
        for candidate in candidates
    ]
    rows = _assessment_rows(candidates)
    valid = [
        (row, candidate)
        for row, candidate in zip(rows, candidates, strict=True)
        if _property_identity(row)
    ]
    bundle = json.loads(evidence_json)
    for sale in bundle["sales"]:
        if sale.get("transaction_date"):
            sale["transaction_date"] = date.fromisoformat(sale["transaction_date"])
    sales = match_owner_evidence([candidate for _, candidate in valid], bundle)
    snapshot = _finish_assessment(rows, valid, sales, datetime.now(timezone.utc), "available")
    result = []
    for row, candidate in zip(snapshot.rows, candidates, strict=True):
        source = baseline.workbook_sha256
        later = candidate.later_sale_date
        matched = candidate.evidence.get("matched_sale_date")
        events = sales.get(candidate.property_key, [])
        later_events = [
            event
            for event in events
            if matched and event["transaction_date"] > date.fromisoformat(matched)
        ]
        matched_key = candidate.evidence.get("matched_sale_key")
        acquisition = next(
            (
                event
                for event in events
                if str(
                    event.get("sale_key")
                    or f"{event['transaction_date']}:{event.get('sale_amount_aed')}"
                )
                == matched_key
            ),
            None,
        )
        acquisition_amount = acquisition.get("sale_amount_aed") if acquisition else None
        disposal = [
            {
                "sale_id": digest(
                    str(
                        event.get("sale_key")
                        or f"{event['transaction_date']}:{event.get('sale_amount_aed')}"
                    )
                ),
                "date": str(event["transaction_date"]),
                "amount_aed": event.get("sale_amount_aed"),
                "amount_ratio_to_acquisition": event.get("sale_amount_aed") / acquisition_amount
                if acquisition_amount and event.get("sale_amount_aed")
                else None,
                "size_ratio_to_acquisition": event.get("size_sqft") / acquisition["size_sqft"]
                if acquisition and acquisition.get("size_sqft") and event.get("size_sqft")
                else None,
                "extent": "extent_unverified",
            }
            for event in later_events
        ]
        result.append(
            {
                "row_id": row_id(source, candidate),
                "person_id": digest(row["canonical_owner_key"]),
                "property_id": digest(row["property_identity"])
                if row["property_identity"]
                else None,
                "property": property_labels(candidate),
                "event_family": candidate.evidence.get("event_family", "unknown"),
                "parsed_event_family": candidate.evidence.get(
                    "parsed_event_family", candidate.evidence.get("event_family", "unknown")
                ),
                "source_semantics_inference": candidate.evidence.get("source_semantics_inference"),
                "flags": ["source_event_family_inferred"]
                if candidate.evidence.get("source_semantics_inference")
                else [],
                "status": row["assessed_status"],
                "confidence_score": row["assessed_confidence_score"],
                "event_status": row["event_assessed_status"],
                "event_confidence_score": row["event_assessed_confidence_score"],
                "later_registration_date": str(later) if later else None,
                "disposal_extent": "extent_unverified" if later or later_events else None,
                "later_registrations": disposal,
                "source_evidence_sha256": source_evidence[row["id"]],
                "evidence_sha256": digest(candidate.evidence),
                "matched_sale_date": matched,
                "matched_sale_id": digest(matched_key) if matched_key else None,
                "matched_sale_amount_aed": acquisition_amount,
                "reason_code": "registry_" + row["assessed_status"],
                "evidence_reason": (
                    "A matched acquisition has later registry registrations; the disposal extent is unverified."
                    if matched and later_events
                    else "An acquisition matched source date, amount and available size; v5 projection determines the relationship label."
                    if matched
                    else "No unique sale acquisition is established for this source assertion; the v5 result remains unverified or unresolved."
                ),
                "matched_date_offset_days": (
                    date.fromisoformat(matched) - candidate.transaction_date
                ).days
                if matched and candidate.transaction_date
                else None,
                "extent_reason": "Later registration observed; whole-interest disposal extent is unverified."
                if later_events or later
                else None,
                "sale_anchor_id": digest(candidate.evidence["sale_anchor_key"])
                if candidate.evidence.get("sale_anchor_key")
                else None,
            }
        )
    return result


def source_relationship_status(rows: list[dict[str, Any]]) -> str:
    """Order a person's source events; newer uncertainty must not revive an older label."""
    if all(row["property_id"] is None for row in rows):
        return "missing_source_identity"
    if any("incompatible_project_scope" in row.get("flags", []) for row in rows):
        return "uncertain_source_parties"
    if any(not row["date"] and row["event_family"] == "sale" for row in rows):
        return "uncertain_source_dates"
    if any(not row["date"] and row["event_family"] != "sale" for row in rows):
        return "uncertain_source_lifecycle"
    latest = max((row["date"] or "" for row in rows), default="")
    statuses = {row["status"] for row in rows if (row["date"] or "") == latest}
    if "non_sale_source_event" in statuses and any(row["event_family"] == "sale" for row in rows):
        return "uncertain_source_lifecycle"
    uncertain = sorted(status for status in statuses if status.startswith("uncertain_"))
    if uncertain:
        return uncertain[0]
    return next(iter(statuses)) if len(statuses) == 1 else "uncertain_source_parties"


def _counts(rows: list[dict[str, Any]], *, source=False) -> dict[str, Any]:
    relationships = defaultdict(list)
    for row in rows:
        if row["property_id"]:
            relationships[(row["person_id"], row["property_id"])].append(row)
    categories = []
    for group in relationships.values():
        statuses = {row["status"] for row in group}
        categories.append(
            source_relationship_status(group)
            if source
            else (next(iter(statuses)) if len(statuses) == 1 else "mixed_canonical_assessments")
        )
    return {
        "rows": len(rows),
        "people": len({row["person_id"] for row in rows}),
        "properties": len({row["property_id"] for row in rows if row["property_id"]}),
        "relationships": len(relationships),
        "missing_identity_rows": sum(row["property_id"] is None for row in rows),
        "event_categories": dict(
            sorted(Counter(row.get("event_status", row["status"]) for row in rows).items())
        ),
        "relationship_categories": dict(sorted(Counter(categories).items())),
        "extent_unverified_rows": sum(
            row.get("disposal_extent") == "extent_unverified" for row in rows
        ),
        "extent_unverified_relationships": sum(
            any(row.get("disposal_extent") == "extent_unverified" for row in group)
            for group in relationships.values()
        ),
    }


def reconcile(a: list[dict[str, Any]], b: list[dict[str, Any]]) -> dict[str, Any]:
    a_by_id = {row["row_id"]: row for row in a}
    b_by_id = {row["row_id"]: row for row in b}
    assert len(a_by_id) == len(a) == len(b_by_id) == len(b), "Duplicate or lost source rows"
    assert a_by_id.keys() == b_by_id.keys(), "Arms have different source rows"
    associations: dict[tuple[str, str], list[str]] = defaultdict(list)
    for row in a:
        # Missing identities remain individually counted in the fixed denominator.
        associations[(row["person_id"], row["property_id"] or row["row_id"])].append(row["row_id"])
    matrix: Counter[tuple[str, str]] = Counter()
    for ids in associations.values():
        source_status = source_relationship_status([a_by_id[key] for key in ids])
        statuses = {b_by_id[key]["status"] for key in ids}
        registry_status = (
            next(iter(statuses)) if len(statuses) == 1 else "mixed_canonical_assessments"
        )
        matrix[(source_status, registry_status)] += 1
    identity_changes = {}
    for field in ("person_id", "property_id"):
        forwards: dict[str, set[str]] = defaultdict(set)
        backwards: dict[str, set[str]] = defaultdict(set)
        for key, left in a_by_id.items():
            right = b_by_id[key]
            if left[field] and right[field]:
                forwards[left[field]].add(right[field])
                backwards[right[field]].add(left[field])
        identity_changes[field] = {
            "source_identities_split": sum(len(values) > 1 for values in forwards.values()),
            "canonical_identities_merged": sum(len(values) > 1 for values in backwards.values()),
            "rows_losing_identity": sum(
                bool(a_by_id[key][field]) and not row[field] for key, row in b_by_id.items()
            ),
            "rows_gaining_identity": sum(
                not a_by_id[key][field] and bool(row[field]) for key, row in b_by_id.items()
            ),
        }
    assert sum(matrix.values()) == len(associations)
    return {
        "accepted_row_denominator": len(a),
        "fixed_source_association_denominator": len(associations),
        "matrix": [
            {"a": left, "b": right, "count": count}
            for (left, right), count in sorted(matrix.items())
        ],
        "a": _counts(a, source=True),
        "b": _counts(b),
        "identity_changes": identity_changes,
    }


def measure(function, *args):
    wall, cpu = time.perf_counter(), time.thread_time()
    value = function(*args)
    return value, {
        "wall_seconds": time.perf_counter() - wall,
        "thread_cpu_seconds": time.thread_time() - cpu,
        "process_peak_rss_kib_shared": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
    }


def run_arms(
    baseline: Baseline, evidence_json: str, *, execution="parallel", source_semantics="strict"
):
    if execution == "parallel":
        with ThreadPoolExecutor(max_workers=2) as pool:
            a = pool.submit(measure, source_arm, baseline, source_semantics)
            b = pool.submit(measure, registry_arm, baseline, evidence_json, source_semantics)
            return a.result(), b.result()
    return measure(source_arm, baseline, source_semantics), measure(
        registry_arm, baseline, evidence_json, source_semantics
    )


async def capture_evidence(baseline: Baseline) -> tuple[str, dict[str, Any]]:
    from app.crm import owner_assessment
    from app.crm.owner_queries import fetch_assessment_source_fingerprint

    started = datetime.now(timezone.utc)
    before = await fetch_assessment_source_fingerprint()
    bundle = await owner_assessment.capture_owner_evidence(baseline.candidates())
    after = await fetch_assessment_source_fingerprint()
    ended = datetime.now(timezone.utc)
    if canonical(before) != canonical(after):
        raise RuntimeError("DXBI/alias physical fingerprints changed during evidence capture")
    # Sort records independently of provider ordering; dates serialize canonically.
    frozen = canonical({key: sorted(bundle[key], key=canonical) for key in ("aliases", "sales")})
    return frozen, {
        "sha256": hashlib.sha256(frozen.encode()).hexdigest(),
        "capture_started_at": started.isoformat(),
        "capture_ended_at": ended.isoformat(),
        "publication_time": None,
        "publication_time_known": False,
        "stable_physical_fingerprint": before,
        "snapshot_semantics": "stable physical fingerprints across capture; merges invalidate capture; not timestamp-atomic",
        "provenance": {
            "sales": "DXBI dxbi_sales_unit_events",
            "aliases": "existing analytics_building_keys alias registry",
        },
        "sales_count": len(bundle["sales"]),
        "aliases_count": len(bundle["aliases"]),
    }


def report(
    baseline, evidence_metadata, a, b, metrics, *, examples_page=None, source_semantics="strict"
):
    from app.crm.owner_assessment import ASSESSMENT_VERSION

    source_counts = json.loads(baseline.counts_json)
    physical, nonempty = source_counts.get("raw_physical_data_rows"), source_counts.get("nonempty")
    if isinstance(physical, int) and isinstance(nonempty, int) and physical >= nonempty:
        source_counts["blank_or_formatting_rows"] = physical - nonempty
    duplicate_counts = Counter(
        row["duplicate_group_id"] for row in a if row.get("duplicate_group_id")
    )
    inferred_a = {row["row_id"] for row in a if row.get("source_semantics_inference")}
    inferred_b = {row["row_id"] for row in b if row.get("source_semantics_inference")}
    assert inferred_a == inferred_b, "Arms applied different source semantics inference"
    assert source_semantics != "strict" or not inferred_a, (
        "Strict policy cannot report inferred events"
    )
    assert all(
        row["source_semantics_inference"]["policy"] == source_semantics
        for row in [*a, *b]
        if row.get("source_semantics_inference")
    ), "Reported policy differs from row inference provenance"
    result = {
        "source_semantics": {
            "policy": source_semantics,
            "rule_version": SOURCE_SEMANTICS_RULE
            if source_semantics == "dated-parties"
            else "strict-parser-output",
            "inferred_rows_a": len(inferred_a),
            "inferred_rows_b": len(inferred_b),
            "rule": "Only parsed contact_snapshot with blank procedure, dated Buyer/Seller and positive amount may infer sale"
            if source_semantics == "dated-parties"
            else "Use unchanged parsed event family",
            "legal_ownership_proof": False,
        },
        "duplicate_groups": len(duplicate_counts),
        "duplicate_extra_rows": sum(count - 1 for count in duplicate_counts.values()),
        "distinct_nonduplicate_event_count": len(a)
        - sum(count - 1 for count in duplicate_counts.values()),
        "assessment_version": ASSESSMENT_VERSION,
        "scoring_rules": "Existing v5 ownership scoring, unchanged by comparison harness",
        "b_scope": "Direct source property identity plus captured existing aliases and DXBI sales, then v5 finish/projection. Import identity recovery, transaction/near-transaction recovery, rental, cadastral, cache, tenant repository and prior enriched claims excluded.",
        "rejected_provenance_sha256": digest(baseline.rejected_json),
        "event": "controlled_owner_comparison",
        "workbook_sha256": baseline.workbook_sha256,
        "parser_sha256": baseline.parser_sha256,
        "comparison_code_sha256": digest(
            {
                str(path.relative_to(Path(__file__).resolve().parents[2])): hashlib.sha256(
                    path.read_bytes()
                ).hexdigest()
                for path in [
                    Path(__file__).resolve(),
                    *[
                        Path(import_parsing.__file__).parent / name
                        for name in ("owner_assessment.py", "owner_projection.py", "ownership.py")
                    ],
                ]
            }
        ),
        "baseline_sha256": digest(baseline.candidates_json),
        "rules_version": RULE_VERSION,
        "rules": RULES,
        "resolver_version": IMPORT_RESOLVER_VERSION,
        "sheet_mappings": json.loads(baseline.mappings_json),
        "source_counts": source_counts,
        "source_cutoff": None,
        "observed_max_event_date": max((row["date"] for row in a if row["date"]), default=None),
        "source_flags": dict(sorted(Counter(flag for row in a for flag in row["flags"]).items())),
        "duplicate_events_retained": sum("duplicate_source_event" in row["flags"] for row in a),
        "evidence": evidence_metadata,
        "comparison": reconcile(a, b),
        "metrics": metrics,
    }
    if examples_page is not None:
        samples: dict[str, list[dict[str, Any]]] = defaultdict(list)
        b_by_id = {row["row_id"]: row for row in b}
        sampled_relationships = set()
        for row in sorted(a, key=lambda item: (item["date"] or "", item["row_id"]), reverse=True):
            registry = b_by_id[row["row_id"]]
            category = registry["status"]
            relationship = (registry["person_id"], registry["property_id"] or registry["row_id"])
            if len(samples[category]) < 3 and relationship not in sampled_relationships:
                sampled_relationships.add(relationship)
                samples[category].append({"a": row, "b": registry})
        examples = [example for category in sorted(samples) for example in samples[category]]
        start = (examples_page - 1) * 10
        result["examples"] = {
            "page": examples_page,
            "page_size": 10,
            "total": len(examples),
            "per_category_limit": 3,
            "rows": examples[start : start + 10],
        }
    return result


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execution", choices=("parallel", "sequential"), default="parallel")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--source-semantics", choices=("strict", "dated-parties"), default="strict")
    parser.add_argument(
        "--timing-label", choices=("cold", "warm", "unspecified"), default="unspecified"
    )
    parser.add_argument("--examples-page", type=int)
    args = parser.parse_args()
    if args.repeat < 1 or (args.examples_page is not None and args.examples_page < 1):
        parser.error("Repeat and example page must be positive")
    # Suppress application/provider logs that could contain source values.
    logging.disable(logging.CRITICAL)
    baseline, parse_metrics = await asyncio.to_thread(measure, parse_workbook, AUTHORIZED_WORKBOOK)
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
        send_receive_timeout=300,
        query_retries=2,
    )
    try:
        capture_start, capture_cpu = time.perf_counter(), time.process_time()
        evidence, metadata = await capture_evidence(baseline)
        evidence_metrics = {
            "wall_seconds": time.perf_counter() - capture_start,
            "process_cpu_seconds": time.process_time() - capture_cpu,
            "process_peak_rss_kib_shared": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        }
        expected_results = None
        for iteration in range(args.repeat):
            (a, am), (b, bm) = await asyncio.to_thread(
                run_arms,
                baseline,
                evidence,
                execution=args.execution,
                source_semantics=args.source_semantics,
            )
            results_hash = digest([a, b])
            if expected_results is not None and results_hash != expected_results:
                raise RuntimeError("Repeated arms changed classifications or evidence")
            expected_results = results_hash
            metrics = {
                "deterministic_results_sha256": results_hash,
                "repeat_equal_verified": iteration > 0,
                "parse": parse_metrics,
                "evidence_capture": evidence_metrics,
                "a": am,
                "b": bm,
                "execution": args.execution,
                "iteration": iteration + 1,
                "timing_label_operator_supplied": args.timing_label,
                "in_process_state": "first_evaluation" if iteration == 0 else "repeated_evaluation",
                "memory_semantics": "Linux process RSS high-water; shared by worker threads",
            }
            print(
                canonical(
                    report(
                        baseline,
                        metadata,
                        a,
                        b,
                        metrics,
                        examples_page=args.examples_page,
                        source_semantics=args.source_semantics,
                    )
                ),
                flush=True,
            )
            del a, b
    finally:
        await warehouse.close_clickhouse()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as error:
        # Exception text may contain SQL values or source contacts.
        print(
            canonical({"event": "comparison_failed", "error_type": type(error).__name__}),
            flush=True,
        )
        raise SystemExit(1) from None
