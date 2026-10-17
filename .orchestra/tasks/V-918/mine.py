"""V-918: mine (origin commit, later fix) pairs from git. Usage: python -I mine.py <repo> <out.json>
For each first-parent main commit F whose subject matches FIX: blame the lines F deleted/changed (in F^1, code files
outside .orchestra) to origin commits; origin must be a first-parent main commit O != F, landed before F.
Also records explicit task refs in F's message."""
import json, re, subprocess, sys
from collections import Counter, defaultdict
from datetime import datetime
repo, out = sys.argv[1], sys.argv[2]
def git(*a, check=True):
    return subprocess.run(["git", "-C", repo, *a], capture_output=True, text=True, check=check).stdout
FIX = re.compile(r"fix|исправ|чин[иь]|регресс|hotfix|repair|restore|восстанов", re.I)
SKIP = re.compile(r"^(Merge|TODO|AGENTS|owner decision|revert|Revert|откат)", re.I)
CODE = re.compile(r"\.(py|js|html|css|sh|toml|yaml|yml)$")
sep, rs = "\x1f", "\x1e"
commits, idx = [], {}
for rec in git("log", "main", "--first-parent", "--reverse", f"--format=%H{sep}%aI{sep}%s{sep}%b{rs}").split(rs):
    rec = rec.strip("\n")
    if rec:
        h, d, s, b = rec.split(sep, 3)
        idx[h] = len(commits); commits.append(dict(sha=h, date=d, subj=s, body=b))
fp = set(idx)
def to_fp(sha):
    """map any commit to the first-parent main commit that brought it in"""
    if sha in fp: return sha
    r = git("log", "main", "--first-parent", "--ancestry-path", "--reverse", "--format=%H", f"{sha}..main", check=False).split()
    return r[0] if r else None
cache = {}
res = []
for F in commits:
    if SKIP.match(F["subj"]) or not FIX.search(F["subj"] + " " + F["body"][:300]): continue
    if not FIX.search(F["subj"]): continue
    p = git("rev-parse", F["sha"] + "^1", check=False).strip()
    if not p: continue
    diff = git("diff", "-U0", p, F["sha"], "--", ".", ":(exclude).orchestra", check=False)
    cur, hunks = None, []
    for l in diff.splitlines():
        if l.startswith("--- "): cur = l[6:] if l.startswith("--- a/") else None
        elif l.startswith("@@") and cur and CODE.search(cur):
            m = re.match(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", l)
            s, n = int(m.group(1)), int(m.group(2) if m.group(2) is not None else 1)
            if n: hunks.append((cur, s, s + n - 1))
    cnt, files = Counter(), defaultdict(set)
    for f, a, b in hunks:
        if b - a > 60: continue
        o = git("blame", "-w", "--porcelain", "-L", f"{a},{b}", p, "--", f, check=False)
        for l in o.splitlines():
            if re.match(r"^[0-9a-f]{40} \d+ \d+", l):
                c = l.split()[0]
                cnt[c] += 1; files[c].add(f)
    byfp = Counter()
    fpfiles = defaultdict(set)
    for c, n in cnt.items():
        if c not in cache: cache[c] = to_fp(c)
        o = cache[c]
        if o and o != F["sha"] and idx[o] < idx[F["sha"]]:
            byfp[o] += n; fpfiles[o] |= files[c]
    refs = set(re.findall(r"#?(V-\d+|(?<![\w/])\d{2,4})(?![\w])", F["subj"] + "\n" + F["body"]))
    res.append(dict(fix=F["sha"], fix_date=F["date"], fix_subj=F["subj"][:140], deleted_hunks=len(hunks),
                    origins=[dict(sha=o, n=n, subj=commits[idx[o]]["subj"][:120], date=commits[idx[o]]["date"],
                                  files=sorted(fpfiles[o])) for o, n in byfp.most_common(5)], refs=sorted(refs)))
json.dump(res, open(out, "w"), indent=1, ensure_ascii=False)
print(len(res), sum(1 for r in res if r["origins"]))
