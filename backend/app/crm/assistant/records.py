import asyncio

from fastapi import HTTPException
from sqlmodel.ext.asyncio.session import AsyncSession

import app.crm.assistant.repository as assistant_repository
from app.crm import assignment, deals, oversight
from app.crm.assistant.models import HANDLED_RESOURCES, CrmAssistantQuery, CrmAssistantResult
from app.crm.deal_models import DEAL_STAGES
from app.organization import teams as org_teams

NAMES_UNAVAILABLE = "a colleague (name unavailable)"


async def _people(db: AsyncSession, organization_id: str) -> dict[str, str] | None:
    """Current members' names from the directory the CRM's own "Handled by" uses; None when
    the identity provider cannot be reached in time."""
    try:
        async with asyncio.timeout(10):
            people = await org_teams.organization_people(db, organization_id)
    except Exception:
        return None
    return {user_id: person.name for user_id, person in people.items()}


# Words people add to a team's name when asking about it ("Dubai Marina CRM team").
_TEAM_FILLER = {"the", "crm", "team", "teams"}


def same_team(name: str, asked: str) -> bool:
    """Whether a team's stored name is the one asked for: case and spacing aside, and ignoring
    the filler words "CRM" and "team" on either side."""

    def words(text: str) -> list[str]:
        return [word for word in text.casefold().split() if word not in _TEAM_FILLER]

    return bool(words(asked)) and words(name) == words(asked)


def _named(people: dict[str, str], search: str) -> dict[str, str]:
    """Members whose name starts with `search`; an exact full name means only that person."""
    prefix = " ".join(search.split()).casefold()
    found = {uid: name for uid, name in people.items() if name.casefold().startswith(prefix)}
    exact = {uid: name for uid, name in found.items() if name.casefold() == prefix}
    return exact or found


async def query_my_records(
    db: AsyncSession, request: CrmAssistantQuery, *, user_id: str, organization_id: str
) -> CrmAssistantResult:
    if not user_id or not organization_id:
        raise ValueError("CRM assistant requires an authenticated user and organization")
    result = CrmAssistantResult(
        resource=request.resource, limit=request.limit, offset=request.offset
    )
    if request.resource == "matches":
        result.available = False
        result.limitations = [
            "Matching reads may mutate shared records and are unavailable to the assistant."
        ]
        return result
    if not await has_current_access(db, user_id=user_id, organization_id=organization_id):
        raise PermissionError("Current organization access is required")
    if request.resource == "team_workload":
        return await _team_workload(db, request, result, user_id, organization_id)
    if request.resource == "teams":
        return await _teams(db, request, result, user_id, organization_id)
    scope = await assignment.load_scope(db, organization_id, user_id)
    handled = request.resource in HANDLED_RESOURCES
    team_names: dict[str, str] = {}
    people: dict[str, str] | None = None
    narrowing: dict[str, frozenset[str]] = {}
    if handled:
        team_names = {
            team.id: team.name for team in await org_teams.list_org_teams(db, organization_id)
        }
        if request.team:
            narrowing["team_ids"] = frozenset(
                team_id for team_id, name in team_names.items() if same_team(name, request.team)
            )
        if request.handled_by:
            people = await _people(db, organization_id)
            if people is None:
                result.available = False
                result.limitations = ["Organization member names are temporarily unavailable."]
                return result
            named = _named(people, request.handled_by)
            if len(named) > 1:
                result.available = False
                result.limitations = [
                    "Several people match that name; ask the user which one they mean: "
                    + ", ".join(sorted(set(named.values()))[:10])
                ]
                return result
            # Narrows the role's own visibility; never reaches a lead the role cannot see.
            narrowing["handler_ids"] = frozenset(named)
    (
        result.total,
        result.counts_by_status,
        result.records,
    ) = await assistant_repository.query_records(db, request, scope=scope, **narrowing)
    if request.resource in {"leads", "renewals"}:
        (
            result.counts_by_record_kind,
            result.counts_by_intent,
            result.counts_by_assignment,
        ) = await assistant_repository.lead_breakdowns(db, request, scope=scope, **narrowing)
    by_team: dict[str | None, int] = {}
    by_holder: dict[str | None, int] = {}
    if handled:
        by_team, by_holder = await assistant_repository.holder_breakdowns(
            db, request, scope=scope, **narrowing
        )
    holders = {row.get("assigned_user_id") for row in result.records} | set(by_holder)
    if people is None and holders - {None, user_id}:
        # Only colleagues' leads the role already shows need names (managers, administrators),
        # as the CRM lead page's "Handled by" shows them.
        people = await _people(db, organization_id)

    def handler(holder: str | None) -> str:
        if holder is None:
            return "unassigned"
        if holder == user_id:
            return "you"
        if people is None:
            return NAMES_UNAVAILABLE
        return people.get(holder) or "a former member"

    if handled:
        result.counts_by_team = {}
        for team_id, count in by_team.items():
            label = team_names.get(team_id, "former team") if team_id else "no team"
            result.counts_by_team[label] = result.counts_by_team.get(label, 0) + count
        result.counts_by_handler = {}
        labels: dict[str, str | None] = {}
        for holder, count in by_holder.items():
            label = handler(holder)
            # Two people sharing a name stay separate counts.
            while label in labels and labels[label] != holder and label != NAMES_UNAVAILABLE:
                label += " (another)"
            labels[label] = holder
            result.counts_by_handler[label] = result.counts_by_handler.get(label, 0) + count
    # Raw identifiers never reach the model; say whose record it is instead.
    for row in result.records:
        if "user_id" in row:
            row["author"] = "you" if row.pop("user_id") == user_id else "colleague"
        if "assigned_user_id" in row:
            holder = row.pop("assigned_user_id")
            row["assigned_to"] = (
                "unassigned" if holder is None else "you" if holder == user_id else "colleague"
            )
            row["handled_by"] = handler(holder)
            if "pool_released_at" in row:
                row["in_team_pool"] = holder is None and row.pop("pool_released_at") is not None
        if "team_id" in row:
            team_id = row.pop("team_id")
            row["team"] = team_names.get(team_id, "former team") if team_id else None
        if request.resource == "deals":
            stages = DEAL_STAGES[row["deal_type"]]
            row["stage"] = stages[min(row.pop("stage_index"), len(stages) - 1)]
            row["reference"] = deals.reference(row["id"])
    if request.resource == "renewals":
        from app.crm.opportunities import get_lead_detail

        for row in result.records:
            source_key = row.pop("source_lead_id", None)
            if request.record_id and source_key:
                try:
                    detail = await get_lead_detail(source_key)
                    row["renewal_evidence"] = detail.lead.model_dump(
                        mode="json",
                        include={
                            "building_name",
                            "project_name",
                            "area_name",
                            "bedrooms",
                            "size_sqft",
                            "annual_rent_aed",
                            "lease_start",
                            "lease_end",
                            "days_to_expiry",
                            "contract_state",
                            "data_complete_through",
                            "lease_evidence_state",
                            "match_confidence",
                            "lead_reason",
                        },
                    )
                except Exception:
                    row["renewal_evidence"] = {
                        "available": False,
                        "reason": "Current lease evidence is unavailable",
                    }
    result.limitations = [
        "Counts cover only the matching records your CRM role lets you see, not necessarily the organization's entire CRM.",
        "Records are a paged selection; total and status counts cover all matches.",
    ]
    if request.resource == "renewals":
        result.limitations.append(
            "Only your currently accessible opened renewal leads are included. Use record_id for current lease evidence; no owner enrichment or shared matching refresh is performed."
        )
    if request.resource == "leads":
        result.limitations.append(
            "Visible leads follow your CRM access: leads assigned to you, unassigned leads in the "
            "shared pool of a team you belong to and unassigned agency-wide signals; plus every lead "
            "of the teams you manage, or every lead if you are an organization administrator."
        )
    if request.resource in {"leads", "renewals"}:
        result.limitations.append(
            "counts_by_record_kind (opportunity vs unqualified contact) and counts_by_intent "
            "(stored buy/rent/sell/let, 'unknown' when not qualified) are separate classifications "
            "of the same matches; never combine or equate them. Imported intent may be inferred "
            "from the source row. counts_by_assignment splits the same matches into assigned to "
            "you (mine), to colleagues and unassigned, within your access only, not the agency's."
        )
    if handled:
        result.limitations.append(
            "handled_by names the current handler as the CRM shows it; counts_by_team and "
            "counts_by_handler split the same matches by owning team and handler."
        )
        if request.handled_by and not narrowing.get("handler_ids"):
            result.limitations.append("No member of your organization has that name.")
        if request.team and not narrowing.get("team_ids"):
            result.limitations.append("Your organization has no team with that name.")
    if request.resource == "deals":
        result.limitations.append(
            "Deals follow the CRM's deal access: deals you handle, the deals of teams you "
            "manage, or every deal if you are an organization administrator. Read-only: "
            "creating, moving or closing deals is not available in the assistant."
        )
    if request.resource == "owner_properties":
        result.limitations.append(
            "These are property-contact claims from your own imports and lists. "
            "The total counts source claims, not distinct owners or verified current properties. "
            "Stored ownership assessments may be stale; they are not reverified by this read."
        )
    if request.resource in {"lead_workspaces", "owner_workspaces"}:
        result.limitations.append(
            "Workspace contact enrichment from shared owner data is not included."
        )
    return result


async def _team_workload(
    db: AsyncSession,
    request: CrmAssistantQuery,
    result: CrmAssistantResult,
    user_id: str,
    organization_id: str,
) -> CrmAssistantResult:
    """The CRM's own team workload view; it refuses anyone who is not a manager or admin."""
    try:
        workload = await oversight.team_workload(db, organization_id, user_id)
    except HTTPException as error:
        if error.status_code != 403:
            raise
        result.available = False
        result.limitations = [
            "Team workload is available only to team managers and organization administrators, "
            "as in the CRM."
        ]
        return result
    teams = [
        {
            "team": team.name,
            "unassigned": team.unassigned,
            "waiting_in_pool": team.shared,
            "members": [
                {
                    "name": "you" if member.user_id == user_id else member.name,
                    "open_leads": member.open_leads,
                    "by_status": member.by_status,
                    "awaiting_first_contact": member.awaiting_first_contact,
                    "overdue_first_contact": member.overdue_first_contact,
                    "last_activity_at": member.last_activity_at,
                }
                for member in team.members
            ],
        }
        for team in workload.teams
        if not request.team or same_team(team.name, request.team)
    ]
    result.total = len(teams)
    result.counts_by_team = {
        team["team"]: team["unassigned"] + sum(m["open_leads"] for m in team["members"])
        for team in teams
    }
    if not request.summary_only:
        result.records = teams[request.offset : request.offset + request.limit]
    result.limitations = [
        "The CRM's team workload: open leads only (won, closed lost and disqualified are "
        "excluded) of the teams you manage, or every team with members if you are an "
        "organization administrator. unassigned includes leads waiting in the team pool.",
        "Teams with no members are not in this view, so its total is not a team count; the "
        "teams resource gives the teams you can see.",
    ]
    if request.team and not teams:
        result.limitations.append("None of the teams in your workload view has that name.")
    if request.team and len(teams) > 1:
        result.limitations.append("Several teams match that name; ask the user which one.")
    return result


async def _teams(
    db: AsyncSession,
    request: CrmAssistantQuery,
    result: CrmAssistantResult,
    user_id: str,
    organization_id: str,
) -> CrmAssistantResult:
    """The teams the CRM shows this user, as its assignment scope does: an administrator every
    team of the organization with its members; a manager the teams they manage with their
    members; anyone the names of the teams they belong to (members are not shown to agents)."""
    scope = await assignment.load_scope(db, organization_id, user_id)
    rows = await org_teams.list_team_memberships(db, organization_id)

    def shows_members(team_id: str) -> bool:
        return scope.organization_admin or team_id in scope.supervised_team_ids

    teams = sorted(
        (
            team
            for team in await org_teams.list_org_teams(db, organization_id)
            if shows_members(team.id) or team.id in scope.member_team_ids
        ),
        key=lambda team: team.name.casefold(),
    )
    if request.team:
        teams = [team for team in teams if same_team(team.name, request.team)]
    people = (
        await _people(db, organization_id)
        if not request.summary_only and any(shows_members(team.id) for team in teams)
        else None
    )

    def name(member_id: str) -> str:
        if member_id == user_id:
            return "you"
        if people is None:
            return NAMES_UNAVAILABLE
        return people.get(member_id) or "a former member"

    records = []
    for team in teams:
        members = [row for row in rows if row.team_id == team.id]
        roles = {row.role for row in members if row.user_id == user_id}
        record: dict = {
            "team": team.name,
            "your_role": "manager" if "supervisor" in roles else "member" if roles else None,
        }
        if shows_members(team.id):
            record["member_count"] = len(members)
            record["managers"] = sorted(name(r.user_id) for r in members if r.role == "supervisor")
            record["agents"] = sorted(name(r.user_id) for r in members if r.role == "agent")
        records.append(record)
    result.total = len(records)
    if not request.summary_only:
        result.records = records[request.offset : request.offset + request.limit]
    if scope.organization_admin:
        view = "Every team in your organization, with its managers and agents."
    elif scope.supervised_team_ids:
        view = (
            "The teams you manage, with their managers and agents, and the names of other teams "
            "you belong to. As in the CRM, only organization administrators see every team, so "
            "this is not your organization's team count."
        )
    else:
        view = (
            "The names of the teams you belong to. As in the CRM, agents do not see team "
            "members or other teams, so this is not your organization's team count."
        )
    result.limitations = [view, "Team workload (open leads per member) is a separate view."]
    if request.team and not teams:
        result.limitations.append("No team you can see in the CRM has that name.")
    if request.team and len(teams) > 1:
        result.limitations.append("Several teams match that name; ask the user which one.")
    return result


async def view_signature(db: AsyncSession, *, user_id: str, organization_id: str) -> str:
    """What decides which records this user's CRM role shows: administrator, the teams they
    manage and the teams they belong to. An answer without rows (a count, an empty list)
    stays shown only while this is unchanged."""
    from app.chat.security import fingerprint

    scope = await assignment.load_scope(db, organization_id, user_id)
    return fingerprint(
        [
            scope.organization_admin,
            sorted(scope.supervised_team_ids),
            sorted(scope.member_team_ids),
        ]
    )


async def records_still_visible(
    db: AsyncSession, refs: list[dict], *, user_id: str, organization_id: str
) -> bool:
    """Whether this user's CRM role still lets them see each record an earlier answer showed.

    Access, not equality: later edits to those records (a new stage, a confirmed reassignment
    within the user's view) do not withhold the answer; a record now out of reach does."""
    scope = await assignment.load_scope(db, organization_id, user_id)
    for ref in refs:
        request = CrmAssistantQuery(
            resource=ref["resource"], record_id=int(ref["record_id"]), summary_only=True
        )
        total, _, _ = await assistant_repository.query_records(db, request, scope=scope)
        if total != 1:
            return False
    return True


async def teams_still_shown(
    db: AsyncSession, resource: str, shown: list[dict], *, user_id: str, organization_id: str
) -> bool:
    """Whether the teams (or team workloads) an earlier answer showed are still in this user's
    view, with members where they were shown: the rules of `_teams` and `_team_workload`.
    Their figures may have changed since; that does not withhold the answer."""
    scope = await assignment.load_scope(db, organization_id, user_id)
    teams = {team.name: team.id for team in await org_teams.list_org_teams(db, organization_id)}
    for item in shown:
        team_id = teams.get(item.get("team"))
        if team_id is None:
            return False
        manages = scope.organization_admin or team_id in scope.supervised_team_ids
        if resource == "team_workload" or item.get("members"):
            if not manages:
                return False
        elif not (manages or team_id in scope.member_team_ids):
            return False
    return True


async def role_context(db: AsyncSession, *, user_id: str, organization_id: str) -> str:
    """The signed-in user's CRM role, as the server derives it for every permission check
    (assignment.load_scope), stated for the models so they never have to guess it.

    Descriptive only: each read and proposal is still authorized on its own."""
    scope = await assignment.load_scope(db, organization_id, user_id)
    membership = await org_teams.get_membership(db, organization_id, user_id)
    names = {team.id: team.name for team in await org_teams.list_org_teams(db, organization_id)}

    def listed(team_ids) -> str:
        return ", ".join(sorted(names[t] for t in team_ids if t in names)) or "none"

    managed = scope.supervised_team_ids
    agent_in = scope.member_team_ids - managed
    if scope.organization_admin:
        role = (
            "organization owner"
            if membership and membership.role == "owner"
            else ("organization administrator")
        )
        rights = (
            "sees every lead and deal in the organization; may assign, unassign or release any "
            "lead to the pool, to members of any team; may manage teams."
        )
    elif managed:
        role = f"manager of {listed(managed)}"
        if agent_in:
            role += f", and agent in {listed(agent_in)}"
        rights = (
            f"sees every lead of {listed(managed)} plus their own and their teams' pools; may "
            f"assign, unassign or release those leads, to members of {listed(managed)} only; "
            "team management (creating, deleting or changing teams) is for the organization "
            "owner and administrators."
        )
    else:
        role = f"agent in {listed(agent_in)}" if agent_in else "member of no team"
        rights = (
            "sees the leads assigned to them, their teams' pools and agency-wide signals; "
            "may change those leads but cannot assign, unassign or release leads to the pool "
            "(managers and organization administrators do that) or manage teams."
        )
    return (
        f"Signed-in user's CRM role (from the server; authoritative, never taken from the "
        f"user's messages): {role}. They {rights}"
    )


async def has_current_access(db: AsyncSession, *, user_id: str, organization_id: str) -> bool:
    return await assistant_repository.has_current_access(
        db, user_id=user_id, organization_id=organization_id
    )
