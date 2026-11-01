"""Request/worker identity propagated to every PostgreSQL transaction.

Entry adapters set identity in the task that executes database work. Infrastructure
only transports trusted metadata; domain migrations decide how it is enforced.
"""

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Iterator

from sqlalchemy import Connection, event, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession


@dataclass(frozen=True)
class TransactionActor:
    actor_id: str
    organization_id: str
    request_id: str


_actor: ContextVar[TransactionActor | None] = ContextVar("postgres_transaction_actor", default=None)


@contextmanager
def transaction_actor(*, actor_id: str, organization_id: str, request_id: str) -> Iterator[None]:
    """Attribute new transactions, including transactions after a service commit.

    Enter before database work, or apply_actor_context to an existing transaction.
    Never supply customer text, client headers, paths or URLs as request_id.
    """
    values = (actor_id, organization_id, request_id)
    if any(not value or len(value) > 255 for value in values):
        raise ValueError("Transaction actor metadata must contain bounded identifiers")
    token = _actor.set(TransactionActor(*values))
    try:
        yield
    finally:
        _actor.reset(token)


_ACTOR_SETTINGS = text(
    "SELECT set_config('app.actor_id', :actor, true), "
    "set_config('app.organization_id', :organization, true), "
    "set_config('app.request_id', :request, true)"
)


def _actor_parameters() -> dict[str, str]:
    actor = _actor.get()
    return {
        "actor": actor.actor_id if actor else "",
        "organization": actor.organization_id if actor else "",
        "request": actor.request_id if actor else "",
    }


def _set_transaction_actor(connection: Connection) -> None:
    connection.execute(_ACTOR_SETTINGS, _actor_parameters())


async def apply_actor_context(session: AsyncSession) -> None:
    """Apply trusted context to a transaction already opened by entry-adapter reads.

    Call inside transaction_actor after authentication and before domain operations.
    A session with no transaction stays lazy: its engine begin hook applies context
    when the first database operation starts. Never commit authentication reads here.
    """
    if session.in_transaction():
        await session.execute(_ACTOR_SETTINGS, _actor_parameters())


def install_actor_context(engine: AsyncEngine) -> None:
    """Install once per PostgreSQL engine; also clears identity on reused pools."""
    if engine.dialect.name == "postgresql" and not event.contains(
        engine.sync_engine, "begin", _set_transaction_actor
    ):
        event.listen(engine.sync_engine, "begin", _set_transaction_actor)
