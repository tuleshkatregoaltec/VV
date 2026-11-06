"""Run connectivity checks without exposing a public message-sending endpoint."""

import argparse
import asyncio
import json

import httpx

from app.config import settings
from app.whatsapp.service import readiness, send_test_template


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["status", "send-test"])
    args = parser.parse_args()
    if args.command == "status":
        print(json.dumps(readiness(settings), indent=2))
        return
    try:
        await send_test_template(settings)
    except (ValueError, httpx.HTTPError):
        # HTTP exceptions can include request URLs or provider-supplied details.
        print("Test not confirmed. Check configuration, recipient eligibility and Meta dashboard.")
        raise SystemExit(1) from None
    print("Meta accepted the configured test template. Check WhatsApp for delivery.")
    if settings.WHATSAPP_APP_SECRET:
        print("Send a message back; backend.log records signed inbound event counts only.")
    else:
        print(
            "Incoming webhook reception still requires WHATSAPP_APP_SECRET and a backend restart."
        )


if __name__ == "__main__":
    asyncio.run(main())
