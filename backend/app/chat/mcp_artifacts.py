"""Pure rendering of successful MCP evidence into the existing chat card formats.

No queries, model-request dispatch, metric calculations or inferred inventory totals live
here. Call only after FunctionToolResultEvent, with the returned MCP envelope. The same
artifact can be streamed and persisted unchanged for later replay.
"""

from __future__ import annotations

import json
import math
from copy import deepcopy
from typing import Any

MAX_ARTIFACTS = 3
MAX_CHART_POINTS = 50
MAX_LISTINGS = 20
MAX_ARTIFACT_BYTES = 64 * 1024


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _notes(data: dict, evidence: dict) -> list[str]:
    notes = []
    for source in (data, evidence):
        coverage = source.get("coverage") or {}
        if isinstance(coverage, dict) and coverage.get("status") in {"unverified", "partial"}:
            notes.append(f"Coverage {coverage['status']}.")
        notes.extend(note for note in source.get("limitations", []) if isinstance(note, str))
    return list(dict.fromkeys(notes))


def _base(kind, identifier, title, data, evidence, created_at, *, extra_notes=()):
    notes = list(dict.fromkeys([*extra_notes, *_notes(data, evidence)]))
    filters = data.get("filters") or {}
    period = data.get("period") or {}
    scope = [filters.get("location"), filters.get("building")]
    if period.get("start") and period.get("end"):
        scope.append(f"{period['start']} to {period['end']}")
    scope.extend(notes)
    return {
        "id": identifier,
        "type": kind,
        "status": "ready",
        "title": title,
        "subtitle": " · ".join(str(value) for value in scope if value),
        "created_at": created_at,
        "query": {
            "filters": deepcopy(filters),
            "period": deepcopy(period),
            "coverage": deepcopy(data.get("coverage", evidence.get("coverage"))),
            "release": deepcopy(evidence.get("release")),
            "reference_date": evidence.get("reference_date"),
            "sources": deepcopy(data.get("sources", data.get("source", evidence.get("sources")))),
            "limitations": notes,
        },
    }


def _metric_artifact(data, evidence, identifier, created_at):
    if data.get("status") in {"unavailable", "error", "clarification_required"}:
        return None
    if data.get("coverage", {}).get("status") == "unavailable":
        return None
    total = data.get("total")
    definitions = data.get("definitions")
    if not isinstance(total, dict) or not _number(total.get("count")):
        return None
    if not isinstance(definitions, list):
        return None
    definitions = [item for item in definitions if isinstance(item, dict)]
    # Select one returned requested metric. No cross-unit series or re-aggregation.
    metric = next((item for item in definitions if item.get("name") != "count"), None)
    metric = metric or next((item for item in definitions if item.get("name") == "count"), None)
    if metric is None:
        return None
    name, unit = metric.get("name"), metric.get("unit")
    if not isinstance(name, str) or not isinstance(unit, str):
        return None
    rows = data.get("rows") or [total]
    points = []
    omitted_unknown = False
    for row in rows:
        if not isinstance(row, dict):
            continue
        value = row.get("count") if name == "count" else (row.get("values") or {}).get(name)
        if not _number(value) or not _number(row.get("count")):
            omitted_unknown = True
            continue
        points.append(
            {
                "label": str(row.get("group") or "Selected period"),
                "value": value,
                "record_count": row["count"],
            }
        )
    if not points:
        return None
    notes = []
    if omitted_unknown:
        notes.append("Unknown values are omitted, never displayed as zero.")
    if len(points) > MAX_CHART_POINTS:
        notes.append(
            f"Showing the first {MAX_CHART_POINTS} returned groups; this chart is a subset."
        )
    points = points[:MAX_CHART_POINTS]
    amount = "achieved sale price" if data.get("dataset") == "sales" else "annual registered rent"
    labels = {
        "count": "Eligible records",
        "rated_count": "Records with known area",
        "total_contract_aed": "Total whole-term contract rent",
        "median_contract_aed": "Median whole-term contract rent",
        "total_aed": f"Total {amount}",
        "mean_aed": f"Mean {amount}",
        "median_aed": f"Median {amount}",
        "p25_aed": f"25th percentile {amount}",
        "p75_aed": f"75th percentile {amount}",
    }
    label = labels.get(name, f"{name.replace('_', ' ')} {amount}") + f" ({unit})"
    source_label = (
        "Achieved sales" if data.get("dataset") == "sales" else "Registered rental contracts"
    )
    artifact = _base(
        "custom_chart",
        identifier,
        f"{source_label}: {label}",
        data,
        evidence,
        created_at,
        extra_notes=notes,
    )
    dimension = (data.get("filters") or {}).get("group_by") or "period"
    artifact["query"].update(metric=name, definition=deepcopy(metric), displayed_groups=len(points))
    artifact["data"] = {
        # Bars never connect across missing periods or interpolate a price trajectory.
        "chart_type": "bar" if dimension == "month" else "horizontal_bar",
        "metric": name,
        "metric_label": label,
        "dimension": dimension,
        "dimension_label": str(dimension).replace("_", " ").title(),
        "data_source": source_label,
        "points": points,
        "series": [],
        "summary": {
            "point_count": len(points),
            "total_records": total["count"],
            "period_start": (data.get("period") or {}).get("start"),
            "period_end": (data.get("period") or {}).get("end"),
        },
    }
    return artifact


def _listing_artifact(data, evidence, identifier, created_at):
    if data.get("status") in {"unavailable", "error", "clarification_required"}:
        return None
    filters = data.get("filters") or {}
    mode = filters.get("mode")
    if mode not in {"sale", "rent"}:
        return None
    rows = data.get("listings", data.get("older_listings"))
    if not isinstance(rows, list) or not rows:
        return None
    listings, dates = [], []
    for row in rows[:MAX_LISTINGS]:
        if not isinstance(row, dict) or not isinstance(row.get("listing_id"), str):
            continue
        property_type = row.get("property_type")
        if property_type not in {"Apartment", "Villa", "Townhouse", "Office", "Shop"}:
            continue
        price, size = row.get("asking_price_aed"), row.get("size_sqft")
        age, rate = row.get("age_days_at_capture"), row.get("asking_aed_per_sqft")
        # Only display fields with direct evidence. Titles are labels, never source prose;
        # no links, descriptions, images or agent/broker/contact data are passed through.
        listings.append(
            {
                "listing_id": row["listing_id"],
                "listing_mode": mode,
                "asset_class": "commercial"
                if property_type in {"Office", "Shop"}
                else "residential",
                "title": f"{property_type} · {row.get('building') or row['listing_id']}",
                "property_type": property_type,
                "price_value": price if _number(price) and price > 0 else None,
                "price_currency": "AED" if _number(price) and price > 0 else None,
                "price_period": "year" if mode == "rent" else "sell",
                "size_value": size if _number(size) and size > 0 else None,
                "size_unit": "sqft" if _number(size) and size > 0 else None,
                "bedrooms": row.get("bedrooms"),
                "area_name": row.get("community"),
                "tower_name": row.get("building"),
                "listing_age_days": age if isinstance(age, int) and age >= 0 else None,
                "price_per_sqft_aed": rate if _number(rate) and rate > 0 else None,
            }
        )
        dates.append(
            {
                key: row.get(key)
                for key in (
                    "listing_id",
                    "posted_at",
                    "captured_at",
                    "first_observed_at",
                    "age_days_at_capture",
                )
            }
        )
    if not listings:
        return None
    notes = [
        f"{len(listings)} displayed from a bounded evidence sample; total matching inventory is unknown.",
        "Asking prices, not achieved prices.",
    ]
    if "older_listings" in data:
        notes.append("Listing age is posting-to-capture age; first observation remains unknown.")
    artifact = _base(
        "listing_results",
        identifier,
        "Rental listing evidence" if mode == "rent" else "Sale listing evidence",
        data,
        evidence,
        created_at,
        extra_notes=notes,
    )
    artifact["query"].update(
        mode=mode,
        area=filters.get("location"),
        returned_count=len(listings),
        total_scope="unknown",
        listing_dates=dates,
    )
    artifact["data"] = {
        "listings": listings,
        "total": None,
        "limit": len(listings),
        "offset": 0,
        "filters": {},
    }
    return artifact


def render_mcp_artifacts(
    tool_name: str, tool_call_id: str, envelope: dict, *, created_at: str
) -> list[dict]:
    """Render only completed, successful known capabilities; callers persist this exact result."""
    if envelope.get("status") != "ok" or not isinstance(envelope.get("data"), dict):
        return []
    data = envelope["data"]
    evidence = envelope.get("evidence") or {}
    identifier = f"mcp:{tool_name}:{tool_call_id}"
    candidates = []
    if tool_name == "query_market_metrics":
        candidates.append(_metric_artifact(data, evidence, identifier, created_at))
    elif tool_name in {"get_listing_inventory", "compare_listing_age", "compare_listing_rents"}:
        candidates.append(_listing_artifact(data, evidence, identifier, created_at))
    elif tool_name == "compose_market_report":
        for name, component in (data.get("components") or {}).items():
            if not isinstance(component, dict):
                continue
            candidate = _metric_artifact(component, evidence, f"{identifier}:{name}", created_at)
            candidate = candidate or _listing_artifact(
                component, evidence, f"{identifier}:{name}", created_at
            )
            if candidate:
                candidates.append(candidate)
            if len(candidates) == MAX_ARTIFACTS:
                break
    artifacts = [artifact for artifact in candidates if artifact][:MAX_ARTIFACTS]
    return (
        artifacts
        if len(json.dumps(artifacts, allow_nan=False).encode()) <= MAX_ARTIFACT_BYTES
        else []
    )
