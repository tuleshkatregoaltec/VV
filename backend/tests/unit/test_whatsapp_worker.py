"""The worker stops cleanly on SIGTERM: systemd stop/restart must not record a failure,
and a reply already being sent finishes instead of being cut off mid-send."""

import asyncio
import os
import signal
import subprocess
import sys
import textwrap
from pathlib import Path

from scripts import whatsapp_worker as worker

BACKEND = Path(__file__).resolve().parents[2]


async def test_idle_lane_stops_promptly_when_asked():
    stop = asyncio.Event()
    calls = []

    async def run():
        calls.append(1)
        return False

    lane = asyncio.create_task(worker.poll(run, stop, idle_seconds=30))
    await asyncio.sleep(0.05)
    stop.set()
    await asyncio.wait_for(lane, 1)
    assert calls == [1]


def test_sigterm_finishes_the_current_iteration_and_exits_zero():
    script = textwrap.dedent(
        """
        import asyncio, sys
        from scripts import whatsapp_worker as worker

        async def run():
            print("started", flush=True)
            await asyncio.sleep(0.5)  # a send in flight
            print("finished", flush=True)
            return True

        asyncio.run(worker.serve([(run, 0.5)], grace=5))
        print("stopped", flush=True)
        """
    )
    process = subprocess.Popen(
        [sys.executable, "-c", script],
        cwd=BACKEND,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=os.environ.copy(),
    )
    assert process.stdout.readline().strip() == "started", process.stderr.read()
    process.send_signal(signal.SIGTERM)
    out, err = process.communicate(timeout=20)
    assert process.returncode == 0, err
    assert out.split() == ["finished", "stopped"]
