"""Market AI's readable source labels, applied to its own tool results.

Market evidence names its sources as stored keys ("dld/matched", "dubai_pulse", "pf_listings");
Market AI shows them as the business sources they are. These labels are Market AI's alone: the
shared chat guard (app.chat.security) keeps a record's own source as stored, which is right for
CRM records (a lead's channel such as "Property Finder" is not a listings dataset).
"""

import functools
from typing import Any

from app.chat.security import safe_tool as shared_safe_tool

SOURCE_KEYS = {"source", "sources", "source_table", "source_name"}


def source_label(value: Any) -> str:
    text = str(value).lower()
    if "property finder" in text or "propertyfinder" in text or text.startswith("pf"):
        return "Property Finder asking listings"
    if "dld" in text and "dxbi" in text:
        return "Reconciled DLD and DXBI registered records"
    if "dubai_pulse" in text:
        return "DLD registered transactions"
    if "dxbi" in text:
        return "DXBI records"
    if "dld" in text:
        return "DLD project register" if "project" in text else "DLD registered transactions"
    if "reelly" in text:
        return "Reelly project catalogue"
    return "Stored market data"


def source_evidence(value: Any) -> Any:
    if isinstance(value, dict):
        counts = {}
        for source, count in list(value.items())[:20]:
            if isinstance(count, (int, float)):
                label = source_label(source)
                counts[label] = counts.get(label, 0) + count
        return counts
    if isinstance(value, list):
        return list(dict.fromkeys(source_label(item) for item in value[:20]))
    return source_label(value)


def market_sources(value: Any, depth: int = 0) -> Any:
    """The result with every source field named as a market source; nothing else changes."""
    if depth > 8:
        return value
    if isinstance(value, dict):
        return {
            key: source_evidence(item)
            if str(key) in SOURCE_KEYS
            else market_sources(item, depth + 1)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [market_sources(item, depth + 1) for item in value]
    return value


def safe_tool(function):
    """The shared tool guard (bounds, redaction, error hiding), after market source labels."""

    @functools.wraps(function)
    async def labelled(*args, **kwargs):
        return market_sources(await function(*args, **kwargs))

    return shared_safe_tool(labelled)
