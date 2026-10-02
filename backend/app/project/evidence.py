"""Public DLD project evidence. No inferred Reelly payment plans or catalogue prices."""

from datetime import date, datetime

from app.market.evidence import MarketAccessContext
from app.project import evidence_queries, queries


async def get_project_observation() -> dict:
    rows = await queries.fetch_project_register_snapshot()
    return {
        key: str(value) if value is not None else None
        for key, value in (rows[0] if rows else {}).items()
    }


async def get_project_evidence(names: list[str], *, context: MarketAccessContext) -> dict:
    rows = await evidence_queries.fetch_project_evidence(names)
    return {
        "reference_date": context.reference_date.isoformat(),
        "projects": [
            {
                key: value.isoformat() if isinstance(value, (date, datetime)) else value
                for key, value in row.items()
            }
            for row in rows
        ],
        "source": "DLD project register; construction progress is reported percent_completed",
        "unit_prices": None,
        "unit_sizes": None,
        "payment_plans": None,
        "limitations": [
            "Reelly/Bayut catalogue data and payment plans are unavailable.",
            "Planned delivery is a scheduled date, not a completion guarantee.",
        ],
    }
