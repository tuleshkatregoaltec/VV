import asyncio
import logging.config

from app.core.logging_config import LOGGING_CONFIG
from app.whatsapp.automation import run_once
from app.whatsapp.customer_automation import run_customer_once
from app.whatsapp.customer_connections import bootstrap_on_startup


async def poll(run, *, idle_seconds=2):
    while True:
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
            await asyncio.sleep(delay)


async def main():
    logging.config.dictConfig(LOGGING_CONFIG)
    await bootstrap_on_startup()
    # Classification runs in the API process from in-memory text (nothing unclassified
    # is persisted). These lanes deliver due replies for every agent and recover
    # receipts whose classifier died; send locks guarantee a single outbound attempt.
    await asyncio.gather(
        poll(run_once),
        poll(run_customer_once, idle_seconds=0.5),
        poll(run_customer_once, idle_seconds=0.5),
    )


if __name__ == "__main__":
    asyncio.run(main())
