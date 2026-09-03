"""Вариант предсказателя без опоры на заголовок секции.

Признак — число уникальных путей к прод-коду (app/, scripts/, static/, pipelines/),
упомянутых во ВСЁМ research.md. Тесты и .md не считаются.
Проверяется только на задачах, которые реально дали код (prod>0).
"""
import csv
import glob
import os
import re
import statistics

REPO = "/home/kesha/orchestra"
RE_PATH = re.compile(r"((?:app|scripts|static|templates)/[\w./-]+\.(?:py|js|css|html))")

fact = {}
for r in csv.DictReader(open("/tmp/diffsize.tsv"), delimiter="\t"):
    if not r["ids"]:
        continue
    for t in r["ids"].split(","):
        fact[t] = fact.get(t, 0) + int(r["prod+"]) + int(r["prod-"])

rows = []
for d in sorted(glob.glob(f"{REPO}/docs/tasks/*/")):
    tid = d.rstrip("/").split("/")[-1]
    p = os.path.join(d, "research.md")
    if not tid.isdigit() or not os.path.exists(p) or fact.get(tid, 0) == 0:
        continue
    named = set(RE_PATH.findall(open(p, encoding="utf-8", errors="replace").read()))
    rows.append((tid, len(named), fact[tid]))

print("task\tpaths_in_research\tprod_lines")
for t, n, p in sorted(rows, key=lambda x: x[1]):
    print(f"{t}\t{n}\t{p}")

print("\n# сводка (только задачи с кодом)")
for lo, hi, lbl in [(0, 2, "0-2 пути"), (3, 5, "3-5"), (6, 10, "6-10"), (11, 999, "11+")]:
    g = [p for _, n, p in rows if lo <= n <= hi]
    if g:
        print(f"{lbl}: n={len(g)} медиана={statistics.median(g):.0f} макс={max(g)} "
              f">150 строк: {sum(1 for x in g if x > 150)}/{len(g)}")
