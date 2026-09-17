#!/usr/bin/env python3
"""Кандидаты в надписи интерфейса из шаблонов и клиентских сценариев.

Вспомогательный инструмент для СОСТАВЛЕНИЯ словаря, а не приёмка: он смотрит в
исходный текст, а норма говорит про отрисованный экран. Приёмка — audit_screens.py.
"""
import re, sys, glob, json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
FILES = sorted(glob.glob(str(ROOT / 'app/static/js/*.js'))) + [
    str(ROOT / 'app/templates/dashboard.html'),
    str(ROOT / 'app/templates/login.html'),
]

# Текст между > и < ; значения видимых атрибутов; присваивания подписей; alert/confirm
PATTERNS = [
    re.compile(r'>\s*([^<>{}`\'"$]{2,90}?)\s*<'),
    re.compile(r'''(?:title|placeholder|aria-label|alt)\s*=\s*\\?["'`]([^"'`<>$]{2,90})'''),
    re.compile(r'''(?:textContent|innerText|\.title|\.placeholder|\.label)\s*=\s*["'`]([^"'`$]{2,90})["'`]'''),
    re.compile(r'''(?:alert|confirm)\(\s*["'`]([^"'`$]{3,140})'''),
    re.compile(r''':\s*["']([A-Z][A-Za-z ./&+-]{2,40})["']\s*[,}]'''),
]
LATIN = re.compile(r'[A-Za-z]{2,}')
CYR = re.compile(r'[А-Яа-яЁё]')
# Технический мусор, который не является надписью
NOISE = re.compile(
    r'^(?:[a-z-]+:[^ ]*$|#[0-9a-fA-F]{3,8}$|\d|https?://|/|\.\.?/)'
)

def looks_like_label(s: str) -> bool:
    if not LATIN.search(s) or CYR.search(s):
        return False
    if NOISE.match(s):
        return False
    if s.count(';') >= 2 or s.count(':') >= 2:   # css-строки
        return False
    if re.fullmatch(r'[a-z_]+(?:-[a-z_]+)*', s):  # css-класс/идентификатор в одиночку
        return False
    return True

def main():
    rows = []
    for path in FILES:
        rel = str(Path(path).relative_to(ROOT))
        if 'vendor' in rel:
            continue
        for i, line in enumerate(Path(path).read_text(encoding='utf-8').split('\n'), 1):
            seen = set()
            for pat in PATTERNS:
                for s in pat.findall(line):
                    s = s.strip()
                    if s in seen or not looks_like_label(s):
                        continue
                    seen.add(s)
                    rows.append((rel, i, s))
    if '--json' in sys.argv:
        print(json.dumps([{'file': f, 'line': n, 'text': s} for f, n, s in rows],
                         ensure_ascii=False, indent=1))
        return
    for f, n, s in rows:
        print(f'{f}:{n}\t{s}')
    print(f'\n# всего: {len(rows)}; уникальных: {len({s for _, _, s in rows})}',
          file=sys.stderr)

main()
