"""Hub fallback only: stdlib checks with stubbed HTTP/accounting dependencies.

Run from the checkout root with PYTHONDONTWRITEBYTECODE=1. This does not
replace the repository's required uv/pytest checks in a complete checkout.
"""

import ast
import importlib
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
FIXTURES = ROOT / "tests" / "fixtures" / "deepgram_confidence"
HEADER = "[Расшифровка содержит неуверенно распознанные слова: [?]]"
MARKED = f"{HEADER}\nПроверь,  делает[?] старт[?]?\nПроверь Orchestra[?]."

# The hub copy has neither third-party HTTP nor app.db. Execute the actual
# transcription module, replacing only these unavailable dependencies.
http = ModuleType("httpx")
http.create_ssl_context = MagicMock(return_value=object())
http.AsyncClient = MagicMock()
db = ModuleType("app.db")
db.voice_cost_add = MagicMock()
app = importlib.import_module("app")
with patch.dict(sys.modules, {"httpx": http, "app.db": db}):
    transcription = importlib.import_module("app.transcription")


def payload(name):
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


class ConfidenceChecks(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        self.audio = self.directory / "voice.oga"
        self.audio.write_bytes(b"offline-audio")
        self.cache = self.directory / "cache.json"
        for patcher in (
            patch.object(transcription, "TRANSCRIPTION_CACHE_PATH", self.cache),
            patch.object(transcription, "_transcription_cache", {}),
            patch.dict(os.environ, {"DEEPGRAM_API_KEY": "offline-placeholder"}),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.client = MagicMock()
        self.client.__aenter__ = AsyncMock(return_value=self.client)
        self.client.__aexit__ = AsyncMock(return_value=False)
        self.client.post = AsyncMock()
        http.AsyncClient.reset_mock()
        http.AsyncClient.return_value = self.client
        db.voice_cost_add.reset_mock()

    def reply(self, data, status=200):
        self.client.post.return_value = SimpleNamespace(
            status_code=status, content=json.dumps(data).encode(),
        )

    async def check_response_and_reload(self, name, expected):
        data = payload(name)
        self.reply(data)
        result = await transcription.transcribe_audio(
            str(self.audio), "tg-new", session_name="orch", scope="/scope",
        )
        self.assertEqual(result, (expected, None))
        self.assertEqual(json.loads(self.cache.read_text()), {"tg-new": expected})
        self.client.post.assert_awaited_once()
        self.assertEqual(self.client.post.await_args.args, (
            "https://api.deepgram.com/v1/listen?model=nova-3&language=multi"
            "&smart_format=true&profanity_filter=false",
        ))
        self.assertEqual(self.client.post.await_args.kwargs["content"], b"offline-audio")
        db.voice_cost_add.assert_called_once_with(
            session_name="orch", scope="/scope", duration_sec=data["metadata"]["duration"],
            cost_usd=data["metadata"]["duration"] / 60 * 0.0052, file_id="tg-new",
        )
        transcription._transcription_cache = transcription._load_transcription_cache()
        os.environ.pop("DEEPGRAM_API_KEY", None)
        self.audio.unlink()
        self.assertEqual(await transcription.transcribe_audio(str(self.audio), "tg-new"), result)
        self.client.post.assert_awaited_once()
        db.voice_cost_add.assert_called_once()

    async def test_high_confidence_unchanged_and_reload(self):
        expected = payload("high")["results"]["channels"][0]["alternatives"][0]["transcript"]
        await self.check_response_and_reload("high", expected)

    async def test_low_confidence_marked_and_reload(self):
        await self.check_response_and_reload("low", MARKED)

    async def test_actual_handle_voice_body_forwards_annotations(self):
        # The complete bridge cannot import without aiogram and the omitted app
        # modules. Execute its real handler body with boundary dependencies mocked.
        source = ROOT / "app" / "tg_bridge.py"
        tree = ast.parse(source.read_text(encoding="utf-8"))
        handler = next(node for node in tree.body if isinstance(node, ast.AsyncFunctionDef)
                       and node.name == "handle_voice")
        handler.decorator_list = []
        session = SimpleNamespace(name="orch", scope="/scope")
        resolve = AsyncMock()
        namespace = {
            "types": SimpleNamespace(Message=object), "time": time,
            "logger": MagicMock(),
            "_resolve_orch": AsyncMock(return_value=("orch", session)),
            "_register_media": AsyncMock(return_value="media-token"),
            "_download_file": AsyncMock(return_value=str(self.audio)),
            "_media_name": lambda *args: "voice.oga",
            "_sender_tag": lambda msg: "", "_forward_meta": lambda msg: "",
            "_transcribe_audio": transcription.transcribe_audio, "_resolve_media": resolve,
        }
        exec(compile(ast.Module(body=[handler], type_ignores=[]), str(source), "exec"), namespace)
        self.reply(payload("low"))
        await namespace["handle_voice"](SimpleNamespace(voice=SimpleNamespace(
            file_id="tg-file", file_unique_id="tg-new", duration=3,
        )))
        resolve.assert_awaited_once_with("media-token", f"[voice: {self.audio} | {MARKED}]")

    async def test_legacy_cache_hit_without_key_or_audio(self):
        self.cache.write_text(json.dumps(payload("legacy_cache")))
        transcription._transcription_cache = transcription._load_transcription_cache()
        os.environ.pop("DEEPGRAM_API_KEY", None)
        self.audio.unlink()
        self.assertEqual(await transcription.transcribe_audio(str(self.audio), "tg-legacy-voice"), (
            "Проверь статус Orchestra.", None,
        ))
        http.AsyncClient.assert_not_called()
        db.voice_cost_add.assert_not_called()

    async def test_new_entries_preserve_legacy_cache(self):
        self.cache.write_text(json.dumps(payload("legacy_cache")))
        transcription._transcription_cache = transcription._load_transcription_cache()
        self.reply(payload("low"))
        self.assertEqual(await transcription.transcribe_audio(str(self.audio), "tg-new"), (MARKED, None))
        self.assertEqual(transcription._load_transcription_cache(), {
            "tg-legacy-voice": "Проверь статус Orchestra.", "tg-new": MARKED,
        })

    def test_strict_boundary_and_unknown_scores(self):
        for score, marked in (
            (0, True), (0.649999, True), (0.65, False), (1, False),
            (None, False), ("0.4", False), (True, False), (-1, False),
        ):
            with self.subTest(score=score):
                self.assertEqual(transcription._format_transcript({
                    "transcript": "Старт?", "confidence": 0.99,
                    "words": [{"word": "старт", "punctuated_word": "Старт?", "confidence": score}],
                }), f"{HEADER}\nСтарт[?]?" if marked else "Старт?")

    def test_missing_words_and_scores_are_not_invented(self):
        for words in (None, [], [{"word": "старт"}]):
            with self.subTest(words=words):
                self.assertEqual(transcription._format_transcript({
                    "transcript": "Старт?", "words": words,
                }), "Старт?")

    def test_repeated_words_and_closing_punctuation(self):
        self.assertEqual(transcription._format_transcript({
            "transcript": "Старт, старт, «старт».",
            "words": [
                {"word": "старт", "punctuated_word": "Старт,", "confidence": 0.99},
                {"word": "старт", "punctuated_word": "старт,", "confidence": 0.4},
                {"word": "старт", "punctuated_word": "«старт».", "confidence": 0.5},
            ],
        }), f"{HEADER}\nСтарт, старт[?], «старт[?]».")

    def test_unaligned_smart_format_retains_all_words(self):
        self.assertEqual(transcription._format_transcript({
            "transcript": "Wait 25 seconds.",
            "words": [
                {"word": "wait", "punctuated_word": "Wait", "confidence": 0.99},
                {"word": "twenty", "confidence": 0.4},
                {"word": "five", "confidence": 0.99},
                {"word": "seconds", "punctuated_word": "seconds.", "confidence": 0.99},
            ],
        }), f"{HEADER}\nWait twenty[?] five seconds.")

    def test_empty_transcript_is_not_noise(self):
        self.assertEqual(transcription._format_transcript({
            "transcript": "", "words": [{"word": "noise", "confidence": 0.1}],
        }), "")

    async def test_missing_audio_never_creates_http_client(self):
        self.audio.unlink()
        text, error = await transcription.transcribe_audio(str(self.audio))
        self.assertEqual(text, "")
        self.assertTrue(error.startswith("audio file unavailable: FileNotFoundError:"))
        http.AsyncClient.assert_not_called()

    async def test_upstream_error_is_not_cached_or_billed(self):
        self.reply({"err_msg": "offline upstream failure"}, status=400)
        self.assertEqual(await transcription.transcribe_audio(str(self.audio), "tg-new"), (
            "", "offline upstream failure",
        ))
        self.assertFalse(self.cache.exists())
        db.voice_cost_add.assert_not_called()

    def test_corrupt_cache_recovers(self):
        self.cache.write_text("{")
        self.assertEqual(transcription._load_transcription_cache(), {})
        transcription._save_transcription_cache({"recovered": MARKED})
        self.assertEqual(transcription._load_transcription_cache(), {"recovered": MARKED})


if __name__ == "__main__":
    print(f"Imported transcription: {transcription.__file__}", flush=True)
    print(f"Imported app paths: {list(app.__path__)}", flush=True)
    unittest.main(verbosity=2)
