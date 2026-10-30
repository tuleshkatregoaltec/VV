"""Identifier and property-kind keys shared by the matchers; a leaf module with no CRM imports."""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Any

from app.market.reference import property_name_lookup_key

_MISSING = {"", "0", "null", "none", "n/a", "na", "-", "unknown", "#ref!"}


@lru_cache(maxsize=100_000)
def identifier(value: str) -> str:
    """Retain full code namespaces and separators; normalize numeric padding only."""
    text = re.sub(r"\s+", "", value.casefold()).replace("–", "-")
    if text in _MISSING:
        return ""
    if re.fullmatch(r"\d+\.0", text):
        text = text[:-2]
    return re.sub(r"\d+", lambda match: str(int(match.group())), text)


@lru_cache(maxsize=100_000)
def generic_building(value: str) -> bool:
    key = property_name_lookup_key(value)
    return bool(
        re.fullmatch(
            r"(?:tower|building|bldg|block)(?:no)?(?:[a-z]|[0-9]+|[a-z][0-9]+|[0-9]+[a-z]|[ivx]+)?",
            key,
        )
    )


def _kind(value: Any) -> str:
    text = str(value or "").casefold().strip()
    if text in {"apartment", "apartments", "flat", "flats", "office", "shop", "retail"}:
        return "flat"
    if text in {"villa", "villas", "townhouse", "townhouses"}:
        return "villa"
    if text in {"land", "plot", "plots"}:
        return "plot"
    return ""
