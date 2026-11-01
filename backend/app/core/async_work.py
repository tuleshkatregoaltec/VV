"""Keep caller admission until an abandoned blocking operation actually finishes."""

import asyncio
from collections.abc import Callable
from typing import ParamSpec, TypeVar

P = ParamSpec("P")
T = TypeVar("T")


async def run_in_thread(function: Callable[P, T], *args: P.args, **kwargs: P.kwargs) -> T:
    """Cancellation cannot kill a thread; drain it before releasing caller resources."""
    task = asyncio.create_task(asyncio.to_thread(function, *args, **kwargs))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        # A second cancellation must not orphan the still-allocating worker either.
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                continue
            except Exception:
                break
        if task.done() and not task.cancelled():
            task.exception()  # Retrieve any worker exception while preserving cancellation.
        raise
