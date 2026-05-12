from __future__ import annotations

import re
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

    def insert_rows(
        self, *, table: str, rows: Sequence[Sequence[Any]], column_names: Sequence[str]
    ) -> None:
        self._client.insert(table=table, data=list(rows), column_names=list(column_names))

    @staticmethod
    def _staging_name(table: str, staging_suffix: str) -> str:
        safe = re.sub(r"[^0-9A-Za-z_]", "_", staging_suffix)
        return f"{table}_staging_{safe}"

    def replace_table_rows(
        self,
        *,
        table: str,
        rows: Sequence[Sequence[Any]],
        column_names: Sequence[str],
        staging_suffix: str = "replace_rows",
    ) -> int:
        staging = self._staging_name(table, staging_suffix)
        quoted_table = quote_clickhouse_identifier(table)
        quoted_staging = quote_clickhouse_identifier(staging)
        self.command(f"DROP TABLE IF EXISTS {quoted_staging}")
        self.command(f"CREATE TABLE {quoted_staging} AS {quoted_table}")
        try:
            if rows:
                self.insert_rows(table=staging, rows=rows, column_names=column_names)
            self.command(f"EXCHANGE TABLES {quoted_table} AND {quoted_staging}")
        finally:
            self.command(f"DROP TABLE IF EXISTS {quoted_staging}")
        return len(rows)


_CLICKHOUSE_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][0-9A-Za-z_]*$")


def quote_clickhouse_identifier(identifier: str) -> str:
    if not _CLICKHOUSE_IDENTIFIER_RE.fullmatch(identifier):
        raise ValueError(f"Invalid ClickHouse identifier: {identifier!r}")
    return f"`{identifier}`"


def sql_string(value: str) -> str:
    return "'" + value.replace("\\", "\\\\").replace("'", "''") + "'"
