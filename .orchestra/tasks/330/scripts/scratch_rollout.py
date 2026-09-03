"""Scratch analyzer for #330: compaction frequency + cost in Codex rollouts."""
import json, glob, os, re, sys, collections

ROOT = os.path.expanduser("~/.codex/sessions")
files = sorted(glob.glob(os.path.join(ROOT, "2026/08/*/*.jsonl")))

# path-ish tokens inside tool inputs; literal-based, no catastrophic regex
PATH_RE = re.compile(r"[A-Za-z0-9_./-]*/[A-Za-z0-9_./-]+\.(?:py|md|js|toml|yaml|yml|json|sql|html|css|txt|sh|rs)")

sessions = []
for path in files:
    meta = None
    model = None
    events = []          # (ts, kind, payload-lite)
    try:
        fh = open(path, errors="replace")
    except OSError:
        continue
    with fh:
        for line in fh:
            if len(line) > 4_000_000:
                # giant compacted blob: only keep its size
                pass
            try:
                o = json.loads(line)
            except Exception:
                continue
            t = o.get("type")
            p = o.get("payload") or {}
            ts = o.get("timestamp")
            if t == "session_meta":
                meta = {"id": p.get("session_id"), "cwd": p.get("cwd"),
                        "ts": p.get("timestamp"), "orig": p.get("originator"),
                        "cli": p.get("cli_version")}
            elif t == "turn_context":
                model = p.get("model") or model
            elif t == "compacted":
                rh = p.get("replacement_history") or []
                events.append((ts, "compact", {"n_items": len(rh),
                                               "chars": len(json.dumps(rh, ensure_ascii=False))}))
            elif t == "event_msg":
                pt = p.get("type")
                if pt == "token_count":
                    info = p.get("info") or {}
                    last = info.get("last_token_usage") or {}
                    tot = info.get("total_token_usage") or {}
                    rl = (p.get("rate_limits") or {}).get("primary") or {}
                    events.append((ts, "tok", {
                        "in": last.get("input_tokens", 0),
                        "cached": last.get("cached_input_tokens", 0),
                        "out": last.get("output_tokens", 0),
                        "tin": tot.get("input_tokens", 0),
                        "tout": tot.get("output_tokens", 0),
                        "win": info.get("model_context_window"),
                        "pct": rl.get("used_percent"),
                    }))
                elif pt == "user_message":
                    events.append((ts, "user", {}))
            elif t == "response_item" and p.get("type") in ("custom_tool_call", "function_call"):
                inp = p.get("input") or p.get("arguments") or ""
                if not isinstance(inp, str):
                    inp = json.dumps(inp, ensure_ascii=False)
                paths = set(PATH_RE.findall(inp[:20000]))
                events.append((ts, "tool", {"name": p.get("name"), "paths": paths,
                                            "len": len(inp)}))
    if meta is None or not events:
        continue
    sessions.append({"path": path, "meta": meta, "model": model, "events": events})

print(f"sessions parsed: {len(sessions)}", file=sys.stderr)

out = {}

# ---------- A. compaction frequency ----------
per_sess = []
for s in sessions:
    toks = [e for e in s["events"] if e[1] == "tok"]
    comps = [e for e in s["events"] if e[1] == "compact"]
    if not toks:
        continue
    per_sess.append({
        "id": s["meta"]["id"], "date": s["meta"]["ts"], "model": s["model"],
        "cwd": s["meta"]["cwd"], "orig": s["meta"]["orig"],
        "n_req": len(toks), "n_comp": len(comps),
        "max_in": max(e[2]["in"] for e in toks),
        "tin": max(e[2]["tin"] for e in toks),
        "tout": max(e[2]["tout"] for e in toks),
        "win": collections.Counter(e[2]["win"] for e in toks).most_common(1)[0][0],
    })

out["A_sessions_total"] = len(per_sess)
out["A_sessions_with_compact"] = sum(1 for x in per_sess if x["n_comp"])
out["A_compactions_total"] = sum(x["n_comp"] for x in per_sess)
out["A_requests_total"] = sum(x["n_req"] for x in per_sess)
hist = collections.Counter(x["n_comp"] for x in per_sess)
out["A_hist_compacts_per_session"] = dict(sorted(hist.items()))
comp_sess = [x for x in per_sess if x["n_comp"]]
out["A_compacted_sessions_median_reqs"] = sorted(x["n_req"] for x in comp_sess)[len(comp_sess)//2] if comp_sess else None
clean = [x for x in per_sess if not x["n_comp"]]
out["A_clean_sessions_median_reqs"] = sorted(x["n_req"] for x in clean)[len(clean)//2] if clean else None
out["A_top_compactors"] = sorted(
    ({"n": x["n_comp"], "req": x["n_req"], "cwd": (x["cwd"] or "")[-45:], "model": x["model"]}
     for x in comp_sess), key=lambda d: -d["n"])[:12]
out["A_by_model"] = {}
bym = collections.defaultdict(lambda: [0, 0, 0, 0])
for x in per_sess:
    b = bym[x["model"]]
    b[0] += 1; b[1] += x["n_comp"]; b[2] += x["n_req"]; b[3] += 1 if x["n_comp"] else 0
out["A_by_model"] = {k: {"sessions": v[0], "compactions": v[1], "requests": v[2],
                         "sessions_with_compact": v[3]} for k, v in bym.items()}

# ---------- B. cost of one compaction ----------
comp_records = []
for s in sessions:
    ev = s["events"]
    for i, (ts, kind, pl) in enumerate(ev):
        if kind != "compact":
            continue
        before = None
        for j in range(i - 1, -1, -1):
            if ev[j][1] == "tok":
                before = ev[j][2]; break
        after = None
        for j in range(i + 1, len(ev)):
            if ev[j][1] == "tok":
                after = ev[j][2]; break
        comp_records.append({
            "sess": s["meta"]["id"], "model": s["model"], "ts": ts,
            "before_in": before["in"] if before else None,
            "before_cached": before["cached"] if before else None,
            "after_in": after["in"] if after else None,
            "repl_chars": pl["chars"], "repl_items": pl["n_items"],
            "idx": i, "n_ev": len(ev),
        })

def pct(vals, q):
    vals = sorted(v for v in vals if v is not None)
    if not vals:
        return None
    return vals[min(len(vals) - 1, int(q * len(vals)))]

bef = [c["before_in"] for c in comp_records]
aft = [c["after_in"] for c in comp_records]
out["B_n_compactions"] = len(comp_records)
out["B_before_in"] = {"p10": pct(bef, .10), "p50": pct(bef, .50), "p90": pct(bef, .90),
                      "mean": round(sum(v for v in bef if v) / max(1, len([v for v in bef if v])))}
out["B_after_in"] = {"p10": pct(aft, .10), "p50": pct(aft, .50), "p90": pct(aft, .90),
                     "mean": round(sum(v for v in aft if v) / max(1, len([v for v in aft if v])))}
pairs = [(c["before_in"], c["after_in"]) for c in comp_records if c["before_in"] and c["after_in"]]
out["B_pairs"] = len(pairs)
out["B_dropped_median"] = sorted(b - a for b, a in pairs)[len(pairs) // 2] if pairs else None
out["B_dropped_sum"] = sum(b - a for b, a in pairs)
out["B_before_sum"] = sum(b for b, a in pairs)

# ---------- C. re-reading after compaction ----------
reread = []
for s in sessions:
    ev = s["events"]
    comp_idx = [i for i, e in enumerate(ev) if e[1] == "compact"]
    if not comp_idx:
        continue
    for i in comp_idx:
        pre = set()
        for j in range(i):
            if ev[j][1] == "tool":
                pre |= ev[j][2]["paths"]
        post_calls = 0
        post_paths = set()
        nxt = next((k for k in comp_idx if k > i), len(ev))
        for j in range(i + 1, nxt):
            if ev[j][1] == "tool":
                post_calls += 1
                post_paths |= ev[j][2]["paths"]
        again = pre & post_paths
        reread.append({"sess": s["meta"]["id"], "pre_paths": len(pre),
                       "post_calls": post_calls, "post_paths": len(post_paths),
                       "reread_paths": len(again),
                       "examples": sorted(again)[:4]})
out["C_windows"] = len(reread)
out["C_windows_with_reread"] = sum(1 for r in reread if r["reread_paths"])
out["C_reread_paths_median"] = sorted(r["reread_paths"] for r in reread)[len(reread) // 2] if reread else None
out["C_reread_paths_sum"] = sum(r["reread_paths"] for r in reread)
out["C_post_paths_sum"] = sum(r["post_paths"] for r in reread)
out["C_examples"] = [r for r in reread if r["reread_paths"] >= 3][:8]

# ---------- D. request size distribution ----------
allin = []
for s in sessions:
    for ts, kind, pl in s["events"]:
        if kind == "tok":
            allin.append(pl["in"])
out["D_n_requests"] = len(allin)
out["D_pcts"] = {f"p{int(q*100)}": pct(allin, q) for q in (.5, .75, .9, .95, .99)}
out["D_max"] = max(allin) if allin else None
for thr in (200_000, 245_000, 258_400, 272_000):
    out[f"D_above_{thr}"] = sum(1 for v in allin if v > thr)

# ---------- E. windows in use ----------
out["E_windows"] = dict(collections.Counter(
    pl["win"] for s in sessions for ts, k, pl in s["events"] if k == "tok").most_common())

# ---------- F. per-session totals for simulation ----------
sim = [{"id": x["id"], "model": x["model"], "n_req": x["n_req"], "n_comp": x["n_comp"],
        "tin": x["tin"], "tout": x["tout"], "max_in": x["max_in"], "cwd": (x["cwd"] or "")[-40:]}
       for x in per_sess]
with open("/tmp/330_sessions.json", "w") as f:
    json.dump(sim, f)
with open("/tmp/330_compactions.json", "w") as f:
    json.dump([{k: v for k, v in c.items()} for c in comp_records], f)

print(json.dumps(out, ensure_ascii=False, indent=1, default=str))
