"""Server-scoped customer evidence access; no private CRM or arbitrary query surface."""

from datetime import timedelta

from app.analytics.market_metrics import get_market_metrics
from app.analytics.models import MarketMetricsRequest, MarketPeriodRequest
from app.whatsapp import customer_repository as repository
from app.whatsapp import customer_voice as voice
from app.whatsapp.customer_evidence import (
    CustomerEvidence,
    CustomerRetrieval,
    ListingSearch,
    MarketSummary,
    listing_evidence,
    market_evidence,
)
from app.whatsapp.customer_policy import rejected_text
from app.whatsapp.models import utcnow


async def retrieve(db, request: CustomerRetrieval, *, connection_id, user_id, organization_id):
    """Identity comes from the locked worker connection, never model arguments."""
    connection = await repository.connection(db, connection_id, user_id, organization_id)
    if connection is None or not connection.enabled:
        return []
    if request.location and rejected_text(request.location):
        return []
    if isinstance(request, ListingSearch):
        rows = await repository.published_listings(
            db,
            connection_id,
            user_id,
            organization_id,
            active_at=utcnow(),
            filters=request,
            limit=5,
        )
        return [item for row in rows if not rejected_text((item := listing_evidence(row)).text)]
    if not isinstance(request, MarketSummary) or not connection.market_data_enabled:
        return []
    # Only aggregate count and median, at city/community level, <= one quarter.
    # No rows, contact fields, project/unit filters, model SQL or release choice.
    result = await get_market_metrics(
        MarketMetricsRequest(
            dataset=request.dataset,
            metrics=["count", "median_aed"],
            period=MarketPeriodRequest(type=request.period),
            location=request.location,
            limit=1,
            min_group_count=10,
        )
    )
    item = market_evidence(
        result, expires_at=utcnow() + timedelta(minutes=15), location=request.location
    )
    return [item] if item is not None and not rejected_text(item.text) else []


async def valid_evidence(
    db, connection, evidence_ids, snapshots, reply, *, human_edited=False, context=()
):
    """Revalidate the evidence behind a reply under the connection lock before sending.

    Human edits are explicit broker statements and require the existing approval flow.
    Generated replies must rest on still-authorized facts and, unless they quote those
    facts verbatim, pass the same deterministic wording checks as at draft time.
    `context` is what the buyer said, so numbers they gave may be echoed.
    """
    if human_edited:
        return not evidence_ids and not snapshots
    try:
        items = [CustomerEvidence.model_validate(item) for item in snapshots]
    except (ValueError, TypeError):
        return False
    if len(items) > 5 or len({item.id for item in items}) != len(items):
        return False
    if any(item.id not in evidence_ids for item in items):
        return False
    facts = {fact["id"]: fact["text"] for fact in connection.approved_knowledge}
    for item in items:
        if item.expires_at <= utcnow():
            return False
        if item.kind == "listing":
            row = await repository.published_listing(
                db, item.listing_id, connection.id, connection.user_id, connection.organization_id
            )
            if row is None or row.revoked_at is not None or row.expires_at <= utcnow():
                return False
            if listing_evidence(row) != item:
                return False
        elif not connection.market_data_enabled or not item.release_id:
            return False
        if item.id in facts or rejected_text(item.text):
            return False
        facts[item.id] = item.text
    agent_name = voice.prompt_voice(connection.reply_voice, display_name=connection.display_name)[
        "agent_name"
    ]
    if not evidence_ids:
        # Questions and holding lines state no facts, only echo what the buyer said.
        return not items and not voice.reply_violations(
            reply, sources=[], context=context, agent_name=agent_name
        )
    if len(set(evidence_ids)) != len(evidence_ids) or any(key not in facts for key in evidence_ids):
        return False
    chosen = [facts[key] for key in evidence_ids]
    return reply == "\n\n".join(chosen) or not voice.reply_violations(
        reply, sources=chosen, context=context, agent_name=agent_name
    )
