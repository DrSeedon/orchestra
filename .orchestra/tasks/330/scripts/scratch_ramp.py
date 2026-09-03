"""#330 pass 2: what one compaction costs — cache invalidation, ramp-back, re-read tokens."""
import json, glob, os, sys, collections

ROOT = os.path.expanduser("~/.codex/sessions")
files = sorted(glob.glob(os.path.join(ROOT, "2026/08/*/*.jsonl")))

def pctl(vals, q):
    vals = sorted(v for v in vals if v is not None)
    return vals[min(len(vals) - 1, int(q * len(vals)))] if vals else None

ramps = []          # per compaction: trajectory after
steady_cache = []   # cache ratio in normal (non-post-compact) requests
post_cache = []     # cache ratio of first request after compaction
sessions_meta = []

for path in files:
    seq = []   # ordered: ('tok', d) | ('comp', d)
    model = None
    sid = None
    with open(path, errors="replace") as fh:
        for line in fh:
            if '"token_count"' not in line and '"compacted"' not in line \
               and '"turn_context"' not in line and '"session_meta"' not in line:
                continue
            try:
                o = json.loads(line)
            except Exception:
                continue
            t = o.get("type"); p = o.get("payload") or {}
            if t == "session_meta":
                sid = p.get("session_id")
            elif t == "turn_context":
                model = p.get("model") or model
            elif t == "compacted":
                seq.append(("comp", {"ts": o.get("timestamp")}))
            elif t == "event_msg" and p.get("type") == "token_count":
                info = p.get("info") or {}
                last = info.get("last_token_usage") or {}
                tot = info.get("total_token_usage") or {}
                seq.append(("tok", {
                    "in": last.get("input_tokens", 0),
                    "cached": last.get("cached_input_tokens", 0),
                    "cw": last.get("cache_write_input_tokens", 0),
                    "out": last.get("output_tokens", 0),
                    "tin": tot.get("input_tokens", 0),
                    "tout": tot.get("output_tokens", 0),
                    "win": info.get("model_context_window"),
                    "ts": o.get("timestamp"),
                }))
    if not seq:
        continue
    toks = [d for k, d in seq if k == "tok"]
    comps = sum(1 for k, _ in seq if k == "comp")
    if toks:
        sessions_meta.append({"id": sid, "model": model, "n_req": len(toks),
                              "n_comp": comps,
                              "tin": max(t["tin"] for t in toks),
                              "tout": max(t["tout"] for t in toks),
                              "max_in": max(t["in"] for t in toks),
                              "win": toks[0]["win"]})

    comp_positions = [i for i, (k, _) in enumerate(seq) if k == "comp"]
    for ci in comp_positions:
        # last real request before
        before = None
        for j in range(ci - 1, -1, -1):
            if seq[j][0] == "tok" and seq[j][1]["in"] > 0:
                before = seq[j][1]; break
        # trajectory of real requests after, until next compaction
        nxt = next((k for k in comp_positions if k > ci), len(seq))
        after = [seq[j][1] for j in range(ci + 1, nxt)
                 if seq[j][0] == "tok" and seq[j][1]["in"] > 0]
        zeros = sum(1 for j in range(ci + 1, nxt)
                    if seq[j][0] == "tok" and seq[j][1]["in"] == 0)
        if not before or not after:
            continue
        # requests needed to climb back to the pre-compaction size
        back = next((n for n, d in enumerate(after, 1) if d["in"] >= before["in"]), None)
        ramps.append({
            "model": model, "before": before["in"],
            "before_cached": before["cached"],
            "after0": after[0]["in"], "after0_cached": after[0]["cached"],
            "n_after": len(after), "zeros": zeros,
            "peak_after": max(d["in"] for d in after),
            "back_in_n": back,
            "sum_in_after": sum(d["in"] for d in after),
            "sum_cached_after": sum(d["cached"] for d in after),
        })
        if after[0]["in"]:
            post_cache.append(after[0]["cached"] / after[0]["in"])
    # steady-state cache ratio: requests not immediately after a compaction
    post_idx = {ci + 1 for ci in comp_positions}
    for i, (k, d) in enumerate(seq):
        if k == "tok" and d["in"] > 50_000 and i not in post_idx:
            steady_cache.append(d["cached"] / d["in"])

out = {}
out["n_ramps"] = len(ramps)
out["before_p50"] = pctl([r["before"] for r in ramps], .5)
out["after0_p50"] = pctl([r["after0"] for r in ramps], .5)
out["after0_p90"] = pctl([r["after0"] for r in ramps], .9)
drops = [r["before"] - r["after0"] for r in ramps]
out["drop_p50"] = pctl(drops, .5)
out["drop_mean"] = round(sum(drops) / len(drops)) if drops else None
out["drop_sum"] = sum(drops)
out["cache_steady_p50"] = round(pctl(steady_cache, .5), 4) if steady_cache else None
out["cache_steady_mean"] = round(sum(steady_cache) / len(steady_cache), 4) if steady_cache else None
out["cache_post_compact_p50"] = round(pctl(post_cache, .5), 4) if post_cache else None
out["cache_post_compact_mean"] = round(sum(post_cache) / len(post_cache), 4) if post_cache else None
out["n_steady_samples"] = len(steady_cache)
back = [r["back_in_n"] for r in ramps if r["back_in_n"]]
out["ramped_back_count"] = len(back)
out["ramped_back_share"] = round(len(back) / len(ramps), 3) if ramps else None
out["back_in_n_p50"] = pctl(back, .5)
out["back_in_n_p90"] = pctl(back, .9)
out["n_after_p50"] = pctl([r["n_after"] for r in ramps], .5)
out["zeros_total"] = sum(r["zeros"] for r in ramps)
# uncached (billable-at-full-rate) input right after compaction vs steady
out["uncached_first_after_p50"] = pctl(
    [r["after0"] - r["after0_cached"] for r in ramps], .5)

with open("/tmp/330_ramps.json", "w") as f:
    json.dump(ramps, f)
with open("/tmp/330_sessions2.json", "w") as f:
    json.dump(sessions_meta, f)
print(json.dumps(out, ensure_ascii=False, indent=1))
