"""ClickHouse resource with staging + EXCHANGE TABLES load pattern."""

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

    def load_table_from_s3(
        self,
        table: str,
        s3_url: str,
        aws_access_key_id: str,
        aws_secret_access_key: str,
        format: str = "CSVWithNames",
    ) -> int:
        """
        Atomic load: create staging, insert from S3, validate, EXCHANGE, drop staging.
        Returns the number of rows loaded.
        """
        log = get_dagster_logger()
        staging = f"{table}_staging"
        client = self._client()

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

        row = client.query(f"SELECT count() FROM {staging}").first_row
        count = int(row[0])
        if count == 0:
            client.command(f"DROP TABLE IF EXISTS {staging}")
            raise ValueError(f"Staging table {staging} loaded 0 rows from {s3_url}")

        log.info(f"Exchanging {table} ↔ {staging} ({count:,} rows)")
        client.command(f"EXCHANGE TABLES {table} AND {staging}")
        client.command(f"DROP TABLE IF EXISTS {staging}")

        log.info(f"Loaded {count:,} rows into {table}")
        return count

    def query_scalar(self, sql: str) -> int | float | str:
        row = self._client().query(sql).first_row
        return row[0]

    def command(self, sql: str) -> None:
        self._client().command(sql)
