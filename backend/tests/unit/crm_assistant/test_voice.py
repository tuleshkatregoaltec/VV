"""Voice messages: only a WAV recording goes to the model, the agent gets back just the words
(for them to check before sending), the tokens count toward their daily limit, and the voice
model stays on OpenRouter even when the chat runs on OpenAI (its chat model takes no audio)."""

import struct
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic_ai import BinaryContent
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from app.core.openrouter import CompatibleOpenRouterModel
from app.crm.assistant import voice


def wav(samples: int = 1600, *, level: int = 3000, bits: int = 16) -> bytes:
    """A 16 kHz mono WAV as the browser uploads it: a square wave at `level`, 0 for silence."""
    data = b"".join(struct.pack("<h", level if i % 40 < 20 else -level) for i in range(samples))
    header = b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVE"
    fmt = b"fmt " + struct.pack("<IHHIIHH", 16, 1, 1, 16_000, 32_000, 2, bits)
    return header + fmt + b"data" + struct.pack("<I", len(data)) + data


@pytest.fixture
def usage(monkeypatch):
    record = AsyncMock()
    monkeypatch.setattr(voice.token_usage_service, "record_usage", record)
    return record


def model_saying(text: str, seen: list | None = None) -> FunctionModel:
    def reply(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if seen is not None:
            seen.extend(messages[-1].parts[-1].content)
        return ModelResponse(parts=[TextPart(text)])

    return FunctionModel(reply)


async def test_the_recording_goes_to_the_model_as_wav_and_only_the_words_come_back(usage):
    seen: list = []
    with voice.transcribe_agent.override(model=model_saying("  Move Ahmed to qualified \n", seen)):
        text = await voice.transcribe(None, user_id="user-1", audio=wav())

    assert text == "Move Ahmed to qualified"
    [audio] = [part for part in seen if isinstance(part, BinaryContent)]
    assert audio.media_type == "audio/wav"


async def test_transcribing_counts_toward_the_users_daily_tokens(usage):
    with voice.transcribe_agent.override(model=model_saying("hello")):
        await voice.transcribe(None, user_id="user-1", audio=wav())

    usage.assert_awaited_once()
    kwargs = usage.await_args.kwargs
    assert kwargs["user_id"] == "user-1"
    assert kwargs["total_tokens"] > 0


async def test_when_the_model_hears_no_speech_the_agent_gets_nothing(usage):
    with voice.transcribe_agent.override(model=model_saying(voice.NO_SPEECH)):
        assert await voice.transcribe(None, user_id="user-1", audio=wav()) == ""


@pytest.mark.parametrize("level", [0, 60], ids=["silence", "quiet room"])
async def test_silent_recordings_never_reach_the_model(level, usage, monkeypatch):
    """Models make up whole sentences from silence; the agent must never be shown those."""
    run = AsyncMock()
    monkeypatch.setattr(voice.transcribe_agent, "run", run)
    assert await voice.transcribe(None, user_id="user-1", audio=wav(16_000, level=level)) == ""
    run.assert_not_awaited()
    usage.assert_not_awaited()


@pytest.mark.parametrize(
    "audio",
    [
        pytest.param(b"OggS" + b"\x00" * 100, id="not wav"),
        pytest.param(wav()[:44], id="header only"),
        pytest.param(wav(bits=8), id="not 16-bit"),
        pytest.param(wav(samples=voice.MAX_AUDIO_BYTES // 2), id="longer than the limit"),
    ],
)
async def test_bad_recordings_never_reach_the_model(audio, usage, monkeypatch):
    run = AsyncMock()
    monkeypatch.setattr(voice.transcribe_agent, "run", run)
    with pytest.raises(voice.InvalidAudio):
        await voice.transcribe(None, user_id="user-1", audio=audio)
    run.assert_not_awaited()
    usage.assert_not_awaited()


def test_voice_stays_on_openrouter_even_with_an_assistant_openai_key():
    config = SimpleNamespace(
        OPENROUTER_API_KEY="or-key",
        DEFAULT_CHAT_MODEL="google/gemini-3.1-flash-lite",
        ASSISTANT_OPENAI_API_KEY="sk-test",
        ASSISTANT_VOICE_MODEL=None,
    )
    model = voice.create_voice_model(config)
    assert isinstance(model, CompatibleOpenRouterModel)
    assert model.model_name == "google/gemini-3.1-flash-lite"


def test_voice_model_can_be_chosen():
    config = SimpleNamespace(
        OPENROUTER_API_KEY="or-key",
        DEFAULT_CHAT_MODEL="google/gemini-3.1-flash-lite",
        ASSISTANT_VOICE_MODEL="google/gemini-2.5-flash",
    )
    assert voice.create_voice_model(config).model_name == "google/gemini-2.5-flash"
