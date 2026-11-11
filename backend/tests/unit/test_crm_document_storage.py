from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest

from app import config
from app.core.object_storage import ObjectStorageClient
from app.crm import document_storage

DOC_ID = UUID("00000000-0000-0000-0000-000000000001")


class FakeS3:
    def __init__(self):
        self.calls: list[dict] = []

    async def put_object(self, **kwargs):
        self.calls.append(kwargs)


def fake_client(monkeypatch, storage: ObjectStorageClient) -> FakeS3:
    s3 = FakeS3()

    @asynccontextmanager
    async def client():
        yield s3

    monkeypatch.setattr(storage, "client", client)
    return s3


async def test_upload_without_metadata_is_unchanged(monkeypatch):
    # Existing callers (chunk uploads, import drop logs) pass only a key and bytes.
    storage = ObjectStorageClient(None, "key", "secret", "bucket")
    s3 = fake_client(monkeypatch, storage)
    await storage.upload("a/b.json", b"{}")
    assert s3.calls == [{"Bucket": "bucket", "Key": "a/b.json", "Body": b"{}"}]


async def test_pdf_is_stored_privately_per_organization_as_an_attachment(monkeypatch):
    storage = ObjectStorageClient(None, "key", "secret", "bucket")
    s3 = fake_client(monkeypatch, storage)
    monkeypatch.setattr(document_storage, "_storage", lambda: storage)

    key = await document_storage.store_pdf("org-1", DOC_ID, "noc-123.pdf", b"%PDF-1.7")

    assert key == f"crm-documents/org-1/{DOC_ID}.pdf"
    assert s3.calls[0]["ContentType"] == "application/pdf"
    assert s3.calls[0]["ContentDisposition"] == 'attachment; filename="noc-123.pdf"'


async def test_download_filename_cannot_break_the_header(monkeypatch):
    storage = ObjectStorageClient(None, "key", "secret", "bucket")
    s3 = fake_client(monkeypatch, storage)
    monkeypatch.setattr(document_storage, "_storage", lambda: storage)

    await document_storage.store_pdf("org-1", DOC_ID, 'x"\r\nSet-Cookie: a.pdf', b"%PDF")

    disposition = s3.calls[0]["ContentDisposition"]
    assert "\r" not in disposition and "\n" not in disposition
    assert disposition.count('"') == 2


def test_client_without_static_keys_uses_the_default_credential_chain():
    # Production containers authenticate with their task role, not stored keys.
    storage = ObjectStorageClient(None, None, None, "bucket", region="me-central-1")
    assert "aws_access_key_id" not in storage.client_kwargs
    assert "aws_secret_access_key" not in storage.client_kwargs


def test_signing_kwargs_omit_keys_when_none_are_configured(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)  # env_value also reads .env.dev from the working directory
    for name in ("OBJECT_STORAGE_ACCESS_KEY_ID", "OBJECT_STORAGE_SECRET_ACCESS_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("OBJECT_STORAGE_REGION", "me-central-1")
    monkeypatch.delenv("OBJECT_STORAGE_ENDPOINT_URL", raising=False)
    assert config.build_object_storage_client_kwargs() == {"region_name": "me-central-1"}


def test_signing_kwargs_keep_local_minio_keys(monkeypatch):
    monkeypatch.setenv("OBJECT_STORAGE_ACCESS_KEY_ID", "minio")
    monkeypatch.setenv("OBJECT_STORAGE_SECRET_ACCESS_KEY", "minio-secret")
    kwargs = config.build_object_storage_client_kwargs()
    assert (kwargs["aws_access_key_id"], kwargs["aws_secret_access_key"]) == (
        "minio",
        "minio-secret",
    )


async def test_download_links_last_five_minutes(monkeypatch):
    seen = {}

    async def fake_sign(*, bucket, key, expires_in, client_kwargs):
        seen.update(bucket=bucket, key=key, expires_in=expires_in)
        return "https://storage.example/signed"

    monkeypatch.setattr(document_storage, "sign_object_url", fake_sign)
    monkeypatch.setattr(document_storage, "build_object_storage_client_kwargs", lambda: {})
    before = datetime.now(timezone.utc)

    url, expires_at = await document_storage.signed_pdf_url("crm-documents/org-1/x.pdf")

    assert url == "https://storage.example/signed"
    assert (seen["key"], seen["expires_in"]) == ("crm-documents/org-1/x.pdf", 300)
    assert timedelta(seconds=299) <= expires_at - before <= timedelta(seconds=301)


@pytest.fixture(autouse=True)
def _bucket(monkeypatch):
    monkeypatch.setattr(document_storage.settings, "OBJECT_STORAGE_BUCKET", "bucket")
