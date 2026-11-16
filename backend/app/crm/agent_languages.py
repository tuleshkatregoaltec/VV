"""Languages each agent speaks, for routing rules set to "speakers only".

Agreed (meeting of 13 Nov 2026, 32:17-33:29): a Hindi-speaking client goes first to an agent who
speaks Hindi, then rotates to another who does; the manager sets this up. A person's languages are
recorded by an organization administrator, or by a manager for the members of the teams they
supervise. Nothing is inferred from names or nationality. A lead's language is separate: the
contact's preferred language from an imported Language column.
"""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.dialects.postgresql import insert
from sqlmodel.ext.asyncio.session import AsyncSession

from app.crm import routing_repository
from app.crm.assignment import AssignmentScope
from app.crm.inbound_policy import _utcnow
from app.crm.routing_models import (
    AgentLanguagesResponse,
    AgentLanguagesWrite,
    CrmAgentLanguages,
    language_key,
)
from app.organization import teams as org_teams

languages_by_user = routing_repository.languages_by_user


async def speaks(db: AsyncSession, organization_id: str, user_id: str, language: str) -> bool:
    """Whether the person is recorded as speaking `language` (already a `language_key`)."""
    spoken = (await languages_by_user(db, organization_id, [user_id])).get(user_id, [])
    return language in {language_key(item) for item in spoken}


async def set_languages(
    db: AsyncSession, scope: AssignmentScope, user_id: str, payload: AgentLanguagesWrite
) -> AgentLanguagesResponse:
    if not scope.can_assign:
        raise HTTPException(
            status_code=403, detail="Only managers and administrators record agents' languages"
        )
    # A manager records languages for the people in the teams they supervise; anyone else in the
    # organization answers like a stranger. An administrator may record any current member.
    allowed = (
        await org_teams.get_membership(db, scope.organization_id, user_id) is not None
        if scope.organization_admin
        else user_id in scope.eligible_user_ids
    )
    if not allowed:
        raise HTTPException(status_code=404, detail="Person not found")
    now = _utcnow()
    values = {
        "languages": payload.languages,
        "updated_by_user_id": scope.user_id,
        "updated_at": now,
    }
    # One statement: two managers saving at once leave the last write, never a duplicate row.
    await db.exec(
        insert(CrmAgentLanguages)
        .values(organization_id=scope.organization_id, user_id=user_id, **values)
        .on_conflict_do_update(constraint="uq_crm_agent_languages_member", set_=values)
    )
    await db.commit()
    return AgentLanguagesResponse(user_id=user_id, languages=payload.languages)
