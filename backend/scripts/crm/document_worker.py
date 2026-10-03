"""Finite or supervised CRM PDF worker using the existing PostgreSQL and private storage."""

import argparse
import asyncio

from sqlmodel.ext.asyncio.session import AsyncSession

from app.crm.documents import process_document_job
from app.postgres import close_postgres, get_postgres_engine


async def run(once=False):
    try:
        while True:
            async with AsyncSession(get_postgres_engine(), expire_on_commit=False) as db:
                processed = await process_document_job(db)
            if once:
                return
            if not processed:
                await asyncio.sleep(2)
    finally:
        await close_postgres()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="Claim at most one document then exit")
    asyncio.run(run(parser.parse_args().once))
