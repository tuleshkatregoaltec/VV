from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.chat import operations


@pytest.fixture
def quota(monkeypatch):
    async def session():
        yield object()

    monkeypatch.setattr(operations, "get_db_session", session)
    access = AsyncMock(return_value=True)
    acquire = AsyncMock(return_value="lease")
    finish = AsyncMock()
    monkeypatch.setattr(operations, "channel_access", access)
    monkeypatch.setattr(operations.admission, "acquire", acquire)
    monkeypatch.setattr(operations.admission, "finish", finish)
    return SimpleNamespace(access=access, acquire=acquire, finish=finish)


async def test_customer_models_share_existing_durable_quota(quota):
    async with operations.channel_budget(
        user_id="u", organization_id="o", conversation_id=1
    ) as usage:
        usage.input_tokens = 100
    quota.acquire.assert_awaited_once_with(user_id="u", organization_id="o", conversation_id=1)
    assert quota.finish.call_args.kwargs == {"successful": True}
    assert quota.finish.call_args.args[1].input_tokens == 100


async def test_revoked_customer_connection_cannot_reserve_model_budget(quota):
    quota.access.return_value = False
    with pytest.raises(PermissionError):
        async with operations.channel_budget(user_id="u", organization_id="o", conversation_id=1):
            pytest.fail("Must not enter model budget")
    quota.acquire.assert_not_called()


async def test_failed_customer_model_keeps_reservation_charge(quota):
    with pytest.raises(RuntimeError):
        async with operations.channel_budget(user_id="u", organization_id="o", conversation_id=1):
            raise RuntimeError("provider failed")
    assert quota.finish.call_args.kwargs == {"successful": False}
