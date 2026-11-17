"""Rental timing: is a property free by the tenant's move-in date?

Client call (3 Nov): a tenant needs a home free by the time their current lease ends, so a unit
whose lease expires after the move-in date is disqualified (27:38). Listings rarely have an
availability field; it is written in the description (20:10), and Property Finder listings can be
months old, so their timing needs confirming (19:54).
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any, Literal

Timing = Literal["in_time", "after", "unknown"]

# Older than this, a portal listing's "available now" may no longer hold.
STALE_LISTING_DAYS = 60

_MONTHS = {
    name: number
    for number, names in enumerate(
        (
            ("jan", "january"),
            ("feb", "february"),
            ("mar", "march"),
            ("apr", "april"),
            ("may",),
            ("jun", "june"),
            ("jul", "july"),
            ("aug", "august"),
            ("sep", "sept", "september"),
            ("oct", "october"),
            ("nov", "november"),
            ("dec", "december"),
        ),
        start=1,
    )
    for name in names
}
_MONTH = r"(" + "|".join(sorted(_MONTHS, key=len, reverse=True)) + r")\b\.?"
_DAY = r"(\d{1,2})(?:st|nd|rd|th)?\b"
_YEAR = r"(?:,?\s*(\d{4})\b)?"
_DAY_MONTH = re.compile(_DAY + r"\s*(?:of\s+)?" + _MONTH + _YEAR)
_MONTH_DAY = re.compile(_MONTH + r"\s+" + _DAY + _YEAR)
_MONTH_ONLY = re.compile(_MONTH + _YEAR)
_NUMERIC = re.compile(r"\b(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})\b")

_NOW_WORDS = re.compile(r"^(asap|now|immediate|immediately|straight away)$")
_AVAILABLE_CUE = re.compile(r"\b(?:available|vacant|free|ready)\b\s*(?:from|on|in|by)?\s*:?\s*")
_AVAILABLE_NOW = re.compile(
    r"\b(?:available|vacant)\s*(?:now|immediately)\b"
    r"|\bimmediately available\b"
    r"|\bready to move\b"
    r"|\bvacant\b"
)


def _day_label(value: date) -> str:
    return f"{value.day} {value:%b %Y}"


def _resolve(day: int | None, month: int, year: int | None, ref: date) -> date | None:
    """A written date as a calendar date. With no year, the first occurrence on or after `ref`."""
    try:
        if year:
            return date(year, month, day or 1)
        if day is None:
            # "December": this month still counts, so compare months, not days.
            next_year = (month, 1) < (ref.month, 1)
            return date(ref.year + next_year, month, 1)
        candidate = date(ref.year, month, day)
        return candidate if candidate >= ref else date(ref.year + 1, month, day)
    except ValueError:
        return None


def _find_date(text: str, ref: date, *, anchored: bool) -> date | None:
    """The first date written in `text` (at its start when anchored)."""
    find = (lambda p: p.match(text)) if anchored else (lambda p: p.search(text))
    if match := find(_NUMERIC):
        day, month, year = (int(g) for g in match.groups())
        return _resolve(day, month, year, ref)
    if match := find(_DAY_MONTH):
        day, month, year = match.groups()
        return _resolve(int(day), _MONTHS[month], int(year) if year else None, ref)
    if match := find(_MONTH_DAY):
        month, day, year = match.groups()
        return _resolve(int(day), _MONTHS[month], int(year) if year else None, ref)
    if match := find(_MONTH_ONLY):
        month, year = match.groups()
        return _resolve(None, _MONTHS[month], int(year) if year else None, ref)
    return None


def parse_move_in(value: Any, *, today: date) -> date | None:
    """The tenant's move-in date from the brief, or None when it cannot be read (no gate)."""
    if isinstance(value, date):
        return value
    text = str(value or "").strip().casefold()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        pass
    if _NOW_WORDS.match(text):
        return today
    return _find_date(text, today, anchored=False)


def available_from(description: str | None, *, listed: date) -> date | None:
    """When a listing's description says it is free: a date, `listed` for "now", else None."""
    text = (description or "").casefold()
    if not text:
        return None
    for cue in _AVAILABLE_CUE.finditer(text):
        if found := _find_date(text[cue.end() :], listed, anchored=True):
            return found
    return listed if _AVAILABLE_NOW.search(text) else None


def lease_timing(lease_end: date | None, move_in: date) -> tuple[Timing, str]:
    """In time when the lease ends on or before move-in; after it, the unit is disqualified."""
    if lease_end is None:
        return "unknown", "Lease end unknown, verify"
    verdict: Timing = "in_time" if lease_end <= move_in else "after"
    relation = "before" if verdict == "in_time" else "after"
    return verdict, f"Lease ends {_day_label(lease_end)}, {relation} move-in {_day_label(move_in)}"


def available_reason(available: date) -> str:
    return f"Available from {_day_label(available)}"


def stale_caveat(age_days: int | None, available: date | None, listed: date | None) -> str | None:
    """An old listing that says "available now" (or nothing) may already be let."""
    if age_days is None or age_days <= STALE_LISTING_DAYS:
        return None
    if available is not None and (listed is None or available > listed):
        return None
    return f"Listed {age_days} days ago, confirm it's still available"
