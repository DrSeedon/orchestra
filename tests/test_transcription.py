"""Regression tests for the shared Telegram/dashboard transcription owner."""

import json

import certifi
import httpx
import pytest

from app import transcription


@pytest.mark.asyncio
async def test_transcription_survives_certifi_path_removed_after_import(
    tmp_path, monkeypatch,
):
    audio_path = tmp_path / "voice.oga"
    audio_path.write_bytes(b"audio")
    monkeypatch.setenv("DEEPGRAM_API_KEY", "test-key")
    monkeypatch.setattr(certifi, "where", lambda: str(tmp_path / "deleted-cacert.pem"))
    monkeypatch.setattr(transcription, "_transcription_cache", {})
    monkeypatch.setattr(transcription, "_save_transcription_cache", lambda cache: None)
    monkeypatch.setattr(transcription, "voice_cost_add", lambda **kwargs: None)

    async def no_sleep(_delay):
        return None

    async def fake_post(self, *args, **kwargs):
        return httpx.Response(
            200,
            content=json.dumps(
                {
                    "metadata": {"duration": 1.0},
                    "results": {
                        "channels": [{"alternatives": [{"transcript": "heard"}]}],
                    },
                }
            ).encode(),
        )

    monkeypatch.setattr(transcription.asyncio, "sleep", no_sleep)
    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    assert await transcription.transcribe_audio(str(audio_path)) == ("heard", None)


@pytest.mark.asyncio
async def test_missing_audio_is_classified_before_http_client_creation(
    tmp_path, monkeypatch,
):
    missing = tmp_path / "missing.oga"
    monkeypatch.setenv("DEEPGRAM_API_KEY", "test-key")
    monkeypatch.setattr(transcription, "_transcription_cache", {})

    class UnexpectedClient:
        def __init__(self, **kwargs):
            raise AssertionError("HTTP must not start without readable audio")

    monkeypatch.setattr(httpx, "AsyncClient", UnexpectedClient)

    text, error = await transcription.transcribe_audio(str(missing))

    assert text == ""
    assert error is not None
    assert error.startswith("audio file unavailable: FileNotFoundError:")
    assert str(missing) in error
