from contextlib import asynccontextmanager

from pydantic_ai import RunContext

from app.chat.dependencies import ChatDependencies
from app.chat.security import fingerprint, safe_data, safe_tool
from app.crm import assistant
from app.crm.assistant_models import CrmAssistantQuery
from app.postgres import get_db_session


@safe_tool
async def query_my_crm_records(
    ctx: RunContext[ChatDependencies | None], request: CrmAssistantQuery
) -> dict:
    """Read the CRM records the authenticated user's role allows in their current organization.

    Resources: leads (by CRM role: an agent's own and their team pool, a manager's teams, an
    organization administrator's whole organization), owner_properties (claims
    from your own imports/lists), saved_leads, lead_workspaces, owner_workspaces, deals
    (unavailable until persisted). The server supplies identity and role; you cannot choose
    an agent, role or organization.

    Lead and renewal rows say assigned_to "you", "colleague" or "unassigned"; use assignment
    ("mine", "colleagues", "unassigned") when the user asks about their own leads, their
    colleagues' or unassigned ones. Use summary_only for counts and status breakdowns. Counts cover all matches; records are
    paged. Use search for names/locations on leads or owner properties, and identifiers on
    saved leads/workspaces. Use record_id for a specific returned record, status for a stored
    status, and follow_up_before (inclusive) for due leads/workspaces. Request phone/email
    with include_contact_details only when needed to answer the user's question. Use renewals for opened renewal leads you can currently see (record_id retrieves
    current lease evidence without owner enrichment). Use reminders, viewings and listing_drafts
    for your own stored workflow records. Use lead_notes or lead_activities for every author's entries on
    leads you can see (each row's author is "you" or "colleague"), and workspace_notes or owner_notes
    for your own text on your workspaces. Search is bounded literal text matching. Matching
    and deals are explicitly unavailable. Never go beyond what the tool returns.
    """
    if ctx.deps is None:
        return {"available": False, "reason": "Authenticated CRM context is required"}
    reserved_rows = 0
    if not request.summary_only:
        remaining = ctx.deps.retrieval_budget["crm_detail_rows"]
        if remaining <= 0:
            return {
                "available": False,
                "reason": "This turn's private detail limit is reached. Use an aggregate summary or narrow the question.",
            }
        reserved_rows = min(request.limit, remaining)
        # No await before reservation: parallel specialists share this exact budget.
        ctx.deps.retrieval_budget["crm_detail_rows"] -= reserved_rows
        request = request.model_copy(update={"limit": reserved_rows})
    # Each tool gets a separate session: Pydantic AI can run tools concurrently.
    async with asynccontextmanager(get_db_session)() as db:
        result = await assistant.query_my_records(
            db, request, user_id=ctx.deps.user_id, organization_id=ctx.deps.organization_id
        )
        if reserved_rows:
            ctx.deps.retrieval_budget["crm_detail_rows"] += max(
                0, reserved_rows - len(result.records)
            )
        payload = safe_data(result.model_dump(mode="json"))
        payload["source"] = "Your CRM records"
        ctx.deps.evidence.append(
            {
                "query": request.model_dump(mode="json"),
                "fingerprint": fingerprint(payload),
                "resource_refs": [
                    {"resource": request.resource, "record_id": row["id"]}
                    for row in result.records
                    if isinstance(row.get("id"), int)
                ][:20],
            }
        )
        return payload
