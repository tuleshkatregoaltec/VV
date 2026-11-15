"""The repeat-cost Analytics endpoints are cached on every query parameter, not on the caller."""

from datetime import date, timedelta
from unittest.mock import AsyncMock

import pytest

from app.analytics import router


@pytest.fixture
def cache_spy(monkeypatch):
    get_mock = AsyncMock(return_value=None)
    monkeypatch.setattr("app.core.decorators.cache.get", get_mock)
    monkeypatch.setattr("app.core.decorators.cache.set", AsyncMock())
    monkeypatch.setattr("app.core.decorators.cache.acquire_lock", AsyncMock(return_value="t"))
    monkeypatch.setattr("app.core.decorators.cache.release_lock", AsyncMock())
    return get_mock


def _key(spy) -> str:
    return spy.await_args_list[0].args[0]


SALES = dict(
    market_type="residential_units",
    property_usage="Residential",
    timeframe_days=90,
    start_date=date(2025, 1, 1),
    end_date=date(2025, 6, 1),
    master_project="Marina",
    property_type="Unit",
    rooms="2 B/R",
    reg_type="Off-Plan",
    price_bucket="1M-2M",
    area_bucket="1K-2K",
)
RENTALS = dict(
    property_usage="Commercial",
    timeframe_days=90,
    start_date=date(2025, 1, 1),
    end_date=date(2025, 6, 1),
    master_project="Marina",
    property_type="Unit",
    rent_bucket="100K-200K",
    area_bucket="1K-2K",
)
TREND = dict(days=365, market_type="residential_units", property_usage="Commercial")
PROJECT = dict(
    master_project="Marina",
    project="Marina Gate",
    building_id="b1",
    filter_type="project",
)

CASES = [
    ("get_sales_analytics", "get_sales_analytics", "analytics:sales:v1", SALES),
    ("get_rental_analytics", "get_rental_analytics", "analytics:rentals:v1", RENTALS),
    ("get_market_trend", "get_market_trend", "analytics:market_trend:v1", TREND),
    (
        "get_project_forecast_endpoint",
        "get_project_forecast",
        "analytics:dxbi:forecast:v1",
        {**PROJECT, "days": 365},
    ),
    (
        "get_project_pipeline_endpoint",
        "get_project_pipeline",
        "analytics:dxbi:pipeline:v1",
        PROJECT,
    ),
]


@pytest.fixture(autouse=True)
def stub_scope(monkeypatch):
    monkeypatch.setattr(router, "_resolve_project_scope", lambda **kw: ("P", kw["filter_type"]))


def _stub_service(monkeypatch, endpoint, service_fn, service):
    # The service functions are reached as analytics_service.X, or imported into the router by name
    # (never replacing the endpoint itself, which can share the service function's name).
    if hasattr(router.analytics_service, service_fn):
        monkeypatch.setattr(router.analytics_service, service_fn, service)
    if service_fn != endpoint and hasattr(router, service_fn):
        monkeypatch.setattr(router, service_fn, service)


@pytest.mark.parametrize("endpoint,service_fn,prefix,params", CASES)
async def test_endpoint_is_cached_under_analytics_prefix(
    monkeypatch, cache_spy, endpoint, service_fn, prefix, params
):
    service = AsyncMock(return_value={"ok": True})
    _stub_service(monkeypatch, endpoint, service_fn, service)
    result = await getattr(router, endpoint)(context=object(), **params)
    assert result == {"ok": True}
    assert _key(cache_spy).startswith(prefix + ":")
    assert prefix.startswith("analytics:")
    service.assert_awaited_once()


@pytest.mark.parametrize("endpoint,service_fn,prefix,params", CASES)
async def test_every_query_parameter_changes_the_cache_key(
    monkeypatch, cache_spy, endpoint, service_fn, prefix, params
):
    service = AsyncMock(return_value={"ok": True})
    _stub_service(monkeypatch, endpoint, service_fn, service)
    fn = getattr(router, endpoint)

    await fn(context=object(), **params)
    baseline = _key(cache_spy)
    # The caller is not part of the key: market data is global.
    cache_spy.reset_mock()
    await fn(context="someone-else", **params)
    assert _key(cache_spy) == baseline

    for name, value in params.items():
        changed = dict(params)
        if isinstance(value, int):
            changed[name] = value + 1
        elif isinstance(value, date):
            changed[name] = value + timedelta(days=1)
        elif name == "filter_type":
            changed[name] = "master"
        else:
            changed[name] = f"{value}-other"
        cache_spy.reset_mock()
        await fn(context=object(), **changed)
        assert _key(cache_spy) != baseline, f"{name} is not in the cache key"
