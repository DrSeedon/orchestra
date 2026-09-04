"""Focused contract tests for dashboard voice transcription."""

import asyncio
import io
import wave
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routes import tg


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(tg.router)
    return TestClient(app)


def test_shared_transcriber_reports_missing_key_without_network(tmp_path, monkeypatch):
    from app import transcription

    audio = tmp_path / "voice.webm"
    audio.write_bytes(b"audio")
    monkeypatch.delenv("DEEPGRAM_API_KEY", raising=False)

    result = asyncio.run(transcription.transcribe_audio(str(audio)))

    assert result == ("", "DEEPGRAM_API_KEY is not configured")


def test_transcribe_route_passes_browser_mime_and_cleans_temp_file(monkeypatch):
    seen = {}

    async def duration(path):
        assert Path(path).exists()
        return 3.5

    async def transcribe(path, unique_id, **kwargs):
        seen.update(path=path, unique_id=unique_id, **kwargs)
        assert Path(path).read_bytes() == b"recorded-audio"
        return "надиктованный текст", None

    monkeypatch.setattr(tg, "_audio_duration_seconds", duration)
    monkeypatch.setattr("app.transcription.transcribe_audio", transcribe)

    with _client() as client:
        response = client.post(
            "/api/transcribe",
            files={"audio": ("voice.m4a", b"recorded-audio", "audio/mp4;codecs=mp4a.40.2")},
            data={"session_name": "frontend", "scope": "/repo"},
        )

    assert response.status_code == 200
    assert response.json() == {"text": "надиктованный текст"}
    assert seen["content_type"] == "audio/mp4"
    assert seen["session_name"] == "frontend"
    assert seen["scope"] == "/repo"
    assert seen["unique_id"].startswith("dashboard-")
    assert not Path(seen["path"]).exists()


def test_send_voice_enqueues_the_shared_validated_upload(tmp_path, monkeypatch):
    queued = {}
    target = SimpleNamespace(id="s1", name="worker", scope="/repo")
    monkeypatch.setattr(
        "app.deps.manager", SimpleNamespace(get_by_name=lambda *_args: target),
    )
    monkeypatch.setattr(
        "app.db.dashboard_voice_enqueue",
        lambda *args: queued.setdefault("args", args),
    )
    monkeypatch.setattr(
        tg, "_schedule_dashboard_voice", lambda row: queued.setdefault("row", row),
    )
    monkeypatch.setattr(tg, "UPLOADS_DIR", tmp_path)

    with _client() as client:
        response = client.post(
            "/api/transcribe",
            files={"audio": ("voice.ogg", b"recorded-audio", "audio/ogg")},
            data={"session_name": "worker", "scope": "/repo", "send": "true"},
        )

    assert response.status_code == 200
    assert response.json()["accepted"] is True
    assert queued["args"][1:4] == ("s1", "worker", "/repo")
    assert Path(queued["row"]["path"]).read_bytes() == b"recorded-audio"


def test_transcribe_route_rejects_size_and_duration_before_deepgram(monkeypatch):
    calls = []

    async def transcribe(*args, **kwargs):
        calls.append((args, kwargs))
        return "unexpected", None

    monkeypatch.setattr("app.transcription.transcribe_audio", transcribe)
    monkeypatch.setattr(tg, "VOICE_MAX_BYTES", 4)
    with _client() as client:
        too_large = client.post(
            "/api/transcribe",
            files={"audio": ("voice.webm", b"12345", "audio/webm")},
        )
    assert too_large.status_code == 413
    assert "max 10 MB" in too_large.json()["error"]

    monkeypatch.setattr(tg, "VOICE_MAX_BYTES", 100)
    monkeypatch.setattr(tg, "VOICE_MAX_SECONDS", 2)
    monkeypatch.setattr(tg, "_audio_duration_seconds", lambda path: _async_value(3.0))
    with _client() as client:
        too_long = client.post(
            "/api/transcribe",
            files={"audio": ("voice.webm", b"12345", "audio/webm")},
        )
    assert too_long.status_code == 413
    assert "max 5 minutes" in too_long.json()["error"]

    monkeypatch.setattr(tg, "_audio_duration_seconds", lambda path: _async_value(float("nan")))
    with _client() as client:
        non_finite = client.post(
            "/api/transcribe",
            files={"audio": ("voice.webm", b"12345", "audio/webm")},
        )
    assert non_finite.status_code == 400
    assert non_finite.json() == {"error": "audio duration is invalid"}
    assert calls == []


async def _async_value(value):
    return value


def test_transcribe_route_surfaces_deepgram_and_format_errors(monkeypatch):
    async def duration(path):
        return 1.0

    async def failed(*args, **kwargs):
        return "", "ReadTimeout: upstream stalled"

    monkeypatch.setattr(tg, "_audio_duration_seconds", duration)
    monkeypatch.setattr("app.transcription.transcribe_audio", failed)
    with _client() as client:
        upstream = client.post(
            "/api/transcribe",
            files={"audio": ("voice.webm", b"audio", "audio/webm")},
        )
        unsupported = client.post(
            "/api/transcribe",
            files={"audio": ("voice.bin", b"audio", "application/octet-stream")},
        )

    assert upstream.status_code == 502
    assert upstream.json() == {"error": "transcription failed: ReadTimeout: upstream stalled"}
    assert unsupported.status_code == 415
    assert "unsupported audio type" in unsupported.json()["error"]


def test_ffprobe_reads_actual_audio_duration(tmp_path):
    audio = io.BytesIO()
    with wave.open(audio, "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(8000)
        output.writeframes(b"\0\0" * 8000)
    path = tmp_path / "one-second.wav"
    path.write_bytes(audio.getvalue())

    duration = asyncio.run(tg._audio_duration_seconds(str(path)))

    assert 0.99 <= duration <= 1.01
