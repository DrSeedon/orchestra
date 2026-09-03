"""Предсказуем ли размер работы по секции «Affected files» в research.md?

Из research.md берём число уникальных путей к коду (не .md), названных в секции
«Affected files / Задетые файлы». Сравниваем с фактом: сколько файлов кода и строк
прода в смерженных коммитах main с этим #id.
"""
import csv
import glob
import os
import re
import subprocess

REPO = "/home/kesha/orchestra"
RE_PATH = re.compile(r"`?((?:app|scripts|pipelines|static|templates|tests)/[\w./-]+\.\w+)")
SEC = re.compile(r"^#{1,4}\s*(Affected files|Задетые файлы|Затронутые файлы|Affected code)", re.I)

# факт: файлы и строки прода на задачу
fact = {}
for r in csv.DictReader(open("/tmp/diffsize.tsv"), delimiter="\t"):
    if not r["ids"]:
        continue
    for t in r["ids"].split(","):
        a = fact.setdefault(t, [0, set()])
        a[0] += int(r["prod+"]) + int(r["prod-"])

shas = subprocess.run(["git", "-C", REPO, "log", "main", "--since=2026-07-01",
                       "--pretty=%H|%s"], capture_output=True, text=True).stdout.splitlines()
for line in shas:
    sha, subj = line.split("|", 1)
    ids = set(re.findall(r"#(\d+)", subj))
    if not ids:
        continue
    files = subprocess.run(["git", "-C", REPO, "show", "--name-only", "--format=", sha],
                           capture_output=True, text=True).stdout.split()
    for t in ids:
        a = fact.setdefault(t, [0, set()])
        for p in files:
            if not p.endswith(".md") and not p.startswith("docs/"):
                a[1].add(p)

print("task\tnamed_in_research\tfact_code_files\tfact_prod_lines\tnames")
for d in sorted(glob.glob(f"{REPO}/docs/tasks/*/")):
    tid = d.rstrip("/").split("/")[-1]
    p = os.path.join(d, "research.md")
    if not tid.isdigit() or not os.path.exists(p):
        continue
    lines = open(p, encoding="utf-8", errors="replace").read().splitlines()
    named, inside = set(), False
    for line in lines:
        if line.startswith("#"):
            inside = bool(SEC.match(line))
            continue
        if inside:
            named.update(RE_PATH.findall(line))
    prod, files = fact.get(tid, (0, set()))
    if not named and not files:
        continue
    print(f"{tid}\t{len(named)}\t{len(files)}\t{prod}\t{','.join(sorted(named))[:70]}")
