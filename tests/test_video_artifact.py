"""Сверка распознанной озвучки с планом (scripts/video_artifact/make.py, V-681).

Это оракул приёмки ролика: если он не узнаёт фразу, произнесённую дословно, агент
перефразирует понятный текст или, наоборот, пропустит невнятный.
"""
import importlib.util
import json
import os
import shutil
from pathlib import Path
import sys
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/video_artifact"))
from video_text import caption_text, normalize_vosk_text, UnsupportedVoskSymbol
from tts_worker_tera import add_wordwise_russian_stress, compose_audio, render_phrase, split_pause_segments

MANIM_PY = Path.home() / ".local/share/orchestra-manim/env/bin/python"

spec = importlib.util.spec_from_file_location("video_artifact_make", ROOT / "scripts/video_artifact/make.py")
make = importlib.util.module_from_spec(spec)
spec.loader.exec_module(make)


@pytest.fixture(autouse=True)
def isolate_build_lock(tmp_path, monkeypatch):
    monkeypatch.setattr(make, "BUILD_LOCK_PATH", tmp_path / "video-build.lock")


def test_all_video_artifact_python_sources_compile():
    for path in sorted((ROOT / "scripts/video_artifact").rglob("*.py")):
        compile(path.read_bytes(), str(path), "exec")


def _mock_tts_installation(tmp_path, monkeypatch):
    python = tmp_path / "venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.write_text("test interpreter placeholder")
    model = tmp_path / "vosk-model"
    model.mkdir()
    (model / "model.onnx").touch()
    monkeypatch.setattr(make, "TTS_PYTHON", python)
    monkeypatch.setattr(make, "TTS_MODEL", model)


def test_deepgram_digits_latin_and_glued_words_match_screen_text():
    heard = make.tokens("а deepinfra иstreamlake держат кэш 7680 токенов")
    say, sub = "А Дип Инфра и Стрим Лейк держат кеш", "А DeepInfra и StreamLake держат кеш, 7 680 токенов"
    assert all(h is not None for h in make.align([sub], heard)[0])
    assert None in make.align([say], heard)[0]  # транслитерацию Deepgram пишет латиницей


def test_deepgram_spoken_numbers_match_digits_and_regular_words_stay_strict():
    heard = make.tokens("У нас 5 яблок и 125 слив")
    assert all(hit is not None for hit in make.align(["У нас пять яблок и сто двадцать пять слив"], heard)[0])
    assert None in make.align(["У нас пять груш"], heard)[0]
    assert make.tokens("две с половиной тысячи") == make.tokens("2 500")
    assert make.tokens("one hundred and twenty five") == make.tokens("125")
    skipped_number = make.align(["У нас пять яблок"], make.tokens("У нас яблок"))[0]
    assert make.word_scores("У нас пять яблок", skipped_number) == (1.0, 0.0, 1)
    missing_word = make.align(["У нас пять яблок"], make.tokens("У нас пять"))[0]
    assert make.word_scores("У нас пять яблок", missing_word)[0] < 1.0


def test_missing_word_is_reported_per_phrase():
    heard = make.tokens("один замер на ячейку")
    hits = make.align(["Оговорка: один замер", "на ячейку"], heard)
    assert hits[0][0] is None and hits[0][1:] == [0, 1]
    assert hits[1] == [2, 3]


def test_manual_stress_marker_is_ignored_by_deepgram_word_matching():
    assert make.tokens("П+осле проверки") == make.tokens("После проверки")


def test_manual_stress_marker_is_removed_from_scene_caption():
    import json

    with make.sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        page.add_init_script(make.VOICE_JS % json.dumps({"d": [1, 1]}))
        page.goto("data:text/html,<html><body></body></html>")
        captions = page.evaluate("""() => {
            const sayOnly = {say: "лим+ита"};
            const sub = {say: "лим+ита", sub: "лим+ита"};
            window.voice([sayOnly, sub]);
            return [sayOnly.x, sub.x];
        }""")
        browser.close()
    assert captions == ["лимита", "лим+ита"]


def test_caption_keeps_subtitle_verbatim_but_cleans_tts_stress_marker():
    assert caption_text({"say": "W+X словами", "sub": "W·X + b"}) == "W·X + b"
    assert caption_text({"say": "лим+ита", "sub": None}) == "лимита"


def test_vosk_text_normalizes_quote_dash_and_ellipsis_variants():
    assert normalize_vosk_text("Он сказал: «привет» — затем…") == 'Он сказал: "привет" - затем...'
    assert normalize_vosk_text("„привет“ – дальше ‑ снова") == '"привет" - дальше - снова'
    assert normalize_vosk_text("слово\u00a0слово") == "слово слово"


def test_unsupported_vosk_symbol_fails_during_step_validation():
    with pytest.raises(UnsupportedVoskSymbol, match="•"):
        normalize_vosk_text("фраза • продолжение")
    with pytest.raises(SystemExit, match="шаг 1: символ '•'"):
        make.check_steps([{"t": "x", "say": "фраза • дальше"}], "ru")


def test_tera_requires_spelled_numbers_and_preserves_manual_stress(tmp_path, monkeypatch):
    indexer = tmp_path / "unicode_indexer.json"
    table = [0] * 65_536
    table[ord("•")] = -1
    indexer.write_text(json.dumps(table))
    monkeypatch.setattr(make, "TERA_INDEXER", indexer)
    make._tera_character_table.cache_clear()

    assert make.check_steps([{"t": "ok", "say": "В две тысячи двадцать шестом году лим+ита."}], "ru", "tera")
    assert make.check_steps([{"t": "pause", "say": "Фраза [0.6] продолжается."}], "ru", "tera")
    with pytest.raises(SystemExit, match="поддерживает только TeraTTS"):
        make.check_steps([{"t": "pause", "say": "Фраза [0.6] дальше."}], "ru", "vosk")
    with pytest.raises(SystemExit):
        make.check_steps([{"t": "number", "say": "В 2026 году лимита."}], "ru", "tera")
    with pytest.raises(SystemExit, match="шаг 1: символ '•'"):
        make.check_steps([{"t": "bad", "say": "Фраза • дальше"}], "ru", "tera")


def test_tera_uses_its_own_stress_path_without_external_ruaccent(monkeypatch):
    monkeypatch.setattr(make.subprocess, "run", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError()))
    steps = [{"say": "лим+ита дальше"}]
    assert make.mark_stress(steps, "ru", enabled=True, engine="tera") == steps
    assert "_tts_text" not in steps[0]


def test_tera_manual_stress_does_not_disable_automatic_stress_for_other_words():
    class Accentizer:
        def process_all(self, word):
            return f"<{word}>"

    marked = add_wordwise_russian_stress("<ru>руч+ной остальные.</ru>", Accentizer())
    assert marked == "<ru>руч+ной <остальные.></ru>"


def test_tera_worker_patches_the_imported_normalizer_globals(monkeypatch):
    import types
    import tts_worker_tera

    module = types.ModuleType("remote_tera")
    namespace = {"add_russian_stress": lambda _text, _accentizer: "old"}
    exec("def normalize_text(): return add_russian_stress", namespace)
    module.normalize_text = namespace["normalize_text"]
    class Model:
        pass
    Model.__module__ = "remote_tera"
    monkeypatch.setitem(sys.modules, "remote_tera", module)

    tts_worker_tera.patch_wordwise_stress(Model())

    assert module.normalize_text() is add_wordwise_russian_stress


def test_tera_splits_only_at_sentence_ends_and_explicit_markers():
    segments = split_pause_segments("Сначала, затем: итог — вот он. Число 2.5 и т.д. остаются целыми! Ответ [0.6] готов")
    assert segments == [
        ("text", "Сначала, затем: итог — вот он."), ("gap", None),
        ("text", "Число 2.5 и т.д. остаются целыми!"), ("gap", None),
        ("text", "Ответ"), ("pause", 0.6), ("text", "готов"),
    ]


def test_tera_short_sentence_is_glued_to_the_next_one():
    assert split_pause_segments("Итак. Теперь посмотрим на результат.") == [("text", "Итак. Теперь посмотрим на результат.")]
    assert split_pause_segments("Теперь посмотрим на результат. Нет.") == [
        ("text", "Теперь посмотрим на результат."), ("gap", None), ("text", "Нет.")]


@pytest.mark.skipif(not MANIM_PY.exists(), reason="нужен numpy из окружения Manim")
def test_tera_sentence_gap_scales_with_rate_and_counts_model_tail(tmp_path):
    import subprocess

    code = """
import sys
sys.path.insert(0, %r)
import numpy as np
import tts_worker_tera as t
sr = 1000
speech = np.full(500, 0.5, dtype='float32')
tail = np.zeros(100, dtype='float32')
def gap_len(chunk, rate):
    out = t.compose_audio([('text', chunk), ('gap', None), ('text', speech)], sample_rate=sr, rate=rate)
    return len(out) - len(chunk) - len(speech)
bare = gap_len(speech, 1.0)
assert abs(bare - 420) <= 1, bare
assert abs(gap_len(speech, 1.2) - 350) <= 1
assert abs(gap_len(np.concatenate([speech, tail]), 1.0) - 320) <= 1
assert gap_len(np.concatenate([speech, np.zeros(900, dtype='float32')]), 1.0) == 0
""" % str(Path(make.__file__).parent)
    run = subprocess.run([str(MANIM_PY), "-c", code], capture_output=True, text=True, timeout=60, cwd=tmp_path)
    assert run.returncode == 0, run.stderr


def test_tera_explicit_pause_is_literal_silence():
    audio = compose_audio([("text", b"\x01\x00" * 100), ("pause", 0.6), ("text", b"\x01\x00" * 100)], sample_rate=1000)
    assert audio[200:200 + 1200] == b"\0" * 1200 and len(audio) == 1600


def test_silent_step_requires_hold_and_has_no_lead_time(tmp_path):
    silent = {"t": "Пауза", "say": "", "sub": None, "hold": 1.5}
    assert make.check_steps([silent], "ru", "tera") == [silent]
    with pytest.raises(SystemExit, match="без фразы say"):
        make.check_steps([{**silent, "hold": None}], "ru", "tera")
    clips = make.synthesize([silent], tmp_path / "cache", 1, 1.0)
    timing = make.plan([silent], clips, 1.0)
    assert timing["steps"][0]["phrase_start"] == 0
    assert timing["steps"][0]["d"] == 1.5


def test_numeral_run_warning_threshold_is_three_consecutive_terms(capsys):
    assert make.repeated_numeral_run("два и пять яблок") == 1
    assert make.repeated_numeral_run("двадцать пять тысяч") == 3
    make.warn_numeral_runs([{"say": "двадцать пять тысяч рублей"}])
    assert "подряд 3 числительных" in capsys.readouterr().err


def test_tera_worker_loads_one_model_for_parallel_phrase_jobs(tmp_path, monkeypatch, capsys):
    import importlib.util
    import io
    import json
    import sys
    import threading
    import types
    import wave

    spec = importlib.util.spec_from_file_location("tts_worker_tera", make.HERE / "tts_worker_tera.py")
    worker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(worker)
    snapshot = tmp_path / "tera" / "hub" / "models--TeraSpace--TeraTTSv2" / "snapshots" / worker.REVISION
    snapshot.mkdir(parents=True)
    monkeypatch.setenv("ORCHESTRA_TERA_SNAPSHOT", str(snapshot))
    monkeypatch.setenv("HF_MODULES_CACHE", "pre-test")
    barrier = threading.Barrier(2)
    loads = []

    class FakeModel:
        @classmethod
        def from_pretrained(cls, path, **kwargs):
            loads.append((path, kwargs))
            return cls()

        def generate_speech(self, _text, **_kwargs):
            barrier.wait(timeout=3)
            return b"audio"

        def save_wav(self, path, _audio):
            with wave.open(str(path), "wb") as output:
                output.setnchannels(1); output.setsampwidth(2); output.setframerate(44_100)
                output.writeframes(b"\0\0" * 8)

    monkeypatch.setitem(sys.modules, "transformers", types.SimpleNamespace(AutoModel=FakeModel))
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps([
        {"index": 0, "text": "Первая.", "voice": "ru_m5", "rate": 1.15, "stress": True, "out": str(tmp_path / "0.wav")},
        {"index": 1, "text": "Вторая.", "voice": "ru_m5", "rate": 1.15, "stress": True, "out": str(tmp_path / "1.wav")},
    ], ensure_ascii=False)))
    worker.main()
    assert len(loads) == 1
    assert loads[0][0] == str(snapshot)
    assert loads[0][1]["local_files_only"] is True
    assert os.environ["HF_MODULES_CACHE"] == str(tmp_path / "tera" / "modules")
    assert sorted(json.loads(line)["index"] for line in capsys.readouterr().out.splitlines()) == [0, 1]
    assert (tmp_path / "0.wav").is_file() and (tmp_path / "1.wav").is_file()


def test_tempo_speeds_pauses_but_keeps_phrase_inside_its_step(tmp_path):
    import wave
    clips = []
    for n, seconds in enumerate((2.0, 3.0)):
        clip = tmp_path / f"{n}.wav"
        with wave.open(str(clip), "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(make.SR)
            w.writeframes(b"\0\0" * int(seconds * make.SR))
        clips.append(clip)
    steps = [{"t": "а", "say": "а", "sub": None, "hold": None}, {"t": "б", "say": "б", "sub": None, "hold": 1.5}]
    slow, fast = make.plan(steps, clips, 1.0), make.plan(steps, clips, 1.5)
    for timing in (slow, fast):
        for row in timing["steps"]:
            assert row["step_start"] < row["phrase_start"] < row["phrase_end"] < row["step_start"] + row["d"]
        assert abs(sum(r["d"] for r in timing["steps"]) - timing["T"]) < 1e-6
    # паузы ×1/1.5, hold последнего шага — время досмотреть итог — не меняется
    assert abs(fast["steps"][0]["d"] - (2.0 + (make.LEAD + make.GAP) / 1.5)) < 1e-3
    assert abs(fast["steps"][1]["d"] - (3.0 + make.LEAD / 1.5 + 1.5)) < 1e-3


def test_parallel_synthesis_completions_keep_phrase_order_and_timing(tmp_path):
    import pytest
    import wave

    clips = []
    for n, seconds in enumerate((1.25, 2.5, 0.75)):
        clip = tmp_path / f"{n}.wav"
        with wave.open(str(clip), "wb") as output:
            output.setnchannels(1); output.setsampwidth(2); output.setframerate(make.SR)
            output.writeframes(b"\0\0" * int(seconds * make.SR))
        clips.append(clip)

    pending = {2: clips[2], 0: clips[0]}
    released, next_index = make.drain_ordered(pending, 0)
    assert released == [(0, clips[0])] and next_index == 1
    pending[1] = clips[1]
    released, next_index = make.drain_ordered(pending, next_index)
    assert released == [(1, clips[1]), (2, clips[2])] and next_index == 3

    steps = [{"t": str(i), "say": f"phrase {i}", "sub": None, "hold": None} for i in range(3)]
    timing = make.plan(steps, [path for _i, path in [(0, clips[0]), (1, clips[1]), (2, clips[2])]], 1.15)
    lengths = [row["phrase_end"] - row["phrase_start"] for row in timing["steps"]]
    assert lengths == pytest.approx([1.25, 2.5, 0.75])
    assert [row["say"] for row in timing["steps"]] == ["phrase 0", "phrase 1", "phrase 2"]
    assert timing["steps"][1]["step_start"] == timing["steps"][0]["d"]
    assert timing["steps"][2]["step_start"] == round(sum(row["d"] for row in timing["steps"][:2]), 3)


def test_manim_static_timing_tracks_remaining_budget_and_rejects_overrun():
    timing_spec = importlib.util.spec_from_file_location(
        "video_artifact_manim_timing", ROOT / "scripts/video_artifact/manim_timing.py")
    timing = importlib.util.module_from_spec(timing_spec)
    timing_spec.loader.exec_module(timing)
    source = """class Demo:
    def construct(self):
        with self.step(0):
            self.play(x, run_time=self.left() * 0.4)
            for n_left in range(2, 0, -1):
                per = self.left() * 0.5 / n_left
                self.play(x, run_time=per)
        with self.step(1):
            self.play(x, run_time=self.left() * 1.1)
"""
    analysis = timing.analyze(source, "Demo")
    checked = timing.check(analysis, [4.0, 3.0])
    assert checked["complete"]
    assert checked["overruns"] == [1]
    assert checked["steps"][0]["remaining_s"] > 0
    assert timing.selected_range(analysis, 0, 0) == (1, 3)


def test_build_lock_reports_owner_and_serializes_builds(tmp_path):
    import threading

    path = tmp_path / "build.lock"
    first_owned, release_first, second_owned, waiter_called = (threading.Event() for _ in range(4))
    messages = []

    def first_build():
        with make.build_lock(path, "first-scene"):
            first_owned.set()
            assert release_first.wait(3)

    def waiting(message):
        messages.append(message)
        waiter_called.set()

    def second_build():
        with make.build_lock(path, "second-scene", waiting):
            second_owned.set()

    first = threading.Thread(target=first_build)
    second = threading.Thread(target=second_build)
    first.start()
    assert first_owned.wait(3)
    second.start()
    assert waiter_called.wait(3)
    assert messages[0].startswith("жду сборку first-scene (pid ")
    assert not second_owned.is_set()
    release_first.set()
    first.join(3)
    second.join(3)
    assert second_owned.is_set()


def test_scene_sound_events_follow_planned_step_timing(tmp_path):
    import wave

    voice, music = tmp_path / "voice.wav", tmp_path / "bed.wav"
    voice.touch(); music.touch()
    clips = []
    for n in range(2):
        clip = tmp_path / f"{n}.wav"
        with wave.open(str(clip), "wb") as output:
            output.setnchannels(1); output.setsampwidth(2); output.setframerate(make.SR)
            output.writeframes(b"\0\0" * make.SR)
        clips.append(clip)
    steps = [
        {"t": "first", "say": "First step.", "sub": None, "hold": None, "events": []},
        {"t": "second", "say": "Second step.", "sub": None, "hold": None, "events": [
            {"id": "rise", "at": 0.75, "sound": "whoosh", "weight": "hero", "visual": "move"},
        ]},
    ]
    timing = make.plan(steps, clips, 1)

    sheet = make.sound_cues(timing, 30, voice, music, tmp_path / "kit")

    cue = sheet["cues"][0]
    assert cue["t"] == round(make.PRE + timing["steps"][1]["step_start"] + 0.75, 4)
    assert cue["frame"] == round(cue["t"] * 30)
    assert cue["sound"] == "whoosh" and cue["weight"] == "hero" and cue["visual"] == "move"
    assert sheet["music"]["file"] == str(music.resolve())
    assert sheet["voice"][0]["file"] == str(voice.resolve())


def test_say_rejects_latin_and_digits_before_synthesis():
    assert make.NOT_SPEAKABLE.search("кеш 20 минут")
    assert make.NOT_SPEAKABLE.search("кеш Together")
    assert not make.NOT_SPEAKABLE.search("Кеш живёт двадцать минут — у Тугезера.")


def test_english_voice_reads_latin_and_digits_but_rejects_cyrillic():
    import pytest
    ok = [{"t": "Merge", "say": "Merged #2: 48 tests green.", "sub": None, "hold": None}]
    assert make.check_steps(ok, "en") == ok
    with pytest.raises(SystemExit):
        make.check_steps([{"t": "x", "say": "Merged кеш", "sub": None, "hold": None}], "en")
    with pytest.raises(SystemExit):
        make.check_steps(ok, "ru")


def test_ruaccent_marks_text_before_it_reaches_vosk_synthesis(tmp_path, monkeypatch):
    import io
    import json
    import wave

    _mock_tts_installation(tmp_path, monkeypatch)
    monkeypatch.setattr(make.sys, "argv", ["make.py", "scene.html", "--out", str(tmp_path), "--stills", "--tts-engine", "vosk"])
    monkeypatch.setattr(make, "read_steps", lambda *_: [{"t": "Лимит", "say": "История лимита.", "sub": None, "hold": None}])
    before_path = list(make.sys.path)
    jobs = []
    accent_calls = []

    def fake_accent_process(argv, **kwargs):
        phrases = json.loads(kwargs["input"])
        accent_calls.append((argv, phrases, kwargs["check"], kwargs["capture_output"]))
        return make.subprocess.CompletedProcess(argv, 0, stdout=json.dumps(["История лим+ита."]), stderr="")

    monkeypatch.setattr(make.subprocess, "run", fake_accent_process)

    class FakeInput(io.StringIO):
        def __init__(self, ready):
            super().__init__()
            self.ready = ready
        def close(self):
            self.ready(json.loads(self.getvalue()))
            super().close()

    class FakeProcess:
        def __init__(self, *_args, **_kwargs):
            self.stdout = iter(())
            self.stdin = FakeInput(self.ready)
        def ready(self, payload):
            jobs.extend(payload)
            for job in payload:
                with wave.open(job["out"], "wb") as output:
                    output.setnchannels(1); output.setsampwidth(2); output.setframerate(make.SR)
                    output.writeframes(b"\0\0" * 32)
            self.stdout = iter(json.dumps({"index": job["index"]}) for job in payload)
        def wait(self):
            return 0
        def poll(self):
            return 0

    monkeypatch.setattr(make.subprocess, "Popen", FakeProcess)

    def fake_run(*argv, **kwargs):
        if "tts_worker.py" in argv[1]:
            jobs.extend(json.loads(kwargs["input"]))
            for job in jobs:
                with wave.open(job["out"], "wb") as output:
                    output.setnchannels(1); output.setsampwidth(2); output.setframerate(make.SR)
                    output.writeframes(b"\0\0" * 32)
        elif argv[0] == "ffmpeg":
            with wave.open(argv[-1], "wb") as output:
                output.setnchannels(1); output.setsampwidth(2); output.setframerate(make.SR)
                output.writeframes(b"\0\0" * 32)

    monkeypatch.setattr(make, "run", fake_run)
    monkeypatch.setattr(make, "plan", lambda *_: {"steps": [], "T": 0})
    monkeypatch.setattr(make, "voice_track", lambda *_: None)
    monkeypatch.setattr(make, "render", lambda *_args, **_kwargs: None)
    make.main()
    assert jobs[0]["text"] == "История лим+ита."
    assert accent_calls[0][0] == [str(make.TTS_PYTHON), str(make.HERE / "tts_worker_stress.py")]
    assert accent_calls[0][1] == ["История лимита."]
    assert make.sys.path == before_path


def test_manual_plus_words_are_not_sent_through_automatic_accenting(monkeypatch):
    import importlib.util

    calls = []

    class Accentizer:
        def process_all(self, text):
            calls.append(text)
            return text.upper()

    spec = importlib.util.spec_from_file_location("stress_worker", make.HERE / "tts_worker_stress.py")
    worker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(worker)
    accented = worker.stress_text("Привет, лим+ита готова.", Accentizer())
    assert accented == "ПРИВЕТ, лим+ита ГОТОВА."
    assert calls == ["Привет, ", " готова."]


def test_no_stress_flag_disables_ruaccent_in_cli(monkeypatch, tmp_path):
    monkeypatch.setattr(make.sys, "argv", ["make.py", "scene.html", "--out", str(tmp_path), "--stills", "--no-stress", "--tts-engine", "vosk"])
    monkeypatch.setattr(make, "read_steps", lambda *_: [{"t": "x", "say": "Фраза.", "sub": None, "hold": None}])
    monkeypatch.setattr(make.subprocess, "run", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError()))
    monkeypatch.setattr(make, "synthesize", lambda steps, *_args, **_kwargs: assert_unmarked(steps))
    monkeypatch.setattr(make, "plan", lambda *_: {"steps": [], "T": 0})
    monkeypatch.setattr(make, "voice_track", lambda *_: None)
    monkeypatch.setattr(make, "render", lambda *_args, **_kwargs: None)
    make.main()


def test_stress_only_shows_marked_phrases_without_synthesis(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(make.sys, "argv", ["make.py", "scene.html", "--out", str(tmp_path), "--stress-only", "--tts-engine", "vosk"])
    monkeypatch.setattr(make, "read_steps", lambda *_: [{"t": "x", "say": "До лимита.", "sub": None, "hold": None}])

    def mark(steps, *_args, **_kwargs):
        steps[0]["_tts_text"] = "До лим+ита."
        return steps

    monkeypatch.setattr(make, "mark_stress", mark)
    monkeypatch.setattr(make, "synthesize", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError()))
    make.main()
    assert (tmp_path / "scene.stress.txt").read_text() == "До лим+ита.\n"
    assert "До лим+ита." in capsys.readouterr().out


def assert_unmarked(steps):
    assert "_tts_text" not in steps[0]
    return []


def test_english_cli_branch_does_not_load_or_run_ruaccent(monkeypatch, tmp_path):
    monkeypatch.setattr(make.sys, "argv", ["make.py", "scene.html", "--out", str(tmp_path), "--stills", "--lang", "en"])
    monkeypatch.setattr(make, "read_steps", lambda *_: [{"t": "x", "say": "English words.", "sub": None, "hold": None}])
    monkeypatch.setattr(make.subprocess, "run", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError()))

    def synthesize(steps, *_args, **kwargs):
        assert "_tts_text" not in steps[0]
        assert kwargs["voice"] == "af_heart"
        return []

    monkeypatch.setattr(make, "synthesize", synthesize)
    monkeypatch.setattr(make, "plan", lambda *_: {"steps": [], "T": 0})
    monkeypatch.setattr(make, "voice_track", lambda *_: None)
    monkeypatch.setattr(make, "render", lambda *_args, **_kwargs: None)
    make.main()


@pytest.mark.parametrize(("selected", "expected"), [(None, "ru_m1"), ("f2", "ru_f2")])
def test_russian_cli_defaults_to_local_tera_voice(monkeypatch, tmp_path, selected, expected):
    argv = ["make.py", "scene.html", "--out", str(tmp_path), "--stills"]
    if selected:
        argv.extend(["--voice", selected])
    monkeypatch.setattr(make.sys, "argv", argv)
    monkeypatch.setattr(make, "read_steps", lambda *_: [{"t": "x", "say": "Сумма большая.", "sub": None, "hold": None}])
    monkeypatch.setattr(make, "TERA_INDEXER", tmp_path / "unicode_indexer.json")
    make.TERA_INDEXER.write_text(json.dumps([0] * 65_536))
    make._tera_character_table.cache_clear()
    monkeypatch.setattr(make, "tera_stress", lambda steps, enabled: [{**step, "_tts_text": step["say"]} for step in steps])
    monkeypatch.setattr(make, "synthesize", lambda _steps, *_args, **kwargs: assert_tera_default(kwargs, expected))
    monkeypatch.setattr(make, "plan", lambda *_: {"steps": [], "T": 0})
    monkeypatch.setattr(make, "voice_track", lambda *_: None)
    monkeypatch.setattr(make, "render", lambda *_args, **_kwargs: None)
    make.main()


def test_tera_build_without_local_model_fails_with_install_hint(tmp_path, monkeypatch):
    monkeypatch.setattr(make, "TTS_TERA_PYTHON", tmp_path / "missing-python")
    with pytest.raises(SystemExit, match="нет локальной TeraTTS"):
        make.tera_stress([{"say": "Фраза."}], enabled=True)


def assert_tera_default(kwargs, expected):
    assert kwargs["engine"] == "tera"
    assert kwargs["voice"] == expected
    assert kwargs["stress"] is True
    return []


def test_missing_ruaccent_fails_with_install_command(tmp_path, monkeypatch):
    import pytest

    _mock_tts_installation(tmp_path, monkeypatch)
    def missing(argv, **_kwargs):
        return make.subprocess.CompletedProcess(argv, 2, stdout="", stderr="RUACCENT_NOT_INSTALLED")

    monkeypatch.setattr(make.subprocess, "run", missing)
    with pytest.raises(SystemExit, match="ruaccent==1.5.8.3"):
        make.mark_stress([{"say": "Фраза."}], "ru", enabled=True)


def test_cache_key_changes_when_accented_text_changes(tmp_path, monkeypatch):
    import json
    import wave

    _mock_tts_installation(tmp_path, monkeypatch)
    jobs_seen = []

    def fake_run(*argv, **kwargs):
        if "tts_worker.py" in argv[1]:
            jobs = json.loads(kwargs["input"])
            jobs_seen.extend(job["text"] for job in jobs)
            for job in jobs:
                with wave.open(job["out"], "wb") as output:
                    output.setnchannels(1); output.setsampwidth(2); output.setframerate(make.SR)
                    output.writeframes(b"\0\0" * 32)
        elif argv[0] == "ffmpeg":
            with wave.open(argv[-1], "wb") as output:
                output.setnchannels(1); output.setsampwidth(2); output.setframerate(make.SR)
                output.writeframes(b"\0\0" * 32)

    monkeypatch.setattr(make, "run", fake_run)
    cache = tmp_path / "cache"
    original = [{"say": "История лимита."}]
    marked = [{"say": "История лимита.", "_tts_text": "История лим+ита."}]
    make.synthesize(original, cache, 1, 1.15)
    make.synthesize(marked, cache, 1, 1.15)
    assert jobs_seen == ["История лимита.", "История лим+ита."]


def test_parallel_synthesis_deduplicates_identical_cache_jobs(tmp_path, monkeypatch):
    import json
    import wave

    _mock_tts_installation(tmp_path, monkeypatch)
    jobs_seen = []

    def fake_run(*argv, **kwargs):
        if "tts_worker.py" in argv[1]:
            jobs = json.loads(kwargs["input"])
            jobs_seen.extend(jobs)
            for job in jobs:
                with wave.open(job["out"], "wb") as output:
                    output.setnchannels(1); output.setsampwidth(2); output.setframerate(make.SR)
                    output.writeframes(b"\0\0" * 32)
        elif argv[0] == "ffmpeg":
            with wave.open(argv[-1], "wb") as output:
                output.setnchannels(1); output.setsampwidth(2); output.setframerate(make.SR)
                output.writeframes(b"\0\0" * 32)

    monkeypatch.setattr(make, "run", fake_run)
    steps = [{"say": "Повторяющаяся фраза."}, {"say": "Повторяющаяся фраза."}]
    clips = make.synthesize(steps, tmp_path / "cache", 1, 1.15)
    assert len(jobs_seen) == 1
    assert clips == [clips[0], clips[0]] and clips[0].is_file()


def test_tera_cache_separates_voices_and_keeps_stress_setting(tmp_path, monkeypatch):
    import json
    import wave

    python = tmp_path / "venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.touch()
    snapshot = tmp_path / make.TERA_REVISION
    snapshot.mkdir()
    monkeypatch.setattr(make, "TTS_TERA_PYTHON", python)
    monkeypatch.setattr(make, "TERA_SNAPSHOT", snapshot)
    jobs_seen = []

    def fake_run(*argv, **kwargs):
        if argv[1].endswith("tts_worker_tera.py"):
            jobs = json.loads(kwargs["input"])
            jobs_seen.extend(jobs)
            for job in jobs:
                with wave.open(job["out"], "wb") as output:
                    output.setnchannels(1); output.setsampwidth(2); output.setframerate(44_100)
                    output.writeframes(b"\0\0" * 32)
        elif argv[0] == "ffmpeg":
            with wave.open(argv[-1], "wb") as output:
                output.setnchannels(1); output.setsampwidth(2); output.setframerate(make.SR)
                output.writeframes(b"\0\0" * 32)

    monkeypatch.setattr(make, "run", fake_run)
    cache = tmp_path / "cache"
    step = [{"say": "Одинаковая фраза."}]
    first = make.synthesize(step, cache, 1, 1.15, voice="ru_m5", engine="tera", stress=True)
    second = make.synthesize(step, cache, 1, 1.15, voice="ru_f1", engine="tera", stress=False)
    assert first[0] != second[0]
    assert [(job["voice"], job["stress"]) for job in jobs_seen] == [("ru_m5", True), ("ru_f1", False)]


_FONT_PROBE = """
import sys
sys.path.insert(0, {dir!r})
from manim import config
from manim_voice import VoiceScene, text
{body}
"""


def _manim(body: str, cwd: Path):
    import subprocess
    code = _FONT_PROBE.format(dir=str(Path(make.__file__).parent), body=body)
    return subprocess.run([str(MANIM_PY), "-c", code], capture_output=True, text=True, timeout=120, cwd=cwd)


@pytest.mark.skipif(not MANIM_PY.exists(), reason="окружение Manim не установлено")
def test_manim_missing_font_fails_instead_of_silent_substitution(tmp_path):
    run = _manim("text('x', font='No Such Face 9')", tmp_path)
    assert run.returncode != 0 and "не найден" in run.stderr


@pytest.mark.skipif(not MANIM_PY.exists(), reason="окружение Manim не установлено")
def test_default_theme_font_is_bundled_and_long_caption_fits_frame(tmp_path):
    run = _manim("""
class S(VoiceScene):
    STEPS = [{"t": "t", "say": "x"}]
s = S(); s.setup()
long = "Длинный субтитр проверяет, что перенос строк считается по реальной ширине шрифта, а не по числу знаков, " * 2
lines = s.wrap_caption(long)
widths = [s.text(l, 26).width for l in lines]
assert len(lines) > 1 and max(widths) <= config.frame_width - 2 * s.CAPTION_MARGIN, widths
print("ok")
""", tmp_path)
    assert run.returncode == 0 and "ok" in run.stdout, run.stderr


@pytest.mark.skipif(not MANIM_PY.exists(), reason="нужен numpy из окружения Manim")
def test_tera_level_phrase_removes_overs_and_evens_levels(tmp_path):
    import subprocess

    code = """
import sys
sys.path.insert(0, %r)
import numpy as np
import tts_worker_tera as t
rng = np.random.default_rng(1)
clipped = (rng.standard_normal(4000) * 0.9).astype('float32')
clipped[100] = 1.7
quiet = (rng.standard_normal(4000) * 0.03).astype('float32')
a, b = t.level_phrase(clipped), t.level_phrase(quiet)
for x in (a, b):
    assert np.abs(x).max() <= t.PEAK_CEILING + 1e-6
    assert (np.abs(np.rint(np.clip(x, -1, 1) * 32767)) >= 32767).sum() == 0
rms = lambda x: float((x.astype('float64') ** 2).mean() ** 0.5)
assert abs(20 * np.log10(rms(b) / t.RMS_TARGET)) < 0.1
assert rms(a) < rms(clipped)
""" % str(Path(make.__file__).parent)
    run = subprocess.run([str(MANIM_PY), "-c", code], capture_output=True, text=True, timeout=60, cwd=tmp_path)
    assert run.returncode == 0, run.stderr


def test_manim_text_cache_is_dropped_when_bundled_fonts_change(tmp_path, monkeypatch):
    fonts = tmp_path / "fonts"
    fonts.mkdir()
    (fonts / "a.ttf").write_bytes(b"font-v1")
    monkeypatch.setattr(make, "HERE", tmp_path)
    media = tmp_path / "media"
    (media / "texts").mkdir(parents=True)
    (media / "texts" / "stale.svg").write_text("dejavu glyphs")

    make.fresh_text_cache(media)  # no stamp yet: cache of unknown origin is dropped
    assert not (media / "texts").exists()

    (media / "texts").mkdir()
    (media / "texts" / "ok.svg").write_text("cmu glyphs")
    make.fresh_text_cache(media)
    assert (media / "texts" / "ok.svg").exists()

    (fonts / "a.ttf").write_bytes(b"font-v2")
    make.fresh_text_cache(media)
    assert not (media / "texts").exists()


def test_tera_render_phrase_synthesizes_each_sentence_once_and_never_the_gap():
    calls = []

    class FakeModel:
        def generate_speech(self, text, **kwargs):
            calls.append(text)
            return b"\x01\x00" * 100

    job = {"text": "Первое длинное предложение, с запятой. Второе предложение здесь [0.5] и конец.",
           "voice": "ru_m1", "rate": 1.0, "index": 0}
    audio = render_phrase(FakeModel(), job)
    assert calls == ["<ru>Первое длинное предложение, с запятой.</ru>",
                     "<ru>Второе предложение здесь</ru>", "<ru>и конец.</ru>"]
    assert not any("None" in call for call in calls)
    assert len(audio) == 3 * 200 + 2 * round(0.42 * 44_100) + 2 * round(0.5 * 44_100)


_THEME_SCENE = """<!doctype html><html><head><meta charset="utf-8"></head><body>
<div class="mv"><h1>Title</h1><div class="stg"><svg id="stage" viewBox="0 0 1280 590"></svg></div>
<div class="cap"><div id="capA"><b></b><span>caption</span></div><div id="capB"><b></b><span></span></div></div></div>
<script>
const STEPS = [{t: 'a', say: 'x', d: 1}, {t: 'b', say: 'y', d: 1}];
window.voice?.(STEPS);
const P = {t: 0, T: 2, S: [0, 1], seek(t) { this.t = t; }};
</script></body></html>"""


def _theme_probe(tmp_path, **kwargs):
    scene = tmp_path / "scene.html"
    scene.write_text(_THEME_SCENE)
    with make.sync_playwright() as playwright:
        browser, page = make.open_scene(playwright, scene, {"d": [1, 1]}, **kwargs)
        page.evaluate(make.SEEK_JS, 1.0)
        probe = page.evaluate("""() => ({
            theme: document.documentElement.dataset.theme,
            background: getComputedStyle(document.querySelector('.mv')).backgroundColor,
            heading: getComputedStyle(document.querySelector('.mv h1')).display,
            progress: document.getElementById('paper-progress')?.style.width ?? null,
        })""")
        browser.close()
    return probe


def test_video_frame_defaults_to_paper_theme_and_dark_stays_selectable(tmp_path):
    paper = _theme_probe(tmp_path)
    assert paper == {"theme": "paper", "background": "rgb(246, 247, 249)", "heading": "none", "progress": "50%"}
    dark = _theme_probe(tmp_path, theme="dark")
    assert dark["theme"] == "dark" and dark["background"] == "rgb(11, 14, 20)" and dark["progress"] is None


def test_paper_kit_is_pure_in_time_and_miniature_lands_on_the_zoomed_original(tmp_path):
    scene = tmp_path / "kit.html"
    scene.write_text("""<svg id="stage" viewBox="0 0 1280 590" width="1280" height="590" style="display:block">
            <g id="room"><rect width="1280" height="590" fill="#123"/></g>
            <rect id="orig" x="240" y="20" width="380" height="300"/></svg>""")
    with make.sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 590})
        page.add_init_script((ROOT / "scripts/video_artifact/paper.js").read_text())
        page.goto(scene.as_uri())
        result = page.evaluate("""() => {
            const view = {from: [640, 252], to: [640, 170], scale: 4.2, t0: 1, t1: 2};
            const pic = Paper.picture('room', {x: 96, y: 18, w: 1088, h: 556});
            const mini = document.createElementNS('http://www.w3.org/2000/svg', 'use');
            mini.setAttribute('href', '#orig');
            mini.setAttribute('transform', Paper.miniature(view));
            pic.cam.append(mini);
            const label = document.createElementNS('http://www.w3.org/2000/svg', 'text');
            document.getElementById('stage').append(label);
            const state = t => {
                Paper.camera(pic, t, view); Paper.brush(pic, t); Paper.type(label, 'тревога', t, 1, 2);
                return [pic.cam.getAttribute('transform'), pic.brush.style.strokeDashoffset, label.textContent];
            };
            const forward = state(1.6), later = state(3), back = state(1.6);
            state(3);  // зум закончен: копия в картине должна лечь на оригинал
            const a = mini.getBoundingClientRect(), b = document.getElementById('orig').getBoundingClientRect();
            return {same: JSON.stringify(forward) === JSON.stringify(back), forward, later,
                    gap: Math.max(...['x', 'y', 'width', 'height'].map(k => Math.abs(a[k] - b[k])))};
        }""")
        browser.close()
    assert result["same"], result
    assert result["forward"] != result["later"]
    assert result["gap"] < 1, result


def test_default_bed_comes_from_the_sound_kit_and_missing_bed_fails(tmp_path):
    kit = tmp_path / "kit"
    with pytest.raises(SystemExit):
        make.default_bed(kit)
    (kit / "bed").mkdir(parents=True)
    (kit / "bed" / "pad.wav").touch()
    (kit / "catalog.json").write_text(json.dumps({"types": {"bed": {"defaults": ["bed/pad"]}}}))
    assert make.default_bed(kit) == kit / "bed" / "pad.wav"


def test_music_bed_without_events_still_gets_a_mix_sheet(tmp_path):
    voice, bed = tmp_path / "voice.wav", tmp_path / "bed.wav"
    timing = {"T": 3.0, "steps": [{"step_start": 0.0, "d": 3.0, "events": []}]}
    sheet = make.sound_cues(timing, 30, voice, bed, tmp_path / "kit")
    assert sheet["cues"] == [] and sheet["music"]["file"] == str(bed.resolve())
    assert make.sound_cues(timing, 30, voice, None, tmp_path / "kit") == {}


@pytest.mark.skipif(not (make.SOUND_HOME / "catalog.json").exists(), reason="набор звуков не установлен")
@pytest.mark.timeout(600)
def test_default_bed_mixes_under_voice_and_passes_sound_qa(tmp_path):
    """Подложка набора по умолчанию тихо ложится под голос: qa.py (громкость, голос над музыкой, тишина) проходит."""
    import subprocess
    import wave
    import random

    rng = random.Random(7)
    clips = []
    for n in range(3):
        clip = tmp_path / f"{n}.wav"
        # речеподобный шум: 2,4 с слогов по 0,15 с с короткими провалами
        frames = bytearray()
        for k in range(int(2.4 * make.SR)):
            on = (k // int(0.15 * make.SR)) % 4 != 3
            sample = int(rng.gauss(0, 6000)) if on else 0
            frames += max(-32768, min(32767, sample)).to_bytes(2, "little", signed=True)
        with wave.open(str(clip), "wb") as output:
            output.setnchannels(1); output.setsampwidth(2); output.setframerate(make.SR)
            output.writeframes(bytes(frames))
        clips.append(clip)
    steps = [{"t": str(n), "say": "фраза", "sub": None, "hold": None, "events": []} for n in range(3)]
    timing = make.plan(steps, clips, 1)
    out, name = tmp_path / "out", "scene"
    out.mkdir()
    make.voice_track(timing, clips, out / f"{name}.voice.wav")
    total = make.PRE + timing["T"] + make.POST
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c=#f6f7f9:s=320x180:d={total}:r=30",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(out / f"{name}.video.mp4")], check=True)
    sheet = make.sound_cues(timing, 30, out / f"{name}.voice.wav", make.default_bed())
    make.sound_mix(out, name, sheet)
    mp4 = make.mux(out, name, sound=True)
    qa = subprocess.run([make.UV_BIN, "run", "--script", str(make.SOUND_SCRIPTS / "qa.py"), str(mp4),
                         "--audio", str(out / f"{name}.sound")], capture_output=True, text=True)
    assert qa.returncode == 0, qa.stdout + qa.stderr
    assert "pass  silence" in qa.stdout and "pass  voice" in qa.stdout


def test_text_change_ghost_follows_the_moved_label(tmp_path):
    """V-922: при смене текста уходящее слово рисует копия; она должна стоять там же, где подпись сейчас,
    а не там, где подпись была в начале ролика (иначе старое слово мелькает в другом месте кадра)."""
    import re as _re

    md = (ROOT / ".orchestra/pipelines/default/prompts/skills/html-artifacts/references/animation.md").read_text()
    html = _re.search(r"```html motion-template\n(.*?)```", md, _re.S).group(1)
    html = _re.sub(r'<svg id="stage".*?</svg>', '<svg id="stage" viewBox="0 0 900 200">'
                   '<text id="lbl" x="100" y="50" font-size="40">old</text></svg>', html, count=1, flags=_re.S)
    html = _re.sub(r"const STEPS = \[.*?\];\n", "const STEPS = [{d: 1, t: 'move', x: '', set: {lbl: {x: 600, 'font-size': 20}}},"
                   " {d: 1, t: 'rename', x: '', set: {lbl: {text: 'new'}}}];\n", html, count=1, flags=_re.S)
    scene = tmp_path / "ghost.html"
    scene.write_text(html)
    with make.sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        page.goto(scene.as_uri())
        ghost = page.evaluate("""() => { P.seek(1.03);
            const e = document.getElementById('lbl'), g = e.nextElementSibling;
            return {text: g.textContent, fo: g.getAttribute('fill-opacity'), visible: +g.getAttribute('fill-opacity') > 0,
                    x: g.getAttribute('x'), size: g.getAttribute('font-size'), ex: e.getAttribute('x')}; }""")
        browser.close()
    assert ghost["text"] == "old" and ghost["visible"], ghost
    assert ghost["x"] == ghost["ex"] == "600" and ghost["size"] == "20", ghost


def test_stress_dictionary_fixes_known_misses_and_blocks_unmarked_homographs(tmp_path):
    table = tmp_path / "stress.json"
    table.write_text(json.dumps({"fixed": {"хода": "х+ода", "после": "п+осле"}, "homographs": ["стоит"]}))
    steps = [{"say": "Со следующего хода. После паузы.", "sub": None}, {"say": "Блок сто+ит в конце.", "sub": None}]
    done = make.apply_stress_dictionary(steps, table)
    assert done[0]["say"] == "Со следующего х+ода. П+осле паузы." and done[0]["sub"] == "Со следующего хода. После паузы."
    assert done[1]["say"] == "Блок сто+ит в конце."
    with pytest.raises(SystemExit) as stop:
        make.apply_stress_dictionary([{"say": "Это стоит денег.", "sub": None}], table)
    assert "стоит" in str(stop.value)


def test_bundled_stress_dictionary_is_valid_and_marks_each_fix():
    table = json.loads(make.STRESS_DICT.read_text())
    assert table["homographs"] and all(word == word.lower() for word in table["homographs"])
    assert all("+" in value and value.replace("+", "") == key for key, value in table["fixed"].items())


def _scenes_page(tmp_path, body):
    page_file = tmp_path / "scenes.html"
    page_file.write_text(f'<svg id="stage" viewBox="0 0 1280 590" width="1280" height="590" style="display:block">{body}</svg>')
    return page_file


def _with_kit(playwright, page_file):
    browser = playwright.chromium.launch()
    page = browser.new_page(viewport={"width": 1280, "height": 590})
    page.add_init_script(f"window.__PAPER_SCENES = {json.dumps(make.paper_scenes(), ensure_ascii=False)};")
    page.add_init_script((ROOT / "scripts/video_artifact/paper.js").read_text())
    page.goto(page_file.as_uri())
    return browser, page


def test_bundled_scenes_stand_on_supports_and_zoom_onto_the_diagram(tmp_path):
    """V-935: в готовых сценах ничего не висит в воздухе, и наезд на экран сцены кончается ровно на схеме."""
    page_file = _scenes_page(tmp_path, '<g id="pic"></g><rect id="dia" x="90" y="40" width="1100" height="390"/>')
    with make.sync_playwright() as playwright:
        browser, page = _with_kit(playwright, page_file)
        results = page.evaluate("""() => Object.keys(Paper.SCENES).map(name => {
            const g = document.getElementById('pic'); g.removeAttribute('mask'); delete g._paper; g.innerHTML = '';
            const pic = Paper.picture(g, {x: 96, y: 18, w: 1088, h: 556}, {scene: name});
            const view = Paper.view(name), slot = Paper.mini(pic, 'dia', view);
            Paper.camera(pic, 2, {...view, t0: 0, t1: 1});
            const a = slot.lastElementChild.getBoundingClientRect(), b = document.getElementById('dia').getBoundingClientRect();
            return {name, issues: Paper.supportIssues(), gap: Math.max(...['x', 'y', 'width', 'height'].map(k => Math.abs(a[k] - b[k]))),
                    supported: g.querySelectorAll('[data-on]').length};
        })""")
        browser.close()
    assert len(results) >= 3
    for r in results:
        assert r["issues"] == [] and r["supported"] >= 1 and r["gap"] < 1, r


def test_support_check_reports_an_object_floating_beside_its_support(tmp_path):
    page_file = _scenes_page(tmp_path, '<rect id="desk" x="400" y="350" width="500" height="40"/>'
                                       '<g data-on="desk"><rect x="420" y="300" width="40" height="50"/></g>'
                                       '<g data-on="desk"><rect x="960" y="300" width="40" height="52"/></g>')
    with make.sync_playwright() as playwright:
        browser, page = _with_kit(playwright, page_file)
        issues = page.evaluate("Paper.supportIssues()")
        browser.close()
    assert len(issues) == 1 and "desk" in issues[0]


def _sound_fixture(tmp_path, sound="click.wav"):
    """Voice, music bed and one click on disk, plus a cue sheet whose events use only files, so no kit is needed."""
    import math
    import random
    import wave

    rng = random.Random(3)

    def write(name, seconds, sample):
        with wave.open(str(tmp_path / name), "wb") as output:
            output.setnchannels(1); output.setsampwidth(2); output.setframerate(make.SR)
            output.writeframes(b"".join(int(max(-32768, min(32767, sample(i)))).to_bytes(2, "little", signed=True)
                                        for i in range(int(seconds * make.SR))))

    write("voice.wav", 6, lambda i: rng.gauss(0, 5000) if (i // 7200) % 4 != 3 and i > make.SR else 0)
    write("music.wav", 8, lambda i: 2500 * math.sin(2 * math.pi * 220 * i / make.SR) + rng.gauss(0, 800))
    write("click.wav", 0.3, lambda i: 22000 * math.exp(-i / 1500) * math.sin(2 * math.pi * 1800 * i / make.SR))
    cues = {"fps": 30, "duration_s": 7.0, "energy": "calm", "lufs": -18, "kit": str(tmp_path),
            "music": {"file": str(tmp_path / "music.wav"), "start_s": 0, "loop": True, "fade_out_s": 1.0},
            "voice": [{"file": str(tmp_path / "voice.wav"), "start_s": 0}],
            "cues": [{"id": "hit1", "t": 3.0, "frame": 90, "sound": sound if sound.startswith("synth:") else str(tmp_path / sound), "weight": "hero", "visual": "cut"},
                     {"id": "tick2", "t": 5.0, "frame": 150, "sound": str(tmp_path / "click.wav"), "weight": "support"}]}
    (tmp_path / "cues.json").write_text(json.dumps(cues))
    return tmp_path / "cues.json"


def _uv_script(script, *args):
    import subprocess

    return subprocess.run([make.UV_BIN, "run", "--script", str(make.SOUND_SCRIPTS / script), *map(str, args)],
                          capture_output=True, text=True)


needs_sound_tools = pytest.mark.skipif(shutil.which("ffmpeg") is None or not Path(make.UV_BIN).exists(),
                                       reason="нужны ffmpeg и uv")


@needs_sound_tools
@pytest.mark.timeout(600)
def test_mixer_builds_a_generated_synth_cue(tmp_path):
    """Personal-use videos may carry generated sound (owner decision, 2026-10-18)."""
    cues = _sound_fixture(tmp_path, sound="synth:pluck")
    run = _uv_script("mix.py", cues, "--out", tmp_path / "audio")
    assert run.returncode == 0, run.stdout + run.stderr
    assert (tmp_path / "audio" / "mix.wav").exists()
    events = json.loads((tmp_path / "audio" / "mix-report.json").read_text())["events"]
    assert events[0]["sound"] == "synth:pluck"


def test_music_without_source_or_license_is_accepted_with_a_note(tmp_path):
    bed = tmp_path / "bed.wav"
    assert make.music_credit_line(bed, None, None, custom=True) == "bed.wav: source not recorded"
    assert make.music_credit_line(bed, "Author, title", "", custom=True) == "bed.wav: Author, title"
    assert make.music_credit_line(bed, "Author", "CC-BY", custom=True) == "bed.wav: Author, CC-BY"


def test_credits_list_music_and_every_kit_recording_used(tmp_path):
    kit = tmp_path / "kit"
    (kit / "whoosh").mkdir(parents=True)
    (kit / "catalog.json").write_text(json.dumps({"sounds": [{"file": "whoosh/a.wav", "credit": '"Swipe" by Someone'}]}))
    report = tmp_path / "mix-report.json"
    report.write_text(json.dumps({"events": [{"files": [str(kit / "whoosh/a.wav")]}, {"files": [str(tmp_path / "own.wav")]}, {"files": ["synth:pluck"]}]}))
    credits = make.write_credits(tmp_path, "scene", "bed.wav: Author, CC0", report, kit).read_text()
    assert "Music: bed.wav: Author, CC0" in credits
    assert '"Swipe" by Someone, CC0' in credits and "own.wav: source not recorded" in credits
    assert "generated: synth:pluck" in credits


@needs_sound_tools
@pytest.mark.timeout(900)
def test_qa_writes_frames_around_events_and_at_most_five_timestamps(tmp_path):
    import subprocess

    cues = _sound_fixture(tmp_path)
    audio = tmp_path / "audio"
    assert _uv_script("mix.py", cues, "--out", audio).returncode == 0
    video = tmp_path / "v.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=#f6f7f9:s=320x180:d=7:r=30", "-i",
                    str(audio / "mix.wav"), "-c:v", "mpeg4", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(video)], check=True)
    _uv_script("qa.py", video, "--audio", audio)       # fixture checks may FAIL; the ear-check output is what is under test
    ear = audio / "ear-check"
    for event in ("hit1", "tick2"):
        assert (ear / f"{event}-before.png").stat().st_size > 0 and (ear / f"{event}-after.png").stat().st_size > 0
    picks = json.loads((ear / "ear-check.json").read_text())["timestamps"]
    assert 1 <= len(picks) <= 5 and all(item["reason"].strip() for item in picks)
    assert [item["t"] for item in picks] == sorted(item["t"] for item in picks)


_VERTICAL_SCENE = """<!doctype html><html><head><meta charset="utf-8"></head><body>
<div class="mv"><h1>Title</h1><div class="stg"><svg id="stage" viewBox="0 0 720 720"></svg></div>
<div class="cap"><div id="capA"><b></b><span id="capX">%s</span></div><div id="capB"><b></b><span></span></div></div></div>
<script>
const STEPS = [{t: 'a', say: 'x', d: 1}, {t: 'b', say: 'y', d: 1}];
window.voice?.(STEPS);
const P = {t: 0, T: 2, S: [0, 1], seek(t) { this.t = t; }};
</script></body></html>"""


def _vertical_probe(tmp_path, monkeypatch, caption="Рестарт теперь просто пауза, а не потеря работы агентов.", hook=None, t=0.0):
    monkeypatch.setenv("VIDEO_ARTIFACT_FORMAT", "vertical")
    if hook:
        monkeypatch.setenv("VIDEO_ARTIFACT_HOOK", hook)
    scene = tmp_path / "scene.html"
    scene.write_text(_VERTICAL_SCENE % caption)
    with make.sync_playwright() as playwright:
        browser, page = make.open_scene(playwright, scene, {"d": [1, 1]})
        page.evaluate(make.SEEK_JS, t)
        size = page.screenshot()[16:24]
        issues = make.safe_area_issues(page, "probe")
        hook_state = page.evaluate("""() => { const h = document.getElementById('paper-hook');
            return h && {opacity: h.style.opacity, visibility: h.style.visibility, text: h.textContent}; }""")
        browser.close()
    return int.from_bytes(size[:4], "big"), int.from_bytes(size[4:], "big"), issues, hook_state


def test_vertical_format_renders_1080x1920_with_caption_in_safe_area_and_landscape_stays_default(tmp_path, monkeypatch):
    width, height, issues, _ = _vertical_probe(tmp_path, monkeypatch)
    assert (width, height) == (1080, 1920) and issues == []
    monkeypatch.delenv("VIDEO_ARTIFACT_FORMAT")
    assert make.frame_format() == "landscape"
    scene = tmp_path / "scene.html"
    with make.sync_playwright() as playwright:
        browser, page = make.open_scene(playwright, scene, {"d": [1, 1]})
        assert len(page.screenshot()) > 0 and page.evaluate("[innerWidth * devicePixelRatio, innerHeight * devicePixelRatio]") == [1920, 1080]
        browser.close()


def test_vertical_caption_too_long_for_the_safe_area_fails_the_build_check(tmp_path, monkeypatch):
    _, _, issues, _ = _vertical_probe(tmp_path, monkeypatch, caption="очень длинная подпись " * 14)
    assert issues and "субтитр" in issues[0]


def test_hook_shows_in_the_first_frame_inside_the_safe_area_and_fades_out(tmp_path, monkeypatch):
    hook = "Ночная заявка — ответ за 40 секунд"
    _, _, issues, shown = _vertical_probe(tmp_path, monkeypatch, hook=hook, t=0.0)
    assert issues == [] and shown["text"] == hook and float(shown["opacity"]) == 1 and shown["visibility"] == "visible"
    _, _, _, gone = _vertical_probe(tmp_path, monkeypatch, hook=hook, t=make.HOOK_SECONDS + 0.1)
    assert gone["visibility"] == "hidden"


def test_hook_without_a_number_is_refused_before_any_work(tmp_path, monkeypatch):
    monkeypatch.setattr(make.sys, "argv", ["make.py", "scene.html", "--out", str(tmp_path), "--format", "vertical", "--hook", "Рестарт без потерь"])
    monkeypatch.setattr(make, "read_steps", lambda *_: pytest.fail("сборка началась до проверки хука"))
    with pytest.raises(SystemExit, match="цифры"):
        make.main()


@pytest.mark.skipif(not MANIM_PY.exists(), reason="окружение Manim не установлено")
def test_manim_caption_wraps_inside_the_narrow_vertical_frame(tmp_path):
    run = _manim("""
config.frame_size = (1080, 1920)
config.frame_width = config.frame_height * config.aspect_ratio  # как делает разбор -r в CLI
class S(VoiceScene):
    STEPS = [{"t": "t", "say": "x"}]
s = S(); s.setup()
lines = s.wrap_caption("Перезапуск теперь просто пауза, а не потеря работы агентов и заданий")
widest = max(s.text(l, 26).width for l in lines)
assert config.frame_width == 4.5 and len(lines) >= 3 and widest <= 4.5 - 2 * s.CAPTION_MARGIN, (config.frame_width, lines, widest)
print("ok")
""", tmp_path)
    assert run.returncode == 0 and "ok" in run.stdout, run.stderr


@needs_sound_tools
def test_pace_script_counts_pauses_by_length_on_a_voice_track(tmp_path):
    import subprocess

    track = tmp_path / "voice.wav"
    gaps = "between(t,1,1.2)+between(t,2.2,2.8)+between(t,3.8,5)+between(t,6,8)+between(t,9,9.4)"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                    f"anoisesrc=d=10.4:c=white:a=0.3:r=16000,volume=0:enable='{gaps}'", str(track)], check=True)
    run = subprocess.run([make.UV_BIN, "run", "--script", str(make.HERE / "pace.py"), str(track)], capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    assert "pauses 5 " in run.stdout and ">=0.5 s: 17.3/min   >=1 s: 11.5/min   >=2 s: 5.8/min" in run.stdout
