from urllib.parse import urlparse
from uuid import uuid4

import httpx

from app.config import settings
from app.core.object_storage import ObjectStorageClient
from app.crm import document_storage


async def test_pdf_round_trips_through_a_signed_link_on_real_minio(monkeypatch):
    endpoint = str(settings.OBJECT_STORAGE_ENDPOINT_URL)
    assert urlparse(endpoint).hostname in {"localhost", "127.0.0.1", "::1"}
    bucket = "vv-migration-test-" + uuid4().hex
    storage = ObjectStorageClient(
        endpoint,
        settings.OBJECT_STORAGE_ACCESS_KEY_ID,
        settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
        bucket,
        settings.OBJECT_STORAGE_REGION,
        settings.OBJECT_STORAGE_USE_PATH_STYLE,
    )
    async with storage.client() as s3:
        await s3.create_bucket(Bucket=bucket)
    monkeypatch.setattr(document_storage, "_storage", lambda: storage)
    monkeypatch.setattr(document_storage.settings, "OBJECT_STORAGE_BUCKET", bucket)
    document_id = uuid4()
    key = None
    try:
        key = await document_storage.store_pdf("org-1", document_id, "noc-123.pdf", b"%PDF-1.7")
        url, _ = await document_storage.signed_pdf_url(key)
        async with httpx.AsyncClient() as http:
            response = await http.get(url)
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/pdf"
        assert 'filename="noc-123.pdf"' in response.headers["content-disposition"]
        assert response.content == b"%PDF-1.7"
    finally:
        async with storage.client() as s3:
            if key:
                await s3.delete_object(Bucket=bucket, Key=key)
            await s3.delete_bucket(Bucket=bucket)
