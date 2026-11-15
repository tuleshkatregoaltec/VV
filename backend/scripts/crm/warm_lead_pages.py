"""Compute today's default lease pages into the release-keyed cache (run after a lease load).

The cache key follows the lease sources' revision, so a vv-dxbi-sync load already retires the
old answers; this only spares the first agent the cold computation (~4 s for the dashboard).

    cd backend && uv run python scripts/crm/warm_lead_pages.py
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.crm.opportunities import get_dashboard  # noqa: E402
from app.crm.renewal_leads import list_renewal_areas, list_renewals  # noqa: E402


async def main() -> None:
    await get_dashboard(
        status=None,
        priority=None,
        asset_class=None,
        property_type=None,
        area=None,
        project=None,
        building=None,
        search=None,
        breakdown="area",
        limit=50,
        offset=0,
    )
    await list_renewal_areas()
    await list_renewals(
        window=None, area=None, property_type=None, project=None, building=None, limit=50, offset=0
    )
    print("CRM lease pages warmed")


if __name__ == "__main__":
    asyncio.run(main())
