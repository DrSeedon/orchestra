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


def test_say_rejects_latin_and_digits_before_synthesis():
    assert make.NOT_SPEAKABLE.search("кеш 20 минут")
    assert make.NOT_SPEAKABLE.search("кеш Together")
    assert not make.NOT_SPEAKABLE.search("Кеш живёт двадцать минут — у Тугезера.")
