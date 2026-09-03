"""Сканер codex-review-*.md: сколько ревью нашли блокирующее.

Признак blocking — строка с 'blocking'/'P0'/'P1'/'критич', не отменённая приставкой
non-/не. Печатает: файл, тип ревью, размер, число blocking-строк, первые строки.
"""
import glob
import re
import sys

NEG = re.compile(r"(non-blocking|не блок|no blocking|нет блок|0 blocking|без блок)", re.I)
POS = re.compile(r"(blocking|\bP0\b|\bP1\b|критичн|critical)", re.I)

rows = []
for f in sorted(glob.glob("/home/kesha/orchestra/docs/tasks/*/codex-review*.md")):
    task = f.split("/")[-2]
    kind = f.split("codex-review")[-1].replace(".md", "").strip("-") or "generic"
    text = open(f, encoding="utf-8", errors="replace").read()
    hits = []
    for line in text.splitlines():
        if POS.search(line) and not NEG.search(line):
            hits.append(line.strip()[:160])
    rows.append((task, kind, len(text), len(hits), hits))

print("task\tkind\tbytes\tblocking_lines")
for task, kind, n, h, hits in rows:
    print(f"{task}\t{kind}\t{n}\t{h}")

if "--dump" in sys.argv:
    print("\n=== строки ===")
    for task, kind, n, h, hits in rows:
        if h:
            print(f"\n## {task}/{kind} ({h})")
            for line in hits[:6]:
                print("  " + line)
