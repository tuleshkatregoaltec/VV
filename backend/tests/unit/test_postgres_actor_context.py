"""Actor transport must preserve lazy sessions and refresh auth-opened transactions."""

from unittest.mock import AsyncMock, Mock

import pytest

from app.postgres.actor_context import apply_actor_context, transaction_actor


async def test_applying_actor_to_lazy_session_does_not_open_database_connection():
    session = Mock(in_transaction=Mock(return_value=False), execute=AsyncMock())
    with transaction_actor(actor_id="user", organization_id="org", request_id="server-request"):
        await apply_actor_context(session)
    session.execute.assert_not_awaited()


async def test_existing_auth_transaction_uses_current_trusted_context_without_commit():
    session = Mock(in_transaction=Mock(return_value=True), execute=AsyncMock())
    with transaction_actor(actor_id="user", organization_id="org", request_id="server-request"):
        await apply_actor_context(session)
    statement, parameters = session.execute.await_args.args
    assert "set_config" in str(statement)
    assert parameters == {"actor": "user", "organization": "org", "request": "server-request"}
    session.commit.assert_not_called()
    session.rollback.assert_not_called()
    # An explicit application outside user context must clear any prior user settings.
    await apply_actor_context(session)
    assert session.execute.await_args.args[1] == {"actor": "", "organization": "", "request": ""}


@pytest.mark.parametrize("field", ["actor_id", "organization_id", "request_id"])
def test_actor_context_rejects_missing_or_unbounded_identifiers(field):
    for invalid in ("", "x" * 256):
        values = {"actor_id": "user", "organization_id": "org", "request_id": "server-request"}
        with pytest.raises(ValueError, match="bounded identifiers"):
            with transaction_actor(**{**values, field: invalid}):
                pytest.fail("Invalid actor context must not be entered")
