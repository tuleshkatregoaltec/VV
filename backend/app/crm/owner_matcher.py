"""Property-first owner matcher: the unit first, then its sale within 2 AED, then Transactions.

Pure functions over a ``SalesIndex`` the caller builds from DXBI events and Transactions
(``market_sale_events``) rows; nothing here reads a database. Dates never select, rank or veto a
match: the source date only breaks a tie between two sales of the same property at the same
amount. Property-type labels never decide either; a difference is only a warning.
"""

from __future__ import annotations

import math
import re
from bisect import bisect_left, bisect_right
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Literal, NamedTuple

from app.crm.owner_identifiers import (
    SourceIdentifier,
    event_unit_keys,
    is_ordinal_label,
    source_identifiers,
    unit_key,
)
from app.crm.owner_matching_policy import SQM_TO_SQFT
from app.crm.owner_namespaces import parse_r3
from app.crm.owner_places import Place, PlaceIndex, clean_label, place_key

MATCHER_VERSION = "property-first-2"

Outcome = Literal[
    "matched_sale",
    "matched_sale_inferred_unit",
    "matched_registry_sale",
    "matched_registry_sale_no_unit",
    "matched_sale_via_mortgage",
    "matched_sale_review",
    "property_confirmed_no_sale",
    "rejected",
    "no_evidence",
]

AMOUNT_TOLERANCE = Decimal("2")
_SIZE_FLOOR = Decimal("50")
_SIZE_FRACTION = Decimal("0.02")
_SHARE_ROUNDING = Decimal("1")  # sqft; DXBI rounds sizes to whole feet
_SHARE_DIVISORS = (2, 4)
MAX_REJECTED = 10
_FINANCING = re.compile(r"mortgage|lease finance|lease to own|modify", re.I)
_LAND = re.compile(r"land|plot", re.I)
_PLAUSIBLE_PLOT_RATIO = (Decimal("0.7"), Decimal("2.5"))  # sheet plot area / DXBI built-up area
MAX_ELIMINATED = 3
_NUMBER_COLUMNS = ("unit_number", "property_number", "building_number")
_PLACE_COLUMNS = ("building_name", "project_name", "master_project", "area_name")
_REJECTED_FIELDS = ("unit_number", "building_name", "project_name", "area_name", "event_date")


@dataclass
class MatchResult:
    outcome: Outcome
    property_key: tuple[str, str] | None = None
    sale: Mapping[str, Any] | None = None
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    rejected: list[dict[str, Any]] = field(default_factory=list)


class _Entry(NamedTuple):
    row: Mapping[str, Any]
    place: Place
    amount: Decimal
    sqft: Decimal | None
    key: str  # unit_key of the row's unit number, "" when it has none
    keys: tuple[str, ...] = ()  # every key the unit is findable under (a villa code has two)
    generic: bool = False  # the unit label is only an ordinal, outside any named building


def _decimal(value: Any) -> Decimal | None:
    try:
        number = Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, ValueError):
        return None
    return number if number.is_finite() and number > 0 else None


def _scoped(place: Place) -> bool:
    """Does the place name a building or a project inside its community? A bare "Villa No. 1"
    identifies a villa only there; across a whole community there is one in every cluster."""
    return bool(place.buildings) or bool(place.project and place.project != place.community)


def _entries(
    rows: Iterable[Mapping[str, Any]],
    place_of: Any,
    amount_of: str,
    sqft_of: Any,
    unit_of: str = "unit_number",
) -> list[_Entry]:
    entries = []
    for row in rows:
        amount = _decimal(row.get(amount_of))
        if amount is not None:
            label, place = str(row.get(unit_of) or ""), place_of(row)
            keys = event_unit_keys(label)
            # "Villa No. 1" in a community-level place is one of many: it names no property
            generic = bool(keys) and is_ordinal_label(label) and not _scoped(place)
            keys = () if generic else keys
            entries.append(
                _Entry(row, place, amount, sqft_of(row), keys[0] if keys else "", keys, generic)
            )
    return sorted(entries, key=lambda entry: entry.amount)


def _near(entries: list[_Entry], amount: Decimal) -> list[_Entry]:
    low = bisect_left(entries, amount - AMOUNT_TOLERANCE, key=lambda entry: entry.amount)
    high = bisect_right(entries, amount + AMOUNT_TOLERANCE, key=lambda entry: entry.amount)
    return entries[low:high]


class SalesIndex:
    """DXBI events (sales and rentals) plus Transactions rows, keyed for the matcher.

    ``events`` are DXBI dicts: ``family``, ``amount``, ``event_date`` and the payload keys.
    ``registry_sales`` are ``market_sale_events`` dicts (DXBI + DLD, ``procedure_area`` in sqm);
    financing procedures are dropped on the way in, so they can never be a sale.
    """

    def __init__(
        self,
        events: Iterable[Mapping[str, Any]],
        places: PlaceIndex,
        registry_sales: Iterable[Mapping[str, Any]] = (),
    ):
        self.places = places

        def event_sqft(row: Mapping[str, Any]) -> Decimal | None:
            return _decimal(row.get("size_sqft"))

        def registry_sqft(row: Mapping[str, Any]) -> Decimal | None:
            area = _decimal(row.get("procedure_area"))
            return area * SQM_TO_SQFT if area is not None else None

        dxbi = _entries(events, places.event_place, "amount", event_sqft)
        self._by_unit: dict[str, list[_Entry]] = defaultdict(list)
        for entry in dxbi:
            for key in entry.keys:
                self._by_unit[key].append(entry)
        self._sales = [entry for entry in dxbi if entry.row.get("family") == "sale"]
        sales = (
            row
            for row in registry_sales
            if not _FINANCING.search(str(row.get("procedure_name_en")))
        )
        self._registry = _entries(sales, places.event_place, "actual_worth", registry_sqft)
        self._places = {id(entry.row): entry.place for entry in dxbi}

    def place_of(self, event: Mapping[str, Any]) -> Place:
        return self._places[id(event)]

    def units(self, place: Place, key: str) -> list[Mapping[str, Any]]:
        """Every event (sale or rental) on this unit in this place."""
        return [e.row for e in self._by_unit.get(key, ()) if self.places.same_place(place, e.place)]

    def sales_at(self, place: Place, amount: Decimal) -> list[Mapping[str, Any]]:
        """Sales within 2 AED of ``amount`` anywhere in this place."""
        return [e.row for e in self._sales_near(place, amount)]

    def _sales_near(self, place: Place | None, amount: Decimal) -> list[_Entry]:
        near = _near(self._sales, amount)
        return [e for e in near if place is None or self.places.same_place(place, e.place)]

    def property_sales(self, key: tuple[str, str]) -> list[Mapping[str, Any]]:
        """Every DXBI sale of the property ``(place label, unit key)`` a match reported."""
        return [
            e.row
            for e in self._by_unit.get(key[1], ())
            if e.row.get("family") == "sale" and _where(e.place) == key[0]
        ]

    def registry_at(self, place: Place, amount: Decimal) -> list[_Entry]:
        near = _near(self._registry, amount)
        return [e for e in near if self.places.same_place(place, e.place)]


# --------------------------------------------------------------------------- sizes


def _source_sizes(source: Mapping[str, Any]) -> list[tuple[str, Decimal]]:
    """The sheet's size as (unit, sqft) candidates; a size of unknown unit is tried both ways."""
    sizes: list[tuple[str, Decimal]] = []
    for column, units in (
        ("size_sqft", ("sqft",)),
        ("size_sqm", ("sqm",)),
        ("size_unknown", ("sqft", "sqm")),
    ):
        value = _decimal(source.get(column))
        for unit in units if value is not None else ():
            sizes.append((unit, value * SQM_TO_SQFT if unit == "sqm" else value))
    return sizes


def _size_fit(sizes: list[tuple[str, Decimal]], sqft: Decimal | None) -> str | None:
    """The unit that fits (``"sqft"`` / ``"sqm"``), ``""`` for a conflict, ``None`` if unknown."""
    if not sizes or sqft is None:
        return None
    for unit, value in sizes:
        if abs(value - sqft) <= max(_SIZE_FLOOR, value * _SIZE_FRACTION):
            return unit
    return ""


# --------------------------------------------------------------------------- helpers


def _day(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _nearest(sales: list[Mapping[str, Any]], source_date: date | None) -> Mapping[str, Any]:
    """The sale nearest the source date. Only ever used among sales of one property."""

    def distance(sale: Mapping[str, Any]) -> tuple[int, str]:
        day = _day(sale.get("event_date"))
        gap = abs((day - source_date).days) if day and source_date else 0
        return gap, str(sale.get("event_key"))

    return min(sales, key=distance)


def _share_qualifier(unit: Any) -> str:
    """ "2807 (Q 2)" -> "Q2": the bracketed share of a fractional (quarter-share) unit."""
    found = re.search(r"\(([^)]*)\)", str(unit or ""))
    return re.sub(r"[^A-Z0-9]", "", found[1].upper()) if found else ""


def _label(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower())


def _type_warnings(source: Mapping[str, Any], sale_type: Any) -> list[str]:
    ours, theirs = _label(source.get("property_type")), _label(sale_type)
    if ours and theirs and ours != theirs:
        return [f"type_label_differs ({source.get('property_type')} vs {sale_type})"]
    return []


def _where(place: Place) -> str:
    return place.building or place.project or place.community


def _rejected(row: Mapping[str, Any], reason: str) -> dict[str, Any]:
    kept = {name: row.get(name) for name in _REJECTED_FIELDS}
    return {
        "reason": reason,
        "amount": row.get("amount"),
        "event_key": row.get("event_key"),
        **kept,
    }


def _same_price_elsewhere(
    index: SalesIndex,
    place: Place,
    amount: Decimal,
    sizes: list[tuple[str, Decimal]],
    own: set[str],
) -> list[dict[str, Any]]:
    """Same-price sales that are not this property, for the report. Never matches."""
    community = Place(place.community, "", "", place.community_labels)
    in_place, in_community, elsewhere = [], [], []
    for entry in index._sales_near(None, amount):
        if own.intersection(entry.keys):
            continue
        if index.places.same_place(place, entry.place):
            in_place.append(_rejected(entry.row, "different_unit_same_price"))
        elif index.places.same_place(community, entry.place):
            in_community.append(_rejected(entry.row, "different_unit_same_price"))
        elif _size_fit(sizes, entry.sqft):
            elsewhere.append(_rejected(entry.row, "different_community"))
    return (in_place + in_community + elsewhere)[:MAX_REJECTED]


# --------------------------------------------------------------------------- DXBI pass


def _unit_properties(
    index: SalesIndex, place: Place, identifiers: list[SourceIdentifier]
) -> dict[tuple[str, str], list[Mapping[str, Any]]]:
    properties: dict[tuple[str, str], dict[int, Mapping[str, Any]]] = {}
    for identifier in identifiers:
        for event in index.units(place, identifier.key):
            found = index.place_of(event)
            if identifier.namespace and identifier.namespace not in (
                found.names | {found.building, found.project}
            ):
                continue
            properties.setdefault((_where(found), identifier.key), {})[id(event)] = event
    return {key: list(events.values()) for key, events in properties.items()}


def _plausible_plot_ratio(
    source: Mapping[str, Any], sizes: list[tuple[str, Decimal]], sqft: Decimal | None
) -> bool:
    """A Land / Plot row quotes the plot, DXBI the built-up area: within 0.7x-2.5x is plausible."""
    if not sizes or not sqft or not _LAND.search(str(source.get("property_type") or "")):
        return False
    # DLD sizes are square metres: a size of unknown unit is judged as sqm, not as sqft
    readings = [value for unit, value in sizes if unit == "sqm"] or [v for _, v in sizes]
    ratio = min((value / sqft for value in readings), key=lambda r: abs(math.log(float(r))))
    return _PLAUSIBLE_PLOT_RATIO[0] <= ratio <= _PLAUSIBLE_PLOT_RATIO[1]


def _sale_verdict(
    sale: Mapping[str, Any], sizes: list[tuple[str, Decimal]], unit_sizes: list[Decimal]
) -> str | None:
    """``"fits"``, ``"share"``, ``"conflict"``, or None when a size is unknown."""
    sqft = _decimal(sale.get("size_sqft"))
    fit = _size_fit(sizes, sqft)
    if fit is None or sqft is None:
        return None
    if fit:
        return "fits"
    for whole in unit_sizes:
        if _size_fit(sizes, whole) and any(
            abs(sqft * divisor - whole) <= _SHARE_ROUNDING for divisor in _SHARE_DIVISORS
        ):
            return "share"
    return "conflict"


def _match_unit(
    source: Mapping[str, Any],
    index: SalesIndex,
    place: Place,
    identifiers: list[SourceIdentifier],
    amount: Decimal,
    sizes: list[tuple[str, Decimal]],
) -> MatchResult:
    properties = _unit_properties(index, place, identifiers)
    if place.buildings:  # a sheet that names a building needs a unit that names it too
        properties = {k: v for k, v in properties.items() if index.place_of(v[0]).buildings}
    reasons: list[str] = []
    if len(properties) > 1:  # the one property with a sale at this amount
        priced = {k: v for k, v in properties.items() if any(_is_sale_at(e, amount) for e in v)}
        properties = priced if len(priced) == 1 else properties
    if not properties:
        rejected = _same_price_elsewhere(index, place, amount, sizes, set())
        return MatchResult("no_evidence", None, None, ["unit_not_in_dxbi"], [], rejected)
    if len(properties) > 1:
        reasons = ["ambiguous_unit", f"{len(properties)} properties: {sorted(properties)}"]
        return MatchResult("no_evidence", None, None, reasons)

    ((key, events),) = properties.items()
    unit_sizes = [s for s in (_decimal(e.get("size_sqft")) for e in events) if s is not None]
    sales = {str(e.get("event_key")): e for e in events if _is_sale_at(e, amount)}.values()
    verdicts = {id(s): _sale_verdict(s, sizes, unit_sizes) for s in sales}
    # An identified unit that sold at this price is the match; plot area against built-up area
    # (or any other size basis) is a warning there, never a rejection.
    usable = [s for s in sales if verdicts[id(s)] != "conflict"] or list(sales)
    conflict = (
        not sales and sizes and unit_sizes and not any(_size_fit(sizes, s) for s in unit_sizes)
    )
    if conflict:
        sizes_text = " / ".join(f"{size:,.0f}" for size in sorted(set(unit_sizes)))
        reasons = ["size_conflict", f"unit {key[1]} is {sizes_text} sqft"]
        if len({i.key for i in identifiers if i.kind != "plot"}) > 1:
            # The sheet names several units, so this one is only a guess: let Transactions try.
            return MatchResult("no_evidence", None, None, reasons)
        return MatchResult("rejected", key, None, reasons)
    if not usable:
        reasons = [f"unit {key[1]} exists in DXBI but has no sale within 2 AED"]
        rejected = _same_price_elsewhere(index, place, amount, sizes, {key[1]})
        return MatchResult("property_confirmed_no_sale", key, None, reasons, [], rejected)

    share = _share_qualifier(source.get("unit_number"))
    same_share = [s for s in usable if _share_qualifier(s.get("unit_number")) == share]
    share_differs = bool(share) and not same_share
    usable = same_share or usable  # "2807 (Q 2)" is its own title: prefer that share's sale
    sale = _nearest(usable, _day(source.get("transaction_date")))
    warnings = _type_warnings(source, sale.get("property_type"))
    if share_differs:
        warnings.append(f"share_qualifier_differs: DXBI sold {sale.get('unit_number')}")
    if len(usable) > 1:
        warnings.append("repeat_price")
    if verdicts[id(sale)] == "share":
        warnings.append("share_sale")
    elif verdicts[id(sale)] == "conflict":
        warnings.append("size_basis_differs")
    outcome: Outcome = "matched_sale"
    if verdicts[id(sale)] == "conflict" and not _plausible_plot_ratio(
        source, sizes, _decimal(sale.get("size_sqft"))
    ):
        outcome = "matched_sale_review"  # another size basis is only believed for a plot
    if share_differs:
        outcome = "matched_sale_review"  # another share of the unit sold at this price
    if len({i.key for i in identifiers if i.namespace}) > 1:
        outcome = "matched_sale_review"
        warnings.append("sheet_names_two_villas: matched the one with a sale at this amount")
    elif (codes := _unit_numbers(source, identifiers)) - {key[1]} and key[1] in codes:
        # unit_number and property_number disagree; a plot code beside a label is no second unit
        if any(i.column == "building_name" and i.key == key[1] for i in identifiers):
            # AR3 writes two villa numberings: BuildingNameEn is 1-5 above "R3 X-V-n". Where they
            # differ, DXBI has the sale on the name-column villa in 3,480 of 3,514 rows (snapshot,
            # 2026-10-29), and only that villa sold at this price here, so it is the match.
            warnings.append(f"buildingno_renumbered {sorted(codes)}: matched the name column")
        else:
            outcome = "matched_sale_review"
            warnings.append(f"sheet_names_two_units {sorted(codes)}: matched {key[1]}")
    return MatchResult(outcome, key, sale, [f"unit {key[1]} in {key[0]}"], warnings)


def _unit_numbers(source: Mapping[str, Any], identifiers: list[SourceIdentifier]) -> set[str]:
    """The unit numbers the sheet writes in its unit / property / building number columns.

    A label that only repeats a building / project name ("Rove City Walk" in BuildingNo) is a
    place, not a second unit. A building name that is itself a villa number ("177" beside
    "R3 Sun-V-173", AR3) is a unit: source_identifiers only yields such names."""
    places = {_label(source.get(name)) for name in _PLACE_COLUMNS}
    return {
        i.key
        for i in identifiers
        if i.kind != "plot"
        and (
            (i.column in _NUMBER_COLUMNS and _label(i.raw) not in places)
            or i.column == "building_name"
        )
    }


def _is_sale_at(event: Mapping[str, Any], amount: Decimal) -> bool:
    value = _decimal(event.get("amount"))
    return (
        event.get("family") == "sale"
        and value is not None
        and abs(value - amount) <= AMOUNT_TOLERANCE
    )


def _match_inferred(
    source: Mapping[str, Any],
    index: SalesIndex,
    place: Place,
    amount: Decimal,
    sizes: list[tuple[str, Decimal]],
) -> MatchResult:
    """No identifier: the one property with a sale at this price and size in the place."""
    fitting: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for entry in index._sales_near(place, amount):
        sale = entry.row
        if _size_fit(sizes, _decimal(sale.get("size_sqft"))):
            # sales of a generic "Villa No. 1" are different villas, not repeat sales of one
            unit = (
                str(sale.get("event_key"))
                if entry.generic
                else unit_key(str(sale.get("unit_number") or ""))
            )
            fitting[(_where(entry.place), unit)].append(sale)
    if not fitting:
        return MatchResult("no_evidence", None, None, ["no_sale_at_price_and_size"])
    if len(fitting) > 1:
        rejected = [_rejected(s, "ambiguous_price_size") for v in fitting.values() for s in v]
        return MatchResult(
            "no_evidence", None, None, ["ambiguous_price_size"], [], rejected[:MAX_REJECTED]
        )
    ((key, sales),) = fitting.items()
    sale = _nearest(sales, _day(source.get("transaction_date")))
    fit = _size_fit(sizes, _decimal(sale.get("size_sqft")))
    warnings = _type_warnings(source, sale.get("property_type"))
    if len({s.get("event_key") for s in sales}) > 1:
        warnings.append("repeat_price")
    reasons = [f"only property with a sale at this price and size in the place; size read as {fit}"]
    return MatchResult("matched_sale_inferred_unit", key, sale, reasons, warnings)


# --------------------------------------------------------------------------- Transactions pass


def _match_registry(
    source: Mapping[str, Any],
    index: SalesIndex,
    place: Place,
    identifiers: list[SourceIdentifier],
    amount: Decimal,
    sizes: list[tuple[str, Decimal]],
    first: MatchResult,
) -> MatchResult:
    """Second pass over DXBI + DLD sales: price and size in the building the sheet names."""
    sheet_units = {i.key for i in identifiers}
    same, other = [], []
    for entry in index.registry_at(place, amount):
        if not _size_fit(sizes, entry.sqft):
            continue
        foreign = entry.keys and sheet_units and sheet_units.isdisjoint(entry.keys)
        (other if foreign else same).append(entry)
    codes = {i.key for i in identifiers if i.kind != "plot"}
    note = (
        f"Transactions: {len(same)} sale(s) fit place and size, {len(other)} belong to other units"
    )
    if len(same) == 1:
        row = same[0].row
        outcome: Outcome = (
            "matched_registry_sale" if identifiers else "matched_registry_sale_no_unit"
        )
        reasons = [note, f"{row.get('match_status')} {row.get('procedure_name_en')}"]
        if other:
            reasons.append(f"eliminated units {sorted({e.key for e in other})}")
        if doubts := _elimination_doubts(place, same[0], other, sheet_units):
            outcome = "matched_sale_review"
            reasons.append(f"elimination_unverified: {'; '.join(doubts)}")
        if len(codes) > 1:
            outcome = "matched_sale_review"
            reasons.append(f"sheet_names_two_units {sorted(codes)}: sale confirmed, unit is not")
        key = first.property_key or (
            (_where(place), next(iter(codes))) if len(codes) == 1 else None
        )
        warnings = _type_warnings(source, row.get("property_type_en"))
        return MatchResult(outcome, key, row, reasons, warnings, first.rejected)
    if not same and len(other) == 1 and identifiers:
        row = other[0].row
        reason = f"unit differs: Transactions says {other[0].key}, sheet says {sorted(sheet_units)}"
        warnings = _type_warnings(source, row.get("property_type_en"))
        return MatchResult(
            "matched_sale_review", first.property_key, row, [note, reason], warnings, first.rejected
        )
    suffix = ["ambiguous_registry_sale"] if len(same) > 1 else []
    return MatchResult(
        first.outcome,
        first.property_key,
        first.sale,
        [*first.reasons, note, *suffix],
        first.warnings,
        first.rejected,
    )


def _elimination_doubts(
    place: Place, candidate: _Entry, other: list[_Entry], sheet_units: set[str]
) -> list[str]:
    """Why a registry match that rests on eliminating other units is not trusted. Empty when the
    candidate was found by its own unit, or nothing was eliminated."""
    if not other or sheet_units.intersection(candidate.keys):
        return []
    doubts = []
    if not place.buildings:
        doubts.append("the sheet names no known building, only a community or project")
    if len({e.key for e in other}) > MAX_ELIMINATED:
        doubts.append(f"{len({e.key for e in other})} units eliminated (limit {MAX_ELIMINATED})")
    if str(candidate.row.get("procedure_name_en") or "").strip().casefold() == "grant":
        doubts.append("the registry procedure is a plain Grant")
    return doubts


def _place_fields(
    source: Mapping[str, Any], identifiers: list[SourceIdentifier]
) -> Mapping[str, Any]:
    """The sheet's location fields. A building name that is really a unit code ("357",
    "R3 Sun-V-122") is an identifier, not a building, so it stays out of the place."""
    name = str(source.get("building_name") or "").strip()
    is_code = name.isdigit() or parse_r3(name) or any(i.raw == name for i in identifiers)
    if name and is_code:
        return {**source, "building_name": None}
    return source


def source_place(source: Mapping[str, Any], places: PlaceIndex) -> Place | None:
    """The place a sheet row names, as ``match_row`` reads it (None when it names none)."""
    return places.source_place(_place_fields(source, source_identifiers(source)))


def match_row(source: Mapping[str, Any], index: SalesIndex) -> MatchResult:
    """Match one owner-sheet row (canonical field names) to the sale that transferred it."""
    amount = _decimal(source.get("transaction_price_aed"))
    identifiers = source_identifiers(source)
    place = index.places.source_place(_place_fields(source, identifiers))
    if amount is None:
        return MatchResult("no_evidence", reasons=["no_amount"])
    if place is None:
        return MatchResult(
            "no_evidence", reasons=["no_place" if identifiers else "no_place_no_identifier"]
        )
    sizes = _source_sizes(source)
    # A bare "Villa No. 1" identifies nothing across a community; the plot code beside it does
    identifiers = [i for i in identifiers if not (i.ordinal and not _scoped(place))]
    if identifiers:
        result = _match_unit(source, index, place, identifiers, amount, sizes)
    else:
        result = _match_inferred(source, index, place, amount, sizes)
    if result.outcome in ("no_evidence", "property_confirmed_no_sale"):
        result = _match_registry(source, index, place, identifiers, amount, sizes, result)
    if _FINANCING.search(str(source.get("procedure_type"))):
        result = _financing_row(result, source, index)
    return result


def _financing_row(
    result: MatchResult, source: Mapping[str, Any], index: SalesIndex
) -> MatchResult:
    """A sheet row whose own procedure is financing (mortgage, lease to own...) can confirm the
    property but is never the sale: its amount is not a sale price.

    One exception: a mortgage is usually registered the day the unit was bought. When the property
    was found and DXBI has exactly one sale of that unit on the sheet's own date, that sale is the
    owner's purchase (DLD's Seller on a mortgage row is the mortgagor)."""
    if (day := _day(source.get("transaction_date"))) and result.property_key is not None:
        if result.outcome not in ("rejected", "no_evidence", "matched_sale_review"):
            same_day = {
                str(sale.get("event_key")): sale
                for sale in index.property_sales(result.property_key)
                if _day(sale.get("event_date")) == day
            }
            if len(same_day) == 1:
                (sale,) = same_day.values()
                reasons = ["financing_row", f"unit {result.property_key[1]} sold on {day}"]
                warnings = _type_warnings(source, sale.get("property_type"))
                return MatchResult(
                    "matched_sale_via_mortgage",
                    result.property_key,
                    sale,
                    reasons,
                    warnings,
                    result.rejected,
                )
    if result.sale is None:
        return result
    reasons = ["financing_row", *result.reasons]
    if result.property_key is None:
        return MatchResult("no_evidence", None, None, reasons, [], result.rejected)
    return MatchResult(
        "property_confirmed_no_sale", result.property_key, None, reasons, [], result.rejected
    )


# --------------------------------------------------------------------------- after matching


def later_sale_date(index: SalesIndex, result: MatchResult) -> str | None:
    """The date of the latest DXBI sale of the matched unit after the matched sale, if any.

    Rentals never count, and neither does a sale on the matched sale's own day. A Transactions
    sale that carries no unit number is looked up under the property the match reported; with
    neither there is nothing to check (``matched_registry_sale_no_unit``)."""
    sale = result.sale
    if sale is None:
        return None
    sold = _day(sale.get("event_date") or sale.get("instance_date"))
    if sold is None:
        return None
    keys = event_unit_keys(str(sale.get("unit_number") or ""))
    if "family" in sale:  # a DXBI event: its own building and unit
        where = _where(index.place_of(sale))
        sales = [e.row for k in keys for e in index._by_unit.get(k, ()) if _where(e.place) == where]
    elif keys:  # a Transactions row with a unit number
        place = index.places.event_place(sale)
        sales = [
            e.row
            for k in keys
            for e in index._by_unit.get(k, ())
            if index.places.same_place(place, e.place)
        ]
    elif result.property_key is not None:
        sales = index.property_sales(result.property_key)
    else:
        return None
    later = [
        day
        for other in sales
        if other.get("family") == "sale" and (day := _day(other.get("event_date"))) and day > sold
    ]
    return max(later).isoformat() if later else None


def _sale_identity(sale: Mapping[str, Any]) -> str:
    return str(
        sale.get("event_key")
        or sale.get("dxbi_sale_key")
        or sale.get("transaction_id")
        or f"{sale.get('amount') or sale.get('actual_worth')}:"
        f"{sale.get('event_date') or sale.get('instance_date')}"
    )


def sheet_unit(source: Mapping[str, Any]) -> tuple[str, tuple[str, ...]]:
    """(the sheet's place label, its identifier keys): what a sheet means by "unit 102 here"."""
    identifiers = source_identifiers(source)
    fields = _place_fields(source, identifiers)
    label = next(
        (
            place_key(clean_label(fields.get(name)))
            for name in ("building_name", "project_name", "master_project", "area_name")
            if clean_label(fields.get(name))
        ),
        "",
    )
    return label, tuple(sorted({i.key for i in identifiers}))


def _dxbi_unit(sale: Mapping[str, Any]) -> tuple[str, str] | None:
    """(building label, unit key) of the sale a result points to; None when it has no unit."""
    key = unit_key(str(sale.get("unit_number") or ""))
    building = sale.get("building_name") or sale.get("building_name_en")
    return (place_key(clean_label(building)), key) if key else None


def promote_learned_aliases(
    pairs: Sequence[tuple[Mapping[str, Any], MatchResult]],
) -> list[MatchResult]:
    """Learn the sheet's own unit numbering from the import it appears in.

    A "unit differs" review row is a sale at the sheet's price and size in the sheet's building,
    under another unit number. When every such row of one (sheet place, sheet unit) points to the
    same single DXBI unit, on at least two different sales, and no other sheet unit in the import
    points to that DXBI unit, the sheet simply numbers that unit differently: the rows become
    ``matched_sale`` with the warning ``learned_unit_alias``. One sale is one piece of evidence
    (a buyer row and a seller row), so a single-sale alias stays in review."""
    targets: dict[tuple[str, tuple[str, ...]], set[tuple[str, str]]] = defaultdict(set)
    pointing: dict[tuple[str, str], set[tuple[str, tuple[str, ...]]]] = defaultdict(set)
    differs: dict[tuple[str, tuple[str, ...]], list[int]] = defaultdict(list)
    groups = []
    for position, (source, result) in enumerate(pairs):
        group = sheet_unit(source)
        groups.append(group)
        unit = _dxbi_unit(result.sale) if result.sale else None
        if unit is not None:
            targets[group].add(unit)
            pointing[unit].add(group)
        if result.outcome == "matched_sale_review" and any(
            reason.startswith("unit differs") for reason in result.reasons
        ):
            differs[group].append(position)
    promoted = [result for _, result in pairs]
    for group, positions in differs.items():
        (unit,) = targets[group] if len(targets[group]) == 1 else (None,)
        sales = {_sale_identity(promoted[p].sale) for p in positions if promoted[p].sale}
        if unit is None or len(sales) < 2 or pointing[unit] != {group}:
            continue
        for position in positions:
            old = promoted[position]
            note = f"learned_unit_alias: sheet unit {list(group[1])} is DXBI unit {unit[1]} ({len(sales)} sales)"
            promoted[position] = MatchResult(
                "matched_sale",
                old.property_key or unit,
                old.sale,
                [*old.reasons, note],
                [*old.warnings, "learned_unit_alias"],
                old.rejected,
            )
    return promoted
