"""The Transactions lists cache a relative window per Dubai day."""

from datetime import datetime
from unittest.mock import AsyncMock

import pytest

from app.market.periods import BUSINESS_TIMEZONE, business_today
from app.transaction import router
from app.transaction.models import RentalFilters, SalesFilters


@pytest.fixture
def cache_spy(monkeypatch):
    get_mock = AsyncMock(return_value=None)
    monkeypatch.setattr("app.core.decorators.cache.get", get_mock)
    monkeypatch.setattr("app.core.decorators.cache.set", AsyncMock())
    monkeypatch.setattr("app.core.decorators.cache.acquire_lock", AsyncMock(return_value="t"))
    monkeypatch.setattr("app.core.decorators.cache.release_lock", AsyncMock())
    return get_mock


@pytest.mark.parametrize(
    "endpoint,fetch,filters",
    [
        ("get_sales_transactions", "fetch_sales_transactions", SalesFilters(timeframe_days=90)),
        ("get_rental_contracts", "fetch_rental_contracts", RentalFilters(timeframe_days=90)),
    ],
)
async def test_transactions_list_key_changes_after_dubai_midnight(
    monkeypatch, cache_spy, endpoint, fetch, filters
):
    monkeypatch.setattr(router, fetch, AsyncMock(return_value={"ok": True}))
    keys = []
    for moment in (
        datetime(2026, 11, 16, 23, 59, tzinfo=BUSINESS_TIMEZONE),
        datetime(2026, 11, 17, 0, 1, tzinfo=BUSINESS_TIMEZONE),
    ):
        monkeypatch.setattr(
            "app.core.decorators.business_today", lambda m=moment: business_today(m)
        )
        cache_spy.reset_mock()
        await getattr(router, endpoint)(context=object(), limit=50, offset=0, filters=filters)
        keys.append(cache_spy.await_args_list[0].args[0])
    assert keys[0] != keys[1]
