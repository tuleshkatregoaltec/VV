"""Anonymous read of one shared collection, addressed only by its bearer token.

Every response (200, 404, 429, 503) carries no-store / noindex / no-referrer headers, and the
token is redacted from uvicorn's access log.
"""

from __future__ import annotations

import logging
import re
import time
from threading import Lock

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlmodel.ext.asyncio.session import AsyncSession

from app.crm import collections as collection_service
from app.postgres import get_db_session

router = APIRouter(prefix="/api/v1/public/collections")

TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{43}$")
PUBLIC_HEADERS = {
    "Cache-Control": "private, no-store",
    "X-Robots-Tag": "noindex",
    "Referrer-Policy": "no-referrer",
}
RATE_LIMIT = 60
RATE_WINDOW_SECONDS = 60

_hits: dict[str, tuple[float, int]] = {}
_hits_lock = Lock()


def reset_rate_limit() -> None:
    with _hits_lock:
        _hits.clear()


def _allow(client: str) -> bool:
    """Fixed window per client IP; a per-replica floor, the ingress limit is the real one."""
    now = time.monotonic()
    with _hits_lock:
        started, count = _hits.get(client, (now, 0))
        if now - started >= RATE_WINDOW_SECONDS:
            started, count = now, 0
        if count >= RATE_LIMIT:
            _hits[client] = (started, count)
            return False
        _hits[client] = (started, count + 1)
        if len(_hits) > 10_000:  # drop expired windows so the table cannot grow without bound
            for key in [k for k, (s, _) in _hits.items() if now - s >= RATE_WINDOW_SECONDS]:
                del _hits[key]
        return True


def _reply(status: int, content) -> JSONResponse:
    return JSONResponse(content, status_code=status, headers=PUBLIC_HEADERS)


@router.get("/{token}")
async def public_collection(
    token: str, request: Request, db: AsyncSession = Depends(get_db_session)
) -> JSONResponse:
    if not _allow(request.client.host if request.client else "unknown"):
        return _reply(429, {"detail": "too_many_requests"})
    if not TOKEN_PATTERN.fullmatch(token):
        return _reply(404, {"detail": collection_service.COLLECTION_UNAVAILABLE})
    try:
        result = await collection_service.public_collection(db, token)
    except HTTPException as exc:
        return _reply(exc.status_code, {"detail": exc.detail})
    return _reply(200, jsonable_encoder(result))


_TOKEN_PATH = re.compile(r"/public/collections/[^\s/?\"']+")
_REDACTED = "/public/collections/[redacted]"


def _redact(value):
    return _TOKEN_PATH.sub(_REDACTED, value) if isinstance(value, str) else value


class RedactCollectionToken(logging.Filter):
    """Strip share tokens from access-log records (uvicorn puts the path in `record.args`)."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = _redact(record.msg)
        if isinstance(record.args, tuple):
            record.args = tuple(_redact(arg) for arg in record.args)
        elif isinstance(record.args, dict):
            record.args = {key: _redact(arg) for key, arg in record.args.items()}
        return True


logging.getLogger("uvicorn.access").addFilter(RedactCollectionToken())
