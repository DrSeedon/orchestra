"""Numbers in the paper that numbers.md does not list, computed from runs.jsonl only.

  python scripts/more_numbers.py [--runs RUNS_JSONL] [--out more_numbers.md]

Definitions (all 320 runs are valid):
  rewrite          a run that removed 20 or more lines from Python files that existed before the run
                   ("-" lines of the diff, in files that the diff does not create).
  run outcome      a run follows the file (or the code) when more than half of its choices do;
                   otherwise it has no majority. Rewrites are counted separately.
  difference       share of choices that follow the code, condition B minus condition A, with a 95%
                   interval from 2,000 resamples of the 40 projects (seed 20261023); each drawn project
                   brings all its runs of both conditions.
"""
import argparse
import collections
import json
import os
import statistics

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
AGENTS = (("claude", "Claude Code"), ("codex", "Codex CLI"))
CONDS = (("A", "without the sentence"), ("B", "with the sentence"))


def removed_lines(diff):
    lines = files = 0
    path, new, n = None, False, 0
    for line in diff.split("\n") + ["diff --git a/end b/end"]:
        if line.startswith("diff --git"):
            if path and not new and path.endswith(".py") and n:
                lines += n
                files += 1
            path, new, n = line.split(" b/")[-1], False, 0
        elif line.startswith("new file mode"):
            new = True
        elif line.startswith("-") and not line.startswith("---"):
            n += 1
    return lines, files


def code_share(runs):
    v = [d["verdict"] for r in runs for d in r["verdicts"]]
    return sum(x == "follow_code" for x in v), len(v)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", default=os.path.join(ROOT, "runs.jsonl"))
    ap.add_argument("--out", default=os.path.join(ROOT, "more_numbers.md"))
    a = ap.parse_args()
    runs = [json.loads(l) for l in open(a.runs, encoding="utf-8") if l.strip()]
    runs = [r for r in runs if r["valid"]]
    md = ["# more numbers", "", "Computed from runs.jsonl by scripts/more_numbers.py.", ""]

    md += ["## Rewrites (Section 5.4)", ""]
    rw = {}
    for r in runs:
        n, f = removed_lines(r["diff"])
        r["_removed"], r["_files"], r["_rewrite"] = n, f, n >= 20
    for ag, name in AGENTS:
        for c, cname in CONDS:
            cell = [r for r in runs if r["agent"] == ag and r["cond"] == c]
            rw[(ag, c)] = [r for r in cell if r["_rewrite"]]
            md.append("- %s, %s: %d of %d runs" % (name, cname, len(rw[(ag, c)]), len(cell)))
    x = rw[("codex", "A")]
    if x:
        md += ["- Codex CLI without the sentence: tests failed in %d of %d rewrites; median %g lines removed from a "
               "median of %g files; %d projects" % (sum(not r["tests"]["all_pass"] for r in x), len(x),
                                                    statistics.median(r["_removed"] for r in x),
                                                    statistics.median(r["_files"] for r in x),
                                                    len({r["repo"] for r in x})),
               "- largest number of removed lines in a run that is not a rewrite: %d"
               % max(r["_removed"] for r in runs if not r["_rewrite"])]

    md += ["", "## What each run did (Figure 6)", ""]
    for c, cname in CONDS:
        for ag, name in AGENTS:
            cnt = collections.Counter()
            for r in runs:
                if r["agent"] != ag or r["cond"] != c:
                    continue
                v = [d["verdict"] for d in r["verdicts"]]
                rep = r["conflict"]["label"] == "YES"
                if r["_rewrite"]:
                    k = "rewrote existing code, tests %s" % ("passed" if r["tests"]["all_pass"] else "failed")
                elif v.count("follow_file") > len(v) / 2:
                    k = "followed the file, %s the conflict" % ("reported" if rep else "did not report")
                elif v.count("follow_code") > len(v) / 2:
                    k = "followed the code, %s the conflict" % ("reported" if rep else "did not report")
                else:
                    k = "no majority, %s the conflict" % ("reported" if rep else "did not report")
                cnt[k] += 1
            md.append("- %s, %s: %s" % (name, cname, "; ".join("%s %d" % kv for kv in sorted(cnt.items()))))

    md += ["", "## Difference in the share of choices that follow the code (Section 5.3)", ""]
    projects = sorted({r["repo"] for r in runs})
    by = collections.defaultdict(list)
    for r in runs:
        by[(r["repo"], r["agent"], r["cond"])].append(r)

    def diff(sample, agents):
        tot = {}
        for c in ("A", "B"):
            k = t = 0
            for p in sample:
                for ag in agents:
                    kk, tt = code_share(by[(p, ag, c)])
                    k += kk
                    t += tt
            tot[c] = k / t
        return 100 * (tot["B"] - tot["A"])

    rng = np.random.default_rng(20261023)
    draws = [list(rng.integers(0, len(projects), len(projects))) for _ in range(2000)]
    for agents, label in ((("claude", "codex"), "both agents"), (("claude",), "Claude Code"), (("codex",), "Codex CLI")):
        est = diff(projects, agents)
        bs = np.percentile([diff([projects[i] for i in d], agents) for d in draws], [2.5, 97.5])
        md.append("- %s: %.1f percentage points, 95%% interval [%.1f, %.1f]" % (label, est, bs[0], bs[1]))

    md += ["", "## Projects per kind of choice (Figure 4)", ""]
    kinds = collections.defaultdict(lambda: collections.defaultdict(set))
    for r in runs:
        for d in r["verdicts"]:
            kinds[d["type"]][d["file_option"]].add(r["repo"])
    for t in sorted(kinds):
        parts = ["file asks for %s: %d" % (o, len(p)) for o, p in sorted(kinds[t].items())]
        md.append("- %s: %d projects (%s)" % (t, sum(len(p) for p in kinds[t].values()), "; ".join(parts)))

    open(a.out, "w", encoding="utf-8", newline="\n").write("\n".join(md) + "\n")
    print("wrote", a.out)


if __name__ == "__main__":
    main()
