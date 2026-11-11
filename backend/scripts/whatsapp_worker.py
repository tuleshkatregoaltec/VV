import asyncio
import contextlib
import logging.config
import signal

from app.core.logging_config import LOGGING_CONFIG
from app.whatsapp.automation import run_once
from app.whatsapp.customer_automation import run_customer_once
from app.whatsapp.customer_connections import bootstrap_on_startup

# Below systemd's default 90-second stop timeout. An iteration still running after this is
# cancelled; an interrupted send is recovered as "unknown", never resent.
SHUTDOWN_GRACE_SECONDS = 60


async def poll(run, stop, *, idle_seconds=2):
    while not stop.is_set():
        delay = idle_seconds
        try:
            processed = await run()
        except Exception as exc:
            logging.getLogger(__name__).error(
                "WhatsApp worker iteration failed (%s)", type(exc).__name__
            )
            processed = False
            delay = 2  # Do not increase retry pressure when infrastructure fails.
        if not processed:
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), delay)


async def serve(runs, *, grace=SHUTDOWN_GRACE_SECONDS):
    """Run the lanes until SIGTERM/SIGINT, then let in-flight iterations finish and return,
    so a systemd stop or restart exits 0 instead of being recorded as a failure."""
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    lanes = [asyncio.create_task(poll(run, stop, idle_seconds=idle)) for run, idle in runs]
    await stop.wait()
    logging.getLogger(__name__).info("WhatsApp worker stopping")
    _, pending = await asyncio.wait(lanes, timeout=grace)
    for lane in pending:
        lane.cancel()
    await asyncio.gather(*pending, return_exceptions=True)


async def main():
    logging.config.dictConfig(LOGGING_CONFIG)
    await bootstrap_on_startup()
    # Classification runs in the API process from in-memory text (nothing unclassified
    # is persisted). These lanes deliver due replies for every agent and recover
    # receipts whose classifier died; send locks guarantee a single outbound attempt.
    await serve([(run_once, 2), (run_customer_once, 0.5), (run_customer_once, 0.5)])


if __name__ == "__main__":
    asyncio.run(main())
