import asyncio
from contextlib import asynccontextmanager

from pydantic_ai import RunContext

from app.chat.security import MAX_DETAIL_ROWS, fingerprint, mark_cached, safe_data, safe_tool
from app.crm import assistant
from app.crm.assistant.dependencies import ChatDependencies
from app.crm.assistant.models import CrmAssistantQuery
from app.postgres import get_db_session


@safe_tool
async def query_my_crm_records(
    ctx: RunContext[ChatDependencies | None], request: CrmAssistantQuery
) -> dict:
    """Read the CRM records the authenticated user's role allows in their current organization.

    Resources: leads (the CRM's lead access: leads assigned to the user, unassigned leads in
    the shared pool of a team they belong to and unassigned agency-wide signals; plus every
    lead of the teams they manage, or every lead for an organization administrator),
    owner_properties (claims from your own imports/lists), saved_leads, lead_workspaces,
    owner_workspaces, deals (read-only, by the CRM's deal access: deals the user handles, the
    deals of teams they manage, or every deal for an organization administrator) and
    team_workload (managers and administrators only: per team, open leads per member by stage,
    unassigned and pooled leads, first contacts awaiting or overdue; agents are refused) and
    teams (the CRM's team view: an organization administrator sees every team of the
    organization with its managers and agents, a manager the teams they manage with their
    members, an agent only the names of the teams they belong to; total is the number of teams
    the user can see, which is the organization's count only for an administrator). Pass team
    (the team's name as the user gave it; "CRM" and "team" are ignored) to narrow teams,
    team_workload, leads, renewals or deals to one team. The server supplies identity and
    role; you cannot choose an agent, role or organization.

    Lead, renewal and deal rows name their current handler in handled_by ("you", a colleague's
    name or "unassigned") and their owning team; lead rows say in_team_pool. Their summaries
    also give counts_by_team and counts_by_handler over the same matches. To narrow to one
    colleague's or one team's records, pass handled_by (the name as the user gave it) or team
    (the team's name); if several people match, ask the user which one.

    Lead and renewal rows say assigned_to "you", "colleague" or "unassigned"; use assignment
    ("mine", "colleagues", "unassigned") when the user asks about their own leads, their
    colleagues' or unassigned ones. Use summary_only for counts and breakdowns. ONE summary_only
    call returns the total and counts_by_status for every status; for leads and renewals also
    counts_by_assignment (mine, colleagues, unassigned: the assignment filter's own buckets),
    counts_by_record_kind (opportunity vs unqualified contact) and counts_by_intent
    (buy/rent/sell/let/unknown), separate classifications. Never query each status or assignment
    separately, or list records, to count them; add status or assignment filters only to narrow
    to that subset (e.g. unassigned leads due for follow-up). Other resources have no such
    breakdown. Counts cover all matches; records are paged: one answer may include at most 10
    records with personal details, so request at most 10 and read page (matching, included,
    complete, next_offset). For the next records ("show the next 10") pass offset=next_offset
    in a later message. Lead search matches contact name,
    source and the lead's stored location names, literally (abbreviations such as JVC are not
    expanded). Use search for names/locations on leads or owner properties, and identifiers on
    saved leads/workspaces. Use record_id for a specific returned record, status for a stored
    status, and follow_up_before (inclusive) for due leads/workspaces. Request phone/email
    with include_contact_details only when needed to answer the user's question. Use renewals for opened renewal leads you can currently see (record_id retrieves
    current lease evidence without owner enrichment). Use reminders, viewings and listing_drafts
    for your own stored workflow records. Use lead_notes or lead_activities for every author's entries on
    leads you can see (each row's author is "you" or "colleague"), and workspace_notes or owner_notes
    for your own text on your workspaces. Search is bounded literal text matching. Matching
    is unavailable. Never go beyond what the tool returns.
    """
    if ctx.deps is None:
        return {"available": False, "reason": "Authenticated CRM context is required"}
    deps = ctx.deps
    # A turn reads identical CRM records once: a repeat of the exact query (a retry, or a second
    # workflow in the same turn) reuses that result instead of re-reading the database,
    # re-spending the detail budget and recording duplicate evidence. Any differing argument
    # (filter, assignment, page, contact details) is a separate read.
    if request.summary_only:
        # A summary returns no rows: paging and contact details change none of its counts, so
        # summaries that differ only there are the same read.
        request = request.model_copy(
            update={
                field: CrmAssistantQuery.model_fields[field].default
                for field in ("limit", "offset", "include_contact_details")
            }
        )
    key = fingerprint(request.model_dump(mode="json"))
    read = deps.crm_reads.get(key)
    if read is None:
        read = deps.crm_reads[key] = asyncio.ensure_future(_read(deps, request))

        def forget_unusable(task: asyncio.Future) -> None:
            # Failed or refused reads are not reused; a later identical call tries afresh.
            if task.cancelled() or task.exception() or task.result().get("available") is False:
                deps.crm_reads.pop(key, None)

        read.add_done_callback(forget_unusable)
    else:
        mark_cached()
    return await read


async def _read(deps: ChatDependencies, request: CrmAssistantQuery) -> dict:
    reserved_rows = 0
    if not request.summary_only:
        remaining = deps.retrieval_budget["crm_detail_rows"]
        if remaining <= 0:
            return {
                "available": False,
                "reason": "This turn's private detail limit is reached. Use an aggregate summary or narrow the question.",
            }
        reserved_rows = min(request.limit, remaining)
        # No await before reservation: parallel specialists share this exact budget.
        deps.retrieval_budget["crm_detail_rows"] -= reserved_rows
        request = request.model_copy(update={"limit": reserved_rows})
    # Each tool gets a separate session: Pydantic AI can run tools concurrently.
    async with asynccontextmanager(get_db_session)() as db:
        result = await assistant.query_my_records(
            db, request, user_id=deps.user_id, organization_id=deps.organization_id
        )
        if reserved_rows:
            deps.retrieval_budget["crm_detail_rows"] += max(0, reserved_rows - len(result.records))
        payload = safe_data(result.model_dump(mode="json"))
        payload["source"] = "Your CRM records"
        refs = [
            {"resource": request.resource, "record_id": row["id"]}
            for row in result.records
            if isinstance(row.get("id"), int)
        ][:20]
        # An answer without rows (a count, an empty list) is kept while the role's view is.
        view = (
            {
                "view": await assistant.view_signature(
                    db, user_id=deps.user_id, organization_id=deps.organization_id
                )
            }
            if not refs and request.resource not in {"teams", "team_workload"}
            else {}
        )
        deps.evidence.append(
            {
                "query": request.model_dump(mode="json"),
                "fingerprint": fingerprint(payload),
                "resource_refs": refs,
                **view,
                # Team views carry no record IDs: the teams shown, and whether their members
                # were, so the answer is withheld only if that view is lost.
                **(
                    {
                        "teams_shown": [
                            {"team": row["team"], "members": "agents" in row}
                            for row in result.records
                        ]
                    }
                    if request.resource in {"teams", "team_workload"}
                    else {}
                ),
            }
        )
        if not request.summary_only and isinstance(result.total, int):
            _describe_page(payload, request, len(result.records), result.total)
        return payload


def _describe_page(payload: dict, request: CrmAssistantQuery, included: int, total: int) -> None:
    """State plainly how much of the matching set this read holds and how to continue.

    Personal detail is capped per answer (retrieval_budget, matching the output guard's
    MAX_DETAIL_ROWS), so a list may be partial: the model must say so, never describe records
    it did not receive, and offer the next page in a later message or a filter.
    """
    next_offset = request.offset + included
    complete = next_offset >= total
    payload["page"] = {
        "matching": total,
        "included": included,
        "first": request.offset + 1 if included else None,
        "last": next_offset if included else None,
        "complete": complete,
        "next_offset": None if complete else next_offset,
    }
    if not complete:
        payload["limitations"] = [
            *payload.get("limitations", []),
            f"Partial list: {total} records match and this answer holds {included} "
            f"(numbers {request.offset + 1}-{next_offset}). An answer may include at most "
            f"{MAX_DETAIL_ROWS} records with personal details. Say how many match and how many "
            "are shown, describe only the records returned, and offer the next ones (offset "
            f"{next_offset}) in the user's next message or a narrower filter (team, handler, "
            "area, status).",
        ]
