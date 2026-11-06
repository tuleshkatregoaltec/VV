import logging


class CallbackQueryFilter(logging.Filter):
    """Meta verifies by query string; omit its token from Uvicorn access logs."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple) and len(record.args) == 5:
            client, method, path, version, status = record.args
            if isinstance(path, str) and path.split("?", 1)[0] == "/api/v1/webhooks/whatsapp":
                record.args = (client, method, path.split("?", 1)[0], version, status)
        return True
