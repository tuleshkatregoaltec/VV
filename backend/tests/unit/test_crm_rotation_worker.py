"""The rotation worker loop: it keeps going after failures, stops cleanly, and reports."""

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from scripts.crm import advance_lead_rotations as worker


def _factory():
    @asynccontextmanager
    async def session():
        yield object()

    return session


async def _run(outcomes, *, interval=0.01, heartbeat=None):
    """Run the loop through `outcomes` (dicts or exceptions), then stop it."""
    stop = asyncio.Event()
    reports: list[str] = []
    runs = 0

    async def fake_advance(db, *, limit, should_stop):
        nonlocal runs
        runs += 1
        outcome = outcomes[min(runs, len(outcomes)) - 1]
        if runs >= len(outcomes):
            stop.set()
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    with patch.object(worker, "advance_due", fake_advance):
        await asyncio.wait_for(
            worker.run_forever(
                _factory(), stop=stop, interval=interval, heartbeat=heartbeat, report=reports.append
            ),
            timeout=5,
        )
    return runs, reports


@pytest.mark.asyncio
async def test_a_failed_run_is_reported_and_the_worker_carries_on(tmp_path):
    # A database outage mid-run must not kill the worker: the next minute retries.
    heartbeat = tmp_path / "beat"
    runs, reports = await _run(
        [{"rotated": 1}, RuntimeError("db down"), {"rotated": 1, "failed": 2}, {}],
        heartbeat=heartbeat,
    )
    assert runs == 4
    assert reports == [
        "CRM lead rotation run failed",
        "CRM lead rotation: 2 lead(s) failed and will be retried",
    ]
    assert heartbeat.exists()  # touched by the runs that reached the database


@pytest.mark.asyncio
async def test_the_heartbeat_is_not_touched_when_the_run_fails(tmp_path):
    heartbeat = tmp_path / "beat"
    await _run([RuntimeError("db down")], heartbeat=heartbeat)
    assert not heartbeat.exists()  # the container health check then fails, as it should


@pytest.mark.asyncio
async def test_a_full_batch_is_followed_at_once_but_failures_wait_for_the_interval():
    # 500 moved: more may be due, go again now. 500 failed: waiting avoids a hot error loop.
    runs, _ = await _run([{"rotated": worker.BATCH}, {"rotated": 1}], interval=30)
    assert runs == 2  # the second run came without waiting 30 s (the test has a 5 s cap)
    started = asyncio.get_running_loop().time()
    runs, _ = await _run([{"failed": worker.BATCH}, {}], interval=0.2)
    assert runs == 2 and asyncio.get_running_loop().time() - started >= 0.2


@pytest.mark.asyncio
async def test_stop_ends_the_wait_immediately():
    stop = asyncio.Event()

    async def fake_advance(db, *, limit, should_stop):
        return {}

    with patch.object(worker, "advance_due", fake_advance):
        task = asyncio.create_task(
            worker.run_forever(_factory(), stop=stop, interval=3600, heartbeat=None)
        )
        await asyncio.sleep(0.05)
        stop.set()
        await asyncio.wait_for(task, timeout=1)  # SIGTERM does not wait out the hour


@pytest.mark.asyncio
async def test_busy_leads_wait_instead_of_spinning():
    started = asyncio.get_running_loop().time()
    runs, _ = await _run([{"busy": worker.BATCH}, {}], interval=0.2)
    assert runs == 2 and asyncio.get_running_loop().time() - started >= 0.2


@pytest.mark.asyncio
async def test_a_broken_alert_transport_does_not_kill_the_worker():
    stop = asyncio.Event()
    runs = 0

    async def advance(db, *, limit, should_stop):
        nonlocal runs
        runs += 1
        if runs == 2:
            stop.set()
            return {}
        raise RuntimeError("database unavailable")

    def broken_report(message):
        raise RuntimeError("alert transport unavailable")

    with patch.object(worker, "advance_due", advance):
        await asyncio.wait_for(
            worker.run_forever(_factory(), stop=stop, interval=0.01, report=broken_report),
            timeout=1,
        )
    assert runs == 2


@pytest.mark.parametrize(
    "age,healthy", [(0, True), (179, True), (180, False), (360, False), (-10, False)]
)
def test_health_checks_detect_missing_stale_and_future_heartbeats(tmp_path, age, healthy):
    heartbeat = tmp_path / "beat"
    assert not worker.heartbeat_healthy(heartbeat)
    heartbeat.touch()
    assert worker.heartbeat_healthy(heartbeat, now=heartbeat.stat().st_mtime + age) is healthy


@pytest.mark.asyncio
async def test_sigterm_finishes_only_the_current_lead(monkeypatch):
    from app.crm import rotation

    stop = asyncio.Event()
    db = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())
    monkeypatch.setattr(
        rotation.routing_repository, "due_rotation_enquiry_ids", AsyncMock(return_value=[1, 2])
    )
    moved = []

    async def advance(db, lead_id, now):
        moved.append(lead_id)
        stop.set()
        return "rotated"

    monkeypatch.setattr(rotation, "_advance_one", advance)
    assert await rotation.advance_due(db, should_stop=stop.is_set) == {"rotated": 1}
    assert moved == [1]
    db.commit.assert_awaited_once()
