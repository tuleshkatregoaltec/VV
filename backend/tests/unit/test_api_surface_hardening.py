"""API-surface hardening: docs exposure, auth errors, upload health and chunk limits."""

import io
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException, UploadFile

from app.config import settings
from app.core.dependencies import require_api_key
from app.main import docs_urls_for
from app.upload import service

API_KEY = settings.SERVICE_API_KEY


# 1. Interactive docs / schema are local-only -------------------------------------------------


@pytest.mark.parametrize("environment", ["staging", "production"])
def test_docs_and_schema_are_disabled_outside_local(environment):
    assert docs_urls_for(environment) == {
        "docs_url": None,
        "redoc_url": None,
        "openapi_url": None,
    }


def test_docs_and_schema_stay_available_locally():
    urls = docs_urls_for("local")
    assert urls["docs_url"] == "/docs"
    assert urls["redoc_url"] == "/redoc"
    assert urls["openapi_url"] == "/openapi.json"


async def test_running_app_serves_docs_only_when_environment_is_local(client_no_auth):
    expected = 200 if settings.ENVIRONMENT == "local" else 404
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert (await client_no_auth.get(path)).status_code == expected


# 4. Malformed / invalid bearer tokens ---------------------------------------------------------


@pytest.mark.parametrize("header", ["Bearer abc.def.ghi", "Bearer", "Bearer a b"])
async def test_bad_authorization_header_is_a_json_401(client_no_auth, monkeypatch, header):
    monkeypatch.setattr("app.providers.auth.auth_backend.verify_user", AsyncMock(return_value=None))
    response = await client_no_auth.get("/api/v1/health", headers={"Authorization": header})
    assert response.status_code == 401
    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == {"detail": "Invalid credentials"}
    assert response.headers["www-authenticate"] == "Bearer"


async def test_missing_authorization_header_still_reaches_public_routes(client_no_auth):
    assert (await client_no_auth.get("/api/v1/health")).status_code == 200


# 5. API key comparison ------------------------------------------------------------------------


async def test_non_ascii_api_key_is_rejected_with_401_not_500():
    with pytest.raises(HTTPException) as exc:
        await require_api_key("clé-ünïcode-✓")
    assert exc.value.status_code == 401


async def test_correct_api_key_is_accepted():
    assert await require_api_key(API_KEY) is None


# 2/3. Upload health + error bodies ------------------------------------------------------------


class FakeStorage:
    def __init__(self, error: Exception | None = None):
        self.error = error
        self.calls: list[str] = []
        self.bucket_name = "test-bucket"

    async def upload(self, key, data):
        self.calls.append("upload")

    async def delete_many(self, keys):
        self.calls.append("delete_many")

    def client(self):
        self.calls.append("client")
        storage = self

        class Ctx:
            async def __aenter__(self_inner):
                if storage.error:
                    raise storage.error
                s3 = MagicMock()
                s3.head_bucket = AsyncMock()
                return s3

            async def __aexit__(self_inner, *exc):
                return False

        return Ctx()


async def test_upload_health_requires_the_service_key(client_no_auth, monkeypatch):
    storage = FakeStorage()
    monkeypatch.setattr(service, "object_storage_client", storage)
    response = await client_no_auth.get("/api/v1/upload/health")
    assert response.status_code in (401, 422)
    assert storage.calls == []


async def test_upload_health_never_writes_to_storage(client_no_auth, monkeypatch):
    storage = FakeStorage()
    monkeypatch.setattr(service, "object_storage_client", storage)
    monkeypatch.setattr(service, "cache", MagicMock(ping=AsyncMock(return_value=True)))
    response = await client_no_auth.get("/api/v1/upload/health", headers={"x-api-key": API_KEY})
    assert response.status_code == 200
    assert "upload" not in storage.calls and "delete_many" not in storage.calls


async def test_upload_health_failure_does_not_leak_exception_text(client_no_auth, monkeypatch):
    secret = "https://secret-account.r2.cloudflarestorage.com/private-bucket"
    monkeypatch.setattr(service, "object_storage_client", FakeStorage(RuntimeError(secret)))
    monkeypatch.setattr(service, "cache", MagicMock(ping=AsyncMock(return_value=True)))
    response = await client_no_auth.get("/api/v1/upload/health", headers={"x-api-key": API_KEY})
    assert response.status_code == 503
    assert "secret-account" not in response.text and "private-bucket" not in response.text


async def test_chunked_upload_500_does_not_leak_exception_text(client_no_auth, monkeypatch):
    secret = "boto: https://secret-account.r2.cloudflarestorage.com failed"
    monkeypatch.setattr(
        "app.upload.router.process_chunked_upload", AsyncMock(side_effect=RuntimeError(secret))
    )
    response = await client_no_auth.post(
        "/api/v1/upload/chunked",
        headers={"x-api-key": API_KEY},
        params=_params(),
        files={"chunk": ("c", b"x")},
    )
    assert response.status_code == 500
    assert "secret-account" not in response.text


async def test_news_article_500_does_not_leak_exception_text(client_no_auth, monkeypatch):
    monkeypatch.setattr(
        "app.upload.router.create_news_article",
        AsyncMock(side_effect=RuntimeError("password=hunter2 host=db.internal")),
    )
    response = await client_no_auth.post(
        "/api/v1/upload/news/article",
        headers={"x-api-key": API_KEY},
        json={"article": {"url": "https://example.com/a", "headline": "h"}},
    )
    assert response.status_code == 500
    assert "hunter2" not in response.text and "db.internal" not in response.text


# 6. Chunked upload validation -----------------------------------------------------------------


def _params(**overrides):
    params = dict(
        source_url="https://example.com/s",
        upload_session_id="0123456789abcdef0123456789abcdef",
        chunk_index=1,
        total_chunks=2,
        original_filename="fixture.csv",
        total_file_size=10,
        chunk_size=5,
        expected_hash=None,
    )
    params.update(overrides)
    return params


class FakeRedis:
    def __init__(self):
        self.sets: dict[str, set] = {}

    async def sismember(self, key, member):
        return member in self.sets.get(key, set())

    async def sadd(self, key, member):
        self.sets.setdefault(key, set()).add(member)

    async def expire(self, key, ttl):
        return True

    async def scard(self, key):
        return len(self.sets.get(key, set()))


@pytest.fixture
def fake_io(monkeypatch):
    storage = FakeStorage()
    cache = MagicMock(redis=FakeRedis(), delete=AsyncMock())
    monkeypatch.setattr(service, "object_storage_client", storage)
    monkeypatch.setattr(service, "cache", cache)
    return storage, cache


def _chunk(data=b"hello"):
    return UploadFile(file=io.BytesIO(data), filename="chunk")


@pytest.mark.parametrize(
    "session_id",
    ["../../etc/x", "a/b", "a b", "", "x" * 200, "ünï", "a%2e%2e", "..", "id\n1"],
)
async def test_unsafe_upload_session_ids_are_rejected_before_any_write(fake_io, session_id):
    storage, _ = fake_io
    with pytest.raises(HTTPException) as exc:
        await service.process_chunked_upload(_chunk(), **_params(upload_session_id=session_id))
    assert exc.value.status_code == 400
    assert storage.calls == []


@pytest.mark.parametrize(
    "overrides",
    [
        dict(total_chunks=0),
        dict(total_chunks=10_000, chunk_index=1),
        dict(chunk_size=0),
        dict(chunk_size=service.MAX_CHUNK_SIZE + 1),
        dict(total_file_size=0),
        dict(total_file_size=service.MAX_TOTAL_FILE_SIZE + 1),
        dict(total_file_size=100, chunk_size=5, total_chunks=2),  # cannot fit in the chunks
        dict(chunk_index=0),
        dict(chunk_index=3),
    ],
)
async def test_out_of_range_sizes_and_counts_are_rejected(fake_io, overrides):
    storage, _ = fake_io
    with pytest.raises(HTTPException) as exc:
        await service.process_chunked_upload(_chunk(), **_params(**overrides))
    assert exc.value.status_code == 400
    assert storage.calls == []


async def test_chunk_larger_than_declared_chunk_size_is_rejected(fake_io):
    storage, _ = fake_io
    with pytest.raises(HTTPException) as exc:
        await service.process_chunked_upload(_chunk(b"123456"), **_params(chunk_size=5))
    assert exc.value.status_code in (400, 413)
    assert "upload" not in storage.calls


async def test_already_received_chunk_index_is_not_overwritten(fake_io):
    storage, _ = fake_io
    first = await service.process_chunked_upload(_chunk(), **_params())
    assert first.status == "chunk_received"
    writes_before = storage.calls.count("upload")
    with pytest.raises(HTTPException) as exc:
        await service.process_chunked_upload(_chunk(b"EVIL!"), **_params())
    assert exc.value.status_code == 409
    assert storage.calls.count("upload") == writes_before


async def test_valid_upload_still_completes_and_metadata_does_not_leak_errors(fake_io):
    await service.process_chunked_upload(_chunk(), **_params(chunk_index=1))
    done = await service.process_chunked_upload(_chunk(), **_params(chunk_index=2))
    assert done.status == "completed"
    assert done.session_id == "0123456789abcdef0123456789abcdef"


async def test_metadata_save_failure_does_not_leak_exception_text(fake_io, monkeypatch):
    storage, _ = fake_io
    await service.process_chunked_upload(_chunk(), **_params(chunk_index=1))
    real_upload = storage.upload

    async def failing(key, data):
        if key.endswith("metadata.json"):
            raise RuntimeError("endpoint=https://secret-account.r2")
        await real_upload(key, data)

    storage.upload = failing
    with pytest.raises(HTTPException) as exc:
        await service.process_chunked_upload(_chunk(), **_params(chunk_index=2))
    assert "secret-account" not in str(exc.value.detail)
