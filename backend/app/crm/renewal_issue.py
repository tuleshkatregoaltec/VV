"""Assets › Renewals: a manager issues selected units to agents as outbound leads.

Each unit becomes (or reuses) the agency's one shared lead for it, exactly as when an agent opens
it, and is then routed with the same choices and checks as a Leads import: one agent, routing
rules, the team's shared pool, or left unassigned. Leads someone already holds are left alone.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from fastapi import HTTPException
from pydantic import BaseModel, Field
from sqlmodel.ext.asyncio.session import AsyncSession

from app.crm import inbound_imports, inbound_repository, routing
from app.crm.inbound_models import (
    CrmInboundActivity,
    CrmInboundEnquiry,
    InboundImportAssignmentSummary,
)
from app.crm.models import CrmLeadDetailResponse
from app.crm.opportunities import get_lead_detail
from app.crm.renewal_leads import _owners_by_candidate, open_lead_from_detail
from app.crm.routing_models import ImportAssignmentPolicy

MAX_RENEWAL_ISSUE = 100
# Lease details come from the warehouse one unit at a time; a few at once keeps it quick.
_DETAIL_CONCURRENCY = 8


class RenewalIssueRequest(BaseModel):
    lease_ids: list[str] = Field(min_length=1, max_length=MAX_RENEWAL_ISSUE)
    assignment: ImportAssignmentPolicy


class RenewalIssueResponse(BaseModel):
    requested: int
    # Leads routed by this request (new, or existing ones nobody held).
    issued: int
    # Units whose lead an agent already holds or that sit in a team pool; left as they are.
    already_assigned: int
    # Units that could not become a lead (no unit number, or the lease is gone).
    skipped: int
    enquiry_ids: list[int]
    assignment: InboundImportAssignmentSummary


async def _details(lease_ids: list[str]) -> list[CrmLeadDetailResponse | None]:
    gate = asyncio.Semaphore(_DETAIL_CONCURRENCY)

    async def one(lease_id: str) -> CrmLeadDetailResponse | None:
        async with gate:
            try:
                return await get_lead_detail(lease_id)
            except HTTPException as error:
                if error.status_code == 404:
                    return None
                raise

    return list(await asyncio.gather(*(one(lease_id) for lease_id in lease_ids)))


def _held(enquiry: CrmInboundEnquiry) -> bool:
    return enquiry.assigned_user_id is not None or enquiry.pool_released_at is not None


async def issue_renewal_leads(
    db: AsyncSession,
    *,
    request: RenewalIssueRequest,
    user_id: str,
    organization_id: str,
) -> RenewalIssueResponse:
    policy = request.assignment
    # Permission, team and rules are checked before any lead is created.
    pool_team, rules = await inbound_imports._resolve_policy(db, organization_id, user_id, policy)
    lease_ids = list(dict.fromkeys(request.lease_ids))
    details = [d for d in await _details(lease_ids) if d is not None and d.lead.unit_number]
    skipped = len(lease_ids) - len(details)
    owners = await _owners_by_candidate(
        db,
        candidate_keys=list({d.lead.unit_candidate_key for d in details}),
        user_id=user_id,
        organization_id=organization_id,
    )

    enquiry_ids: list[int] = []
    for detail in details:
        # Commits the lead on its own, as opening a unit does; routing follows in one transaction.
        opened = await open_lead_from_detail(
            db,
            detail=detail,
            owner=owners.get(detail.lead.unit_candidate_key),
            user_id=user_id,
            organization_id=organization_id,
        )
        if opened.id not in enquiry_ids:
            enquiry_ids.append(opened.id)

    now = datetime.now(timezone.utc)
    routed: list[tuple[CrmInboundEnquiry, str | None, routing.RuleSnapshot | None, str | None]] = []
    already_assigned = 0
    for enquiry_id in enquiry_ids:
        enquiry = await inbound_repository.get_crm_inbound_enquiry(db, enquiry_id)
        if enquiry is None or enquiry.organization_id != organization_id:
            continue
        if _held(enquiry):
            already_assigned += 1
            continue
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
                body="Issued from Renewals for outbound contact",
                metadata_json={"mode": policy.mode},
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
    return RenewalIssueResponse(
        requested=len(lease_ids),
        issued=len(routed),
        already_assigned=already_assigned,
        skipped=skipped,
        enquiry_ids=[enquiry.id or 0 for enquiry, *_ in routed],
        assignment=outcome,
    )
