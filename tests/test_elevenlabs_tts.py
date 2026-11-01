"""Offline behavior of V-1086: no account, provider SDK or real API calls."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/video_artifact"))
import elevenlabs_tts as tts
LOAD_ENVIRONMENT = tts.load_environment
REQUIRE_DECODER = tts.require_decoder

spec = importlib.util.spec_from_file_location("eleven_video_make", ROOT / "scripts/video_artifact/make.py")
make = importlib.util.module_from_spec(spec)
spec.loader.exec_module(make)


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "placeholder-for-offline-test")
    monkeypatch.delenv("ELEVENLABS_VOICE_ID", raising=False)
    monkeypatch.setattr(tts, "load_environment", lambda: None)
    monkeypatch.setattr(tts, "require_decoder", lambda: None)

    def no_network(*args, **kwargs):
        raise AssertionError("real network is forbidden in these tests")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", no_network)


@pytest.fixture
def decoded(monkeypatch):
    def decode(_source, output):
        tts.write_wav(output, b"\x01\x10" * 4800)  # exactly 0.1 s at 48 kHz

    monkeypatch.setattr(tts, "decode_mp3", decode)
    return decode


def mock_client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def audio_response():
    return httpx.Response(200, headers={"content-type": "audio/mpeg"}, content=b"mock-mp3")


def test_payload_uses_approved_model_owner_voice_and_starter_format(tmp_path, decoded):
    def respond(request):
        data = json.loads(request.content)
        assert request.url.host == "api.elevenlabs.io"
        assert request.url.path.endswith("/XuEV9VY3VUASYgJVNBh0")
        assert request.url.params["output_format"] == "mp3_44100_128"
        assert request.headers["xi-api-key"] == "placeholder-for-offline-test"
        assert data == {"text": "В 2026 году Python + API.", "model_id": "eleven_flash_v2_5",
                        "language_code": "ru", "voice_settings": tts.Config().settings}
        assert request.extensions["timeout"] == {"connect": 10.0, "read": 120.0, "write": 30.0, "pool": 10.0}
        return audio_response()

    with mock_client(respond) as client:
        path = tts.synthesize("В 2026 году Python + API.", tmp_path, tts.Config(), client=client)
    assert len(tts.wav_frames(path)) == 9600
    assert not list(tmp_path.glob("*.request.json"))


def test_cache_reuses_response_without_key_and_separates_configuration(tmp_path, monkeypatch, decoded):
    calls = []

    def respond(request):
        calls.append(request)
        return audio_response()

    config = tts.Config()
    with mock_client(respond) as client:
        first = tts.synthesize("Кеш.", tmp_path, config, client=client)
        monkeypatch.delenv("ELEVENLABS_API_KEY")
        assert tts.synthesize("Кеш.", tmp_path, config, client=client) == first
        monkeypatch.setenv("ELEVENLABS_API_KEY", "different-placeholder")
        assert tts.synthesize("Кеш.", tmp_path, config, client=client) == first
        for changed in [replace(config, voice="another_saved_voice"), replace(config, speed=1.1),
                        replace(config, stability=0.3), replace(config, similarity=0.6), replace(config, language="en")]:
            assert tts.synthesize("Кеш.", tmp_path, changed, client=client) != first
        assert tts.synthesize("Новый текст.", tmp_path, config, client=client) != first
    assert len(calls) == 7
    assert all("placeholder" not in p.read_text() for p in tmp_path.glob("*.json"))


@pytest.mark.parametrize("status,detail,reason", [
    (401, {}, "authentication"), (403, {}, "permissions"), (402, {}, "quota"),
    (429, {}, "quota"), (401, {"status": "quota_exceeded"}, "quota"),
    (404, {}, "unavailable"), (422, {}, "request failed"),
])
def test_explicit_refusals_have_safe_messages_and_allow_fixing_request(tmp_path, decoded, status, detail, reason):
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(status, json={"detail": {**detail, "message": "do-not-echo-private-response"}})

    with mock_client(respond) as client:
        with pytest.raises(tts.TTSError, match=reason) as error:
            tts.synthesize("Фраза.", tmp_path, tts.Config(), client=client)
    assert "private-response" not in str(error.value)
    assert "placeholder" not in str(error.value)
    assert not list(tmp_path.glob("*.request.json"))
    with mock_client(lambda _: audio_response()) as client:
        assert tts.synthesize("Фраза.", tmp_path, tts.Config(), client=client).is_file()
    assert len(calls) == 1


@pytest.mark.parametrize("failure", ["timeout", "connection", "server", "redirect", "json", "empty", "truncated-mp3"])
def test_uncertain_failure_cannot_charge_twice_even_on_next_run(tmp_path, monkeypatch, failure):
    calls = []

    def respond(request):
        calls.append(request)
        if failure == "timeout":
            raise httpx.ReadTimeout("do-not-echo-secret", request=request)
        if failure == "connection":
            raise httpx.ReadError("do-not-echo-secret", request=request)
        if failure == "server":
            return httpx.Response(503)
        if failure == "redirect":
            return httpx.Response(302, headers={"location": "https://example.invalid"})
        if failure == "json":
            return httpx.Response(200, json={"unexpected": "do-not-echo-secret"})
        return httpx.Response(200, headers={"content-type": "audio/mpeg"}, content=b"bad" if failure == "truncated-mp3" else b"")

    monkeypatch.setattr(tts, "decode_mp3", lambda *_: (_ for _ in ()).throw(tts.TTSError("bad MP3")))
    with mock_client(respond) as client:
        for _ in range(2):
            with pytest.raises(tts.TTSError) as error:
                tts.synthesize("Фраза.", tmp_path, tts.Config(), client=client)
            assert "do-not-echo-secret" not in str(error.value)
    assert len(calls) == 1
    assert list(tmp_path.glob("*.request.json"))


def test_decoder_failure_recovers_from_received_audio_without_another_charge(tmp_path, monkeypatch, decoded):
    calls = []
    monkeypatch.setattr(tts, "decode_mp3", lambda *_: (_ for _ in ()).throw(tts.TTSError("decoder unavailable")))
    with mock_client(lambda req: calls.append(req) or audio_response()) as client:
        with pytest.raises(tts.TTSError, match="decoder"):
            tts.synthesize("Recover.", tmp_path, tts.Config(language="en"), client=client)
        monkeypatch.setattr(tts, "decode_mp3", decoded)
        monkeypatch.delenv("ELEVENLABS_API_KEY")
        path = tts.synthesize("Recover.", tmp_path, tts.Config(language="en"), client=client)
    assert path.is_file() and len(calls) == 1
    assert not list(tmp_path.glob("*.request.json"))


def test_crash_marker_blocks_submission_before_network(tmp_path, decoded):
    config = tts.Config()
    marker = tmp_path / f"{tts.cache_key('Фраза.', config)}.request.json"
    marker.write_text('{"state":"submission_uncertain"}')
    with mock_client(lambda _: pytest.fail("must not submit after a crash")) as client:
        with pytest.raises(tts.TTSError, match="refusing another charge"):
            tts.synthesize("Фраза.", tmp_path, config, client=client)


def test_request_intent_is_durable_before_post_and_never_contains_key(tmp_path, decoded):
    def respond(_request):
        markers = list(tmp_path.glob("*.request.json"))
        assert len(markers) == 1
        assert json.loads(markers[0].read_text()) == {"state": "submission_uncertain", "provider": "elevenlabs"}
        return audio_response()

    with mock_client(respond) as client:
        tts.synthesize("Фраза.", tmp_path, tts.Config(), client=client)


def test_corrupt_cached_audio_never_silently_submits_again(tmp_path, decoded):
    calls = []
    old_local = tmp_path / "old-tera-cache.wav"
    old_local.write_bytes(b"existing-local-cache")
    with mock_client(lambda req: calls.append(req) or audio_response()) as client:
        path = tts.synthesize("Фраза.", tmp_path, tts.Config(), client=client)
        path.write_bytes(b"corrupt")
        with pytest.raises(tts.TTSError, match="Invalid cached WAV"):
            tts.synthesize("Фраза.", tmp_path, tts.Config(), client=client)
    assert len(calls) == 1 and old_local.read_bytes() == b"existing-local-cache"


def test_parallel_callers_share_one_paid_submission(tmp_path, decoded):
    calls = []
    with mock_client(lambda req: calls.append(req) or audio_response()) as client:
        with ThreadPoolExecutor(max_workers=4) as pool:
            paths = list(pool.map(lambda _: tts.synthesize("Одна фраза.", tmp_path, tts.Config(), client=client), range(8)))
    assert len(calls) == 1 and len(set(paths)) == 1


def test_pause_samples_are_literal_and_speech_is_reused(tmp_path, decoded):
    calls = []
    with mock_client(lambda req: calls.append(req) or audio_response()) as client:
        path = tts.synthesize("[0.2] Фраза. [0.4] Фраза. [0.3]", tmp_path, tts.Config(speed=1.2), client=client)
    frames = tts.wav_frames(path)
    assert len(calls) == 1
    assert len(frames) == round(1.1 * tts.SR) * 2
    assert frames[:round(0.2 * tts.SR) * 2] == bytes(round(0.2 * tts.SR) * 2)
    assert frames[round(0.3 * tts.SR) * 2:round(0.7 * tts.SR) * 2] == bytes(round(0.4 * tts.SR) * 2)
    assert all("[" not in json.loads(req.content)["text"] for req in calls)


def test_plan_uses_decoded_duration_with_existing_html_manim_contract(tmp_path, decoded):
    config = tts.Config(speed=1.2)
    with mock_client(lambda _: audio_response()) as client:
        spoken = tts.synthesize("Фраза. [0.4] Фраза.", tmp_path, config, client=client)
        silent = tts.synthesize("", tmp_path, config, client=client)
    steps = [{"t": "Voice", "say": "Фраза. [0.4] Фраза.", "sub": None, "hold": None},
             {"t": "Hold", "say": "", "sub": None, "hold": 1.5}]
    timing = make.plan(steps, [spoken, silent], 1.2)
    first, last = timing["steps"]
    assert first["phrase_end"] - first["phrase_start"] == pytest.approx(0.6, abs=0.001)
    assert first["d"] == pytest.approx(round(make.LEAD / 1.2 + 0.6 + make.GAP / 1.2, 3))
    assert last["d"] == 1.5 and last["phrase_start"] == last["step_start"]


@pytest.mark.parametrize("kwargs", [{"speed": 0}, {"speed": 1.21}, {"speed": float("nan")},
                                     {"stability": -1}, {"similarity": 2}, {"voice": "bad/voice"},
                                     {"model": "eleven_multilingual_v2"}, {"language": "fr"}])
def test_invalid_configuration_rejected_before_submission(kwargs):
    with pytest.raises(tts.TTSError):
        tts.Config(**kwargs)


@pytest.mark.parametrize("text", ["A [0] B", "A [10.1] B", "a" * 40001])
def test_all_text_validated_before_any_charge(tmp_path, text):
    with mock_client(lambda _: pytest.fail("invalid input must not be submitted")) as client:
        with pytest.raises(tts.TTSError):
            tts.synthesize(text, tmp_path, tts.Config(), client=client)


def test_missing_key_has_actionable_error_and_does_not_poison_cache(tmp_path, monkeypatch):
    monkeypatch.delenv("ELEVENLABS_API_KEY")
    with mock_client(lambda _: pytest.fail("missing key must not submit")) as client:
        with pytest.raises(tts.TTSError, match="Missing ELEVENLABS_API_KEY"):
            tts.synthesize("Фраза.", tmp_path, tts.Config(), client=client)
    assert not list(tmp_path.glob("*.request.json"))


def test_environment_loading_uses_only_repository_env_and_never_overrides_exports(monkeypatch):
    import dotenv

    seen = []
    monkeypatch.setattr(dotenv, "load_dotenv", lambda *a, **k: seen.append((a, k)))
    LOAD_ENVIRONMENT()
    assert seen == [((ROOT / ".env",), {"override": False})]


def test_missing_decoder_refuses_before_paid_submission(tmp_path, monkeypatch):
    monkeypatch.setattr(tts, "require_decoder", REQUIRE_DECODER)
    monkeypatch.setattr(tts.shutil, "which", lambda _: None)
    with mock_client(lambda _: pytest.fail("missing decoder must not charge")) as client:
        with pytest.raises(tts.TTSError, match="ffmpeg is required"):
            tts.synthesize("Фраза.", tmp_path, tts.Config(), client=client)
    assert not list(tmp_path.glob("*.request.json"))


def test_video_error_is_terminal_without_local_or_paid_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr(tts, "synthesize", lambda *_: (_ for _ in ()).throw(tts.TTSError("quota exceeded")))
    monkeypatch.setattr(make, "run", lambda *_a, **_k: pytest.fail("no fallback worker allowed"))
    with pytest.raises(SystemExit, match="quota exceeded"):
        make.synthesize([{"say": "Фраза."}], tmp_path, 1, 1.0)


def test_legacy_stress_removed_without_destroying_plus_and_mixed_languages():
    assert tts.clean_text("лим+ита и стрессо́в, C++ и 2+2.") == "лимита и стрессов, C++ и 2+2."
    for lang in ("ru", "en"):
        steps = [{"t": "Mix", "say": "2026 Python и API [0.4] вместе.", "hold": None}]
        assert make.check_steps(steps, lang, "elevenlabs") == steps


@pytest.mark.parametrize("language", ["ru", "en"])
@pytest.mark.parametrize("suffix", [".html", ".py"])
def test_video_default_dispatches_ru_en_html_manim_to_sergey_flash(tmp_path, monkeypatch, language, suffix):
    steps = [{"t": "Mix", "say": "2026 API и кеш.", "sub": None, "hold": None}]
    monkeypatch.setattr(make.sys, "argv", ["make.py", "scene" + suffix, "--out", str(tmp_path), "--lang", language, "--stills"])
    monkeypatch.setattr(make, "read_steps", lambda *_: steps)
    monkeypatch.setattr(make, "manim_steps", lambda *_: ("Demo", steps))
    for name in ("mark_stress", "tera_stress", "apply_stress_dictionary"):
        monkeypatch.setattr(make, name, lambda *_a, **_k: pytest.fail("ElevenLabs must not use local stress tools"))
    seen = []

    def synthesize(text, cache, config):
        seen.append(config)
        assert text == steps[0]["say"]
        path = cache / "mock.wav"
        cache.mkdir(parents=True, exist_ok=True)
        tts.write_wav(path, b"\x01\x10" * 4800)
        return path

    monkeypatch.setattr(tts, "synthesize", synthesize)
    for name in ("voice_track", "render", "render_manim", "manim_timing_check"):
        monkeypatch.setattr(make, name, lambda *_a, **_k: None)
    make._main()
    assert len(seen) == 1 and seen[0].language == language
    assert seen[0].voice == "XuEV9VY3VUASYgJVNBh0" and seen[0].model == "eleven_flash_v2_5"
    timing = json.loads((tmp_path / "scene.timing.json").read_text())
    assert timing["steps"][0]["phrase_end"] == 0.45


@pytest.mark.parametrize("suffix", [".html", ".py"])
def test_preview_never_loads_env_keys_or_synthesizes(tmp_path, monkeypatch, suffix):
    monkeypatch.delenv("ELEVENLABS_API_KEY")
    steps = [{"t": "Preview", "say": "2026 API [0.4] кеш.", "hold": None, "sub": None}]
    monkeypatch.setattr(make.sys, "argv", ["make.py", "scene" + suffix, "--out", str(tmp_path), "--preview-step", "1"])
    monkeypatch.setattr(make, "read_steps", lambda *_: steps)
    monkeypatch.setattr(make, "manim_steps", lambda *_: ("Demo", steps))
    monkeypatch.setattr(tts, "load_environment", lambda: pytest.fail("preview must not read .env"))
    monkeypatch.setattr(make, "synthesize", lambda *_a, **_k: pytest.fail("preview must not synthesize"))
    seen = []
    monkeypatch.setattr(make, "preview_html", lambda *_: seen.append("html"))
    monkeypatch.setattr(make, "preview_manim", lambda *_: seen.append("manim"))
    make._main()
    assert seen == ["html" if suffix == ".html" else "manim"]


def test_voice_override_and_direct_file_cli(tmp_path, monkeypatch):
    monkeypatch.setenv("ELEVENLABS_VOICE_ID", "saved_override")
    assert tts.config_from_env().voice == "saved_override"
    assert tts.config_from_env(voice="explicit_override").voice == "explicit_override"
    source = tmp_path / "text.txt"
    source.write_text("Фраза.", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["elevenlabs_tts.py", "--file", str(source), "--out", str(tmp_path / "out.wav")])

    def synthesize(text, cache, config):
        assert text == "Фраза." and config.voice == "saved_override"
        path = tmp_path / "cached.wav"
        tts.write_wav(path, b"\x01\x10" * 4800)
        return path

    monkeypatch.setattr(tts, "synthesize", synthesize)
    tts.main()
    assert len(tts.wav_frames(tmp_path / "out.wav")) == 9600


def test_decoder_declares_mp3_input_and_validates_atomic_wav_output(tmp_path, monkeypatch):
    source, output = tmp_path / "source.mp3", tmp_path / "clip.wav"
    source.write_bytes(b"offline-fixture")
    seen = []

    def run(argv, **kwargs):
        seen.append(argv)
        assert argv[argv.index("-i") - 2:argv.index("-i")] == ["-f", "mp3"]
        assert argv[-3:-1] == ["-f", "wav"]
        assert kwargs["timeout"] == 120
        tts.write_wav(Path(argv[-1]), b"\x01\x10" * 4800)
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(subprocess, "run", run)
    tts.decode_mp3(source, output)
    assert len(tts.wav_frames(output)) == 9600 and len(seen) == 1
    assert not output.with_name(output.name + ".part").exists()


@pytest.mark.parametrize("has_timing", [False, True])
def test_check_only_cannot_submit_new_speech(tmp_path, monkeypatch, has_timing):
    steps = [{"t": "Old", "say": "Прежняя фраза.", "sub": None, "hold": None}]
    monkeypatch.setattr(make.sys, "argv", ["make.py", "scene.html", "--out", str(tmp_path),
                                          "--check-only", "--no-music", "--no-check"])
    monkeypatch.setattr(make, "read_steps", lambda *_: steps)
    monkeypatch.setattr(make, "synthesize", lambda *_a, **_k: pytest.fail("check-only must not synthesize"))
    monkeypatch.setattr(tts, "load_environment", lambda: pytest.fail("check-only must not load credentials"))
    if has_timing:
        (tmp_path / "scene.timing.json").write_text(json.dumps({"T": 1, "pre": 0.4, "post": 1.6,
            "steps": [{"say": steps[0]["say"], "d": 1, "phrase_start": 0.35, "phrase_end": 0.6}]}))
        make._main()
    else:
        with pytest.raises(SystemExit):
            make._main()


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="local ffmpeg decoder required")
def test_real_mp3_decoder_produces_pcm_wav_and_rejects_malformed_audio(tmp_path):
    mp3 = tmp_path / "local-fixture.mp3"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                    "sine=frequency=440:sample_rate=44100:duration=0.3", "-c:a", "libmp3lame", str(mp3)],
                   check=True, capture_output=True, timeout=10)
    path = tmp_path / "decoded.wav"
    tts.decode_mp3(mp3, path)
    assert len(tts.wav_frames(path)) / (tts.SR * 2) == pytest.approx(0.3, abs=0.03)
    broken = tmp_path / "broken.mp3"
    broken.write_bytes(b"not an mp3")
    with pytest.raises(tts.TTSError, match="malformed/undecodable"):
        tts.decode_mp3(broken, tmp_path / "broken.wav")
    assert not (tmp_path / "broken.wav").exists()
