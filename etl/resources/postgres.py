"""Postgres resource — primarily configured via dagster.yaml for metadata storage.

This module exposes a lightweight resource for direct queries if assets need
to read/write application data to Postgres outside of Dagster metadata.
"""

from __future__ import annotations

import os

from dagster import ConfigurableResource


class PostgresResource(ConfigurableResource):
    """Direct Postgres connection for application queries (not Dagster metadata)."""

    postgres_url: str = ""

    def get_url(self) -> str:
        url = self.postgres_url or os.environ.get("APP_POSTGRES_URL", "")
        if not url:
            raise ValueError("postgres_url or APP_POSTGRES_URL must be set")
        return url
