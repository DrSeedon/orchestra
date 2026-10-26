"""Offline recount of published records; never import or execute the authors' code."""
import collections
import hashlib
import json
from pathlib import Path
import re
import statistics

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "evidence/stale-docs-data-fa3c8b8a3347b11e7d4faa073af2b210a1b037e3"
raw = (DATA / "runs.jsonl").read_bytes()
rows = [json.loads(line) for line in raw.splitlines() if line.strip()]
tasks = {p.parent.name: json.loads(p.read_text()) for p in sorted((DATA / "tasks").glob("*/task.json"))}
assert len(rows) == 320 and len(tasks) == 40
assert len({r["run"] for r in rows}) == 320
assert all(r["valid"] is True for r in rows)
assert all(len(r["verdicts"]) == r["n_decisions"] == len(tasks[r["repo"]]["decisions"]) for r in rows)
assert all(r["conflict"]["label"] in {"YES", "NO"} for r in rows)
assert all(v["verdict"] in {"follow_file", "follow_code", "neither"} for r in rows for v in r["verdicts"])
grid = collections.Counter((r["repo"], r["agent"], r["cond"]) for r in rows)
assert len(grid) == 160 and set(grid.values()) == {2}


def removed(diff):
    """Count '-' body lines in existing .py sections, excluding diff headers/new files."""
    counts = []
    for part in diff.split("diff --git ")[1:]:
        lines = part.splitlines()
        path = lines[0].split(" b/", 1)[-1]
        if not path.endswith(".py") or "new file mode " in part.split("@@", 1)[0]:
            continue
        n = sum(line.startswith("-") and not line.startswith("---") for line in lines[1:])
        if n:
            counts.append(n)
    return sum(counts), len(counts)


for r in rows:
    r["removed"], r["removed_files"] = removed(r["diff"])
    r["rewrite"] = r["removed"] >= 20


def counts(rs):
    return collections.Counter(v["verdict"] for r in rs for v in r["verdicts"])


def fraction(n, d):
    return f"{n}/{d} ({100*n/d:.1f}%)"


metrics = {}
print("runs.jsonl SHA256", hashlib.sha256(raw).hexdigest())
print("coverage: 320 unique valid runs; 40 projects; 2 agents x 2 conditions x 2 repeats/project")
print("task decision counts", dict(sorted(collections.Counter(len(t["decisions"]) for t in tasks.values()).items())))
print("all record keys", sorted(set().union(*(r.keys() for r in rows)) - {"removed", "removed_files", "rewrite"}))
for cond, prefix in (("A", "S"), ("B", "P")):
    for agent in (None, "claude", "codex"):
        rs = [r for r in rows if r["cond"] == cond and (agent is None or r["agent"] == agent)]
        suffix = "" if agent is None else "-" + agent
        c = counts(rs)
        for verdict, name in (("follow_file", "file"), ("follow_code", "code"), ("neither", "neither")):
            metrics[f"{prefix}-{name}{suffix}"] = (c[verdict], sum(c.values()))
        metrics[f"{prefix}-report{suffix}"] = (sum(r["conflict"]["label"] == "YES" for r in rs), len(rs))
        metrics[f"{prefix}-tests{suffix}"] = (sum(r["tests"]["all_pass"] for r in rs), len(rs))
        if cond == "A":
            for label, name in (("YES", "reported"), ("NO", "notreported")):
                sub = counts([r for r in rs if r["conflict"]["label"] == label])
                metrics[f"S-file-{name}{suffix}"] = (sub["follow_file"], sum(sub.values()))
for name, (n, d) in metrics.items():
    print(name, fraction(n, d))
reference = (DATA / "numbers.md").read_text()
published = {m[1]: (int(m[3]), int(m[4])) for m in re.finditer(r"^- `([^`]+)`: ([\d.]+)% \((\d+)/(\d+)\)", reference, re.M)}
assert metrics == published, (metrics, published)
print("PASS all", len(metrics), "published keyed numerator/denominator aggregates match")

categories = sorted({v["type"] for r in rows for v in r["verdicts"]})
majority = []
print("CATEGORY A: type | claude file/code/total | codex file/code/total")
for cat in categories:
    cs = [collections.Counter(v["verdict"] for r in rows if r["cond"] == "A" and r["agent"] == ag
                              for v in r["verdicts"] if v["type"] == cat) for ag in ("claude", "codex")]
    values = [(c["follow_file"], c["follow_code"], sum(c.values())) for c in cs]
    print(cat, values)
    if all(f * 2 > n for f, _, n in values):
        majority.append(cat)
    line = next(line for line in reference.splitlines() if line.startswith(f"| {cat} |"))
    pairs = [(int(n), int(d)) for n, d in re.findall(r"\((\d+)/(\d+)\)", line)]
    assert pairs == [(k, n) for f, co, n in values for k in (f, co)]
print("PASS 64 category fractions; file majority for both:", len(majority), majority)

print("CELL: runs, choices, reported, tests_pass, rewrites, median tools, median seconds, run outcomes")
for agent in ("claude", "codex"):
    for cond in ("A", "B"):
        rs = [r for r in rows if r["agent"] == agent and r["cond"] == cond]
        outcomes = collections.Counter()
        for r in rs:
            c = counts([r])
            outcome = ("rewrite-pass" if r["tests"]["all_pass"] else "rewrite-fail") if r["rewrite"] else (
                "file" if c["follow_file"] * 2 > r["n_decisions"] else
                "code" if c["follow_code"] * 2 > r["n_decisions"] else "no-majority")
            outcomes[outcome + "/" + r["conflict"]["label"]] += 1
        print(agent, cond, len(rs), sum(r["n_decisions"] for r in rs),
              sum(r["conflict"]["label"] == "YES" for r in rs), sum(r["tests"]["all_pass"] for r in rs),
              sum(r["rewrite"] for r in rs), statistics.median(r["tool_calls"] for r in rs),
              round(statistics.median(r["seconds"] for r in rs), 1), dict(sorted(outcomes.items())))
rewrites = [r for r in rows if r["rewrite"]]
assert len(rewrites) == 20 and all(r["agent"] == "codex" and r["cond"] == "A" for r in rewrites)
assert sum(not r["tests"]["all_pass"] for r in rewrites) == 17
assert all(r["rewrite"] for r in rows if not r["tests"]["all_pass"])
print("rewrites: runs/fails/projects/median removed/median files", len(rewrites),
      sum(not r["tests"]["all_pass"] for r in rewrites), len({r["repo"] for r in rewrites}),
      statistics.median(r["removed"] for r in rewrites), statistics.median(r["removed_files"] for r in rewrites))
print("max deletions below rewrite threshold", max(r["removed"] for r in rows if not r["rewrite"]))
print("rewrite IDs", [r["run"] for r in rewrites])
print("reported within rewrites", [(r["run"], r["conflict"]["label"]) for r in rewrites if r["conflict"]["label"] == "YES"])
print("instruction file edited", [(r["run"], r["agent"], r["cond"]) for r in rows if r["doc_edited"]])
print("failed attempts", [(r["run"], r["failures"]) for r in rows if r["failures"]])
print("versions/models", dict(collections.Counter((r["agent"], r["tool_version"], r["model"]) for r in rows)))
for agents in (("claude", "codex"), ("claude",), ("codex",)):
    shares = [counts([r for r in rows if r["cond"] == c and r["agent"] in agents]) for c in ("A", "B")]
    print("B-A percentage points", agents, round(100*(shares[1]["follow_code"]/sum(shares[1].values())
                                                    - shares[0]["follow_code"]/sum(shares[0].values())), 1))
for cat in categories:
    options = collections.defaultdict(set)
    for r in rows:
        for v in r["verdicts"]:
            if v["type"] == cat:
                options[v["file_option"]].add(r["repo"])
    print("project coverage", cat, {o: len(ps) for o, ps in sorted(options.items())})
print("NOT RECOMPUTED: verdicts from diffs, model conflict judgments, test outcomes, bootstrap intervals, token count")
print("PASS offline recount completed; no network, provider, subprocess or author-code execution")
