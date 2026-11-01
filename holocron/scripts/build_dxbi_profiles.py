"""Rebuild the DXBI profiles, then the listed records Analytics reads (holocron.market.dxbi_profile).

Dagster runs this as the dxbi_profiles asset after the market releases; run it by hand after a
manual release:

    python scripts/build_dxbi_profiles.py [--only dxbi_sale_profile] [--from-hierarchy]
"""

from __future__ import annotations

import argparse
import time

from holocron.market import analytics_hierarchy
from holocron.market.dxbi_profile import (
    LISTED_TABLES,
    PROFILE_TABLES,
    build_profile,
    create_tables,
)
from holocron.platform.clickhouse import ClickHouseClient
from holocron.platform.settings import Settings

HIERARCHY = "analytics_hierarchy"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--only", choices=(*PROFILE_TABLES, HIERARCHY, *LISTED_TABLES))
    parser.add_argument(
        "--from-hierarchy",
        action="store_true",
        help="keep the profiles; rebuild the Analytics hierarchy and the listed records",
    )
    args = parser.parse_args(argv)
    clickhouse = ClickHouseClient(Settings())
    create_tables(clickhouse)
    # The hierarchy reads the profiles and the listed records read both: built in that order, as
    # the dxbi_profiles asset does.
    steps = [*PROFILE_TABLES, HIERARCHY, *LISTED_TABLES]
    if args.from_hierarchy:
        steps = steps[steps.index(HIERARCHY) :]
    for step in steps:
        if args.only and step != args.only:
            continue
        started = time.monotonic()
        if step == HIERARCHY:
            for table, rows in analytics_hierarchy.build_hierarchy(clickhouse).items():
                print(f"{table}: {rows} rows")
        else:
            print(f"{step}: {build_profile(clickhouse, step)} rows", end="")
        print(f" ({step} in {time.monotonic() - started:.0f}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
