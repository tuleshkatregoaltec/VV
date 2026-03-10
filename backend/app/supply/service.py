"""Supply service for upcoming projects using ClickHouse."""

import logging
from typing import Any, Dict, List

from app.clickhouse.client import query
from app.clickhouse.queries import get_upcoming_projects

logger = logging.getLogger(__name__)


async def get_upcoming_projects_ch(limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
    """
    Get all active/upcoming projects from ClickHouse.
    Active = has start_date AND no completion_date AND no cancellation_date
    """
    try:
        sql = get_upcoming_projects(limit=limit, offset=offset)
        params = {"limit": limit, "offset": offset}

        result = await query(sql, params)
        return result

    except Exception as e:
        logger.error(f"Error fetching upcoming projects from ClickHouse: {str(e)}")
        return []
