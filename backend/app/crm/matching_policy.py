from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

from app.crm.inbound_policy import _locations


def _location_fit(criteria: dict[str, Any], *values: str) -> tuple[int, str]:
    requested = _locations(criteria)
    if not requested:
        return 0, "Preferred location is missing"
    haystack = " ".join(values).casefold()
    if any(item.casefold() in haystack or haystack in item.casefold() for item in requested):
        return 20, f"Matches {requested[0]}"
    return 0, "Outside preferred location"


def _budget_fit(criteria: dict[str, Any], value: int | None) -> tuple[int, str]:
    maximum = int(criteria.get("budget_max_aed") or 0)
    minimum = int(criteria.get("budget_min_aed") or 0)
    if not maximum and not minimum:
        return 0, "Budget is missing"
    if not value:
        return 5, "Price requires verification"
    if (not minimum or value >= minimum) and (not maximum or value <= maximum):
        return 15, "Within stated budget"
    if maximum and value <= maximum * 1.1 and value >= minimum * 0.9:
        return 9, "Within flexible budget margin"
    return 0, "Outside budget"


# Portal listings: the buyer's budget is a band, not a ceiling (matching call, 26 Oct).
# Anything outside it is not shown; inside it, closer prices earn more of the 25 points.
LISTING_BUDGET_BELOW = 0.30
LISTING_BUDGET_ABOVE = 0.20
LISTING_BUDGET_POINTS = 25


def _listing_budget_band(criteria: dict[str, Any]) -> tuple[int, int] | None:
    maximum = int(criteria.get("budget_max_aed") or 0)
    minimum = int(criteria.get("budget_min_aed") or 0)
    if not maximum and not minimum:
        return None
    low = minimum or maximum
    high = maximum or minimum
    return round(low * (1 - LISTING_BUDGET_BELOW)), round(high * (1 + LISTING_BUDGET_ABOVE))


def _listing_budget_fit(criteria: dict[str, Any], value: int | None) -> tuple[int, str] | None:
    """Budget points for a listing, or None when its price is outside the budget band."""
    band = _listing_budget_band(criteria)
    if band is None:
        return 0, "Budget is missing"
    if not value:
        return 5, "Price requires verification"
    if not band[0] <= value <= band[1]:
        return None
    low = int(criteria.get("budget_min_aed") or 0) or int(criteria.get("budget_max_aed"))
    high = int(criteria.get("budget_max_aed") or 0) or low
    if value < low:
        gap = (low - value) / (low * LISTING_BUDGET_BELOW)
        percent, side = round((low - value) / low * 100), "below"
    elif value > high:
        gap = (value - high) / (high * LISTING_BUDGET_ABOVE)
        percent, side = round((value - high) / high * 100), "over"
    else:
        return LISTING_BUDGET_POINTS, "Within stated budget"
    reason = f"{percent}% {side} budget" if percent else "Within 1% of budget"
    return round(LISTING_BUDGET_POINTS * (1 - gap)), reason


def _listing_type_matches(criteria: dict[str, Any], value: str) -> bool:
    """A requested property type is a hard rule for listings: other or unknown types are out."""
    requested = _canonical_property_type(criteria.get("property_type"))
    return not requested or requested == _canonical_property_type(value)


def _listing_bedrooms(criteria: dict[str, Any]) -> list[str] | None:
    """The listing bedroom values to search: listings say "studio", "1"…"7" and "7+"."""
    requested = criteria.get("bedrooms_min")
    if requested is None:
        return None
    beds = int(requested)
    if beds == 0:
        return ["studio"]
    if beds >= 7 and criteria.get("bedrooms_max") is None:
        return ["7", "7+"]
    return [str(beds)]


def _bedroom_fit(criteria: dict[str, Any], value: str) -> tuple[int, str]:
    requested = criteria.get("bedrooms_min")
    if requested is None:
        return 0, "Bedroom requirement is missing"
    match = re.search(r"\d+", value)
    observed = int(match.group()) if match else 0 if "studio" in value.lower() else None
    if observed == int(requested):
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
    """The type name the listing search matches exactly: a synonym maps to its portal name,
    and a portal name chosen in the Wants dropdown passes through as written."""
    raw = str(value or "").strip()
    normalized = _canonical_property_type(raw)
    if not normalized:
        return None
    return raw if normalized == raw.casefold() and raw != raw.casefold() else normalized.title()


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
    return any(checks.get(field, 1) == 0 for field in strict_fields)


def _json_snapshot(row: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value.isoformat() if isinstance(value, date | datetime) else value
        for key, value in row.items()
    }
