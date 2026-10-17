"""V-905: share of task landings on Orchestra main that were later rolled back or repaired.

Rule fixed BEFORE counting (see report.md section 3):
 unit      = first-parent commit of `main` whose subject starts with a task ref
             (`#N:`, `V-N:`, `#V-N:`, optional `WIP `); grouped by task key = digits of the ref.
 reverted  = a later commit with `Revert "` / `revert` / `откат` as subject start (after
             optional task ref) or body `This reverts commit <sha>`; the target is the commit
             whose sha/subject it names.
 repaired  = a later commit of ANOTHER task, within WINDOW_DAYS of the original task's last
             landing, whose subject+body names the original task explicitly (`#N`, `V-N`) AND whose
             subject has a fix word (fix/исправ/чин/регресс/hotfix/follow-up/доработ).
 A task is "bad" if any of its units is reverted or repaired. Tasks that landed less than
 WINDOW_DAYS before the newest commit are right-censored and excluded from rates.
Usage: python -I rollback_rate.py [repo] [--list]
"""
import re
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timedelta

WINDOW_DAYS = 14
CUT = datetime(2026, 9, 20)
REF = re.compile(r"^(?:WIP\s+)?(?:#|PAR-)?((?:V-)?\d+)\s*:", re.I)
REVERT = re.compile(r'^(?:(?:WIP\s+)?#?(?:V-)?\d+:\s*)?(?:revert\b|откат)', re.I)
FIX = re.compile(r"fix|исправ|чин[иь]|регресс|hotfix|follow-?up|доработ", re.I)
def refs_in(text):
    return {("V-" + a) if a else b
            for a, b in re.findall(r"(?:#?V-(\d+)|#(\d+))", text, re.I)}


repo = next((a for a in sys.argv[1:] if not a.startswith("--")), ".")
sep, rs = "\x1f", "\x1e"
out = subprocess.run(
    ["git", "-C", repo, "log", "main", "--first-parent", "--reverse",
     f"--format=%H{sep}%aI{sep}%s{sep}%b{rs}"],
    capture_output=True, text=True, check=True).stdout
commits = []
for rec in out.split(rs):
    rec = rec.strip("\n")
    if not rec:
        continue
    h, d, s, b = rec.split(sep, 3)
    commits.append((h, datetime.fromisoformat(d).replace(tzinfo=None), s, b))
newest = commits[-1][1]
tasks = defaultdict(list)           # key -> [(idx, date)]
sha_task, subj_task = {}, {}
for i, (h, d, s, b) in enumerate(commits):
    m = REF.match(s)
    if m and not REVERT.match(s):
        key = m.group(1).upper()
        tasks[key].append((i, d))
        sha_task[h] = key
        subj_task.setdefault(s.strip(), key)
bad = defaultdict(set)
for i, (h, d, s, b) in enumerate(commits):
    if REVERT.match(s) or "This reverts commit" in b:
        tgt = None
        for sha in re.findall(r"This reverts commit ([0-9a-f]{7,40})", b):
            tgt = next((t for k, t in sha_task.items() if k.startswith(sha)), tgt)
        q = re.search(r'Revert "(.+)"', s)
        if not tgt and q:
            tgt = subj_task.get(q.group(1).strip())
        if not tgt:
            tgt = next((r for r in sorted(refs_in(s)) if r in tasks), None)
        if tgt and tgt != (REF.match(s).group(1).upper() if REF.match(s) else None):
            bad[tgt].add("revert")
    m = REF.match(s)
    own = m.group(1).upper() if m else None
    if FIX.search(s):
        for r in refs_in(s + "\n" + b):
            if r != own and r in tasks:
                last = max(dt for _, dt in tasks[r])
                if timedelta(0) <= d - last <= timedelta(days=WINDOW_DAYS) and \
                        max(ix for ix, _ in tasks[r]) < i:
                    bad[r].add("repaired")

def stats(label, keys):
    n = len(keys)
    b = sum(1 for k in keys if k in bad)
    rv = sum(1 for k in keys if "revert" in bad.get(k, ()))
    print(f"{label:28s} tasks={n:4d} bad={b:3d} ({100*b/max(n,1):5.1f}%) "
          f"reverted={rv:3d} ({100*rv/max(n,1):4.1f}%)")

first = {k: min(dt for _, dt in v) for k, v in tasks.items()}
last = {k: max(dt for _, dt in v) for k, v in tasks.items()}
elig = [k for k in tasks if newest - last[k] >= timedelta(days=WINDOW_DAYS)]
print(f"commits(first-parent)={len(commits)} task_units={sum(len(v) for v in tasks.values())} "
      f"tasks={len(tasks)} newest={newest:%F} eligible(not censored)={len(elig)}")
months = sorted({first[k].strftime("%Y-%m") for k in elig})
for mth in months:
    stats(mth, [k for k in elig if first[k].strftime("%Y-%m") == mth])
stats("BEFORE 2026-09-20", [k for k in elig if first[k] < CUT])
stats("AFTER  2026-09-20", [k for k in elig if first[k] >= CUT])
for lo, hi, lab in [("2026-08-01", "2026-09-20", "Aug1-Sep19 (equal 7w)"),
                    ("2026-09-20", "2026-10-04", "Sep20-Oct3")]:
    lo, hi = datetime.fromisoformat(lo), datetime.fromisoformat(hi)
    stats(lab, [k for k in elig if lo <= first[k] < hi])
if "--list" in sys.argv:
    for k in sorted(bad, key=lambda x: first.get(x, newest)):
        print(k, f"{first[k]:%F}", sorted(bad[k]))

# Throughput context: distinct tasks first landed per 14-day window (all, incl. censored).
start = min(first.values())
w = defaultdict(int)
for k, dt in first.items():
    w[(dt - start).days // 14] += 1
print("tasks first landed per 14d window (start %s):" % f"{start:%F}")
print(" ".join(f"{(start + timedelta(days=14 * i)):%m-%d}:{w[i]}" for i in sorted(w)))
