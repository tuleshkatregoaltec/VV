from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from functools import lru_cache
from typing import Any, Iterable

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.async_work import run_in_thread
from app.crm import import_repository, owner_queries
from app.crm.brokers import load_broker_index
from app.crm.identity import (
    ParsedContact,
    _candidate_owner_key,
    _location_key,
    _location_number_markers,
    _location_similarity,
    _location_tokens,
    _normalize_unit,
    _property_scopes_compatible,
    _recover_embedded_property_identity,
    _registry_type_compatible,
    _transaction_location_score,
    _usable_project_name,
)
from app.crm.import_context import in_file_context, prepare_file_context, recover_from_file_context
from app.crm.import_events import event_family, has_sale_evidence
from app.crm.import_models import (
    CrmContactImportSummary,
)
from app.crm.import_normalization import normalize_location, positive_decimal
from app.crm.owner_cache import _invalidate_owner_summary_cache
from app.crm.owner_match_stage import run_owner_matching
from app.crm.owner_match_status import apply_owner_match, summarize_owner_matches
from app.crm.owner_matching_policy import (
    POLICY_VERSION,
    SQM_TO_SQFT,
    LookupScopeIndex,
    OwnerMatchIndex,
    PropertyIdentityIndex,
    SheetSizeEvidence,
    lookup_scopes,
    original_identifier_support,
    qualified,
)
from app.crm.owner_namespaces import history_unit_aliases, registry_namespace
from app.crm.registry_fallback import _apply_registry_unit_fallbacks
from app.crm.registry_locations import (
    RegistryLocationIndex,
    infer_source_file_context,
    normalize_registry_locations,
)
from app.crm.source_lifecycle import annotate_source_lifecycle
from app.crm.transaction_matching import (
    amounts_match,
    exact_date_event,
    identifier,
    physical_types_conflict,
    property_identity,
    property_lookup_identifiers,
    sizes_match,
)
from app.market.reference import (
    AREA_ALIASES,
    COMMUNITY_KEYS,
    property_name_lookup_key,
    unit_lookup_key,
)

logger = logging.getLogger(__name__)

_QUERY_CHUNK = 4_000

_SALES_EVIDENCE_UNIT_CHUNK = 20_000

_TRANSACTION_SIGNATURE_CHUNK = 1_500

_EXCEL_ERROR = re.compile(
    r"#(REF!|N/A|VALUE!|NAME\?|DIV/0!|NULL!|NUM!|SPILL!|CALC!)", re.IGNORECASE
)

_STATUS_SUMMARY_FIELDS = {
    "verified_current_owner": "verified_current_owners",
    "probable_current_owner": "probable_current_owners",
    "unit_linked_unverified": "unit_linked_unverified",
    "former_owner": "former_owners",
    "unverified_former_owner": "unverified_former_owners",
    "conflicting_claim": "conflicting_claims",
    "insufficient_property_data": "insufficient_property_data",
    "registry_not_observed": "registry_not_observed",
    "unmatched": "unmatched",
}


def _chunks(values: list[str], size: int = _QUERY_CHUNK) -> Iterable[list[str]]:
    for start in range(0, len(values), size):
        yield values[start : start + size]


def _is_mortgage_procedure(candidate: ParsedContact) -> bool:
    return "mortgage" in candidate.procedure_type.casefold()


def _reuse_mortgage_property_from_sale_anchors(candidates: list[ParsedContact]) -> int:
    """Link a mortgage row only when a same-import sale resolves its exact property.

    Mortgage amounts are loan amounts, so the source sale amount is not compared. Unit,
    date, area, and project must match, and all matching sale anchors must identify one sale.
    """
    anchors_by_source: dict[
        tuple[date, str, str, str],
        list[tuple[tuple[str, str, str, str], ParsedContact, dict[str, Any]]],
    ] = {}
    exact_sale_methods = {
        "unique_transaction_signature",
        "unique_transaction_unit_signature",
        "transaction_signature_with_master_project_area",
        "transaction_signature_with_location",
    }
    for anchor in candidates:
        if (
            not has_sale_evidence(anchor)
            or not anchor.transaction_date
            or not anchor.transaction_price_aed
        ):
            continue
        resolution = anchor.evidence.get("property_identity_resolution") or {}
        if resolution.get("method") not in exact_sale_methods:
            continue
        source = resolution.get("source") or {}
        resolved = resolution.get("resolved") or {}
        unit = _normalize_unit(source.get("unit_number") or anchor.unit_number)
        area = _location_key(_usable_project_name(str(source.get("area_name") or "")))
        project = _location_key(_usable_project_name(str(source.get("project_name") or "")))
        resolved_unit = _normalize_unit(resolved.get("unit_number"))
        resolved_area = _location_key(str(resolved.get("area_name") or ""))
        resolved_building = _location_key(
            str(resolved.get("building_name") or resolved.get("project_name") or "")
        )
        sale_key = str(resolved.get("sale_key") or "")
        if not all(
            (unit, area, project, resolved_unit, resolved_area, resolved_building, sale_key)
        ):
            continue
        if unit != resolved_unit:
            continue
        source_key = (anchor.transaction_date, unit, area, project)
        property_key = (resolved_area, resolved_building, resolved_unit, sale_key)
        anchors_by_source.setdefault(source_key, []).append((property_key, anchor, source))

    resolved_count = 0
    for candidate in candidates:
        if (
            not _is_mortgage_procedure(candidate)
            or not candidate.transaction_date
            or candidate.evidence.get("property_identity_resolution")
        ):
            continue
        unit = _normalize_unit(candidate.unit_number)
        area = _location_key(_usable_project_name(candidate.area_name))
        project = _location_key(_usable_project_name(candidate.project_name))
        if not all((unit, area, project)):
            continue
        source_key = (candidate.transaction_date, unit, area, project)
        matching = []
        candidate_building = _location_key(_usable_project_name(candidate.building_name))
        for property_key, anchor, anchor_source in anchors_by_source.get(source_key, []):
            anchor_building = _location_key(
                _usable_project_name(str(anchor_source.get("building_name") or ""))
            )
            if candidate_building and anchor_building and candidate_building != anchor_building:
                continue
            matching.append((property_key, anchor))
        if not matching or len({item[0] for item in matching}) != 1:
            continue

        anchor = matching[0][1]
        resolution = anchor.evidence["property_identity_resolution"]
        source = resolution["source"]
        resolved = resolution["resolved"]
        original_location = {
            "area_name": candidate.area_name,
            "project_name": candidate.project_name,
            "building_name": candidate.building_name,
            "unit_number": candidate.unit_number,
        }
        candidate.area_name = str(resolved.get("area_name") or candidate.area_name)
        candidate.project_name = str(resolved.get("project_name") or candidate.project_name)
        candidate.building_name = str(
            resolved.get("building_name") or resolved.get("project_name") or ""
        )
        candidate.unit_number = _normalize_unit(resolved.get("unit_number"))
        candidate.evidence["mortgage_property_resolution"] = {
            "method": "same_import_exact_sale_anchor",
            "anchor_source_sheet": anchor.source_sheet,
            "anchor_source_row": anchor.source_row_number,
            "anchor_sale_key": str(resolved.get("sale_key") or ""),
            "anchor_sale_price_aed": anchor.transaction_price_aed,
            "source": original_location,
            "anchor_source": source,
        }
        resolved_count += 1

    if resolved_count:
        logger.info("Mortgage properties linked from same-import sale anchors: %s", resolved_count)
    return resolved_count


def _unique_unit_on_signature(
    candidate: ParsedContact,
    properties: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Fallback for a date+price signature the location rules rejected or could not decide.

    Only one of the sales on that exact date and price may carry the row's unit, and the row's
    location has to fit that sale without contradicting it: at least one of its building,
    project or area must match the sale (score >= 55, or one name's words contained in the
    other's, e.g. "GR Panorama" and "Panorama"), and building numbers must not differ
    ("Tower 1" never matches "Tower 2"). Excel error values such as #REF! are not locations.
    A row with no location at all is decided by the unit.
    """
    unit = _normalize_unit(candidate.unit_number)
    if not unit:
        return None
    matches = [row for row in properties if _normalize_unit(row.get("unit_number")) == unit]
    if len(matches) != 1:
        return None
    sale = matches[0]
    owner_locations = [
        value
        for value in (
            _fallback_location(candidate.building_name),
            _fallback_location(candidate.project_name),
            _fallback_location(candidate.area_name),
        )
        if value
    ]
    if not owner_locations:
        return sale
    sale_building = str(sale.get("building_name") or "")
    sale_locations = [
        value
        for value in (
            sale_building,
            str(sale.get("project_name") or ""),
            str(sale.get("area_name") or ""),
        )
        if value
    ]
    owner_numbers = _location_number_markers(_fallback_location(candidate.building_name))
    sale_numbers = _location_number_markers(sale_building)
    if owner_numbers and sale_numbers and owner_numbers != sale_numbers:
        return None
    fits = any(
        _location_fits(owner, observed) for owner in owner_locations for observed in sale_locations
    )
    return sale if fits else None


def _fallback_location(value: str) -> str:
    location = _usable_project_name(value)
    return "" if _EXCEL_ERROR.fullmatch(location) else location


def _location_fits(owner: str, observed: str) -> bool:
    if _location_similarity(owner, observed) >= 55:
        return True
    owner_tokens = frozenset(_location_tokens(owner))
    observed_tokens = frozenset(_location_tokens(observed))
    return bool(owner_tokens and observed_tokens) and (
        owner_tokens <= observed_tokens or observed_tokens <= owner_tokens
    )


def _unique_property_in_master_project_area(
    candidate: ParsedContact,
    properties: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Ignore a long registry number appended to a master-project area label."""
    if candidate.evidence.get("source_area_field") != "master_project":
        return None
    source_area = _fallback_location(candidate.area_name)
    if not re.search(r"\b\d{3,}$", source_area):
        return None
    source_tokens = {token for token in _location_tokens(source_area) if not token.isdigit()}
    if len(source_tokens) < 2:
        return None

    matches = [
        row
        for row in properties
        if {
            token
            for token in _location_tokens(str(row.get("area_name") or ""))
            if not token.isdigit()
        }
        == source_tokens
    ]
    return matches[0] if len(matches) == 1 else None


def _amount_match_source(candidate: ParsedContact) -> dict[str, Any]:
    fields = candidate.evidence.get("source_fields", {})
    original = candidate.evidence.get("original_property_fields") or {}
    source = {
        field: fields[field]
        if field in fields
        else original.get(field, getattr(candidate, field, ""))
        for field in ("area_name", "project_name", "building_name", "unit_number", "property_type")
    }
    # Parsing already recognizes explicit embedded villa IDs and tower prefixes.
    # Reuse that recorded transformation while retaining the original raw fields
    # for rematching; a registry-selected label is never its own source evidence.
    address = candidate.evidence.get("address_recovery", {})
    if address.get("method") in {
        "embedded_villa_identifier",
        "embedded_numeric_identifier",
        "project_unit_prefix_tower",
    }:
        source["building_name"] = address.get("resolved_building_name") or source["building_name"]
        source["unit_number"] = address.get("resolved_unit_number") or source["unit_number"]
    source["unit_number"] = _normalize_unit(source["unit_number"])
    source.update(candidate.evidence.get("source_identifiers", {}))
    source.update(
        {
            key: fields[key]
            for key in ("building_number", "property_number", "plot_number")
            if fields.get(key)
        }
    )
    # Raw source consideration survives the legacy BIGINT persistence model.
    # Never use the rounded display/persisted amount for matching when available.
    source["amount_aed"] = fields.get("transaction_price_aed") or candidate.transaction_price_aed
    source["event_family"] = (
        "sale" if has_sale_evidence(candidate) else event_family(candidate.procedure_type)
    )
    if source["event_family"] == "rental":
        source["amount_basis"] = "contract_amount_aed"
    source["transaction_date"] = candidate.transaction_date
    source["size_sqft"] = _source_size_decimal(candidate)
    source["source_area_field"] = candidate.evidence.get("source_area_field")
    inferred = candidate.evidence.get("inferred_file_context", {}).get("resolved_fields", {})
    for field in ("building_name", "project_name", "area_name"):
        if not source[field] and inferred.get(field):
            source[field] = inferred[field]
    source["source_filename"] = candidate.evidence.get("source_filename")
    source["source_file_scope"] = (
        candidate.evidence.get("source_file_sha256")
        or candidate.evidence.get("source_import_scope")
        or source["source_filename"]
    )
    source["source_sheet"] = candidate.source_sheet
    source["size_unknown"] = fields.get("size_unknown")
    if "original_identifiers" in candidate.evidence:
        source["original_identifiers"] = candidate.evidence["original_identifiers"]
    elif any(
        fields.get(key)
        for key in ("unit_number", "building_number", "property_number", "plot_number")
    ):
        source["original_identifiers"] = {
            key: fields.get(key, "")
            for key in (
                "unit_number",
                "building_number",
                "property_number",
                "plot_number",
                "plot_pre_reg_number",
            )
        }
    source["raw_location_fields"] = {
        field: fields.get(field) or "" for field in ("building_name", "project_name", "area_name")
    }
    aligned = candidate.evidence.get("source_registry_location_resolution", {})
    for field in ("building_name", "project_name", "area_name"):
        if field in aligned.get("resolved_fields", {}) and source.get(field) == aligned.get(
            "raw_fields", {}
        ).get(field):
            source[field] = aligned["resolved_fields"][field]
    if aligned:
        source["registry_location_resolution"] = aligned
    return source


async def _recover_amount_first_properties(
    candidates: list[ParsedContact],
    *,
    near_entry: bool = False,
    lookup_catalog: LookupScopeIndex | None = None,
) -> dict[str, int]:
    eligible = [
        candidate
        for candidate in candidates
        if (
            has_sale_evidence(candidate)
            or event_family(candidate.procedure_type) in {"rental", "unknown", "contact_snapshot"}
        )
        and positive_decimal(_amount_match_source(candidate)["amount_aed"]) is not None
        and "amount_first_match" not in candidate.evidence
    ]
    counts = {
        "eligible": len(eligible),
        "unique": 0,
        "contextual": 0,
        "unit": 0,
        "master_project_area": 0,
        "ambiguous": 0,
        "resolved": 0,
    }
    # Learn units across the whole sheet before selecting any transaction. The
    # first pass uses IDs/location/date only; repeated parties cannot add votes.
    size_evidence = SheetSizeEvidence()
    if eligible and lookup_catalog is None:
        lookup_catalog = LookupScopeIndex(await owner_queries.fetch_registry_places())
    batches = []
    cached = None
    for start in range(0, len(eligible), _TRANSACTION_SIGNATURE_CHUNK):
        batch = eligible[start : start + _TRANSACTION_SIGNATURE_CHUNK]
        parameters = {
            "prices": sorted(
                {
                    str(positive_decimal(_amount_match_source(candidate)["amount_aed"]))
                    for candidate in batch
                }
            )
        }
        if any("original_identifiers" in candidate.evidence for candidate in batch):
            parameters["scopes"] = sorted(
                {
                    scope
                    for candidate in batch
                    for scope in lookup_scopes(_amount_match_source(candidate), lookup_catalog)
                }
            )
        rows = await owner_queries.fetch_transaction_signatures(parameters)
        index = OwnerMatchIndex(rows)
        batches.append((batch, parameters))
        cached = (parameters, rows, index)
        for candidate in batch:
            source = _amount_match_source(candidate)
            size_evidence.observe(source, index.candidates(source))
    for batch, parameters in batches:
        if cached is not None and cached[0] == parameters:
            _, rows, index = cached
        else:
            rows = await owner_queries.fetch_transaction_signatures(parameters)
            index = OwnerMatchIndex(rows)
        for candidate in batch:
            source = _amount_match_source(candidate)
            inferred_size = (
                size_evidence.infer(source)
                if positive_decimal(source.get("size_unknown"))
                else None
            )
            candidate.evidence.pop("inferred_size_unit", None)
            if inferred_size:
                candidate.evidence["inferred_size_unit"] = inferred_size
                source["size_sqft"] = positive_decimal(source["size_unknown"]) * (
                    SQM_TO_SQFT if inferred_size["unit"] == "sqm" else Decimal(1)
                )
            result = index.match(source)
            candidate.evidence["amount_first_match"] = {
                **result.evidence,
                "status": result.status,
                "property_identity": list(result.property_identity)
                if result.property_identity
                else None,
                "exact_transaction": result.exact_transaction,
                "flags": list(result.flags),
                "size_unit_evidence": inferred_size,
            }
            if result.status != "matched":
                counts["ambiguous"] += result.candidate_event_count > 0
                continue
            # Property-only resolution is useful even when duplicate/competing
            # registrations prevent identifying a unique transaction.
            selected = result.event or next(
                row for row in rows if property_identity(row) == result.property_identity
            )
            score = _transaction_location_score(candidate, selected)
            if near_entry:
                method = "near_transaction_signature_with_location"
            elif result.candidate_event_count == 1 and score >= 55:
                method = "unique_transaction_signature"
                counts["unique"] += 1
            elif score >= 55:
                method = "transaction_signature_with_location"
                counts["contextual"] += 1
            elif candidate.evidence.get("source_area_field") == "master_project":
                method = "transaction_signature_with_master_project_area"
                counts["master_project_area"] += 1
            else:
                method = "unique_transaction_unit_signature"
                counts["unit"] += 1
            source_identity = {
                key: getattr(candidate, key)
                for key in ("area_name", "project_name", "building_name", "unit_number")
            }
            candidate.area_name = str(selected.get("area_name") or candidate.area_name)
            candidate.project_name = str(selected.get("project_name") or candidate.project_name)
            candidate.building_name = str(
                selected.get("building_name") or selected.get("project_name") or ""
            )
            candidate.unit_number = _normalize_unit(selected.get("unit_number"))
            candidate.evidence["property_identity_resolution"] = {
                "method": method,
                "matcher_version": result.evidence["version"],
                "score": score,
                "date_delta_days": result.evidence.get("date_delta_days"),
                "transaction_candidate_count": result.candidate_event_count,
                "exact_transaction": result.exact_transaction,
                "flags": list(result.flags),
                "event_family": result.evidence.get("event_family"),
                "registry_location_resolution": selected.get("registry_location_resolution"),
                "source": source_identity,
                "resolved": {
                    **{key: getattr(candidate, key) for key in source_identity},
                    "sale_key": str(selected.get("sale_key") or "") if result.event else "",
                    "transaction_date": str(selected.get("transaction_date") or "")
                    if result.event
                    else "",
                },
            }
            counts["resolved"] += 1
    return counts


async def _recover_property_identity_from_transaction(
    candidates: list[ParsedContact],
) -> dict[str, int]:
    """Resolve property identity from all-date, complete Decimal amount bands."""
    for candidate in candidates:
        candidate.evidence["owner_match_policy"] = POLICY_VERSION
        source = _amount_match_source(candidate)
        if "original_identifiers" in source:
            candidate.evidence["original_identifiers"] = source["original_identifiers"]
        previous = candidate.evidence.get("property_identity_resolution", {}).get("source", {})
        for field in ("area_name", "project_name", "building_name", "unit_number"):
            if field in previous:
                setattr(candidate, field, str(previous[field] or ""))
        previous_area = (
            candidate.evidence.get("source_registry_location_resolution", {})
            .get("area_alignment", {})
            .get("source_area")
        )
        if previous_area:
            candidate.area_name = str(previous_area)
        prior_file = candidate.evidence.pop("inferred_file_context", {})
        for field, value in prior_file.get("raw_fields", {}).items():
            if field in {"area_name", "project_name", "building_name"}:
                setattr(candidate, field, str(value or ""))
    file_candidates = [
        candidate
        for candidate in candidates
        if candidate.evidence.get("source_filename")
        and event_family(candidate.procedure_type)
        in {"sale", "rental", "unknown", "contact_snapshot"}
        and not candidate.evidence.get("source_fields", {}).get("building_name")
        and not candidate.evidence.get("source_fields", {}).get("project_name")
    ]
    named_candidates = [
        candidate
        for candidate in candidates
        if candidate.evidence.get("source_fields")
        and (
            _amount_match_source(candidate).get("building_name")
            or _amount_match_source(candidate).get("project_name")
        )
    ]
    for candidate in candidates:
        candidate.evidence.pop("source_registry_location_resolution", None)
    places = (
        await owner_queries.fetch_registry_places() if file_candidates or named_candidates else []
    )
    catalog = RegistryLocationIndex(places) if file_candidates or named_candidates else None
    lookup_catalog = LookupScopeIndex(places)
    if file_candidates:
        assert catalog is not None
        for candidate in file_candidates:
            contextual = infer_source_file_context(_amount_match_source(candidate), catalog)
            if contextual.get("inferred_file_context"):
                for field in ("building_name", "project_name", "area_name"):
                    setattr(candidate, field, str(contextual.get(field) or ""))
                candidate.evidence["inferred_file_context"] = contextual["inferred_file_context"]
    if catalog is not None:
        for candidate in candidates:
            normalized = normalize_registry_locations(_amount_match_source(candidate), catalog)
            if normalized.get("registry_location_resolution", {}).get(
                "area_alignment"
            ) or normalized.get("registry_location_resolution", {}).get("project_alignment"):
                candidate.evidence["source_registry_location_resolution"] = normalized[
                    "registry_location_resolution"
                ]
                for field in ("building_name", "project_name", "area_name"):
                    setattr(candidate, field, str(normalized.get(field) or ""))
    for candidate in candidates:
        candidate.evidence.pop("amount_first_match", None)
        candidate.evidence.pop("property_identity_resolution", None)
        candidate.evidence.pop("property_identity_match", None)
    counts = await _recover_amount_first_properties(candidates, lookup_catalog=lookup_catalog)
    unresolved = [
        candidate
        for candidate in candidates
        if "property_identity_resolution" not in candidate.evidence
        and property_lookup_identifiers(_amount_match_source(candidate))
    ]
    counts["property_only"] = 0
    for start in range(0, len(unresolved), _TRANSACTION_SIGNATURE_CHUNK):
        batch = unresolved[start : start + _TRANSACTION_SIGNATURE_CHUNK]
        identifiers = sorted(
            {
                value
                for candidate in batch
                for value in property_lookup_identifiers(_amount_match_source(candidate))
            }
        )
        rows = await owner_queries.fetch_property_identity_candidates(
            {
                "identifiers": identifiers,
                "scopes": sorted(
                    {
                        scope
                        for candidate in batch
                        for scope in lookup_scopes(_amount_match_source(candidate), lookup_catalog)
                    }
                ),
            }
        )
        index = PropertyIdentityIndex(rows)
        for candidate in batch:
            source = _amount_match_source(candidate)
            result = index.match(source)
            candidate.evidence["property_identity_match"] = {
                **result.evidence,
                "status": result.status,
                "flags": list(result.flags),
                "property_identity": list(result.property_identity)
                if result.property_identity
                else None,
            }
            if result.status != "matched":
                continue
            selected = next(
                row
                for row in index.candidates(source)
                if property_identity(row) == result.property_identity
            )
            source_identity = {
                key: getattr(candidate, key)
                for key in ("area_name", "project_name", "building_name", "unit_number")
            }
            candidate.area_name = str(selected.get("area_name") or candidate.area_name)
            candidate.project_name = str(selected.get("project_name") or candidate.project_name)
            candidate.building_name = str(selected.get("building_name") or "")
            candidate.unit_number = _normalize_unit(selected.get("unit_number"))
            candidate.evidence["property_identity_resolution"] = {
                "method": "exact_scoped_property_identity",
                "source": source_identity,
                "exact_transaction": False,
                "flags": list(result.flags),
                "resolved": {key: getattr(candidate, key) for key in source_identity},
            }
            counts["property_only"] += 1
    return counts


async def _recover_property_identity_from_near_transaction(
    candidates: list[ParsedContact], *, window_days: int = 14
) -> dict[str, int]:
    """Compatibility entry point; date proximity no longer filters property identity."""
    return await _recover_amount_first_properties(candidates, near_entry=True)


def _canonical_source_location(candidate: ParsedContact) -> dict[str, Any]:
    # Imported source fields survive transaction recovery. Recovered geography
    # cannot serve as independent evidence for a second property lookup.
    source = dict(
        candidate.evidence.get("source_fields")
        or candidate.evidence.get("property_identity_resolution", {}).get("source")
        or {
            "area_name": candidate.area_name,
            "project_name": candidate.project_name,
            "building_name": candidate.building_name,
        }
    )
    if not _usable_project_name(str(source.get("area_name") or "")):
        master = _usable_project_name(str(source.get("master_project") or ""))
        if master:
            source["area_name"] = master
    return source


@lru_cache(maxsize=2048)
def _area_scope_keys(area: str) -> frozenset[str]:
    canonical = normalize_location(area, area=True)
    equivalent = {area, canonical}
    equivalent.update(
        alias for alias in AREA_ALIASES if normalize_location(alias, area=True) == canonical
    )
    for community, aliases in COMMUNITY_KEYS.items():
        if normalize_location(community, area=True) == canonical:
            equivalent.update(aliases)
    return frozenset(property_name_lookup_key(value) for value in equivalent if value)


def _canonical_alias_id(
    candidate: ParsedContact,
    row: dict[str, Any],
    aliases: dict[tuple[str, str, str], set[str]],
) -> str:
    source = _canonical_source_location(candidate)
    source_area = property_name_lookup_key(str(source.get("area_name") or ""))
    row_area = property_name_lookup_key(str(row.get("area_name") or ""))
    if not source_area or normalize_location(
        str(source.get("area_name") or ""), area=True
    ) != normalize_location(str(row.get("area_name") or ""), area=True):
        return ""
    source_project = property_name_lookup_key(str(source.get("project_name") or ""))
    row_project = property_name_lookup_key(str(row.get("project_name") or ""))
    if source_project and row_project and source_project != row_project:
        return ""

    def resolve(name: str, area: str, project: str) -> str:
        name_key = property_name_lookup_key(name)
        # Both original area keys and documented equivalent aliases must agree.
        observed: set[str] = set()
        for area_key in (
            _area_scope_keys(str(source.get("area_name") or ""))
            | _area_scope_keys(str(row.get("area_name") or ""))
            | {area}
        ):
            observed.update(aliases.get((name_key, area_key, ""), set()))
            if project:
                observed.update(aliases.get((name_key, area_key, project), set()))
                scoped_area = f"{area_key}/{project}"
                observed.update(aliases.get((name_key, scoped_area, ""), set()))
                observed.update(aliases.get((name_key, scoped_area, project), set()))
        return next(iter(observed)) if len(observed) == 1 else ""

    source_id = resolve(str(source.get("building_name") or ""), source_area, source_project)
    row_id = resolve(str(row.get("building_name") or ""), row_area, row_project)
    return source_id if source_id and source_id == row_id else ""


async def _sales_evidence(
    candidates: list[ParsedContact],
) -> dict[str, list[dict[str, Any]]]:
    """Find DXBI sales history through a canonical project/building hierarchy."""
    for candidate in candidates:
        candidate.evidence.pop("scoped_identity_collision", None)
        candidate.evidence.pop("registry_property_scope", None)
        candidate.evidence["sales_lookup"] = {"status": "not_resolved"}
    unit_keys = sorted(
        {
            unit
            for candidate in candidates
            if candidate.property_key and candidate.unit_number
            for unit in history_unit_aliases({**vars(candidate), "property_type": "Villa"})
        }
    )
    evidence: dict[str, list[dict[str, Any]]] = {}
    sales_by_unit: dict[str, list[dict[str, Any]]] = {}
    history_scopes = sorted(
        {scope for candidate in candidates for scope in lookup_scopes(vars(candidate))}
    )
    for chunk in _chunks(unit_keys, size=_SALES_EVIDENCE_UNIT_CHUNK):
        parameters = {"unit_keys": chunk}
        if any(
            candidate.evidence.get("owner_match_policy") == POLICY_VERSION
            for candidate in candidates
        ):
            parameters["scopes"] = history_scopes
        rows = await owner_queries.fetch_unit_sales(parameters)
        for row in rows:
            for unit in history_unit_aliases(row):
                sales_by_unit.setdefault(unit, []).append(row)

    aliases: dict[tuple[str, str, str], set[str]] = {}
    source_locations = [_canonical_source_location(candidate) for candidate in candidates]
    locations = [*source_locations, *(row for rows in sales_by_unit.values() for row in rows)]
    name_keys = sorted(
        {property_name_lookup_key(str(row.get("building_name") or "")) for row in locations} - {""}
    )
    community_keys = set()
    for row in source_locations:
        area = property_name_lookup_key(str(row.get("area_name") or ""))
        project = property_name_lookup_key(str(row.get("project_name") or ""))
        if area:
            for area_key in _area_scope_keys(str(row.get("area_name") or "")):
                community_keys.add(area_key)
                if project:
                    community_keys.add(f"{area_key}/{project}")
    if name_keys and community_keys and sales_by_unit:
        for chunk in _chunks(name_keys):
            rows = await owner_queries.fetch_canonical_building_keys(
                {"name_keys": chunk, "community_keys": sorted(community_keys)}
            )
            for row in rows:
                if (
                    not row.get("name_key")
                    or not row.get("community_key")
                    or not row.get("building_id")
                ):
                    continue
                key = (
                    str(row["name_key"]),
                    str(row["community_key"]),
                    str(row.get("project_key") or ""),
                )
                aliases.setdefault(key, set()).add(str(row["building_id"]))

    properties_by_unit: dict[
        str,
        list[tuple[tuple[str, str, str], list[dict[str, Any]]]],
    ] = {}
    for unit_key, unit_rows in sales_by_unit.items():
        grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
        for row in unit_rows:
            building_key = str(row.get("building_key") or "") or _location_key(
                str(row.get("building_name") or row.get("project_name") or "")
            )
            namespace = registry_namespace(row)
            identity = namespace or (
                str(row.get("area_key") or ""),
                building_key,
                unit_lookup_key(str(row.get("unit_number") or row.get("unit_key") or "")),
            )
            grouped.setdefault(identity, []).append(row)
        properties_by_unit[unit_key] = list(grouped.items())

    resolution_cache: dict[
        tuple,
        tuple[int, str, list[dict[str, Any]], int] | None,
    ] = {}
    for candidate in candidates:
        source_property_key = candidate.property_key
        if not source_property_key or not candidate.unit_number:
            continue
        rows_for_unit = sales_by_unit.get(unit_lookup_key(candidate.unit_number), [])
        if not rows_for_unit:
            candidate.evidence["sales_lookup"] = {
                "status": "unit_not_observed",
                "normalized_unit_number": unit_lookup_key(candidate.unit_number),
            }
            continue

        cache_key = (
            _location_key(candidate.area_name),
            _location_key(candidate.project_name),
            _location_key(candidate.building_name),
            unit_lookup_key(candidate.unit_number),
            tuple(
                str(_canonical_source_location(candidate).get(field) or "")
                for field in ("area_name", "project_name", "building_name")
            ),
            str(
                candidate.evidence.get("source_fields", {}).get("property_type")
                or candidate.property_type
            ),
            tuple(candidate.evidence.get("file_context", {}).get("locations", [])),
            candidate.evidence.get("property_identity_resolution", {})
            .get("resolved", {})
            .get("sale_key"),
        )
        if cache_key in resolution_cache:
            cached = resolution_cache[cache_key]
            if cached is None:
                continue
            best_score, method, selected_rows, registry_candidate_count = cached
        else:
            identified_sale = (
                candidate.evidence.get("property_identity_resolution", {})
                .get("resolved", {})
                .get("sale_key")
            )
            accepted_sale = bool(
                candidate.evidence.get("owner_match_policy") == POLICY_VERSION
                and identified_sale
                and candidate.evidence.get("amount_first_match", {}).get("status") == "matched"
                and candidate.evidence.get("amount_first_match", {}).get("selected_event_key")
                == f"sale:{identified_sale}"
            )
            scoped_properties: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
            for identity, property_rows in properties_by_unit[
                unit_lookup_key(candidate.unit_number)
            ]:
                for row in property_rows:
                    if not _registry_type_compatible(candidate, row):
                        continue
                    source = _amount_match_source(candidate)
                    if candidate.evidence.get(
                        "owner_match_policy"
                    ) == POLICY_VERSION and not qualified(source, row):
                        continue
                    alias_id = _canonical_alias_id(candidate, row, aliases)
                    scoped_identity = (
                        (identity[0], f"analytics:{alias_id}", identity[2])
                        if alias_id
                        else identity
                    )
                    scoped_properties.setdefault(scoped_identity, []).append(row)
            ranked = sorted(
                (
                    (
                        100
                        if identity[1].startswith("analytics:")
                        else _transaction_location_score(candidate, property_rows[0]),
                        identity,
                        property_rows,
                    )
                    for identity, property_rows in scoped_properties.items()
                    if (accepted_sale or in_file_context(candidate, property_rows[0]))
                    and (
                        not identified_sale
                        or any(row.get("sale_key") == identified_sale for row in property_rows)
                    )
                ),
                key=lambda item: item[0],
                reverse=True,
            )
            if not ranked:
                candidate.evidence["sales_lookup"] = {"status": "location_not_observed"}
                resolution_cache[cache_key] = None
                continue
            best_score, _, selected_rows = ranked[0]
            runner_up = ranked[1][0] if len(ranked) > 1 else 0
            lookup_unit = unit_lookup_key(candidate.unit_number)
            distinctive_unit = len(lookup_unit) >= 5 and any(
                character.isalpha() for character in lookup_unit
            )
            unique_distinctive_unit = distinctive_unit and len(ranked) == 1
            if not unique_distinctive_unit and (
                best_score < 55 or (len(ranked) > 1 and best_score - runner_up < 12)
            ):
                candidate.evidence["sales_lookup"] = {
                    "status": "ambiguous_location",
                    "registry_property_candidates": len(ranked),
                    "best_location_score": best_score,
                    "runner_up_location_score": runner_up,
                }
                resolution_cache[cache_key] = None
                continue

            method = (
                "canonical_building_alias_with_unit"
                if _canonical_alias_id(candidate, selected_rows[0], aliases)
                else "unique_registry_unit_identifier"
                if unique_distinctive_unit
                else "unit_with_location_hierarchy"
            )
            registry_candidate_count = len(ranked)
            resolution_cache[cache_key] = (
                best_score,
                method,
                selected_rows,
                registry_candidate_count,
            )

        canonical = selected_rows[0]
        candidate.evidence["registry_property_scope"] = {
            field: str(canonical.get(field) or "")
            for field in ("area_name", "project_name", "building_name", "unit_number")
        }
        all_property_rows = list(selected_rows)
        selected_sale_keys = {str(row.get("sale_key") or "") for row in selected_rows}
        for _, sibling_rows in properties_by_unit[unit_lookup_key(candidate.unit_number)]:
            sibling = sibling_rows[0]
            if not _registry_type_compatible(candidate, sibling):
                continue
            if method == "canonical_building_alias_with_unit" and not _canonical_alias_id(
                candidate, sibling, aliases
            ):
                continue
            if not _same_registry_property_alias(canonical, sibling):
                continue
            for row in sibling_rows:
                sale_key = str(row.get("sale_key") or "")
                if sale_key and sale_key not in selected_sale_keys:
                    selected_sale_keys.add(sale_key)
                    all_property_rows.append(row)
        all_property_rows.sort(key=lambda row: row["transaction_date"])
        candidate.evidence.pop("sales_lookup", None)
        source_identity = {
            "area_name": candidate.area_name,
            "project_name": candidate.project_name,
            "building_name": candidate.building_name,
            "unit_number": candidate.unit_number,
        }
        candidate.area_name = str(canonical.get("area_name") or candidate.area_name)
        candidate.project_name = str(canonical.get("project_name") or candidate.project_name)
        candidate.building_name = str(
            canonical.get("building_name") or canonical.get("project_name") or ""
        )
        candidate.unit_number = _normalize_unit(canonical.get("unit_number"))
        if candidate.property_key != source_property_key:
            candidate.evidence["unit_hierarchy_resolution"] = {
                "method": method,
                "score": best_score,
                "registry_property_candidates": registry_candidate_count,
                "source": source_identity,
                "resolved": {
                    "area_name": candidate.area_name,
                    "project_name": candidate.project_name,
                    "building_name": candidate.building_name,
                    "unit_number": candidate.unit_number,
                },
            }

        selected: list[dict[str, Any]] = []
        seen_sale_keys: set[str] = set()
        for row in all_property_rows:
            sale_key = str(row.get("sale_key") or "")
            if sale_key in seen_sale_keys:
                continue
            seen_sale_keys.add(sale_key)
            selected.append({**row, "_match_method": method})
        evidence[candidate.property_key] = selected
    # Persisted keys predate area scoping. Do not let two independently resolved
    # locations sharing a display name/unit overwrite each other's ownership.
    by_key: dict[str, list[ParsedContact]] = {}
    for candidate in candidates:
        if candidate.property_key:
            by_key.setdefault(candidate.property_key, []).append(candidate)
    for key, group in by_key.items():
        scopes = {
            tuple(row.evidence["registry_property_scope"].items())
            for row in group
            if row.evidence.get("registry_property_scope")
        }
        resolved_scopes = [dict(scope) for scope in scopes]
        if any(
            unit_lookup_key(left["unit_number"]) != unit_lookup_key(right["unit_number"])
            or not _property_scopes_compatible(left, right)
            for index, left in enumerate(resolved_scopes)
            for right in resolved_scopes[index + 1 :]
        ):
            evidence[key] = []
            for candidate in group:
                candidate.evidence["scoped_identity_collision"] = True
    return evidence


def _same_registry_property_alias(left: dict[str, Any], right: dict[str, Any]) -> bool:
    """Recognize a building-key variant only with matching location and unit facts."""
    left_namespace, right_namespace = registry_namespace(left), registry_namespace(right)
    if left_namespace or right_namespace:
        return bool(left_namespace and left_namespace == right_namespace)
    left_unit = str(left.get("unit_key") or _normalize_unit(left.get("unit_number"))).lower()
    right_unit = str(right.get("unit_key") or _normalize_unit(right.get("unit_number"))).lower()
    left_area = str(left.get("area_key") or _location_key(str(left.get("area_name") or "")))
    right_area = str(right.get("area_key") or _location_key(str(right.get("area_name") or "")))
    left_building = set(_location_tokens(str(left.get("building_name") or "")))
    right_building = set(_location_tokens(str(right.get("building_name") or "")))
    left_type = _location_key(str(left.get("property_type") or ""))
    right_type = _location_key(str(right.get("property_type") or ""))
    try:
        same_size = abs(float(left.get("size_sqft")) - float(right.get("size_sqft"))) <= 1
    except (TypeError, ValueError):
        same_size = False

    left_bedrooms = _location_key(str(left.get("bedrooms") or ""))
    right_bedrooms = _location_key(str(right.get("bedrooms") or ""))
    return bool(
        left_unit
        and left_unit == right_unit
        and left_area
        and left_area == right_area
        and left_building
        and right_building
        and left_building != right_building
        and (left_building < right_building or right_building < left_building)
        and left_type
        and left_type == right_type
        and same_size
        and (not left_bedrooms or not right_bedrooms or left_bedrooms == right_bedrooms)
    )


async def _rental_evidence(
    candidates: list[ParsedContact],
) -> dict[str, dict[str, Any]]:
    units = sorted({candidate.unit_number for candidate in candidates if candidate.unit_number})
    return await _rental_evidence_for_units(units)


async def _rental_evidence_for_units(units: list[str]) -> dict[str, dict[str, Any]]:
    evidence: dict[str, dict[str, Any]] = {}
    scopes: dict[str, set[tuple[str, str, str]]] = {}
    units = sorted({_normalize_unit(unit) for unit in units if _normalize_unit(unit)})
    if not units:
        return evidence
    columns = await owner_queries.fetch_rental_source_columns()
    has_source_unit = bool(columns[0]["has_unit"])
    anchor = date.today()
    for chunk in _chunks(units):
        rows = await owner_queries.fetch_rental_evidence(
            {
                "units": chunk,
                "window_start": (anchor - timedelta(days=365)).isoformat(),
                "window_end": (anchor + timedelta(days=90)).isoformat(),
            },
            has_source_unit,
        )
        for row in rows:
            location = str(row.get("building_name") or row.get("project_name") or "")
            key = f"{_location_key(location)}|{_normalize_unit(row['unit_number']).lower()}"
            scopes.setdefault(key, set()).add(
                (
                    str(row.get("area_name") or ""),
                    str(row.get("project_name") or ""),
                    unit_lookup_key(str(row["unit_number"])),
                )
            )
            evidence.setdefault(key, row)
    # A display building/unit key is not globally unique. A lease from another
    # community must never give a verified owner the wrong renewal opportunity.
    for key, pairs in scopes.items():
        locations = [
            dict(zip(("area_name", "project_name", "unit_key"), pair, strict=True))
            for pair in pairs
        ]
        if any(
            left["unit_key"] != right["unit_key"] or not _property_scopes_compatible(left, right)
            for index, left in enumerate(locations)
            for right in locations[index + 1 :]
        ):
            evidence.pop(key, None)
    return evidence


def _rental_scope_compatible(candidate: Any, rental: dict[str, Any]) -> bool:
    """A shared display key alone cannot establish the lease's property scope."""
    scope = (candidate.evidence or {}).get("registry_property_scope") or {
        field: getattr(candidate, field, "") for field in ("area_name", "project_name")
    }
    return _property_scopes_compatible(scope, rental)


async def refresh_property_contact_rentals(
    db: AsyncSession,
    *,
    organization_id: str,
    import_id: int | None = None,
    commit: bool = True,
) -> dict[str, int]:
    """Refresh rental links for every imported claim without changing owner identities.

    Missing current evidence clears an old rental link. Contact/source data,
    ownership assessments, sales evidence and agent workspaces remain intact.
    """
    claims = await import_repository.list_rental_refresh_claims(db, import_id, organization_id)
    units = sorted({claim.unit_number for claim in claims if claim.unit_number})
    rentals = await _rental_evidence_for_units(units)
    counts = {
        "claims": len(claims),
        "before_hits": 0,
        "after_hits": 0,
        "added_hits": 0,
        "removed_hits": 0,
        "changed_claims": 0,
    }
    now = datetime.now(timezone.utc)
    for claim in claims:
        before = (claim.lead_id, claim.unit_candidate_key, claim.lease_end, claim.annual_rent_aed)
        rental = (
            None
            if (claim.evidence or {}).get("scoped_identity_collision")
            else rentals.get(claim.property_key)
        )
        if rental and not _rental_scope_compatible(claim, rental):
            rental = None
        after = (
            (
                str(rental["event_key"]),
                str(rental["unit_candidate_key"]),
                rental.get("lease_end"),
                int(rental.get("annual_rent_aed") or 0) or None,
            )
            if rental
            else (None, None, None, None)
        )
        counts["before_hits"] += bool(before[0])
        counts["after_hits"] += bool(after[0])
        counts["added_hits"] += bool(after[0]) and not before[0]
        counts["removed_hits"] += bool(before[0]) and not after[0]
        if before != after:
            (claim.lead_id, claim.unit_candidate_key, claim.lease_end, claim.annual_rent_aed) = (
                after
            )
            claim.updated_at = now
            import_repository.save(db, claim)
            counts["changed_claims"] += 1
    await db.flush()
    import_ids = {claim.import_id for claim in claims}
    if import_id is not None:
        import_ids.add(import_id)
    await _refresh_contact_import_match_summaries(
        db,
        organization_id=organization_id,
        import_ids=import_ids,
    )
    if commit:
        await db.commit()
    _invalidate_owner_summary_cache(organization_id)
    return counts


def _price_matches(imported: int | None, observed: int) -> bool:
    return amounts_match(imported, observed)


def _source_size_decimal(candidate: ParsedContact) -> Decimal | None:
    fields = candidate.evidence.get("source_fields", {})
    declared_unit = candidate.evidence.get("source_size_unit")
    if declared_unit == "unknown":
        inferred = candidate.evidence.get("inferred_size_unit") or {}
        value = positive_decimal(fields.get("size_unknown"))
        if value is None or inferred.get("unit") not in {"sqft", "sqm"}:
            return None
        return value * (SQM_TO_SQFT if inferred["unit"] == "sqm" else Decimal(1))
    value = fields.get("size_sqft")
    multiplier = Decimal("1")
    if declared_unit == "sqm":
        value = fields.get("size_sqm") or value
        multiplier = Decimal("10.76391041671")
    elif value in (None, ""):
        value = fields.get("size_sqm")
        multiplier = Decimal("10.76391041671")
    size = positive_decimal(value)
    return size * multiplier if size is not None else None


def _source_size(candidate: ParsedContact) -> float | None:
    size = _source_size_decimal(candidate)
    return float(size) if size is not None else None


def _size_matches(candidate: ParsedContact, event: dict[str, Any]) -> bool:
    supplied = _source_size_decimal(candidate)
    if supplied is None:
        return True
    return sizes_match(supplied, event.get("size_sqft"))


def _apply_evidence(
    candidate: ParsedContact,
    *,
    sales: dict[str, list[dict[str, Any]]],
    rentals: dict[str, dict[str, Any]],
) -> None:
    _apply_registry_evidence(candidate, sales=sales, rentals=rentals)
    apply_owner_match(candidate)  # the property-first verdict, when the import stored one
    lifecycle = candidate.evidence.get("source_lifecycle") or {}
    if lifecycle.get("reasons"):
        candidate.match_reason += " Source review: " + " ".join(lifecycle["reasons"])


def _apply_registry_evidence(
    candidate: ParsedContact,
    *,
    sales: dict[str, list[dict[str, Any]]],
    rentals: dict[str, dict[str, Any]],
) -> None:
    # Each assessment replaces derived results; rematching must not retain a
    # previous current/former status when the supporting observation disappears.
    candidate.ownership_status = "unmatched"
    candidate.confidence_score = 20
    candidate.latest_sale_date = None
    candidate.latest_sale_price_aed = None
    candidate.later_sale_date = None
    candidate.lead_id = None
    candidate.unit_candidate_key = None
    candidate.lease_end = None
    candidate.annual_rent_aed = None
    candidate.evidence.pop("registry_inferred_sale", None)
    candidate.evidence.pop("sales_match", None)
    candidate.evidence.pop("matched_sale_date", None)
    candidate.evidence.pop("matched_sale_key", None)
    candidate.evidence.pop("sale_anchor_key", None)
    candidate.evidence.pop("date_event_resolution", None)
    candidate.match_reason = "No unambiguous property evidence was found."
    key = candidate.property_key
    if candidate.evidence.get("scoped_identity_collision"):
        candidate.ownership_status = "conflicting_claim"
        candidate.confidence_score = 40
        candidate.match_reason = (
            "This building/unit key identifies more than one area or project. "
            "The property identity requires review before attaching ownership or a lease."
        )
        return
    if not candidate.unit_number and candidate.evidence.get("cadastral_identity"):
        candidate.ownership_status = "unit_linked_unverified"
        candidate.confidence_score = 50
        candidate.match_reason = (
            "The land number and location match a DLD plot. The source record is retained, "
            "but an individual villa/unit and current ownership have not been verified."
        )
        return
    # Failed lookup rows must not inherit a different row's sales merely because
    # the old persisted display key happens to be equal.
    sale_events = [] if candidate.evidence.get("sales_lookup") else sales.get(key, [])
    if any(
        re.search(r"\([^)]*\)", str(value or ""))
        for value in (
            candidate.unit_number,
            candidate.evidence.get("source_unit_number"),
            candidate.evidence.get("source_fields", {}).get("unit_number"),
        )
    ):
        candidate.ownership_status = "unit_linked_unverified"
        candidate.confidence_score = 50
        candidate.match_reason = "The original unit contains a share or subunit qualifier; the ownership interest requires review."
        return
    source = _amount_match_source(candidate)
    if (
        candidate.evidence.get("owner_match_policy") == POLICY_VERSION
        and sale_events
        and any(
            not original_identifier_support(source, event)
            or ("original_identifiers" in candidate.evidence and not qualified(source, event))
            for event in sale_events
        )
    ):
        candidate.ownership_status = "conflicting_claim"
        candidate.confidence_score = 40
        candidate.match_reason = "The original typed identifiers, property type, or qualified location conflict with the registry property; a recovered alias cannot establish ownership."
        return
    resolution = candidate.evidence.get("property_identity_resolution") or {}
    original_identity = resolution.get("source") or {}
    source_unit_keys = {
        normalized_unit
        for value in (
            original_identity.get("unit_number"),
            candidate.evidence.get("source_fields", {}).get("unit_number"),
        )
        if (normalized_unit := identifier(str(value or "")))
    }
    if source_unit_keys and any(
        str(event.get("property_type") or "").strip().casefold() in {"land", "plot", "plots"}
        and any(
            source_unit_key
            != identifier(
                str(event.get("unit_number") or event.get("unit_key") or candidate.unit_number)
            )
            for source_unit_key in source_unit_keys
        )
        for event in sale_events
    ):
        candidate.ownership_status = "conflicting_claim"
        candidate.confidence_score = 40
        candidate.match_reason = (
            "The original source unit differs from this registry plot. "
            "A parent plot association cannot establish ownership of that unit."
        )
        return
    if any(
        not _registry_type_compatible(candidate, event)
        or physical_types_conflict(
            candidate.evidence.get("source_fields", {}).get("property_type")
            or candidate.property_type,
            event.get("property_type"),
        )
        for event in sale_events
    ):
        candidate.ownership_status = "conflicting_claim"
        candidate.confidence_score = 40
        candidate.match_reason = (
            "The source property type conflicts with the registry history for this key; "
            "the property identity requires review."
        )
        return
    rental = rentals.get(key)
    if rental and not _rental_scope_compatible(candidate, rental):
        rental = None
    if rental:
        candidate.lead_id = str(rental["event_key"])
        candidate.unit_candidate_key = str(rental["unit_candidate_key"])
        candidate.lease_end = rental.get("lease_end")
        candidate.annual_rent_aed = int(rental.get("annual_rent_aed") or 0) or None

    latest = sale_events[-1] if sale_events else None
    if latest:
        candidate.latest_sale_date = latest["transaction_date"]
        candidate.latest_sale_price_aed = (
            int(positive_decimal(latest.get("sale_amount_aed")) or 0) or None
        )
        methods = sorted(
            {str(event.get("_match_method") or "exact_building_key") for event in sale_events}
        )
        candidate.evidence["sales_match"] = {
            "property_type": str(latest.get("property_type") or ""),
            "market_status": str(latest.get("market_status") or ""),
            "methods": methods,
            "matched_buildings": sorted(
                {
                    str(event.get("building_name") or "")
                    for event in sale_events
                    if event.get("building_name")
                }
            ),
            "matched_sales": len(sale_events),
        }

    if not key:
        candidate.ownership_status = "insufficient_property_data"
        candidate.confidence_score = 0
        candidate.match_reason = candidate.evidence.get("context_lookup", {}).get("reason") or (
            "Source record retained. The land/building/property identifiers require "
            "resolution before this contact can be linked to a registry property."
        )
        return

    # Blank procedures require an independently scoped exact registry event.
    # Preserve the source family; dated parties alone never prove a sale.
    inferred_registry_sale = False
    if (
        event_family(candidate.procedure_type) == "contact_snapshot"
        and candidate.evidence.get("parsed_event_family", candidate.evidence.get("event_family"))
        in {None, "contact_snapshot"}
        and candidate.party_role in {"Buyer", "Seller"}
        and candidate.transaction_date
        and (candidate.transaction_price_aed or 0) > 0
    ):
        exact = {
            str(
                event.get("sale_key")
                or f"{event['transaction_date']}:{event.get('sale_amount_aed')}"
            ): event
            for event in sale_events
            if event["transaction_date"] == candidate.transaction_date
            and positive_decimal(_amount_match_source(candidate)["amount_aed"]) is not None
            and positive_decimal(_amount_match_source(candidate)["amount_aed"])
            == positive_decimal(event.get("sale_amount_aed"))
            and (_source_size(candidate) is None or _size_matches(candidate, event))
        }
        inferred_registry_sale = len(exact) == 1
        if inferred_registry_sale:
            candidate.evidence["registry_inferred_sale"] = {
                "version": "exact-registry-inference-1",
                "sale_key": next(iter(exact)),
                "basis": "Independently scoped registry event with exact date and equal positive Decimal amount; available declared size matches within max(50 sqft, 2%)",
                "source_event_family": "contact_snapshot",
            }
    if (
        not has_sale_evidence(candidate)
        or event_family(candidate.procedure_type) == "contact_snapshot"
    ) and not inferred_registry_sale:
        candidate.ownership_status = "unit_linked_unverified" if latest or rental else "unmatched"
        candidate.confidence_score = 50 if latest or rental else 20
        candidate.match_reason = (
            "Source event retained for review. This procedure or party role does not "
            "establish a sale acquisition or disposal; its date and amount were not "
            "used to infer current ownership from sales history."
        )
        return

    if {
        "location_review_required",
        "type_mismatch_review_required",
        "geography_review_required",
        "missing_target_area",
        "unknown_source_event_family",
        "identity_only",
        "generic_building_project_review",
    }.intersection(
        candidate.evidence.get("amount_first_match", {}).get("flags", [])
        + candidate.evidence.get("property_identity_match", {}).get("flags", [])
    ):
        candidate.ownership_status = "unit_linked_unverified"
        candidate.confidence_score = 50
        candidate.match_reason = "The amount and unit support a property candidate, but the source building label or property type requires review before ownership can be assessed."
        return

    if (
        key
        and latest
        and candidate.evidence.get("owner_match_policy") == POLICY_VERSION
        and not (
            candidate.evidence.get("amount_first_match", {}).get("status") == "matched"
            and candidate.evidence.get("amount_first_match", {}).get("selected_event_key")
        )
    ):
        candidate.ownership_status = "unit_linked_unverified"
        candidate.confidence_score = 50
        candidate.match_reason = "The property may be linked, but no unique transaction passed the original identifier, location, type, amount and available size checks."
        return

    source_units = [
        candidate.unit_number,
        candidate.evidence.get("source_unit_number"),
        candidate.evidence.get("source_fields", {}).get("unit_number"),
        candidate.evidence.get("unit_hierarchy_resolution", {})
        .get("source", {})
        .get("unit_number"),
        candidate.evidence.get("registry_unit_fallback", {}).get("source", {}).get("unit_number"),
    ]
    if any(re.search(r"\([^)]*\)", str(unit or "")) for unit in source_units):
        candidate.ownership_status = "unit_linked_unverified"
        candidate.confidence_score = 50
        candidate.match_reason = (
            "The source unit contains a share or subunit qualifier. Its ownership "
            "interest must be resolved before treating a sale as acquisition or full disposal."
        )
        return

    if candidate.party_role == "Seller":
        candidate.ownership_status = "unverified_former_owner"
        candidate.confidence_score = 20
        candidate.match_reason = (
            "The source identifies a seller, but no matching registry disposal is established."
        )

    if not key:
        candidate.ownership_status = "insufficient_property_data"
        candidate.confidence_score = 0
        candidate.match_reason = (
            "The source row has transaction evidence but no recoverable unit/property "
            "identifier; registry matching requires source enrichment."
        )
        return

    if not latest:
        if candidate.party_role == "Seller":
            return
        if rental:
            candidate.ownership_status = "unit_linked_unverified"
            candidate.confidence_score = 60
            candidate.match_reason = (
                "The contact links to an exact lease-opportunity unit, but acquisition "
                "evidence was not found in the sales registry."
            )
        else:
            lookup_status = str((candidate.evidence.get("sales_lookup") or {}).get("status") or "")
            if lookup_status == "unit_not_observed":
                candidate.ownership_status = "registry_not_observed"
                candidate.confidence_score = 10
                candidate.match_reason = (
                    "The source contains a usable unit identifier, but that unit is not "
                    "present in current DXBI sales-registry coverage."
                )
            else:
                candidate.match_reason = (
                    "Registry candidates exist for the unit, but the property location "
                    "could not be resolved unambiguously."
                )
        return

    identity_label = (
        "canonical building identity and unit"
        if any(str(event.get("_match_method")) != "exact_building_key" for event in sale_events)
        else "exact building and unit"
    )

    if not candidate.transaction_date:
        if candidate.party_role == "Seller":
            return
        candidate.ownership_status = "unit_linked_unverified"
        candidate.confidence_score = 62 if rental else 55
        candidate.match_reason = (
            "The unit is exact, but the uploaded contact list does not provide an "
            "acquisition date or price."
        )
        return

    resolution = candidate.evidence.get("property_identity_resolution", {})
    nearby = [
        event
        for event in sale_events
        if abs((event["transaction_date"] - candidate.transaction_date).days) <= 7
    ]

    # A missing size cannot corroborate a match, but it is not a contradiction.
    # Explicit, comparable sizes must agree even for lower-confidence contacts.
    def compatible_terms(event: dict[str, Any]) -> bool:
        supplied_price = _amount_match_source(candidate)["amount_aed"]
        observed_price = event.get("sale_amount_aed") or 0
        return _price_matches(supplied_price, observed_price) and (
            _source_size(candidate) is None
            or ("original_identifiers" not in candidate.evidence and not event.get("size_sqft"))
            or _size_matches(candidate, event)
        )

    def event_key(event: dict[str, Any]) -> str:
        return str(
            event.get("sale_key") or f"{event['transaction_date']}:{event.get('sale_amount_aed')}"
        )

    plausible = {event_key(event): event for event in sale_events if compatible_terms(event)}
    matched_event = next(iter(plausible.values()), None)
    if len(plausible) > 1:
        matched_event = exact_date_event(candidate.transaction_date, plausible.values())
        if matched_event is None:
            candidate.ownership_status = "conflicting_claim"
            candidate.confidence_score = 40
            candidate.match_reason = "Multiple sales fit the supplied amount and available size; no unique exact-date registration excludes competing events within fourteen days."
            return
        candidate.evidence["date_event_resolution"] = "unique_exact_date_without_nearby_competitor"
    if (
        matched_event
        and candidate.evidence.get("owner_match_policy") != POLICY_VERSION
        and (matched_event["transaction_date"] - candidate.transaction_date).days > 7
    ):
        # A property link may span arbitrary dates; a source observation cannot
        # establish an acquisition that the registry records substantially later.
        matched_event = None
    if not matched_event:
        if candidate.party_role != "Seller":
            candidate.ownership_status = "conflicting_claim" if nearby else "unit_linked_unverified"
            candidate.confidence_score = 40
            candidate.match_reason = (
                "The property is linked, but no unique registry acquisition matches the supplied "
                "date, positive amount and available size. Current ownership is unverified."
            )
        return

    acquisition_date = matched_event["transaction_date"]
    if (
        candidate.evidence.get("owner_match_policy") == POLICY_VERSION
        and candidate.evidence.get("amount_first_match", {}).get("selected_event_key")
        != f"sale:{event_key(matched_event)}"
    ):
        candidate.ownership_status = "conflicting_claim"
        candidate.confidence_score = 40
        candidate.match_reason = "Fresh history does not identify the unique transaction accepted from the original source evidence."
        return
    candidate.evidence["matched_sale_date"] = acquisition_date.isoformat()
    candidate.evidence["matched_sale_key"] = event_key(matched_event)
    if acquisition_date == latest["transaction_date"]:
        last_day_events = {
            event_key(event)
            for event in sale_events
            if event["transaction_date"] == latest["transaction_date"]
        }
        if len(last_day_events) > 1:
            candidate.ownership_status = "conflicting_claim"
            candidate.confidence_score = 40
            candidate.match_reason = (
                "More than one registration exists on the last observed sale date. "
                "Dates alone cannot establish which acquisition is current."
            )
            return
    if latest["transaction_date"] > acquisition_date:
        candidate.ownership_status = "former_owner"
        candidate.confidence_score = 99
        candidate.later_sale_date = latest["transaction_date"]
        candidate.match_reason = (
            f"A later sale was recorded on {latest['transaction_date']:%d %b %Y}; "
            "this contact is not presented as the current owner."
        )
        if resolution.get("method") == "file_context_transaction_signature":
            candidate.match_reason += (
                f" Property inferred from {', '.join(candidate.evidence.get('file_context', {}).get('locations', []))}, "
                f"the source amount and acquisition dated {acquisition_date:%d %b %Y}."
            )
            candidate.confidence_score = 90 if not resolution.get("date_delta_days") else 80
        return

    candidate.evidence["sale_anchor_key"] = event_key(matched_event)
    shifted_days = abs((acquisition_date - candidate.transaction_date).days)
    if candidate.party_role == "Seller":
        candidate.ownership_status = "former_owner"
        candidate.confidence_score = 95 if not shifted_days else (65 if shifted_days > 7 else 75)
        candidate.match_reason = (
            f"The source identifies this party as Seller and its positive amount matches "
            f"the uniquely corroborated registry disposal ({acquisition_date:%d %b %Y}). "
            "This is a former-owner source relationship, subject to imported identity "
            "accuracy; the registry does not certify the party's legal identity."
        )
        if shifted_days:
            candidate.match_reason += (
                f" The source date differs by {shifted_days} days and requires review."
            )
        return
    if shifted_days:
        known_size = _source_size(candidate) is not None and bool(matched_event.get("size_sqft"))
        candidate.ownership_status = "probable_current_owner"
        candidate.confidence_score = 65 if shifted_days > 7 else (80 if known_size else 75)
        candidate.match_reason = (
            f"The property and positive amount match the unique latest registry sale "
            f"({acquisition_date:%d %b %Y}); the source date differs by {shifted_days} days. "
            "No later sale is observed. This is a possible current contact requiring review, "
            "not registry verification of the imported buyer's identity."
        )
        if not known_size:
            candidate.match_reason += (
                " A size with a declared unit was unavailable to corroborate the match."
            )
        return
    candidate.ownership_status = "verified_current_owner"
    candidate.confidence_score = 98
    candidate.match_reason = (
        f"{identity_label.title()}; acquisition date and price match the latest sale, "
        "with no later sale observed. The buyer identity comes from the import."
    )


async def rematch_property_contact_claims(
    db: AsyncSession,
    *,
    organization_id: str,
    import_id: int | None = None,
    only_unmatched: bool = True,
    audit_resolution_methods: set[str] | None = None,
) -> dict[str, int]:
    """Re-evaluate saved owner claims against the current DXBI sales registry.

    Imports are immutable source records, but their evidence changes when either
    DXBI coverage improves or the building-identity resolver improves. This
    updates only calculated matching fields, never the uploaded contact data.
    """
    claims = await import_repository.list_claims_for_rematch(
        db, audit_resolution_methods, import_id, only_unmatched, organization_id
    )
    candidates: list[ParsedContact] = []
    for claim in claims:
        claim_evidence = dict(claim.evidence or {})
        source_identity: dict[str, Any] = {}
        if audit_resolution_methods:
            prior_resolution = claim_evidence.get("property_identity_resolution")
            if (
                isinstance(prior_resolution, dict)
                and prior_resolution.get("method") in audit_resolution_methods
            ):
                raw_source = prior_resolution.get("source")
                if isinstance(raw_source, dict):
                    source_identity = raw_source
            for calculated_key in (
                "property_identity_resolution",
                "unit_hierarchy_resolution",
                "sales_lookup",
                "sales_match",
            ):
                claim_evidence.pop(calculated_key, None)

        def identity_field(field_name: str, current: str) -> str:
            value = source_identity.get(field_name)
            return str(value) if value is not None else current

        candidate = ParsedContact(
            source_sheet=claim.source_sheet,
            source_row_number=claim.source_row_number,
            contact_name=claim.contact_name,
            phone_primary=claim.phone_primary,
            phone_alternate=claim.phone_alternate,
            email_primary=claim.email_primary,
            area_name=identity_field("area_name", claim.area_name),
            project_name=identity_field("project_name", claim.project_name),
            building_name=identity_field("building_name", claim.building_name),
            unit_number=identity_field("unit_number", claim.unit_number),
            property_type=claim.property_type,
            transaction_date=claim.transaction_date,
            transaction_price_aed=claim.transaction_price_aed,
            party_role=claim.party_role,
            procedure_type=claim.procedure_type,
            row_fingerprint=claim.row_fingerprint,
            evidence={key: value for key, value in claim_evidence.items() if key != "sales_match"},
        )
        candidate.evidence["source_import_scope"] = str(claim.import_id)
        _recover_embedded_property_identity(candidate)
        candidates.append(candidate)
    await run_in_thread(annotate_source_lifecycle, candidates)
    await prepare_file_context(candidates)
    resolution_counts = await _recover_property_identity_from_transaction(candidates)
    near_resolution_counts = await _recover_property_identity_from_near_transaction(candidates)
    await recover_from_file_context(candidates)
    _reuse_mortgage_property_from_sale_anchors(candidates)
    sales = await _sales_evidence(candidates)
    await _apply_registry_unit_fallbacks(candidates, sales)
    rentals = await _rental_evidence(candidates)
    await run_in_thread(annotate_source_lifecycle, candidates)
    # claims made before it get their source rebuilt
    await run_owner_matching(candidates, await load_broker_index(db))
    now = datetime.now(timezone.utc)
    status_counts: dict[str, int] = {}
    for claim, candidate in zip(claims, candidates, strict=True):
        _apply_evidence(candidate, sales=sales, rentals=rentals)
        claim.area_name = candidate.area_name
        claim.project_name = candidate.project_name
        claim.building_name = candidate.building_name
        claim.unit_number = candidate.unit_number
        claim.property_key = candidate.property_key or f"source:{candidate.row_fingerprint}"
        claim.owner_key = _candidate_owner_key(candidate)
        claim.ownership_status = candidate.ownership_status
        claim.confidence_score = candidate.confidence_score
        claim.match_reason = candidate.match_reason
        claim.lead_id = candidate.lead_id
        claim.unit_candidate_key = candidate.unit_candidate_key
        claim.latest_sale_date = candidate.latest_sale_date
        claim.latest_sale_price_aed = candidate.latest_sale_price_aed
        claim.later_sale_date = candidate.later_sale_date
        claim.lease_end = candidate.lease_end
        claim.annual_rent_aed = candidate.annual_rent_aed
        claim.evidence = candidate.evidence
        claim.updated_at = now
        import_repository.save(db, claim)
        status_counts[candidate.ownership_status] = (
            status_counts.get(candidate.ownership_status, 0) + 1
        )
    await db.flush()
    affected_import_ids = {claim.import_id for claim in claims}
    if import_id is not None:
        affected_import_ids.add(import_id)
    await _refresh_contact_import_match_summaries(
        db,
        organization_id=organization_id,
        import_ids=affected_import_ids,
    )
    await db.commit()
    _invalidate_owner_summary_cache(organization_id)
    return {
        "claims": len(claims),
        **{f"transaction_{key}": value for key, value in resolution_counts.items()},
        **{f"near_transaction_{key}": value for key, value in near_resolution_counts.items()},
        **status_counts,
    }


async def _refresh_contact_import_match_summaries(
    db: AsyncSession,
    *,
    organization_id: str,
    import_ids: set[int],
) -> dict[int, dict[str, int]]:
    """Synchronize persisted import cards with current claim evidence."""
    refreshed: dict[int, dict[str, int]] = {}
    if not import_ids:
        return refreshed

    import_result = await import_repository.list_imports_by_ids(db, import_ids, organization_id)
    for record in import_result:
        record_id = record.id
        if record_id is None:
            continue
        status_result = await import_repository.count_claims_by_status(
            db, organization_id, record_id
        )
        status_counts = {str(status): int(count) for status, count in status_result}
        (
            candidate_rows,
            valid_contacts,
            rental_opportunities,
            contact_ready,
            rows_with_sales_history,
            plot_only_rows,
        ) = await import_repository.count_import_claim_metrics(db, organization_id, record_id)
        distinct_properties = await import_repository.count_import_distinct_properties(
            db, organization_id, record_id
        )
        summary = dict(record.summary or {})
        summary.update(
            {
                "candidate_rows": candidate_rows,
                "distinct_properties": distinct_properties,
                "rows_with_sales_history": rows_with_sales_history,
                "plot_only_rows": plot_only_rows,
                "valid_contacts": valid_contacts,
                "rental_opportunities": rental_opportunities,
                "contact_ready": contact_ready,
            }
        )
        summary["properties_linked_rows"] = await import_repository.count_import_linked_rows(
            db, organization_id, record_id
        )
        for summary_field in _STATUS_SUMMARY_FIELDS.values():
            summary[summary_field] = 0
        for status, count in status_counts.items():
            summary_field = _STATUS_SUMMARY_FIELDS.get(status)
            if summary_field:
                summary[summary_field] = count
        verdicts = await import_repository.list_claim_matches(db, organization_id, record_id)
        if verdicts:
            summary["owner_match"] = summarize_owner_matches(verdicts)
        validated = CrmContactImportSummary.model_validate(summary).model_dump()
        record.summary = validated
        import_repository.save(db, record)
        refreshed[record_id] = {
            "candidate_rows": candidate_rows,
            **status_counts,
        }
    return refreshed


async def refresh_contact_import_match_summaries(
    db: AsyncSession,
    *,
    organization_id: str,
    import_id: int | None = None,
) -> dict[int, dict[str, int]]:
    """Refresh import-card summaries without re-running registry matching."""
    if import_id is not None:
        import_ids = {import_id}
    else:
        result = await import_repository.list_import_ids(db, organization_id)
        import_ids = {record_id for record_id in result if record_id is not None}
    refreshed = await _refresh_contact_import_match_summaries(
        db,
        organization_id=organization_id,
        import_ids=import_ids,
    )
    await db.commit()
    _invalidate_owner_summary_cache(organization_id)
    return refreshed
