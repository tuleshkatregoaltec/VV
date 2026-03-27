"""Supply service for upcoming projects using ClickHouse."""

import logging
from typing import Any, Dict, List

from app.clickhouse.client import query

logger = logging.getLogger(__name__)


async def get_upcoming_projects_ch(limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
    """
    Get all active/upcoming projects from ClickHouse.
    Active = has start_date AND no completion_date AND no cancellation_date
    """
    try:
        sql = """
            SELECT
                p.project_id,
                p.project_name,
                p.developer_id,
                d.developer_name_en as developer_name,
                p.area_name_en,
                p.project_start_date,
                p.project_end_date,
                p.percent_completed,
                p.no_of_buildings,
                p.no_of_units
            FROM ch_projects p
            LEFT JOIN ch_developers d ON p.developer_id = d.developer_id
            WHERE
                p.project_start_date IS NOT NULL
                AND p.completion_date IS NULL
                AND p.cancellation_date IS NULL
            ORDER BY
                p.project_end_date ASC NULLS LAST,
                p.project_name ASC
            LIMIT {limit:Int32}
            OFFSET {offset:Int32}
        """
        params = {"limit": limit, "offset": offset}

        result = await query(sql, params)
        return result

    except Exception as e:
        logger.error(f"Error fetching upcoming projects from ClickHouse: {str(e)}")
        return []
