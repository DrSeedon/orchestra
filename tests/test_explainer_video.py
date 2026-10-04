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
