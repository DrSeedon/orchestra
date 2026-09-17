#!/usr/bin/env python3
"""Все строковые литералы файла, похожие на надписи, — сырьё для словаря."""
import re, sys
from pathlib import Path

src = Path(sys.argv[1]).read_text(encoding='utf-8')
LIT = re.compile(r"""(?<![\w\\])(?:'((?:[^'\\\n]|\\.)*)'|"((?:[^"\\\n]|\\.)*)")""")
CYR = re.compile(r'[А-Яа-яЁё]')
WORDY = re.compile(r'[A-Za-z]{2,}')

seen = {}
for i, line in enumerate(src.split('\n'), 1):
    s = line.lstrip()
    if s.startswith('//') or s.startswith('*'):
        continue
    for m in LIT.finditer(line):
        text = m.group(1) if m.group(1) is not None else m.group(2)
        if not text or CYR.search(text) or not WORDY.search(text):
            continue
        if len(text) > 120:
            continue
        # отсеиваем явный код: селекторы, классы, ключи, пути, события
        if re.fullmatch(r'[\w.#\[\]=\'"()\-, :>*^$~|]+', text) and ' ' not in text.strip():
            if not re.fullmatch(r'[A-Z][A-Za-z]+', text):
                continue
        if text.startswith(('/', './', 'http', 'application/', 'text/', 'data:')):
            continue
        seen.setdefault(text, []).append(i)

for text, lines in seen.items():
    print(f"{','.join(map(str, lines[:4]))}\t{text!r}")
print(f'# уникальных: {len(seen)}', file=sys.stderr)
