"""Public endpoint the calendar connector is called back on.

It carries no CRM session, so it lives outside the CRM router (whose every route
requires a subscription and a request lane):

Google sends the browser back to `/calendar/google/callback`. That request is not trusted to
  say whose sign-in it is, so nothing is exchanged here: the code and state are handed to the
  CRM page in the URL fragment (never sent to a server, never in access logs), and the signed-in
  page posts them to `/calendar/google/complete`, which checks the state belongs to that user.
"""

from __future__ import annotations

import logging
import re
from urllib.parse import urlencode

from fastapi import APIRouter
from fastapi.responses import RedirectResponse

from app.config import settings

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


# Google's one-time code/state arrive in the query string; keep them out of uvicorn's access log.
_SECRET_PARAM = re.compile(r"([?&](?:code|state)=)[^&\s\"']*")


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
