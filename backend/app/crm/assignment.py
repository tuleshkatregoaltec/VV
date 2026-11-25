"""Who may see a lead, and the one place a lead's assignee or owning team changes.

Imports, manual creation, lead edits, the Assistant, Inbox approval, bulk reassignment, the shared
team pool and timed rotation all come through here, so visibility, eligibility, concurrency and
history cannot drift apart between them. Nothing here commits, except the request entry points
(`assign_leads`, `release_to_pool`, `claim`): the caller commits the change with the write it
belongs to.

Every lead belongs to one organization and, usually, one team (`team_id`). Who sees it (derived
from the database on every call, never from the client):
- an organization administrator (owner, or a member an owner made one): every lead of the
  organization;
- a manager (supervisor of a team): the leads their teams own, assigned or not;
- anyone: the leads assigned to them, and while unassigned, leads waiting in the shared pool of a
  team they belong to, plus the agency-wide signals that are shared by design (recently sold
  owners and Vitevue lease leads, whose data every member already sees in the owner registry).
A lead with no team (legacy, or created by someone in several teams) is seen only by
administrators and its assignee. A lead someone cannot see answers 404, like a missing one.

Who may assign:
- an organization administrator: any lead of the organization, to anyone in any of its teams;
- a manager: leads their teams own (and unowned shared signals), to people in those teams;
- an agent: no one else. Leads an agent creates, imports or approves from the Inbox are assigned
  to that agent, whether or not they are in a team, and an agent may claim a lead from the pool of
  a team they belong to.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import and_, or_
from sqlmodel import col
from sqlmodel.ext.asyncio.session import AsyncSession

from app.crm import inbound_repository, routing_repository
from app.crm.inbound_models import (
    SOLD_OWNER_SOURCE,
    VITEVUE_LEASE_SOURCE,
    CrmInboundAssignmentEvent,
    CrmInboundEnquiry,
)
from app.crm.inbound_policy import _utcnow
from app.crm.routing_models import (
    AssignmentCapabilities,
    AssignmentEventResponse,
    AssignmentPerson,
    AssignmentScopeResponse,
    AssignmentTeam,
    LeadAssignmentRequest,
    LeadAssignmentResponse,
    LeadAssignmentResult,
    MyTeam,
    PoolReleaseRequest,
)
from app.organization import teams as org_teams

# Agency-wide signals: created unassigned by a sync or on first open, shared by design.
SHARED_SOURCES = (SOLD_OWNER_SOURCE, VITEVUE_LEASE_SOURCE)
# Actor recorded for changes no person made (timed rotation).
SYSTEM_ACTOR = "system"


@dataclass(frozen=True)
class AssignmentScope:
    organization_id: str
    user_id: str
    organization_admin: bool
    supervised_team_ids: frozenset[str]
    # Teams this user may assign into (every team for an administrator) and their people.
    team_members: dict[str, frozenset[str]]
    # Teams this user belongs to in any role: their shared pools are theirs to claim from.
    member_team_ids: frozenset[str] = frozenset()

    @property
    def can_assign(self) -> bool:
        return self.organization_admin or bool(self.supervised_team_ids)

    @property
    def eligible_user_ids(self) -> frozenset[str]:
        return frozenset().union(*self.team_members.values())

    def teams_with(self, user_id: str) -> frozenset[str]:
        return frozenset(team for team, users in self.team_members.items() if user_id in users)

    def can_view(self, enquiry: CrmInboundEnquiry) -> bool:
        """The Python twin of `visible_clause`; keep the two identical."""
        if enquiry.organization_id != self.organization_id:
            return False
        if self.organization_admin or enquiry.assigned_user_id == self.user_id:
            return True
        if enquiry.team_id is not None and enquiry.team_id in self.supervised_team_ids:
            return True
        if enquiry.assigned_user_id is not None:
            return False
        return enquiry.source in SHARED_SOURCES or (
            enquiry.pool_released_at is not None and enquiry.team_id in self.member_team_ids
        )

    def can_edit(self, enquiry: CrmInboundEnquiry) -> bool:
        """Change details, notes or stage. A lead waiting in a team pool is read-only to the
        team's agents until one claims it (by logging contact); its managers may still edit."""
        if not self.can_view(enquiry):
            return False
        pooled = enquiry.assigned_user_id is None and enquiry.pool_released_at is not None
        return not pooled or self.may_reassign(enquiry)

    def may_reassign(self, enquiry: CrmInboundEnquiry) -> bool:
        if self.organization_admin:
            return True
        if not self.can_assign:
            return False
        if enquiry.team_id is not None:
            return enquiry.team_id in self.supervised_team_ids
        # An unowned agency-wide signal any manager may hand out; other unowned leads are the
        # administrators' to place.
        return enquiry.assigned_user_id is None and enquiry.source in SHARED_SOURCES


def visible_clause(scope: AssignmentScope):
    """SQL condition for the leads this user may see (see the module docstring)."""
    lead = CrmInboundEnquiry
    in_org = col(lead.organization_id) == scope.organization_id
    if scope.organization_admin:
        return in_org
    unassigned = col(lead.assigned_user_id).is_(None)
    options = [
        col(lead.assigned_user_id) == scope.user_id,
        and_(unassigned, col(lead.source).in_(SHARED_SOURCES)),
    ]
    if scope.supervised_team_ids:
        options.append(col(lead.team_id).in_(sorted(scope.supervised_team_ids)))
    if scope.member_team_ids:
        options.append(
            and_(
                unassigned,
                col(lead.pool_released_at).is_not(None),
                col(lead.team_id).in_(sorted(scope.member_team_ids)),
            )
        )
    return and_(in_org, or_(*options))


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="Inbound enquiry not found")


async def load_scope(db: AsyncSession, organization_id: str, user_id: str) -> AssignmentScope:
    membership = await org_teams.get_membership(db, organization_id, user_id)
    admin = org_teams.is_organization_admin(membership)
    rows = await org_teams.list_team_memberships(db, organization_id) if membership else []
    supervised = frozenset(
        row.team_id for row in rows if row.user_id == user_id and row.role == "supervisor"
    )
    members: dict[str, set[str]] = {}
    for row in rows:
        if admin or row.team_id in supervised:
            members.setdefault(row.team_id, set()).add(row.user_id)
    return AssignmentScope(
        organization_id=organization_id,
        user_id=user_id,
        organization_admin=admin,
        supervised_team_ids=supervised,
        team_members={team: frozenset(users) for team, users in members.items()},
        member_team_ids=frozenset(row.team_id for row in rows if row.user_id == user_id),
    )


async def load_visible(
    db: AsyncSession, scope: AssignmentScope, enquiry_id: int, *, lock: bool = False
) -> CrmInboundEnquiry:
    """The lead when this user may see it; otherwise the same 404 a missing id gets.

    `lock` holds the row until commit (taken before any rotation row, like the rotation worker),
    so a write that depends on who holds the lead cannot race a reassignment.
    """
    if lock:
        rows = await inbound_repository.lock_enquiries(db, scope.organization_id, [enquiry_id])
        enquiry = rows[0] if rows else None
    else:
        enquiry = await inbound_repository.get_crm_inbound_enquiry(db, enquiry_id)
    if not enquiry or not scope.can_view(enquiry):
        raise _not_found()
    return enquiry


def require_edit(scope: AssignmentScope, enquiry: CrmInboundEnquiry) -> None:
    if not scope.can_edit(enquiry):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "LEAD_IN_POOL",
                "message": "This lead is waiting in your team's pool. Log contact to take it.",
            },
        )


async def visible_ids(db: AsyncSession, scope: AssignmentScope, enquiry_ids) -> set[int]:
    """Which of these leads this user may see."""
    if not enquiry_ids:
        return set()
    return set(
        await inbound_repository.list_visible_ids(db, visible_clause(scope), list(enquiry_ids))
    )


def require_assigner(scope: AssignmentScope) -> None:
    if not scope.can_assign:
        raise HTTPException(
            status_code=403, detail="Only managers and organization administrators can do this"
        )


async def importer_still_member(db: AsyncSession, scope: AssignmentScope) -> bool:
    """True when the importer still belongs to the organization; the membership row stays
    share-locked until commit, so removing them waits for their own import."""
    return await org_teams.lock_membership(db, scope.organization_id, scope.user_id)


async def destination_available(
    db: AsyncSession, scope: AssignmentScope, user_id: str, team_ids: frozenset[str]
) -> bool:
    """True when the person is, right now, in one of these teams of the scope.

    The membership row stays share-locked until commit, so removing them from the team waits
    for this assignment instead of racing it.
    """
    teams = team_ids & scope.teams_with(user_id)
    return bool(teams) and await org_teams.lock_destination(
        db, scope.organization_id, user_id, teams
    )


def own_team(scope: AssignmentScope, preferred: str | None = None) -> str | None:
    """The team a self-assigned lead belongs to: `preferred` when the user is in it, else the
    user's only team. None when they are in no team or several (nothing is guessed)."""
    if preferred is not None and preferred in scope.member_team_ids:
        return preferred
    return next(iter(scope.member_team_ids)) if len(scope.member_team_ids) == 1 else None


def assignable_team(
    scope: AssignmentScope, assignee: str, requested: str | None, current: str | None = None
) -> str:
    """Which of the user's teams owns a lead given to `assignee`.

    The requested team when the assignee is in it; else the lead's current team when the
    assignee is in that; else the only team of the user's that holds the assignee. Someone in
    several of them needs `requested`.
    """
    candidates = scope.teams_with(assignee)
    if not candidates:
        raise HTTPException(
            status_code=403, detail="That person is not in a team you can assign leads to"
        )
    if requested is not None:
        if requested not in candidates:
            raise HTTPException(status_code=403, detail="That person is not in the team you chose")
        return requested
    if current in candidates:
        return current  # type: ignore[return-value]
    if len(candidates) == 1:
        return next(iter(candidates))
    raise HTTPException(
        status_code=422,
        detail={
            "code": "TEAM_REQUIRED",
            "message": "This person is in several of your teams. Choose the team.",
        },
    )


async def check_new_assignee(
    db: AsyncSession,
    scope: AssignmentScope,
    assignee: str,
    *,
    requested_team: str | None = None,
) -> str | None:
    """Refuse an assignee for a lead being created before anything is written; returns the
    team that will own it. The creator may always take their own lead."""
    if assignee == scope.user_id:
        return own_team(scope, requested_team)
    team = assignable_team(scope, assignee, requested_team)
    if not await destination_available(db, scope, assignee, frozenset({team})):
        raise HTTPException(
            status_code=403, detail="That person is not in a team you can assign leads to"
        )
    return team


def record_assignment(
    db: AsyncSession,
    enquiry: CrmInboundEnquiry,
    assignee: str | None,
    *,
    actor_user_id: str,
    reason: str,
    now: datetime,
    team_id: str | None,
    shared: bool = False,
    rule_id: int | None = None,
    rule_revision: int | None = None,
    import_id: int | None = None,
) -> None:
    """Change the assignee, owning team and pool state, and write the history entry.

    Callers have checked eligibility. `shared` puts an unassigned lead in its team's pool.
    """
    previous = enquiry.assigned_user_id
    enquiry.assigned_user_id = assignee
    enquiry.team_id = team_id
    enquiry.pool_released_at = now if shared and assignee is None and team_id else None
    enquiry.assignment_revision = (enquiry.assignment_revision or 0) + 1
    enquiry.assigned_at = now if assignee else None
    enquiry.updated_at = now
    inbound_repository.save(db, enquiry)
    inbound_repository.save(
        db,
        CrmInboundAssignmentEvent(
            organization_id=enquiry.organization_id,
            enquiry_id=enquiry.id or 0,
            previous_user_id=previous,
            assigned_user_id=assignee,
            actor_user_id=actor_user_id,
            reason=reason,
            rule_id=rule_id,
            rule_revision=rule_revision,
            import_id=import_id,
            team_id=team_id,
            revision=enquiry.assignment_revision,
            created_at=now,
        ),
    )


async def sync_rotation(db: AsyncSession, enquiry: CrmInboundEnquiry, *, now: datetime) -> None:
    """After a change of hands made by a person (not by the rotation itself), bring the lead's
    running rotation up to date, in the same transaction and under the lead's row lock.

    Reassigned to another person in the rule's team: the rule's timeout restarts for them and the
    rotation records them as having held the lead; the previous timer is void because the
    rotation now carries the new revision (a worker that read the old one stops, see
    `rotation._advance_one`). Reassignment is not contact: the lead still rotates on if the new
    holder does not act. Unassigned, put in a pool or moved to another team: the rotation ends;
    continuing an old team's order across that boundary would need a new routing decision.
    """
    rotation = await routing_repository.lock_rotation(db, enquiry.id or 0)
    if rotation is None or rotation.status != "active":
        return
    rotation.updated_at = now
    if enquiry.assigned_user_id is None:
        rotation.status, rotation.stop_reason = "stopped", "unassigned"
    elif enquiry.team_id != rotation.team_id:
        rotation.status, rotation.stop_reason = "stopped", "team_changed"
    else:
        rotation.assignment_revision = enquiry.assignment_revision
        rotation.due_at = now + timedelta(minutes=rotation.timeout_minutes)
        if enquiry.assigned_user_id not in (rotation.tried_user_ids or []):
            rotation.tried_user_ids = [*(rotation.tried_user_ids or []), enquiry.assigned_user_id]
    routing_repository.save(db, rotation)


def _changed_meanwhile(stale: list[int | None]) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={
            "code": "ASSIGNMENT_CHANGED",
            "message": "Someone else changed who handles these leads. Reload and try again.",
            "enquiry_ids": stale,
        },
    )


async def _lock_visible(
    db: AsyncSession,
    scope: AssignmentScope,
    enquiry_ids: list[int],
    expected_revisions: dict[int, int] | None,
) -> list[CrmInboundEnquiry]:
    rows = list(await inbound_repository.lock_enquiries(db, scope.organization_id, enquiry_ids))
    if len(rows) != len(set(enquiry_ids)) or not all(scope.can_view(row) for row in rows):
        raise _not_found()
    if expected_revisions is not None:
        stale = [
            row.id for row in rows if expected_revisions.get(row.id or 0) != row.assignment_revision
        ]
        if stale:
            raise _changed_meanwhile(stale)
    return rows


async def reassign(
    db: AsyncSession,
    scope: AssignmentScope,
    enquiry_ids: list[int],
    assignee: str | None,
    *,
    reason: str = "manual",
    expected_revisions: dict[int, int] | None = None,
    allow_self: bool = False,
    team_id: str | None = None,
) -> list[tuple[CrmInboundEnquiry, bool]]:
    """Assign existing leads, all or none. Each lead is locked, authorized and revision-checked
    before any changes; a lead already with this assignee is left as it is (no history).

    Unassigning keeps the lead with its team (out of the shared pool): the team's managers still
    see it. `allow_self` lets the user take an unassigned lead they can see for themselves.
    """
    rows = await _lock_visible(db, scope, enquiry_ids, expected_revisions)
    for row in rows:
        self_service = (
            allow_self and assignee == scope.user_id and row.assigned_user_id in (None, assignee)
        )
        if not (self_service or scope.may_reassign(row)):
            raise HTTPException(status_code=403, detail="You cannot reassign this lead")
    changing = [
        row
        for row in rows
        if row.assigned_user_id != assignee
        or (assignee is not None and team_id is not None and row.team_id != team_id)
    ]
    now = _utcnow()
    checked: set[str] = set()
    for row in changing:
        if assignee is None:
            team = row.team_id
        elif allow_self and assignee == scope.user_id:
            team = own_team(scope, team_id or row.team_id)
        else:
            team = assignable_team(scope, assignee, team_id, row.team_id)
            if team not in checked:
                if not await destination_available(db, scope, assignee, frozenset({team})):
                    raise HTTPException(
                        status_code=403,
                        detail="That person is not in a team you can assign leads to",
                    )
                checked.add(team)
        record_assignment(
            db, row, assignee, actor_user_id=scope.user_id, reason=reason, now=now, team_id=team
        )
        await sync_rotation(db, row, now=now)
    changed = {row.id for row in changing}
    return [(row, row.id in changed) for row in rows]


def _result(row: CrmInboundEnquiry, changed: bool) -> LeadAssignmentResult:
    return LeadAssignmentResult(
        enquiry_id=row.id or 0,
        assigned_user_id=row.assigned_user_id,
        assignment_revision=row.assignment_revision,
        changed=changed,
        team_id=row.team_id,
        shared=row.pool_released_at is not None,
    )


async def assign_leads(
    db: AsyncSession, organization_id: str, user_id: str, request: LeadAssignmentRequest
) -> LeadAssignmentResponse:
    """Manual assign/reassign/unassign of a bounded batch by a manager or administrator."""
    scope = await load_scope(db, organization_id, user_id)
    require_assigner(scope)
    results = await reassign(
        db,
        scope,
        request.enquiry_ids,
        request.assignee_user_id,
        reason="manual",
        expected_revisions=request.expected_revisions,
        team_id=request.team_id,
    )
    await db.commit()
    return LeadAssignmentResponse(results=[_result(row, changed) for row, changed in results])


async def release_to_pool(
    db: AsyncSession, organization_id: str, user_id: str, request: PoolReleaseRequest
) -> LeadAssignmentResponse:
    """Put leads, unassigned, in a team's shared pool, all or none: the manager of that team (or
    an administrator) frees them for the team's agents to claim."""
    scope = await load_scope(db, organization_id, user_id)
    results = await release(
        db, scope, request.enquiry_ids, request.team_id, request.expected_revisions
    )
    await db.commit()
    return LeadAssignmentResponse(results=results)


async def release(
    db: AsyncSession,
    scope: AssignmentScope,
    enquiry_ids: list[int],
    team_id: str,
    expected_revisions: dict[int, int] | None = None,
) -> list[LeadAssignmentResult]:
    """`release_to_pool` without the commit: the Assistant confirms through this too."""
    require_assigner(scope)
    if team_id not in scope.team_members:
        raise HTTPException(status_code=403, detail="You do not manage that team")
    rows = await _lock_visible(db, scope, enquiry_ids, expected_revisions)
    if not all(scope.may_reassign(row) for row in rows):
        raise HTTPException(status_code=403, detail="You cannot reassign this lead")
    now = _utcnow()
    results = []
    for row in rows:
        already = (
            row.assigned_user_id is None
            and row.team_id == team_id
            and row.pool_released_at is not None
        )
        if not already:
            record_assignment(
                db,
                row,
                None,
                actor_user_id=scope.user_id,
                reason="released",
                now=now,
                team_id=team_id,
                shared=True,
            )
            await sync_rotation(db, row, now=now)
        results.append(_result(row, not already))
    return results


async def claim(
    db: AsyncSession, scope: AssignmentScope, enquiry: CrmInboundEnquiry, *, now: datetime
) -> bool:
    """Give a lead waiting in a team pool to this user, who belongs to that team.

    One conditional UPDATE decides it, so of two people claiming at once exactly one wins; the
    other gets False and the lead stays with the winner. Not committed here.
    """
    if (
        enquiry.assigned_user_id is not None
        or enquiry.pool_released_at is None
        or enquiry.team_id not in scope.member_team_ids
    ):
        return False
    # The membership row stays share-locked until commit: leaving the team waits for the claim.
    if not await org_teams.lock_destination(
        db, scope.organization_id, scope.user_id, frozenset({enquiry.team_id})
    ):
        return False
    won = await inbound_repository.claim_pooled(
        db,
        organization_id=scope.organization_id,
        enquiry_id=enquiry.id or 0,
        team_id=enquiry.team_id,
        user_id=scope.user_id,
        now=now,
    )
    if won is None:
        return False
    enquiry.assigned_user_id = scope.user_id
    enquiry.assignment_revision = won
    enquiry.assigned_at = now
    enquiry.pool_released_at = None
    inbound_repository.save(
        db,
        CrmInboundAssignmentEvent(
            organization_id=scope.organization_id,
            enquiry_id=enquiry.id or 0,
            previous_user_id=None,
            assigned_user_id=scope.user_id,
            actor_user_id=scope.user_id,
            reason="claimed",
            team_id=enquiry.team_id,
            revision=won,
            created_at=now,
        ),
    )
    return True


async def assignment_history(
    db: AsyncSession, organization_id: str, user_id: str, enquiry_id: int
) -> list[AssignmentEventResponse]:
    scope = await load_scope(db, organization_id, user_id)
    await load_visible(db, scope, enquiry_id)
    events = await inbound_repository.list_assignment_events(db, organization_id, enquiry_id)
    return [AssignmentEventResponse.model_validate(event, from_attributes=True) for event in events]


async def scope_response(db: AsyncSession, scope: AssignmentScope) -> AssignmentScopeResponse:
    people = await org_teams.organization_people(db, scope.organization_id)
    spoken = await routing_repository.languages_by_user(
        db, scope.organization_id, scope.eligible_user_ids
    )
    names = {
        team.id: team.name for team in await org_teams.list_org_teams(db, scope.organization_id)
    }
    teams = [
        AssignmentTeam(
            id=team_id,
            name=names.get(team_id, ""),
            supervised=team_id in scope.supervised_team_ids,
            members=sorted(
                (
                    AssignmentPerson(
                        user_id=user_id,
                        name=people[user_id].name,
                        languages=spoken.get(user_id, []),
                    )
                    for user_id in users
                    if user_id in people
                ),
                key=lambda person: person.name.casefold(),
            ),
        )
        for team_id, users in scope.team_members.items()
    ]
    return AssignmentScopeResponse(
        capabilities=AssignmentCapabilities(
            organization_admin=scope.organization_admin,
            # Every member imports; only assigners choose who gets the leads (can_assign).
            can_import=True,
            can_assign=scope.can_assign,
            # Managers edit the rules of the teams they supervise; administrators edit all.
            can_manage_rules=scope.can_assign,
            can_manage_teams=scope.organization_admin,
        ),
        teams=sorted(teams, key=lambda team: team.name.casefold()),
        my_teams=sorted(
            (MyTeam(id=team_id, name=names.get(team_id, "")) for team_id in scope.member_team_ids),
            key=lambda team: team.name.casefold(),
        ),
        people=sorted(
            (AssignmentPerson(user_id=p.user_id, name=p.name) for p in people.values()),
            key=lambda person: person.name.casefold(),
        ),
    )
