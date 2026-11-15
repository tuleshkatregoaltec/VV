"""Build the Transactions page tables (dxbi_sales_page, dxbi_leases_page).

Each holds ``_sales_source`` / ``_rentals_source`` over all dates, one row per DXBI record with
its place and profile resolved, ordered by date for the newest-first pages. The DXBI warehouse
sync builds them in its release step, after the profiles they read
(holocron/holocron/platform/sync_dxbi_to_warehouse.py), and then clears the cached pages.
A build fills a staging copy and swaps it in, so readers never see a partial table, and an empty
build leaves the served table unchanged.

    cd backend && .venv/bin/python -m app.transaction.page_tables
"""

import asyncio
import json
import logging
from typing import Any, Callable

from app.transaction import queries

logger = logging.getLogger(__name__)

PAGE_TABLES: dict[str, tuple[Callable[[], str], str]] = {
    queries.SALES_PAGE_TABLE: (
        lambda: queries._sales_source("1 = 1"),
        "(transaction_date, transaction_id)",
    ),
    queries.LEASES_PAGE_TABLE: (
        lambda: queries._rentals_source("1 = 1"),
        "(lease_start, contract_id)",
    ),
}
# A build reads the whole DXBI source once (about 1.7 GiB for sales); keep it well inside the
# warehouse's 9 GiB that the CRM shares.
BUILD_SETTINGS = {"max_memory_usage": 4_000_000_000, "max_threads": 4}


async def build_page_table(client: Any, table: str, select: str, order_by: str) -> int:
    staging = f"{table}__staging"
    await client.command(f"DROP TABLE IF EXISTS {staging}")
    try:
        await client.command(
            f"CREATE TABLE {staging} ENGINE = MergeTree ORDER BY {order_by} "
            f"AS SELECT * FROM ({select})",
            settings=BUILD_SETTINGS,
        )
        result = await client.query(f"SELECT count() FROM {staging}")
        rows = int(result.result_rows[0][0])
        if rows == 0:
            raise RuntimeError(
                f"{table}: the build produced no rows; the served table is unchanged"
            )
        if int(await client.command(f"EXISTS TABLE {table}")):
            await client.command(f"EXCHANGE TABLES {staging} AND {table}")
        else:
            await client.command(f"RENAME TABLE {staging} TO {table}")
        return rows
    finally:
        await client.command(f"DROP TABLE IF EXISTS {staging}")


async def build_page_tables(client: Any) -> dict[str, int]:
    """Both page tables; returns the rows each now serves."""
    rows = {}
    for table, (select, order_by) in PAGE_TABLES.items():
        rows[table] = await build_page_table(client, table, select(), order_by)
        logger.info("%s built: %d rows", table, rows[table])
    return rows


async def _main() -> dict[str, int]:
    from app.clickhouse.client import close_clickhouse, get_client

    try:
        return await build_page_tables(await get_client())
    finally:
        await close_clickhouse()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    print(json.dumps(asyncio.run(_main())))
