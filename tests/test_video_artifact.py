"""Сверка распознанной озвучки с планом (scripts/video_artifact/make.py, V-681).

Это оракул приёмки ролика: если он не узнаёт фразу, произнесённую дословно, агент
перефразирует понятный текст или, наоборот, пропустит невнятный.
"""
import importlib.util
import json
import os
from pathlib import Path
import sys
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/video_artifact"))
from video_text import caption_text, normalize_vosk_text, UnsupportedVoskSymbol
from tts_worker_tera import add_wordwise_russian_stress, compose_audio, split_pause_segments

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


def test_tera_punctuation_and_explicit_pause_insert_silence_in_samples():
    segments = split_pause_segments("Раз, два. Ответ [0.6] готов")
    assert [value for kind, value in segments if kind == "pause"] == [0.33, 0.63, 0.6]
    pieces = [("text", b"\x01\x00" * 100) if kind == "text" else (kind, value)
              for kind, value in segments]
    audio = compose_audio(pieces, sample_rate=1000)
    cursor = 100 * 2
    for duration in (0.33, 0.63, 0.6):
        count = round(duration * 1000) * 2
        assert audio[cursor:cursor + count] == b"\0" * count
        cursor += count + 100 * 2
    assert len(audio) == cursor


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
    monkeypatch.setattr(make, "synthesize", lambda _steps, *_args, **kwargs: assert_tera_default(kwargs, expected))
    monkeypatch.setattr(make, "plan", lambda *_: {"steps": [], "T": 0})
    monkeypatch.setattr(make, "voice_track", lambda *_: None)
    monkeypatch.setattr(make, "render", lambda *_args, **_kwargs: None)
    make.main()


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


MANIM_PY = Path.home() / ".local/share/orchestra-manim/env/bin/python"
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
def test_default_cmu_serif_is_bundled_and_long_caption_fits_frame(tmp_path):
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
