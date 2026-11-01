import asyncio
import json
from collections.abc import AsyncGenerator
from typing import Any


def encode_sse(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, default=str)}\n\n"


async def with_heartbeat(
    stream: AsyncGenerator[str, None], *, interval: float = 15
) -> AsyncGenerator[str, None]:
    """Keep buffered turns alive without exposing unvalidated model output."""
    pending = asyncio.create_task(anext(stream))
    try:
        while True:
            done, _ = await asyncio.wait({pending}, timeout=interval)
            if not done:
                yield ": keep-alive\n\n"
                continue
            try:
                chunk = pending.result()
            except StopAsyncIteration:
                return
            yield chunk
            pending = asyncio.create_task(anext(stream))
    finally:
        # Closing the HTTP stream must cancel provider work and settle its lease
        # before the request-scoped database session is released.
        pending.cancel()
        await asyncio.gather(pending, return_exceptions=True)
        await stream.aclose()
