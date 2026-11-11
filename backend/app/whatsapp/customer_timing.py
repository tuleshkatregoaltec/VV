"""Human-paced reply timing. Pure functions; every delay is bounded and jittered.

Sequence for one automatic reply: wait a reading delay, mark the buyer's message read and
show Meta's typing indicator (it lasts at most 25 seconds, or until we reply), wait a typing
delay scaled to the reply length, then send. Delays are skipped when they would crowd the
24-hour customer-service window.
"""

import random
from datetime import datetime, timedelta

WINDOW = timedelta(hours=24)
WINDOW_MARGIN = timedelta(minutes=3)
INDICATOR_SECONDS = 25  # Meta dismisses the typing indicator after 25 seconds.
MIN_READING, MAX_READING = 4.0, 20.0
MIN_TYPING, MAX_TYPING = 3.0, 18.0
MIN_GAP, MAX_GAP = 1.5, 5.0
_WORST_CASE = timedelta(seconds=MAX_READING + MAX_TYPING + MAX_GAP)


def _bounded(base: float, low: float, high: float, rng, spread=(0.7, 1.4)) -> float:
    return min(high, max(low, base * rng.uniform(*spread)))


def reading_delay(inbound_chars: int, rng=random) -> float:
    return _bounded(3.0 + 0.02 * inbound_chars, MIN_READING, MAX_READING, rng, (0.8, 1.6))


def typing_delay(reply_chars: int, rng=random) -> float:
    return _bounded(2.0 + 0.07 * reply_chars, MIN_TYPING, MAX_TYPING, rng)


def split_gap(next_chars: int, rng=random) -> float:
    return _bounded(1.0 + 0.02 * next_chars, MIN_GAP, MAX_GAP, rng)


def fits_window(now: datetime, sent_at: datetime) -> bool:
    return now + _WORST_CASE + WINDOW_MARGIN < sent_at + WINDOW


def reading_due(now, sent_at, inbound_chars, *, enabled=True, rng=random) -> datetime:
    if not enabled or not fits_window(now, sent_at):
        return now
    return now + timedelta(seconds=reading_delay(inbound_chars, rng))


def typing_due(now, sent_at, reply_chars, *, rng=random) -> datetime:
    if not fits_window(now, sent_at):
        return now
    return now + timedelta(seconds=typing_delay(reply_chars, rng))
