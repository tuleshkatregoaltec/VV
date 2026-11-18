"""CRM deals: create from a lead, move through the conveyancing steps, close, and oversee.

Visibility follows lead assignment: an agent sees the deals they hold, a manager the deals of
their supervised teams, an administrator the organization's. A deal outside the scope gets the
same 404 a missing id gets.
"""

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import and_, or_
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.crm import assignment
from app.crm.assignment import AssignmentScope
from app.crm.deal_models import (
    DEAL_STAGES,
    ORIGIN_LABELS,
    AgentDealSummary,
    CrmDeal,
    CrmDealEvent,
    DealCloseRequest,
    DealCreateRequest,
    DealEventResponse,
    DealListResponse,
    DealMoveRequest,
    DealOversightResponse,
    DealResponse,
    DealUpdateRequest,
)
from app.crm.inbound_models import (
    OWNER_OUTBOUND_SOURCE,
    SOLD_OWNER_SOURCE,
    VITEVUE_LEASE_SOURCE,
    CrmInboundContact,
)

PORTALS = ("property finder", "bayut", "dubizzle")
ADS = ("meta", "facebook", "instagram", "google", "tiktok", "snapchat")
OWN_CONTACT = ("own contact", "referral")
AGENT_TO_AGENT = ("agent for a client", "agent to agent", "agent-to-agent")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def reference(deal_id: int) -> str:
    return f"D-{deal_id}"


def origin_of(source: str | None, listing_id: str | None) -> str:
    """Where a deal came from, in the buckets the manager view breaks deals down by."""
    if listing_id:
        return "listing"
    label = (source or "").strip()
    if label in (SOLD_OWNER_SOURCE, OWNER_OUTBOUND_SOURCE) or label.lower().startswith(
        "owner file"
    ):
        return "owner_outreach"
    if label == VITEVUE_LEASE_SOURCE:
        return "renewal"
    low = label.lower()
    if any(p in low for p in PORTALS):
        return "portal"
    if any(a == low or low.startswith(f"{a} ") or low.endswith(f" {a}") for a in ADS):
        return "ads"
    if low in OWN_CONTACT:
        return "own_contact"
    if low in AGENT_TO_AGENT:
        return "agent_to_agent"
    return "inbound"


def _deal_type(intent: str) -> str:
    if intent in ("buy", "sell"):
        return "sale"
    if intent in ("rent", "let"):
        return "rent"
    raise HTTPException(
        status_code=422, detail="Set the lead's type (buy, sell, rent or let) before a deal"
    )


def visible_clause(scope: AssignmentScope):
    deal = CrmDeal
    in_org = col(deal.organization_id) == scope.organization_id
    if scope.organization_admin:
        return in_org
    options = [col(deal.assigned_user_id) == scope.user_id]
    if scope.supervised_team_ids:
        options.append(col(deal.team_id).in_(sorted(scope.supervised_team_ids)))
    return and_(in_org, or_(*options))


def serialize(deal: CrmDeal) -> DealResponse:
    stages = DEAL_STAGES[deal.deal_type]
    index = min(deal.stage_index, len(stages) - 1)
    return DealResponse(
        id=deal.id,
        reference=reference(deal.id),
        deal_type=deal.deal_type,
        unit=deal.unit,
        client=deal.client,
        counterparty=deal.counterparty,
        value_aed=deal.value_aed,
        due_date=deal.due_date,
        listing_id=deal.listing_id,
        lead_id=deal.lead_id,
        agent_user_id=deal.assigned_user_id,
        team_id=deal.team_id,
        origin=deal.origin,
        origin_label=ORIGIN_LABELS.get(deal.origin, "Other inbound"),
        origin_source=deal.origin_source,
        stages=stages,
        stage_index=index,
        stage=stages[index],
        next_stage=stages[index + 1] if deal.status == "open" and index + 1 < len(stages) else None,
        status=deal.status,
        dld_transaction_id=deal.dld_transaction_id,
        created_at=deal.created_at,
        updated_at=deal.updated_at,
        closed_at=deal.closed_at,
    )


def _event(deal: CrmDeal, actor: str, kind: str, **fields) -> CrmDealEvent:
    return CrmDealEvent(
        organization_id=deal.organization_id,
        deal_id=deal.id,
        actor_user_id=actor,
        kind=kind,
        created_at=_now(),
        **fields,
    )


async def load_visible(db: AsyncSession, scope: AssignmentScope, deal_id: int) -> CrmDeal:
    deal = (
        await db.exec(select(CrmDeal).where(CrmDeal.id == deal_id, visible_clause(scope)))
    ).first()
    if deal is None:
        raise HTTPException(status_code=404, detail="Deal not found")
    return deal


def _unit_of(lead, payload: DealCreateRequest) -> str:
    if payload.unit and payload.unit.strip():
        return payload.unit.strip()
    for data in (lead.confirmed_data or {}, lead.observed_data or {}, lead.qualification or {}):
        value = data.get("unit") if isinstance(data, dict) else None
        if isinstance(value, str) and value.strip():
            return value.strip()[:200]
    places = (lead.criteria or {}).get("locations") or []
    kind = (lead.criteria or {}).get("property_type")
    described = " · ".join(str(x) for x in [kind, *places[:2]] if x)
    return described[:200] or "Unit not stated"


async def create_deal(
    db: AsyncSession, scope: AssignmentScope, payload: DealCreateRequest
) -> DealResponse:
    lead = await assignment.load_visible(db, scope, payload.lead_id)
    assignment.require_edit(scope, lead)
    contact = await db.get(CrmInboundContact, lead.contact_id)
    now = _now()
    deal = CrmDeal(
        organization_id=scope.organization_id,
        lead_id=lead.id,
        # A lead waiting in a pool is taken by whoever opens the deal.
        assigned_user_id=lead.assigned_user_id or scope.user_id,
        team_id=lead.team_id or assignment.own_team(scope),
        created_by_user_id=scope.user_id,
        deal_type=_deal_type(lead.intent),
        unit=_unit_of(lead, payload),
        client=(contact.full_name if contact else "") or "Client",
        counterparty=(payload.counterparty or "").strip(),
        value_aed=payload.value_aed,
        due_date=payload.due_date,
        listing_id=(payload.listing_id or "").strip() or None,
        origin=origin_of(lead.source, payload.listing_id),
        origin_source=lead.source or "",
        stage_index=0,
        status="open",
        created_at=now,
        updated_at=now,
    )
    db.add(deal)
    await db.flush()
    db.add(_event(deal, scope.user_id, "created", to_stage=0))
    await db.commit()
    await db.refresh(deal)
    return serialize(deal)


async def list_deals(
    db: AsyncSession, scope: AssignmentScope, *, tab: str, deal_type: str | None
) -> DealListResponse:
    rows = list(
        (
            await db.exec(
                select(CrmDeal)
                .where(visible_clause(scope))
                .order_by(col(CrmDeal.updated_at).desc())
                .limit(1000)
            )
        ).all()
    )
    open_rows = [d for d in rows if d.status == "open"]
    counts = {
        "open": len(open_rows),
        "closed": sum(d.status == "won" for d in rows),
        "lost": sum(d.status == "lost" for d in rows),
        "missing_documents": 0,  # documents are not tracked yet
        "sale": sum(d.deal_type == "sale" for d in open_rows),
        "rent": sum(d.deal_type == "rent" for d in open_rows),
    }
    if tab == "closed":
        shown = [d for d in rows if d.status == "won"]
    elif tab == "lost":
        shown = [d for d in rows if d.status == "lost"]
    elif tab == "missing_documents":
        shown = []
    elif tab == "commission":
        shown = [d for d in rows if d.status != "lost"]
    else:  # pipeline, conveyancing
        shown = open_rows
    if deal_type:
        shown = [d for d in shown if d.deal_type == deal_type]
    return DealListResponse(
        items=[serialize(d) for d in shown],
        counts=counts,
        open_value_aed=sum(d.value_aed or 0 for d in open_rows),
    )


async def get_deal(db: AsyncSession, scope: AssignmentScope, deal_id: int) -> DealResponse:
    return serialize(await load_visible(db, scope, deal_id))


async def move_deal(
    db: AsyncSession, scope: AssignmentScope, deal_id: int, payload: DealMoveRequest
) -> DealResponse:
    deal = await load_visible(db, scope, deal_id)
    if deal.status != "open":
        raise HTTPException(status_code=409, detail="This deal is closed; reopen it first")
    if deal.stage_index != payload.expected_stage_index:
        raise HTTPException(
            status_code=409, detail="This deal was moved meanwhile; review its current stage"
        )
    last = len(DEAL_STAGES[deal.deal_type]) - 1
    before = deal.stage_index
    now = _now()
    if payload.direction == "back":
        if before == 0:
            raise HTTPException(status_code=409, detail="The deal is at its first step")
        deal.stage_index = before - 1
        db.add(_event(deal, scope.user_id, "stage", from_stage=before, to_stage=deal.stage_index))
    elif before == last:
        # Completing the last step (transferred / keys handed over) closes the deal as won.
        deal.status = "won"
        deal.closed_at = now
        db.add(_event(deal, scope.user_id, "closed", from_stage=before, detail={"outcome": "won"}))
    else:
        deal.stage_index = before + 1
        db.add(_event(deal, scope.user_id, "stage", from_stage=before, to_stage=deal.stage_index))
    deal.updated_at = now
    await db.commit()
    await db.refresh(deal)
    return serialize(deal)


async def close_deal(
    db: AsyncSession, scope: AssignmentScope, deal_id: int, payload: DealCloseRequest
) -> DealResponse:
    deal = await load_visible(db, scope, deal_id)
    now = _now()
    if payload.outcome == "reopen":
        if deal.status == "open":
            raise HTTPException(status_code=409, detail="This deal is already open")
        deal.status, deal.closed_at = "open", None
        db.add(_event(deal, scope.user_id, "reopened"))
    else:
        if deal.status != "open":
            raise HTTPException(status_code=409, detail="This deal is already closed")
        deal.status, deal.closed_at = "lost", now
        db.add(
            _event(
                deal,
                scope.user_id,
                "closed",
                from_stage=deal.stage_index,
                detail={"outcome": "lost", "reason": (payload.reason or "").strip()},
            )
        )
    deal.updated_at = now
    await db.commit()
    await db.refresh(deal)
    return serialize(deal)


async def update_deal(
    db: AsyncSession, scope: AssignmentScope, deal_id: int, payload: DealUpdateRequest
) -> DealResponse:
    deal = await load_visible(db, scope, deal_id)
    changed = payload.model_dump(exclude_unset=True)
    if not changed:
        return serialize(deal)
    for field, value in changed.items():
        if isinstance(value, str):
            value = value.strip() or None if field == "dld_transaction_id" else value.strip()
        setattr(deal, field, value)
    deal.updated_at = _now()
    db.add(_event(deal, scope.user_id, "edited", detail={"fields": sorted(changed)}))
    await db.commit()
    await db.refresh(deal)
    return serialize(deal)


async def deal_history(
    db: AsyncSession, scope: AssignmentScope, deal_id: int
) -> list[DealEventResponse]:
    deal = await load_visible(db, scope, deal_id)
    stages = DEAL_STAGES[deal.deal_type]
    name = lambda i: stages[i] if i is not None and 0 <= i < len(stages) else None  # noqa: E731
    rows = (
        await db.exec(
            select(CrmDealEvent)
            .where(CrmDealEvent.deal_id == deal.id)
            .order_by(col(CrmDealEvent.created_at), col(CrmDealEvent.id))
        )
    ).all()
    return [
        DealEventResponse(
            kind=e.kind,
            actor_user_id=e.actor_user_id,
            from_stage=name(e.from_stage),
            to_stage=name(e.to_stage),
            detail=e.detail or {},
            created_at=e.created_at,
        )
        for e in rows
    ]


def _aware(at: datetime | None) -> datetime | None:
    """Stored times as UTC-aware (SQLite drops the zone that Postgres keeps)."""
    return at.replace(tzinfo=timezone.utc) if at is not None and at.tzinfo is None else at


def _closed_since(deal: CrmDeal, status: str, since: datetime) -> bool:
    closed = _aware(deal.closed_at)
    return deal.status == status and closed is not None and closed >= since


def _summary(user_id: str | None, deals: list[CrmDeal], activity, since) -> AgentDealSummary:
    open_rows = [d for d in deals if d.status == "open"]
    valued = [d.value_aed for d in open_rows if d.value_aed]
    return AgentDealSummary(
        user_id=user_id,
        open=len(open_rows),
        won_30d=sum(_closed_since(d, "won", since) for d in deals),
        lost_30d=sum(_closed_since(d, "lost", since) for d in deals),
        open_value_aed=sum(valued),
        average_value_aed=round(sum(valued) / len(valued)) if valued else 0,
        by_stage=dict(Counter(DEAL_STAGES[d.deal_type][d.stage_index] for d in open_rows)),
        by_origin=dict(Counter(d.origin for d in open_rows)),
        last_activity_at=activity,
    )


async def oversight(db: AsyncSession, scope: AssignmentScope) -> DealOversightResponse:
    """Per agent: open deals, value, stages, origins and recent outcomes, from stored deals."""
    deals = list((await db.exec(select(CrmDeal).where(visible_clause(scope)))).all())
    by_agent: dict[str | None, list[CrmDeal]] = defaultdict(list)
    for d in deals:
        by_agent[d.assigned_user_id].append(d)
    if scope.organization_admin:
        kind = "organization"
    elif scope.supervised_team_ids:
        kind = "teams"
    else:
        kind = "own"
    # Everyone overseen appears, with zeros when they have no deals yet.
    people: set[str] = {scope.user_id} if kind == "own" else set()
    for team, members in scope.team_members.items():
        if kind == "organization" or team in scope.supervised_team_ids:
            people |= set(members)
    for user in people:
        by_agent.setdefault(user, [])
    activity: dict[str, datetime] = {}
    if deals:
        events = (
            await db.exec(
                select(CrmDealEvent.actor_user_id, CrmDealEvent.created_at).where(
                    col(CrmDealEvent.deal_id).in_([d.id for d in deals])
                )
            )
        ).all()
        for actor, at in events:
            at = _aware(at)
            if actor not in activity or at > activity[actor]:
                activity[actor] = at
    since = _now() - timedelta(days=30)
    agents = sorted(
        (_summary(u, rows, activity.get(u) if u else None, since) for u, rows in by_agent.items()),
        key=lambda s: (-s.open, -s.open_value_aed, s.user_id or ""),
    )
    return DealOversightResponse(
        scope=kind,
        agents=agents,
        totals=_summary(None, deals, max(activity.values(), default=None), since),
        origin_labels=ORIGIN_LABELS,
    )
