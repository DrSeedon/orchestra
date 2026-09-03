"""#330 pass 5: what compaction actually COSTS us today (the savings a big window would buy)."""
import json, glob, os
ROOT = os.path.expanduser("~/.codex/sessions")
STEADY = 0.989   # measured median cached share of a >50k request outside a compaction ramp
tot_excess_fresh = 0
tot_fresh = 0
tot_in = 0
n_ramp_reqs = 0
for path in sorted(glob.glob(os.path.join(ROOT, "2026/08/*/*.jsonl"))):
    seq = []
    for line in open(path, errors="replace"):
        if '"token_count"' not in line and '"compacted"' not in line:
            continue
        try: o = json.loads(line)
        except Exception: continue
        t = o.get("type"); p = o.get("payload") or {}
        if t == "compacted":
            seq.append(("comp", None))
        elif t == "event_msg" and p.get("type") == "token_count":
            l = (p.get("info") or {}).get("last_token_usage") or {}
            if l.get("input_tokens"):
                seq.append(("tok", (l["input_tokens"], l.get("cached_input_tokens", 0))))
    for i, (k, v) in enumerate(seq):
        if k == "tok":
            tot_in += v[0]; tot_fresh += v[0] - v[1]
        if k != "comp":
            continue
        # ramp: requests after this compaction until cached share recovers
        for j in range(i + 1, len(seq)):
            if seq[j][0] == "comp":
                break
            if seq[j][0] != "tok":
                continue
            in_t, cached = seq[j][1]
            if in_t and cached / in_t >= 0.95:
                break
            n_ramp_reqs += 1
            tot_excess_fresh += (in_t - cached) - in_t * (1 - STEADY)
print(json.dumps({
  "ramp_requests_with_degraded_cache": n_ramp_reqs,
  "excess_fresh_tokens_from_compaction": round(tot_excess_fresh),
  "total_fresh_tokens_all_sessions": tot_fresh,
  "total_input_tokens_all_sessions": tot_in,
  "excess_as_share_of_all_fresh": round(tot_excess_fresh / tot_fresh, 4),
}, indent=1))
