"""Vitevue-supplied renewal leads: the lease-expiry dataset filtered to one agent's areas.

Assets › Renewals reads the whole dataset (/crm/renewals). Leads shows this view, computed on
every request from the agent's saved areas and windows, so it follows time, new lease data and
preference changes without storing copies of property data. One row per unit comes from the
lease query itself. When an agent opens a unit it becomes the agency's one shared lead for that
unit (open_renewal_lead), which keeps its stage, notes and owner after it leaves the window.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Literal

from fastapi import HTTPException
from pydantic import RootModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.crm import (
    inbound,
    inbound_repository,
    lead_cache,
    opportunity_queries,
    renewal_repository,
    workspace_repository,
)
from app.crm.identity import _normalize_email, _normalize_phone
from app.crm.inbound_models import InboundEnquiryResponse
from app.crm.lead_data_errors import lead_data_error, not_loaded
from app.crm.models import (
    CrmAgentAreaPreference,
    CrmAreaPreferencesResponse,
    CrmAreaPreferencesUpdate,
    CrmRenewalArea,
    CrmRenewalLead,
    CrmRenewalLeadCounts,
    CrmRenewalLeadsResponse,
    CrmRenewalOwner,
    CrmRenewalsResponse,
)
from app.crm.opportunities import _lead_from_row, get_lead_detail
from app.crm.owner_store import open_store

logger = logging.getLogger(__name__)


def _preferences_response(
    record: CrmAgentAreaPreference | None,
) -> CrmAreaPreferencesResponse:
    if record is None:
        return CrmAreaPreferencesResponse(areas=[])
    return CrmAreaPreferencesResponse(
        areas=list(record.areas),
        forward_days=record.forward_days,
        lookback_days=record.lookback_days,
        updated_at=record.updated_at,
    )


def _clean_areas(areas: list[str]) -> list[str]:
    return sorted({area.strip() for area in areas if area.strip()})


async def until_disconnected(is_disconnected, work):
    """Answer `work`, or None after stopping its lease queries when the agent abandons it."""
    return await opportunity_queries.run_until_disconnected(is_disconnected, work)


async def get_area_preferences(
    db: AsyncSession, *, user_id: str, organization_id: str
) -> CrmAreaPreferencesResponse:
    record = await renewal_repository.get_area_preference(db, user_id, organization_id)
    return _preferences_response(record)


async def update_area_preferences(
    db: AsyncSession,
    *,
    payload: CrmAreaPreferencesUpdate,
    user_id: str,
    organization_id: str,
) -> CrmAreaPreferencesResponse:
    now = datetime.now(timezone.utc)
    record = await renewal_repository.get_area_preference(db, user_id, organization_id)
    if record is None:
        record = CrmAgentAreaPreference(
            user_id=user_id,
            organization_id=organization_id,
            created_at=now,
            updated_at=now,
        )
    record.areas = _clean_areas(payload.areas)
    record.forward_days = payload.forward_days
    record.lookback_days = payload.lookback_days
    record.updated_at = now
    renewal_repository.save(db, record)
    await db.commit()
    await db.refresh(record)
    return _preferences_response(record)


class _RenewalAreas(RootModel[list[CrmRenewalArea]]):
    pass


async def list_renewal_areas(as_of: date | None = None) -> list[CrmRenewalArea]:
    """Areas with their units whose lease ends in the next 90 days, once per data release."""
    anchor = as_of or date.today()

    async def compute() -> _RenewalAreas:
        return _RenewalAreas(await _compute_renewal_areas(anchor))

    return (
        await lead_cache.cached("renewal_areas", {"as_of": anchor}, _RenewalAreas, compute)
    ).root


async def _compute_renewal_areas(anchor: date) -> list[CrmRenewalArea]:
    if not await opportunity_queries._tables_exist():
        raise not_loaded()
    try:
        rows = await opportunity_queries.fetch_renewal_areas(anchor)
    except Exception as exc:
        raise lead_data_error(exc, "renewal areas") from exc
    return [
        CrmRenewalArea(area=str(row["area"]), upcoming_90_days=int(row["upcoming_90_days"]))
        for row in rows
    ]


# Vacant: the unit's lease ended this many days ago at most (Assets › Renewals default).
VACANT_LOOKBACK_DAYS_DEFAULT = 60


async def list_renewals(
    *,
    window: str | None,
    area: str | None,
    property_type: str | None,
    project: str | None,
    building: str | None,
    limit: int,
    offset: int,
    as_of: date | None = None,
    unit_keys: list[str] | None = None,
    exclude_units: bool = False,
) -> CrmRenewalsResponse:
    """Every lease in the dataset, whatever any agent's areas, narrowed by the tab's filters.

    window: vacant (ended in the last 60 days, no later lease), expired (last 12 months), one of
    the expiring windows, or None for all of them.
    """
    anchor = as_of or date.today()
    params = {
        "window": window,
        "area": area,
        "property_type": property_type,
        "project": project,
        "building": building,
        "limit": limit,
        "offset": offset,
        "as_of": anchor,
        "unit_keys": sorted(set(unit_keys or [])),
        "exclude_units": exclude_units,
    }
    return await lead_cache.cached(
        "renewals", params, CrmRenewalsResponse, lambda: _compute_renewals(**params)
    )


async def _compute_renewals(
    *,
    window: str | None,
    area: str | None,
    property_type: str | None,
    project: str | None,
    building: str | None,
    limit: int,
    offset: int,
    as_of: date,
    unit_keys: list[str],
    exclude_units: bool,
) -> CrmRenewalsResponse:
    anchor = as_of
    empty = CrmRenewalsResponse(leads=[], total=0, limit=limit, offset=offset, as_of=anchor)
    if not await opportunity_queries._tables_exist():
        raise not_loaded()
    vacant = window == "vacant"
    try:
        rows, total, facets = await opportunity_queries.fetch_renewals(
            anchor,
            status="expired" if vacant else window,
            unlet_only=vacant,
            expired_days=VACANT_LOOKBACK_DAYS_DEFAULT if vacant else 365,
            area=area,
            property_type=property_type,
            project=project,
            building=building,
            limit=limit,
            offset=offset,
            unit_keys=unit_keys,
            exclude_units=exclude_units,
        )
    except Exception as exc:
        raise lead_data_error(exc, "renewals") from exc
    return empty.model_copy(
        update={
            "leads": [_lead_from_row(row) for row in rows],
            "total": int(total),
            "property_types": list(facets.get("property_types") or []),
            "projects": list(facets.get("projects") or []),
            "buildings": list(facets.get("buildings") or []),
        }
    )


async def list_owner_renewals(
    db: AsyncSession,
    *,
    user_id: str,
    organization_id: str,
    window: str | None,
    area: str | None,
    property_type: str | None,
    project: str | None,
    building: str | None,
    limit: int,
    offset: int,
    as_of: date | None = None,
    owner: Literal["known", "unknown"] = "known",
) -> CrmRenewalsResponse:
    """Assets › Renewals, split by whether the agency has the unit's owner on file.

    known: units with a current owner in the owner imports, each with that owner's contact
    (client, 3 Nov: someone the agency can call as the lease ends).
    unknown: every other lease, the units whose owner is still to be found.
    """
    imported_keys = await renewal_repository.list_imported_unit_keys(db, organization_id)
    known_owners = await _owners_by_candidate(
        db, candidate_keys=imported_keys, user_id=user_id, organization_id=organization_id
    )
    keys = sorted(known_owners)
    if owner == "unknown":
        return await list_renewals(
            window=window,
            area=area,
            property_type=property_type,
            project=project,
            building=building,
            limit=limit,
            offset=offset,
            as_of=as_of,
            unit_keys=keys,
            exclude_units=True,
        )
    if not keys:
        # No filter would mean every lease in Dubai, so an agency without owner imports sees none.
        anchor = as_of or date.today()
        return CrmRenewalsResponse(leads=[], total=0, limit=limit, offset=offset, as_of=anchor)
    res = await list_renewals(
        window=window,
        area=area,
        property_type=property_type,
        project=project,
        building=building,
        limit=limit,
        offset=offset,
        as_of=as_of,
        unit_keys=keys,
    )
    candidate_keys = [lead.unit_candidate_key for lead in res.leads]
    changed_keys = sorted(set(candidate_keys) - set(keys))
    aliases = (
        await opportunity_queries.fetch_owner_unit_aliases(changed_keys, keys)
        if changed_keys
        else []
    )
    owners = dict(known_owners)
    for row in aliases:
        if row["candidate_key"] not in owners and row["owner_candidate_key"] in owners:
            owners[row["candidate_key"]] = owners[row["owner_candidate_key"]]
    return res.model_copy(
        update={"owners": {key: owners[key] for key in candidate_keys if key in owners}}
    )


async def _owners_by_candidate(
    db: AsyncSession,
    *,
    candidate_keys: list[str],
    user_id: str,
    organization_id: str,
) -> dict[str, CrmRenewalOwner]:
    """Manual owner fields override a single supported current imported identity."""
    if not candidate_keys:
        return {}
    candidate_keys = sorted(set(candidate_keys))
    owners: dict[str, CrmRenewalOwner] = {}
    rows = []
    if await renewal_repository.has_imported_unit_keys(db, organization_id, candidate_keys):
        store = await open_store(db, organization_id)
        rows = await store.renewal_rows(candidate_keys)
    requested = set(candidate_keys)
    by_unit: dict[str, dict[str, list[dict]]] = {}
    for row in rows:
        key = row.get("unit_candidate_key")
        if (
            key in requested
            and row["property_identity"] is not None
            and row["assessed_status"]
            in {"verified_current_owner", "probable_current_owner", "conflicting_claim"}
            and row.get("event_assessed_status", row["assessed_status"])
            in {"verified_current_owner", "probable_current_owner", "conflicting_claim"}
        ):
            by_unit.setdefault(key, {}).setdefault(row["canonical_owner_key"], []).append(row)
    for key, candidates in by_unit.items():
        verified = {
            person: [
                row
                for row in events
                if row["assessed_status"] == "verified_current_owner"
                and row.get("event_assessed_status", row["assessed_status"])
                == "verified_current_owner"
                and row.get("party_role") == "Buyer"
            ]
            for person, events in candidates.items()
        }
        verified = {person: events for person, events in verified.items() if events}
        if len(verified) != 1 or len(candidates) > 2:
            continue
        if any(
            row["assessed_status"] == "conflicting_claim"
            or row.get("event_assessed_status") == "conflicting_claim"
            for events in candidates.values()
            for row in events
        ):
            continue
        person, buyer_events = next(iter(verified.items()))
        other_events = [
            row for key, events in candidates.items() if key != person for row in events
        ]
        # A tentative Seller on the uniquely paired sale does not compete with
        # its verified Buyer. Other people or sale anchors still prevent autofill.
        if any(
            row.get("party_role") != "Seller"
            or row["assessed_status"] != "probable_current_owner"
            or row.get("event_assessed_status", row["assessed_status"]) != "probable_current_owner"
            or not any(
                buyer.get("sale_anchor_key")
                and buyer.get("sale_anchor_date")
                and row.get("sale_anchor_key") == buyer["sale_anchor_key"]
                and row.get("sale_anchor_date") == buyer["sale_anchor_date"]
                and row["property_identity"] == buyer["property_identity"]
                and buyer.get("transaction_date")
                and row.get("transaction_date") == buyer.get("transaction_date")
                and int(row.get("transaction_price_aed") or 0) > 0
                and int(buyer.get("transaction_price_aed") or 0) > 0
                for buyer in buyer_events
            )
            for row in other_events
        ):
            continue
        claim = max(
            buyer_events, key=lambda row: (row.get("transaction_date") or date.min, row["id"])
        )
        phone = _normalize_phone(claim.get("phone_primary")) or _normalize_phone(
            claim.get("phone_alternate")
        )
        email = _normalize_email(claim.get("email_primary"))
        if not (phone or email) or not claim.get("lead_id"):
            continue
        owners[key] = CrmRenewalOwner(
            name=claim["contact_name"] or None,
            phone=phone,
            email=email,
            source="owner_import",
        )
    workspaces = []
    # The repository expands IN values into parameters; all imported units can exceed
    # asyncpg's 32,767-parameter limit, even though only a few have saved workspaces.
    for start in range(0, len(candidate_keys), 10_000):
        workspaces.extend(
            await workspace_repository.list_lead_workspaces_for_candidates(
                db, candidate_keys[start : start + 10_000], organization_id, user_id
            )
        )
    for workspace in workspaces:
        is_manual = workspace.owner_source == "manual" or (
            workspace.owner_source is None and "Imported owner" not in (workspace.tags or [])
        )
        if is_manual and (workspace.owner_name or workspace.owner_phone or workspace.owner_email):
            owners[workspace.unit_candidate_key] = CrmRenewalOwner(
                name=workspace.owner_name,
                phone=workspace.owner_phone,
                email=workspace.owner_email,
                source="workspace",
            )
        elif workspace.owner_source == "manual":
            # An explicit manual clear is an override too. An untouched empty
            # legacy workspace (source=None) must still allow a later import.
            owners.pop(workspace.unit_candidate_key, None)
    return owners


async def get_renewal_detail(
    db: AsyncSession,
    *,
    lead_id: str,
    user_id: str,
    organization_id: str,
    as_of: date | None = None,
):
    detail = await get_lead_detail(lead_id, as_of=as_of)
    owners = await _owners_by_candidate(
        db,
        candidate_keys=[detail.lead.unit_candidate_key],
        user_id=user_id,
        organization_id=organization_id,
    )
    return detail.model_copy(update={"owner": owners.get(detail.lead.unit_candidate_key)})


async def list_renewal_leads(
    db: AsyncSession,
    *,
    user_id: str,
    organization_id: str,
    limit: int,
    offset: int,
    as_of: date | None = None,
    kind: str | None = None,
) -> CrmRenewalLeadsResponse:
    anchor = as_of or date.today()
    preferences = await get_area_preferences(db, user_id=user_id, organization_id=organization_id)
    empty = CrmRenewalLeadsResponse(
        items=[],
        total=0,
        limit=limit,
        offset=offset,
        entered_today=0,
        preferences=preferences,
        as_of=anchor,
        kind=kind or "all",
    )
    if not preferences.areas:
        return empty
    if not await opportunity_queries._tables_exist():
        raise not_loaded()
    try:
        lead_rows, count_rows = await opportunity_queries.fetch_renewal_leads(
            anchor,
            preferences.areas,
            preferences.forward_days,
            preferences.lookback_days,
            limit,
            offset,
            kind=kind,
        )
    except Exception as exc:
        raise lead_data_error(exc, "renewal leads") from exc
    leads = [_lead_from_row(row) for row in lead_rows]
    owners = await _owners_by_candidate(
        db,
        candidate_keys=sorted({lead.unit_candidate_key for lead in leads}),
        user_id=user_id,
        organization_id=organization_id,
    )
    opened = {
        enquiry.source_lead_id: enquiry.id
        for enquiry in await inbound_repository.list_vitevue_lease_enquiries(
            db, organization_id, {lead.unit_candidate_key for lead in leads}
        )
    }
    counts = count_rows[0] if count_rows else {}
    return empty.model_copy(
        update={
            "items": [
                CrmRenewalLead(
                    lead=lead,
                    owner=owners.get(lead.unit_candidate_key),
                    lead_record_id=opened.get(lead.unit_candidate_key),
                )
                for lead in leads
            ],
            "total": int(counts.get("total") or 0),
            "entered_today": int(counts.get("entered_today") or 0),
            "counts": CrmRenewalLeadCounts(
                **{name: int(counts.get(name) or 0) for name in CrmRenewalLeadCounts.model_fields}
            ),
        }
    )


async def open_renewal_lead(
    db: AsyncSession, *, lease_id: str, user_id: str, organization_id: str
) -> InboundEnquiryResponse:
    """Turn a Vitevue lease into the agency's shared lead for its unit, or return the one there.

    The lead starts undecided (seller or landlord) and carries the unit, its last tenancy and
    last purchase. The owner comes from manual workspace fields or a reliable current-owner
    import match; otherwise it stays blank for the agent to fill in.
    """
    detail = await get_lead_detail(lease_id)
    lead = detail.lead
    if not lead.unit_number:
        raise HTTPException(status_code=422, detail="This lease has no unit number")
    owners = await _owners_by_candidate(
        db,
        candidate_keys=[lead.unit_candidate_key],
        user_id=user_id,
        organization_id=organization_id,
    )
    owner = owners.get(lead.unit_candidate_key)
    criteria = {
        "building": lead.building_name or lead.project_name,
        "unit_number": lead.unit_number,
        "locations": [lead.area_name],
        "property_type": lead.property_subtype,
        "bedrooms": lead.bedrooms,
        "size_sqft": lead.size_sqft,
    }
    lease = {
        "lease_id": lead.lead_id,
        "lease_start": lead.lease_start.isoformat(),
        "lease_end": lead.lease_end.isoformat(),
        "annual_rent_aed": lead.annual_rent_aed,
        "vacant": lead.lease_evidence_state == "unlet_signal",
        "last_purchase_date": (
            lead.last_purchase_date.isoformat() if lead.last_purchase_date else None
        ),
        "last_purchase_price_aed": lead.latest_purchase_price_aed or lead.matched_sale_price_aed,
    }
    return await inbound.open_vitevue_lease_enquiry(
        db,
        organization_id=organization_id,
        user_id=user_id,
        unit_key=lead.unit_candidate_key,
        owner_name=(owner.name or "") if owner else "",
        owner_phone=owner.phone if owner else None,
        owner_email=owner.email if owner else None,
        owner_source=owner.source if owner else None,
        criteria={key: value for key, value in criteria.items() if value},
        lease=lease,
    )
