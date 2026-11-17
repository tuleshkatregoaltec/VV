"""Square-foot view of feasibility data for the workspace chat.

The workbook model and research store areas in m² and rates per m². The user sees square feet
everywhere, so the chat model is given every area and rate already in square feet (it never
converts) and proposes changes in square feet; proposals are converted back to the workbook's
square-metre fields before they reach the frontend.

Key naming in the workbook and research payloads:
- rates per m²: camelCase ``...Psqm...`` (sellingRatePsqm, constructionCostPsqmBua), ``...psm...``
  (median_rent_psm_annual) and snake_case ``*_sqm`` keys that name a price, rent or cost
  (median_price_sqm, price_per_gfa_sqm, avg_rent_price_sqm_12m);
- areas in m²: every other ``...Sqm`` / ``*_sqm`` key (avgSizeSqm, plot_area_sqm, maxGfaSqm).
"""

import re
from typing import Any

from app.market.units import SQM_TO_SQFT

_RATE_WORDS = {"price", "prices", "rent", "rents", "cost", "costs", "rate", "rates", "fee", "fees"}


def _is_rate(key: str) -> bool:
    """Whether a key names an amount per area (a word of it is price, rent, cost, rate or fee)."""
    words = re.findall(r"[a-z]+", re.sub(r"([A-Z])", r"_\1", key).lower())
    return any(word in _RATE_WORDS for word in words)


def _sqft_key(key: str) -> tuple[str, str] | None:
    """(new key, 'rate' | 'area') for a square-metre key, else None."""
    if "Psqm" in key:
        return key.replace("Psqm", "Psqft"), "rate"
    if re.search(r"(^|_)psm(_|$)", key):
        return re.sub(r"(^|_)psm(_|$)", r"\1psqft\2", key), "rate"
    if re.search(r"_sqm(_|$)", key):
        kind = "rate" if _is_rate(key) else "area"
        return re.sub(r"_sqm(_|$)", r"_sqft\1", key), kind
    if "Sqm" in key:
        kind = "rate" if _is_rate(key) else "area"
        return key.replace("Sqm", "Sqft"), kind
    return None


def _sqm_key(key: str) -> tuple[str, str] | None:
    """The inverse of ``_sqft_key``: (workbook key, 'rate' | 'area') for a square-foot key."""
    if "Psqft" in key:
        return key.replace("Psqft", "Psqm"), "rate"
    if re.search(r"(^|_)psqft(_|$)", key):
        return re.sub(r"(^|_)psqft(_|$)", r"\1psm\2", key), "rate"
    if re.search(r"_sqft(_|$)", key):
        kind = "rate" if _is_rate(key) else "area"
        return re.sub(r"_sqft(_|$)", r"_sqm\1", key), kind
    if "Sqft" in key:
        kind = "rate" if _is_rate(key) else "area"
        return key.replace("Sqft", "Sqm"), kind
    return None


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def to_sqft_view(value: Any) -> Any:
    """A copy with every m² area and per-m² rate renamed and converted to square feet."""
    if isinstance(value, list):
        return [to_sqft_view(item) for item in value]
    if not isinstance(value, dict):
        return value
    result: dict[str, Any] = {}
    for key, item in value.items():
        converted = _sqft_key(key) if isinstance(key, str) else None
        if converted and (_is_number(item) or item is None):
            new_key, kind = converted
            if item is None:
                result[new_key] = None
            else:
                result[new_key] = round(
                    item * SQM_TO_SQFT if kind == "area" else item / SQM_TO_SQFT, 2
                )
        else:
            result[key] = to_sqft_view(item)
    return result


def to_workbook_units(value: Any) -> Any:
    """A copy with square-foot keys proposed by the chat converted back to the workbook's m²."""
    if isinstance(value, list):
        return [to_workbook_units(item) for item in value]
    if not isinstance(value, dict):
        return value
    result: dict[str, Any] = {}
    for key, item in value.items():
        converted = _sqm_key(key) if isinstance(key, str) else None
        if converted and _is_number(item):
            new_key, kind = converted
            result[new_key] = item / SQM_TO_SQFT if kind == "area" else item * SQM_TO_SQFT
        else:
            result[key] = to_workbook_units(item)
    return result


def price_per_sqm(price_per_sqft: float) -> float:
    return price_per_sqft * SQM_TO_SQFT
