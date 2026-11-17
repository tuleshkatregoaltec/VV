"""Tenant-scoped ownership history from the shared registry assessment."""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import HTTPException
from sqlmodel.ext.asyncio.session import AsyncSession

from app.crm import owner_repository
from app.crm.identity import _normalize_email, _normalize_phone
from app.crm.import_models import (
    CrmOwnerHistoryEvent,
    CrmOwnerHistoryResponse,
    CrmOwnerHistorySummary,
)
from app.crm.owner_projection import _family, _projection_owner_key, _property_identity
from app.crm.owner_projection import project_owner_history as project_owner_history


async def _history_rows(
    db: AsyncSession,
    *,
    organization_id: str,
    owner_key: str | None,
    import_id: int | None,
    include_source_details: bool = True,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if import_id is not None and not await owner_repository.owner_history_import_exists(
        db, organization_id, import_id
    ):
        raise HTTPException(status_code=404, detail="CRM contact import not found")
    arguments = dict(
        organization_id=organization_id,
        owner_key=owner_key,
        import_id=import_id,
        include_source_details=include_source_details,
    )
    selected = await owner_repository.list_owner_history_rows(db, **arguments)
    context = selected
    if owner_key is not None:
        seeds = selected
        context_arguments = {**arguments, "import_id": None}
        if import_id is not None:
            seeds = await owner_repository.list_owner_history_rows(db, **context_arguments)
        if seeds:
            phones = {
                phone
                for row in seeds
                if (
                    phone := _normalize_phone(row.get("phone_primary"))
                    or _normalize_phone(row.get("phone_alternate"))
                )
            }
            digits = {phone.lstrip("+") for phone in phones}
            digits |= {"00" + value for value in list(digits)}
            digits |= {"0" + phone[4:] for phone in phones if phone.startswith("+971")}
            digits |= {phone[4:] for phone in phones if phone.startswith("+971")}
            emails = {_normalize_email(row.get("email_primary")) for row in seeds} - {None}
            context = await owner_repository.list_owner_history_rows(
                db,
                **context_arguments,
                property_context=True,
                canonical_phone_digits=sorted(digits),
                canonical_emails=sorted(emails),
            )
            canonical = {_projection_owner_key(row) for row in seeds}
            selected = [
                row
                for row in context
                if _projection_owner_key(row) in canonical
                and (import_id is None or row["import_id"] == import_id)
            ]
            extra_keys = {row["property_key"] for row in selected} - {
                row["property_key"] for row in seeds
            }
            if extra_keys:
                expanded = await owner_repository.list_owner_history_rows(
                    db,
                    **context_arguments,
                    property_context=True,
                    additional_property_keys=sorted(extra_keys),
                )
                context = list({row["id"]: row for row in context + expanded}.values())
    elif selected and import_id is not None:
        context = await owner_repository.list_owner_history_rows(
            db, **arguments, property_context=True
        )
        identities = {_property_identity(row) for row in selected} - {None}
        context = selected + [row for row in context if _property_identity(row) in identities]
    return selected, context


async def get_owner_history_summary(
    db: AsyncSession,
    *,
    organization_id: str,
    import_id: int | None = None,
) -> CrmOwnerHistorySummary:
    from app.crm.owner_assessment import summarize_assessment_rows
    from app.crm.owner_store import open_store

    if import_id is not None and not await owner_repository.owner_history_import_exists(
        db, organization_id, import_id
    ):
        raise HTTPException(status_code=404, detail="CRM contact import not found")
    store = await open_store(db, organization_id)
    if import_id is None:
        return CrmOwnerHistorySummary.model_validate(store.state.summary)
    stored = store.state.import_summaries.get(str(import_id))
    if stored is not None:
        return CrmOwnerHistorySummary.model_validate(stored)
    return summarize_assessment_rows(store.snapshot_stub(), [])


async def get_owner_history(
    db: AsyncSession,
    *,
    organization_id: str,
    owner_key: str,
    import_id: int | None = None,
    limit: int = 50,
    offset: int = 0,
) -> CrmOwnerHistoryResponse:
    from app.crm.owner_assessment import summarize_assessment_rows
    from app.crm.owner_store import open_store

    if import_id is not None and not await owner_repository.owner_history_import_exists(
        db, organization_id, import_id
    ):
        raise HTTPException(status_code=404, detail="CRM contact import not found")
    store = await open_store(db, organization_id)
    canonical = await store.canonical_owners(owner_key)
    if not canonical:
        raise HTTPException(status_code=404, detail="Owner profile not found")
    if len(canonical) > 1:
        raise HTTPException(status_code=409, detail="Choose a distinct canonical owner identity")
    selected = [
        row
        for row in await store.owner_rows(canonical)
        if import_id is None or row["import_id"] == import_id
    ]
    summary = summarize_assessment_rows(store.snapshot_stub(), selected)
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
