"""Agent lead analytics for managers (agreed 17 Nov 2026): per-person response and claim times,
contacts in the last day, stages and sources, from facts the CRM already records.

Averages only; nothing is scored or ranked.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta

from app.crm.analytics_models import SourceKind
from app.crm.inbound_models import SOLD_OWNER_SOURCE

CONTACT_TYPES = ("contact_attempt", "call", "email", "whatsapp", "meeting")
QUALIFIED = ("qualified", "viewing", "valuation", "signed", "active", "won")
OWN_SOURCES = ("manual", "own contact", "referral")


def source_kind(source: str, observed_data: dict | None) -> SourceKind:
    if source == SOLD_OWNER_SOURCE:
        return "vitevue_sold"
    if observed_data and "vitevue_lease" in observed_data:
        return "vitevue_lease"
    if (source or "").strip().casefold() in OWN_SOURCES:
        return "own"
    return "marketing"


def average_minutes(durations: list[timedelta]) -> int | None:
    if not durations:
        return None
    seconds = sum(d.total_seconds() for d in durations) / len(durations)
    # Round half up (12.5 → 13), not Python's banker's rounding.
    return int(seconds / 60 + 0.5)


def claim_waits(
    events: list[tuple[int, str, datetime, str | None]],
) -> dict[str, list[timedelta]]:
    """Rows (enquiry_id, reason, created_at, actor) in time order → per claimer, the wait from the
    latest earlier release of the same lead. A claim with no earlier release is skipped."""
    released: dict[int, datetime] = {}
    waits: dict[str, list[timedelta]] = defaultdict(list)
    for enquiry_id, reason, created_at, actor in events:
        if reason == "released":
            released[enquiry_id] = created_at
        elif reason == "claimed" and actor and enquiry_id in released:
            waits[actor].append(created_at - released.pop(enquiry_id))
    return dict(waits)
