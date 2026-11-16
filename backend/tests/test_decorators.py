import inspect
from unittest.mock import AsyncMock

from fastapi import Depends

from app.core.decorators import _build_cache_key, cached_endpoint


async def _require_context():
    return {"user_id": "ignored"}


async def _get_db():
    return object()


async def test_cached_endpoint_returns_falsey_cached_payload(monkeypatch):
    get_mock = AsyncMock(return_value=[])
    set_mock = AsyncMock()
    monkeypatch.setattr("app.core.decorators.cache.get", get_mock)
    monkeypatch.setattr("app.core.decorators.cache.set", set_mock)

    called = False

    @cached_endpoint(prefix="projects")
    async def endpoint(limit: int = 20):
        nonlocal called
        called = True
        return ["fresh"]

    result = await endpoint(limit=20)

    assert result == []
    assert called is False
    set_mock.assert_not_called()


async def test_cached_endpoint_excludes_dependency_params_from_cache_key(monkeypatch):
    get_mock = AsyncMock(return_value=None)
    set_mock = AsyncMock()
    monkeypatch.setattr("app.core.decorators.cache.get", get_mock)
    monkeypatch.setattr("app.core.decorators.cache.set", set_mock)

    @cached_endpoint(prefix="news")
    async def endpoint(
        context=Depends(_require_context),
        limit: int = 20,
        offset: int = 0,
        db=Depends(_get_db),
    ):
        return {"articles": [], "total": 0, "limit": limit, "offset": offset}

    db = object()
    context = {"org_id": 1}
    result = await endpoint(context=context, limit=20, offset=5, db=db)

    assert result["offset"] == 5
    get_mock.assert_awaited_once_with('news:{"limit":20,"offset":5}')
    set_mock.assert_awaited_once()


def test_build_cache_key_ignores_dependencies():
    async def endpoint(
        context=Depends(_require_context),
        limit: int = 20,
        offset: int = 0,
        db=Depends(_get_db),
    ):
        return None

    key = _build_cache_key(
        "news",
        inspect.signature(endpoint),
        context={"ignored": True},
        limit=20,
        offset=10,
        db=object(),
    )

    assert key == 'news:{"limit":20,"offset":10}'


# Single flight: a cold key used to send every concurrent request to the warehouse (the
# Transactions page alone costs 3-4 GiB of ClickHouse memory per cold load; 2026-11-15 audit).


def _no_cache(monkeypatch, *, lock="token"):
    monkeypatch.setattr("app.core.decorators.cache.get", AsyncMock(return_value=None))
    monkeypatch.setattr("app.core.decorators.cache.set", AsyncMock())
    monkeypatch.setattr("app.core.decorators.cache.acquire_lock", AsyncMock(return_value=lock))
    monkeypatch.setattr("app.core.decorators.cache.release_lock", AsyncMock())


async def test_concurrent_misses_for_one_key_compute_once(monkeypatch):
    import asyncio

    _no_cache(monkeypatch)
    calls = 0

    @cached_endpoint(prefix="flight")
    async def endpoint(limit: int = 20):
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.05)
        return {"limit": limit}

    results = await asyncio.gather(*(endpoint(limit=5) for _ in range(5)))

    assert calls == 1
    assert results == [{"limit": 5}] * 5


async def test_concurrent_misses_for_different_keys_compute_each(monkeypatch):
    import asyncio

    _no_cache(monkeypatch)
    calls = []

    @cached_endpoint(prefix="flight")
    async def endpoint(limit: int = 20):
        calls.append(limit)
        await asyncio.sleep(0.01)
        return limit

    assert await asyncio.gather(endpoint(limit=1), endpoint(limit=2)) == [1, 2]
    assert sorted(calls) == [1, 2]


async def test_a_failed_fill_reaches_every_waiter_and_the_next_call_retries(monkeypatch):
    import asyncio

    _no_cache(monkeypatch)
    calls = 0

    @cached_endpoint(prefix="flight")
    async def endpoint(limit: int = 20):
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.01)
        if calls == 1:
            raise RuntimeError("warehouse down")
        return "ok"

    results = await asyncio.gather(*(endpoint() for _ in range(3)), return_exceptions=True)

    assert calls == 1
    assert all(isinstance(result, RuntimeError) for result in results)
    assert await endpoint() == "ok"
    assert calls == 2


async def test_a_waiter_that_goes_away_does_not_cancel_the_fill(monkeypatch):
    import asyncio

    _no_cache(monkeypatch)
    finished = asyncio.Event()

    @cached_endpoint(prefix="flight")
    async def endpoint(limit: int = 20):
        await asyncio.sleep(0.05)
        finished.set()
        return "ok"

    first = asyncio.ensure_future(endpoint())
    await asyncio.sleep(0.01)
    first.cancel()
    assert await endpoint() == "ok"
    assert finished.is_set()


async def test_another_worker_filling_the_key_is_awaited_through_the_cache(monkeypatch):
    monkeypatch.setattr(
        "app.core.decorators.cache.get", AsyncMock(side_effect=[None, None, {"from": "peer"}])
    )
    monkeypatch.setattr("app.core.decorators.cache.set", AsyncMock())
    monkeypatch.setattr("app.core.decorators.cache.acquire_lock", AsyncMock(return_value=None))
    monkeypatch.setattr("app.core.decorators.cache.release_lock", AsyncMock())
    monkeypatch.setattr("app.core.decorators.LOCK_POLL_SECONDS", 0.001)
    called = False

    @cached_endpoint(prefix="flight")
    async def endpoint(limit: int = 20):
        nonlocal called
        called = True
        return "mine"

    assert await endpoint() == {"from": "peer"}
    assert called is False


async def test_the_fill_lock_is_released_after_the_fill(monkeypatch):
    _no_cache(monkeypatch, lock="abc")

    @cached_endpoint(prefix="flight")
    async def endpoint(limit: int = 20):
        return "ok"

    await endpoint()

    from app.core import decorators

    decorators.cache.release_lock.assert_awaited_once_with('flight:{"limit":20}', "abc")


# A relative window ("last 90 days") must not outlive the Dubai day it was computed on.
def _dubai(year, month, day, hour, minute=0):
    from datetime import datetime

    from app.market.periods import BUSINESS_TIMEZONE

    return datetime(year, month, day, hour, minute, tzinfo=BUSINESS_TIMEZONE)


def _freeze_dubai(monkeypatch, moment):
    from app.market.periods import business_today

    monkeypatch.setattr("app.core.decorators.business_today", lambda: business_today(moment))


async def test_daily_endpoint_key_changes_at_dubai_midnight(monkeypatch):
    seen = []

    async def get(key):
        seen.append(key)
        return None

    monkeypatch.setattr("app.core.decorators.cache.get", get)
    monkeypatch.setattr("app.core.decorators.cache.set", AsyncMock())
    monkeypatch.setattr("app.core.decorators.cache.acquire_lock", AsyncMock(return_value="t"))
    monkeypatch.setattr("app.core.decorators.cache.release_lock", AsyncMock())

    @cached_endpoint(prefix="window", daily=True)
    async def endpoint(timeframe_days: int = 90):
        return {"days": timeframe_days}

    _freeze_dubai(monkeypatch, _dubai(2026, 11, 16, 23, 59))
    await endpoint(timeframe_days=90)
    _freeze_dubai(monkeypatch, _dubai(2026, 11, 17, 0, 1))
    await endpoint(timeframe_days=90)
    await endpoint(timeframe_days=90)

    assert seen[0] != seen[1]
    assert seen[1] == seen[2]
    assert "2026-11-16" in seen[0] and "2026-11-17" in seen[1]
    assert seen[0].startswith("window:")


async def test_dateless_endpoint_key_is_unchanged_by_midnight(monkeypatch):
    seen = []

    async def get(key):
        seen.append(key)
        return None

    monkeypatch.setattr("app.core.decorators.cache.get", get)
    monkeypatch.setattr("app.core.decorators.cache.set", AsyncMock())
    monkeypatch.setattr("app.core.decorators.cache.acquire_lock", AsyncMock(return_value="t"))
    monkeypatch.setattr("app.core.decorators.cache.release_lock", AsyncMock())

    @cached_endpoint(prefix="static")
    async def endpoint(limit: int = 20):
        return {"limit": limit}

    _freeze_dubai(monkeypatch, _dubai(2026, 11, 16, 23, 59))
    await endpoint(limit=5)
    _freeze_dubai(monkeypatch, _dubai(2026, 11, 17, 0, 1))
    await endpoint(limit=5)

    assert seen[0] == seen[1] == 'static:{"limit":5}'


async def test_daily_endpoint_keeps_single_flight(monkeypatch):
    import asyncio

    _no_cache(monkeypatch)
    _freeze_dubai(monkeypatch, _dubai(2026, 11, 16, 12))
    calls = 0

    @cached_endpoint(prefix="window", daily=True)
    async def endpoint(timeframe_days: int = 90):
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.05)
        return {"days": timeframe_days}

    results = await asyncio.gather(*(endpoint(timeframe_days=7) for _ in range(5)))

    assert calls == 1
    assert results == [{"days": 7}] * 5
