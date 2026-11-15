from __future__ import annotations

import hashlib
import logging
from datetime import date
from typing import Any

from fastapi import HTTPException
from sqlmodel.ext.asyncio.session import AsyncSession

from app.crm import lead_cache, owner_queries, owner_repository
from app.crm.identity import (
    _claim_owner_key,
    _claim_preference,
    _claim_property_key,
    _location_key,
    _location_similarity,
    _normalize_email,
    _normalize_phone,
    _normalize_unit,
    _usable_project_name,
)
from app.crm.import_context import property_details
from app.crm.import_models import (
    CrmContactClaimResponse,
    CrmContactList,
    CrmContactListDetail,
    CrmContactListSummary,
    CrmLeadImportedContact,
    CrmOwnerProfile,
    CrmOwnerProperty,
    CrmOwnerRegistryResponse,
    CrmOwnerRegistrySummary,
    CrmPropertyContactClaim,
    CrmSourceAuditSummary,
)
from app.crm.owner_cache import (
    _invalidate_owner_summary_cache as _invalidate_owner_summary_cache,
)
from app.crm.owner_rows import (
    CURRENT_OWNER_STATUSES,
    REVIEW_OWNER_STATUSES,
    assessed_list_counts,
    owner_read_keys,
    profile_with_properties,
    property_contact_ready,
)
from app.crm.owner_store import open_store

logger = logging.getLogger(__name__)


def _claim_source_rows(group: list[CrmPropertyContactClaim]) -> list[str]:
    values = {f"{claim.source_sheet}:{claim.source_row_number}" for claim in group}
    for claim in group:
        source_rows = claim.evidence.get("source_rows", []) if claim.evidence else []
        if isinstance(source_rows, list):
            values.update(str(item) for item in source_rows if item)
    return sorted(values)


def _claim_duplicate_count(group: list[CrmPropertyContactClaim]) -> int:
    persisted = [
        int(claim.evidence.get("duplicate_count", 1))
        for claim in group
        if claim.evidence and isinstance(claim.evidence.get("duplicate_count", 1), int)
    ]
    return max(len(group), max(persisted, default=1))


def _claim_response(
    claim: CrmPropertyContactClaim,
    group: list[CrmPropertyContactClaim] | None = None,
) -> CrmContactClaimResponse:
    if claim.id is None:
        raise HTTPException(status_code=500, detail="Imported contact is missing an id")
    grouped = group or [claim]
    return CrmContactClaimResponse(
        id=claim.id,
        source_sheet=claim.source_sheet,
        source_row_number=claim.source_row_number,
        contact_name=claim.contact_name,
        phone_primary=claim.phone_primary,
        phone_alternate=claim.phone_alternate,
        email_primary=claim.email_primary,
        area_name=claim.area_name,
        project_name=claim.project_name,
        building_name=claim.building_name,
        unit_number=claim.unit_number,
        property_type=claim.property_type,
        property_details=property_details(claim.evidence or {}),
        transaction_date=claim.transaction_date,
        transaction_price_aed=claim.transaction_price_aed,
        ownership_status=claim.ownership_status,  # type: ignore[arg-type]
        confidence_score=claim.confidence_score,
        match_reason=claim.match_reason,
        lead_id=claim.lead_id,
        unit_candidate_key=claim.unit_candidate_key,
        latest_sale_date=claim.latest_sale_date,
        latest_sale_price_aed=claim.latest_sale_price_aed,
        later_sale_date=claim.later_sale_date,
        lease_end=claim.lease_end,
        annual_rent_aed=claim.annual_rent_aed,
        owner_key=_claim_owner_key(claim),
        duplicate_count=_claim_duplicate_count(grouped),
        source_rows=_claim_source_rows(grouped),
        **_match_fields(claim.evidence or {}),
    )


def _match_fields(evidence: dict[str, Any]) -> dict[str, Any]:
    """The stored property-first verdict as the row fields the API shows (empty before it)."""
    match = evidence.get("owner_match")
    if not isinstance(match, dict):
        return {}
    return {
        "match_outcome": match.get("outcome"),
        "match_colour": match.get("colour"),
        "match_reasons": list(match.get("reasons") or []),
        "match_warnings": list(match.get("warnings") or []),
        "matched_sale": match.get("sale"),
    }


def _projected_claims(
    claims: list[CrmPropertyContactClaim],
    rows: list[dict[str, Any]],
    read_keys: dict[str, str] | None = None,
) -> list[CrmPropertyContactClaim]:
    assessed = {row["id"]: row for row in rows}
    if read_keys is None:
        read_keys = owner_read_keys(rows)
    projected = []
    for claim in claims:
        row = assessed.get(claim.id)
        if row is None:
            continue
        projected.append(
            claim.model_copy(
                update={
                    "owner_key": read_keys[row["canonical_owner_key"]],
                    "property_key": row["property_key"],
                    "ownership_status": row["assessed_status"],
                    "confidence_score": row.get(
                        "assessed_confidence_score", row["confidence_score"]
                    ),
                    "match_reason": row["assessed_reason"],
                    "phone_primary": _normalize_phone(row.get("phone_primary")),
                    "phone_alternate": _normalize_phone(row.get("phone_alternate")),
                    "email_primary": _normalize_email(row.get("email_primary")),
                    **{
                        key: row.get(key)
                        for key in (
                            "area_name",
                            "project_name",
                            "building_name",
                            "unit_number",
                            "lead_id",
                            "unit_candidate_key",
                            "latest_sale_date",
                            "latest_sale_price_aed",
                            "later_sale_date",
                            "lease_end",
                            "annual_rent_aed",
                        )
                    },
                }
            )
        )
    return projected


def _list_summary(contact_list: CrmContactList, counts: dict[str, int]) -> CrmContactListSummary:
    return CrmContactListSummary(
        id=contact_list.id,
        source_import_id=contact_list.source_import_id,
        name=contact_list.name,
        description=contact_list.description,
        **counts,
        created_at=contact_list.created_at,
        updated_at=contact_list.updated_at,
    )


def _assessed_list_summary(
    contact_list: CrmContactList, rows: list[dict[str, Any]]
) -> CrmContactListSummary:
    return _list_summary(contact_list, assessed_list_counts(rows))


_NO_COUNTS = {"total_contacts": 0, "contact_ready": 0, "needs_review": 0, "former_owners": 0}


async def list_contact_lists(
    db: AsyncSession,
    *,
    organization_id: str,
) -> list[CrmContactListSummary]:
    list_result = await owner_repository.list_contact_lists(db, organization_id)
    contact_lists = list(list_result)
    if not contact_lists:
        return []
    store = await open_store(db, organization_id)
    return [
        _list_summary(item, store.state.list_counts.get(str(item.id), _NO_COUNTS))
        for item in contact_lists
    ]


async def get_contact_list(
    db: AsyncSession,
    *,
    list_id: int,
    organization_id: str,
    status: str | None,
    search: str | None,
    limit: int,
    offset: int,
    match_colour: list[str] | None = None,
    match_outcome: list[str] | None = None,
) -> CrmContactListDetail:
    list_result = await owner_repository.get_contact_list(db, list_id, organization_id)
    contact_list = list_result
    if not contact_list:
        raise HTTPException(status_code=404, detail="CRM contact list not found")
    store = await open_store(db, organization_id)
    total, visible = await store.contact_list_groups(
        list_id,
        search=search,
        status=status,
        match_colour=match_colour,
        match_outcome=match_outcome,
        limit=limit,
        offset=offset,
    )
    selected = await store.rows_by_ids([group["best_id"] for group in visible])
    claims = await owner_repository.list_claims_by_ids(
        db, organization_id, [row["id"] for row in selected]
    )
    read_keys = await store.read_keys({row["canonical_owner_key"] for row in selected})
    projected = {claim.id: claim for claim in _projected_claims(list(claims), selected, read_keys)}
    contacts = []
    for group in visible:
        claim = projected.get(group["best_id"])
        if claim is None:
            continue
        response = _claim_response(claim)
        response.duplicate_count = group["rows"]
        response.source_rows = group["source_rows"]
        contacts.append(response)
    return CrmContactListDetail(
        list=_list_summary(contact_list, store.state.list_counts.get(str(list_id), _NO_COUNTS)),
        contacts=contacts,
        total=total,
        limit=limit,
        offset=offset,
    )


async def list_lead_imported_contacts(
    db: AsyncSession,
    *,
    lead_id: str,
    organization_id: str,
) -> list[CrmLeadImportedContact]:
    result = await owner_repository.list_lead_claims_with_lists(db, lead_id, organization_id)
    rows = list(result)
    store = await open_store(db, organization_id)
    by_id = {claim.id: contact_list for claim, contact_list in rows}
    # The assessed rows of the claims on this lead, then every row of the people they name:
    # a person's property count spans all of their rows.
    linked = [
        row
        for row in await store.rows_by_ids([claim.id for claim, _ in rows if claim.id is not None])
        if row.get("lead_id") == lead_id
        and row.get("unit_candidate_key")
        and row["property_identity"] is not None
    ]
    projected_rows = linked
    projected = _projected_claims(
        [claim for claim, _ in rows if claim.id in {row["id"] for row in linked}],
        projected_rows,
        await store.read_keys({row["canonical_owner_key"] for row in linked}),
    )
    grouped: dict[tuple[str, str], list[tuple[CrmPropertyContactClaim, CrmContactList]]] = {}
    for claim in projected:
        grouped.setdefault((claim.owner_key, claim.property_key), []).append(
            (claim, by_id[claim.id])
        )
    property_counts = await store.property_counts({row["canonical_owner_key"] for row in linked})

    contacts: list[CrmLeadImportedContact] = []
    for group_rows in grouped.values():
        claim_group = [claim for claim, _ in group_rows]
        claim = max(claim_group, key=_claim_preference)
        contact_list = next(
            contact_list for candidate, contact_list in group_rows if candidate.id == claim.id
        )
        if claim.id is None or contact_list.id is None:
            continue
        owner_key = _claim_owner_key(claim)
        contacts.append(
            CrmLeadImportedContact(
                claim_id=claim.id,
                list_id=contact_list.id,
                list_name=contact_list.name,
                contact_name=claim.contact_name,
                phone_primary=claim.phone_primary,
                phone_alternate=claim.phone_alternate,
                email_primary=claim.email_primary,
                ownership_status=claim.ownership_status,  # type: ignore[arg-type]
                confidence_score=claim.confidence_score,
                match_reason=claim.match_reason,
                source_sheet=claim.source_sheet,
                imported_at=claim.created_at,
                owner_key=owner_key,
                duplicate_count=_claim_duplicate_count(claim_group),
                property_count=property_counts.get(owner_key, 0),
                source_lists=sorted({item.name for _, item in group_rows}),
            )
        )
    contacts.sort(key=lambda item: (item.confidence_score, item.property_count), reverse=True)
    return contacts


def _property_from_rows(
    rows: list[tuple[CrmPropertyContactClaim, CrmContactList]],
) -> CrmOwnerProperty:
    claims = [claim for claim, _ in rows]
    best = max(claims, key=_claim_preference)
    return CrmOwnerProperty(
        property_key=_claim_property_key(best),
        area_name=best.area_name,
        project_name=best.project_name,
        building_name=best.building_name,
        unit_number=best.unit_number,
        property_type=best.property_type,
        ownership_status=best.ownership_status,  # type: ignore[arg-type]
        confidence_score=best.confidence_score,
        match_reason=best.match_reason,
        lead_id=best.lead_id,
        unit_candidate_key=best.unit_candidate_key,
        imported_transaction_date=best.transaction_date,
        imported_transaction_price_aed=best.transaction_price_aed,
        imported_property_type=best.property_type,
        imported_party_role=best.party_role,
        latest_sale_date=best.latest_sale_date,
        latest_sale_price_aed=best.latest_sale_price_aed,
        registry_sale_date=best.latest_sale_date,
        registry_sale_price_aed=best.latest_sale_price_aed,
        later_sale_date=best.later_sale_date,
        lease_end=best.lease_end,
        annual_rent_aed=best.annual_rent_aed,
        duplicate_count=_claim_duplicate_count(claims),
        source_lists=sorted({contact_list.name for _, contact_list in rows}),
        source_rows=_claim_source_rows(claims),
    )


def _profile_search_matches(profile: CrmOwnerProfile, search: str) -> bool:
    return (
        search.strip().casefold()
        in " ".join(
            str(value or "")
            for value in (
                profile.contact_name,
                profile.phone_primary,
                profile.phone_alternate,
                profile.email_primary,
            )
        ).casefold()
    )


def _assessed_property_matches(
    item: CrmOwnerProperty,
    *,
    profile: CrmOwnerProfile,
    scope: str,
    status: str | None,
    search: str | None,
    lease_window: str | None,
    min_rent_aed: int | None,
    max_rent_aed: int | None,
    min_value_aed: int | None,
    max_value_aed: int | None,
    transaction_match_status: str | None = None,
) -> bool:
    if transaction_match_status and (
        item.source_reference is None
        or item.source_reference.transaction_match_status != transaction_match_status
    ):
        return False
    ready = property_contact_ready(item, profile)
    if scope == "rental_ready" and not ready:
        return False
    if scope == "registry" and (ready or item.ownership_status == "former_owner"):
        return False
    if scope == "current_owners" and item.ownership_status not in CURRENT_OWNER_STATUSES:
        return False
    if scope == "prior_owners" and item.ownership_status != "former_owner":
        return False
    if scope == "needs_review" and item.ownership_status not in REVIEW_OWNER_STATUSES:
        return False
    if status and item.ownership_status != status:
        return False
    if (
        search
        and not _profile_search_matches(profile, search)
        and search.strip().casefold()
        not in " ".join(
            (item.area_name, item.project_name, item.building_name, item.unit_number)
        ).casefold()
    ):
        return False
    if lease_window:
        if item.lease_end is None:
            return False
        days = (item.lease_end - date.today()).days
        if lease_window == "expired" and days >= 0:
            return False
        windows = {"expiring_30": (0, 30), "expiring_60": (30, 60), "expiring_90": (60, 90)}
        if lease_window in windows:
            lower, upper = windows[lease_window]
            if not lower < days <= upper:
                return False
    for value, minimum, maximum in (
        (item.annual_rent_aed, min_rent_aed, max_rent_aed),
        (item.latest_sale_price_aed, min_value_aed, max_value_aed),
    ):
        if minimum is not None and (value is None or value < minimum):
            return False
        if maximum is not None and (value is None or value > maximum):
            return False
    return True


async def get_owner_registry(
    db: AsyncSession,
    *,
    organization_id: str,
    list_id: int | None,
    scope: str,
    status: str | None,
    search: str | None,
    lease_window: str | None,
    portfolio_only: bool,
    min_rent_aed: int | None,
    max_rent_aed: int | None,
    min_value_aed: int | None,
    max_value_aed: int | None,
    limit: int,
    offset: int,
    min_properties: int | None = None,
    next_event_days: int | None = None,
    transaction_match_status: str | None = None,
) -> CrmOwnerRegistryResponse:
    """One page of the owner file, cached per published assessment generation and day.

    A generation is immutable once published (a rebuild or lease refresh publishes a new one),
    so a repeat view never re-ranks every owner.
    """
    store = await open_store(db, organization_id)
    today = _today()
    params = {
        "list_id": list_id,
        "scope": scope,
        "status": status,
        "search": search,
        "lease_window": lease_window,
        "portfolio_only": portfolio_only,
        "min_rent_aed": min_rent_aed,
        "max_rent_aed": max_rent_aed,
        "min_value_aed": min_value_aed,
        "max_value_aed": max_value_aed,
        "limit": limit,
        "offset": offset,
        "min_properties": min_properties,
        "next_event_days": next_event_days,
        "transaction_match_status": transaction_match_status,
        "today": today,
    }
    tenant = hashlib.sha256(organization_id.encode()).hexdigest()[:24]
    return await lead_cache.cached_for(
        "owner_registry",
        f"{tenant}-{store.state.generation}",
        params,
        CrmOwnerRegistryResponse,
        lambda: _owner_registry_page(store, **params),
        ttl=OWNER_PAGE_TTL_SECONDS,
    )


def _today() -> date:
    return date.today()


# A list row's properties: enough for the row and its page filters; the profile has them all.
OWNER_LIST_PROPERTIES_MAX = 25
OWNER_PAGE_TTL_SECONDS = 3600


def _bounded(profile: CrmOwnerProfile) -> CrmOwnerProfile:
    if len(profile.properties) <= OWNER_LIST_PROPERTIES_MAX:
        return profile
    return profile.model_copy(
        update={
            "properties": profile.properties[:OWNER_LIST_PROPERTIES_MAX],
            "properties_truncated": True,
            "total_property_count": profile.total_property_count or profile.property_count,
        }
    )


async def _owner_registry_page(
    store,
    *,
    list_id: int | None,
    scope: str,
    status: str | None,
    search: str | None,
    lease_window: str | None,
    portfolio_only: bool,
    min_rent_aed: int | None,
    max_rent_aed: int | None,
    min_value_aed: int | None,
    max_value_aed: int | None,
    limit: int,
    offset: int,
    min_properties: int | None,
    next_event_days: int | None,
    transaction_match_status: str | None,
    today: date,
) -> CrmOwnerRegistryResponse:
    page, total, counts = await store.registry_page(
        list_id=list_id,
        scope=scope,
        status=status,
        search=search,
        lease_window=lease_window,
        portfolio_only=portfolio_only,
        min_rent_aed=min_rent_aed,
        max_rent_aed=max_rent_aed,
        min_value_aed=min_value_aed,
        max_value_aed=max_value_aed,
        min_properties=min_properties,
        next_event_days=next_event_days,
        transaction_match_status=transaction_match_status,
        today=today,
        limit=limit,
        offset=offset,
    )
    owners = []
    full_profiles = await store.profiles(page)
    list_profiles = full_profiles if list_id is None else await store.profiles(page, list_id)
    for canonical in page:
        full, profile = full_profiles.get(canonical), list_profiles.get(canonical)
        if full is None or profile is None:
            continue
        properties = [
            item
            for item in profile.properties
            if _assessed_property_matches(
                item,
                profile=profile,
                scope=scope,
                status=status,
                search=search,
                lease_window=lease_window,
                min_rent_aed=min_rent_aed,
                max_rent_aed=max_rent_aed,
                min_value_aed=min_value_aed,
                max_value_aed=max_value_aed,
                transaction_match_status=transaction_match_status,
            )
        ]
        owners.append(
            _bounded(
                profile_with_properties(profile, properties).model_copy(
                    update={"total_property_count": full.property_count}
                )
                if scope in {"current_owners", "prior_owners"} or transaction_match_status
                else full
            )
        )
    source_audit = store.state.source_audit.get("all" if list_id is None else str(list_id))
    return CrmOwnerRegistryResponse(
        source_audit=CrmSourceAuditSummary.model_validate(source_audit) if source_audit else None,
        scope=scope,  # type: ignore[arg-type]
        owners=owners,
        total=total,
        limit=limit,
        offset=offset,
        summary=CrmOwnerRegistrySummary(**counts),
    )


def _owner_property_registry_score(
    owner_property: CrmOwnerProperty,
    row: dict[str, Any],
) -> int:
    owner_building = _usable_project_name(owner_property.building_name)
    owner_project = _usable_project_name(owner_property.project_name)
    owner_area = _usable_project_name(owner_property.area_name)
    sale_building = str(row.get("building_name") or "")
    sale_project = str(row.get("project_name") or "")
    sale_area = str(row.get("area_name") or "")
    combined_sale = " ".join(value for value in (sale_building, sale_project) if value)
    building_score = max(
        (_location_similarity(owner_building, value) for value in (sale_building, combined_sale)),
        default=0,
    )
    project_score = max(
        (
            _location_similarity(owner_project, value)
            for value in (sale_project, sale_building, combined_sale)
        ),
        default=0,
    )
    area_score = _location_similarity(owner_area, sale_area)
    if owner_building:
        return round(0.70 * building_score + 0.25 * project_score + 0.05 * area_score)
    if owner_project:
        return round(0.90 * project_score + 0.10 * area_score)
    return area_score


def _positive_float(value: Any) -> float | None:
    parsed = float(value or 0)
    return parsed if parsed > 0 else None


async def _enrich_owner_profile_registry(profile: CrmOwnerProfile) -> CrmOwnerProfile:
    """Attach authoritative DLD registry attributes to a clicked owner profile.

    Claims already retain the selected property's latest sale signature. Restricting
    the registry query to those signatures avoids scanning every Dubai property that
    happens to use a generic unit number such as 101 or 204.
    """
    eligible = [
        owner_property
        for owner_property in profile.properties
        if owner_property.unit_number
        and owner_property.latest_sale_date
        and owner_property.latest_sale_price_aed
    ]
    if not eligible:
        return profile
    signatures = {
        (
            owner_property.latest_sale_date,
            int(owner_property.latest_sale_price_aed or 0),
        )
        for owner_property in eligible
    }
    rows = await owner_queries.fetch_owner_property_signatures(
        {
            "dates": sorted({signature[0] for signature in signatures}),
            "prices": sorted({signature[1] for signature in signatures}),
        }
    )
    rows_by_signature: dict[tuple[date, int], list[dict[str, Any]]] = {}
    for row in rows:
        signature = (
            row["transaction_date"],
            int(row.get("sale_amount_aed") or 0),
        )
        if signature in signatures:
            rows_by_signature.setdefault(signature, []).append(row)

    for owner_property in eligible:
        signature = (
            owner_property.latest_sale_date,
            int(owner_property.latest_sale_price_aed or 0),
        )
        unit_key = _normalize_unit(owner_property.unit_number).lower()
        property_candidates: dict[tuple[str, str, str], dict[str, Any]] = {}
        for row in rows_by_signature.get(signature, []):
            if str(row.get("unit_key") or "") != unit_key:
                continue
            building_key = str(row.get("building_key") or "") or _location_key(
                str(row.get("building_name") or row.get("project_name") or "")
            )
            identity = (
                str(row.get("area_key") or ""),
                building_key,
                str(row.get("unit_key") or ""),
            )
            property_candidates.setdefault(identity, row)
        if not property_candidates:
            continue
        ranked = sorted(
            (
                (_owner_property_registry_score(owner_property, row), row)
                for row in property_candidates.values()
            ),
            key=lambda item: item[0],
            reverse=True,
        )
        score, selected = ranked[0]
        runner_up = ranked[1][0] if len(ranked) > 1 else 0
        if score < 55 or (len(ranked) > 1 and score - runner_up < 12):
            continue

        owner_property.registry_sale_date = selected["transaction_date"]
        owner_property.registry_sale_price_aed = int(selected.get("sale_amount_aed") or 0) or None
        owner_property.registry_property_type = (
            str(selected.get("property_type") or "").strip() or None
        )
        owner_property.registry_bedrooms = str(selected.get("bedrooms") or "").strip() or None
        owner_property.registry_size_sqft = _positive_float(selected.get("size_sqft"))
        owner_property.registry_built_up_area_sqft = _positive_float(
            selected.get("built_up_area_sqft")
        )
        owner_property.registry_price_per_sqft_aed = _positive_float(
            selected.get("price_per_sqft_aed")
        )
        owner_property.registry_market_status = (
            str(selected.get("market_status") or "").strip() or None
        )
        owner_property.registry_unit_number = str(selected.get("unit_number") or "").strip() or None
        owner_property.registry_building_name = (
            str(selected.get("building_name") or selected.get("project_name") or "").strip() or None
        )
        owner_property.registry_area_name = str(selected.get("area_name") or "").strip() or None
    return profile


async def get_owner_profile(
    db: AsyncSession,
    *,
    organization_id: str,
    owner_key: str,
) -> CrmOwnerProfile:
    store = await open_store(db, organization_id)
    canonical = await store.canonical_owners(owner_key)
    if not canonical:
        raise HTTPException(status_code=404, detail="Owner profile not found")
    if len(canonical) != 1:
        raise HTTPException(
            status_code=409,
            detail="This legacy owner key contains multiple contact identities; select an owner from the registry to review its evidence.",
        )
    selected_key = next(iter(canonical))
    profile = await store.profile(selected_key)
    if profile is None:
        raise HTTPException(status_code=404, detail="No reviewed owner candidate for this party")
    if await store.has_source_rows(selected_key):
        return profile
    try:
        return await _enrich_owner_profile_registry(profile)
    except Exception:
        logger.exception(
            "Owner profile registry enrichment failed",
            extra={"owner_key": owner_key},
        )
        return profile
