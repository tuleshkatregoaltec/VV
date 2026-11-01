"""Select an immutable rental base only while every input revision still matches."""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from crm_rental_sql import (
    AREA_LEAD_CTE,
    BASE_TABLE,
    DEPENDENCY_STATE_SQL,
    LIVE_LEAD_CTE,
    PUBLICATION_POLICY,
    TRANSFORM_REVISION,
    base_lead_cte,
    dependency_revision,
    schema_revision,
    schema_sql,
)

from app.config import settings

logger = logging.getLogger(__name__)
Query = Callable[..., Awaitable[list[dict[str, Any]]]]

BASE_METADATA_SQL = f"""
SELECT engine, total_rows, comment
FROM system.tables
WHERE database=currentDatabase() AND name='{BASE_TABLE}'
"""


async def lead_cte(query: Query, *, areas: bool = False) -> str:
    live = AREA_LEAD_CTE if areas else LIVE_LEAD_CTE
    if not settings.CRM_RENTAL_BASE_ENABLED:
        return live
    try:
        metadata = await query(BASE_METADATA_SQL)
        if not metadata or metadata[0]["engine"] not in {
            "MergeTree",
            "ReplicatedMergeTree",
            "SharedMergeTree",
        }:
            return live
        table = metadata[0]
        marker = json.loads(table["comment"])
        if (
            marker.get("kind") != PUBLICATION_POLICY
            or marker.get("transform") != TRANSFORM_REVISION
            or not marker.get("rows")
            or table["total_rows"] != marker["rows"]
        ):
            return live
        columns = await query(schema_sql(BASE_TABLE))
        if not columns or marker.get("schema") != schema_revision(columns):
            return live
        current = dependency_revision(await query(DEPENDENCY_STATE_SQL))
        if marker.get("source") != current:
            return live
        return base_lead_cte(areas=areas)
    except Exception:
        # Missing permissions, unsupported schema, malformed/old markers and stale inputs all
        # fail open to the canonical live query. Cancellation still propagates (BaseException).
        logger.warning("Rental ranked base unavailable; using live query", exc_info=True)
        return live
