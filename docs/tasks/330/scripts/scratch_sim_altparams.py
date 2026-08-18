"""#330 pass 4: CORRECTED counterfactual.

Two fixes to pass 3, both of which cut AGAINST the "big window loses" conclusion:
  1. A 872K window still compacts, just later. Pass 3 let context grow unbounded
     past 828_400 in 8_995 requests, which inflated the counterfactual.
     Here the counterfactual compacts at the SAME RELATIVE FILL we measure today.
  2. Part of the post-compaction context regrowth is re-reading of files that were
     already in context. Those tokens are counted once in the observed `in` and a
     second time inside `offset`. Discount factor from measurement.

Units: multiples of the model's uncached input price (model-invariant for gpt-5.6).
"""
import json, glob, os, re, sys, collections

ROOT = os.path.expanduser("~/.codex/sessions")
files = sorted(glob.glob(os.path.join(ROOT, "2026/08/*/*.jsonl")))

SHORT = dict(fresh=1.0, cached=0.1, write=1.25, out=6.0)
LONG = dict(fresh=2.0, cached=0.2, write=2.5, out=9.0)
THRESHOLD = 272_000
SMALL_WIN = 258_400
BIG_WIN = 828_400
FILL_TRIGGER = 0.862          # measured: compaction fires at p50 222_632 / 258_400
FILL_FLOOR = 0.265            # measured: lands at p50 68_437 / 258_400
SUMMARY_OUT = 3_000
REREAD_DISCOUNT = float(sys.argv[1]) if len(sys.argv) > 1 else 0.286

BIG_TRIGGER = float(os.environ.get("TRIG_ABS", "0")) or BIG_WIN * FILL_TRIGGER      # 714_080
BIG_FLOOR = float(os.environ.get("FLOOR_ABS", "0")) or BIG_WIN * FILL_FLOOR          # 219_526


def units(in_t, cached, cw, out, long_tier):
    r = LONG if long_tier else SHORT
    fresh = max(0, in_t - cached - cw)
    return fresh * r["fresh"] + cached * r["cached"] + cw * r["write"] + out * r["out"]


agg = collections.Counter()
rows = []

for path in files:
    seq = []
    model = None
    with open(path, errors="replace") as fh:
        for line in fh:
            if ('"token_count"' not in line and '"compacted"' not in line
                    and '"turn_context"' not in line):
                continue
            try:
                o = json.loads(line)
            except Exception:
                continue
            t = o.get("type"); p = o.get("payload") or {}
            if t == "turn_context":
                model = p.get("model") or model
            elif t == "compacted":
                seq.append(("comp", {}))
            elif t == "event_msg" and p.get("type") == "token_count":
                info = p.get("info") or {}
                last = info.get("last_token_usage") or {}
                if not last.get("input_tokens"):
                    continue
                seq.append(("tok", {"in": last["input_tokens"],
                                    "cached": last.get("cached_input_tokens", 0),
                                    "cw": last.get("cache_write_input_tokens", 0),
                                    "out": last.get("output_tokens", 0)}))
    toks = [d for k, d in seq if k == "tok"]
    if not toks:
        continue
    n_comp = sum(1 for k, _ in seq if k == "comp")

    # ---------- observed world: small window ----------
    actual = sum(units(d["in"], d["cached"], d["cw"], d["out"], d["in"] > THRESHOLD)
                 for d in toks)
    comp_extra = 0.0
    for i, (k, _) in enumerate(seq):
        if k != "comp":
            continue
        for j in range(i - 1, -1, -1):
            if seq[j][0] == "tok":
                b = seq[j][1]
                comp_extra += units(b["in"], b["cached"], 0, SUMMARY_OUT,
                                    b["in"] > THRESHOLD)
                break

    # ---------- counterfactual world: 872K window, still compacts ----------
    offset = 0.0
    cf = 0.0
    cf_comp = 0
    cf_long = 0
    last_cf_in = 0
    last_cf_cached = 0
    for i, (k, d) in enumerate(seq):
        if k == "comp":
            before = after = None
            for j in range(i - 1, -1, -1):
                if seq[j][0] == "tok":
                    before = seq[j][1]["in"]; break
            for j in range(i + 1, len(seq)):
                if seq[j][0] == "tok":
                    after = seq[j][1]["in"]; break
            if before and after:
                offset += max(0, before - after) * (1.0 - REREAD_DISCOUNT)
            continue
        if k != "tok":
            continue
        cin = d["in"] + offset
        if cin > BIG_TRIGGER:
            # the big window compacts too: pay a summarisation call at the long tier,
            # then drop to the same relative floor
            cf += units(int(last_cf_in or cin), int(last_cf_cached or cin * 0.98), 0,
                        SUMMARY_OUT, True)
            cf_comp += 1
            offset = max(0.0, BIG_FLOOR - d["in"])
            cin = d["in"] + offset
        ccached = min(d["cached"] + offset, cin)
        long_tier = cin > THRESHOLD
        if long_tier:
            cf_long += 1
        cf += units(cin, ccached, d["cw"], d["out"], long_tier)
        last_cf_in, last_cf_cached = cin, ccached

    agg["actual"] += actual
    agg["comp_extra"] += comp_extra
    agg["cf"] += cf
    agg["reqs"] += len(toks)
    agg["n_comp"] += n_comp
    agg["cf_comp"] += cf_comp
    agg["cf_long"] += cf_long
    if n_comp:
        agg["actual_c"] += actual
        agg["comp_extra_c"] += comp_extra
        agg["cf_c"] += cf
        agg["reqs_c"] += len(toks)
        agg["cf_long_c"] += cf_long
        agg["cf_comp_c"] += cf_comp
    rows.append({"model": model, "n_comp": n_comp, "reqs": len(toks),
                 "actual": actual + comp_extra, "cf": cf, "cf_long": cf_long})

small = agg["actual"] + agg["comp_extra"]
out = {
    "reread_discount_used": REREAD_DISCOUNT,
    "big_trigger_tokens": round(BIG_TRIGGER),
    "big_floor_tokens": round(BIG_FLOOR),
    "requests": agg["reqs"],
    "compactions_observed": agg["n_comp"],
    "compactions_counterfactual": agg["cf_comp"],
    "compaction_reduction": round(1 - agg["cf_comp"] / max(1, agg["n_comp"]), 3),
    "units_small_window": round(small),
    "units_big_window": round(agg["cf"]),
    "ratio_big_over_small_ALL": round(agg["cf"] / small, 3),
    "ratio_big_over_small_COMPACTED_ONLY": round(
        agg["cf_c"] / (agg["actual_c"] + agg["comp_extra_c"]), 3),
    "long_tier_requests": agg["cf_long"],
    "long_tier_share_all": round(agg["cf_long"] / agg["reqs"], 4),
    "long_tier_share_compacted_sessions": round(agg["cf_long_c"] / max(1, agg["reqs_c"]), 4),
    "compaction_overhead_share_of_today": round(agg["comp_extra"] / agg["actual"], 4),
}
# sessions that never compact: does the big window change them at all?
clean = [r for r in rows if not r["n_comp"]]
out["clean_sessions"] = len(clean)
out["clean_ratio"] = round(sum(r["cf"] for r in clean) / max(1, sum(r["actual"] for r in clean)), 4)
out["clean_long_tier_requests"] = sum(r["cf_long"] for r in clean)
print(json.dumps(out, ensure_ascii=False, indent=1))
