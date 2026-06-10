from __future__ import annotations

from dagster import ConfigurableResource

from holocron.platform.clickhouse import ClickHouseClient
from holocron.platform.s3 import S3Client
from holocron.platform.settings import settings


class S3Resource(ConfigurableResource):
    def client(self) -> S3Client:
        return S3Client(settings)


class ClickHouseResource(ConfigurableResource):
    def client(self) -> ClickHouseClient:
        return ClickHouseClient(settings)
