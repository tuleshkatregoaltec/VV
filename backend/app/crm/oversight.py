"""A manager's view of their teams: who holds how many leads, at which stage, and what is late.

Only recorded facts are shown (lead stages, first-response deadlines, logged activity).
Average first-response and pool claim times per person were agreed on 17 Nov 2026 and live in
`agent_analytics`; still no ratings or rankings.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone

from sqlalchemy import func
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.crm import assignment
from app.crm.inbound_models import CrmInboundActivity, CrmInboundEnquiry
from app.crm.routing_models import MemberWorkload, TeamWorkload, WorkloadResponse
from app.organization import teams as org_teams

CLOSED = ("won", "closed_lost", "disqualified")


async def team_workload(db: AsyncSession, organization_id: str, user_id: str) -> WorkloadResponse:
    """Every team this user manages (all teams for an administrator), current members only."""
    scope = await assignment.load_scope(db, organization_id, user_id)
    assignment.require_assigner(scope)
    team_ids = sorted(scope.team_members)
    if not team_ids:
        return WorkloadResponse(teams=[])
    lead = CrmInboundEnquiry
    now = datetime.now(timezone.utc)
    rows = (
        await db.exec(
            select(
                lead.team_id,
                lead.assigned_user_id,
                lead.status,
                lead.pool_released_at.is_not(None),  # type: ignore[union-attr]
                func.count(),
                func.count().filter(col(lead.first_contact_at).is_(None)),
                func.count().filter(
                    col(lead.first_contact_at).is_(None),
                    col(lead.first_response_due_at) < now,
                ),
            )
            .where(
                col(lead.organization_id) == organization_id,
                col(lead.team_id).in_(team_ids),
                col(lead.status).notin_(CLOSED),
            )
            .group_by(
                lead.team_id,
                lead.assigned_user_id,
                lead.status,
                lead.pool_released_at.is_not(None),  # type: ignore[union-attr]
            )
        )
    ).all()
    last_activity = dict(
        (
            await db.exec(
                select(CrmInboundActivity.user_id, func.max(CrmInboundActivity.created_at))
                .join(lead, col(lead.id) == CrmInboundActivity.enquiry_id)
                .where(
                    col(lead.organization_id) == organization_id,
                    col(lead.team_id).in_(team_ids),
                )
                .group_by(CrmInboundActivity.user_id)
            )
        ).all()
    )
    people = await org_teams.organization_people(db, organization_id)
    names = {team.id: team.name for team in await org_teams.list_org_teams(db, organization_id)}
    members: dict[tuple[str, str], MemberWorkload] = {}
    waiting: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for team_id, holder, status, shared, count, awaiting, overdue in rows:
        if holder is None:
            waiting[team_id][1 if shared else 0] += count
            continue
        member = members.setdefault(
            (team_id, holder),
            MemberWorkload(user_id=holder, name=people[holder].name if holder in people else ""),
        )
        member.open_leads += count
        member.by_status[status] = member.by_status.get(status, 0) + count
        member.awaiting_first_contact += awaiting
        member.overdue_first_contact += overdue
    teams = []
    for team_id in team_ids:
        roster = []
        # Current members, plus anyone who left the team but still holds its leads.
        holders = {user for team, user in members if team == team_id}
        for user_id in scope.team_members[team_id] | holders:
            member = members.get((team_id, user_id)) or MemberWorkload(
                user_id=user_id, name=people[user_id].name if user_id in people else ""
            )
            member.last_activity_at = last_activity.get(user_id)
            roster.append(member)
        teams.append(
            TeamWorkload(
                team_id=team_id,
                name=names.get(team_id, ""),
                unassigned=waiting[team_id][0] + waiting[team_id][1],
                shared=waiting[team_id][1],
                members=sorted(roster, key=lambda m: m.name.casefold()),
            )
        )
    return WorkloadResponse(teams=sorted(teams, key=lambda t: t.name.casefold()))
