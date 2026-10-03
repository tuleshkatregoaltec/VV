from __future__ import annotations

import math
import re
from datetime import date, datetime
from typing import Any

from app.crm.inbound_policy import _locations


def _location_fit(criteria: dict[str, Any], *values: str) -> tuple[int, str]:
    requested = _locations(criteria)
    if not requested:
        return 0, "Preferred location is missing"
    haystack = " ".join(values).casefold()
    if haystack.strip() and any(
        item.casefold() in haystack or haystack in item.casefold() for item in requested
    ):
        return 20, f"Matches {requested[0]}"
    return 0, "Outside preferred location"


def _budget_fit(criteria: dict[str, Any], value: float | None) -> tuple[int, str]:
    maximum = float(criteria.get("budget_max_aed") or 0)
    minimum = float(criteria.get("budget_min_aed") or 0)
    if not maximum and not minimum:
        return 0, "Budget is missing"
    if not value:
        return 5, "Price requires verification"
    lower_ok = (
        not minimum
        or value > minimum
        or (value == minimum and criteria.get("budget_min_inclusive", True))
    )
    upper_ok = (
        not maximum
        or value < maximum
        or (value == maximum and criteria.get("budget_max_inclusive", True))
    )
    if lower_ok and upper_ok:
        return 15, "Within stated budget"
    if maximum and value <= maximum * 1.1 and value >= minimum * 0.9:
        return 9, "Within flexible budget margin"
    return 0, "Outside budget"


def _bedroom_fit(criteria: dict[str, Any], value: str) -> tuple[int, str]:
    requested = criteria.get("bedrooms_min")
    if requested is None:
        return 0, "Bedroom requirement is missing"
    match = re.search(r"\d+", value)
    observed = int(match.group()) if match else 0 if "studio" in value.lower() else None
    maximum = criteria.get("bedrooms_max")
    if observed is not None and (
        int(requested) <= observed <= int(maximum)
        if maximum is not None
        else observed == int(requested)
    ):
        return 10, "Exact bedroom match"
    if observed is not None and abs(observed - int(requested)) <= 1:
        return 6, "Within flexible bedroom range"
    return 0, "Bedroom mismatch"


def _property_fit(criteria: dict[str, Any], value: str) -> int:
    requested = _canonical_property_type(criteria.get("property_type"))
    if not requested:
        return 0
    observed = _canonical_property_type(value)
    return 10 if requested == observed else 0


def _canonical_property_type(value: Any) -> str:
    normalized = str(value or "").strip().casefold()
    aliases = {
        "flat": "apartment",
        "apartments": "apartment",
        "residential flat": "apartment",
        "residential flats": "apartment",
        "residential": "apartment",
        "unit": "apartment",
        "condo": "apartment",
        "condominium": "apartment",
        "hotel apartments": "apartment",
        "townhouses": "townhouse",
        "villas": "villa",
        "offices": "office",
    }
    return aliases.get(normalized, normalized)


def _listing_property_type(value: Any) -> str | None:
    normalized = _canonical_property_type(value)
    return normalized.title() if normalized else None


def _violates_strict_fields(
    strict_fields: list[str],
    *,
    location_points: int,
    budget_points: int,
    bedroom_points: int,
    property_points: int,
) -> bool:
    checks = {
        "locations": location_points,
        "budget_min_aed": budget_points,
        "budget_max_aed": budget_points,
        "bedrooms_min": bedroom_points,
        "bedrooms_max": bedroom_points,
        "property_type": property_points,
    }
    minimum_points = {
        "locations": 20,
        "budget_min_aed": 15,
        "budget_max_aed": 15,
        "bedrooms_min": 10,
        "bedrooms_max": 10,
        "property_type": 10,
    }
    return any(checks.get(field, 1) < minimum_points.get(field, 1) for field in strict_fields)


def _json_snapshot(row: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value.isoformat() if isinstance(value, date | datetime) else value
        for key, value in row.items()
    }


def evaluate_requirements(criteria: dict[str, Any], facts: dict[str, Any]) -> dict:
    """Explain hard requirement support using the shared fit rules, without a second ranker.

    Every populated criterion is accounted for. Unknown constraints or candidate facts
    require review and cannot become a supported property shortlist.
    """
    from app.market.reference import area_search_text

    supported = {
        "locations",
        "building",
        "project",
        "unit_number",
        "property_type",
        "bedrooms_min",
        "bedrooms_max",
        "budget_min_aed",
        "budget_max_aed",
        "budget_min_inclusive",
        "budget_max_inclusive",
    }
    active = {key: value for key, value in criteria.items() if value not in (None, "", [])}
    unsupported = sorted(set(active) - supported)
    missing, outside = [], []

    def number(value):
        try:
            result = float(value)
            return result if math.isfinite(result) else None
        except (ValueError, TypeError):
            return None

    if _locations(criteria):
        observed = [facts.get(key) for key in ("location", "building", "project") if facts.get(key)]
        wanted = {area_search_text(value).casefold() for value in _locations(criteria)}
        if not observed:
            missing.append("locations")
        elif not wanted.intersection(area_search_text(value).casefold() for value in observed):
            outside.append("locations")
    for key in ("building", "project", "unit_number"):
        if key in active:
            if not facts.get(key):
                missing.append(key)
            elif str(facts[key]).strip().casefold() != str(active[key]).strip().casefold():
                outside.append(key)
    if "property_type" in active:
        if not facts.get("property_type"):
            missing.append("property_type")
        elif _property_fit(criteria, facts["property_type"]) < 10:
            outside.append("property_type")
    bedroom_fields = [key for key in ("bedrooms_min", "bedrooms_max") if key in active]
    if bedroom_fields:
        text = str(facts.get("bedrooms") or "").casefold()
        found = re.search(r"\d+", text)
        observed = int(found.group()) if found else 0 if "studio" in text else None
        for key in bedroom_fields:
            expected = number(active[key])
            if observed is None or expected is None:
                missing.append(key)
            elif (key == "bedrooms_min" and observed < expected) or (
                key == "bedrooms_max" and observed > expected
            ):
                outside.append(key)
    budget_fields = [key for key in ("budget_min_aed", "budget_max_aed") if key in active]
    if budget_fields:
        price = number(facts.get("price_aed"))
        if price is None or price <= 0:
            missing.extend(budget_fields)
        else:
            for key in budget_fields:
                bound = number(active[key])
                if bound is None:
                    missing.append(key)
                    continue
                inclusive = criteria.get(key.replace("_aed", "_inclusive"), True)
                if not isinstance(inclusive, bool):
                    missing.append(key.replace("_aed", "_inclusive"))
                elif (
                    key == "budget_min_aed"
                    and (price < bound or (price == bound and not inclusive))
                ) or (
                    key == "budget_max_aed"
                    and (price > bound or (price == bound and not inclusive))
                ):
                    outside.append(key)
    return {
        "status": "outside" if outside else "review" if missing or unsupported else "supported",
        "outside_requirements": sorted(outside),
        "unknown_requirements": sorted(missing),
        "unsupported_requirements": unsupported,
    }
