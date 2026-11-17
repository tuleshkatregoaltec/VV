#!/usr/bin/env python3
"""Put owners whose unit recently resold into the CRM Lead Inbox (one item per owner).

Run this explicit maintenance operation after reviewed owner or sales data changes.
It is not run inside HTTP uploads or the fenced import publication transaction.

    uv run python scripts/crm/sync_recently_sold_inbox.py --organization-id <org>
    uv run python scripts/crm/sync_recently_sold_inbox.py --organization-id <org> --days 60
"""

from __future__ import annotations

import argparse
import asyncio

from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlmodel.ext.asyncio.session import AsyncSession

from app.crm.recently_sold import RECENTLY_SOLD_DAYS, sync_recently_sold_inbox
from app.postgres import close_postgres, get_postgres_engine


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--organization-id", required=True)
    parser.add_argument(
        "--days",
        type=int,
        default=RECENTLY_SOLD_DAYS,
        help=f"Sales within this many days (default {RECENTLY_SOLD_DAYS}).",
    )
    args = parser.parse_args()

    session_factory = async_sessionmaker(
        get_postgres_engine(),
        class_=AsyncSession,
        expire_on_commit=False,
    )
    try:
        async with session_factory() as db:
            result = await sync_recently_sold_inbox(
                db, organization_id=args.organization_id, days=args.days
            )
    finally:
        await close_postgres()
    print(result)


if __name__ == "__main__":
    asyncio.run(main())
