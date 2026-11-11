#!/usr/bin/env python3
"""Mark generated documents left `generating` by a crashed API process as failed.

Agents then see the failure and can generate again. Orphaned PDFs (uploaded, but the record
never became `ready`) are not deleted here.

    uv run python scripts/crm/reconcile_documents.py
    uv run python scripts/crm/reconcile_documents.py --older-than-minutes 30
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import timedelta

from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlmodel.ext.asyncio.session import AsyncSession

import app.postgres.models  # noqa: F401 - registers every table the documents reference
from app.crm.documents import reconcile_stale_documents
from app.postgres import close_postgres, get_postgres_engine


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--older-than-minutes",
        type=int,
        default=10,
        help="Only documents still generating after this many minutes (default 10).",
    )
    args = parser.parse_args()

    session_factory = async_sessionmaker(
        get_postgres_engine(),
        class_=AsyncSession,
        expire_on_commit=False,
    )
    try:
        async with session_factory() as db:
            count = await reconcile_stale_documents(
                db, older_than=timedelta(minutes=args.older_than_minutes)
            )
    finally:
        await close_postgres()
    print(f"Marked {count} interrupted document(s) as failed")


if __name__ == "__main__":
    asyncio.run(main())
