"""Conservative owner-import rules, independent of experiment files and contact data."""

from __future__ import annotations

import re
from bisect import bisect_left, bisect_right
from collections import defaultdict
from decimal import Decimal
from typing import Any, Iterable, Mapping

from app.crm import transaction_matching as tm
from app.crm.owner_namespaces import source_namespace
from app.crm.registry_locations import _area_key, _place_key
from app.market.reference import property_name_lookup_key, unit_lookup_key

POLICY_VERSION = "owner-qualified-1"
SQM_TO_SQFT = Decimal("10.76391041671")
IDENTIFIER_FIELDS = (
    "unit_number",
    "building_number",
    "property_number",
    "plot_number",
    "plot_pre_reg_number",
)


class LookupScopeIndex:
    """Catalog-backed query aliases; the full matcher still proves every candidate."""

    def __init__(self, places: Iterable[Mapping[str, Any]]):
        places = list(places)
        self.by_token: dict[str, set[str]] = defaultdict(set)
        self.area_aliases: dict[str, set[str]] = defaultdict(set)
        self.cache: dict[str, set[str]] = {}
        for place in places:
            area = _area_key(place.get("area_label"))
            if area:
                self.area_aliases[area].update(
                    {
                        property_name_lookup_key(str(place.get("area_label") or "")),
                        property_name_lookup_key(str(place.get("area_key") or "")),
                        _area_key(place.get("area_key")),
                    }
                    - {""}
                )
        labels = {
            str(place.get(field) or "")
            for place in places
            for field in ("building_label", "project_label")
        }
        for label in labels:
            if (
                not tm._location(label)
                or tm.generic_building(label)
                or tm.identifier(label).isdigit()
            ):
                continue
            for token in tm._location_tokens(label):
                if not token.isdigit():
                    self.by_token[token].add(label)

    def names(self, source: Mapping[str, Any]) -> set[str]:
        # Retrieval sees raw provider geography, before catalog normalization.
        # Include its documented legal-area key for the same source community.
        result = set(self.area_aliases.get(_area_key(source.get("area_name")), ()))
        for field in ("building_name", "project_name"):
            value = str(source.get(field) or "")
            if (
                not tm._location(value)
                or tm.generic_building(value)
                or tm.identifier(value).isdigit()
            ):
                continue
            if value not in self.cache:
                candidates = {
                    label
                    for token in tm._location_tokens(value)
                    if not token.isdigit()
                    for label in self.by_token.get(token, ())
                }
                self.cache[value] = {
                    property_name_lookup_key(label)
                    for label in candidates
                    if tm._fits(value, label)
                }
            result.update(self.cache[value])
        return result


def lookup_scopes(
    source: Mapping[str, Any], catalog: LookupScopeIndex | None = None
) -> set[tuple[str, str]]:
    """Bound numeric lookups by an explicit named project, building, or community."""
    names = {
        property_name_lookup_key(str(source.get(key) or ""))
        for key in ("building_name", "project_name", "area_name")
        if tm._location(source.get(key))
        and not tm.generic_building(str(source.get(key) or ""))
        and not tm.identifier(str(source.get(key) or "")).isdigit()
    } - {"", "dubai"}
    if _place_key(source.get("area_name")) == "jumeirahvillagetriangle":
        names.add("jumeirahvillagetrianglejvt")
    if catalog is not None:
        names.update(catalog.names(source))
    units = {unit_lookup_key(unit) for unit in tm.property_lookup_identifiers(source)} - {""}
    return {(name, unit) for name in names for unit in units}


def full_child_villa(source: Mapping[str, Any], target: Mapping[str, Any]) -> bool:
    raw = source.get("original_identifiers") or source
    unit, building, observed = (
        tm.identifier(str(row.get(key) or ""))
        for row, key in ((raw, "unit_number"), (raw, "building_number"), (target, "unit_number"))
    )
    # BuildingNo is itself an original typed child identifier. A normalized
    # UnitNo derived from it adds no second vote, and an absent raw UnitNo is
    # not a contradiction. Parent plots and numeric-only values cannot qualify.
    normalized_unit = tm.identifier(str(source.get("unit_number") or ""))
    return bool(
        building
        and building == observed
        and re.search("[a-z]", building)
        and (not unit or unit == building)
        and (not normalized_unit or normalized_unit == building)
    )


def original_identifier_support(source: Mapping[str, Any], target: Mapping[str, Any]) -> bool:
    raw = source.get("original_identifiers")
    if raw is None:
        return True  # Older persisted rows have no raw-role audit; keep their existing guards.
    kind = tm._kind(target.get("property_type"))
    fields = {
        "flat": ("unit_number", "property_number"),
        "villa": ("building_number", "unit_number"),
        "plot": ("plot_number", "plot_pre_reg_number", "unit_number"),
    }.get(kind, ())
    if not any(tm.identifier(str(raw.get(key) or "")) for key in fields):
        return False
    if source_namespace(source, target):
        return True
    return all(tm._identifiers_fit({**source, **raw}, target))


def hierarchy_flags(source: Mapping[str, Any], target: Mapping[str, Any]) -> list[str]:
    sb, sp, sa = (
        _place_key(source.get(key)) for key in ("building_name", "project_name", "area_name")
    )
    rb, rp, ra = (
        _place_key(target.get(key)) for key in ("building_name", "project_name", "area_name")
    )
    flags = []
    if (
        sb
        and sb == rb
        and sa == "citywalk"
        and ra in {"centralpark", "centalpark"}
        and "citywalk" in rp
        and ("centralpark" in rp or "centalpark" in rp)
    ):
        flags.append("citywalk_centralpark_same_building_hierarchy")

    def marker(value):
        match = re.fullmatch(
            r"(?:citywalkresidential)?(?:building|bldg|tower|block)(?:no)?([0-9]+[a-z]?)(?:cw)?",
            _place_key(value),
        )
        return tm.identifier(match[1]) if match else None

    left, right = marker(source.get("building_name")), marker(target.get("building_name"))
    listed = {
        tm.identifier(value)
        for value in re.findall(
            r"(?:\bno[.\s]*|\bbuilding\s*)(\d+\s*[a-z]?)",
            str(source.get("project_name") or ""),
            re.I,
        )
    }
    if (
        left
        and left == right
        and sa == ra == "citywalk"
        and (sp in {"", "0", "citywalk", "citywalkresidential", sb} or left in listed)
        and (sb.startswith("citywalkresidential") or rb.startswith("citywalkresidential"))
    ):
        flags.append("citywalk_residential_full_building_suffix")
    observed = tm.identifier(str(target.get("unit_number") or ""))
    raw = source.get("original_identifiers") or source
    unit = tm.identifier(str(source.get("unit_number") or ""))
    if not unit:
        # Original BuildingNo is the typed villa child ID when UnitNo is absent.
        # The qualifier checks run only after original_identifier_support.
        field = (
            "building_number"
            if tm._kind(target.get("property_type")) == "villa"
            else "property_number"
        )
        unit = tm.identifier(str(raw.get(field) or ""))
    if (
        unit
        and unit == observed
        and sa == "jumeirahvillagetriangle"
        and not ra
        and rb == "jumeirahvillagetrianglejvt"
        and unit.startswith("jvt")
        and sb in {"", "0", "null", sa, rb}
    ):
        flags.append("jvt_named_community_missing_area")
    if (
        unit
        and unit == observed
        and sa == "alfurjan"
        and sb in {"", "0", "null", "alfurjan"}
        and rb == "alfurjan"
        and _area_key(target.get("area_name")) in {"jabalali1", "jebelali1"}
        and unit.startswith("af")
    ):
        flags.append("alfurjan_named_community_legal_area")
    # The precise target catalog path is evidence; the input filename is not.
    if (
        sb
        and sb == rb
        and re.fullmatch(r"damachills[0-9]{3,}", sa)
        and rb in {"viridisc", "viridisd", "navitastowera", "navitastowerb"}
        and ra == "damachills2"
        and target.get("registry_catalog_confirmed")
    ):
        flags.append("damachills_numeric_master_exact_catalog_building")
    return flags


def qualified(source: Mapping[str, Any], target: Mapping[str, Any]) -> tuple[int, list[str]] | None:
    if not all(tm.property_identity(target)[1:]) or not original_identifier_support(source, target):
        return None
    namespace = source_namespace(source, target)
    if not namespace and not all(tm._identifiers_fit(source, target)):
        return None
    source_kind, target_kind = (
        tm._kind(source.get("property_type")),
        tm._kind(target.get("property_type")),
    )
    child = full_child_villa(source, target)
    if tm.physical_types_conflict(source.get("property_type"), target.get("property_type")):
        return None
    if source_kind == "plot" and target_kind == "villa" and not (child or namespace):
        return None
    score, conflict = tm._scope(source, target)
    hierarchy = hierarchy_flags(source, target)
    if (conflict or not score) and not (hierarchy or namespace):
        return None
    review = set(
        tm._review_flags(
            {**source, "size_sqft": None},
            target,
            max(score, 200) if hierarchy or namespace else score,
            {"amount_aed"},
        )
    )
    if child or namespace:
        review.discard("type_mismatch_review_required")
    if hierarchy or namespace:
        review -= {"geography_review_required", "missing_target_area", "location_review_required"}
    if any("citywalk" in flag for flag in hierarchy):
        review.discard("generic_building_project_review")
    if review - {"date_conflict", "rental_review_required", "unknown_source_event_family"}:
        return None
    return max(score, 200) if hierarchy or namespace else score, hierarchy + (
        ["r3_qualified_full_child_namespace"] if namespace else []
    ) + (["plot_to_villa_same_full_child_id"] if child else [])


def source_unit_identity(source: Mapping[str, Any]) -> tuple[str, ...]:
    raw = source.get("original_identifiers") or source
    return tuple(
        _place_key(source.get(key)) for key in ("area_name", "project_name", "building_name")
    ) + tuple(tm.identifier(str(raw.get(key) or "")) for key in IDENTIFIER_FIELDS)


class SheetSizeEvidence:
    """Each unit gets one vote; predictions exclude every event of that unit."""

    def __init__(self):
        self.votes: dict[tuple[str, str], dict[tuple[str, ...], set[str]]] = defaultdict(
            lambda: defaultdict(set)
        )
        self.source_units: dict[tuple[str, ...], set[tuple[str, ...]]] = defaultdict(set)

    def observe(
        self, source: Mapping[str, Any], candidates: list[tuple[dict, int, list[str]]]
    ) -> None:
        if len(candidates) != 1:
            return
        target, _, flags = candidates[0]
        raw, observed = (
            tm.positive_decimal(source.get("size_unknown")),
            tm.positive_decimal(target.get("size_sqft")),
        )
        if (
            not raw
            or not observed
            or flags
            or tm._day(source.get("transaction_date")) != tm._day(target.get("transaction_date"))
        ):
            return
        if tm._day(source.get("transaction_date")) is None:
            return
        fits = [
            unit
            for unit, multiplier in (("sqft", Decimal(1)), ("sqm", SQM_TO_SQFT))
            if tm.sizes_match(raw * multiplier, observed)
        ]
        vote = fits[0] if len(fits) == 1 else "ambiguous" if fits else "neither"
        unit = tm.property_identity(target)
        self.source_units[source_unit_identity(source)].add(unit)
        self.votes[
            (
                str(source.get("source_file_scope") or source.get("source_filename") or ""),
                str(source.get("source_sheet") or ""),
            )
        ][unit].add(vote)

    def infer(self, source: Mapping[str, Any]) -> dict[str, Any] | None:
        scope = (
            str(source.get("source_file_scope") or source.get("source_filename") or ""),
            str(source.get("source_sheet") or ""),
        )
        votes = [
            values
            for unit, values in self.votes.get(scope, {}).items()
            if unit not in self.source_units.get(source_unit_identity(source), set())
        ]
        if not all(scope) or len(votes) < 10:
            return None
        for label in ("sqft", "sqm"):
            count = sum(values == {label} for values in votes)
            if count >= 10 and Decimal(count) / len(votes) >= Decimal("0.95"):
                return {
                    "unit": label,
                    "independent_units": len(votes),
                    "winning_unit_support": count,
                    "agreement": str(Decimal(count) / len(votes)),
                    "leave_source_unit_out": True,
                }
        return None


class OwnerMatchIndex(tm.AmountFirstIndex):
    """Full identifiers and qualified location precede size/date event selection."""

    def _pool(self, source: Mapping[str, Any]) -> list[int]:
        amount = tm.positive_decimal(source.get("amount_aed"))
        if amount is None:
            return []
        low, high = (
            bisect_left(self._prices, amount - tm.AMOUNT_TOLERANCE_AED),
            bisect_right(self._prices, amount + tm.AMOUNT_TOLERANCE_AED),
        )
        return sorted({item[1] for item in self._entries[low:high]})

    def candidates(self, source: Mapping[str, Any]) -> list[tuple[dict, int, list[str]]]:
        amount = tm.positive_decimal(source.get("amount_aed"))
        result = []
        for index in self._pool(source):
            row = self._events[index]
            family = source.get("event_family")
            if family in {"sale", "rental"} and tm._family(row) != family:
                continue
            if family not in {"sale", "rental", "unknown", "contact_snapshot", "", None}:
                continue
            if source.get("amount_basis") and not any(
                field == source["amount_basis"] and tm.amounts_match(amount, value)
                for field, value in tm._amounts(row)
            ):
                continue
            supported = qualified(source, row)
            if supported:
                result.append((row, *supported))
        return result

    def match(self, source: Mapping[str, Any]) -> tm.AmountMatchResult:
        rows = self.candidates(source)
        pool_count = len(self._pool(source))
        evidence = {
            "version": POLICY_VERSION,
            "amount_tolerance_aed": "2",
            "date_used_as_filter": False,
            "location_candidate_count": len(rows),
            "global_amount_candidate_count": pool_count,
            "identifier_supported": bool(rows),
        }
        if not rows:
            return tm.AmountMatchResult(
                "unmatched",
                candidate_event_count=pool_count,
                flags=("no_supported_original_identifier_location",),
                evidence=evidence,
            )
        original_count = pool_count
        size = tm.positive_decimal(source.get("size_sqft"))
        if size is not None:
            if any(tm.positive_decimal(row.get("size_sqft")) is None for row, _, _ in rows):
                return tm.AmountMatchResult(
                    "ambiguous",
                    candidate_event_count=len(rows),
                    flags=("unknown_target_size",),
                    evidence=evidence,
                )
            rows = [item for item in rows if tm.sizes_match(size, item[0].get("size_sqft"))]
            if not rows:
                return tm.AmountMatchResult(
                    "unmatched",
                    candidate_event_count=original_count,
                    flags=("size_conflict",),
                    evidence=evidence,
                )
        identities = {tm.property_identity(row) for row, _, _ in rows}
        if len(identities) > 1 and size is None:
            return tm.AmountMatchResult(
                "ambiguous",
                candidate_event_count=original_count,
                property_count=len(identities),
                flags=("multiple_properties_no_independent_size",),
                evidence=evidence,
            )
        if len(rows) > 1:
            exact = [
                item
                for item in rows
                if tm._day(source.get("transaction_date")) is not None
                and tm._day(item[0].get("transaction_date"))
                == tm._day(source.get("transaction_date"))
            ]
            if (
                len(exact) == 1
                and tm.exact_date_event(
                    source.get("transaction_date"),
                    [
                        row
                        for row, _, _ in rows
                        if tm.property_identity(row) == tm.property_identity(exact[0][0])
                    ],
                )
                is not None
            ):
                rows = exact
                evidence["date_event_resolution"] = "unique_exact_date_without_nearby_competitor"
        identities = {tm.property_identity(row) for row, _, _ in rows}
        if len(rows) != 1:
            return tm.AmountMatchResult(
                "matched" if len(identities) == 1 else "ambiguous",
                next(iter(identities)) if len(identities) == 1 else None,
                candidate_event_count=original_count,
                property_count=len(identities),
                flags=("ambiguous_transaction",),
                evidence=evidence,
            )
        row, score, flags = rows[0]
        review = set(tm._review_flags(source, row, score, {"amount_aed"}))
        if flags:
            review -= {
                "geography_review_required",
                "missing_target_area",
                "location_review_required",
                "type_mismatch_review_required",
            }
            if any("citywalk" in flag for flag in flags):
                review.discard("generic_building_project_review")
        evidence.update(
            event_family=tm._family(row),
            selected_event_key=tm._event_key(row),
            score=score,
            supported_rules=flags,
            date_delta_days=(
                tm._day(row.get("transaction_date")) - tm._day(source.get("transaction_date"))
            ).days
            if tm._day(row.get("transaction_date")) and tm._day(source.get("transaction_date"))
            else None,
        )
        exact = bool(
            tm._day(source.get("transaction_date"))
            and tm._day(source.get("transaction_date")) == tm._day(row.get("transaction_date"))
            and not review
        )
        return tm.AmountMatchResult(
            "matched",
            tm.property_identity(row),
            row,
            original_count,
            1,
            exact,
            tuple(sorted(review)),
            evidence,
        )


class PropertyIdentityIndex:
    """Index complete property candidates once for an import batch."""

    def __init__(self, events: Iterable[Mapping[str, Any]]):
        self._events = [dict(row) for row in events]
        self._identifiers: dict[str, list[int]] = {}
        for index, row in enumerate(self._events):
            full = tm.identifier(str(row.get("unit_number") or row.get("unit_key") or ""))
            keys = {full} - {""}
            if tm._kind(row.get("property_type")) == "villa" and (
                suffix := re.search(r"(\d+)$", full)
            ):
                keys.add(str(int(suffix.group(1))))
            for key in keys:
                self._identifiers.setdefault(key, []).append(index)

    def candidates(self, source: Mapping[str, Any]) -> list[dict[str, Any]]:
        indices = {
            index
            for key in tm.property_lookup_identifiers(source)
            for index in self._identifiers.get(key, [])
        }
        return [self._events[index] for index in sorted(indices)]

    def match(self, source: Mapping[str, Any]) -> tm.AmountMatchResult:
        rows = self.candidates(source)
        supported = [row for row in rows if qualified(source, row)]
        identities = {tm.property_identity(row) for row in supported}
        if len(identities) == 1:
            return tm.AmountMatchResult(
                "matched",
                next(iter(identities)),
                candidate_event_count=len(rows),
                property_count=1,
                flags=("identity_only",),
                evidence={
                    "version": tm.MATCHER_VERSION,
                    "method": "exact_scoped_property_identity",
                    "identifier_supported": True,
                    "amount_used": False,
                    "date_used_as_filter": False,
                },
            )
        if supported or source.get("original_identifiers") is not None:
            return tm.AmountMatchResult(
                "ambiguous" if supported else "unmatched",
                candidate_event_count=len(rows),
                property_count=len(identities),
            )
        return tm.match_property(source, rows)
