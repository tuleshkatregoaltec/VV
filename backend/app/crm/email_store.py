"""Connectors › Email storage: one local JSON file instead of database tables.

Sends, templates and received emails are kept in `CRM_EMAIL_STORE_PATH` (default
`backend/data/crm_email_store.json`, git-ignored). Writes go to a temporary file first and then
replace the store, so a crash mid-write never leaves half a file.

Local and single-process only: one lock guards it inside this process, so run one backend worker.
Moving to Postgres later means swapping this module for tables; the rest of the pipeline reads and
writes `EmailStoreData` and does not change.
"""

import asyncio
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from app.config import settings
from app.crm.email_models import EmailStoreData

DEFAULT_PATH = Path(__file__).resolve().parents[2] / "data" / "crm_email_store.json"

_lock = asyncio.Lock()


def store_path() -> Path:
    return Path(settings.CRM_EMAIL_STORE_PATH) if settings.CRM_EMAIL_STORE_PATH else DEFAULT_PATH


def _load(path: Path) -> EmailStoreData:
    if not path.exists():
        return EmailStoreData()
    return EmailStoreData.model_validate_json(path.read_text(encoding="utf-8") or "{}")


def _save(path: Path, data: EmailStoreData) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(data.model_dump_json(indent=2), encoding="utf-8")
    os.replace(tmp, path)


async def read() -> EmailStoreData:
    """A snapshot to read from; changes to it are not saved."""
    async with _lock:
        return _load(store_path())


@asynccontextmanager
async def edit() -> AsyncIterator[EmailStoreData]:
    """Load, change and save under the lock. Nothing is saved if the block raises."""
    async with _lock:
        path = store_path()
        data = _load(path)
        yield data
        _save(path, data)
