"""Database-integration layer: each case's reference probe, run against the real CRM.

No language model runs here. A probe calls the same tool function or service the assistant
would (query_my_crm_records, the lookups, propose_crm_action, the confirmation service), as the
case's actor, against a fresh copy of the synthetic fixture in a disposable local database. It
proves the case's expectations are what the CRM actually does: who can see what, which writes
are refused, that nothing is written before confirmation, and what is persisted after it.

`isolated_side_effects` is also used by the live-model runner. Inside it, Brevo and Google
Calendar report themselves unconfigured, the lead mailbox is the fixture's synthetic thread,
names come from the fixture's synthetic directory, and any outbound HTTP request fails unless
its host is explicitly allowed (only the model provider, and only for an opted-in live run).
"""

from __future__ import annotations

import contextlib
import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from unittest import mock

from scripts.evaluations.crm_assistant import crm_fixture as fixture
from scripts.evaluations.crm_assistant.crm_dataset import (
    ActionProbe,
    CalendarProbe,
    CrmCase,
    EmailProbe,
    GuardProbe,
    LookupProbe,
    Mutation,
    NoProbe,
    PendingProbe,
    ReadProbe,
    StateCheck,
)
from scripts.evaluations.crm_assistant.crm_report import CaseResult, Check, safe_error

LAYER = "db_integration"


class NetworkBlocked(RuntimeError):
    """An evaluation tried to reach a host it was not allowed to."""


@contextlib.contextmanager
def isolated_side_effects(
    db, seeded: fixture.Seeded, *, allowed_hosts=frozenset()
) -> Iterator[None]:
    """Run the CRM's real code on `db` with every external side effect replaced or blocked."""
    import httpx

    from app.assistant_actions import service as actions
    from app.crm import brevo, calendar_service, email_pipeline
    from app.crm.assistant import connector_tools, crm_tools, workflows
    from app.organization import service as organizations
    from app.organization import teams

    directory = seeded.directory()

    async def person(user_id):
        return directory.get(user_id)

    async def session():
        # One session for the case, as the CRM's own integration tests do. Not rolled back on
        # exit: tools (the calendar) read loaded rows after their session block, which a
        # production session's close keeps but a rollback here would expire.
        yield db

    async def thread(*, organization_id, enquiry_id):
        return seeded.email_thread(enquiry_id) if organization_id == seeded.orgs["A"] else []

    real_async_send, real_send = httpx.AsyncClient.send, httpx.Client.send

    async def async_send(client, request, *args, **kwargs):
        if request.url.host not in allowed_hosts:
            raise NetworkBlocked(f"Outbound request to {request.url.host} blocked")
        return await real_async_send(client, request, *args, **kwargs)

    def send(client, request, *args, **kwargs):
        if request.url.host not in allowed_hosts:
            raise NetworkBlocked(f"Outbound request to {request.url.host} blocked")
        return real_send(client, request, *args, **kwargs)

    patches = [
        *(
            mock.patch.object(m, "get_db_session", session)
            for m in (crm_tools, connector_tools, workflows)
        ),
        *(mock.patch.object(m, "get_user_by_id", person) for m in (organizations, actions, teams)),
        mock.patch.object(brevo, "is_configured", lambda: False),
        mock.patch.object(calendar_service, "configured", lambda: False),
        mock.patch.object(email_pipeline, "lead_thread", thread),
        mock.patch.object(httpx.AsyncClient, "send", async_send),
        mock.patch.object(httpx.Client, "send", send),
    ]
    with contextlib.ExitStack() as stack:
        for patch in patches:
            stack.enter_context(patch)
        yield


def _ctx(deps, tool: str, step: int):
    """The parts of pydantic-ai's RunContext the CRM tools read."""
    return SimpleNamespace(deps=deps, tool_name=tool, tool_call_id=f"probe-{tool}-{step}")


async def _deps(db, seeded: fixture.Seeded, actor: str):
    from app.chat.conversations import create_conversation
    from app.crm.assistant.dependencies import ChatDependencies

    user_id, organization_id = seeded.people[actor], seeded.org_of(actor)
    conversation = await create_conversation(db, user_id, organization_id)
    return ChatDependencies(
        user_id=user_id, organization_id=organization_id, conversation_id=conversation.id
    )


def _eq(name: str, actual: Any, expected: Any) -> Check:
    ok = actual == expected
    return Check(name, ok, "" if ok else f"expected {expected!r}, got {actual!r}")


def _row_keys(seeded: fixture.Seeded, resource: str, rows: list[dict], actor: str) -> list[str]:
    """Map returned rows back to fixture keys (by ID: names repeat, e.g. two Bilal Hameeds)."""
    by_id = {
        "leads": seeded.leads,
        "renewals": seeded.leads,
        "deals": seeded.deals,
        "reminders": seeded.reminders,
        "viewings": seeded.viewings,
        "listing_drafts": seeded.listings,
    }
    if resource in by_id:
        reverse = {value: key for key, value in by_id[resource].items()}
        return sorted(reverse.get(row.get("id"), "unknown") for row in rows)
    if resource in {"lead_notes", "lead_activities"}:
        reverse = {value: key for key, value in seeded.leads.items()}
        return sorted(reverse.get(row.get("enquiry_id"), "unknown") for row in rows)
    if resource in {"teams", "team_workload"}:
        org = fixture.PEOPLE[actor][0]
        names = {name: key for key, (o, name, _) in fixture.TEAMS.items() if o == org}
        return sorted(names.get(row.get("team"), "unknown") for row in rows)
    return sorted(str(row.get("id")) for row in rows)


def _excluded(seeded: fixture.Seeded, key: str, rows_keys: list[str], serialized: str) -> bool:
    """Whether an excluded fixture record stays out of a result."""
    if key in fixture.PEOPLE:
        return fixture.display_name(key) not in serialized
    return key not in rows_keys


async def _read(db, seeded, case: CrmCase, probe: ReadProbe) -> list[Check]:
    from app.crm.assistant import crm_tools
    from app.crm.assistant.models import CrmAssistantQuery

    deps = await _deps(db, seeded, case.actor)
    result = await crm_tools.query_my_crm_records(
        _ctx(deps, "query_my_crm_records", 1), CrmAssistantQuery(**probe.query)
    )
    expect = probe.expect
    checks = [_eq("available", result.get("available", True), expect.available)]
    for name in (
        "total",
        "counts_by_status",
        "counts_by_team",
        "counts_by_handler",
        "counts_by_assignment",
    ):
        if getattr(expect, name) is not None:
            checks.append(_eq(name, result.get(name), getattr(expect, name)))
    rows = result.get("records") or []
    keys = _row_keys(seeded, probe.query["resource"], rows, case.actor)
    if expect.records is not None:
        checks.append(_eq("records", keys, sorted(expect.records)))
    if expect.includes:
        missing = sorted(set(expect.includes) - set(keys))
        checks.append(Check("includes", not missing, f"missing {missing}" if missing else ""))
    serialized = json.dumps(result, default=str)
    leaked = [key for key in expect.excludes if not _excluded(seeded, key, keys, serialized)]
    checks.append(Check("excludes", not leaked, f"present {leaked}" if leaked else ""))
    if expect.page is not None:
        page = result.get("page") or {}
        checks.append(_eq("page", {k: page.get(k) for k in expect.page}, expect.page))
    if expect.limitation_contains is not None:
        wanted = expect.limitation_contains.casefold()
        found = any(wanted in str(item).casefold() for item in result.get("limitations", []))
        checks.append(Check("limitation", found, "" if found else "expected limitation absent"))
    return checks


async def _calendar(db, seeded, case: CrmCase, probe: CalendarProbe) -> list[Check]:
    from app.crm.assistant import connector_tools

    deps = await _deps(db, seeded, case.actor)
    result = await connector_tools.query_my_calendar(
        _ctx(deps, "query_my_calendar", 1), probe.start, probe.end
    )
    reverse = {value: key for key, value in seeded.events.items()}
    keys = sorted(reverse.get(event.get("id"), "unknown") for event in result.get("events", []))
    leaked = sorted(set(probe.excludes) & set(keys))
    return [
        _eq("available", result.get("available", True), True),
        _eq("events", keys, sorted(probe.events)),
        Check("excludes", not leaked, f"present {leaked}" if leaked else ""),
    ]


async def _emails(db, seeded, case: CrmCase, probe: EmailProbe) -> list[Check]:
    from app.crm.assistant import connector_tools

    deps = await _deps(db, seeded, case.actor)
    result = await connector_tools.query_my_lead_emails(
        _ctx(deps, "query_my_lead_emails", 1), seeded.leads[probe.lead]
    )
    checks = [_eq("available", result.get("available", True), probe.available)]
    if probe.total is not None:
        checks.append(_eq("total", result.get("total"), probe.total))
    return checks


def _lookup_tool(name: str):
    from app.crm.assistant import workflows

    return getattr(workflows, name)


async def _lookup(db, seeded, case: CrmCase, probe: LookupProbe) -> list[Check]:
    deps = await _deps(db, seeded, case.actor)
    result = await _lookup_tool(probe.tool)(_ctx(deps, probe.tool, 1), probe.search)
    to_key = seeded.team_key if probe.tool == "find_teams" else seeded.person_key
    matches = sorted(to_key(item.get("id")) for item in result.get("matches", []))
    checks = [_eq("available", result.get("available", True), probe.available)]
    if probe.available:
        checks.append(_eq("matches", matches, sorted(probe.matches)))
    if probe.clarification_required is not None:
        checks.append(
            _eq(
                "clarification_required",
                result.get("clarification_required"),
                probe.clarification_required,
            )
        )
    if probe.reason_contains is not None:
        found = probe.reason_contains.casefold() in str(result.get("reason", "")).casefold()
        checks.append(Check("reason", found, "" if found else "expected reason absent"))
    return checks


async def _mutate(db, seeded: fixture.Seeded, change: Mutation) -> None:
    """Someone else changes the CRM between proposal and confirmation."""
    from sqlalchemy import delete, update

    from app.assistant_actions.models import AssistantAction
    from app.crm.calendar_models import CrmCalendarEvent
    from app.crm.inbound_models import CrmInboundEnquiry
    from app.organization.models import (
        Organization,
        OrganizationMembership,
        OrganizationTeamMember,
    )

    lead = CrmInboundEnquiry.id == seeded.leads.get(change.lead or "", -1)
    statement = {
        "reassign_lead": lambda: update(CrmInboundEnquiry)
        .where(lead)
        .values(
            assigned_user_id=seeded.people[change.to] if change.to else None,
            assignment_revision=CrmInboundEnquiry.assignment_revision + 1,
        ),
        "set_lead_status": lambda: update(CrmInboundEnquiry)
        .where(lead)
        .values(status=change.status),
        "remove_team_member": lambda: delete(OrganizationTeamMember).where(
            OrganizationTeamMember.team_id == seeded.teams[change.team],
            OrganizationTeamMember.user_id == seeded.people[change.person],
        ),
        "remove_membership": lambda: delete(OrganizationMembership).where(
            OrganizationMembership.user_id == seeded.people[change.person]
        ),
        "suspend_organization": lambda: update(Organization)
        .where(Organization.id == seeded.orgs["A"])
        .values(subscription_status="canceled"),
        "expire_actions": lambda: update(AssistantAction)
        .where(AssistantAction.user_id == seeded.people[change.person])
        .values(expires_at=datetime.now(UTC) - timedelta(minutes=1)),
        "delete_event": lambda: delete(CrmCalendarEvent).where(
            CrmCalendarEvent.id == seeded.events[change.event]
        ),
    }[change.op]()
    if change.op == "remove_membership":
        await db.exec(
            delete(OrganizationTeamMember).where(
                OrganizationTeamMember.user_id == seeded.people[change.person]
            )
        )
    await db.exec(statement)
    await db.commit()


async def observe(db, seeded: fixture.Seeded, subject: str, field: str) -> Any:
    """One persisted fact, read fresh from the database (see crm_dataset.STATE_FIELDS)."""
    from sqlalchemy import func
    from sqlmodel import select

    from app.assistant_actions.models import (
        AssistantAction,
        AssistantListingDraft,
        AssistantOutbox,
        AssistantReminder,
        AssistantViewing,
    )
    from app.crm.calendar_models import CrmCalendarEvent
    from app.crm.inbound_models import (
        CrmInboundActivity,
        CrmInboundContact,
        CrmInboundEnquiry,
        CrmInboundNote,
    )
    from app.organization.models import OrganizationTeam, OrganizationTeamMember

    db.expire_all()
    kind, key = subject.split(":", 1)
    org_a = seeded.orgs["A"]

    async def count(statement) -> int:
        return int((await db.exec(statement)).one())

    if kind == "lead":
        lead = await db.get(CrmInboundEnquiry, seeded.leads[key])
        values = {
            "assigned_to": lambda: seeded.person_key(lead.assigned_user_id),
            "team": lambda: seeded.team_key(lead.team_id),
            "status": lambda: lead.status,
            "intent": lambda: lead.intent,
            "in_pool": lambda: lead.assigned_user_id is None and lead.pool_released_at is not None,
            "next_follow_up": lambda: lead.next_follow_up.isoformat()
            if lead.next_follow_up
            else None,
        }
        if field in values:
            return values[field]()
        model = CrmInboundNote if field == "notes" else CrmInboundActivity
        return await count(
            select(func.count()).select_from(model).where(model.enquiry_id == lead.id)
        )
    if kind == "team":
        if field == "exists":
            return await db.get(OrganizationTeam, seeded.teams[key]) is not None
        rows = (
            await db.exec(
                select(OrganizationTeamMember).where(
                    OrganizationTeamMember.team_id == seeded.teams[key]
                )
            )
        ).all()
        return sorted(f"{seeded.person_key(row.user_id)}:{row.role}" for row in rows)
    if kind == "team_named":
        return (
            await count(
                select(func.count())
                .select_from(OrganizationTeam)
                .where(OrganizationTeam.organization_id == org_a, OrganizationTeam.name == key)
            )
            > 0
        )
    if kind in {"event", "events_titled"}:
        if kind == "event":
            event = await db.get(CrmCalendarEvent, seeded.events[key])
            if field == "exists":
                return event is not None
        else:
            events = (
                await db.exec(
                    select(CrmCalendarEvent)
                    .where(CrmCalendarEvent.organization_id == org_a, CrmCalendarEvent.title == key)
                    .order_by(CrmCalendarEvent.id)
                )
            ).all()
            if field == "count":
                return len(events)
            event = events[0] if events else None
        if event is None:
            return None
        return {
            "date": event.event_date.isoformat(),
            "time": event.event_time,
            "end_date": (event.event_end_date or event.event_date).isoformat(),
            "end_time": event.event_end_time,
        }[field]
    if kind in {"reminder", "listing"}:
        model = AssistantReminder if kind == "reminder" else AssistantListingDraft
        ids = seeded.reminders if kind == "reminder" else seeded.listings
        row = await db.get(model, ids[key])
        if field == "exists":
            return row is not None
        if row is None:
            return None
        value = getattr(row, field)
        return value.astimezone(UTC).isoformat() if isinstance(value, datetime) else value
    if kind == "leads_named":
        return await count(
            select(func.count())
            .select_from(CrmInboundEnquiry)
            .join(CrmInboundContact, CrmInboundContact.id == CrmInboundEnquiry.contact_id)
            .where(CrmInboundEnquiry.organization_id == org_a, CrmInboundContact.full_name == key)
        )
    model = {
        "reminders": AssistantReminder,
        "viewings": AssistantViewing,
        "listing_drafts": AssistantListingDraft,
        "outbox": AssistantOutbox,
        "actions": AssistantAction,
    }[kind]
    statement = select(func.count()).select_from(model).where(model.user_id == seeded.people[key])
    if model is AssistantViewing:
        statement = statement.where(AssistantViewing.status == "scheduled")
    return await count(statement)


async def _state(db, seeded, checks: list[StateCheck], stage: str, *, after: bool) -> list[Check]:
    results = []
    for item in checks:
        expected = item.expected_after if after else item.before
        actual = await observe(db, seeded, item.subject, item.field)
        results.append(_eq(f"{stage}:{item.subject}.{item.field}", actual, expected))
    return results


async def _action(db, seeded, case: CrmCase, probe: ActionProbe) -> list[Check]:
    from fastapi import HTTPException

    from app.assistant_actions import service as actions
    from app.assistant_actions.models import PAYLOAD_TYPES, ActionKind
    from app.crm.assistant import workflows

    deps = await _deps(db, seeded, case.actor)
    for step, lookup in enumerate(probe.lookups, start=1):
        await _lookup_tool(lookup.tool)(_ctx(deps, lookup.tool, step), lookup.search)
    checks = await _state(db, seeded, probe.state, "before_proposal", after=False)
    kind = ActionKind(probe.kind)
    payload = PAYLOAD_TYPES[kind].model_validate(seeded.resolve(probe.payload))
    result = await workflows.propose_crm_action(
        _ctx(deps, "propose_crm_action", len(probe.lookups) + 1), kind, payload
    )
    stored = await observe(db, seeded, f"actions:{case.actor}", "count")
    if probe.proposal == "created":
        checks += [
            _eq("proposal_status", result.get("status"), "awaiting_confirmation"),
            _eq("confirmation_required", result.get("confirmation_required"), True),
            _eq("proposals_in_turn", len(deps.proposals), 1),
            _eq("stored_proposals", stored, 1),
        ]
    else:
        checks += [
            _eq("proposal_refused", result.get("available"), False),
            _eq("proposals_in_turn", len(deps.proposals), 0),
            _eq("stored_proposals", stored, 0),
        ]
        if probe.reason_contains is not None:
            found = probe.reason_contains.casefold() in str(result.get("reason", "")).casefold()
            checks.append(Check("refusal_reason", found, "" if found else "expected reason absent"))
    # Nothing changes until the user confirms.
    checks += await _state(db, seeded, probe.state, "before_confirmation", after=False)
    for change in probe.between:
        await _mutate(db, seeded, change)
    if probe.decision != "none":
        if not deps.proposals:
            return [*checks, Check("decision", False, "no proposal to decide on")]
        action_id = deps.proposals[0]["id"]
        decide = actions.confirm_action if probe.decision == "confirm" else actions.cancel_action
        try:
            response = await decide(
                db, user_id=deps.user_id, organization_id=deps.organization_id, action_id=action_id
            )
            status = response.status
        except HTTPException as error:
            await db.rollback()
            status = f"error:{error.status_code}"
        checks.append(_eq("final_status", status, probe.final_status))
    checks += await _state(db, seeded, probe.state, "after_decision", after=True)
    return checks


async def _pending(db, seeded, case: CrmCase, probe: PendingProbe) -> list[Check]:
    from app.assistant_actions import service as actions
    from app.assistant_actions.models import ActionKind
    from app.crm.assistant import workflows

    deps = await _deps(db, seeded, case.actor)
    kind = ActionKind(probe.kind) if probe.kind else None
    held = await workflows.hold_pending_request(
        _ctx(deps, "hold_pending_request", 1), kind=kind, lead_id=seeded.leads[probe.lead]
    )
    checks = [_eq("held", held.get("available") is True, probe.held)]
    for change in probe.between:
        await _mutate(db, seeded, change)
    # What the next turn rechecks before it continues the held request.
    later = await actions.pending_target(
        db,
        user_id=deps.user_id,
        organization_id=deps.organization_id,
        kind=kind,
        lead_id=seeded.leads[probe.lead],
    )
    checks.append(_eq("still_held", later.get("available") is True, probe.still_held))
    return checks


RUNNERS = {
    ReadProbe: _read,
    CalendarProbe: _calendar,
    EmailProbe: _emails,
    LookupProbe: _lookup,
    ActionProbe: _action,
    PendingProbe: _pending,
}


async def run_case(db, case: CrmCase) -> CaseResult:
    """Seed a fresh fixture copy and run the case's probe; never raises."""
    probe = case.probe
    if isinstance(probe, NoProbe):
        return CaseResult(case.id, LAYER, "not_applicable", [Check("probe", True, probe.reason)])
    if isinstance(probe, GuardProbe):
        from app.chat.security import input_refusal

        refused = input_refusal(case.question) is not None
        return CaseResult.from_checks(case.id, LAYER, [Check("input_guard_refuses", refused)])
    try:
        seeded = await fixture.seed(db)
        with isolated_side_effects(db, seeded):
            checks = await RUNNERS[type(probe)](db, seeded, case, probe)
    except Exception as exc:
        await db.rollback()
        return CaseResult(case.id, LAYER, "error", [Check("probe_ran", False, safe_error(exc))])
    return CaseResult.from_checks(case.id, LAYER, checks)
