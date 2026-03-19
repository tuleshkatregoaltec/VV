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

    @staticmethod
    def _key_expr(columns: tuple[str, ...], alias: str = "") -> str:
        qualified = [f"{alias}{column}" for column in columns]
        if len(qualified) == 1:
            return qualified[0]
        return f"tuple({', '.join(qualified)})"

    @staticmethod
    def _deduped_select_sql(
        *,
        table: str,
        staging: str,
        key_columns: tuple[str, ...],
        table_columns: list[str],
    ) -> str:
        missing = [column for column in key_columns if column not in table_columns]
        if missing:
            missing_str = ", ".join(missing)
            raise ValueError(f"Missing dedupe columns for {table}: {missing_str}")

        deduped_columns = []
        for column in table_columns:
            if column in key_columns:
                deduped_columns.append(column)
            else:
                deduped_columns.append(f"any({column}) AS {column}")

        inner_sql = (
            f"SELECT {', '.join(deduped_columns)} FROM {staging} GROUP BY {', '.join(key_columns)}"
        )
        return (
            f"SELECT {', '.join(table_columns)} "
            f"FROM ({inner_sql}) AS incoming "
            f"WHERE {ClickHouseResource._key_expr(key_columns, 'incoming.')} "
            f"NOT IN (SELECT {ClickHouseResource._key_expr(key_columns)} FROM {table})"
        )

    def _table_columns(self, client, table: str) -> list[str]:
        result = client.query(f"DESCRIBE TABLE {table}")
        return [str(row[0]) for row in result.result_rows]

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
        dedupe_key: tuple[str, ...] = (),
    ) -> int:
        staging = self._staging_name(table, staging_suffix)
        client = self._client()
        loaded_count = self._load_into_staging(
            client,
            table,
            staging,
            s3_url,
            aws_access_key_id,
            aws_secret_access_key,
            format,
            allow_empty=allow_empty,
        )
        if loaded_count == 0:
            client.command(f"DROP TABLE IF EXISTS {staging}")
            return 0
        try:
            if dedupe_key:
                table_columns = self._table_columns(client, table)
                select_sql = self._deduped_select_sql(
                    table=table,
                    staging=staging,
                    key_columns=dedupe_key,
                    table_columns=table_columns,
                )
                inserted_count = int(
                    client.query(f"SELECT count() FROM ({select_sql})").first_row[0]
                )
                if inserted_count > 0:
                    client.command(f"INSERT INTO {table} {select_sql}")
                return inserted_count

            client.command(f"INSERT INTO {table} SELECT * FROM {staging}")
        finally:
            client.command(f"DROP TABLE IF EXISTS {staging}")
        return loaded_count

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
