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


def turn_stream_response(stream: AsyncGenerator[str, None], *, context: str):
    """An assistant turn as an SSE response: heartbeats while it works, and one safe error
    event (never the exception's text) if the turn itself fails unexpectedly."""
    from contextlib import aclosing

    from fastapi.responses import StreamingResponse

    from app.chat.errors import failure_event

    async def events():
        try:
            async with aclosing(with_heartbeat(stream)) as heartbeats:
                async for chunk in heartbeats:
                    yield chunk
        except Exception as error:
            yield encode_sse(failure_event(error, context=context))

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
