"""Real ClickHouse execution against a database owned by this test only."""

from uuid import uuid4

import clickhouse_connect
import pytest

from app.clickhouse import client
from app.config import settings


@pytest.fixture
async def warehouse(monkeypatch):
    if settings.CLICKHOUSE_HOST not in {"localhost", "127.0.0.1", "::1"}:
        pytest.fail("ClickHouse integration requires a local service")
    options = {
        "host": settings.CLICKHOUSE_HOST,
        "port": settings.CLICKHOUSE_PORT,
        "username": settings.CLICKHOUSE_USER,
        "password": settings.CLICKHOUSE_PASSWORD,
        "secure": settings.CLICKHOUSE_SECURE,
    }
    admin = await clickhouse_connect.get_async_client(**options)
    database = "vv_migration_test_" + uuid4().hex
    await admin.command(f"CREATE DATABASE {database}")
    isolated = await clickhouse_connect.get_async_client(**options, database=database)
    monkeypatch.setattr(client, "_client", isolated)
    try:
        yield isolated
    finally:
        await isolated.close()
        await admin.command(f"DROP DATABASE {database} SYNC")
        await admin.close()
