from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.crm.assignment import AssignmentScope
from app.crm.inbound_models import CrmInboundEnquiry
from app.crm.routing import RuleSnapshot, first_match, rule_matches
from app.crm.routing_models import (
    ImportAssignmentPolicy,
    LeadAssignmentRequest,
    RoutingCondition,
)


def _lead(**overrides) -> CrmInboundEnquiry:
    now = datetime.now(timezone.utc)
    values = dict(
        organization_id="org",
        contact_id=1,
        created_by_user_id="manager",
        intent="buy",
        source="Property Finder",
        criteria={"locations": ["JVC"]},
        enquiry_date=now,
        created_at=now,
        updated_at=now,
    )
    return CrmInboundEnquiry(**{**values, **overrides})


def _rule(rule_id, destination, *conditions, match="all") -> RuleSnapshot:
    return RuleSnapshot(
        id=rule_id,
        revision=1,
        team_id="team",
        destination_user_id=destination,
        match_mode=match,
        conditions=tuple(RoutingCondition(field=f, values=v) for f, v in conditions),
    )


def test_first_matching_rule_wins_so_the_order_managers_set_is_the_order_applied():
    rules = [
        _rule(1, "omar", ("area", ["JVC"])),
        _rule(2, "sara", ("intent", ["buy"])),  # also matches, but comes second
    ]
    assert first_match(rules, _lead()).destination_user_id == "omar"
    assert first_match(list(reversed(rules)), _lead()).destination_user_id == "sara"


def test_area_rules_route_jvc_and_marina_leads_to_different_agents():
    rules = [_rule(1, "omar", ("area", ["JVC"])), _rule(2, "sara", ("area", ["Dubai Marina"]))]
    jvc = _lead(criteria={"locations": ["jvc "]})  # case and spacing from a spreadsheet
    marina = _lead(criteria={"locations": ["Downtown Dubai", "Dubai Marina"]})
    assert first_match(rules, jvc).destination_user_id == "omar"
    assert first_match(rules, marina).destination_user_id == "sara"


def test_missing_data_never_counts_as_a_match():
    # An unqualified lead must stay unassigned and reported, not guessed into someone's queue.
    rules = [
        _rule(1, "omar", ("area", ["JVC"])),
        _rule(2, "sara", ("intent", ["buy", "rent", "sell", "let"])),
        _rule(3, "lina", ("source", ["Property Finder"])),
    ]
    lead = _lead(intent="unknown", source="", criteria={})
    assert first_match(rules, lead) is None


def test_match_all_needs_every_condition_and_match_any_needs_one():
    conditions = (("area", ["JVC"]), ("intent", ["rent"]))
    buyer_in_jvc = _lead()
    assert not rule_matches(_rule(1, "omar", *conditions, match="all"), buyer_in_jvc)
    assert rule_matches(_rule(1, "omar", *conditions, match="any"), buyer_in_jvc)


def test_conditions_are_typed_so_a_rule_cannot_carry_an_expression_or_an_unknown_intent():
    with pytest.raises(ValidationError):
        RoutingCondition(field="raw_notes", values=["x"])
    with pytest.raises(ValidationError):
        RoutingCondition(field="intent", values=["unknown"])  # missing data, not a target
    with pytest.raises(ValidationError):
        RoutingCondition(field="area", values=["  "])
    assert RoutingCondition(field="intent", values=["BUY"]).values == ["buy"]


def test_import_policy_names_an_agent_only_in_agent_mode():
    with pytest.raises(ValidationError):
        ImportAssignmentPolicy(mode="agent")
    with pytest.raises(ValidationError):
        ImportAssignmentPolicy(mode="unassigned", assignee_user_id="omar")
    assert ImportAssignmentPolicy(mode="rules").assignee_user_id is None
    # "self" takes the assignee from the signed-in user; a body naming someone is refused.
    with pytest.raises(ValidationError):
        ImportAssignmentPolicy(mode="self", assignee_user_id="omar")


def test_bulk_assignment_is_bounded_and_carries_the_revision_seen_for_each_lead():
    with pytest.raises(ValidationError):
        LeadAssignmentRequest(enquiry_ids=list(range(101)), expected_revisions={})
    with pytest.raises(ValidationError):
        LeadAssignmentRequest(enquiry_ids=[1, 2], expected_revisions={1: 0})
    with pytest.raises(ValidationError):
        LeadAssignmentRequest(enquiry_ids=[1, 1], expected_revisions={1: 0})


def _scope(admin=False, supervised=(), teams=None, member_of=()) -> AssignmentScope:
    return AssignmentScope(
        organization_id="org",
        user_id="me",
        organization_admin=admin,
        supervised_team_ids=frozenset(supervised),
        team_members={team: frozenset(users) for team, users in (teams or {}).items()},
        member_team_ids=frozenset(member_of) | frozenset(supervised),
    )


def test_a_manager_reassigns_only_leads_their_own_teams_own():
    manager = _scope(supervised={"north"}, teams={"north": {"me", "omar"}})
    assert manager.may_reassign(_lead(team_id="north", assigned_user_id=None))
    assert manager.may_reassign(_lead(team_id="north", assigned_user_id="omar"))
    # Another team's lead stays with that team, even when held by someone also in North: the
    # Downtown manager does not handle Business Bay's leads (meeting, 28:40).
    assert not manager.may_reassign(_lead(team_id="south", assigned_user_id="omar"))
    # An unowned lead is the administrators' to place, unless it is an agency-wide signal.
    assert not manager.may_reassign(_lead(team_id=None, assigned_user_id=None))
    assert manager.may_reassign(
        _lead(team_id=None, assigned_user_id=None, source="Owner file · recently sold")
    )


def test_who_sees_a_lead():
    """The permission table: administrators see everything in the organization; managers their
    teams' leads; anyone their own leads, their teams' shared pools and agency-wide signals."""
    admin = _scope(admin=True)
    manager = _scope(supervised={"north"}, teams={"north": {"me"}})
    agent = _scope(member_of={"north"})
    loner = _scope()  # in no team: sees only what is assigned to them
    now = datetime.now(timezone.utc)
    north_held = _lead(team_id="north", assigned_user_id="omar")
    south_held = _lead(team_id="south", assigned_user_id="lina")
    north_waiting = _lead(team_id="north", assigned_user_id=None)
    north_pool = _lead(team_id="north", assigned_user_id=None, pool_released_at=now)
    south_pool = _lead(team_id="south", assigned_user_id=None, pool_released_at=now)
    legacy = _lead(team_id=None, assigned_user_id="omar")
    mine = _lead(team_id=None, assigned_user_id="me")
    signal = _lead(team_id=None, assigned_user_id=None, source="Vitevue lease lead")
    other_org = _lead(organization_id="elsewhere", assigned_user_id="me")

    def seen(scope):
        return [
            scope.can_view(lead)
            for lead in (
                north_held, south_held, north_waiting, north_pool, south_pool, legacy, mine,
                signal, other_org,
            )
        ]  # fmt: skip

    assert seen(admin) == [True, True, True, True, True, True, True, True, False]
    assert seen(manager) == [True, False, True, True, False, False, True, True, False]
    assert seen(agent) == [False, False, False, True, False, False, True, True, False]
    assert seen(loner) == [False, False, False, False, False, False, True, True, False]


def test_a_pooled_lead_is_read_only_to_agents_until_claimed():
    now = datetime.now(timezone.utc)
    pooled = _lead(team_id="north", assigned_user_id=None, pool_released_at=now)
    assert not _scope(member_of={"north"}).can_edit(pooled)
    assert _scope(supervised={"north"}, teams={"north": {"me"}}).can_edit(pooled)


def test_an_agent_cannot_assign_and_an_administrator_can_reassign_any_lead():
    agent = _scope()
    assert not agent.can_assign
    assert not agent.may_reassign(_lead(assigned_user_id=None))
    admin = _scope(admin=True, teams={"north": {"omar"}, "south": {"sara"}})
    assert admin.may_reassign(_lead(assigned_user_id="someone-outside-teams"))
    assert admin.eligible_user_ids == {"omar", "sara"}
