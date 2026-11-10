"""The whole-snapshot read paths as they were before the assessment was stored.

Kept only as the oracle the stored reads are compared with: each function reads
``SNAPSHOT`` (set by the test) where it used to build or fetch the tenant's snapshot.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from fastapi import HTTPException
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.async_work import run_in_thread
from app.crm import import_repository, owner_repository, workspace_repository
from app.crm.identity import _claim_owner_key, _claim_preference, _location_key, has_usable_contact
from app.crm.import_models import (
    CrmContactList,
    CrmContactListDetail,
    CrmContactListSummary,
    CrmImportPropertiesResponse,
    CrmLeadImportedContact,
    CrmOwnerHistoryEvent,
    CrmOwnerHistoryResponse,
    CrmOwnerHistorySummary,
    CrmOwnerProfile,
    CrmOwnerRegistryResponse,
    CrmOwnerWorkspaceSummary,
    CrmPropertyContactClaim,
)
from app.crm.imports import _PROPERTY_RECORDS_MAX, _group_properties
from app.crm.owner_assessment import OwnerAssessmentSnapshot, summarize_assessment_rows
from app.crm.owner_history import _family, _property_identity
from app.crm.owners import (
    _assessed_contact_groups,
    _assessed_list_summary,
    _assessed_profiles,
    _assessed_property_matches,
    _assessed_row_preference,
    _claim_duplicate_count,
    _claim_response,
    _owner_read_keys,
    _owner_registry_summary,
    _profile_search_matches,
    _profile_with_properties,
    _projected_claims,
    _source_contact_ready,
)
from app.crm.workspaces import _owner_workspace_summaries

SNAPSHOT = None


async def _profiles_for_snapshot(snapshot):
    return _build_snapshot_profiles(snapshot)


async def list_contact_lists(
    db: AsyncSession,
    *,
    organization_id: str,
) -> list[CrmContactListSummary]:
    list_result = await owner_repository.list_contact_lists(db, organization_id)
    contact_lists = list(list_result)
    if not contact_lists:
        return []
    snapshot = SNAPSHOT
    grouped: dict[int, list[dict[str, Any]]] = {}
    for row in snapshot.rows:
        grouped.setdefault(row["list_id"], []).append(row)
    return [_assessed_list_summary(item, grouped.get(item.id or 0, [])) for item in contact_lists]


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
    snapshot = SNAPSHOT
    all_rows = [row for row in snapshot.rows if row["list_id"] == list_id]
    matching_rows = all_rows
    if search:
        term = search.strip().casefold()
        matching_rows = [
            row
            for row in matching_rows
            if term
            in " ".join(
                str(row.get(field) or "")
                for field in (
                    "contact_name",
                    "phone_primary",
                    "phone_alternate",
                    "email_primary",
                    "area_name",
                    "building_name",
                    "project_name",
                    "unit_number",
                )
            ).casefold()
        ]
    groups = _assessed_contact_groups(matching_rows)
    if status:
        groups = [group for group in groups if group[0]["assessed_status"] == status]
    # The row a group shows decides its match filters, as it decides the fields shown.
    for field_name, wanted in (("match_colour", match_colour), ("match_outcome", match_outcome)):
        if wanted:
            groups = [
                group
                for group in groups
                if max(group, key=_assessed_row_preference).get(field_name) in wanted
            ]
    visible = groups[offset : offset + limit]
    selected = [max(group, key=_assessed_row_preference) for group in visible]
    claims = await owner_repository.list_claims_by_ids(
        db, organization_id, [row["id"] for row in selected]
    )
    projected = {claim.id: claim for claim in _projected_claims(list(claims), snapshot.rows)}
    contacts = []
    for row, group in zip(selected, visible, strict=True):
        claim = projected.get(row["id"])
        if claim is None:
            continue
        response = _claim_response(claim)
        response.duplicate_count = len(group)
        response.source_rows = sorted(
            {f"{event['source_sheet']}:{event['source_row_number']}" for event in group}
        )
        contacts.append(response)
    return CrmContactListDetail(
        list=_assessed_list_summary(contact_list, all_rows),
        contacts=contacts,
        total=len(groups),
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
    snapshot = SNAPSHOT
    by_id = {claim.id: contact_list for claim, contact_list in rows}
    linked_ids = {
        row["id"]
        for row in snapshot.rows
        if row.get("lead_id") == lead_id
        and row.get("unit_candidate_key")
        and row["property_identity"] is not None
    }
    projected = _projected_claims(
        [claim for claim, _ in rows if claim.id in linked_ids], snapshot.rows
    )
    grouped: dict[tuple[str, str], list[tuple[CrmPropertyContactClaim, CrmContactList]]] = {}
    for claim in projected:
        grouped.setdefault((claim.owner_key, claim.property_key), []).append(
            (claim, by_id[claim.id])
        )
    read_keys = _owner_read_keys(snapshot.rows)
    property_sets: dict[str, set[tuple[str, str]]] = {}
    for row in snapshot.rows:
        if row["property_identity"] is not None:
            property_sets.setdefault(read_keys[row["canonical_owner_key"]], set()).add(
                tuple(row["property_identity"])
            )
    property_counts = {key: len(identities) for key, identities in property_sets.items()}

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


def _build_snapshot_profiles(snapshot: OwnerAssessmentSnapshot) -> dict[str, CrmOwnerProfile]:
    profiles = _assessed_profiles(snapshot.rows, snapshot=snapshot)
    by_read_key = {profile.owner_key: profile for profile in profiles}
    return {
        canonical: by_read_key[read_key]
        for canonical, read_key in _owner_read_keys(snapshot.rows).items()
        if read_key in by_read_key
    }


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
    snapshot = SNAPSHOT
    full_profiles = await _profiles_for_snapshot(snapshot)
    if list_id is None:
        profiles = list(full_profiles.values())
    else:
        rows = [row for row in snapshot.rows if row["list_id"] == list_id]
        profiles = await run_in_thread(
            _assessed_profiles, rows, identity_rows=snapshot.rows, snapshot=snapshot
        )
    full_by_key = {profile.owner_key: profile for profile in full_profiles.values()}
    summary = _owner_registry_summary(profiles)
    filtered = []
    for profile in profiles:
        if scope == "prior_owners" and profile.developer_side_seller:
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
        invalid_review = (
            (
                not profile.properties
                or (
                    scope == "needs_review"
                    and profile.history_summary
                    and profile.history_summary.invalid_identity_source_count
                )
            )
            and scope in {"all", "registry", "needs_review"}
            and not transaction_match_status
            and status in {None, "insufficient_property_data"}
            and (not search or _profile_search_matches(profile, search))
            and not any(
                value is not None
                for value in (
                    lease_window,
                    min_rent_aed,
                    max_rent_aed,
                    min_value_aed,
                    max_value_aed,
                )
            )
        )
        if not properties and not invalid_review:
            continue
        full = full_by_key[profile.owner_key]
        scoped = (
            _profile_with_properties(profile, properties).model_copy(
                update={"total_property_count": full.property_count}
            )
            if scope in {"current_owners", "prior_owners"} or transaction_match_status
            else full
        )
        if portfolio_only and scoped.property_count < 2:
            continue
        if min_properties is not None and scoped.property_count < min_properties:
            continue
        if next_event_days is not None and (
            scoped.next_lease_end is None
            or not date.today()
            <= scoped.next_lease_end
            <= date.today() + timedelta(days=next_event_days)
        ):
            continue
        filtered.append(scoped)
    filtered.sort(
        key=lambda profile: (
            -profile.contact_ready_count,
            -profile.property_count,
            -profile.highest_confidence_score,
            profile.next_lease_end or date.max,
            profile.owner_key,
        )
    )
    from app.crm.source_audit import aggregate_source_audit

    source_audit = aggregate_source_audit(snapshot.rows, list_id)
    return CrmOwnerRegistryResponse(
        source_audit=source_audit,
        scope=scope,  # type: ignore[arg-type]
        owners=[profile.model_copy(deep=True) for profile in filtered[offset : offset + limit]],
        total=len(filtered),
        limit=limit,
        offset=offset,
        summary=summary,
    )


async def list_import_properties(
    db: AsyncSession,
    *,
    import_id: int,
    organization_id: str,
    search: str | None,
    limit: int,
    offset: int,
) -> CrmImportPropertiesResponse:
    """One page of an import's distinct properties, each with its kept rows."""
    record = await import_repository.get_import_for_org(db, import_id, organization_id)
    if not record:
        raise HTTPException(status_code=404, detail="Owner-data import not found")
    snapshot = SNAPSHOT
    current_by_property = {}
    for row in snapshot.rows:
        if row["property_identity"] is not None and row["assessed_status"] in {
            "verified_current_owner",
            "probable_current_owner",
            "conflicting_claim",
        }:
            current_by_property.setdefault(tuple(row["property_identity"]), {}).setdefault(
                row["canonical_owner_key"], []
            ).append(row)
    grouped = {}
    for row in snapshot.rows:
        if row["import_id"] != import_id or row["property_identity"] is None:
            continue
        if (
            search
            and search.strip().casefold()
            not in " ".join(
                str(row.get(field) or "")
                for field in (
                    "contact_name",
                    "area_name",
                    "building_name",
                    "project_name",
                    "unit_number",
                )
            ).casefold()
        ):
            continue
        grouped.setdefault(tuple(row["property_identity"]), []).append(row)
    groups = sorted(
        grouped.values(),
        key=lambda rows: (
            str(rows[0].get("building_name") or rows[0].get("project_name") or "").casefold(),
            str(rows[0].get("unit_number") or "").casefold(),
            str(rows[0].get("area_name") or "").casefold(),
        ),
    )
    visible = groups[offset : offset + limit]
    selected = []
    for group in visible:
        ordered = sorted(
            group,
            key=lambda row: (
                row.get("transaction_date") or date.min,
                row["source_row_number"],
                row["id"],
            ),
            reverse=True,
        )
        selected.extend(ordered[:_PROPERTY_RECORDS_MAX])
    # Fetch original property/source metadata only for the displayed records.
    # The shared assessment supplies all counts and classifications for the file.
    claims = await owner_repository.list_claims_by_ids(
        db, organization_id, [row["id"] for row in selected]
    )
    properties = _group_properties(_projected_claims(list(claims), snapshot.rows))
    by_identity = {(item.property_key, _location_key(item.area)): item for item in properties}
    ordered_properties = []
    for group in visible:
        first = group[0]
        item = by_identity.get((first["property_key"], _location_key(first["area_name"])))
        if item is None:
            continue
        candidates = current_by_property.get(tuple(first["property_identity"]), {})
        current = next(iter(candidates.values())) if len(candidates) == 1 else []
        item.current_owner = (
            current[0]["contact_name"]
            if current
            and all(row["assessed_status"] == "verified_current_owner" for row in current)
            else None
        )
        item.rows = len(group)
        item.buyers = sum(row["party_role"] == "Buyer" for row in group)
        item.sellers = sum(row["party_role"] == "Seller" for row in group)
        item.records_truncated = len(group) > _PROPERTY_RECORDS_MAX
        ordered_properties.append(item)
    return CrmImportPropertiesResponse(
        total=len(groups),
        offset=offset,
        limit=limit,
        rows=ordered_properties,
    )


async def get_owner_history_summary(
    db: AsyncSession,
    *,
    organization_id: str,
    import_id: int | None = None,
) -> CrmOwnerHistorySummary:
    if import_id is not None and not await owner_repository.owner_history_import_exists(
        db, organization_id, import_id
    ):
        raise HTTPException(status_code=404, detail="CRM contact import not found")
    snapshot = SNAPSHOT
    if import_id is None:
        return snapshot.summary
    selected = [row for row in snapshot.rows if row["import_id"] == import_id]
    return summarize_assessment_rows(snapshot, selected)


async def get_owner_history(
    db: AsyncSession,
    *,
    organization_id: str,
    owner_key: str,
    import_id: int | None = None,
    limit: int = 50,
    offset: int = 0,
) -> CrmOwnerHistoryResponse:
    if import_id is not None and not await owner_repository.owner_history_import_exists(
        db, organization_id, import_id
    ):
        raise HTTPException(status_code=404, detail="CRM contact import not found")
    snapshot = SNAPSHOT
    canonical = {
        row["canonical_owner_key"]
        for row in snapshot.rows
        if row["owner_key"] == owner_key or row["canonical_owner_key"] == owner_key
    }
    if not canonical:
        raise HTTPException(status_code=404, detail="Owner profile not found")
    if len(canonical) > 1:
        raise HTTPException(status_code=409, detail="Choose a distinct canonical owner identity")
    selected = [
        row
        for row in snapshot.rows
        if row["canonical_owner_key"] in canonical
        and (import_id is None or row["import_id"] == import_id)
    ]
    summary = summarize_assessment_rows(snapshot, selected)
    selected.sort(
        key=lambda row: (
            row.get("transaction_date") or date.min,
            row["import_id"],
            row["source_sheet"],
            row["source_row_number"],
            row["id"],
        ),
        reverse=True,
    )
    events = []
    for row in selected[offset : offset + limit]:
        identity = _property_identity(row)
        status, reason = (
            (row["assessed_status"], row["assessed_reason"])
            if identity is not None
            else (
                "insufficient_property_data",
                "The source event has no valid scoped property identity and is excluded from property counts.",
            )
        )
        events.append(
            CrmOwnerHistoryEvent(
                **{
                    name: row[name]
                    for name in (
                        "id",
                        "import_id",
                        "source_filename",
                        "source_sheet",
                        "source_row_number",
                        "contact_name",
                        "area_name",
                        "project_name",
                        "building_name",
                        "unit_number",
                        "property_type",
                        "party_role",
                        "procedure_type",
                        "transaction_date",
                        "transaction_price_aed",
                        "confidence_score",
                    )
                },
                property_key=row["property_key"] if identity is not None else None,
                event_family=_family(row),
                observed_ownership_status=row["ownership_status"],
                current_ownership_status=status,
                evidence_reason=row["match_reason"],
                current_evidence_reason=reason,
                resolver_version=row.get("claim_resolver_version")
                or row.get("import_resolver_version"),
            )
        )
    return CrmOwnerHistoryResponse(
        owner_key=owner_key,
        summary=summary,
        events=events,
        total=len(selected),
        limit=limit,
        offset=offset,
    )


async def list_owner_workspaces(
    db: AsyncSession,
    *,
    user_id: str,
    organization_id: str,
) -> list[CrmOwnerWorkspaceSummary]:
    workspace_result = await workspace_repository.list_owner_workspaces(
        db, organization_id, user_id
    )
    workspaces = list(workspace_result)
    if not workspaces:
        return []
    workspace_ids = [item.id for item in workspaces if item.id is not None]
    note_result = await workspace_repository.list_owner_notes(
        db, organization_id, user_id, workspace_ids
    )
    summaries = _owner_workspace_summaries(workspaces, list(note_result))
    snapshot = SNAPSHOT
    read_keys = _owner_read_keys(snapshot.rows)
    aliases: dict[str, set[str]] = {}
    ready_keys: set[str] = set()
    for row in snapshot.rows:
        canonical = row["canonical_owner_key"]
        aliases.setdefault(row["owner_key"], set()).add(canonical)
        if (
            row["property_identity"] is not None
            and row.get("lead_id")
            and row.get("unit_candidate_key")
            and _source_contact_ready(row["assessed_status"], row.get("party_role"))
            and _source_contact_ready(
                row.get("event_assessed_status", row["assessed_status"]), row.get("party_role")
            )
            and has_usable_contact(
                row.get("phone_primary"),
                row.get("phone_alternate"),
                row.get("email_primary"),
                row.get("broker_contact"),
            )
        ):
            ready_keys.add(read_keys[canonical])
    merged: dict[str, CrmOwnerWorkspaceSummary] = {}
    for summary in summaries:
        canonical = aliases.get(summary.owner_key, set())
        key = read_keys[next(iter(canonical))] if len(canonical) == 1 else summary.owner_key
        summary = summary.model_copy(update={"owner_key": key})
        if summary.pipeline_status == "contact_ready" and key not in ready_keys:
            summary.pipeline_status = "researching"
            if summary.highlight_color == "green":
                summary.highlight_color = "none"
        previous = merged.get(key)
        if previous is None:
            merged[key] = summary
        else:
            previous.note_count += summary.note_count
            if previous.last_note is None:
                previous.last_note = summary.last_note
            previous.tags = list(dict.fromkeys(previous.tags + summary.tags))[:12]
    return list(merged.values())
