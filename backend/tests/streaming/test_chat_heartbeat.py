import asyncio

import pytest

from app.chat.events import with_heartbeat


async def test_slow_answer_sends_only_comments_until_validated_output_is_ready():
    release = asyncio.Event()

    async def response():
        await release.wait()
        yield 'data: {"type": "content", "content": "Validated answer"}\n\n'
        yield 'data: {"type": "done"}\n\n'

    stream = with_heartbeat(response(), interval=0.01)
    assert await anext(stream) == ": keep-alive\n\n"
    assert await anext(stream) == ": keep-alive\n\n"
    release.set()
    assert [item async for item in stream] == [
        'data: {"type": "content", "content": "Validated answer"}\n\n',
        'data: {"type": "done"}\n\n',
    ]


async def test_closing_at_a_heartbeat_cancels_and_awaits_provider_cleanup():
    cleaned_up = asyncio.Event()

    async def response():
        try:
            await asyncio.Event().wait()
            yield "unreachable"
        finally:
            await asyncio.sleep(0)
            cleaned_up.set()

    stream = with_heartbeat(response(), interval=0.01)
    assert await anext(stream) == ": keep-alive\n\n"
    await stream.aclose()
    assert cleaned_up.is_set()


async def test_disconnect_while_waiting_cancels_and_awaits_provider_cleanup():
    started, cleaned_up = asyncio.Event(), asyncio.Event()

    async def response():
        try:
            started.set()
            await asyncio.Event().wait()
            yield "unreachable"
        finally:
            cleaned_up.set()

    stream = with_heartbeat(response())
    task = asyncio.create_task(anext(stream))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert cleaned_up.is_set()


async def test_provider_failure_propagates_without_success_event():
    async def response():
        yield 'data: {"type": "thinking"}\n\n'
        raise RuntimeError("provider failed")

    stream = with_heartbeat(response())
    assert await anext(stream) == 'data: {"type": "thinking"}\n\n'
    with pytest.raises(RuntimeError, match="provider failed"):
        await anext(stream)
