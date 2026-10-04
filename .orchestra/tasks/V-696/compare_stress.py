#!/usr/bin/env python3
"""Record RUAccent and Vosk dictionary stress positions for a scene's say phrases."""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts" / "explainer_video"))
import make

VOWELS = "аеёиоуыэюя"
WORD = re.compile(r"[А-Яа-яЁё+]+")
PHONE_VOWEL = re.compile(r"[aeiouy][01]")


def main():
    scene = Path(sys.argv[1])
    output = Path(sys.argv[2])
    model = make.TTS_MODEL
    selected, probabilities = {}, {}
    with (model / "dictionary").open(encoding="utf-8") as dictionary:
        for line in dictionary:
            word, probability, phones = line.split(maxsplit=2)
            probability = float(probability)
            if probabilities.get(word, 0) < probability:
                selected[word] = phones.strip()
                probabilities[word] = probability

    accentizer = make.load_accentizer()
    rows = []
    for step in make.read_steps(scene, "ru"):
        marked = make.stress_text(step["say"], accentizer)
        raw_words = WORD.findall(step["say"])
        marked_words = WORD.findall(marked)
        for raw, annotated in zip(raw_words, marked_words, strict=True):
            word = raw.lower()
            if "+" in annotated:
                clean = annotated.replace("+", "").lower()
                ru_index = sum(ch.lower() in VOWELS for ch in annotated[:annotated.index("+")]) + 1
            else:
                clean, ru_index = annotated.lower(), None
            phones = selected.get(word)
            phone_stresses = [i + 1 for i, phone in enumerate(PHONE_VOWEL.findall(phones or "")) if phone.endswith("1")]
            differs = (phones is None and ru_index is not None) or (
                phones is not None and ru_index is not None and phone_stresses != [ru_index]
            )
            if differs:
                rows.append({
                    "phrase": step["say"], "word": raw, "vosk_stress_vowel_indices": phone_stresses,
                    "vosk_phones": phones, "ruaccent_word": annotated, "ruaccent_stress_vowel_index": ru_index,
                    "difference": "OOV" if phones is None else "stress differs",
                })
            if clean != word:
                rows.append({"phrase": step["say"], "word": raw, "ruaccent_word": annotated,
                             "difference": "RUAccent spelling changed"})
    output.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{len(rows)} differences -> {output}")
    for row in rows:
        print(json.dumps(row, ensure_ascii=False))


if __name__ == "__main__":
    main()
