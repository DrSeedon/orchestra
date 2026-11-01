"""Regression tests for the shared Telegram/dashboard transcription owner."""

import json
from pathlib import Path

import certifi
import httpx
import pytest

from app import transcription


FIXTURES = Path(__file__).parent / "fixtures" / "deepgram_confidence"
UNCERTAIN_HEADER = "[Расшифровка содержит неуверенно распознанные слова: [?]]"
MARKED_TRANSCRIPT = (
    f"{UNCERTAIN_HEADER}\n"
    "Проверь,  делает[?] старт[?]?\nПроверь Orchestra[?]."
)


def _response_fixture(name):
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


@pytest.mark.asyncio
@pytest.mark.parametrize("fixture", ["high", "low"])
async def test_deepgram_word_confidence_reaches_transcript_and_cache(
    fixture, tmp_path, monkeypatch,
):
    payload = _response_fixture(fixture)
    expected = (
        MARKED_TRANSCRIPT if fixture == "low"
        else payload["results"]["channels"][0]["alternatives"][0]["transcript"]
    )
    audio = tmp_path / "voice.oga"
    audio.write_bytes(b"offline-fixture-audio")
    cache_path = tmp_path / "cache.json"
    monkeypatch.setenv("DEEPGRAM_API_KEY", "test-key")
    monkeypatch.setattr(transcription, "TRANSCRIPTION_CACHE_PATH", cache_path)
    legacy_cache = _response_fixture("legacy_cache")
    monkeypatch.setattr(transcription, "_transcription_cache", legacy_cache.copy())
    costs = []
    monkeypatch.setattr(transcription, "voice_cost_add", lambda **kwargs: costs.append(kwargs))
    calls = []

    async def fake_post(self, url, **kwargs):
        calls.append(url)
        assert kwargs["content"] == b"offline-fixture-audio"
        return httpx.Response(200, json=payload)

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    assert await transcription.transcribe_audio(
        str(audio), "tg-confidence-voice", session_name="orch", scope="/scope",
    ) == (expected, None)
    assert calls == [
        "https://api.deepgram.com/v1/listen?model=nova-3&language=multi"
        "&smart_format=true&profanity_filter=false"
    ]
    assert costs == [{
        "session_name": "orch", "scope": "/scope",
        "duration_sec": payload["metadata"]["duration"],
        "cost_usd": payload["metadata"]["duration"] / 60 * 0.0052,
        "file_id": "tg-confidence-voice",
    }]
    assert json.loads(cache_path.read_text()) == {**legacy_cache, "tg-confidence-voice": expected}

    # Simulate a process reload; cache hits need neither a key nor the audio file
    # and must not add another header, request or cost record.
    monkeypatch.setattr(transcription, "_transcription_cache", transcription._load_transcription_cache())
    monkeypatch.delenv("DEEPGRAM_API_KEY")
    audio.unlink()
    assert await transcription.transcribe_audio(str(audio), "tg-confidence-voice") == (expected, None)
    assert len(calls) == len(costs) == 1


@pytest.mark.asyncio
async def test_legacy_string_cache_still_loads_without_api_or_audio(tmp_path, monkeypatch):
    monkeypatch.setattr(transcription, "TRANSCRIPTION_CACHE_PATH", FIXTURES / "legacy_cache.json")
    monkeypatch.setattr(transcription, "_transcription_cache", transcription._load_transcription_cache())
    monkeypatch.delenv("DEEPGRAM_API_KEY", raising=False)

    class UnexpectedClient:
        def __init__(self, **kwargs):
            raise AssertionError("legacy cache hits must not call Deepgram")

    monkeypatch.setattr(httpx, "AsyncClient", UnexpectedClient)
    monkeypatch.setattr(transcription, "voice_cost_add", lambda **kwargs: pytest.fail("cache hit billed"))
    assert await transcription.transcribe_audio(
        str(tmp_path / "missing.oga"), "tg-legacy-voice",
    ) == ("Проверь статус Orchestra.", None)


@pytest.mark.parametrize("confidence, marked", [
    (0.0, True), (0.649999, True), (0.65, False), (0.99, False), (1.0, False),
    (None, False), ("0.4", False), (True, False), (-1.0, False),
])
def test_word_confidence_threshold_is_strict_and_ignores_unknown_scores(confidence, marked):
    alternative = {
        "transcript": "Старт?", "confidence": 0.99,
        "words": [{"word": "старт", "punctuated_word": "Старт?", "confidence": confidence}],
    }
    expected = f"{UNCERTAIN_HEADER}\nСтарт[?]?" if marked else "Старт?"
    assert transcription._format_transcript(alternative) == expected


@pytest.mark.parametrize("words", [None, [], [{"word": "старт"}]])
def test_transcript_without_word_scores_is_unchanged(words):
    assert transcription._format_transcript({"transcript": "Старт?", "words": words}) == "Старт?"


def test_repeated_words_keep_their_own_confidence_and_closing_punctuation():
    alternative = {
        "transcript": "Старт, старт, «старт».",
        "words": [
            {"word": "старт", "punctuated_word": "Старт,", "confidence": 0.99},
            {"word": "старт", "punctuated_word": "старт,", "confidence": 0.4},
            {"word": "старт", "punctuated_word": "«старт».", "confidence": 0.5},
        ],
    }
    assert transcription._format_transcript(alternative) == (
        f"{UNCERTAIN_HEADER}\nСтарт, старт[?], «старт[?]»."
    )


def test_unaligned_smart_format_preserves_all_words_and_marks():
    alternative = {
        "transcript": "Wait 25 seconds.",
        "words": [
            {"word": "wait", "punctuated_word": "Wait", "confidence": 0.99},
            {"word": "twenty", "confidence": 0.4},
            {"word": "five", "confidence": 0.99},
            {"word": "seconds", "punctuated_word": "seconds.", "confidence": 0.99},
        ],
    }
    assert transcription._format_transcript(alternative) == (
        f"{UNCERTAIN_HEADER}\nWait twenty[?] five seconds."
    )


def test_empty_transcript_remains_empty_even_if_words_have_low_confidence():
    assert transcription._format_transcript({
        "transcript": "", "words": [{"word": "noise", "confidence": 0.1}],
    }) == ""


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
