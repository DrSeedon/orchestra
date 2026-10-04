#!/usr/bin/env python3
"""Short VPS integration check for the isolated RUAccent TTS worker."""
import importlib.util
import json
from pathlib import Path

root = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("explainer_make", root / "scripts/explainer_video/make.py")
make = importlib.util.module_from_spec(spec)
spec.loader.exec_module(make)
steps = [
    {"say": "Шлюз задерживает запуск новых воркеров до исчерпания лимита."},
    {"say": "П+осле проверки продолжаем."},
    {"say": "Вы описываете задачу оркестратору обычными словами."},
]
make.mark_stress(steps, "ru", enabled=True)
texts = [step["_tts_text"] for step in steps]
assert "лим+ита" in texts[0], texts[0]
assert texts[1].startswith("П+осле "), texts[1]
assert "оркестр+атору" in texts[2], texts[2]
print(json.dumps(texts, ensure_ascii=False, indent=2))
