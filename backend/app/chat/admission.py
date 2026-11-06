"""Durable cross-worker turn admission. Expiry frees capacity, never reserved budget."""

from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from pydantic_ai.usage import RunUsage

from app.auth.service import get_user_by_id
from app.chat import repository
from app.chat.models import ChatTurnLease
from app.postgres import get_db_session
from app.token_usage import repository as usage_repository

RESERVED_TOKENS = 24000
USER_CONCURRENCY = 1
TENANT_CONCURRENCY = 20
LEASE_SECONDS = 600  # Longer than the complete turn's 300-second deadline.
BUSY = "Another assistant turn is running. Please try again shortly."
NO_ALLOWANCE = "Insufficient daily token allowance for another assistant turn."


class AdmissionRefused(HTTPException):
    """429 before anything is reserved; `code` ("busy" or "allowance") lets callers wait."""

    def __init__(self, code: str):
        super().__init__(429, BUSY if code == "busy" else NO_ALLOWANCE)
        self.code = code


async def reserve(db, *, user_id, organization_id, conversation_id, daily_limit):
    """Called only with server identity and the authenticated account's quota."""
    now = datetime.now(timezone.utc)
    # Transaction locks serialize admission across all workers, without holding a
    # database connection during the model run. Tenant then user is a fixed order.
    await repository.lock_turn_admission(db, user_id, organization_id)
    for field, value, maximum in (
        ("organization_id", organization_id, TENANT_CONCURRENCY),
        ("user_id", user_id, USER_CONCURRENCY),
        ("conversation_id", conversation_id, 1),
    ):
        count = await repository.active_turn_count(db, field, value, now)
        if count >= maximum:
            raise AdmissionRefused("busy")
    usage = await usage_repository.increment(db, user_id, now.date(), 0, 0, 0)
    if usage.total_tokens + RESERVED_TOKENS > daily_limit:
        raise AdmissionRefused("allowance")
    await usage_repository.increment(db, user_id, now.date(), 0, 0, RESERVED_TOKENS)
    lease = ChatTurnLease(
        user_id=user_id,
        organization_id=organization_id,
        conversation_id=conversation_id,
        budget_day=now.date(),
        reserved_tokens=RESERVED_TOKENS,
        expires_at=now + timedelta(seconds=LEASE_SECONDS),
    )
    db.add(lease)
    await db.commit()
    return lease.id


async def settle(db, lease_id: str, usage: RunUsage, *, successful: bool):
    lease = await repository.locked_turn_lease(db, lease_id)
    if lease is None or lease.status != "active":
        return
    now = datetime.now(timezone.utc)
    # Timeouts/crashes can consume tokens absent from provider usage reports.
    # Never refund their reservation; observed overruns are charged as well.
    charged = (
        usage.total_tokens
        if successful and now < lease.expires_at
        else max(lease.reserved_tokens, usage.total_tokens)
    )
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


async def acquire(*, user_id: str, organization_id: str, conversation_id: int) -> str:
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
        )


async def finish(lease_id: str, usage: RunUsage, *, successful: bool):
    # A separate transaction survives an aborted chat transaction or client disconnect.
    async with asynccontextmanager(get_db_session)() as db:
        await settle(db, lease_id, usage, successful=successful)
