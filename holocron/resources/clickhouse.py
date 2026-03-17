"""ClickHouse resource with full-swap and append publish patterns."""

from __future__ import annotations

import clickhouse_connect
from dagster import ConfigurableResource, get_dagster_logger
from pydantic import PrivateAttr


class ClickHouseResource(ConfigurableResource):
    host: str
    port: int = 8443
    user: str = "default"
    password: str = ""
    database: str = "default"
    secure: bool = True

    _client_instance: object = PrivateAttr(default=None)

    def _client(self):
        if self._client_instance is None:
            self._client_instance = clickhouse_connect.get_client(
                host=self.host,
                port=self.port,
                username=self.user,
                password=self.password,
                database=self.database,
                secure=self.secure,
            )
        return self._client_instance

    @staticmethod
    def _staging_name(table: str, staging_suffix: str) -> str:
        safe = "".join(ch if ch.isalnum() else "_" for ch in staging_suffix)
        return f"{table}_staging_{safe}"

    def _load_into_staging(
        self,
        client,
        table: str,
        staging: str,
        s3_url: str,
        aws_access_key_id: str,
        aws_secret_access_key: str,
        format: str,
        *,
        allow_empty: bool = False,
    ) -> int:
        log = get_dagster_logger()
        log.info(f"Creating staging table {staging}")
        client.command(f"DROP TABLE IF EXISTS {staging}")
        client.command(f"CREATE TABLE {staging} AS {table}")
        client.command(
            f"""
            INSERT INTO {staging}
            SELECT * FROM s3(
                '{s3_url}',
                '{aws_access_key_id}',
                '{aws_secret_access_key}',
                '{format}'
            )
            """
        )
        count = int(client.query(f"SELECT count() FROM {staging}").first_row[0])
        if count == 0:
            if not allow_empty:
                client.command(f"DROP TABLE IF EXISTS {staging}")
                raise ValueError(f"Staging table {staging} loaded 0 rows from {s3_url}")
        return count

    def load_table_from_s3(
        self,
        table: str,
        s3_url: str,
        aws_access_key_id: str,
        aws_secret_access_key: str,
        format: str = "CSVWithNames",
        staging_suffix: str = "publish",
        allow_empty: bool = False,
    ) -> int:
        log = get_dagster_logger()
        staging = self._staging_name(table, staging_suffix)
        client = self._client()
        count = self._load_into_staging(
            client,
            table,
            staging,
            s3_url,
            aws_access_key_id,
            aws_secret_access_key,
            format,
            allow_empty=allow_empty,
        )
        log.info(f"Exchanging {table} with {staging} ({count:,} rows)")
        client.command(f"EXCHANGE TABLES {table} AND {staging}")
        client.command(f"DROP TABLE IF EXISTS {staging}")
        return count

    def append_table_from_s3(
        self,
        table: str,
        s3_url: str,
        aws_access_key_id: str,
        aws_secret_access_key: str,
        format: str = "CSVWithNames",
        staging_suffix: str = "append",
        allow_empty: bool = False,
    ) -> int:
        staging = self._staging_name(table, staging_suffix)
        client = self._client()
        count = self._load_into_staging(
            client,
            table,
            staging,
            s3_url,
            aws_access_key_id,
            aws_secret_access_key,
            format,
            allow_empty=allow_empty,
        )
        if count == 0:
            client.command(f"DROP TABLE IF EXISTS {staging}")
            return 0
        try:
            client.command(f"INSERT INTO {table} SELECT * FROM {staging}")
        finally:
            client.command(f"DROP TABLE IF EXISTS {staging}")
        return count

    def query_scalar(self, sql: str):
        return self._client().query(sql).first_row[0]

    def command(self, sql: str) -> None:
        self._client().command(sql)

    def query_rows(self, sql: str) -> tuple[list[str], list[tuple]]:
        result = self._client().query(sql)
        return list(result.column_names), list(result.result_rows)

    def replace_table_rows(
        self,
        *,
        table: str,
        rows: list[tuple],
        column_names: list[str],
        staging_suffix: str = "replace_rows",
    ) -> int:
        staging = self._staging_name(table, staging_suffix)
        client = self._client()
        client.command(f"DROP TABLE IF EXISTS {staging}")
        client.command(f"CREATE TABLE {staging} AS {table}")
        if rows:
            client.insert(staging, rows, column_names=column_names)
        client.command(f"EXCHANGE TABLES {table} AND {staging}")
        client.command(f"DROP TABLE IF EXISTS {staging}")
        return len(rows)
