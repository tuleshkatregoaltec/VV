"""Delivery primitives shared by the actions service and connectors (no service import here).

Adapters must use the proposal ID as the provider idempotency key. A caller must persist an
outbox claim as ``unknown`` *before* dispatch. An ambiguous outcome must be reconciled with the
provider; automatically retrying could send twice.
"""

import asyncio
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict

from app.assistant_actions.models import PublishListing, ScheduleViewing, SendMessage

ExternalPayload = SendMessage | PublishListing | ScheduleViewing


class DeliveryOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["succeeded", "failed", "unknown", "not_connected"]
    # What happened, in words the confirmation card can show.
    message: str | None = None


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
    """One bounded call only; an exception or timeout is an unknown outcome, never a retry."""
    try:
        async with asyncio.timeout(20):
            return await adapter.dispatch(payload=payload, idempotency_key=idempotency_key)
    except Exception:
        # A timeout/error after provider acceptance is not proof of failure.
        return DeliveryOutcome(status="unknown")
