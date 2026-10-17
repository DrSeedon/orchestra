"""V-909: build the review sample. Rules fixed BEFORE any reviewer run (see report.md sec 1).
Usage: python -I build_sample.py <repo> <out.json>
"""
import json, random, re, subprocess, sys
from collections import defaultdict
from datetime import datetime, timedelta

repo, out = sys.argv[1], sys.argv[2]
SEED = 909
REF = re.compile(r"^(?:WIP\s+)?(?:#|PAR-)?((?:V-)?\d+)\s*:", re.I)
REVERT = re.compile(r'^(?:(?:WIP\s+)?#?(?:V-)?\d+:\s*)?(?:revert\b|откат)', re.I)
FIX = re.compile(r"fix|исправ|чин[иь]|регресс|hotfix|follow-?up|доработ", re.I)
def git(*a):
    return subprocess.run(["git", "-C", repo, *a], capture_output=True, text=True, check=True).stdout
sep, rs = "\x1f", "\x1e"
commits = []
for rec in git("log", "main", "--first-parent", "--reverse", f"--format=%H{sep}%aI{sep}%s{sep}%b{rs}").split(rs):
    rec = rec.strip("\n")
    if rec:
        h, d, s, b = rec.split(sep, 3)
        commits.append((h, datetime.fromisoformat(d).replace(tzinfo=None), s, b))
newest = commits[-1][1]
cutoff = newest - timedelta(days=14)
# the 9 owner-frame bad tasks (rollback_rate.py --list, V-905) -> the exact reverted/repaired commit
BAD = {
 "35":    "270db54e",  # repaired by #39/#40 (fix findings of review #35) - docs-only restore
 "51":    "ddd889d3",  # reverted 6h later, reason not recorded
 "88":    "ccc55e9c",  # reverted in the 'remove enterprise features' sweep, restored later
 "85":    "a05b13d0",  # same sweep
 "90":    "e3e180c1",  # same sweep (UX decision)
 "91":    "a755646c",  # same sweep; re-landed, then fixed by 2364a9e2 (proxy URL)
 "52":    "08c3932d",  # changelog build from task reports, reverted for privacy (policy)
 "V-600": "4dd81e7e",  # AGENTS.md rule reverted (owner policy)
 "V-621": "0059e675",  # accidental merge of catalog migration, reverted by 97b80e29
}
tasks = defaultdict(list)
for i, (h, d, s, b) in enumerate(commits):
    m = REF.match(s)
    if m and not REVERT.match(s):
        tasks[m.group(1).upper()].append(i)
bad_keys = set(BAD) | {"V-802"}
# widened repaired set (supplementary stratum R): fix commit naming an earlier task, within 60 days
wid = {}
for i, (h, d, s, b) in enumerate(commits):
    if not FIX.search(s):
        continue
    own = REF.match(s)
    own = own.group(1).upper() if own else None
    for a, c in re.findall(r"(?:#?V-(\d+)|#(\d+))", s + "\n" + b):
        r = ("V-" + a) if a else c
        if r != own and r in tasks and r not in bad_keys and max(tasks[r]) < i:
            lastd = commits[max(tasks[r])][1]
            if timedelta(0) <= d - lastd <= timedelta(days=60):
                wid.setdefault(r, (commits[i][0][:8], commits[i][2][:90]))
def diffstat(h):
    p = ["--", ".", ":(exclude).orchestra"]
    n = git("show", "--format=", "--numstat", h, *p)
    files, lines = [], 0
    for l in n.splitlines():
        a, b, f = l.split("\t", 2)
        files.append(f)
        lines += (int(a) if a.isdigit() else 0) + (int(b) if b.isdigit() else 0)
    return files, lines
CODE = re.compile(r"\.(py|js|html|css|sh|toml|yaml|yml)$")
def eligible_unit(h):
    files, lines = diffstat(h)
    code = [f for f in files if CODE.search(f)]
    return (bool(code), lines, len(files))
sample = []
for k, h in BAD.items():
    ok, lines, nf = eligible_unit(h)
    sample.append(dict(id=f"bad-{k}", stratum="bad", task=k, sha=git("rev-parse", h).strip(), lines=lines, files=nf))
rep = []
for k, (fx, subj) in wid.items():
    # the widened set uses the task's last unit
    h = commits[max(tasks[k])][0]
    ok, lines, nf = eligible_unit(h)
    if ok and 20 <= lines <= 1500 and commits[max(tasks[k])][1] <= cutoff:
        rep.append(dict(id=f"rep-{k}", stratum="repaired60", task=k, sha=h, lines=lines, files=nf, fixed_by=fx, fix_subject=subj))
random.Random(SEED).shuffle(rep)
sample += sorted(rep[:10], key=lambda x: x["id"])
pool = []
for k, idxs in tasks.items():
    if k in bad_keys or k in wid:
        continue
    for i in idxs:
        h, d, s, b = commits[i]
        if d > cutoff:
            continue
        ok, lines, nf = eligible_unit(h)
        if ok and 20 <= lines <= 1500:
            pool.append(dict(task=k, sha=h, date=d.isoformat(), subj=s[:90], lines=lines, files=nf))
random.Random(SEED).shuffle(pool)
seen, clean = set(), []
for p in pool:
    if p["task"] in seen:
        continue
    seen.add(p["task"]); clean.append(dict(id=f"clean-{p['task']}", stratum="clean", **p))
    if len(clean) == 40:
        break
sample += clean
json.dump(dict(newest=newest.isoformat(), cutoff=cutoff.isoformat(), seed=SEED, widened_available=len(rep),
               clean_pool_units=len(pool), items=sample), open(out, "w"), indent=1, ensure_ascii=False)
print("bad", len(BAD), "repaired60 avail", len(rep), "clean pool units", len(pool), "clean tasks", len(seen))
for s in sample:
    print(s["id"], s["sha"][:8], s["lines"], s["files"])
