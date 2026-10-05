"""Сверка распознанной озвучки с планом (scripts/explainer_video/make.py, V-681).

Это оракул приёмки ролика: если он не узнаёт фразу, произнесённую дословно, агент
перефразирует понятный текст или, наоборот, пропустит невнятный.
"""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("explainer_make", ROOT / "scripts/explainer_video/make.py")
make = importlib.util.module_from_spec(spec)
spec.loader.exec_module(make)


def test_deepgram_digits_latin_and_glued_words_match_screen_text():
    heard = make.tokens("а deepinfra иstreamlake держат кэш 7680 токенов")
    say, sub = "А Дип Инфра и Стрим Лейк держат кеш", "А DeepInfra и StreamLake держат кеш, 7 680 токенов"
    assert all(h is not None for h in make.align([sub], heard)[0])
    assert None in make.align([say], heard)[0]  # транслитерацию Deepgram пишет латиницей


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
    assert captions == ["лимита", "лимита"]


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
    import json
    import wave

    monkeypatch.setattr(make.sys, "argv", ["make.py", "scene.html", "--out", str(tmp_path), "--stills"])
    monkeypatch.setattr(make, "read_steps", lambda *_: [{"t": "Лимит", "say": "История лимита.", "sub": None, "hold": None}])
    before_path = list(make.sys.path)
    jobs = []
    accent_calls = []

    def fake_accent_process(argv, **kwargs):
        phrases = json.loads(kwargs["input"])
        accent_calls.append((argv, phrases, kwargs["check"], kwargs["capture_output"]))
        return make.subprocess.CompletedProcess(argv, 0, stdout=json.dumps(["История лим+ита."]), stderr="")

    monkeypatch.setattr(make.subprocess, "run", fake_accent_process)

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
    monkeypatch.setattr(make.sys, "argv", ["make.py", "scene.html", "--out", str(tmp_path), "--stills", "--no-stress"])
    monkeypatch.setattr(make, "read_steps", lambda *_: [{"t": "x", "say": "Фраза.", "sub": None, "hold": None}])
    monkeypatch.setattr(make.subprocess, "run", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError()))
    monkeypatch.setattr(make, "synthesize", lambda steps, *_args, **_kwargs: assert_unmarked(steps))
    monkeypatch.setattr(make, "plan", lambda *_: {"steps": [], "T": 0})
    monkeypatch.setattr(make, "voice_track", lambda *_: None)
    monkeypatch.setattr(make, "render", lambda *_args, **_kwargs: None)
    make.main()


def test_stress_only_shows_marked_phrases_without_synthesis(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(make.sys, "argv", ["make.py", "scene.html", "--out", str(tmp_path), "--stress-only"])
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


def test_missing_ruaccent_fails_with_install_command(monkeypatch):
    import pytest

    def missing(argv, **_kwargs):
        return make.subprocess.CompletedProcess(argv, 2, stdout="", stderr="RUACCENT_NOT_INSTALLED")

    monkeypatch.setattr(make.subprocess, "run", missing)
    with pytest.raises(SystemExit, match="ruaccent==1.5.8.3"):
        make.mark_stress([{"say": "Фраза."}], "ru", enabled=True)


def test_cache_key_changes_when_accented_text_changes(tmp_path, monkeypatch):
    import json
    import wave

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
