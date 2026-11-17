"""Ordered lead routing rules: management and deterministic first-match evaluation.

Rules route newly imported leads only. Changing a rule never moves existing leads (nor a rotation
already running: it keeps the order it started with). Organization administrators manage every
rule; a manager manages the rules of the teams they supervise and reorders them among themselves.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException
from sqlmodel.ext.asyncio.session import AsyncSession

from app.crm import routing_repository
from app.crm.assignment import AssignmentScope
from app.crm.inbound_models import CrmInboundContact, CrmInboundEnquiry
from app.crm.inbound_policy import _utcnow
from app.crm.routing_models import (
    ROUTABLE_INTENTS,
    CrmRoutingRule,
    RoutingCondition,
    RoutingRuleOrder,
    RoutingRuleResponse,
    RoutingRuleUpdate,
    RoutingRuleWrite,
    language_key,
)


@dataclass(frozen=True)
class RuleSnapshot:
    """A rule as it stood when an import started; later edits do not change that import."""

    id: int
    revision: int
    team_id: str
    destination_user_id: str
    match_mode: str
    conditions: tuple[RoutingCondition, ...]
    rotation_user_ids: tuple[str, ...] = ()
    rotation_minutes: int | None = None
    speakers_only: bool = False

    @property
    def order(self) -> tuple[str, ...]:
        """Who may get the lead, in turn: the destination, then the rotation."""
        return (self.destination_user_id, *self.rotation_user_ids)


def lead_language(contact: CrmInboundContact | None) -> str | None:
    """The lead's own language (the imported Language column), normalized; None when unknown."""
    return language_key(contact.preferred_language if contact else None) or None


def _lead_values(
    field: str, enquiry: CrmInboundEnquiry, contact: CrmInboundContact | None = None
) -> set[str]:
    """The lead's values for a field, normalized; empty means the lead does not say."""
    if field == "language":
        language = lead_language(contact)
        return {language} if language else set()
    if field == "intent":
        return {enquiry.intent} if enquiry.intent in ROUTABLE_INTENTS else set()
    if field == "source":
        source = (enquiry.source or "").strip().casefold()
        return {source} if source else set()
    locations = (enquiry.criteria or {}).get("locations") or []
    if isinstance(locations, str):
        locations = [locations]
    return {str(item).strip().casefold() for item in locations if str(item).strip()}


def condition_matches(
    condition: RoutingCondition,
    enquiry: CrmInboundEnquiry,
    contact: CrmInboundContact | None = None,
) -> bool:
    normalize = language_key if condition.field == "language" else str.casefold
    wanted = {normalize(value) for value in condition.values}
    return bool(_lead_values(condition.field, enquiry, contact) & wanted)


def rule_matches(
    rule: RuleSnapshot, enquiry: CrmInboundEnquiry, contact: CrmInboundContact | None = None
) -> bool:
    results = (condition_matches(condition, enquiry, contact) for condition in rule.conditions)
    return all(results) if rule.match_mode == "all" else any(results)


def first_match(
    rules: list[RuleSnapshot],
    enquiry: CrmInboundEnquiry,
    contact: CrmInboundContact | None = None,
) -> RuleSnapshot | None:
    """The first rule in priority order that matches. Later rules are never tried after it,
    even when its destination turns out to be unavailable."""
    return next((rule for rule in rules if rule_matches(rule, enquiry, contact)), None)


def _snapshot(rule: CrmRoutingRule) -> RuleSnapshot:
    return RuleSnapshot(
        id=rule.id or 0,
        revision=rule.revision,
        team_id=rule.team_id,
        destination_user_id=rule.destination_user_id,
        match_mode=rule.match_mode,
        conditions=tuple(RoutingCondition.model_validate(item) for item in rule.conditions),
        rotation_user_ids=tuple(rule.rotation_user_ids or ()),
        rotation_minutes=rule.rotation_minutes,
        speakers_only=rule.speakers_only,
    )


def _in_scope(scope: AssignmentScope, rule: CrmRoutingRule) -> bool:
    # By role, not by current team members: a rule whose team emptied must still be evaluated
    # (and report its destination unavailable) rather than vanish and let a later rule match.
    return scope.organization_admin or rule.team_id in scope.supervised_team_ids


async def rule_snapshot(db: AsyncSession, scope: AssignmentScope) -> list[RuleSnapshot]:
    """Enabled rules for the teams this user may route into, first match first."""
    rules = await routing_repository.list_rules(db, scope.organization_id)
    return [_snapshot(rule) for rule in rules if rule.enabled and _in_scope(scope, rule)]


def _response(rule: CrmRoutingRule) -> RoutingRuleResponse:
    return RoutingRuleResponse(
        id=rule.id or 0,
        name=rule.name,
        team_id=rule.team_id,
        enabled=rule.enabled,
        priority=rule.priority,
        match_mode=rule.match_mode,  # type: ignore[arg-type]
        conditions=[RoutingCondition.model_validate(item) for item in rule.conditions],
        destination_user_id=rule.destination_user_id,
        rotation_user_ids=list(rule.rotation_user_ids or []),
        rotation_minutes=rule.rotation_minutes,
        speakers_only=rule.speakers_only,
        revision=rule.revision,
        updated_by_user_id=rule.updated_by_user_id,
        created_at=rule.created_at,
        updated_at=rule.updated_at,
    )


def _require_rule_manager(scope: AssignmentScope) -> None:
    if not scope.can_assign:
        raise HTTPException(
            status_code=403,
            detail="Only managers and organization administrators can change routing rules",
        )


def _require_rule_in_scope(scope: AssignmentScope, rule: CrmRoutingRule | None) -> CrmRoutingRule:
    # Another team's rule answers like a missing one: a manager does not learn it exists.
    if not rule or not _in_scope(scope, rule):
        raise HTTPException(status_code=404, detail="Routing rule not found")
    return rule


def _validate_destination(scope: AssignmentScope, payload: RoutingRuleWrite) -> None:
    # scope.team_members holds only the teams this user may route into (every team of the
    # organization for an administrator, the supervised ones for a manager), so this also proves
    # the team is theirs and this organization's.
    if payload.team_id not in scope.team_members:
        raise HTTPException(status_code=403, detail="You do not manage that team")
    members = scope.team_members[payload.team_id]
    if payload.destination_user_id not in members:
        raise HTTPException(
            status_code=422, detail="The destination must be a member of the rule's team"
        )
    if any(user_id not in members for user_id in payload.rotation_user_ids):
        raise HTTPException(
            status_code=422, detail="Everyone in the rotation must be a member of the rule's team"
        )


def _write(rule: CrmRoutingRule, payload: RoutingRuleWrite, user_id: str) -> None:
    rule.name = payload.name.strip()
    rule.team_id = payload.team_id
    rule.enabled = payload.enabled
    rule.match_mode = payload.match_mode
    rule.conditions = [condition.model_dump() for condition in payload.conditions]
    rule.destination_user_id = payload.destination_user_id
    rule.rotation_user_ids = list(payload.rotation_user_ids)
    rule.rotation_minutes = payload.rotation_minutes
    rule.speakers_only = payload.speakers_only
    rule.updated_by_user_id = user_id
    rule.updated_at = _utcnow()


def _conflict() -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={
            "code": "RULE_CHANGED",
            "message": "Someone else changed the routing rules. Reload and try again.",
        },
    )


async def list_rules(db: AsyncSession, scope: AssignmentScope) -> list[RoutingRuleResponse]:
    """Administrators see every rule; managers see the rules of the teams they supervise."""
    if not scope.can_assign:
        raise HTTPException(status_code=403, detail="Only managers can view routing rules")
    rules = await routing_repository.list_rules(db, scope.organization_id)
    return [_response(rule) for rule in rules if _in_scope(scope, rule)]


async def create_rule(
    db: AsyncSession, scope: AssignmentScope, payload: RoutingRuleWrite
) -> RoutingRuleResponse:
    _require_rule_manager(scope)
    _validate_destination(scope, payload)
    now = _utcnow()
    rule = CrmRoutingRule(
        organization_id=scope.organization_id,
        team_id=payload.team_id,
        name="",
        priority=await routing_repository.next_priority(db, scope.organization_id),
        destination_user_id=payload.destination_user_id,
        created_by_user_id=scope.user_id,
        updated_by_user_id=scope.user_id,
        created_at=now,
        updated_at=now,
    )
    _write(rule, payload, scope.user_id)
    routing_repository.save(db, rule)
    await db.commit()
    await db.refresh(rule)
    return _response(rule)


async def update_rule(
    db: AsyncSession, scope: AssignmentScope, rule_id: int, payload: RoutingRuleUpdate
) -> RoutingRuleResponse:
    _require_rule_manager(scope)
    rule = _require_rule_in_scope(
        scope, await routing_repository.lock_rule(db, scope.organization_id, rule_id)
    )
    if rule.revision != payload.expected_revision:
        raise _conflict()
    _validate_destination(scope, payload)
    _write(rule, payload, scope.user_id)
    rule.revision += 1
    routing_repository.save(db, rule)
    await db.commit()
    await db.refresh(rule)
    return _response(rule)


async def delete_rule(
    db: AsyncSession, scope: AssignmentScope, rule_id: int, expected_revision: int
) -> None:
    _require_rule_manager(scope)
    rule = _require_rule_in_scope(
        scope, await routing_repository.lock_rule(db, scope.organization_id, rule_id)
    )
    if rule.revision != expected_revision:
        raise _conflict()
    await routing_repository.delete(db, rule)
    await db.commit()


async def reorder_rules(
    db: AsyncSession, scope: AssignmentScope, order: RoutingRuleOrder
) -> list[RoutingRuleResponse]:
    """Set the order of every rule this user manages at once, each at the revision the editor
    saw. A manager's rules are reordered among the positions they already hold, so the order of
    other teams' rules (and theirs relative to those) does not change."""
    _require_rule_manager(scope)
    every = list(await routing_repository.list_rules(db, scope.organization_id, lock=True))
    rules = [rule for rule in every if _in_scope(scope, rule)]
    by_id = {rule.id: rule for rule in rules}
    if len(set(order.rule_ids)) != len(order.rule_ids) or set(order.rule_ids) != set(by_id):
        raise _conflict()
    if any(order.expected_revisions.get(rule.id or 0) != rule.revision for rule in rules):
        raise _conflict()
    now = _utcnow()
    slots = sorted(rule.priority for rule in rules)
    for priority, rule_id in zip(slots, order.rule_ids, strict=True):
        rule = by_id[rule_id]
        if rule.priority != priority:
            rule.priority = priority
            rule.revision += 1
            rule.updated_by_user_id = scope.user_id
            rule.updated_at = now
            routing_repository.save(db, rule)
    await db.commit()
    return [
        _response(rule)
        for rule in await routing_repository.list_rules(db, scope.organization_id)
        if _in_scope(scope, rule)
    ]
