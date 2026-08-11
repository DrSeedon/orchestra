"""Размер результата каждой задачи: строки прод-кода в смерженном коммите main.

Прод = всё, кроме docs/, tests/, *.md. Печатает task_id, sha, prod +/-, docs +/-, tests +/-.
"""
import re
import subprocess
import sys
from collections import defaultdict

REPO = "/home/kesha/orchestra"


def git(*args):
    return subprocess.run(["git", "-C", REPO, *args], capture_output=True, text=True).stdout


rows = git("log", "main", "--since=2026-07-01", "--pretty=%H|%ad|%s", "--date=short").splitlines()

out = []
for row in rows:
    sha, date, subj = row.split("|", 2)
    ids = sorted(set(re.findall(r"#(\d+)", subj)))
    stat = git("show", "--numstat", "--format=", sha)
    buckets = defaultdict(lambda: [0, 0])
    for line in stat.splitlines():
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        a, d, path = parts
        if a == "-":
            continue
        if path.startswith("docs/") or path.endswith(".md"):
            k = "docs"
        elif path.startswith("tests/") or "/test" in path or path.startswith("test"):
            k = "tests"
        else:
            k = "prod"
        buckets[k][0] += int(a)
        buckets[k][1] += int(d)
    out.append((sha[:7], date, ",".join(ids), subj[:60],
                buckets["prod"][0], buckets["prod"][1],
                buckets["tests"][0], buckets["tests"][1],
                buckets["docs"][0], buckets["docs"][1]))

print("sha\tdate\tids\tprod+\tprod-\ttest+\ttest-\tdocs+\tdocs-\tsubject")
for r in out:
    print(f"{r[0]}\t{r[1]}\t{r[2]}\t{r[4]}\t{r[5]}\t{r[6]}\t{r[7]}\t{r[8]}\t{r[9]}\t{r[3]}")
