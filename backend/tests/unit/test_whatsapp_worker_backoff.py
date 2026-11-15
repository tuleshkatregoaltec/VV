"""Worker retry pressure: capped exponential backoff with jitter, reset on success."""

import asyncio

import pytest

from scripts import whatsapp_worker as worker


def test_backoff_doubles_then_caps():
    ceilings = [worker.retry_delay(n, jitter=lambda: 1.0) for n in range(1, 9)]
    assert ceilings[:4] == [2, 4, 8, 16]
    assert ceilings[-1] == worker.MAX_RETRY_SECONDS
    assert ceilings == sorted(ceilings)


def test_backoff_is_jittered_below_the_ceiling():
    assert worker.retry_delay(3, jitter=lambda: 0.0) == pytest.approx(4)
    assert worker.retry_delay(3, jitter=lambda: 0.5) == pytest.approx(6)


def test_backoff_survives_huge_failure_counts():
    assert worker.retry_delay(10_000, jitter=lambda: 1.0) == worker.MAX_RETRY_SECONDS


async def run_poll(outcomes, idle_seconds=0.5):
    """Feed poll() a scripted run(); return the delays it waited, in order."""
    stop = asyncio.Event()
    delays = []
    script = iter(outcomes)

    async def run():
        try:
            outcome = next(script)
        except StopIteration:
            stop.set()
            return True
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    async def wait(stop_event, delay):
        delays.append(delay)

    original = worker._wait
    worker._wait = wait
    try:
        await worker.poll(run, stop, idle_seconds=idle_seconds, jitter=lambda: 1.0)
    finally:
        worker._wait = original
    return delays


async def test_consecutive_failures_back_off_and_success_resets():
    boom = RuntimeError("db down")
    delays = await run_poll([boom, boom, boom, False, boom])
    assert delays == [2, 4, 8, 0.5, 2]


async def test_idle_polling_stays_responsive():
    assert await run_poll([False, False, False]) == [0.5, 0.5, 0.5]


async def test_busy_lane_does_not_wait_and_clears_failures():
    boom = RuntimeError("x")
    assert await run_poll([boom, True, boom]) == [2, 2]
