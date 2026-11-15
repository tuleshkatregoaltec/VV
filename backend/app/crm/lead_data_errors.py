"""What a lease-data (ClickHouse) failure means to the agent and the page.

- Over its memory or time budget, or the connection timed out: the warehouse is busy, a retry
  in a few seconds can succeed (503 with Retry-After).
- Lease tables not loaded: the data is not there, which must not read as "no leads" (503).
- Anything else: unavailable, a retry is not expected to help (503 without Retry-After).
"""

from __future__ import annotations

import logging

from fastapi import HTTPException

logger = logging.getLogger(__name__)

# ClickHouse error codes: MEMORY_LIMIT_EXCEEDED, TIMEOUT_EXCEEDED, TOO_SLOW, QUERY_WAS_CANCELLED
# (the server's own cancellation), and the per-query memory/time markers in their messages.
_BUSY_MARKERS = (
    "Code: 241.",
    "Code: 159.",
    "Code: 160.",
    "Code: 394.",
    "MEMORY_LIMIT_EXCEEDED",
    "TIMEOUT_EXCEEDED",
    "TOO_SLOW",
    "Read timed out",
    "timed out",
)

BUSY_DETAIL = "CRM lead data is busy. Retry in a few seconds."
UNAVAILABLE_DETAIL = "CRM lead data is temporarily unavailable"
NOT_LOADED_DETAIL = "CRM lead data is not loaded yet"


def is_busy(exc: BaseException) -> bool:
    if isinstance(exc, TimeoutError):
        return True
    text = str(exc)
    return any(marker in text for marker in _BUSY_MARKERS)


def lead_data_error(exc: Exception, what: str) -> HTTPException:
    """The HTTP error for a failed lease query; logs it once with its classification."""
    if is_busy(exc):
        logger.warning("CRM %s query over budget: %s", what, str(exc)[:300])
        return HTTPException(status_code=503, detail=BUSY_DETAIL, headers={"Retry-After": "5"})
    logger.error("CRM %s query failed", what, exc_info=exc)
    return HTTPException(status_code=503, detail=UNAVAILABLE_DETAIL)


def not_loaded() -> HTTPException:
    return HTTPException(status_code=503, detail=NOT_LOADED_DETAIL)
