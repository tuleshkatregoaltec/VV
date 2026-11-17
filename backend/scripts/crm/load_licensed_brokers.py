#!/usr/bin/env python3
"""Replace the licensed real-estate broker reference table from the regulator's broker CSV.

Run from backend: ``uv run python -m scripts.crm.load_licensed_brokers --csv PATH``.
The CSV holds brokers' personal phones and emails: it is read, never copied or committed, and only
counts are printed. The table is replaced in one transaction, so a failed load keeps the old list.
After a load, ``python -m scripts.crm.backfill_licensed_brokers`` applies the list to stored claims.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import delete, insert
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.crm.brokers import broker_row
from app.crm.models import CrmLicensedBroker
from app.postgres import close_postgres, get_postgres_engine

CHUNK = 2000


def read_brokers(path: Path) -> tuple[list[dict], int]:
    """(table rows, skipped records) of the CSV; the last record of a broker number wins."""
    now = datetime.now(timezone.utc)
    rows: dict[int, dict] = {}
    skipped = 0
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for record in csv.DictReader(handle):
            row = broker_row(record, now=now)
            if row is None or not row["name_key"]:
                skipped += 1
                continue
            rows[row["broker_number"]] = row
    return list(rows.values()), skipped


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", required=True, type=Path)
    args = parser.parse_args()
    rows, skipped = read_brokers(args.csv)
    if not rows:
        raise SystemExit("The CSV holds no brokers; the table was left as it was.")
    factory = async_sessionmaker(get_postgres_engine(), expire_on_commit=False)
    try:
        async with factory() as db:
            await db.execute(delete(CrmLicensedBroker))
            for start in range(0, len(rows), CHUNK):
                await db.execute(insert(CrmLicensedBroker), rows[start : start + CHUNK])
            await db.commit()
    finally:
        await close_postgres()
    print(
        {
            "brokers_loaded": len(rows),
            "skipped_records": skipped,
            "with_phone": sum(bool(row["phones"]) for row in rows),
            "with_email": sum(bool(row["emails"]) for row in rows),
            "expired_cards": sum(
                bool(row["card_expiry_date"]) and row["card_expiry_date"] < datetime.now().date()
                for row in rows
            ),
        }
    )


if __name__ == "__main__":
    asyncio.run(main())
