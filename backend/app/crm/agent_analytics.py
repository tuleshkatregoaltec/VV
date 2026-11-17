"""Agent lead analytics for managers (agreed 17 Nov 2026): per-person response and claim times,
contacts in the last day, stages and sources, from facts the CRM already records.

Averages only; nothing is scored or ranked.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import func
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.crm import oversight
from app.crm.analytics_models import (
    AgentAnalyticsDetail,
    AgentLeadMetrics,
    AgentLeadRow,
    AnalyticsDays,
    DailyActivity,
    SourceCount,
    SourceKind,
    TeamAnalyticsResponse,
)
from app.crm.inbound_models import (
    SOLD_OWNER_SOURCE,
    CrmInboundActivity,
    CrmInboundAssignmentEvent,
    CrmInboundContact,
    CrmInboundEnquiry,
)

DUBAI = ZoneInfo("Asia/Dubai")
CALLS = ("call", "contact_attempt")
MESSAGES = ("whatsapp", "email")
MAX_LEAD_ROWS = 200

CONTACT_TYPES = ("contact_attempt", "call", "email", "whatsapp", "meeting")
QUALIFIED = ("qualified", "viewing", "valuation", "signed", "active", "won")
OWN_SOURCES = ("manual", "own contact", "referral")


def source_kind(source: str, observed_data: dict | None) -> SourceKind:
    if source == SOLD_OWNER_SOURCE:
        return "vitevue_sold"
    if observed_data and "vitevue_lease" in observed_data:
        return "vitevue_lease"
    if (source or "").strip().casefold() in OWN_SOURCES:
        return "own"
    return "marketing"


def average_minutes(durations: list[timedelta]) -> int | None:
    if not durations:
        return None
    seconds = sum(d.total_seconds() for d in durations) / len(durations)
    # Round half up (12.5 → 13), not Python's banker's rounding.
    return int(seconds / 60 + 0.5)


def claim_waits(
    events: list[tuple[int, str, datetime, str | None]],
) -> dict[str, list[timedelta]]:
    """Rows (enquiry_id, reason, created_at, actor) in time order → per claimer, the wait from the
    latest earlier release of the same lead. A claim with no earlier release is skipped."""
    released: dict[int, datetime] = {}
    waits: dict[str, list[timedelta]] = defaultdict(list)
    for enquiry_id, reason, created_at, actor in events:
        if reason == "released":
            released[enquiry_id] = created_at
        elif reason == "claimed" and actor and enquiry_id in released:
            waits[actor].append(created_at - released.pop(enquiry_id))
    return dict(waits)


def _team_leads(organization_id: str, team_ids: list[str]):
    lead = CrmInboundEnquiry
    return select(lead.id).where(
        col(lead.organization_id) == organization_id, col(lead.team_id).in_(team_ids)
    )


async def team_analytics(
    db: AsyncSession, organization_id: str, user_id: str, days: AnalyticsDays = 30
) -> TeamAnalyticsResponse:
    """Every person in the teams this user manages (all teams for an administrator), with their
    open work (Team workload rules) and their response, claim and contact figures."""
    now = datetime.now(timezone.utc)
    # Team workload checks the caller may assign (403 otherwise) and lists current members plus
    # anyone who still holds a managed team's lead.
    workload = await oversight.team_workload(db, organization_id, user_id)
    team_ids = [team.team_id for team in workload.teams]
    people: dict[str, AgentLeadMetrics] = {}
    for team in workload.teams:
        for member in team.members:
            person = people.setdefault(
                member.user_id, AgentLeadMetrics(user_id=member.user_id, name=member.name)
            )
            person.team_ids.append(team.team_id)
            person.open_leads += member.open_leads
            for status, count in member.by_status.items():
                person.by_status[status] = person.by_status.get(status, 0) + count
            person.awaiting_first_contact += member.awaiting_first_contact
            person.overdue_first_contact += member.overdue_first_contact
            person.last_activity_at = member.last_activity_at
    if not team_ids:
        return TeamAnalyticsResponse(days=days, generated_at=now, agents=[])
    start = now - timedelta(days=days)
    lead = CrmInboundEnquiry

    responses: dict[str, list[timedelta]] = defaultdict(list)
    for holder, assigned_at, first_contact_at, status in (
        await db.exec(
            select(
                lead.assigned_user_id, lead.assigned_at, lead.first_contact_at, lead.status
            ).where(
                col(lead.organization_id) == organization_id,
                col(lead.team_id).in_(team_ids),
                col(lead.assigned_user_id).is_not(None),
                col(lead.assigned_at) >= start,
            )
        )
    ).all():
        person = people.get(holder)
        if person is None:
            continue
        person.assigned_in_window += 1
        person.qualified_or_better += status in QUALIFIED
        # A lead contacted before this assignment (e.g. reassigned) says nothing about this
        # person's response time.
        if first_contact_at is not None and first_contact_at >= assigned_at:
            responses[holder].append(first_contact_at - assigned_at)

    event = CrmInboundAssignmentEvent
    rows = (
        await db.exec(
            select(event.enquiry_id, event.reason, event.created_at, event.actor_user_id)
            .where(
                col(event.organization_id) == organization_id,
                col(event.enquiry_id).in_(_team_leads(organization_id, team_ids)),
                col(event.reason).in_(("released", "claimed")),
            )
            .order_by(event.created_at, event.id)
        )
    ).all()
    claims = claim_waits(
        [row for row in rows if row[1] == "released" or row[2] >= start]  # claims in the window
    )

    activity = CrmInboundActivity
    contacted = dict(
        (
            await db.exec(
                select(activity.user_id, func.count(func.distinct(activity.enquiry_id)))
                .where(
                    col(activity.organization_id) == organization_id,
                    col(activity.enquiry_id).in_(_team_leads(organization_id, team_ids)),
                    col(activity.activity_type).in_(CONTACT_TYPES),
                    col(activity.created_at) >= now - timedelta(hours=24),
                )
                .group_by(activity.user_id)
            )
        ).all()
    )
    for person in people.values():
        person.avg_first_response_minutes = average_minutes(responses.get(person.user_id, []))
        person.avg_claim_minutes = average_minutes(claims.get(person.user_id, []))
        person.contacted_24h = contacted.get(person.user_id, 0)
    agents = sorted(people.values(), key=lambda p: p.name.casefold())
    return TeamAnalyticsResponse(days=days, generated_at=now, agents=agents)


async def agent_analytics(
    db: AsyncSession,
    organization_id: str,
    user_id: str,
    agent_user_id: str,
    days: AnalyticsDays = 30,
) -> AgentAnalyticsDetail:
    """One person's figures, sources, last 7 days of activity and their leads, for a manager of
    a team they belong to (or whose lead they hold). Anyone else answers 404."""
    team = await team_analytics(db, organization_id, user_id, days)
    metrics = next((a for a in team.agents if a.user_id == agent_user_id), None)
    if metrics is None:
        raise HTTPException(status_code=404, detail="This person is not in a team you manage")
    team_ids = metrics.team_ids
    now = team.generated_at
    lead = CrmInboundEnquiry

    held = (
        await db.exec(
            select(lead, CrmInboundContact.full_name)
            .join(CrmInboundContact, col(CrmInboundContact.id) == lead.contact_id)
            .where(
                col(lead.organization_id) == organization_id,
                col(lead.team_id).in_(team_ids),
                col(lead.assigned_user_id) == agent_user_id,
            )
        )
    ).all()
    sources = Counter((source_kind(e.source, e.observed_data), e.source) for e, _ in held)
    rows = [
        AgentLeadRow(
            id=e.id,
            name=name,
            status=e.status,
            source=e.source,
            source_kind=source_kind(e.source, e.observed_data),
            assigned_at=e.assigned_at,
            first_contact_at=e.first_contact_at,
            last_contact_at=e.last_contact_at,
            next_follow_up=e.next_follow_up,
            overdue=(
                e.first_contact_at is None
                and e.first_response_due_at is not None
                and e.first_response_due_at < now
                and e.status not in oversight.CLOSED
            ),
        )
        for e, name in held
    ]
    oldest = datetime.min.replace(tzinfo=timezone.utc)
    rows.sort(key=lambda r: (not r.overdue, -(r.assigned_at or oldest).timestamp()))

    today = now.astimezone(DUBAI).date()
    week = [today - timedelta(days=offset) for offset in range(6, -1, -1)]
    buckets: dict[date, DailyActivity] = {day: DailyActivity(date=day) for day in week}
    activity = CrmInboundActivity
    for kind, created_at in (
        await db.exec(
            select(activity.activity_type, activity.created_at).where(
                col(activity.organization_id) == organization_id,
                col(activity.user_id) == agent_user_id,
                col(activity.enquiry_id).in_(_team_leads(organization_id, team_ids)),
                col(activity.created_at) >= now - timedelta(days=8),
            )
        )
    ).all():
        bucket = buckets.get(created_at.astimezone(DUBAI).date())
        if bucket is None:
            continue
        if kind in CALLS:
            bucket.calls += 1
        elif kind in MESSAGES:
            bucket.messages += 1
        elif kind == "meeting":
            bucket.meetings += 1

    return AgentAnalyticsDetail(
        days=days,
        metrics=metrics,
        sources=[
            SourceCount(kind=kind, label=label, count=count)
            for (kind, label), count in sources.most_common()
        ],
        activity=[buckets[day] for day in week],
        leads=rows[:MAX_LEAD_ROWS],
    )
