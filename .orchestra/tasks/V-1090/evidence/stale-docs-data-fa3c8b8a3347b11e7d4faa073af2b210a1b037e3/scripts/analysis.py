"""Numbers and the main figure, computed from runs.jsonl only (one line per planned run).

  python analysis.py numbers [--runs RUNS_JSONL] [--fix FIX_FILE] [--out numbers.md]
  python analysis.py figure  [--runs RUNS_JSONL] [--out fig-main.pdf]
  python analysis.py rejudge [--runs RUNS_JSONL]   re-judge every diff with judge.py; compare with the record

Definitions (all over valid runs):
  choice shares    each decision of each valid run is one choice: follow_file, follow_code or neither.
                   share = choices with that verdict / all choices of the cell.
  S-*              condition A.  P-*  condition B.
  report shares    runs whose final reply the conflict judge labelled YES / runs with a label.
  S-file-reported  condition A, runs labelled YES: follow_file choices / all their choices.
  kinds-file-majority  condition A: categories in which, for both agents, follow_file choices are
                   more than half of that category's choices.
  tests            runs whose existing tests and held-out feature test all pass / runs.
  95% intervals    2,000 bootstrap resamples of the 40 repositories (with replacement, seed 20261023);
                   every run of a drawn repository goes in; percentile interval 2.5-97.5.
  n                tokens of the fix sentence, tiktoken o200k_base, leading/trailing white space removed.
"""
import argparse
import collections
import json
import os
import statistics

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if os.path.exists(os.path.join(ROOT, "runs.jsonl")):          # release layout
    DEF_RUNS = os.path.join(ROOT, "runs.jsonl")
    DEF_OUT = ROOT
else:                                                         # working layout
    DEF_RUNS = os.path.join(ROOT, "runs", "runs.jsonl")
    DEF_OUT = os.path.join(ROOT, "out")
DEF_FIX = os.path.join(ROOT, "conditions", "B_fix.md")

AGENTS = ("claude", "codex")
AGENT_LABEL = {"claude": "Claude Code", "codex": "Codex CLI"}
CONDS = ("A", "B")
VERDICTS = ("follow_file", "follow_code", "neither")
VLABEL = {"follow_file": "file", "follow_code": "code", "neither": "neither"}
CATEGORIES = ["LOG", "PATH", "EXC", "ERR", "TFILE", "TSTYLE", "REC", "NAME", "OPT", "IMPORT", "GENERIC", "FMT",
              "DOCSTR", "MONEY", "CONFIG", "ENUM"]
REPOS = ["P%02d" % i for i in range(1, 41)]   # a resample always draws from all 40 repositories
BOOT_N = 2000
BOOT_SEED = 20261023


def load(path):
    with open(path, encoding="utf-8") as fh:
        return [json.loads(l) for l in fh if l.strip()]


def pct(num, den):
    if not den:
        return "n/a (0/0)"
    return "%.1f%% (%d/%d)" % (100.0 * num / den, num, den)


def pct_val(num, den):
    return 100.0 * num / den if den else float("nan")


def valid(runs, agent=None, cond=None):
    return [r for r in runs if r["valid"] and (agent is None or r["agent"] == agent)
            and (cond is None or r["cond"] == cond)]


def choice_counts(runs):
    c = collections.Counter()
    for r in runs:
        for v in r["verdicts"]:
            c[v["verdict"]] += 1
            c["total"] += 1
    return c


def label_of(r):
    return (r.get("conflict") or {}).get("label")


# ---------------------------------------------------------------- bootstrap

def boot_ci(runs, fn_counts):
    """fn_counts(list of runs) -> (num, den). Resample repositories; return (lo, hi) in percent."""
    import numpy as np
    repos = REPOS
    by_repo = collections.defaultdict(list)
    for r in runs:
        by_repo[r["repo"]].append(r)
    nums = np.array([fn_counts(by_repo[p])[0] for p in repos], dtype=float)
    dens = np.array([fn_counts(by_repo[p])[1] for p in repos], dtype=float)
    rng = np.random.default_rng(BOOT_SEED)
    idx = rng.integers(0, len(repos), size=(BOOT_N, len(repos)))
    n = nums[idx].sum(axis=1)
    d = dens[idx].sum(axis=1)
    share = np.where(d > 0, 100.0 * n / np.where(d > 0, d, 1), np.nan)
    lo, hi = np.nanpercentile(share, [2.5, 97.5])
    return float(lo), float(hi)


def verdict_fn(verdict):
    def f(rs):
        c = choice_counts(rs)
        return c[verdict], c["total"]
    return f


# ---------------------------------------------------------------- numbers

def compute(runs, fix_path):
    out = collections.OrderedDict()
    lines = []

    def put(key, num, den, ci=None):
        out[key] = {"num": num, "den": den, "pct": round(pct_val(num, den), 1) if den else None}
        s = "- `%s`: %s" % (key, pct(num, den))
        if ci:
            out[key]["ci95"] = [round(ci[0], 1), round(ci[1], 1)]
            s += ", 95%% CI [%.1f, %.1f]" % ci
        lines.append(s)

    lines.append("## Choice shares")
    for cond, prefix in (("A", "S"), ("B", "P")):
        for verdict, name in (("follow_file", "file"), ("follow_code", "code"), ("neither", "neither")):
            rs = valid(runs, cond=cond)
            c = choice_counts(rs)
            put("%s-%s" % (prefix, name), c[verdict], c["total"], boot_ci(rs, verdict_fn(verdict)))
            for a in AGENTS:
                rs = valid(runs, a, cond)
                c = choice_counts(rs)
                put("%s-%s-%s" % (prefix, name, a), c[verdict], c["total"], boot_ci(rs, verdict_fn(verdict)))

    lines.append("")
    lines.append("## Conflict reported in the final reply (conflict judge)")
    for cond, prefix in (("A", "S"), ("B", "P")):
        rs = [r for r in valid(runs, cond=cond) if label_of(r)]
        put("%s-report" % prefix, sum(label_of(r) == "YES" for r in rs), len(rs))
        for a in AGENTS:
            rs = [r for r in valid(runs, a, cond) if label_of(r)]
            put("%s-report-%s" % (prefix, a), sum(label_of(r) == "YES" for r in rs), len(rs))
    unl = [r["run"] for r in valid(runs) if not label_of(r)]
    lines.append("- valid runs without a judge label: %d%s" % (len(unl), (" (" + ", ".join(unl) + ")") if unl else ""))
    for suffix, agent in (("", None), ("-claude", "claude"), ("-codex", "codex")):
        rs = [r for r in valid(runs, agent, "A") if label_of(r) == "YES"]
        c = choice_counts(rs)
        put("S-file-reported" + suffix, c["follow_file"], c["total"])
    for suffix, agent in (("", None), ("-claude", "claude"), ("-codex", "codex")):
        rs = [r for r in valid(runs, agent, "A") if label_of(r) == "NO"]
        c = choice_counts(rs)
        put("S-file-notreported" + suffix, c["follow_file"], c["total"])

    lines.append("")
    lines.append("## Categories, condition A (follow_file share per category and agent)")
    per = {}
    for a in AGENTS:
        for cat in CATEGORIES:
            c = collections.Counter()
            for r in valid(runs, a, "A"):
                for v in r["verdicts"]:
                    if v["type"] == cat:
                        c[v["verdict"]] += 1
                        c["total"] += 1
            per[(a, cat)] = c
    lines.append("")
    lines.append("| category | Claude Code file | Claude Code code | Codex CLI file | Codex CLI code |")
    lines.append("|---|---|---|---|---|")
    maj = []
    out["category_A"] = {}
    for cat in CATEGORIES:
        row = [cat]
        both = True
        for a in AGENTS:
            c = per[(a, cat)]
            row += [pct(c["follow_file"], c["total"]), pct(c["follow_code"], c["total"])]
            out["category_A"]["%s-%s" % (cat, a)] = {"file": c["follow_file"], "code": c["follow_code"],
                                                     "neither": c["neither"], "total": c["total"]}
            if not (c["total"] and 2 * c["follow_file"] > c["total"]):
                both = False
        if both:
            maj.append(cat)
        lines.append("| " + " | ".join(row) + " |")
    lines.append("")
    out["kinds-file-majority"] = {"count": len(maj), "of": len(CATEGORIES), "categories": maj}
    lines.append("- `kinds-file-majority`: %d (of %d): %s" % (len(maj), len(CATEGORIES), ", ".join(maj) or "none"))

    lines.append("")
    lines.append("## Tests (existing tests and held-out feature test all pass)")
    for cond, prefix in (("A", "S"), ("B", "P")):
        rs = valid(runs, cond=cond)
        put("%s-tests" % prefix, sum(bool(r["tests"]["all_pass"]) for r in rs), len(rs))
        for a in AGENTS:
            rs = valid(runs, a, cond)
            put("%s-tests-%s" % (prefix, a), sum(bool(r["tests"]["all_pass"]) for r in rs), len(rs))

    lines.append("")
    lines.append("## Choice shares per condition and agent (Figure 5a; 95% CI, 2,000 bootstrap resamples by repository)")
    lines.append("")
    lines.append("| condition | agent | follow file | follow code | neither | choices |")
    lines.append("|---|---|---|---|---|---|")
    out["table2"] = {}
    for cond in CONDS:
        for a in AGENTS:
            rs = valid(runs, a, cond)
            c = choice_counts(rs)
            cells = []
            for verdict in VERDICTS:
                lo, hi = boot_ci(rs, verdict_fn(verdict))
                cells.append("%s [%.1f, %.1f]" % (pct(c[verdict], c["total"]), lo, hi))
                out["table2"]["%s-%s-%s" % (cond, a, VLABEL[verdict])] = {
                    "num": c[verdict], "den": c["total"], "pct": round(pct_val(c[verdict], c["total"]), 1),
                    "ci95": [round(lo, 1), round(hi, 1)]}
            lines.append("| %s | %s | %s | %d |" % (cond, AGENT_LABEL[a], " | ".join(cells), c["total"]))

    lines.append("")
    lines.append("## Efficiency table")
    lines.append("")
    lines.append("| condition | agent | tests all pass | median tool calls | median seconds | valid runs |")
    lines.append("|---|---|---|---|---|---|")
    out["efficiency"] = {}
    for cond in CONDS:
        for a in AGENTS:
            rs = valid(runs, a, cond)
            npass = sum(bool(r["tests"]["all_pass"]) for r in rs)
            mt = statistics.median([r["tool_calls"] for r in rs]) if rs else float("nan")
            ms = statistics.median([r["seconds"] for r in rs]) if rs else float("nan")
            out["efficiency"]["%s-%s" % (cond, a)] = {"tests_pass": [npass, len(rs)],
                                                      "median_tool_calls": mt, "median_seconds": ms}
            lines.append("| %s | %s | %s | %s | %.1f | %d |" % (cond, AGENT_LABEL[a], pct(npass, len(rs)),
                                                               ("%g" % mt), ms, len(rs)))

    lines.append("")
    lines.append("## decisions-per-cell (choices judged; valid runs x decisions of the task)")
    out["decisions-per-cell"] = {}
    for a in AGENTS:
        for cond in CONDS:
            rs = valid(runs, a, cond)
            n = sum(len(r["verdicts"]) for r in rs)
            planned = sum(r["n_decisions"] for r in runs if r["agent"] == a and r["cond"] == cond)
            out["decisions-per-cell"]["%s-%s" % (a, cond)] = n
            lines.append("- `decisions-per-cell` %s %s: %d (valid runs: %d; planned decisions: %d)"
                         % (AGENT_LABEL[a], cond, n, len(rs), planned))

    lines.append("")
    lines.append("## Runs")
    for a in AGENTS:
        for cond in CONDS:
            rs = [r for r in runs if r["agent"] == a and r["cond"] == cond]
            inv = [r for r in rs if not r["valid"]]
            lines.append("- %s %s: planned %d, valid %d, invalid %d%s" % (
                AGENT_LABEL[a], cond, len(rs), len(rs) - len(inv), len(inv),
                (" (" + ", ".join("%s: %s" % (r["run"], r.get("invalid_reason") or "") for r in inv) + ")") if inv else ""))
    reruns = [r for r in runs if r.get("failures")]
    lines.append("- runs with at least one failed attempt: %d%s" % (len(reruns), (" (" + ", ".join(
        "%s: %s" % (r["run"], "; ".join(r["failures"])) for r in reruns) + ")") if reruns else ""))
    docs = [r["run"] for r in valid(runs) if r.get("doc_edited")]
    lines.append("- valid runs that edited the instruction file: %d%s" % (len(docs), (" (" + ", ".join(docs) + ")") if docs else ""))

    lines.append("")
    lines.append("## n and versions")
    with open(fix_path, encoding="utf-8") as fh:
        fix = fh.read().strip()
    import tiktoken
    n_tok = len(tiktoken.get_encoding("o200k_base").encode(fix))
    out["n"] = n_tok
    lines.append("- `n`: %d tokens (tiktoken o200k_base; sentence: \"%s\")" % (n_tok, fix))
    vers = collections.defaultdict(collections.Counter)
    models = collections.defaultdict(collections.Counter)
    for r in valid(runs):
        vers[r["agent"]][str(r.get("tool_version"))] += 1
        models[r["agent"]][str(r.get("model"))] += 1
    out["versions"] = {a: dict(vers[a]) for a in AGENTS}
    out["models"] = {a: dict(models[a]) for a in AGENTS}
    for a in AGENTS:
        lines.append("- %s version (as recorded in each valid run): %s" % (
            AGENT_LABEL[a], ", ".join("%s x%d" % kv for kv in sorted(vers[a].items())) or "none"))
        lines.append("- %s model (as recorded in each valid run): %s" % (
            AGENT_LABEL[a], ", ".join("%s x%d" % kv for kv in sorted(models[a].items())) or "none"))
    return out, lines


def cmd_numbers(args):
    runs = load(args.runs)
    out, lines = compute(runs, args.fix)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    head = ["# numbers", "",
            "All values come from runs.jsonl (%d planned runs). Percentages: one decimal, (numerator/denominator)."
            % len(runs), ""]
    with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(head + lines) + "\n")
    with open(os.path.splitext(args.out)[0] + ".json", "w", encoding="utf-8", newline="\n") as fh:
        json.dump(out, fh, indent=1)
    print("wrote", args.out)


# ---------------------------------------------------------------- figure

def cmd_figure(args):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    serif = [f for f in ("Times New Roman", "Nimbus Roman", "TeX Gyre Termes", "DejaVu Serif")
             if any(x.name == f for x in font_manager.fontManager.ttflist)]
    plt.rcParams.update({"font.family": "serif", "font.serif": serif + ["DejaVu Serif"], "pdf.fonttype": 42,
                         "ps.fonttype": 42, "font.size": 9, "axes.linewidth": 0.6, "hatch.linewidth": 0.6})
    runs = load(args.runs)
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(7.0, 6.4), gridspec_kw={"height_ratios": [1, 1.05]})

    styles = {"follow_file": dict(facecolor="0.15", edgecolor="black", hatch=""),
              "follow_code": dict(facecolor="white", edgecolor="black", hatch="////"),
              "neither": dict(facecolor="0.72", edgecolor="black", hatch="..")}
    groups = [(a, c) for a in AGENTS for c in CONDS]
    w = 0.26
    for gi, (a, c) in enumerate(groups):
        rs = valid(runs, a, c)
        cnt = choice_counts(rs)
        for vi, v in enumerate(VERDICTS):
            val = pct_val(cnt[v], cnt["total"]) if cnt["total"] else 0.0
            lo, hi = boot_ci(rs, verdict_fn(v)) if cnt["total"] else (0.0, 0.0)
            x = gi + (vi - 1) * w
            ax1.bar(x, val, w, linewidth=0.6, label=("follows the file" if v == "follow_file" else
                                                     "follows the code" if v == "follow_code" else "neither")
                    if gi == 0 else None, **styles[v])
            ax1.errorbar(x, val, yerr=[[val - lo], [hi - val]], fmt="none", ecolor="black", elinewidth=0.7,
                         capsize=2)
            ax1.text(x, hi + 1.5, "%.1f" % val, ha="center", va="bottom", fontsize=7)
    ax1.set_xticks(range(len(groups)))
    ax1.set_xticklabels(["%s\n%s" % (AGENT_LABEL[a], "condition A (empty)" if c == "A" else "condition B (fix sentence)")
                         for a, c in groups])
    ax1.set_ylabel("share of choices (%)")
    ax1.set_ylim(0, 112)
    ax1.set_yticks(range(0, 101, 20))
    ax1.legend(frameon=False, ncol=3, loc="upper center", bbox_to_anchor=(0.5, 1.13), fontsize=8)
    ax1.set_title("(a)", loc="left", fontsize=9, pad=14)
    for s in ("top", "right"):
        ax1.spines[s].set_visible(False)

    w2 = 0.38
    astyle = {"claude": dict(facecolor="0.15", edgecolor="black", hatch=""),
              "codex": dict(facecolor="white", edgecolor="black", hatch="\\\\\\\\")}
    for ai, a in enumerate(AGENTS):
        vals = []
        for cat in CATEGORIES:
            c = collections.Counter()
            for r in valid(runs, a, "A"):
                for v in r["verdicts"]:
                    if v["type"] == cat:
                        c[v["verdict"]] += 1
                        c["total"] += 1
            vals.append(pct_val(c["follow_file"], c["total"]) if c["total"] else 0.0)
        xs = [i + (ai - 0.5) * w2 for i in range(len(CATEGORIES))]
        ax2.bar(xs, vals, w2, linewidth=0.6, label=AGENT_LABEL[a], **astyle[a])
    ax2.axhline(50, color="black", linewidth=0.5, linestyle=(0, (3, 3)))
    ax2.set_xticks(range(len(CATEGORIES)))
    ax2.set_xticklabels(CATEGORIES, rotation=45, ha="right", fontsize=8)
    ax2.set_ylabel("follows the file, condition A (%)")
    ax2.set_ylim(0, 105)
    ax2.set_yticks(range(0, 101, 20))
    ax2.legend(frameon=False, ncol=2, loc="upper center", bbox_to_anchor=(0.5, 1.12), fontsize=8)
    ax2.set_title("(b)", loc="left", fontsize=9, pad=14)
    for s in ("top", "right"):
        ax2.spines[s].set_visible(False)
    fig.tight_layout(h_pad=2.0)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    fig.savefig(args.out, metadata={"CreationDate": None, "ModDate": None, "Producer": None, "Creator": None})
    print("wrote", args.out, "font:", serif[:1])


def cmd_rejudge(args):
    import sys
    sys.path.insert(0, HERE)
    import judge
    runs = load(args.runs)
    n = bad = 0
    for r in valid(runs):
        with open(os.path.join(ROOT, "tasks", r["repo"], "task.json"), encoding="utf-8") as fh:
            task = json.load(fh)
        new = [v["verdict"] for v in judge.judge(task, r["diff"])]
        old = [v["verdict"] for v in r["verdicts"]]
        n += 1
        if new != old:
            bad += 1
            print("differs:", r["run"], old, new)
    print("re-judged %d valid runs; %d differ" % (n, bad))
    return 1 if bad else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["numbers", "figure", "rejudge"])
    ap.add_argument("--runs", default=DEF_RUNS)
    ap.add_argument("--fix", default=DEF_FIX)
    ap.add_argument("--out")
    args = ap.parse_args()
    if not args.out:
        args.out = os.path.join(DEF_OUT, "numbers.md" if args.cmd == "numbers" else "fig-main.pdf")
    if args.cmd == "rejudge":
        raise SystemExit(cmd_rejudge(args))
    {"numbers": cmd_numbers, "figure": cmd_figure}[args.cmd](args)


if __name__ == "__main__":
    main()
