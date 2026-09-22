"""Tokens per 1% of the Codex 5h/7d window, by plan (pro vs plus), from Codex rollout logs.

Token deltas come from the monotonic total_token_usage of each session file (not summing
last_token_usage, which repeats across token_count events). The window percent is shared by
all sessions of the account, so tokens are aggregated across every file per (window, plan).
"""
import collections
import datetime
import glob
import json
import os

ROOT = os.path.expanduser("~/.orchestra/codex-home")
CUTOFF = datetime.datetime(2026, 9, 1).timestamp()
KEYS = ("input_tokens", "cached_input_tokens", "output_tokens")

agg = {"5h": collections.defaultdict(lambda: {"pcts": [], "tok": collections.Counter(), "files": set()}),
       "7d": collections.defaultdict(lambda: {"pcts": [], "tok": collections.Counter(), "files": set()})}

_seen = {}
for _root in (os.path.expanduser("~/.codex"), ROOT):
    for _f in glob.glob(_root + "/**/rollout-*.jsonl", recursive=True):
        if os.path.getmtime(_f) >= CUTOFF:
            _seen.setdefault(os.path.basename(_f), os.path.realpath(_f))
files = sorted(_seen.values())
for f in files:
    prev = None
    try:
        fh = open(f, errors="ignore")
    except OSError:
        continue
    for line in fh:
        if '"token_count"' not in line:
            continue
        try:
            p = json.loads(line).get("payload", {})
        except ValueError:
            continue
        info, rl = p.get("info") or {}, p.get("rate_limits") or {}
        tot = info.get("total_token_usage")
        if not tot or not rl.get("primary"):
            continue
        cur = tuple(tot.get(k, 0) for k in KEYS)
        delta = [0, 0, 0] if prev is None else [max(0, c - q) for c, q in zip(cur, prev)]
        if prev is None:
            delta = list(cur)
        prev = cur
        plan = rl.get("plan_type") or "?"
        for name, win in (("5h", rl.get("primary")), ("7d", rl.get("secondary"))):
            if not win:
                continue
            w = agg[name][(win["resets_at"], plan)]
            w["pcts"].append(win["used_percent"])
            w["files"].add(f)
            for k, d in zip(KEYS, delta):
                w["tok"][k] += d

print("files scanned:", len(files))
for name in ("5h", "7d"):
    print("==", name, "window  (unc_in = input - cached)")
    for (reset, plan), w in sorted(agg[name].items()):
        d = max(w["pcts"]) - min(w["pcts"])
        t = w["tok"]
        unc = t["input_tokens"] - t["cached_input_tokens"]
        when = datetime.datetime.fromtimestamp(reset, datetime.UTC).strftime("%m-%d %H:%M")
        per = f"per1%: unc_in={unc / d / 1e3:.0f}k cached={t['cached_input_tokens'] / d / 1e6:.2f}M out={t['output_tokens'] / d / 1e3:.1f}k" if d >= 5 else ""
        print(f"{when} {plan:5} pct {min(w['pcts']):.0f}->{max(w['pcts']):.0f} files={len(w['files'])} "
              f"unc_in={unc / 1e6:.2f}M cached={t['cached_input_tokens'] / 1e6:.1f}M out={t['output_tokens'] / 1e3:.0f}k {per}")
