"""The voice endpoint: the signed-in user's recording in, only the words out."""

from unittest.mock import AsyncMock

import pytest

from app.core.dependencies import require_token_quota
from app.main import app

URL = "/api/v1/chat/transcribe"
WAV_UPLOAD = {"audio": ("voice.wav", b"RIFF....WAVE", "audio/wav")}


@pytest.fixture
def quota_ok():
    app.dependency_overrides[require_token_quota] = lambda: None
    yield
    app.dependency_overrides.pop(require_token_quota, None)


async def test_transcribe_returns_the_words_and_uses_the_signed_in_user(
    client, quota_ok, monkeypatch
):
    service = AsyncMock(return_value="Move Ahmed to qualified")
    monkeypatch.setattr("app.chat.router.transcribe", service)

    response = await client.post(URL, files=WAV_UPLOAD)

    assert response.status_code == 200
    assert response.json() == {"text": "Move Ahmed to qualified"}
    assert service.await_args.kwargs["user_id"] == "test-user-id"
    assert service.await_args.kwargs["audio"] == b"RIFF....WAVE"


async def test_transcribe_rejects_a_bad_recording(client, quota_ok, monkeypatch):
    from app.chat.voice import InvalidAudio

    monkeypatch.setattr(
        "app.chat.router.transcribe",
        AsyncMock(side_effect=InvalidAudio("Recording must be WAV audio.")),
    )

    response = await client.post(URL, files={"audio": ("voice.webm", b"not audio", "audio/webm")})

    assert response.status_code == 422
    assert response.json()["detail"] == "Recording must be WAV audio."


async def test_transcribe_provider_failure_does_not_leak_or_log_what_was_said(
    client, quota_ok, monkeypatch, caplog
):
    """Provider errors can quote the audio's words; the agent and the logs get neither."""
    monkeypatch.setattr(
        "app.chat.router.transcribe",
        AsyncMock(side_effect=RuntimeError("provider said: move Ahmed +971501234567")),
    )

    response = await client.post(URL, files=WAV_UPLOAD)

    assert response.status_code == 502
    assert "Ahmed" not in response.text
    assert "Ahmed" not in caplog.text
    assert "+971" not in caplog.text


async def test_transcribe_requires_auth(client_no_auth):
    response = await client_no_auth.post(URL, files=WAV_UPLOAD)
    assert response.status_code == 401
