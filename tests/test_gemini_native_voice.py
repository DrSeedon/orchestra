from __future__ import annotations

import asyncio
import base64
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starlette.testclient import TestClient

from app import backend_antigravity, db, native_voice, transcription
from app.main import app as fastapi_app
from app.models import supports_native_audio_input
from app.routes import tg as tg_routes


class TestSupportsNativeAudioInput:
    def test_gemini_antigravity_models_and_aliases(self):
        for target in (
            "antigravity/gemini-4-neon-high",
            "antigravity/gemini-4-carbon",
            "antigravity/gemini-4-hydrogen-high",
            "antigravity/gemini-4-argon-high",
            "agy-neon",
            "agy-neon-high",
            "agy-carbon",
            "agy-hydrogen",
            "agy-argon",
            "agy-flash",
            "agy-pro",
            SimpleNamespace(model="agy-neon-high"),
            {"model": "antigravity/gemini-4-carbon"},
        ):
            assert supports_native_audio_input(target) is True, f"Expected True for {target}"

    def test_non_gemini_and_missing_model_false(self):
        for target in (
            None,
            "",
            SimpleNamespace(name="orch", scope="/scope"),
            SimpleNamespace(model=""),
            "gpt-6.2-sol",
            "claude-opus-5-5",
            "agy-opus",
            "agy-sonnet",
            "agy-gptoss",
            "hubargon",
            "gemini-web",
        ):
            assert supports_native_audio_input(target) is False, f"Expected False for {target}"


class TestNativeVoiceHelpers:
    def test_extract_and_build_inline_audio_blocks(self, tmp_path):
        uploads = tmp_path / "uploads"
        uploads.mkdir()
        ogg = uploads / "voice-1.ogg"
        ogg.write_bytes(b"OggS-fake-audio")
        other = tmp_path / "outside.ogg"
        other.write_bytes(b"outside")
        wav = uploads / "not-ogg.wav"
        wav.write_bytes(b"RIFF")

        tag = native_voice.format_native_voice_tag(ogg, 7, source="voice")
        assert str(ogg) in tag
        assert "read_file" in tag

        mixed = f"{tag}\n[voice: {other}]\n[voice: {wav}]\nhello"
        paths = native_voice.extract_native_voice_paths(mixed, uploads)
        assert paths == [ogg.resolve()]

        blocks = native_voice.build_inline_audio_blocks(mixed, uploads)
        assert len(blocks) == 1
        assert blocks[0]["type"] == "audio"
        assert blocks[0]["mimeType"] == "audio/ogg"
        assert base64.b64decode(blocks[0]["data"]) == b"OggS-fake-audio"

    def test_extract_respects_size_limit(self, tmp_path):
        uploads = tmp_path / "uploads"
        uploads.mkdir()
        ogg = uploads / "big.ogg"
        ogg.write_bytes(b"x" * 100)
        tag = native_voice.format_native_voice_tag(ogg, source="dashboard")
        assert native_voice.extract_native_voice_paths(tag, uploads, max_bytes=50) == []


class TestBackendAntigravityInlineAudio:
    def test_inline_audio_block_builder_matches_backend_condition(self, tmp_path):
        uploads = tmp_path / "uploads"
        uploads.mkdir()
        ogg = uploads / "msg.ogg"
        ogg.write_bytes(b"OggS-inline")
        tag = native_voice.format_native_voice_tag(ogg, 3, source="dashboard")

        backend = backend_antigravity.AntigravityBackend.__new__(backend_antigravity.AntigravityBackend)
        backend._owner = SimpleNamespace(capabilities={"promptCapabilities": {"audio": True}})
        backend.model = "gemini-4-neon-high"

        blocks = [{"type": "text", "text": tag}]
        prompt_caps = (getattr(backend._owner, "capabilities", None) or {}).get("promptCapabilities") or {}
        if prompt_caps.get("audio") and backend.model.startswith("gemini-"):
            blocks.extend(native_voice.build_inline_audio_blocks(tag, uploads))
        assert len(blocks) == 2
        assert blocks[1]["type"] == "audio"
        assert blocks[1]["mimeType"] == "audio/ogg"
        assert base64.b64decode(blocks[1]["data"]) == b"OggS-inline"


def _tg_msg(**extra):
    base = {
        "chat": SimpleNamespace(id=123),
        "from_user": SimpleNamespace(id=1, first_name="Максим", last_name=None, username="maxim", is_bot=False),
        "caption": None,
        "forward_from": None,
        "forward_from_chat": None,
        "forward_sender_name": None,
        "forward_origin": None,
        "reply_to_message": None,
    }
    base.update(extra)
    return SimpleNamespace(**base)


class TestTgBridgeNativeVoice:
    def test_handle_voice_skips_deepgram_for_gemini(self, tmp_path):
        import app.tg_bridge as tg_bridge

        session = SimpleNamespace(name="gemini-agent", scope="/scope", model="agy-neon-high")
        audio_file = tmp_path / "voice.ogg"
        audio_file.write_bytes(b"OggS-tg")

        msg = _tg_msg(voice=SimpleNamespace(file_id="fid-1", file_unique_id="u-1", duration=5))

        with (
            patch.object(tg_bridge, "_resolve_orch", new=AsyncMock(return_value=("gemini-agent", session))),
            patch.object(tg_bridge, "_media_name", return_value="voice.ogg") as mock_name,
            patch.object(tg_bridge, "_download_file", new=AsyncMock(return_value=str(audio_file))),
            patch.object(tg_bridge, "_transcribe_audio", new=AsyncMock(side_effect=AssertionError("Deepgram must not be called"))),
            patch.object(tg_bridge, "_register_media", new=AsyncMock(return_value="m1")),
            patch.object(tg_bridge, "_resolve_media", new=AsyncMock()) as mock_resolve,
        ):
            asyncio.run(tg_bridge.handle_voice(msg))
            mock_name.assert_called_once()
            assert mock_name.call_args[0][1] == ".ogg"
            mock_resolve.assert_awaited_once()
            resolved_text = mock_resolve.call_args[0][1]
            assert str(audio_file) in resolved_text
            assert "read_file" in resolved_text

    def test_handle_video_note_skips_deepgram_for_gemini(self, tmp_path):
        import app.tg_bridge as tg_bridge

        session = SimpleNamespace(name="gemini-agent", scope="/scope", model="antigravity/gemini-4-carbon")
        video_file = tmp_path / "vnote.mp4"
        video_file.write_bytes(b"mp4-bytes")

        msg = _tg_msg(video_note=SimpleNamespace(file_id="fid-vn", file_unique_id="u-vn", duration=9))

        class FakeProc:
            returncode = 0
            async def communicate(self):
                return (b"", b"")

        async def fake_exec(*cmd, **kw):
            Path(cmd[-1]).write_bytes(b"OggS-extracted")
            return FakeProc()

        with (
            patch.object(tg_bridge, "_resolve_orch", new=AsyncMock(return_value=("gemini-agent", session))),
            patch.object(tg_bridge, "_media_name", return_value="vnote.mp4"),
            patch.object(tg_bridge, "_download_file", new=AsyncMock(return_value=str(video_file))),
            patch.object(tg_bridge.asyncio, "create_subprocess_exec", side_effect=fake_exec),
            patch.object(tg_bridge, "_transcribe_audio", new=AsyncMock(side_effect=AssertionError("Deepgram must not be called"))),
            patch.object(tg_bridge, "_register_media", new=AsyncMock(return_value="m2")),
            patch.object(tg_bridge, "_resolve_media", new=AsyncMock()) as mock_resolve,
        ):
            asyncio.run(tg_bridge.handle_video_note(msg))
            mock_resolve.assert_awaited_once()
            resolved_text = mock_resolve.call_args[0][1]
            assert ".ogg" in resolved_text
            assert "read_file" in resolved_text

    def test_handle_audio_prompts_native_read_for_gemini(self, tmp_path):
        import app.tg_bridge as tg_bridge

        session = SimpleNamespace(name="gemini-agent", scope="/scope", model="agy-hydrogen")
        audio_file = tmp_path / "track.mp3"
        audio_file.write_bytes(b"mp3-bytes")
        msg = _tg_msg(audio=SimpleNamespace(file_id="fid-aud", file_unique_id="u-aud", file_name="track.mp3", duration=12))

        with (
            patch.object(tg_bridge, "_resolve_orch", new=AsyncMock(return_value=("gemini-agent", session))),
            patch.object(tg_bridge, "_media_name", return_value="track.mp3"),
            patch.object(tg_bridge, "_download_file", new=AsyncMock(return_value=str(audio_file))),
            patch.object(tg_bridge, "_send_to_agent", new=AsyncMock()) as mock_send,
        ):
            asyncio.run(tg_bridge.handle_audio(msg))
            mock_send.assert_awaited_once()
            sent_text = mock_send.call_args[0][2]
            assert str(audio_file) in sent_text
            assert "read_file" in sent_text


class TestDashboardVoiceNativeGemini:
    def test_transcribe_upload_gemini_skips_deepgram_without_key(self, tmp_path, monkeypatch):
        from app import deps

        uploads = tmp_path / "uploads"
        uploads.mkdir()
        monkeypatch.setattr(tg_routes, "UPLOADS_DIR", uploads)
        monkeypatch.setattr(transcription, "DEEPGRAM_API_KEY", "", raising=False)
        monkeypatch.setattr(tg_routes, "_audio_duration_seconds", AsyncMock(return_value=4.2))

        gem_session = SimpleNamespace(name="gem-1", scope="/s", model="agy-neon-high")
        monkeypatch.setattr(deps.manager, "get_by_name", lambda name, scope: gem_session if name == "gem-1" else None)

        async def fake_conv(src, dst):
            Path(dst).write_bytes(b"OggS-conv")
            return Path(dst)

        with (
            patch.object(transcription, "transcribe_audio", new=AsyncMock(side_effect=AssertionError("Deepgram must not be called"))),
            patch.object(tg_routes, "convert_to_ogg_opus", side_effect=fake_conv),
            patch("app.tg_bridge._cleanup_uploads", lambda: None),
        ):
            with TestClient(fastapi_app) as client:
                resp = client.post(
                    "/api/transcribe",
                    data={"send": "false", "session_name": "gem-1", "scope": "/s"},
                    files={"audio": ("mic.webm", b"webm-bytes", "audio/webm")},
                )
        assert resp.status_code == 200
        body = resp.json()
        assert body["native_audio"] is True
        assert body["url"].startswith("/uploads/")
        assert body["url"].endswith(".ogg")
        assert Path(body["path"]).exists()
        assert "read_file" in body["text"]

    def test_process_dashboard_voice_gemini_keeps_ogg_and_skips_deepgram(self, tmp_path, monkeypatch):
        from app import deps

        uploads = tmp_path / "uploads"
        uploads.mkdir()
        src = uploads / "dash-raw.webm"
        src.write_bytes(b"webm-raw")
        monkeypatch.setattr(tg_routes, "UPLOADS_DIR", uploads)
        monkeypatch.setattr(tg_routes, "_audio_duration_seconds", AsyncMock(return_value=6.0))

        gem_session = SimpleNamespace(id="sid-1", name="gem-1", scope="/s", model="antigravity/gemini-4-carbon")
        sent = []
        row = {
            "voice_id": "v-1",
            "session_id": "sid-1",
            "session_name": "gem-1",
            "scope": "/s",
            "path": str(src),
            "content_type": "audio/webm",
        }
        statuses = []
        monkeypatch.setattr(deps.manager, "ensure_loaded_by_id", AsyncMock(return_value=gem_session))
        monkeypatch.setattr(deps.manager, "send", AsyncMock(side_effect=lambda sid, msg, **kw: sent.append(msg)))
        monkeypatch.setattr(db, "dashboard_voice_mark_running", lambda vid: statuses.append(("running", vid)))
        monkeypatch.setattr(db, "dashboard_voice_mark_sent", lambda vid: statuses.append(("sent", vid)))
        monkeypatch.setattr(db, "dashboard_voice_mark_failed", lambda vid, err: statuses.append(("failed", vid, err)))
        monkeypatch.setattr(db, "voice_cost_add", MagicMock(side_effect=AssertionError("voice_cost_add must not be called")))

        async def fake_conv(s, d):
            Path(d).write_bytes(b"OggS-kept")
            return Path(d)

        with (
            patch.object(transcription, "transcribe_audio", new=AsyncMock(side_effect=AssertionError("Deepgram must not be called"))),
            patch.object(tg_routes, "convert_to_ogg_opus", side_effect=fake_conv),
            patch("app.tg_bridge._cleanup_uploads", lambda: None),
        ):
            asyncio.run(tg_routes._process_dashboard_voice(row))

        assert len(sent) == 1
        assert ".ogg" in sent[0]
        assert "read_file" in sent[0]
        assert (uploads / "dashboard-voice-v-1.ogg").exists()
        assert not src.exists()
        assert ("sent", "v-1") in statuses


class TestFrontendChatNativeVoice:
    def test_chat_js_extract_native_voice_badges(self):
        voice_tag = native_voice.format_native_voice_tag(
            "/home/kesha/orchestra/data/uploads/dashboard-voice-1.ogg", 5, source="voice"
        )
        vnote_tag = native_voice.format_native_voice_tag(
            "/home/kesha/orchestra/data/uploads/vn-1.ogg", 9,
            source="video_note", companion_video="/home/kesha/orchestra/data/uploads/vn-1.mp4",
        )
        audio_tag = native_voice.format_native_voice_tag(
            "/home/kesha/orchestra/data/uploads/track.mp3", 12,
            source="audio", filename="track.mp3",
        )
        payload = json.dumps({
            "voice": f"{voice_tag}\nпроверь текст",
            "vnote": vnote_tag,
            "audio": audio_tag,
        })
        script = f"""
const fs = require("fs");
const vm = require("vm");
const code = fs.readFileSync("app/static/js/chat.js", "utf8");
const sandbox = {{
  window: {{}},
  document: {{ getElementById: () => null, querySelector: () => null, createElement: () => ({{}}) }},
  navigator: {{}},
  localStorage: {{ getItem: () => null, setItem: () => {{}} }},
  T: (k) => k,
}};
const fnMatch = code.match(/function _nativeVoiceAudioSrc[\\s\\S]*?\\n\\}}\\n\\nfunction _extractNativeVoiceBadges[\\s\\S]*?\\n\\}}/);
if (!fnMatch) throw new Error("Functions not found in chat.js");
vm.runInNewContext(fnMatch[0], sandbox);
const input = {payload};
const out = {{
  src: sandbox._nativeVoiceAudioSrc("/home/kesha/orchestra/data/uploads/dashboard-voice-1.ogg"),
  voice: sandbox._extractNativeVoiceBadges(input.voice),
  vnote: sandbox._extractNativeVoiceBadges(input.vnote),
  audio: sandbox._extractNativeVoiceBadges(input.audio),
}};
console.log(JSON.stringify(out));
"""
        proc = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True)
        data = json.loads(proc.stdout.strip())
        assert data["src"] == "/uploads/dashboard-voice-1.ogg"
        assert len(data["voice"]["items"]) == 1
        assert data["voice"]["items"][0]["audioPath"] == "/home/kesha/orchestra/data/uploads/dashboard-voice-1.ogg"
        assert data["voice"]["cleanText"] == "проверь текст"
        assert len(data["vnote"]["items"]) == 1
        assert data["vnote"]["items"][0]["audioPath"] == "/home/kesha/orchestra/data/uploads/vn-1.ogg"
        assert len(data["audio"]["items"]) == 1
        assert data["audio"]["items"][0]["audioPath"] == "/home/kesha/orchestra/data/uploads/track.mp3"
