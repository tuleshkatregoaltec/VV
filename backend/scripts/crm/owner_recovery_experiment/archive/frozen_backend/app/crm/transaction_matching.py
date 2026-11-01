"""Shared, pure amount-first DXBI matching; property links never certify ownership."""

from __future__ import annotations

import re
from bisect import bisect_left, bisect_right
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from functools import lru_cache
from types import SimpleNamespace
from typing import Any

from app.crm.identity import (
    _location_number_markers,
    _location_similarity,
    _location_tokens,
    _transaction_location_score,
    _usable_project_name,
)
from app.crm.import_normalization import normalize_location, positive_decimal
from app.market.reference import property_name_lookup_key

MATCHER_VERSION = "amount-first-1"
AMOUNT_TOLERANCE_AED = Decimal("2")
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


def property_identity(event: Mapping[str, Any]) -> tuple[str, str, str]:
    from app.crm.owner_namespaces import registry_namespace

    if namespace := registry_namespace(event):
        return namespace[0], f"r3::{namespace[1]}", namespace[2]
    building = str(event.get("building_name") or event.get("project_name") or "")
    building_key = property_name_lookup_key(building)
    project_key = property_name_lookup_key(str(event.get("project_name") or ""))
    if generic_building(building) and project_key:
        building_key = f"{project_key}::{building_key}"
    return (
        normalize_location(event.get("area_name"), area=True),
        building_key,
        identifier(str(event.get("unit_number") or event.get("unit_key") or "")),
    )


def amounts_match(imported: Any, observed: Any) -> bool:
    left, right = positive_decimal(imported), positive_decimal(observed)
    return left is not None and right is not None and abs(left - right) <= AMOUNT_TOLERANCE_AED


def sizes_match(imported: Any, observed: Any) -> bool:
    left, right = positive_decimal(imported), positive_decimal(observed)
    return (
        left is not None
        and right is not None
        and abs(left - right) <= max(Decimal("50"), left * Decimal("0.02"))
    )


def _day(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def exact_date_event(
    source_date: Any, events: Iterable[Mapping[str, Any]]
) -> Mapping[str, Any] | None:
    """Use an exact date only after amount and property identity are established.

    A competing registration within fourteen days, or one with an unknown date,
    prevents choosing a transaction. No nearest-date selection or property filtering.
    """
    day = _day(source_date)
    if day is None:
        return None
    rows = list(events)
    dated = [(row, _day(row.get("transaction_date") or row.get("lease_start"))) for row in rows]
    exact = [row for row, observed in dated if observed == day]
    if len(exact) != 1:
        return None
    selected = exact[0]
    if any(
        row is not selected and (observed is None or abs((observed - day).days) <= 14)
        for row, observed in dated
    ):
        return None
    return selected


def _family(row: Mapping[str, Any]) -> str:
    value = str(row.get("event_family") or row.get("category") or "")
    return value or ("rental" if row.get("contract_key") or row.get("annual_rent_aed") else "sale")


def _amounts(row: Mapping[str, Any]) -> list[tuple[str, Decimal]]:
    # Rental purchase_price_aed is historical sale context, never rental consideration.
    fields = (
        ("contract_amount_aed", "annual_rent_aed")
        if _family(row) == "rental"
        else ("sale_amount_aed",)
    )
    values = [(name, row.get(name)) for name in ("amount_aed", *fields)]
    values.extend(
        (str(item.get("field") or "amount_aed"), item.get("value", item.get("amount_aed")))
        for item in row.get("amounts", [])
        if item.get("field") in {"amount_aed", *fields}
    )
    return [
        (name, amount) for name, value in values if (amount := positive_decimal(value)) is not None
    ]


def _event_key(row: Mapping[str, Any]) -> str:
    return f"{_family(row)}:" + str(
        row.get("event_key")
        or row.get("sale_key")
        or row.get("contract_key")
        or (
            property_identity(row),
            str(row.get("transaction_date") or row.get("lease_start")),
            _amounts(row),
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


def physical_types_conflict(source: Any, observed: Any) -> bool:
    """A shared unit-number namespace does not make explicit property uses equal."""
    aliases = {
        "apartment": "apartment",
        "apartments": "apartment",
        "flat": "apartment",
        "flats": "apartment",
        "office": "office",
        "offices": "office",
        "shop": "retail",
        "shops": "retail",
        "retail": "retail",
        "villa": "villa",
        "villas": "villa",
        "townhouse": "villa",
        "townhouses": "villa",
    }
    left = aliases.get(str(source or "").casefold().strip())
    right = aliases.get(str(observed or "").casefold().strip())
    return bool(left and right and left != right)


def _location(value: Any) -> str:
    text = str(value or "")
    return "" if text.casefold().strip() in _MISSING else _usable_project_name(text)


def _fits(left: str, right: str) -> bool:
    if not left or not right:
        return False
    ln, rn = _location_number_markers(left), _location_number_markers(right)
    if ln and rn and ln != rn:
        return False
    lt, rt = frozenset(_location_tokens(left)), frozenset(_location_tokens(right))
    return _location_similarity(left, right) >= 80 or bool(lt and rt and (lt <= rt or rt <= lt))


def _scope(source: Mapping[str, Any], row: Mapping[str, Any]) -> tuple[int, bool]:
    return _scope_names(
        *(
            str(source.get(key) or "")
            for key in ("building_name", "project_name", "area_name", "source_area_field")
        ),
        *(str(row.get(key) or "") for key in ("building_name", "project_name", "area_name")),
    )


@lru_cache(maxsize=100_000)
def _scope_names(
    building: str,
    project: str,
    area: str,
    source_area_field: str,
    observed_building: str,
    observed_project: str,
    observed_area: str,
) -> tuple[int, bool]:
    building, project, area = map(_location, (building, project, area))
    observed_building, observed_project, observed_area = map(
        _location, (observed_building, observed_project, observed_area)
    )
    generic = generic_building(building) or generic_building(observed_building)
    broad_project = normalize_location(project, area=True) == normalize_location(area, area=True)
    if (
        generic
        and project
        and observed_project
        and not broad_project
        and not property_scope_matches(project, observed_project)
    ):
        return 0, True
    # A numeric villa/building identifier is not a tower-name qualifier.
    if identifier(building).isdigit():
        building = ""
    bn, rn = _location_number_markers(building), _location_number_markers(observed_building)
    if bn and rn and bn != rn:
        return 0, True
    building_fit = _fits(building, observed_building)
    project_fit = any(_fits(project, value) for value in (observed_project, observed_building))
    if (
        building
        and observed_building
        and not building_fit
        and normalize_location(building)
        not in {normalize_location(project), normalize_location(area)}
    ):
        generic = {
            "tower",
            "building",
            "house",
            "residence",
            "residences",
            "block",
            "phase",
            "villa",
            "villas",
            "apartment",
            "apartments",
        }
        left = set(_location_tokens(building)) - generic
        right = set(_location_tokens(observed_building)) - generic
        if not left.intersection(right):
            return 0, True
    area_fit = bool(
        area and normalize_location(area, area=True) == normalize_location(observed_area, area=True)
    )
    if not area_fit and source_area_field == "master_project":
        # Registry master-project labels sometimes append a cadastral number.
        area_fit = bool(re.search(r"\b\d{3,}$", area)) and {
            token for token in _location_tokens(area) if not token.isdigit()
        } == set(_location_tokens(observed_area))
    if not (building_fit or project_fit or area_fit):
        return 0, bool(building or project or area)
    # A precise building match can bridge marketed/legal geography names.
    score = _transaction_location_score(
        SimpleNamespace(building_name=building, project_name=project, area_name=area),
        {
            "building_name": observed_building,
            "project_name": observed_project,
            "area_name": observed_area,
        },
    )
    return (300 if building_fit else 200 if project_fit else 100) + score, False


def _identifiers_fit(source: Mapping[str, Any], row: Mapping[str, Any]) -> tuple[bool, bool]:
    observed = identifier(str(row.get("unit_number") or row.get("unit_key") or ""))
    kind = _kind(row.get("property_type")) or _kind(source.get("property_type"))
    unit = identifier(str(source.get("unit_number") or ""))
    number = identifier(str(source.get("building_number") or ""))
    if kind == "plot":
        # A parent plot reference cannot identify a different explicit child
        # unit. Keep both namespaces constrained even when PlotPreRegNo agrees.
        if unit and unit != observed:
            return False, False
        supplied = next(
            (
                value
                for field in ("plot_number", "plot_pre_reg_number", "unit_number")
                if (value := identifier(str(source.get(field) or "")))
            ),
            "",
        )
    elif kind == "villa":
        supplied = number or unit
    else:
        supplied = unit or identifier(str(source.get("property_number") or ""))
    if not supplied:
        return True, False

    def agrees(value: str) -> bool:
        if value == observed:
            return True
        if kind != "villa" or not value.isdigit():
            return False
        # Numeric villa IDs require a corroborated namespace. Plots and flats
        # never borrow a trailing numeric fragment from another full code.
        match = re.fullmatch(r"(.+?)[-_/](?:v[-_/])?(\d+)", observed)
        namespace = property_name_lookup_key(match.group(1)) if match else ""
        names = [
            property_name_lookup_key(_location(source.get(key)))
            for key in ("building_name", "project_name")
        ]
        return bool(
            match and match.group(2) == value and any(name and name in namespace for name in names)
        )

    # Explicit full unit and BuildingNo must both identify the same villa.
    fits = agrees(supplied) and (kind != "villa" or not unit or agrees(unit))
    return fits, fits


def _review_flags(
    source: Mapping[str, Any], row: Mapping[str, Any], score: int, matching_fields: set[str]
) -> list[str]:
    flags: list[str] = []
    if str(source.get("event_family") or "unknown") in {"unknown", "contact_snapshot", ""}:
        flags.append("unknown_source_event_family")
    if score < 200 and _location(source.get("building_name")):
        flags.append("location_review_required")
    if (
        _kind(source.get("property_type")) == "plot" and _kind(row.get("property_type")) == "villa"
    ) or physical_types_conflict(source.get("property_type"), row.get("property_type")):
        flags.append("type_mismatch_review_required")
    source_date = _day(source.get("transaction_date"))
    observed_date = _day(row.get("transaction_date") or row.get("lease_start"))
    if source_date and observed_date and source_date != observed_date:
        flags.append("date_conflict")
    if generic_building(str(source.get("building_name") or "")) or generic_building(
        str(row.get("building_name") or "")
    ):
        source_project = _location(source.get("project_name"))
        target_project = _location(row.get("project_name"))
        broad_project = normalize_location(source_project, area=True) == normalize_location(
            source.get("area_name"), area=True
        )
        if not source_project or not target_project or broad_project:
            flags.append("generic_building_project_review")
    source_area = normalize_location(source.get("area_name"), area=True)
    target_area = normalize_location(row.get("area_name"), area=True)
    source_project = normalize_location(source.get("project_name"), area=True)
    target_project = normalize_location(row.get("project_name"), area=True)
    hierarchy_bridge = (source_area and source_area == target_project) or (
        source_project and source_project == target_area
    )
    master_project_bridge = (
        source.get("source_area_field") == "master_project"
        and bool(re.search(r"\b\d{3,}$", str(source.get("area_name") or "")))
        and {
            token
            for token in _location_tokens(str(source.get("area_name") or ""))
            if not token.isdigit()
        }
        == set(_location_tokens(str(row.get("area_name") or "")))
    )
    if (
        source_area
        and target_area
        and source_area != target_area
        and not hierarchy_bridge
        and not master_project_bridge
    ):
        flags.append("geography_review_required")
    if source_area and not target_area:
        flags.append("missing_target_area")
    source_size, observed_size = (
        positive_decimal(source.get("size_sqft")),
        positive_decimal(row.get("size_sqft")),
    )
    if source_size and observed_size and not sizes_match(source_size, observed_size):
        flags.append("size_conflict")
    if _family(row) == "rental":
        flags.append("rental_review_required")
        if matching_fields == {"annual_rent_aed"}:
            flags.append("annualized_amount_basis")
    return flags


@dataclass(frozen=True)
class AmountMatchResult:
    status: str
    property_identity: tuple[str, str, str] | None = None
    event: dict[str, Any] | None = None
    candidate_event_count: int = 0
    property_count: int = 0
    exact_transaction: bool = False
    flags: tuple[str, ...] = ()
    evidence: dict[str, Any] = field(default_factory=dict)


class AmountFirstIndex:
    """Index the complete supplied event universe once, then compare Decimal bands.

    Callers must not truncate candidates before constructing this index. A unique
    property can contain several indistinguishable registrations: event stays None.
    """

    def __init__(self, events: Iterable[Mapping[str, Any]]):
        self._events: list[dict[str, Any]] = []
        entries: list[tuple[Decimal, int, str]] = []
        seen: set[tuple[str, tuple[str, str, str]]] = set()
        for value in events:
            row = dict(value)
            identity = property_identity(row)
            amounts = _amounts(row)
            key = (_event_key(row), identity)
            if key in seen or not amounts:
                continue
            seen.add(key)
            index = len(self._events)
            self._events.append(row)
            entries.extend((amount, index, name) for name, amount in amounts)
        entries.sort()
        self._entries = entries
        self._prices = [entry[0] for entry in entries]

    def match(self, source: Mapping[str, Any]) -> AmountMatchResult:
        amount = positive_decimal(source.get("amount_aed", source.get("transaction_price_aed")))
        if amount is None:
            return AmountMatchResult("unmatched", flags=("missing_positive_amount",))
        low = bisect_left(self._prices, amount - AMOUNT_TOLERANCE_AED)
        high = bisect_right(self._prices, amount + AMOUNT_TOLERANCE_AED)
        pool: dict[int, set[str]] = {}
        for _, index, name in self._entries[low:high]:
            pool.setdefault(index, set()).add(name)
        source_family = str(source.get("event_family") or "unknown")
        if source_family not in {"sale", "rental", "unknown", "contact_snapshot", ""}:
            return AmountMatchResult(
                "unmatched", candidate_event_count=len(pool), flags=("unsupported_event_family",)
            )
        amount_basis = source.get("amount_basis")
        ranked: list[tuple[int, int, bool]] = []
        for index in pool:
            row = self._events[index]
            if source_family in {"sale", "rental"} and _family(row) != source_family:
                continue
            if amount_basis and amount_basis not in pool[index]:
                continue
            identity = property_identity(row)
            if not identity[1] or not identity[2]:
                continue
            fits, id_supported = _identifiers_fit(source, row)
            if not fits:
                continue
            score, conflict = _scope(source, row)
            source_kind, observed_kind = (
                _kind(source.get("property_type")),
                _kind(row.get("property_type")),
            )
            # Land is a broad legal category in source exports, not a villa label.
            type_conflict = (
                source_kind in {"flat", "villa"}
                and observed_kind in {"flat", "villa"}
                and source_kind != observed_kind
            )
            if source_kind == "plot" and observed_kind == "villa":
                explicit_plot = source.get("plot_number") or source.get("plot_pre_reg_number")
                villa_identifier = source.get("building_number") or re.search(
                    r"[-_/]v[-_/]", str(source.get("unit_number") or ""), re.IGNORECASE
                )
                type_conflict = bool(explicit_plot or not villa_identifier)
            if conflict or not fits or type_conflict or not score:
                continue
            ranked.append((score, index, id_supported))
        evidence: dict[str, Any] = {
            "version": MATCHER_VERSION,
            "amount_tolerance_aed": "2",
            "source_amount_aed": str(amount),
            "global_amount_candidate_count": len(pool),
            "location_candidate_count": len(ranked),
            "date_used_as_filter": False,
        }
        if not ranked:
            return AmountMatchResult(
                "unmatched", candidate_event_count=len(pool), evidence=evidence
            )
        # Size supports event resolution; it never rescues a conflicting explicit ID.
        best_score = max(item[0] for item in ranked)
        best = [item for item in ranked if item[0] == best_score]
        identities = {property_identity(self._events[item[1]]) for item in best}
        if len(identities) > 1:
            supporting = [
                item
                for item in best
                if sizes_match(source.get("size_sqft"), self._events[item[1]].get("size_sqft"))
            ]
            supported_ids = {property_identity(self._events[item[1]]) for item in supporting}
            if len(supported_ids) == 1:
                best, identities = supporting, supported_ids
        if len(identities) != 1:
            return AmountMatchResult(
                "ambiguous",
                candidate_event_count=len(pool),
                property_count=len(identities),
                evidence=evidence,
            )
        identity = next(iter(identities))
        events = [item for item in ranked if property_identity(self._events[item[1]]) == identity]
        if len(events) > 1 and positive_decimal(source.get("size_sqft")) is not None:
            known_sizes = all(
                positive_decimal(self._events[item[1]].get("size_sqft")) is not None
                for item in events
            )
            supported = [
                item
                for item in events
                if sizes_match(source.get("size_sqft"), self._events[item[1]].get("size_sqft"))
            ]
            if known_sizes and len(supported) == 1:
                events = supported
        if len(events) > 1:
            dated = exact_date_event(
                source.get("transaction_date"), [self._events[item[1]] for item in events]
            )
            if dated is not None:
                events = [item for item in events if self._events[item[1]] is dated]
                evidence["date_event_resolution"] = "unique_exact_date_without_nearby_competitor"
                evidence["date_conflict_window_days"] = 14
        evidence.update(identifier_supported=all(item[2] for item in events), score=best_score)
        if len(events) != 1:
            review = [
                set(_review_flags(source, self._events[index], score, pool[index]))
                for score, index, _ in events
            ]
            flags = {"ambiguous_transaction"} | set().union(*review)
            flags.discard("date_conflict")
            if not all("size_conflict" in item for item in review):
                flags.discard("size_conflict")
            return AmountMatchResult(
                "matched",
                identity,
                candidate_event_count=len(pool),
                property_count=1,
                flags=tuple(sorted(flags)),
                evidence=evidence,
            )
        _, index, id_supported = events[0]
        row = self._events[index]
        flags = _review_flags(source, row, best_score, pool[index])
        source_date = _day(source.get("transaction_date"))
        observed_date = _day(row.get("transaction_date") or row.get("lease_start"))
        evidence.update(
            score=best_score,
            identifier_supported=id_supported,
            matching_amount_fields=sorted(pool[index]),
            event_family=_family(row),
            selected_event_key=_event_key(row),
            date_delta_days=abs((observed_date - source_date).days)
            if observed_date and source_date
            else None,
        )
        exact = bool(source_date and observed_date == source_date and not flags)
        return AmountMatchResult(
            "matched", identity, row, len(pool), 1, exact, tuple(flags), evidence
        )


def property_lookup_identifiers(source: Mapping[str, Any]) -> tuple[str, ...]:
    """Candidate retrieval keys only; suffix/name compatibility remains below."""
    from app.crm.owner_namespaces import parse_r3

    values = {
        full[1] for key in ("unit_number", "building_number") if (full := parse_r3(source.get(key)))
    }
    return tuple(
        sorted(
            {
                identifier(str(source.get(field) or ""))
                for field in (
                    "unit_number",
                    "plot_number",
                    "plot_pre_reg_number",
                    "property_number",
                    "building_number",
                )
            }.union(values)
            - {""}
        )
    )


def property_scope(source: Mapping[str, Any]) -> tuple[str, str]:
    return _location(source.get("building_name")), _location(source.get("project_name"))


@lru_cache(maxsize=100_000)
def property_scope_matches(source_label: str, target_label: str) -> bool:
    """Exact/vetted-alias scope predicate shared with database prefilters."""
    left, right = _location(source_label), _location(target_label)
    return bool(left and right) and (
        _location_similarity(left, right) == 100
        or property_name_lookup_key(left) == property_name_lookup_key(right)
    )


def match_property(
    source: Mapping[str, Any], events: Iterable[Mapping[str, Any]]
) -> AmountMatchResult:
    """Resolve a scoped full identifier independently of monetary consideration.

    This result never selects a transaction or establishes an owner. Callers must
    provide every candidate for the source's full identifiers (and villa suffix
    lookup keys); this function checks complete namespaces and unique properties.
    """
    if not property_lookup_identifiers(source):
        return AmountMatchResult("unmatched", flags=("missing_property_identifier",))
    source_building, source_project = property_scope(source)
    building = source_building or source_project
    if not building or identifier(building).isdigit():
        return AmountMatchResult("unmatched", flags=("missing_building_scope",))
    source_area = normalize_location(source.get("area_name"), area=True)
    candidates = []
    count = 0
    for value in events:
        count += 1
        row = dict(value)
        observed_building = _location(row.get("building_name"))
        scopes = (
            [observed_building]
            if source_building
            else [_location(row.get("project_name")), observed_building]
        )
        if not any(property_scope_matches(building, scope) for scope in scopes):
            continue
        fits, supported = _identifiers_fit(source, row)
        if not fits or not supported:
            continue
        score, conflict = _scope(source, row)
        if conflict or not score:
            continue
        review = set(_review_flags(source, row, score, set())) - {
            "date_conflict",
            "annualized_amount_basis",
        }
        if "geography_review_required" in review:
            continue
        source_kind, observed_kind = (
            _kind(source.get("property_type")),
            _kind(row.get("property_type")),
        )
        if (
            source_kind == "plot"
            and observed_kind == "villa"
            and (
                source.get("plot_number")
                or source.get("plot_pre_reg_number")
                or not (
                    source.get("building_number")
                    or re.search(
                        r"[-_/]v[-_/]", str(source.get("unit_number") or ""), re.IGNORECASE
                    )
                )
            )
        ):
            continue
        identity = property_identity(row)
        if source_area and not identity[0]:
            review.add("missing_target_area")
        candidates.append((identity, review))
    evidence = {
        "version": MATCHER_VERSION,
        "method": "exact_scoped_property_identity",
        "identifier_supported": bool(candidates),
        "candidate_event_count": count,
        "location_candidate_count": len(candidates),
        "amount_used": False,
        "date_used_as_filter": False,
    }
    identities = {identity for identity, _ in candidates}
    if len(identities) != 1:
        return AmountMatchResult(
            "ambiguous" if identities else "unmatched",
            candidate_event_count=count,
            property_count=len(identities),
            evidence=evidence,
        )
    reviews = [review for _, review in candidates]
    flags = {"identity_only"} | set().union(*reviews)
    if not all("size_conflict" in review for review in reviews):
        flags.discard("size_conflict")
    if positive_decimal(source.get("amount_aed", source.get("transaction_price_aed"))) is None:
        flags.add("missing_positive_amount")
    return AmountMatchResult(
        "matched",
        next(iter(identities)),
        candidate_event_count=count,
        property_count=1,
        flags=tuple(sorted(flags)),
        evidence=evidence,
    )


class PropertyIdentityIndex:
    """Index complete property candidates once for an import batch."""

    def __init__(self, events: Iterable[Mapping[str, Any]]):
        self._events = [dict(row) for row in events]
        self._identifiers: dict[str, list[int]] = {}
        for index, row in enumerate(self._events):
            full = identifier(str(row.get("unit_number") or row.get("unit_key") or ""))
            keys = {full} - {""}
            if _kind(row.get("property_type")) == "villa" and (
                suffix := re.search(r"(\d+)$", full)
            ):
                keys.add(str(int(suffix.group(1))))
            for key in keys:
                self._identifiers.setdefault(key, []).append(index)

    def candidates(self, source: Mapping[str, Any]) -> list[dict[str, Any]]:
        indices = {
            index
            for key in property_lookup_identifiers(source)
            for index in self._identifiers.get(key, [])
        }
        return [self._events[index] for index in sorted(indices)]

    def match(self, source: Mapping[str, Any]) -> AmountMatchResult:
        from app.crm.owner_matching_policy import qualified

        rows = self.candidates(source)
        supported = [row for row in rows if qualified(source, row)]
        identities = {property_identity(row) for row in supported}
        if len(identities) == 1:
            return AmountMatchResult(
                "matched",
                next(iter(identities)),
                candidate_event_count=len(rows),
                property_count=1,
                flags=("identity_only",),
                evidence={
                    "version": MATCHER_VERSION,
                    "method": "exact_scoped_property_identity",
                    "identifier_supported": True,
                    "amount_used": False,
                    "date_used_as_filter": False,
                },
            )
        if supported or source.get("original_identifiers") is not None:
            return AmountMatchResult(
                "ambiguous" if supported else "unmatched",
                candidate_event_count=len(rows),
                property_count=len(identities),
            )
        return match_property(source, rows)
