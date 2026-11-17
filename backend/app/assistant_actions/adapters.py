"""Typed future connector boundary; no live adapter or dispatcher is configured.

Adapters must use the proposal ID as the provider idempotency key. A caller must
persist an outbox claim as ``unknown`` *before* dispatch. An ambiguous outcome
must be reconciled with the provider; automatically retrying could send twice.
"""

import asyncio
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict

from app.assistant_actions.models import PublishListing, ScheduleViewing, SendMessage

ExternalPayload = SendMessage | PublishListing | ScheduleViewing


class DeliveryOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["succeeded", "failed", "unknown", "not_connected"]


class ExternalActionAdapter(Protocol):
    async def dispatch(self, *, payload: ExternalPayload, idempotency_key: str) -> DeliveryOutcome:
        """A configured adapter resolves destinations from authorized server-side records."""
        ...


async def dispatch_claimed(
    adapter: ExternalActionAdapter,
    *,
    payload: ExternalPayload,
    idempotency_key: str,
) -> DeliveryOutcome:
    """One bounded call only. This is deliberately not wired to an application entrypoint."""
    try:
        async with asyncio.timeout(10):
            return await adapter.dispatch(payload=payload, idempotency_key=idempotency_key)
    except Exception:
        # A timeout/error after provider acceptance is not proof of failure.
        return DeliveryOutcome(status="unknown")


async def dispatch_queued(
    db, *, user_id, organization_id, action_id, adapter: ExternalActionAdapter
):
    """Dormant worker integration; no endpoint, configuration, or live adapter installs it."""
    from app.assistant_actions.service import claim_external_dispatch, record_external_outcome

    payload = await claim_external_dispatch(
        db,
        user_id=user_id,
        organization_id=organization_id,
        action_id=action_id,
    )
    if payload is None:
        return None
    outcome = await dispatch_claimed(adapter, payload=payload, idempotency_key=action_id)
    await record_external_outcome(
        db,
        user_id=user_id,
        organization_id=organization_id,
        action_id=action_id,
        status=outcome.status,
    )
    return outcome
