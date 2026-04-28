from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import clickhouse_connect

from holocron.platform.settings import Settings


class ClickHouseClient:
    def __init__(self, settings: Settings) -> None:
        self._client = clickhouse_connect.get_client(
            host=settings.clickhouse_host,
            port=settings.clickhouse_port,
            username=settings.clickhouse_user,
            password=settings.clickhouse_password,
            database=settings.clickhouse_database,
            secure=settings.clickhouse_secure,
        )

    def command(self, sql: str) -> Any:
        return self._client.command(sql)

    def query(self, sql: str) -> Any:
        return self._client.query(sql)

    def insert_rows(self, *, table: str, rows: Sequence[Sequence[Any]], column_names: Sequence[str]) -> None:
        self._client.insert(table=table, data=list(rows), column_names=list(column_names))
