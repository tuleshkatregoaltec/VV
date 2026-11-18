"""Public endpoints the calendar and email connectors are called back on.

None of these carry a CRM session, so they live outside the CRM router (whose every route
requires a subscription and a request lane):

- Google sends the browser back to `/calendar/google/callback`. That request is not trusted to
  say whose sign-in it is, so nothing is exchanged here: the code and state are handed to the
  CRM page in the URL fragment (never sent to a server, never in access logs), and the signed-in
  page posts them to `/calendar/google/complete`, which checks the state belongs to that user.
- Brevo posts delivery events and inbound mail; the shared secret in the query string is the gate.
"""

from __future__ import annotations

import logging
import re
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from sqlmodel.ext.asyncio.session import AsyncSession

from app.config import settings
from app.crm.email_pipeline import receive_inbound, receive_webhook
from app.postgres import get_db_session

router = APIRouter(prefix="/api/v1/crm")

# Google's authorization codes are well under this; anything longer is not one.
_MAX_PARAM = 2048


def _calendar_page(fragment: dict[str, str]) -> RedirectResponse:
    base = f"{str(settings.FRONTEND_URL).rstrip('/')}/crm/calendar"
    response = RedirectResponse(f"{base}#{urlencode(fragment)}", status_code=303)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


@router.get("/calendar/google/callback", include_in_schema=False)
async def crm_google_calendar_callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
):
    if error or not code or not state or len(code) > _MAX_PARAM or len(state) > _MAX_PARAM:
        return _calendar_page({"google_calendar": "error"})
    return _calendar_page({"google_code": code, "google_state": state})


async def _json(request: Request):
    try:
        return await request.json()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid JSON") from None


@router.post("/email/brevo-webhook", include_in_schema=False)
async def crm_brevo_webhook(request: Request, secret: str | None = Query(default=None)):
    """Brevo pushes delivery events here."""
    applied = await receive_webhook(secret=secret, payload=await _json(request))
    return {"ok": True, "applied": applied}


@router.post("/email/brevo-inbound", include_in_schema=False)
async def crm_brevo_inbound(
    request: Request,
    secret: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db_session),
):
    """Brevo inbound parsing posts received emails here."""
    stored = await receive_inbound(db, secret=secret, payload=await _json(request))
    return {"ok": True, "stored": stored}


# Webhook secrets and Google's one-time code/state arrive in the query string; keep them out of
# uvicorn's access log.
_SECRET_PARAM = re.compile(r"([?&](?:secret|code|state)=)[^&\s\"']*")


def _redact(value):
    return _SECRET_PARAM.sub(r"\1[redacted]", value) if isinstance(value, str) else value


class RedactConnectorSecrets(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = _redact(record.msg)
        if isinstance(record.args, tuple):
            record.args = tuple(_redact(arg) for arg in record.args)
        elif isinstance(record.args, dict):
            record.args = {key: _redact(arg) for key, arg in record.args.items()}
        return True


logging.getLogger("uvicorn.access").addFilter(RedactConnectorSecrets())
