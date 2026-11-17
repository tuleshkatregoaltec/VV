"""Private storage for generated document PDFs and their short-lived download links.

A signed link is a bearer credential: it is never logged or cached, and it is issued only after
the caller's access to the document record has been checked.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from uuid import UUID

from app.config import build_object_storage_client_kwargs, settings
from app.core.object_storage import ObjectStorageClient, sign_object_url

DOWNLOAD_TTL_SECONDS = 300
_UNSAFE_FILENAME = re.compile(r"[^A-Za-z0-9._-]+")


@lru_cache(maxsize=1)
def _storage() -> ObjectStorageClient:
    return ObjectStorageClient(
        endpoint_url=(
            str(settings.OBJECT_STORAGE_ENDPOINT_URL)
            if settings.OBJECT_STORAGE_ENDPOINT_URL
            else None
        ),
        access_key_id=settings.OBJECT_STORAGE_ACCESS_KEY_ID,
        secret_access_key=settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
        bucket_name=settings.OBJECT_STORAGE_BUCKET,
        region=settings.OBJECT_STORAGE_REGION,
        use_path_style=settings.OBJECT_STORAGE_USE_PATH_STYLE,
    )


def document_key(organization_id: str, document_id: UUID) -> str:
    return f"crm-documents/{organization_id}/{document_id}.pdf"


async def store_pdf(organization_id: str, document_id: UUID, filename: str, data: bytes) -> str:
    """Upload one PDF under the organization's private prefix; returns its object key."""
    key = document_key(organization_id, document_id)
    safe_name = _UNSAFE_FILENAME.sub("-", filename).strip("-") or "document.pdf"
    await _storage().upload(
        key,
        data,
        content_type="application/pdf",
        content_disposition=f'attachment; filename="{safe_name}"',
    )
    return key


async def signed_pdf_url(object_key: str, *, inline: bool = False) -> tuple[str, datetime]:
    """A short-lived link; `inline` opens the PDF in the browser (preview) instead of saving it."""
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=DOWNLOAD_TTL_SECONDS)
    url = await sign_object_url(
        bucket=settings.OBJECT_STORAGE_BUCKET,
        key=object_key,
        expires_in=DOWNLOAD_TTL_SECONDS,
        client_kwargs=build_object_storage_client_kwargs(),
        response_content_disposition="inline" if inline else None,
    )
    return url, expires_at
