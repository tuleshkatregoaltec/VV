#!/usr/bin/env python3
"""Source property references and size-supported proposals, never title verification.

Run after clean_owner_workbook. No database calls or application importer changes.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

from app.crm.import_normalization import positive_decimal
from scripts.crm.clean_owner_workbook import _csv_value, load_source

RULE_VERSION = "owner-source-inventory-1"


def token(value) -> str:
    text = " ".join(str(value).strip().casefold().split()) if value is not None else ""
    return "" if text in {"", "null", "n/a", "#n/a", "0"} else text


def reference_key(row: tuple, source_row: int) -> tuple:
    """Keep apartment numbers tower-scoped; never replace villa names with cluster IDs."""
    project, building, name, unit, land = (token(row[i]) for i in (3, 5, 6, 8, 11))
    if unit and name:
        return ("unit", name, unit)
    if not unit and name and project:
        return ("named_villa_or_building", project, name)
    if not unit and building and land:
        return ("building_number_only", project, land, building)
    if not unit and land:
        # This is a workbook-local parcel REFERENCE, not a globally unique cadastral ID.
        return ("parcel_only", land)
    return ("unidentified_row", str(source_row))


def reference_id(key: tuple) -> str:
    return hashlib.sha256(json.dumps(key).encode()).hexdigest()[:24]


def area(row: tuple) -> float | None:
    value = positive_decimal(row[7])
    return float(value) if value is not None else None


def compatible_area(left: float, right: float) -> bool:
    """Allow rounding only; this proposes a link and cannot prove property identity."""
    return abs(left - right) <= max(0.5, 0.005 * min(left, right))


def candidate_events(records: list[tuple[int, tuple, tuple]]) -> list[dict]:
    """Combine label variants and party sides without erasing rows or asserting a sale ID."""
    events = {}
    for number, _raw, row in records:
        reference = reference_key(row, number)
        key = (reference, row[0], row[1], row[7])
        event = events.setdefault(key, {"rows": [], "values": set()})
        event["rows"].append(number)
        event["values"].add(row)
    result = []
    for (reference, when, price, sqm), event in events.items():
        roles = Counter(token(row[12]) for row in event["values"])
        result.append(
            {
                "candidate_event_id": hashlib.sha256(
                    json.dumps([reference, when, price, sqm], default=str).encode()
                ).hexdigest()[:24],
                "reference_id": reference_id(reference),
                "reference_kind": reference[0],
                "date": str(when),
                "value_aed": price,
                "size_sqm": sqm,
                "source_rows": len(event["rows"]),
                "retained_party_rows": len(event["values"]),
                "buyer_rows": roles["buyer"],
                "seller_rows": roles["seller"],
                "source_attribute_variants": len({row[:12] for row in event["values"]}),
                "source_row_numbers": ";".join(map(str, event["rows"])),
            }
        )
    return result


def build_inventory(records: list[tuple[int, tuple, tuple]]) -> tuple[list, list, dict]:
    groups, named_by_context, granular_by_land = {}, defaultdict(set), defaultdict(set)
    for number, _raw, row in records:
        key = reference_key(row, number)
        group = groups.setdefault(key, {"rows": [], "values": set(), "observations": []})
        group["rows"].append(number)
        group["values"].add(row)
        group["observations"].append((number, row))
        if key[0] == "named_villa_or_building":
            named_by_context[(token(row[3]), token(row[11]), token(row[5]))].add(key)
        if key[0] in {"unit", "named_villa_or_building"}:
            granular_by_land[token(row[11])].add(key)

    inventory, proposals = [], []
    proposal_counts = Counter()
    for key, group in groups.items():
        rows = group["values"]
        areas = sorted({area(row) for row in rows if area(row) is not None})
        lands = sorted({token(row[11]) for row in rows if token(row[11])})
        types = sorted({token(row[10]) or "missing" for row in rows})
        names = sorted({token(row[6]) for row in rows if token(row[6])})
        flags = []
        if key[0] in {"building_number_only", "parcel_only", "unidentified_row"}:
            flags.append("incomplete_individual_identity")
        if len(lands) > 1:
            flags.append("same_address_multiple_land_numbers")
        if areas and areas[-1] / areas[0] > 1.1:
            flags.append("area_spread_over_10_percent")
        if any(key[0] == "parcel_only" and granular_by_land[land] for land in lands):
            flags.append("parcel_overlaps_individual_asset_records")
        if key[0] == "building_number_only":
            context = tuple(key[1:])
            if named_by_context[context]:
                flags.append("building_number_also_indexes_named_assets")
        if any(not token(row[3]) for row in rows):
            flags.append("missing_project")
        if key[0] == "unit":
            judgment = "numbered_unit"
        elif "villa" in types:
            judgment = "villa_evidence_keep_individual_identifier"
        elif key[0] == "named_villa_or_building" and areas and areas[-1] <= 1000:
            judgment = "small_named_building_villa_scale_not_whole_tower_proof"
        elif set(types) <= {"land", "residential", "general use", "missing"}:
            judgment = "plot_or_land_use_record_keep_as_parcel_evidence"
        else:
            judgment = "building_or_plot_extent_requires_review"
        inventory.append(
            {
                "reference_id": reference_id(key),
                "kind": key[0],
                "source_key": json.dumps(key, ensure_ascii=False),
                "source_rows": len(group["rows"]),
                "clean_rows": len(rows),
                "source_row_numbers": ";".join(map(str, group["rows"])),
                "land_numbers": ";".join(lands),
                "recorded_property_types": ";".join(types),
                "building_names": ";".join(names),
                "size_min_sqm": areas[0] if areas else None,
                "size_max_sqm": areas[-1] if areas else None,
                "distinct_sizes": len(areas),
                "distinct_dates": len({row[0] for row in rows}),
                "distinct_prices": len({row[1] for row in rows}),
                "judgment": judgment,
                "review_reasons": ";".join(flags),
            }
        )
        if key[0] not in {"building_number_only", "parcel_only"}:
            continue
        # Evaluate each retained observation: one parent reference can contain many sizes.
        observations = defaultdict(list)
        for number, row in group["observations"]:
            observations[(token(row[3]), token(row[11]), token(row[5]), area(row))].append(number)
        for (project, land, building, sqm), numbers in observations.items():
            anchors = named_by_context[(project, land, building)] if building else set()
            candidates = sorted(
                reference_id(anchor)
                for anchor in anchors
                if sqm is not None
                and any(
                    area(row) is not None and compatible_area(sqm, area(row))
                    for row in groups[anchor]["values"]
                )
            )
            decision = (
                "one_observed_size_match_proposed_only"
                if len(candidates) == 1
                else "multiple_size_matches_do_not_merge"
                if candidates
                else "no_size_match_keep_unresolved"
            )
            proposal_counts[decision] += len(numbers)
            proposals.append(
                {
                    "reference_id": reference_id(key),
                    "source_row_numbers": ";".join(map(str, numbers)),
                    "size_sqm": sqm,
                    "candidate_named_reference_ids": ";".join(candidates),
                    "decision": decision,
                }
            )
    kinds = Counter(item["kind"] for item in inventory)
    flags = Counter(
        flag for item in inventory for flag in item["review_reasons"].split(";") if flag
    )
    by_kind_rows = Counter()
    for item in inventory:
        by_kind_rows[item["kind"]] += item["source_rows"]
    summary = {
        "rule_version": RULE_VERSION,
        "source_rows": len(records),
        "clean_rows": sum(item["clean_rows"] for item in inventory),
        "source_reference_groups": len(inventory),
        "reference_groups_by_kind": dict(kinds),
        "source_rows_by_kind": dict(by_kind_rows),
        "named_individual_reference_groups": kinds["unit"] + kinds["named_villa_or_building"],
        "incomplete_identity_reference_groups": sum(
            kinds[kind] for kind in ("building_number_only", "parcel_only", "unidentified_row")
        ),
        "review_reference_groups_by_reason": dict(flags),
        "size_proposal_source_rows": dict(proposal_counts),
        "references_with_multiple_dates": sum(item["distinct_dates"] > 1 for item in inventory),
        "references_with_multiple_prices": sum(item["distinct_prices"] > 1 for item in inventory),
        "distinct_land_number_values": len({token(row[11]) for _, _, row in records}),
        "exact_physical_property_count": None,
        "denominator_status": "not_certified_mixed_granularity_and_incomplete_identifiers",
        "size_unit": "sqm_user_confirmed_2026-10-26",
        "size_link_tolerance": "max(0.5 sqm, 0.5% of smaller area); proposals only",
        "size_classification": "1000 sqm is a descriptive small-building heuristic, not identity",
        "scope": "Workbook-local source references; no cadastral area IDs or registry lookup",
        "observed_date_min": min(str(row[0]) for _, _, row in records),
        "observed_date_max": max(str(row[0]) for _, _, row in records),
    }
    assert sum(item["source_rows"] for item in inventory) == len(records)
    assert sum(item["clean_rows"] for item in inventory) == len({row for _, _, row in records})
    return inventory, proposals, summary


def write_inventory(source: Path, destination: Path) -> dict:
    _, records, _ = load_source(source)
    inventory, proposals, summary = build_inventory(records)
    events = candidate_events(records)
    summary["canonical_candidate_event_groups"] = len(events)
    summary["canonical_candidate_events_with_both_party_sides"] = sum(
        bool(event["buyer_rows"] and event["seller_rows"]) for event in events
    )
    summary["canonical_candidate_events_with_source_label_variants"] = sum(
        event["source_attribute_variants"] > 1 for event in events
    )
    summary["canonical_candidate_event_rule"] = (
        "Source reference + exact date/value/size, ignoring source type/master label variants; "
        "no transaction ID, so these remain candidates. All party records retained."
    )
    summary["source_sha256"] = hashlib.sha256(source.read_bytes()).hexdigest()
    assert sum(event["source_rows"] for event in events) == len(records)
    assert sum(event["retained_party_rows"] for event in events) == summary["clean_rows"]
    destination.mkdir(parents=True, exist_ok=True)
    for name, values in (
        ("property-inventory.csv", inventory),
        ("size-link-review.csv", proposals),
        ("canonical-candidate-events.csv", events),
    ):
        with (destination / name).open("w", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream)
            if values:
                writer.writerow(values[0])
                writer.writerows([_csv_value(v) for v in item.values()] for item in values)
    (destination / "property-metrics.json").write_text(json.dumps(summary, indent=2) + "\n")
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    print(json.dumps(write_inventory(args.source, args.destination), indent=2))
