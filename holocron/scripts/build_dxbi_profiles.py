"""Rebuild dxbi_sale_profile and dxbi_rental_profile (holocron.market.dxbi_profile).

Dagster runs this as the dxbi_profiles asset after the market releases; run it by hand after a
manual release:

    python scripts/build_dxbi_profiles.py [--only dxbi_sale_profile]
"""

from __future__ import annotations

import argparse
import time

from holocron.market.dxbi_profile import PROFILE_TABLES, build_profile, create_tables
from holocron.platform.clickhouse import ClickHouseClient
from holocron.platform.settings import Settings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--only", choices=PROFILE_TABLES)
    args = parser.parse_args(argv)
    clickhouse = ClickHouseClient(Settings())
    create_tables(clickhouse)
    for table in PROFILE_TABLES:
        if args.only and table != args.only:
            continue
        started = time.monotonic()
        rows = build_profile(clickhouse, table)
        print(f"{table}: {rows} rows in {time.monotonic() - started:.0f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
