#!/usr/bin/env python3
"""Estimate today's value of current-owner properties from recent comparable sales."""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict

from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlmodel.ext.asyncio.session import AsyncSession

from app.clickhouse.client import close_clickhouse
from app.crm.valuation_service import value_owner_claims
from app.postgres import close_postgres, get_postgres_engine


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--organization-id", required=True)
    parser.add_argument("--import-id", type=int)
    parser.add_argument(
        "--dry-run", action="store_true", help="Value and report, then roll back without saving."
    )
    args = parser.parse_args()

    session_factory = async_sessionmaker(
        get_postgres_engine(), class_=AsyncSession, expire_on_commit=False
    )
    try:
        async with session_factory() as db:
            summary = await value_owner_claims(
                db,
                organization_id=args.organization_id,
                import_id=args.import_id,
                commit=not args.dry_run,
            )
            if args.dry_run:
                await db.rollback()
    finally:
        await close_clickhouse()
        await close_postgres()
    print(json.dumps({"dry_run": args.dry_run, **asdict(summary)}, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
