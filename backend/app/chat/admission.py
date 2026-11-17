"""Durable cross-worker turn admission. Expiry frees capacity, never reserved budget.

A turn reserves min(per-turn limit, remaining daily allowance) and settles to the tokens
the provider reported. Only a process lost before settlement keeps its reservation.
"""

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from pydantic_ai.usage import RunUsage

from app.auth.service import get_user_by_id
from app.chat import repository
from app.chat.models import ChatTurnLease
from app.config import settings
from app.postgres import get_db_session
from app.token_usage import repository as usage_repository

USER_CONCURRENCY = 1
TENANT_CONCURRENCY = 20
LEASE_SECONDS = 600  # Longer than the complete turn's 300-second deadline.
BUSY = "Another assistant turn is running. Please try again shortly."
NO_ALLOWANCE = "Insufficient daily token allowance for another assistant turn."


@dataclass(frozen=True)
class TurnLease:
    id: str
    token_budget: int  # this turn's cumulative total_tokens limit


class AdmissionRefused(HTTPException):
    """429 before anything is reserved; `code` ("busy" or "allowance") lets callers wait."""

    def __init__(self, code: str):
        super().__init__(429, BUSY if code == "busy" else NO_ALLOWANCE)
        self.code = code


async def reserve(
    db, *, user_id, organization_id, conversation_id, daily_limit, token_limit=None
) -> TurnLease:
    """Called only with server identity and the authenticated account's quota.

    conversation_id None admits a run without a conversation (feasibility): it still
    counts against the user's and tenant's concurrency and the daily allowance.
    """
    now = datetime.now(timezone.utc)
    # Transaction locks serialize admission across all workers, without holding a
    # database connection during the model run. Tenant then user is a fixed order.
    await repository.lock_turn_admission(db, user_id, organization_id)
    checks = [
        ("organization_id", organization_id, TENANT_CONCURRENCY),
        ("user_id", user_id, USER_CONCURRENCY),
    ]
    if conversation_id is not None:
        checks.append(("conversation_id", conversation_id, 1))
    for field, value, maximum in checks:
        count = await repository.active_turn_count(db, field, value, now)
        if count >= maximum:
            raise AdmissionRefused("busy")
    usage = await usage_repository.increment(db, user_id, now.date(), 0, 0, 0)
    remaining = daily_limit - usage.total_tokens
    if remaining < settings.ASSISTANT_TURN_MIN_TOKENS:
        raise AdmissionRefused("allowance")
    reserved = min(token_limit or settings.ASSISTANT_TURN_TOKEN_LIMIT, remaining)
    await usage_repository.increment(db, user_id, now.date(), 0, 0, reserved)
    lease = ChatTurnLease(
        user_id=user_id,
        organization_id=organization_id,
        conversation_id=conversation_id or 0,
        budget_day=now.date(),
        reserved_tokens=reserved,
        expires_at=now + timedelta(seconds=LEASE_SECONDS),
    )
    db.add(lease)
    await db.commit()
    return TurnLease(lease.id, reserved)


async def settle(db, lease_id: str, usage: RunUsage, *, successful: bool):
    lease = await repository.locked_turn_lease(db, lease_id)
    if lease is None or lease.status != "active":
        return
    now = datetime.now(timezone.utc)
    # Charge what the provider reported for every completed request, whether the turn
    # succeeded, failed, hit its limit or was cancelled. A request cancelled in flight
    # has no usage report and is not charged.
    charged = usage.total_tokens
    await usage_repository.increment(
        db,
        lease.user_id,
        lease.budget_day,
        usage.input_tokens,
        usage.output_tokens,
        charged - lease.reserved_tokens,
    )
    lease.status = "settled" if successful else "failed"
    lease.finished_at = now
    await db.commit()


async def acquire(
    *,
    user_id: str,
    organization_id: str,
    conversation_id: int | None,
    token_limit: int | None = None,
) -> TurnLease:
    user = await get_user_by_id(user_id)
    if user is None:
        raise HTTPException(403, "Account is unavailable")
    async with asynccontextmanager(get_db_session)() as db:
        return await reserve(
            db,
            user_id=user_id,
            organization_id=organization_id,
            conversation_id=conversation_id,
            daily_limit=user.daily_token_limit,
            token_limit=token_limit,
        )


async def finish(lease_id: str, usage: RunUsage, *, successful: bool):
    # A separate transaction survives an aborted chat transaction or client disconnect.
    async with asynccontextmanager(get_db_session)() as db:
        await settle(db, lease_id, usage, successful=successful)


@asynccontextmanager
async def admitted_run(*, user_id: str, organization_id: str, token_limit: int):
    """Admit one LLM run outside a conversation; yields (usage, token_budget)."""
    lease = await acquire(
        user_id=user_id,
        organization_id=organization_id,
        conversation_id=None,
        token_limit=token_limit,
    )
    usage = RunUsage()
    completed = False
    try:
        yield usage, lease.token_budget
        completed = True
    finally:
        await asyncio.shield(finish(lease.id, usage, successful=completed))
