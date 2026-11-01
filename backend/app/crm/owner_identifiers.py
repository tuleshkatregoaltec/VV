"""One unit key and one identifier extractor for owner-sheet rows."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal, Mapping

from app.crm.owner_namespaces import parse_r3
from app.crm.transaction_matching import _MISSING

_SPREADSHEET_ERRORS = {"#n/a", "#value!"}
_PREFIX = re.compile(
    r"^((UNIT|FLAT|APT|APARTMENT|APPARTMENT)(\s*NO)?\s*[.:#-]?|(DH2|DL)\s*[- ])\s*"
)
_LEADING_ZEROS = re.compile(r"(^|[^0-9])0+([0-9])")
# "1", "01", "VILLA NO. 1", "UNIT-01", "B1": a one- or two-digit number, with at most a word and
# one letter around it. Every villa community has a "Villa 1", so it names no property.
_ORDINAL = re.compile(
    r"(?:(?:villa|unit|flat|apt|apartment|house|townhouse|th|plot)\s*[.:#-]?\s*)?"
    r"(?:(?:no|number)\s*[.:#-]?\s*)?#?[a-z]?\s*[.-]?\s*0*[0-9]{1,2}",
    re.I,
)
# (column, kind). A namespaced villa code is "villa" whichever column holds it.
_COLUMNS: tuple[tuple[str, Literal["unit", "plot", "property"]], ...] = (
    ("unit_number", "unit"),
    ("building_number", "property"),
    ("plot_number", "plot"),
    ("property_number", "property"),
    ("building_name", "property"),
)
# With a unit number, these columns name the parent building or plot, not the unit.
_PARENT_COLUMNS = {"building_number", "plot_number"}


def unit_key(value: str) -> str:
    """A unit number as DXBI and DLD both write it (Python port of the ClickHouse
    ``unit_key`` in ``holocron/market/analytics_hierarchy.py``).

    A share of a unit ("2510 (Q 3)") is that unit; "FLAT 415", "Unit No. 415" and "415" are one,
    as are "A-101", "A 101" and "A101", and "0103" and "103". Damac's estate prefixes are
    dropped: a Damac Hills 2 villa "DH2-XR1139B" on a sale is "XR1139B" on a lease, and a Damac
    Lagoons "DL-K138" is "K138". Leading zeros go from each digit run, never the code itself.
    """
    text = re.sub(r"\s*\([^)]*\)\s*$", "", value.strip().upper())
    text = re.sub(r"[^A-Z0-9]", "", _PREFIX.sub("", text))
    return _LEADING_ZEROS.sub(r"\1\2", text)


def is_ordinal_label(value: str) -> bool:
    """Is this unit label only an ordinal ("Villa No. 1", "01", "B1")?

    A label like that repeats in every cluster of a community, so on its own it cannot identify a
    property. Three-digit apartment numbers (101, 1410) and plot codes (AFWETH017) are not ordinal.
    """
    return bool(_ORDINAL.fullmatch(str(value).strip()))


def event_unit_keys(value: str) -> tuple[str, ...]:
    """Every key a DXBI / Transactions unit number is findable under.

    A namespaced villa code ("R3 Sun-V-259") is the whole key ``R3SUNV259`` and also the villa
    number ``259``, which is what a sheet key looks like once its namespace is read off.
    """
    full = unit_key(value)
    if not full:
        return ()
    villa = parse_r3(value)
    return (full, villa[1]) if villa else (full,)


@dataclass(frozen=True)
class SourceIdentifier:
    kind: Literal["unit", "villa", "plot", "property"]
    raw: str
    key: str
    namespace: str  # "" when the code carries no community namespace
    # Only an ordinal ("Villa No. 1"): usable inside a named building, never across a community.
    ordinal: bool = field(default=False, compare=False)
    column: str = field(default="", compare=False)  # the sheet column it was read from


def _text(value: Any) -> str:
    """The cell as text, or "" for blanks: 0, null, #REF! and spreadsheet float artefacts."""
    if value is None:
        return ""
    text = str(value).strip()
    text = text[:-2] if re.fullmatch(r"\d+\.0", text) else text
    return "" if text.casefold() in _MISSING | _SPREADSHEET_ERRORS else text


def source_identifiers(fields: Mapping[str, Any]) -> list[SourceIdentifier]:
    """Every property identifier a source row carries, with the unit key to match on.

    A full plot code ("AFMU019B") is one whole key, never cut to "19B". With a unit number,
    the plot and building columns are parent references and are dropped, unless they hold a
    namespaced villa code ("R3 Ruba-V-357"). A namespaced code suppresses a bare identifier
    with the same key.
    """
    has_unit = bool(_text(fields.get("unit_number")))
    found: list[SourceIdentifier] = []
    for column, kind in _COLUMNS:
        raw = _text(fields.get(column))
        if not raw:
            continue
        if villa := parse_r3(raw):
            found.append(SourceIdentifier("villa", raw, villa[1], villa[0], column=column))
        elif column == "building_name" and not raw.isdigit():
            continue
        elif not (has_unit and column in _PARENT_COLUMNS):
            ordinal = kind != "plot" and is_ordinal_label(raw)
            found.append(SourceIdentifier(kind, raw, unit_key(raw), "", ordinal, column))
    claimed = {i.key for i in found if i.namespace}
    return [i for i in found if i.namespace or i.key not in claimed]
