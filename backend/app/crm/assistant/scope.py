"""The organisation checks shared by the assistant's tools and its confirm step."""

from datetime import date, datetime
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlmodel.ext.asyncio.session import AsyncSession

from app.crm import inbound_repository
from app.crm.assistant.deps import AssistantDeps
from app.crm.inbound import _is_lead
from app.crm.inbound_models import CrmInboundEnquiry
from app.organization import repository as organization_repository
from app.organization import service as organization_service


async def load_lead(db: AsyncSession, organization_id: str, lead_id: int) -> CrmInboundEnquiry:
    """The lead, only when it is this organisation's and on the Leads list. Anything else gets
    the same 404 a missing id gets, so another organisation's ids reveal nothing."""
    enquiry = await inbound_repository.get_crm_inbound_enquiry(db, lead_id)
    if not enquiry or enquiry.organization_id != organization_id or not _is_lead(enquiry):
        raise HTTPException(status_code=404, detail="Inbound enquiry not found")
    return enquiry


DUBAI = ZoneInfo("Asia/Dubai")


def today() -> date:
    """Today for the agents (Dubai), used for dates like "tomorrow" and "next Monday"."""
    return datetime.now(DUBAI).date()


def lead_link(lead_id: int) -> str:
    return f"/crm/leads?lead={lead_id}"


async def org_members(deps: AssistantDeps) -> list[dict[str, str]]:
    members = await organization_service.get_organization_members(
        context_organization=deps.organization, db=deps.db
    )
    return [
        {
            "user_id": str(member["id"]),
            "name": " ".join(
                part for part in (member.get("first_name"), member.get("last_name")) if part
            )
            or "Team member",
            "role": member["role"],
        }
        for member in members
    ]


async def org_member(deps: AssistantDeps, user_id: str) -> dict[str, str] | None:
    """A member of this organisation by user id, or None."""
    if not user_id or not await organization_repository.get_membership_in_org(
        deps.db, deps.organization_id, user_id
    ):
        return None
    for member in await org_members(deps):
        if member["user_id"] == user_id:
            return member
    return {"user_id": user_id, "name": "Team member", "role": "member"}
