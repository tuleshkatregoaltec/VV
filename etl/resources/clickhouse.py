"""ClickHouse resource with full-swap and append publish patterns."""

from __future__ import annotations

import clickhouse_connect
from dagster import ConfigurableResource, get_dagster_logger


class ClickHouseResource(ConfigurableResource):
    host: str
    port: int = 8443
    user: str = "default"
    password: str = ""
    database: str = "default"
    secure: bool = True

    def _client(self):
        return clickhouse_connect.get_client(
            host=self.host,
            port=self.port,
            username=self.user,
            password=self.password,
            database=self.database,
            secure=self.secure,
        )

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
    ) -> int:
        """Create staging table, load from S3, validate row count, return count."""
        log = get_dagster_logger()
        log.info(f"Creating staging table {staging}")
        client.command(f"DROP TABLE IF EXISTS {staging}")
        client.command(f"CREATE TABLE {staging} AS {table}")
        log.info(f"Loading {staging} from {s3_url}")
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
    ) -> int:
        """
        Atomic load: create staging, insert from S3, validate, EXCHANGE, drop staging.
        Returns the number of rows loaded.
        """
        log = get_dagster_logger()
        staging = self._staging_name(table, staging_suffix)
        client = self._client()
        count = self._load_into_staging(
            client, table, staging, s3_url, aws_access_key_id, aws_secret_access_key, format
        )
        log.info(f"Exchanging {table} ↔ {staging} ({count:,} rows)")
        client.command(f"EXCHANGE TABLES {table} AND {staging}")
        client.command(f"DROP TABLE IF EXISTS {staging}")
        log.info(f"Loaded {count:,} rows into {table}")
        return count

    def append_table_from_s3(
        self,
        table: str,
        s3_url: str,
        aws_access_key_id: str,
        aws_secret_access_key: str,
        format: str = "CSVWithNames",
        staging_suffix: str = "append",
    ) -> int:
        log = get_dagster_logger()
        staging = self._staging_name(table, staging_suffix)
        client = self._client()
        count = self._load_into_staging(
            client, table, staging, s3_url, aws_access_key_id, aws_secret_access_key, format
        )
        log.info(f"Appending {count:,} rows from {staging} into {table}")
        try:
            client.command(f"INSERT INTO {table} SELECT * FROM {staging}")
        finally:
            client.command(f"DROP TABLE IF EXISTS {staging}")
        return count

    def query_scalar(self, sql: str) -> int | float | str:
        row = self._client().query(sql).first_row
        return row[0]

    def command(self, sql: str) -> None:
        self._client().command(sql)
