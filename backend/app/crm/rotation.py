"""Timed lead rotation: a routed lead moves through its rule's people until one acts in time.

Agreed behaviour (meeting of 13 Nov 2026, 32:17, and the product decisions that followed):
- order: the rule's destination first, then its `rotation_user_ids` in the order the manager set;
- timeout: the rule's `rotation_minutes`, the same for each person;
- the rotation stops when the person holding the lead logs contact or changes its stage;
- a manager's reassignment to another person in the same team is not contact and does not stop
  it: the timer restarts for the new holder (the old timer can no longer fire, see
  `assignment.sync_rotation`), and if they do not act either the lead goes to the next person in
  the rule's order who has not held it yet; moving the lead to another team, unassigning it or
  putting it in a pool ends the rotation (a new routing decision is needed);
- a person who has left the rule's team since is skipped, never assigned; under a "speakers
  only" rule, so is anyone not recorded as speaking the lead's language;
- when nobody untried is left, the lead goes, unassigned, to the rule team's shared pool.

State lives in `crm_lead_rotations`, never in a process, so a restart loses nothing. The work is
done by `advance_due`, which a scheduler runs every minute (`scripts/crm/advance_lead_rotations.py`).
Each lead is locked with SKIP LOCKED before its rotation row, the same order request handlers use,
so concurrent workers never move one lead twice and never deadlock with a person acting on it.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime, timedelta

from sqlmodel.ext.asyncio.session import AsyncSession

from app.crm import agent_languages, assignment, routing_repository
from app.crm.inbound_models import CrmInboundEnquiry
from app.crm.inbound_policy import _utcnow
from app.crm.routing import RuleSnapshot
from app.crm.routing_models import CrmLeadRotation
from app.organization import teams as org_teams

logger = logging.getLogger(__name__)

CLOSED_STATUSES = frozenset({"won", "closed_lost", "disqualified"})


def start(
    db: AsyncSession,
    enquiry: CrmInboundEnquiry,
    rule: RuleSnapshot,
    *,
    holder: str,
    now: datetime,
    required_language: str | None = None,
) -> None:
    """Begin a rotation for a lead just given to `holder`, one of `rule`'s people (not committed).

    `required_language` (a "speakers only" rule, lead language known) limits the next people to
    those recorded as speaking it.
    """
    if not rule.rotation_user_ids or not rule.rotation_minutes:
        return
    routing_repository.save(
        db,
        CrmLeadRotation(
            organization_id=enquiry.organization_id,
            enquiry_id=enquiry.id or 0,
            team_id=rule.team_id,
            rule_id=rule.id,
            rule_revision=rule.revision,
            user_ids=list(rule.order),
            tried_user_ids=[holder],
            required_language=required_language,
            position=rule.order.index(holder),
            timeout_minutes=rule.rotation_minutes,
            due_at=now + timedelta(minutes=rule.rotation_minutes),
            assignment_revision=enquiry.assignment_revision,
            status="active",
            created_at=now,
            updated_at=now,
        ),
    )


async def stop_if_holder(
    db: AsyncSession, enquiry: CrmInboundEnquiry, actor_user_id: str, reason: str
) -> None:
    """The holder acted on the lead (logged contact, changed its stage): stop rotating it.

    Callers hold the lead's row lock, taken before this touches the rotation row.
    """
    if enquiry.assigned_user_id == actor_user_id:
        await routing_repository.stop_rotation(db, enquiry.id or 0, reason=reason, now=_utcnow())


async def _next_person(
    db: AsyncSession, rotation: CrmLeadRotation, holder: str
) -> tuple[int, str] | None:
    """The first person in the rule's order who has not held the lead yet (nor holds it now), is
    still in the rule's team (row locked) and, when the rotation requires a language, is recorded
    as speaking it."""
    skip = set(rotation.tried_user_ids or ()) | {holder}
    for position, user_id in enumerate(rotation.user_ids):
        if user_id in skip:
            continue
        if rotation.required_language and not await agent_languages.speaks(
            db, rotation.organization_id, user_id, rotation.required_language
        ):
            continue
        if await org_teams.lock_destination(
            db, rotation.organization_id, user_id, frozenset({rotation.team_id})
        ):
            return position, user_id
    return None


async def _advance_one(db: AsyncSession, enquiry_id: int, now: datetime) -> str:
    enquiry = await routing_repository.lock_enquiry_skip_locked(db, enquiry_id)
    if enquiry is None:
        return "busy"  # another worker (or a person acting on it) holds the lead
    rotation = await routing_repository.lock_rotation(db, enquiry_id)
    if rotation is None or rotation.status != "active" or rotation.due_at > now:
        return "not_due"
    # The rotation knows the revision it last saw (its own move, or a manager's reassignment it
    # was told about). Any other change of hands means this timer is stale: it never overrides.
    if enquiry.assignment_revision != rotation.assignment_revision:
        _finish(db, rotation, "stopped", "reassigned", now)
        return "stopped"
    holder = enquiry.assigned_user_id
    if holder is None or enquiry.team_id != rotation.team_id:
        _finish(db, rotation, "stopped", "unassigned" if holder is None else "team_changed", now)
        return "stopped"
    if enquiry.status in CLOSED_STATUSES:
        _finish(db, rotation, "stopped", "closed", now)
        return "stopped"
    found = await _next_person(db, rotation, holder)
    if found is None:
        assignment.record_assignment(
            db,
            enquiry,
            None,
            actor_user_id=assignment.SYSTEM_ACTOR,
            reason="released",
            now=now,
            team_id=rotation.team_id,
            shared=True,
            rule_id=rotation.rule_id,
            rule_revision=rotation.rule_revision,
        )
        _finish(db, rotation, "finished", "released_to_pool", now)
        return "released"
    position, user_id = found
    assignment.record_assignment(
        db,
        enquiry,
        user_id,
        actor_user_id=assignment.SYSTEM_ACTOR,
        reason="rotation",
        now=now,
        team_id=rotation.team_id,
        rule_id=rotation.rule_id,
        rule_revision=rotation.rule_revision,
    )
    rotation.position = position
    rotation.tried_user_ids = [*(rotation.tried_user_ids or []), user_id]
    rotation.assignment_revision = enquiry.assignment_revision
    rotation.due_at = now + timedelta(minutes=rotation.timeout_minutes)
    rotation.updated_at = now
    routing_repository.save(db, rotation)
    return "rotated"


def _finish(
    db: AsyncSession, rotation: CrmLeadRotation, status: str, reason: str, now: datetime
) -> None:
    rotation.status = status
    rotation.stop_reason = reason
    rotation.updated_at = now
    routing_repository.save(db, rotation)


async def advance_due(
    db: AsyncSession,
    *,
    now: datetime | None = None,
    limit: int = 500,
    should_stop: Callable[[], bool] = lambda: False,
) -> dict[str, int]:
    """Move every overdue lead on to its next person (or the pool), one transaction per lead.

    Safe to run concurrently and to re-run after a crash: a lead already moved is no longer due,
    and one being handled elsewhere is skipped until the next run.
    """
    now = now or _utcnow()
    counts: dict[str, int] = {}
    for enquiry_id in await routing_repository.due_rotation_enquiry_ids(db, now, limit):
        if should_stop():
            break
        try:
            outcome = await _advance_one(db, enquiry_id, now)
            await db.commit()
        except Exception:
            await db.rollback()
            logger.exception("Lead rotation failed for enquiry %s", enquiry_id)
            outcome = "failed"
        counts[outcome] = counts.get(outcome, 0) + 1
    return counts
