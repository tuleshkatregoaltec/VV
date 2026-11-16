"""Owner DB: a manager issues owners from a processed owner sheet to agents as outbound leads.

Each owner becomes one lead for outbound contact (source OWNER_OUTBOUND_SOURCE, keyed by the
owner), carrying their contact details and the unit they own, and is routed with the same
choices and checks as a Leads import. An owner already issued keeps their lead; one an agent
already holds is left alone.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException
from pydantic import BaseModel, Field
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.crm import inbound_imports, inbound_repository, owner_repository, routing
from app.crm.identity import _normalize_email, _normalize_phone
from app.crm.import_models import CrmContactClaimResponse, CrmOwnershipStatus
from app.crm.inbound_models import (
    OWNER_OUTBOUND_SOURCE,
    CrmInboundActivity,
    CrmInboundContact,
    CrmInboundEnquiry,
    InboundImportAssignmentSummary,
)
from app.crm.owners import _claim_response, get_contact_list
from app.crm.routing_models import ImportAssignmentPolicy

MAX_OWNER_ISSUE = 500


class OwnerIssueRequest(BaseModel):
    # Chosen owner rows of this sheet; omitted issues the sheet's owners with `status`.
    claim_ids: list[int] | None = Field(default=None, min_length=1, max_length=MAX_OWNER_ISSUE)
    status: CrmOwnershipStatus | None = "verified_current_owner"
    # How many owners of the sheet to issue when no rows are chosen (first ones in list order).
    limit: int = Field(default=100, ge=1, le=MAX_OWNER_ISSUE)
    # Where this batch starts in the sheet's owners, to continue after an earlier batch.
    offset: int = Field(default=0, ge=0)
    assignment: ImportAssignmentPolicy


class OwnerIssueResponse(BaseModel):
    requested: int
    issued: int
    # Owners whose lead an agent already holds or that sits in a team pool; left as they are.
    already_assigned: int
    # Owner rows with no phone or email to contact.
    skipped: int
    # Sheet owners matching the filter beyond this batch, and where the next batch starts.
    remaining: int
    next_offset: int | None = None
    enquiry_ids: list[int]
    assignment: InboundImportAssignmentSummary


async def _owners(
    db: AsyncSession, list_id: int, organization_id: str, request: OwnerIssueRequest
) -> tuple[list[CrmContactClaimResponse], int]:
    """The owner rows to issue and how many more the sheet holds beyond them."""
    if request.claim_ids is not None:
        claims = await owner_repository.list_claims_by_ids(
            db, organization_id, list(dict.fromkeys(request.claim_ids))
        )
        rows = [_claim_response(claim) for claim in claims if claim.list_id == list_id]
        if not rows:
            raise HTTPException(status_code=404, detail="None of those owners are in this sheet")
        return rows, 0
    detail = await get_contact_list(
        db,
        list_id=list_id,
        organization_id=organization_id,
        status=request.status,
        search=None,
        limit=request.limit,
        offset=request.offset,
    )
    return detail.contacts, max(0, detail.total - request.offset - len(detail.contacts))


def _owner_key(row: CrmContactClaimResponse) -> str:
    return row.owner_key or f"claim:{row.id}"


def _criteria(row: CrmContactClaimResponse) -> dict:
    criteria = {
        "building": row.building_name or row.project_name,
        "unit_number": row.unit_number,
        "locations": [row.area_name] if row.area_name else [],
        "property_type": row.property_type,
    }
    return {key: value for key, value in criteria.items() if value}


async def _existing(
    db: AsyncSession, organization_id: str, keys: list[str]
) -> dict[str, CrmInboundEnquiry]:
    rows = (
        await db.exec(
            select(CrmInboundEnquiry).where(
                CrmInboundEnquiry.organization_id == organization_id,
                CrmInboundEnquiry.source == OWNER_OUTBOUND_SOURCE,
                CrmInboundEnquiry.source_lead_id.in_(keys),  # type: ignore[union-attr]
            )
        )
    ).all()
    return {row.source_lead_id or "": row for row in rows}


async def issue_owner_leads(
    db: AsyncSession,
    *,
    list_id: int,
    request: OwnerIssueRequest,
    user_id: str,
    organization_id: str,
) -> OwnerIssueResponse:
    contact_list = await owner_repository.get_contact_list(db, list_id, organization_id)
    if not contact_list:
        raise HTTPException(status_code=404, detail="Owner sheet not found")
    policy = request.assignment
    # Permission, team and rules are checked before any lead is created.
    pool_team, rules = await inbound_imports._resolve_policy(db, organization_id, user_id, policy)
    rows, remaining = await _owners(db, list_id, organization_id, request)

    # One lead per owner, even when they own several units in the sheet (the first row speaks).
    by_owner: dict[str, CrmContactClaimResponse] = {}
    skipped = 0
    for row in rows:
        if not (row.phone_primary or row.phone_alternate or row.email_primary):
            skipped += 1
            continue
        by_owner.setdefault(_owner_key(row), row)
    existing = await _existing(db, organization_id, list(by_owner))

    now = datetime.now(timezone.utc)
    routed: list[tuple[CrmInboundEnquiry, str | None, routing.RuleSnapshot | None, str | None]] = []
    already_assigned = 0
    for key, row in by_owner.items():
        enquiry = existing.get(key)
        if enquiry is not None and (
            enquiry.assigned_user_id is not None or enquiry.pool_released_at is not None
        ):
            already_assigned += 1
            continue
        if enquiry is None:
            contact = CrmInboundContact(
                organization_id=organization_id,
                full_name=row.contact_name or "",
                phone=_normalize_phone(row.phone_primary or row.phone_alternate),
                email=_normalize_email(row.email_primary),
                created_at=now,
                updated_at=now,
            )
            inbound_repository.save(db, contact)
            await db.flush()
            enquiry = CrmInboundEnquiry(
                organization_id=organization_id,
                contact_id=contact.id or 0,
                created_by_user_id=user_id,
                assigned_user_id=None,
                record_kind="unqualified_contact",
                intent="unknown",
                status="new",
                source=OWNER_OUTBOUND_SOURCE,
                campaign=contact_list.name,
                source_lead_id=key,
                enquiry_date=now,
                criteria=_criteria(row),
                strict_fields=[],
                observed_data={
                    "owner_sheet": {
                        "list_id": list_id,
                        "list_name": contact_list.name,
                        "claim_id": row.id,
                        "ownership_status": row.ownership_status,
                    }
                },
                confirmed_data={},
                qualification={},
                extraction_confidence=1,
                created_at=now,
                updated_at=now,
            )
            inbound_repository.save(db, enquiry)
            await db.flush()
        else:
            contact = await inbound_repository.get_crm_inbound_contact(db, enquiry.contact_id)
        if policy.mode == "self":
            routed.append((enquiry, user_id, None, None))
        elif policy.mode == "agent":
            routed.append((enquiry, policy.assignee_user_id, None, None))
        elif policy.mode == "rules":
            rule = routing.first_match(rules, enquiry, contact)
            language = routing.lead_language(contact) if rule and rule.speakers_only else None
            routed.append((enquiry, rule.destination_user_id if rule else None, rule, language))
        else:
            routed.append((enquiry, None, None, None))
        inbound_repository.save(
            db,
            CrmInboundActivity(
                enquiry_id=enquiry.id or 0,
                organization_id=organization_id,
                user_id=user_id,
                activity_type="issued",
                body=f"Issued from owner sheet {contact_list.name} for outbound contact",
                metadata_json={"list_id": list_id, "claim_id": row.id, "mode": policy.mode},
                created_at=now,
            ),
        )

    outcome = InboundImportAssignmentSummary(
        mode=policy.mode, assignee_user_id=policy.assignee_user_id, team_id=pool_team
    )
    await inbound_imports._assign_imported(
        db, routed, outcome, organization_id, user_id, None, pool_team
    )
    await db.commit()
    return OwnerIssueResponse(
        requested=len(rows),
        issued=len(routed),
        already_assigned=already_assigned,
        skipped=skipped,
        remaining=remaining,
        next_offset=request.offset + len(rows) if remaining else None,
        enquiry_ids=[enquiry.id or 0 for enquiry, *_ in routed],
        assignment=outcome,
    )
