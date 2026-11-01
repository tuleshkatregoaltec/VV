"""Pure, conservative owner-import number and market-location normalization."""

from __future__ import annotations

import re
import unicodedata
from decimal import Decimal, InvalidOperation
from typing import Any

from app.market.reference import (
    AREA_ALIASES,
    COMMUNITY_KEYS,
    area_search_text,
    community_location,
    location_key,
    property_name_lookup_key,
)

NORMALIZATION_VERSION = "owner-import-v2"
_NUMBER = re.compile(
    r"[+-]?(?:[0-9]+|[0-9]{1,3}(?:,[0-9]{3})+|[0-9]{1,3}(?: +[0-9]{3})+)(?:\.[0-9]+)?\Z"
)
_COMMUNITY_ALIASES = {
    alias: canonical for canonical, aliases in COMMUNITY_KEYS.items() for alias in aliases
}


def parse_decimal(value: Any) -> Decimal | None:
    """Read an entire finite number, never concatenate digits from arbitrary text.

    AED may prefix or suffix a number. Group separators must be consistent and
    have groups of three; decimal points always mean fractions, never grouping.
    Signs remain signs. Identifiers and phone numbers must not use this parser.
    """
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float, Decimal)):
        try:
            result = Decimal(str(value))
        except InvalidOperation:
            return None
        return result if result.is_finite() else None
    if not isinstance(value, str):
        return None
    text = "".join(
        str(unicodedata.decimal(char)) if char.isdecimal() else " " if char.isspace() else char
        for char in value
    ).strip()
    text = re.sub(r"^(?:AED)\s*|\s*(?:AED)$", "", text, count=1, flags=re.IGNORECASE).strip()
    if not _NUMBER.fullmatch(text):
        return None
    try:
        return Decimal(text.replace(",", "").replace(" ", ""))
    except InvalidOperation:
        return None


def positive_decimal(value: Any) -> Decimal | None:
    """Return a usable positive amount/size without rounding its precision."""
    result = parse_decimal(value)
    return result if result is not None and result > 0 else None


def normalize_location(value: Any, *, area: bool = False) -> str:
    """Use market display rules and exact area aliases; retain building qualifiers.

    The shared search helper also supports substring search. Imports deliberately
    call it only for explicit area aliases, so e.g. 'JVC Tower 2' stays a building.
    """
    text = location_key(str(value)) if value is not None else ""
    if area:
        if text in AREA_ALIASES:
            text = location_key(area_search_text(text))
        text = _COMMUNITY_ALIASES.get(text, text)
    return text


def location_evidence(area: str, project: str, building: str) -> dict[str, Any]:
    """Comparison evidence only; never a replacement for persisted property keys."""
    canonical_area = normalize_location(area, area=True)
    project_text, building_text = normalize_location(project), normalize_location(building)
    return {
        "version": NORMALIZATION_VERSION,
        "area": canonical_area,
        "community_keys": list(community_location(canonical_area).communities)
        if canonical_area in COMMUNITY_KEYS
        else [canonical_area]
        if canonical_area
        else [],
        "project": project_text,
        "project_lookup_key": property_name_lookup_key(project_text),
        "building": building_text,
        "building_lookup_key": property_name_lookup_key(building_text),
    }
