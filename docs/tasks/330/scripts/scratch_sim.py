"""#330 pass 3: counterfactual simulation — small window (compaction) vs 872K window.

All costs in NORMALISED UNITS = multiples of the model's uncached input price.
The ratio table is identical for every gpt-5.6 model (sol 5/0.5/6.25/30,
luna 0.2/0.02/0.25/1.2 -> 1 / 0.1 / 1.25 / 6), so the unit is model-invariant.
Long-context tier (>272_000 input tokens, per developers.openai.com pricing table):
sol 10/1/12.5/45 -> 2 / 0.2 / 2.5 / 9.
"""
import json, glob, os, re, sys, collections

ROOT = os.path.expanduser("~/.codex/sessions")
files = sorted(glob.glob(os.path.join(ROOT, "2026/08/*/*.jsonl")))

SHORT = dict(fresh=1.0, cached=0.1, write=1.25, out=6.0)
LONG = dict(fresh=2.0, cached=0.2, write=2.5, out=9.0)
THRESHOLD = 272_000
BIG_EFFECTIVE = 828_400          # 872_000 x 0.95
SUMMARY_OUT_TOKENS = 3_000       # assumption, sensitivity reported separately

PATH_RE = re.compile(r"[A-Za-z0-9_./-]*/[A-Za-z0-9_./-]+\.(?:py|md|js|toml|yaml|yml|json|sql|html|css|txt|sh|rs)")


def units(in_t, cached, cw, out, long_tier):
    r = LONG if long_tier else SHORT
    fresh = max(0, in_t - cached - cw)
    return fresh * r["fresh"] + cached * r["cached"] + cw * r["write"] + out * r["out"]


agg = collections.Counter()
sess_rows = []
reread_tokens_total = 0
reread_tokens_windows = []

for path in files:
    seq = []
    model = None
    sid = None
    pending_paths = {}          # call_id -> paths
    with open(path, errors="replace") as fh:
        for line in fh:
            if ('"token_count"' not in line and '"compacted"' not in line
                    and '"turn_context"' not in line and '"session_meta"' not in line
                    and '"custom_tool_call' not in line and '"function_call' not in line):
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
                seq.append(("comp", {}))
            elif t == "event_msg" and p.get("type") == "token_count":
                info = p.get("info") or {}
                last = info.get("last_token_usage") or {}
                if not last.get("input_tokens"):
                    continue
                seq.append(("tok", {
                    "in": last["input_tokens"],
                    "cached": last.get("cached_input_tokens", 0),
                    "cw": last.get("cache_write_input_tokens", 0),
                    "out": last.get("output_tokens", 0),
                }))
            elif t == "response_item":
                pt = p.get("type")
                if pt in ("custom_tool_call", "function_call"):
                    inp = p.get("input") or p.get("arguments") or ""
                    if not isinstance(inp, str):
                        inp = json.dumps(inp, ensure_ascii=False)
                    pending_paths[p.get("call_id")] = set(PATH_RE.findall(inp[:20000]))
                elif pt in ("custom_tool_call_output", "function_call_output"):
                    outp = p.get("output")
                    if isinstance(outp, list):
                        n = sum(len(x.get("text", "")) for x in outp if isinstance(x, dict))
                    else:
                        n = len(outp) if isinstance(outp, str) else 0
                    seq.append(("toolout", {
                        "paths": pending_paths.pop(p.get("call_id"), set()),
                        "tokens": n // 4,
                    }))
    toks = [d for k, d in seq if k == "tok"]
    if not toks:
        continue
    comps = [i for i, (k, _) in enumerate(seq) if k == "comp"]

    # ---- re-read tokens: tool outputs after a compaction whose path was already seen
    if comps:
        seen = set()
        rr = 0
        for i, (k, d) in enumerate(seq):
            if k != "toolout":
                continue
            after_comp = any(c < i for c in comps)
            if after_comp and d["paths"] & seen:
                rr += d["tokens"]
            seen |= d["paths"]
        reread_tokens_total += rr
        if rr:
            reread_tokens_windows.append(rr)

    # ---- actual (small window) cost
    actual = sum(units(d["in"], d["cached"], d["cw"], d["out"], d["in"] > THRESHOLD)
                 for d in toks)
    # compaction summarisation calls, absent from Codex's own totals
    comp_extra = 0.0
    for ci in comps:
        before = None
        for j in range(ci - 1, -1, -1):
            if seq[j][0] == "tok":
                before = seq[j][1]; break
        if before:
            comp_extra += units(before["in"], before["cached"], 0,
                                SUMMARY_OUT_TOKENS, before["in"] > THRESHOLD)

    # ---- counterfactual (872K window, no compaction)
    offset = 0
    cf = 0.0
    cf_long_reqs = 0
    cf_reqs = 0
    cf_overflow = 0
    prev_before = None
    ci_set = set(comps)
    for i, (k, d) in enumerate(seq):
        if k == "comp":
            # drop = last real request before minus first real request after
            before = None
            for j in range(i - 1, -1, -1):
                if seq[j][0] == "tok":
                    before = seq[j][1]["in"]; break
            after = None
            for j in range(i + 1, len(seq)):
                if seq[j][0] == "tok":
                    after = seq[j][1]["in"]; break
            if before and after:
                offset += max(0, before - after)
            continue
        if k != "tok":
            continue
        cf_reqs += 1
        cin = d["in"] + offset
        ccached = d["cached"] + offset
        if cin > BIG_EFFECTIVE:
            cf_overflow += 1
        long_tier = cin > THRESHOLD
        if long_tier:
            cf_long_reqs += 1
        cf += units(cin, min(ccached, cin), d["cw"], d["out"], long_tier)

    agg["actual"] += actual
    agg["comp_extra"] += comp_extra
    agg["cf"] += cf
    agg["reqs"] += len(toks)
    agg["cf_long_reqs"] += cf_long_reqs
    agg["cf_overflow"] += cf_overflow
    agg["n_comp"] += len(comps)
    if comps:
        agg["actual_c"] += actual
        agg["comp_extra_c"] += comp_extra
        agg["cf_c"] += cf
        agg["reqs_c"] += len(toks)
    sess_rows.append({"id": sid, "model": model, "n_comp": len(comps),
                      "reqs": len(toks), "actual": actual, "comp_extra": comp_extra,
                      "cf": cf, "cf_long": cf_long_reqs, "cf_overflow": cf_overflow,
                      "max_in": max(d["in"] for d in toks)})

out = {}
out["sessions"] = len(sess_rows)
out["requests"] = agg["reqs"]
out["compactions"] = agg["n_comp"]
out["units_actual_all"] = round(agg["actual"])
out["units_actual_plus_compact_all"] = round(agg["actual"] + agg["comp_extra"])
out["units_counterfactual_all"] = round(agg["cf"])
out["ratio_all"] = round(agg["cf"] / (agg["actual"] + agg["comp_extra"]), 3)

out["compacted_sessions"] = sum(1 for s in sess_rows if s["n_comp"])
out["units_actual_compacted"] = round(agg["actual_c"])
out["units_actual_plus_compact_compacted"] = round(agg["actual_c"] + agg["comp_extra_c"])
out["units_cf_compacted"] = round(agg["cf_c"])
out["ratio_compacted"] = round(agg["cf_c"] / (agg["actual_c"] + agg["comp_extra_c"]), 3)
out["compaction_overhead_share"] = round(agg["comp_extra"] / agg["actual"], 4)

out["cf_long_requests"] = agg["cf_long_reqs"]
out["cf_long_share_of_all"] = round(agg["cf_long_reqs"] / agg["reqs"], 4)
out["cf_long_share_of_compacted_sessions"] = round(
    agg["cf_long_reqs"] / max(1, agg["reqs_c"]), 4)
out["cf_overflow_requests_above_828400"] = agg["cf_overflow"]

out["reread_tokens_total"] = reread_tokens_total
out["reread_windows"] = len(reread_tokens_windows)
out["reread_tokens_median_per_session"] = (
    sorted(reread_tokens_windows)[len(reread_tokens_windows) // 2]
    if reread_tokens_windows else None)

# worst sessions by counterfactual blow-up
worst = sorted((s for s in sess_rows if s["n_comp"]),
               key=lambda s: -(s["cf"] - s["actual"] - s["comp_extra"]))[:10]
out["worst"] = [{"comp": s["n_comp"], "reqs": s["reqs"],
                 "actual_M": round((s["actual"] + s["comp_extra"]) / 1e6, 2),
                 "cf_M": round(s["cf"] / 1e6, 2),
                 "ratio": round(s["cf"] / max(1, s["actual"] + s["comp_extra"]), 2),
                 "long": s["cf_long"], "ovf": s["cf_overflow"],
                 "model": s["model"]} for s in worst]

with open("/tmp/330_sim_sessions.json", "w") as f:
    json.dump(sess_rows, f)
print(json.dumps(out, ensure_ascii=False, indent=1))
