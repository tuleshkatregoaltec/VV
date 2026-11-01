#!/usr/bin/env python3
"""Apply the licensed-broker rules to stored owner claims without re-running the matcher.

Run from backend: ``uv run python -m scripts.crm.backfill_licensed_brokers [--organization-id ID]
[--import-id N]``. Re-decides only the rows whose broker marks changed (a broker row becomes the
outcome ``broker``), then refreshes every import summary from the stored evidence, which also
fills ``review_reasons`` and ``sales_matched``. Prints per-import before/after numbers, no contacts.
"""

from __future__ import annotations

import argparse
import asyncio
import json

from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlmodel.ext.asyncio.session import AsyncSession

from app.crm.broker_backfill import backfill_licensed_brokers, import_summaries
from app.postgres import close_postgres, get_postgres_engine


def _figures(summary: dict | None) -> dict:
    match = (summary or {}).get("owner_match") or {}
    units = match.get("units") or {}
    total = units.get("total") or 0
    return {
        "units_total": total,
        "units_confirmed": units.get("confirmed"),
        "units_confirmed_pct": round(100 * (units.get("confirmed") or 0) / total, 1)
        if total
        else None,
        "rows_broker": (match.get("rows") or {}).get("broker", 0),
        "rows_lender": (match.get("rows") or {}).get("lender", 0),
        "review_reasons": match.get("review_reasons"),
        "sales_matched": match.get("sales_matched"),
        "contact_ready": (summary or {}).get("contact_ready"),
        "valid_contacts": (summary or {}).get("valid_contacts"),
    }


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--organization-id")
    parser.add_argument("--import-id", type=int)
    args = parser.parse_args()
    factory = async_sessionmaker(get_postgres_engine(), class_=AsyncSession, expire_on_commit=False)
    try:
        async with factory() as db:
            before = await import_summaries(db, organization_id=args.organization_id)
            result = await backfill_licensed_brokers(
                db, organization_id=args.organization_id, import_id=args.import_id
            )
        async with factory() as db:
            after = await import_summaries(db, organization_id=args.organization_id)
    finally:
        await close_postgres()
    report = {
        import_id: {
            "name": record["name"],
            "before": _figures(record),
            "after": _figures(after.get(import_id)),
            "broker_contact_rows": result["per_import"]
            .get(import_id, {})
            .get("broker_contact_rows", 0),
        }
        for import_id, record in sorted(before.items())
        if args.import_id in (None, import_id)
    }
    print(
        json.dumps(
            {**{k: v for k, v in result.items() if k != "per_import"}, "imports": report}, indent=1
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
