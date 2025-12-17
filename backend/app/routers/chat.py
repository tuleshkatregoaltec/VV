from fastapi import APIRouter, Query, Depends
from fastapi.responses import StreamingResponse
import logging
from sqlmodel.ext.asyncio.session import AsyncSession
import json
from openai import AsyncOpenAI


from backend.app.db.session import get_db_session
from backend.app.routers.dependencies import require_auth
from backend.app.schemas.chat import ChatMessageResponse
from backend.app.services.chat_service import *
from backend.app.config import settings

router = APIRouter(
    prefix="/api/v1/chat",
    tags=["chat"],
)

logger = logging.getLogger(__name__)

# We'll create an async client per-request so streaming works cleanly
OPENROUTER_BASE = "https://openrouter.ai/api/v1"

@router.get("/response")
async def chat_response(prompt: str = Query(default="What is your name?")):
  """Stream a model response as SSE (`text/event-stream`)."""

  async def event_stream():
    yield "data: [connected]\n\n"
    logger.info("SSE connection opened for prompt=%s", prompt)

    async def _sse_yield_text(text: str):
      if text is None:
        return
      for line in str(text).splitlines() or [""]:
        yield f"data: {line}\n"
      yield "\n"

    def _get(obj, key):
      try:
        return obj.get(key)
      except Exception:
        return getattr(obj, key, None)

    def _extract_text_event(event) -> str | None:
      etype = _get(event, "type")
      if not etype:
        return None

      if etype in ("response.output_text.delta", "response.output_text", "response.output_text.done"):
        return _get(event, "delta") or _get(event, "text") or _get(event, "snapshot")

      if etype in ("response.content_part.done", "response.content_part.added"):
        part = _get(event, "part")
        if part is None:
          return None
        try:
          return part.get("text")
        except Exception:
          return getattr(part, "text", None) or str(part)

      return None

    async def _iter_stream(it):
      if hasattr(it, "__aenter__"):
        async with it as stream:
          async for ev in stream:
            yield ev
      else:
        async for ev in it:
          yield ev

    try:
      async with AsyncOpenAI(base_url=OPENROUTER_BASE, api_key=settings.OPENROUTER_API_KEY) as async_client:
        stream_func = getattr(async_client.responses, "stream", None)
        if stream_func:
          stream_iter = stream_func(model="amazon/nova-2-lite-v1:free", input=prompt)
        else:
          stream_iter = async_client.responses.create(model="amazon/nova-2-lite-v1:free", input=prompt, stream=True)

        async for event in _iter_stream(stream_iter):
          logger.debug("stream event: %s", repr(event))
          text = _extract_text_event(event)
          if not text:
            continue
          async for s in _sse_yield_text(text):
            yield s

    except Exception as exc:
      logger.exception("Error while streaming model response")
      for line in str(exc).splitlines() or [""]:
        yield f"event: error\ndata: {line}\n"
      yield "\n"

  headers = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
  return StreamingResponse(event_stream(), media_type="text/event-stream", headers=headers)