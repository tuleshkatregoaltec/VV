import random
from datetime import datetime, timedelta, timezone

from app.whatsapp import customer_timing as timing

NOW = datetime(2026, 11, 6, 12, 0, tzinfo=timezone.utc)


def test_delays_are_bounded_and_scale_with_length():
    rng = random.Random(7)
    short = [timing.typing_delay(20, rng) for _ in range(200)]
    long_ = [timing.typing_delay(600, rng) for _ in range(200)]
    assert all(timing.MIN_TYPING <= value <= timing.MAX_TYPING for value in short + long_)
    assert sum(long_) / 200 > sum(short) / 200 + 3
    reading = [timing.reading_delay(n, rng) for n in (1, 40, 4000) for _ in range(100)]
    assert all(timing.MIN_READING <= value <= timing.MAX_READING for value in reading)
    gaps = [timing.split_gap(300, rng) for _ in range(100)]
    assert all(timing.MIN_GAP <= value <= timing.MAX_GAP for value in gaps)


def test_delays_are_jittered_not_constant():
    rng = random.Random(3)
    assert len({round(timing.typing_delay(120, rng), 2) for _ in range(30)}) > 10


def test_typing_never_outlasts_the_meta_indicator():
    assert timing.MAX_TYPING < timing.INDICATOR_SECONDS == 25
    assert timing.MAX_GAP < timing.INDICATOR_SECONDS


def test_humanizing_stops_near_the_24_hour_window_edge():
    assert timing.fits_window(NOW, NOW - timedelta(hours=1))
    assert timing.fits_window(NOW, NOW - timedelta(hours=23, minutes=50))
    assert not timing.fits_window(NOW, NOW - timedelta(hours=23, minutes=58))
    assert not timing.fits_window(NOW, NOW - timedelta(hours=24, seconds=1))


def test_reading_schedule_respects_toggle_and_window():
    rng = random.Random(1)
    due = timing.reading_due(NOW, NOW - timedelta(minutes=1), 40, enabled=True, rng=rng)
    assert (
        NOW + timedelta(seconds=timing.MIN_READING)
        <= due
        <= NOW + timedelta(seconds=timing.MAX_READING)
    )
    assert timing.reading_due(NOW, NOW, 40, enabled=False) == NOW
    assert timing.reading_due(NOW, NOW - timedelta(hours=23, minutes=59), 40, enabled=True) == NOW


def test_typing_schedule_respects_toggle_and_window():
    rng = random.Random(1)
    due = timing.typing_due(NOW, NOW - timedelta(minutes=1), 120, rng=rng)
    assert (
        NOW + timedelta(seconds=timing.MIN_TYPING)
        <= due
        <= NOW + timedelta(seconds=timing.MAX_TYPING)
    )
    assert timing.typing_due(NOW, NOW - timedelta(hours=23, minutes=59), 120) == NOW
