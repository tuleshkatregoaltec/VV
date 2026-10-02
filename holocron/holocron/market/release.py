"""Publish a canonical market release only after it passes validation.

A run builds every table of a release (match ledger, then events) into run-unique staging
tables, evaluates the blocking checks and a served-row floor against those staging tables,
and only then exchanges them with the served tables. A rejected build raises and leaves the
served release untouched; its staging tables are dropped.

The replaced release is kept as ``<table>__previous`` (one release retained) so an operator
can roll back with ``EXCHANGE TABLES <table> AND <table>__previous``. The ledger and the
events are exchanged one after the other; ClickHouse has no multi-table transaction, so a
crash between the two leaves a new ledger beside the old events. The backend reads only the
events, and the next run rebuilds both.
"""

from __future__ import annotations

import math
import re
from dataclasses import replace
from uuid import uuid4

from holocron.market import transforms
from holocron.market.checks import CHECKS, MarketCheck, evaluate
from holocron.platform.clickhouse import ClickHouseClient
from holocron.platform.clickhouse_schema import ensure_schema

# DLD never deletes registered records, so a staged release serving clearly fewer rows than
# the one it replaces means truncated or partial input, not a market change.
MIN_SERVED_ROW_RATIO = 0.99


class MarketReleaseRejected(RuntimeError):
    """The staged release failed validation; the served release was not changed."""


def render(sql: str, names: dict[str, str]) -> str:
    """Point every whole-word reference to a served table at its staging table."""
    pattern = r"\b(" + "|".join(re.escape(name) for name in names) + r")\b"
    return re.sub(pattern, lambda match: names[match.group(1)], sql)


def _scalar(clickhouse: ClickHouseClient, sql: str) -> int:
    return int(clickhouse.query(sql).result_rows[0][0])


def _blocking_failures(
    clickhouse: ClickHouseClient, checks: tuple[MarketCheck, ...], staged: dict[str, str]
) -> list[str]:
    failures = []
    for check in checks:
        if not check.blocking:
            continue
        passed, value = evaluate(clickhouse, replace(check, sql=render(check.sql, staged)))
        # A ratio with nothing to measure (e.g. no DXBI rows yet) cannot invalidate DLD data.
        if not passed and not math.isnan(value):
            failures.append(f"{check.name}={value:g} (needs {check.op} {check.threshold:g})")
    return failures


def publish_validated(
    *,
    clickhouse: ClickHouseClient,
    builds: dict[str, tuple[str, ...]],
    served_table: str,
    checks: tuple[MarketCheck, ...],
) -> dict[str, int | str]:
    release_id = uuid4().hex[:12]
    staged = {table: f"{table}__staging_{release_id}" for table in builds}
    try:
        for table, statements in builds.items():
            clickhouse.command(f"CREATE TABLE `{staged[table]}` AS `{table}`")
            for statement in statements:
                clickhouse.command(render(statement, staged))
            # A fresh INSERT ... SELECT leaves dozens of parts; the backend's ordered LIMIT
            # queries read every part, so the table is merged before it goes live.
            clickhouse.command(f"OPTIMIZE TABLE `{staged[table]}` FINAL")

        failures = _blocking_failures(clickhouse, checks, staged)
        served_sql = "SELECT count() FROM `{}` WHERE is_served = 1"
        live = _scalar(clickhouse, served_sql.format(served_table))
        new = _scalar(clickhouse, served_sql.format(staged[served_table]))
        if new < live * MIN_SERVED_ROW_RATIO:
            failures.append(f"served_rows={new} (live release serves {live})")
        if failures:
            raise MarketReleaseRejected(
                f"{served_table} release {release_id} rejected, served release unchanged: "
                + "; ".join(failures)
            )

        for table in builds:
            clickhouse.command(f"EXCHANGE TABLES `{table}` AND `{staged[table]}`")
            clickhouse.command(f"DROP TABLE IF EXISTS `{table}__previous`")
            clickhouse.command(f"RENAME TABLE `{staged[table]}` TO `{table}__previous`")
    finally:
        for name in staged.values():
            clickhouse.command(f"DROP TABLE IF EXISTS `{name}`")

    rows = clickhouse.query(
        f"SELECT match_status, count() FROM `{served_table}` GROUP BY match_status"
    ).result_rows
    return {
        "release_id": release_id,
        "row_count": sum(int(count) for _, count in rows),
        "served_rows": new,
        **{str(status): int(count) for status, count in rows},
    }


def _checks_for(asset: str) -> tuple[MarketCheck, ...]:
    return tuple(check for check in CHECKS if check.asset == asset)


def materialize_market_sale_events(*, clickhouse: ClickHouseClient) -> dict[str, int | str]:
    ensure_schema(clickhouse=clickhouse)
    return publish_validated(
        clickhouse=clickhouse,
        builds={
            "market_sale_matches": (transforms._SALE_MATCHES_SQL,),
            "market_sale_events": (
                transforms._SALE_EVENTS_DLD_SQL,
                transforms._SALE_EVENTS_DXBI_SQL,
            ),
        },
        served_table="market_sale_events",
        checks=_checks_for("market_sale_events"),
    )


def materialize_market_rental_events(*, clickhouse: ClickHouseClient) -> dict[str, int | str]:
    ensure_schema(clickhouse=clickhouse)
    return publish_validated(
        clickhouse=clickhouse,
        builds={
            "market_rental_matches": transforms._RENTAL_MATCH_STATEMENTS,
            "market_rental_events": (
                transforms._RENTAL_EVENTS_DLD_SQL,
                transforms._RENTAL_EVENTS_DXBI_SQL,
            ),
        },
        served_table="market_rental_events",
        checks=_checks_for("market_rental_events"),
    )
