"""Database connection and bulk insert operations."""

import io
import os
import logging
from typing import Any
from urllib.parse import urlparse

import polars as pl
import psycopg2
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)


def get_connection_params() -> dict:
    """Parse DATABASE_URL into connection params."""
    url = os.environ.get("DATABASE_URL", "").replace("postgresql+asyncpg://", "postgresql://")
    parsed = urlparse(url)
    return {
        "host": parsed.hostname or "localhost",
        "port": parsed.port or 5432,
        "user": parsed.username or "admin",
        "password": parsed.password or "admin",
        "dbname": parsed.path.lstrip("/") or "analytics",
    }


def get_connection(disable_fk: bool = True):
    """Get psycopg2 connection with optional FK checks disabled."""
    conn = psycopg2.connect(**get_connection_params())
    conn.autocommit = False
    if disable_fk:
        with conn.cursor() as cur:
            cur.execute("SET session_replication_role = 'replica'")
        conn.commit()
    return conn


class CopyUpserter:
    """High-performance PostgreSQL upserter using COPY + temp table."""

    def __init__(self, conn, model_class: Any, primary_keys: list[str]):
        self.conn = conn
        self.table_name = model_class.__tablename__
        self.primary_keys = primary_keys
        self.columns = (
            [col.name for col in model_class.__table__.columns]
            if hasattr(model_class, "__table__")
            else []
        )
        self.total_inserted = 0
        self.total_updated = 0
        self.errors: list[str] = []

    def _to_buffer(self, df: pl.DataFrame, cols: list[str]) -> io.BytesIO:
        """Convert DataFrame to tab-separated CSV buffer."""
        buf = io.BytesIO()
        df.select(cols).write_csv(buf, include_header=False, separator="\t", null_value="\\N")
        buf.seek(0)
        return buf

    def insert_batch(self, df: pl.DataFrame) -> int:
        """Insert batch via COPY to temp table, then INSERT with ON CONFLICT DO NOTHING."""
        if df.is_empty():
            return 0

        cols = [c for c in self.columns if c in df.columns]
        col_list, pk_list = ", ".join(cols), ", ".join(self.primary_keys)
        temp = f"_temp_{self.table_name}"

        try:
            with self.conn.cursor() as cur:
                cur.execute(
                    f"CREATE TEMP TABLE IF NOT EXISTS {temp} (LIKE {self.table_name} INCLUDING DEFAULTS) ON COMMIT DELETE ROWS"
                )
                cur.copy_expert(
                    f"COPY {temp} ({col_list}) FROM STDIN WITH (FORMAT CSV, DELIMITER E'\\t', NULL '\\N')",
                    self._to_buffer(df, cols),
                )
                cur.execute(
                    f"INSERT INTO {self.table_name} ({col_list}) SELECT {col_list} FROM {temp} ON CONFLICT ({pk_list}) DO NOTHING"
                )
                inserted = cur.rowcount
            self.conn.commit()
            self.total_inserted += inserted
            return inserted
        except Exception as e:
            self.conn.rollback()
            self.errors.append(f"COPY error: {str(e)[:200]}")
            return 0

    def upsert_batch(self, df: pl.DataFrame) -> int:
        """Upsert batch via COPY to temp table, then INSERT with ON CONFLICT DO UPDATE."""
        if df.is_empty():
            return 0

        cols = [c for c in self.columns if c in df.columns]
        col_list, pk_list = ", ".join(cols), ", ".join(self.primary_keys)
        update_cols = [c for c in cols if c not in self.primary_keys]
        update_clause = ", ".join([f"{c} = EXCLUDED.{c}" for c in update_cols])
        temp = f"_temp_{self.table_name}"

        try:
            with self.conn.cursor() as cur:
                cur.execute(
                    f"CREATE TEMP TABLE IF NOT EXISTS {temp} (LIKE {self.table_name} INCLUDING DEFAULTS) ON COMMIT DELETE ROWS"
                )
                cur.copy_expert(
                    f"COPY {temp} ({col_list}) FROM STDIN WITH (FORMAT CSV, DELIMITER E'\\t', NULL '\\N')",
                    self._to_buffer(df, cols),
                )
                if update_clause:
                    cur.execute(
                        f"INSERT INTO {self.table_name} ({col_list}) SELECT {col_list} FROM {temp} ON CONFLICT ({pk_list}) DO UPDATE SET {update_clause}"
                    )
                else:
                    cur.execute(
                        f"INSERT INTO {self.table_name} ({col_list}) SELECT {col_list} FROM {temp} ON CONFLICT ({pk_list}) DO NOTHING"
                    )
                updated = cur.rowcount
            self.conn.commit()
            self.total_updated += updated
            return updated
        except Exception as e:
            self.conn.rollback()
            self.errors.append(f"Upsert error: {str(e)[:200]}")
            return 0
