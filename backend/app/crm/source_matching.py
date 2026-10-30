"""Reproducible transaction comparison for reviewed owner-source snapshots.

Transaction identities support the workbook's named parties; the warehouse has
no named buyers and this comparison never represents legal title verification.
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter, defaultdict
from datetime import date
from decimal import Decimal
from functools import lru_cache
from typing import Any

from app.crm.identity import (
    _location_alias_identity,
    _location_tokens,
    _normalize_phone,
    _owner_key,
)
from app.crm.import_normalization import normalize_location, positive_decimal
from app.crm.source_audit import CANDIDATE_DISPOSITIONS, REVIEW_DISPOSITIONS, SourceAuditPayload
from app.market.reference import property_name_lookup_key, unit_lookup_key

MATCH_VERSION = "reviewed-source-transactions/2"
_SQM_TO_SQFT = Decimal("10.76391041671")
_FINANCIAL = re.compile(
    r"\b(?:banks?|banking|bancorp|banco|finance|financial|financing|mortgage|tamweel|amlak)\b|بنك|مصرف|تمويل",
    re.I,
)
_EXCLUDED = REVIEW_DISPOSITIONS | {
    "excluded_whole_building_or_project_context",
    "excluded_possible_nonownership_transaction",
}
_GENERIC_BUILDING = re.compile(r"^(?:tower|building|block)\s*[a-z0-9]+$", re.I)
_PROJECT_EQUIVALENTS = {
    "maple": "maple1",
    "sidra": "sidra1",
    "sidravillas": "sidravillas",
    "mapleiii": "maple3",
    "magcity": "mageyetownhouses",
    "mageyephase1": "mageyetownhouses",
    "clubvillasatdubaihills": "clubvillas",
    "golfsuitesdubaihills": "golfsuites",
    "golfville": "golfville",
    "golfplace": "golfplace1",
    "golfplacell": "golfplace2",
    "parkheightsiit1": "parkheights2tower1",
    "parkheights2t1": "parkheights2tower1",
    "parkheightsiit2": "parkheights2tower2",
    "parkheights2t2": "parkheights2tower2",
}


def is_financial_party(name: str) -> bool:
    return bool(_FINANCIAL.search(name))


@lru_cache(maxsize=20000)
def _name(value: Any) -> str:
    text = str(value or "")
    key = _location_alias_identity(text)
    key = _PROJECT_EQUIVALENTS.get(key, key)
    if key == property_name_lookup_key(text):
        key = "".join(_location_tokens(text))
    # This named project is recorded with and without its Park Heights suffix.
    if key.startswith("mulberry"):
        key = key.replace("atparkheights", "").replace("parkheights", "")
    return _PROJECT_EQUIVALENTS.get(key, key)


@lru_cache(maxsize=10000)
def _area(value: Any, project: str = "") -> str:
    text = normalize_location(value or "", area=True)
    # These are this export's explicit master/subproject labels, not fuzzy geography.
    if text.startswith("dubai hills - ") or text in {"dubai hills", "dubai hills estate"}:
        return "dubaihillsestate"
    if (
        text == "hadaeq sheikh mohammed bin rashid - disrict 7"
        and _name(project) == "mageyetownhouses"
    ):
        return "mohammedbinrashidcity"
    return property_name_lookup_key(text) if text not in {"0", ""} else ""


def _date(value: Any) -> str:
    return value.isoformat() if isinstance(value, date) else str(value)


def _identity(sale: dict) -> str:
    return "|".join(
        (
            _area(sale.get("area_name")),
            str(
                sale.get("building_key")
                or _name(sale.get("building_name") or sale.get("project_name"))
            ),
            unit_lookup_key(sale.get("unit_number")),
        )
    )


def _signature(row: Any, sale: dict) -> bool:
    """Dates and positive amount/size are all required for an acquisition anchor."""
    amount, size = positive_decimal(row.amount_aed), positive_decimal(row.size_sqm)
    price, sqft = (
        positive_decimal(sale.get("sale_amount_aed")),
        positive_decimal(sale.get("size_sqft")),
    )
    return bool(
        amount
        and size
        and price
        and sqft
        and row.recorded_at.isoformat() == _date(sale["transaction_date"])
        and abs(amount - price) <= Decimal("0.50")
        and abs(size * _SQM_TO_SQFT - sqft)
        <= max(Decimal("1"), size * _SQM_TO_SQFT * Decimal("0.02"))
    )


def _types_compatible(row: Any, sale: dict, *, anchored: bool) -> bool:
    source = row.property_type.strip().casefold()
    target = str(sale.get("property_type") or "").strip().casefold()
    apartments = {"apartment", "apartments", "flat", "flats"}
    villas = {"villa", "villas", "townhouse", "townhouses"}
    shops = {"shop", "shops", "retail"}
    offices = {"office", "offices"}
    plots = {"land", "plot", "plots"}
    if source in apartments:
        return target in apartments
    if source in villas:
        return target in villas
    if source in shops:
        return target in shops
    if source in offices:
        return target in offices
    if source == "unit":
        return target in apartments | shops | offices | {"unit"}
    if source == "building":
        return target in villas | {"building"}
    if source in plots:
        return target in plots or (anchored and target in villas)
    # Residential Flats/Residential in this export describe cadastral land-use
    # for plot/building references, rather than an individual flat's type.
    return True


class _Index:
    def __init__(self, bundle: dict):
        self.by_unit = defaultdict(list)
        self.by_day = defaultdict(list)
        self.by_identity = defaultdict(dict)
        self.aliases = defaultdict(set)
        for alias in bundle.get("aliases", []):
            self.aliases[str(alias["name_key"])].add(
                (
                    str(alias["building_id"]),
                    str(alias["community_key"]),
                    str(alias.get("project_key") or ""),
                )
            )
        for raw in bundle["sales"]:
            sale = dict(raw)
            sale["transaction_date"] = _date(sale["transaction_date"])
            if (
                not unit_lookup_key(sale.get("unit_number"))
                or unit_lookup_key(sale.get("unit_number")) == "0"
            ):
                continue
            self.by_unit[unit_lookup_key(sale["unit_number"])].append(sale)
            self.by_day[sale["transaction_date"]].append(sale)
            self.by_identity[_identity(sale)][str(sale["sale_key"])] = sale

    def compatible(
        self, row: Any, sale: dict, *, source_building: str, project_only: bool = False
    ) -> bool:
        sa, ra = (
            _area(row.source_values[2] if len(row.source_values) > 2 else "", row.project),
            _area(sale.get("area_name")),
        )
        if not sa or not ra or sa != ra:
            # This workbook sometimes assigns the MAG Eye project to a Dubai
            # Hills master label. Repair only with the explicit MAG project,
            # exact unit lookup and a dated amount/size anchor in its community.
            mag_anchor = (
                _name(row.project) == "mageyetownhouses"
                and _name(sale.get("building_name")) == "mageyetownhouses"
                and ra == "mohammedbinrashidcity"
                and _signature(row, sale)
            )
            if not mag_anchor:
                return False
        source_name = row.project if project_only else source_building
        source, target = (
            _name(source_name),
            _name(sale.get("building_name") or sale.get("project_name")),
        )
        project, registry_project = _name(row.project), _name(sale.get("project_name"))
        # Source project can be the warehouse building (e.g. Maple1), while the
        # warehouse project can be the umbrella SidraVillas. Numbered phase stays.
        project_match = bool(project and project in {target, registry_project})
        if project_only:
            return project_match
        direct = bool(source and source == target)
        # A qualified source label may repeat its exact project before a generic
        # tower/building. The warehouse must carry that same project explicitly.
        if project and registry_project == project and source.startswith(project):
            direct = direct or source[len(project) :] == target
        aliases = self.aliases.get(property_name_lookup_key(source_name), set())
        target_aliases = self.aliases.get(
            property_name_lookup_key(str(sale.get("building_name") or "")), set()
        )
        source_ids = {ident for ident, community, _ in aliases if community.split("/")[0] == ra}
        target_ids = {
            ident for ident, community, _ in target_aliases if community.split("/")[0] == ra
        }
        alias_match = len(source_ids & target_ids) == 1
        if not (direct or alias_match):
            return False
        if _GENERIC_BUILDING.fullmatch(source_name.strip()):
            return bool(project and registry_project and project == registry_project)
        if project and registry_project and not project_match:
            # Identical building is enough only where source project names that
            # same building or a known unnumbered umbrella, never conflicting phases.
            umbrella = (
                registry_project in {"dubaihills", "dubaihillsestate"}
                or (registry_project == "sidravillas" and source.startswith("sidra"))
                or (registry_project == project + "tower")
            )
            if project != source and not umbrella:
                return False
        return True


def _owner_keys(payload: SourceAuditPayload, import_id: int) -> dict[int, str]:
    keys = {}
    source = {row.cleaned_row_number: row for row in payload.rows}
    for ref in payload.references:
        scope = f"source-audit:{import_id}:{ref.reference_id}"
        for index, group in enumerate(ref.owner_candidate_groups):
            row = source[group[0]]
            phone = next(
                (
                    _normalize_phone(source[n].phone)
                    for n in group
                    if _normalize_phone(source[n].phone)
                ),
                None,
            )
            key = _owner_key(
                contact_name=row.contact_name,
                phone_primary=phone,
                phone_alternate=None,
                email_primary=None,
                property_key=scope,
            )
            if (
                ref.disposition == "provisional_named_party_multiple_phones"
                or len(ref.owner_candidate_groups) > 1
            ):
                key = hashlib.sha256(f"{scope}:group:{index}".encode()).hexdigest()
            for number in group:
                keys[number] = key
    # Use observed contact identity; a name without a phone remains reference scoped.
    for row in payload.rows:
        keys.setdefault(
            row.cleaned_row_number,
            _owner_key(
                contact_name=row.contact_name,
                phone_primary=_normalize_phone(row.phone),
                phone_alternate=None,
                email_primary=None,
                property_key=f"source-audit:{import_id}:{row.reference_id}",
            ),
        )
    # Reviewed multi-phone/coowner groups also identify their earlier buyer events
    # when name and an explicitly retained phone coincide, never merely name alone.
    candidates = defaultdict(set)
    for ref in payload.references:
        for group in ref.owner_candidate_groups:
            for n in group:
                row = source[n]
                candidates[
                    (
                        ref.reference_id,
                        re.sub(r"\W", "", row.contact_name.casefold()),
                        _normalize_phone(row.phone),
                    )
                ].add(keys[n])
    for row in payload.rows:
        token = (
            row.reference_id,
            re.sub(r"\W", "", row.contact_name.casefold()),
            _normalize_phone(row.phone),
        )
        if len(candidates[token]) == 1:
            keys[row.cleaned_row_number] = next(iter(candidates[token]))
    return keys


def match_source_payload(payload: SourceAuditPayload, bundle: dict, *, import_id: int = 20) -> dict:
    """Compare a frozen, bounded warehouse snapshot without database mutations."""
    index = _Index(bundle)
    grouped = defaultdict(list)
    for row in payload.rows:
        grouped[row.reference_id].append(row)
    keys = _owner_keys(payload, import_id)
    references, results = {}, {}
    source_references = {ref.reference_id: ref for ref in payload.references}
    for ref in payload.references:
        rows = grouped[ref.reference_id]
        selected: set[str] = set()
        conflicting_identifiers = False
        anchored: set[str] = set()
        kind = ref.source_key[0]
        for row in rows:
            probes = []
            if row.unit_number and unit_lookup_key(row.unit_number) not in {"", "0"}:
                probes.append((row.unit_number, row.building_name or row.project, False))
            elif kind in {"named_villa_or_building", "building_number_only"}:
                numbers = {row.building_name, row.building_number} - {"", "0"}
                conflicting_identifiers = (
                    conflicting_identifiers or len({unit_lookup_key(n) for n in numbers}) > 1
                )
                for number in numbers:
                    probes.append((number, row.project, True))
            for unit, building, project_only in probes:
                for sale in index.by_unit.get(unit_lookup_key(unit), []):
                    if index.compatible(
                        row, sale, source_building=building, project_only=project_only
                    ) and _types_compatible(row, sale, anchored=_signature(row, sale)):
                        selected.add(_identity(sale))
                        if _signature(row, sale):
                            anchored.add(_identity(sale))
            # Parcel/plot labels are not unit numbers. A unique dated amount AND
            # size anchor within the exact project can support a property link.
            if not probes and row.project:
                for sale in index.by_day.get(row.recorded_at.isoformat(), []):
                    if (
                        _signature(row, sale)
                        and index.compatible(
                            row, sale, source_building=row.project, project_only=True
                        )
                        and _types_compatible(row, sale, anchored=True)
                    ):
                        anchored.add(_identity(sale))
                        selected.add(_identity(sale))
        if len(anchored) == 1:
            selected = anchored
        status = "matched" if len(selected) == 1 else "ambiguous" if selected else "unmatched"
        if conflicting_identifiers and selected and not anchored:
            status = "ambiguous"
        reason = (
            "Unique scoped building/unit identity"
            if status == "matched"
            else "Multiple scoped transaction property identities"
            if selected
            else "No unique scoped transaction property observed"
        )
        if status == "matched" and anchored:
            reason = "Unique scoped property with dated amount and size transaction anchor"
        if conflicting_identifiers and status == "ambiguous" and not anchored:
            reason = (
                "Conflicting source building identifiers require a dated amount and size anchor"
            )
        identity = next(iter(selected)) if status == "matched" else None
        sales = (
            sorted(
                index.by_identity[identity].values(),
                key=lambda x: (x["transaction_date"], str(x["sale_key"])),
            )
            if identity
            else []
        )
        latest = sales[-1] if sales else None
        if latest and any(
            _area(r.source_values[2] if len(r.source_values) > 2 else "", r.project)
            != _area(latest.get("area_name"))
            for r in rows
        ):
            reason += "; source master area corrected through exact MAG project and dated amount/size anchor"
        if ref.disposition in _EXCLUDED:
            status, reason = "excluded", f"Reviewed source disposition: {ref.disposition}"
            identity, sales, latest = None, [], None
        reference = {
            "status": status,
            "property_key": identity,
            "latest_sale_date": latest["transaction_date"] if latest else None,
            "latest_sale_price_aed": int(latest["sale_amount_aed"]) if latest else None,
            "matched_sale_keys": [str(x["sale_key"]) for x in sales],
            "owner_category": None,
            "reason": reason,
            "resolver_version": MATCH_VERSION,
            "canonical_area_name": str(latest.get("area_name") or "") if latest else None,
            "canonical_project_name": str(latest.get("project_name") or "") if latest else None,
            "canonical_building_name": str(latest.get("building_name") or "") if latest else None,
            "canonical_unit_number": str(latest.get("unit_number") or "") if latest else None,
            "matched_at": bundle.get("captured_at"),
        }
        references[ref.reference_id] = reference
        candidate_rows = {n for group in ref.owner_candidate_groups for n in group}
        candidate_keys = {keys[n] for n in candidate_rows}
        party_rows = defaultdict(list)
        for row in rows:
            party_rows[keys[row.cleaned_row_number]].append(row)
        for key, party in party_rows.items():
            buyers = [
                r
                for r in party
                if r.party_role.casefold() == "buyer" and not is_financial_party(r.contact_name)
            ]
            acquisition = [
                sale for sale in sales if any(_signature(buyer, sale) for buyer in buyers)
            ]
            acquisition_day = max((r.recorded_at.isoformat() for r in buyers), default="")
            later_sales = (
                [s for s in sales if s["transaction_date"] > acquisition_day]
                if acquisition_day
                else []
            )
            later_buyers = (
                [
                    r
                    for r in rows
                    if r.cleaned_row_number in candidate_rows
                    and r.recorded_at.isoformat() > acquisition_day
                    and keys[r.cleaned_row_number] != key
                    and not is_financial_party(r.contact_name)
                ]
                if buyers
                and key not in candidate_keys
                and ref.disposition in CANDIDATE_DISPOSITIONS
                else []
            )
            category, party_reason = None, reason
            if ref.disposition not in _EXCLUDED and buyers:
                if later_sales and acquisition:
                    category, party_reason = (
                        "former",
                        "Named source buyer acquisition matches a transaction and a later sale is observed",
                    )
                elif key in candidate_keys and not later_sales:
                    category, party_reason = (
                        "current",
                        "Reviewed latest source buyer candidate; no later matched sale observed"
                        if status == "matched"
                        else "Reviewed latest source buyer candidate; transaction identity remains unconfirmed",
                    )
                elif later_buyers:
                    category, party_reason = (
                        "former",
                        "Workbook buyer history followed by a later reviewed buyer; named ownership is source-supported",
                    )
                elif later_sales and key in candidate_keys:
                    category, party_reason = (
                        "former",
                        "Unverified former owner: the workbook records this reviewed buyer before a later matched sale; "
                        "the buyer's acquisition is not corroborated by a matching transaction",
                    )
                elif later_sales:
                    party_reason = "Later matched sale observed, but this party's acquisition signature is not corroborated"
            for row in party:
                result = dict(reference)
                result.update(
                    owner_category=category
                    if row.party_role.casefold() == "buyer"
                    and not is_financial_party(row.contact_name)
                    else None,
                    canonical_owner_key=key,
                    source_successor_supported=bool(later_buyers),
                    acquisition_sale_keys=[str(s["sale_key"]) for s in acquisition],
                    later_sale_date=later_sales[0]["transaction_date"] if later_sales else None,
                    reason=party_reason,
                )
                results[str(row.cleaned_row_number)] = result
    # Two reviewed references must not silently collapse to one physical property.
    # Preserve explicit MAG/Fairway splits and expose duplicate canonical matches.
    inverse = defaultdict(list)
    for refid, result in references.items():
        if result["status"] == "matched":
            inverse[result["property_key"]].append(refid)
    for identity, refids in inverse.items():
        if len(refids) <= 1:
            continue
        for refid in refids:
            references[refid].update(
                status="ambiguous",
                property_key=None,
                latest_sale_date=None,
                latest_sale_price_aed=None,
                matched_sale_keys=[],
                reason="Distinct reviewed source references resolve to the same transaction property; merge requires review",
            )
            for row in grouped[refid]:
                result = results[str(row.cleaned_row_number)]
                result.update(
                    status="ambiguous",
                    property_key=None,
                    latest_sale_date=None,
                    latest_sale_price_aed=None,
                    matched_sale_keys=[],
                    acquisition_sale_keys=[],
                    later_sale_date=None,
                    canonical_area_name=None,
                    canonical_project_name=None,
                    canonical_building_name=None,
                    canonical_unit_number=None,
                    reason=references[refid]["reason"],
                )
                ref = source_references[refid]
                candidate_keys = {keys[n] for group in ref.owner_candidate_groups for n in group}
                result["owner_category"] = (
                    "current"
                    if result["canonical_owner_key"] in candidate_keys
                    and row.party_role.casefold() == "buyer"
                    and not is_financial_party(row.contact_name)
                    else "former"
                    if result.get("source_successor_supported")
                    and row.party_role.casefold() == "buyer"
                    and not is_financial_party(row.contact_name)
                    else None
                )
                if result["owner_category"] == "former":
                    result["reason"] = (
                        "Workbook buyer history followed by a later reviewed buyer; transaction identity remains ambiguous"
                    )
    statuses = Counter(r["status"] for r in references.values())
    associations = {
        (
            grouped_row.reference_id,
            keys[grouped_row.cleaned_row_number],
            results[str(grouped_row.cleaned_row_number)]["owner_category"],
        )
        for grouped_row in payload.rows
        if results[str(grouped_row.cleaned_row_number)]["owner_category"]
    }
    return {
        "resolver_version": MATCH_VERSION,
        "dataset_id": payload.dataset_id,
        "warehouse_fingerprint": bundle.get("warehouse_fingerprint"),
        "captured_at": bundle.get("captured_at"),
        "references": references,
        "rows": results,
        "summary": {
            "source_reference_count": len(references),
            "matched_reference_count": statuses["matched"],
            "matched_property_count": len(
                {r["property_key"] for r in references.values() if r["status"] == "matched"}
            ),
            "unmatched_reference_count": statuses["unmatched"],
            "ambiguous_reference_count": statuses["ambiguous"],
            "excluded_reference_count": statuses["excluded"],
            "current_association_count": sum(
                category == "current" for _, _, category in associations
            ),
            "former_association_count": sum(
                category == "former" for _, _, category in associations
            ),
            "financial_row_count": sum(is_financial_party(r.contact_name) for r in payload.rows),
        },
    }
