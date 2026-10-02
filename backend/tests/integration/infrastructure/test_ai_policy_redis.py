"""Real Lua admission against unique disposable keys; never flush shared Redis."""

import asyncio
from decimal import Decimal
from uuid import uuid4

import pytest

from app.core import ai_policy as policy


@pytest.fixture
async def ledger(monkeypatch):
    prefix = "vv_ai_policy_test:" + uuid4().hex + ":"
    monkeypatch.setattr(policy, "LEDGER_PREFIX", prefix)
    monkeypatch.setattr(policy.settings, "AI_PRICING_MODEL", policy.settings.DEFAULT_CHAT_MODEL)
    for name in (
        "AI_USER_DAILY_USD",
        "AI_USER_MONTHLY_USD",
        "AI_ORG_DAILY_USD",
        "AI_ORG_MONTHLY_USD",
    ):
        monkeypatch.setattr(policy.settings, name, Decimal("5"))
    monkeypatch.setattr(policy.settings, "AI_INPUT_USD_PER_MILLION", Decimal("0.5"))
    monkeypatch.setattr(policy.settings, "AI_OUTPUT_USD_PER_MILLION", Decimal("3"))
    connection = policy.client()
    assert await connection.ping()
    try:
        yield connection
    finally:
        keys = [key async for key in connection.scan_iter(match=prefix + "*")]
        if keys:
            await connection.delete(*keys)
        await connection.aclose()


def scope(user="user", organization="org"):
    return policy.ai_execution(
        user_id=user,
        organization_id=organization,
        execution_id=uuid4().hex,
        daily_token_limit=500000,
    )


async def test_atomic_admission_limits_parallel_calls_and_cleans_leases(ledger):
    admitted = []
    release = asyncio.Event()

    async def enter():
        async with scope():
            try:
                async with policy.provider_reservation(
                    policy.settings.DEFAULT_CHAT_MODEL, "hello", output_tokens=100
                ) as reservation:
                    admitted.append(reservation)
                    await release.wait()
            except policy.AIPolicyError as exc:
                assert "concurrency" in str(exc)

    tasks = [asyncio.create_task(enter()) for _ in range(10)]
    for _ in range(100):
        if (
            len(admitted) == policy.settings.AI_USER_CONCURRENCY
            and sum(t.done() for t in tasks) == 8
        ):
            break
        await asyncio.sleep(0.01)
    release.set()
    await asyncio.gather(*tasks)
    assert len(admitted) == 2
    assert await ledger.zcard(admitted[0].keys[6]) == 0
    assert await ledger.zcard(admitted[0].keys[7]) == 0
    assert int(await ledger.get(admitted[0].keys[1])) == sum(r.reserved_cost for r in admitted)


async def test_actual_settlement_is_idempotent_and_unknown_usage_keeps_charge(ledger):
    async with scope():
        async with policy.provider_reservation(
            policy.settings.DEFAULT_CHAT_MODEL, "hello", output_tokens=100
        ) as reservation:
            reservation.reconcile(20, 10)
            await reservation.finish()
            await reservation.finish()
    assert int(await ledger.get(reservation.keys[1])) == 40
    assert int(await ledger.get(reservation.keys[5])) == 30
    assert await ledger.hget(reservation.keys[0], "status") == "settled"
    from datetime import datetime, timezone

    today = datetime.now(timezone.utc).date()
    assert await policy.reserved_token_records(today) == {"user": 30}
    assert await policy.reserved_token_records(today, ["other"]) == {"other": 0}
    with pytest.raises(asyncio.CancelledError):
        async with scope():
            async with policy.provider_reservation(
                policy.settings.DEFAULT_CHAT_MODEL, "hello", output_tokens=100
            ) as cancelled:
                raise asyncio.CancelledError
    assert int(await ledger.get(cancelled.keys[1])) == 40 + cancelled.reserved_cost
    assert await ledger.hget(cancelled.keys[0], "status") == "unknown"
    assert await ledger.zcard(cancelled.keys[6]) == 0


async def test_org_spend_is_shared_across_users_and_rejection_is_atomic(ledger, monkeypatch):
    monkeypatch.setattr(policy.settings, "AI_ORG_DAILY_USD", Decimal("0.0025"))
    async with scope("one"):
        async with policy.provider_reservation(
            policy.settings.DEFAULT_CHAT_MODEL, "hello", output_tokens=100
        ) as first:
            pass
    async with scope("two"):
        with pytest.raises(policy.AIPolicyError, match="budget"):
            async with policy.provider_reservation(
                policy.settings.DEFAULT_CHAT_MODEL, "hello", output_tokens=100
            ):
                pytest.fail("No provider work may start above tenant budget")
    assert int(await ledger.get(first.keys[3])) == first.reserved_cost
    requests = [key async for key in ledger.scan_iter(match=policy.LEDGER_PREFIX + "request:*")]
    assert len(requests) == 1


async def test_rate_and_identity_are_independent_of_execution_uuid(ledger, monkeypatch):
    monkeypatch.setattr(policy.settings, "AI_REQUESTS_PER_MINUTE", 1)
    for org in ["one", "two"]:
        async with policy.ai_execution(
            user_id=org,
            organization_id=org,
            execution_id="same-request-id",
            daily_token_limit=500000,
        ):
            async with policy.provider_reservation(
                policy.settings.DEFAULT_CHAT_MODEL, "hello", output_tokens=100
            ):
                pass
    async with scope("one", "one"):
        with pytest.raises(policy.AIPolicyError, match="rate"):
            async with policy.provider_reservation(
                policy.settings.DEFAULT_CHAT_MODEL, "hello", output_tokens=100
            ):
                pytest.fail("Rate limit must cover separate executions")
