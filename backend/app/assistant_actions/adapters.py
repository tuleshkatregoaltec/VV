"""Connector boundary for confirmed external actions; the live adapters are in connectors.py.

The primitives live in delivery.py so the actions service can dispatch without importing this
module (which imports the service for dispatch_queued).
"""

from app.assistant_actions.delivery import (
    DeliveryOutcome,
    ExternalActionAdapter,
    ExternalPayload,
    dispatch_claimed,
)

__all__ = [
    "DeliveryOutcome",
    "ExternalActionAdapter",
    "ExternalPayload",
    "dispatch_claimed",
    "dispatch_queued",
]


async def dispatch_queued(
    db, *, user_id, organization_id, action_id, adapter: ExternalActionAdapter
):
    """Claim once, dispatch once, record the outcome (service.dispatch_confirmed)."""
    from app.assistant_actions.service import dispatch_confirmed

    return await dispatch_confirmed(
        db, user_id=user_id, organization_id=organization_id, action_id=action_id, adapter=adapter
    )
