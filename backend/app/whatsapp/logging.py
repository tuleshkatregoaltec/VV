import logging

from honeybadger import honeybadger

from app.config import settings

WEBHOOK_PATH = "/api/v1/webhooks/whatsapp"
logger = logging.getLogger(__name__)


class CallbackQueryFilter(logging.Filter):
    """Meta verifies by query string; omit its token from Uvicorn access logs."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple) and len(record.args) == 5:
            client, method, path, version, status = record.args
            if isinstance(path, str) and path.split("?", 1)[0] == WEBHOOK_PATH:
                record.args = (client, method, path.split("?", 1)[0], version, status)
        return True


def scrub_notice(notice):
    """Honeybadger `before_notify` hook: a failed webhook request reports only where and what
    class of error. Request headers and query string (verify token, signature), any body,
    and exception messages or causes (which can echo SQL parameters or customer text) are
    withheld."""
    context = getattr(notice, "context", None) or {}
    if WEBHOOK_PATH not in str(context.get("url", "")):
        return notice
    notice.context = {key: context[key] for key in ("method", "url") if key in context}
    exception = notice.exception
    error_class = (
        exception.get("error_class") if isinstance(exception, dict) else type(exception).__name__
    )
    notice.error_class = error_class
    notice.error_message = "WhatsApp webhook request failed (details withheld)"
    notice.exception = {"error_class": error_class, "error_message": notice.error_message}
    return notice


def report_failure(exc: Exception) -> None:
    """Alert on an unexpected webhook failure without any of its content."""
    if settings.honeybadger_enabled:
        honeybadger.notify(
            error_class=type(exc).__name__,
            error_message="WhatsApp webhook processing failed",
        )
