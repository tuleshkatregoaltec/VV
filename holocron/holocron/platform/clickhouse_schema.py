from __future__ import annotations

from pathlib import Path

from holocron.contracts import ClickHouseCommands

_cached_statements: list[str] | None = None


def schema_sql_path() -> Path:
    return Path(__file__).resolve().parents[1] / "lib" / "sql" / "clickhouse_schema.sql"


def iter_sql_statements(sql: str) -> list[str]:
    return [statement.strip() for statement in sql.split(";") if statement.strip()]


def ensure_schema(*, clickhouse: ClickHouseCommands) -> None:
    global _cached_statements
    if _cached_statements is None:
        sql_path = schema_sql_path()
        if not sql_path.exists():
            raise FileNotFoundError(f"Missing ClickHouse schema file: {sql_path}")
        _cached_statements = iter_sql_statements(sql_path.read_text(encoding="utf-8"))
    for statement in _cached_statements:
        clickhouse.command(statement)
