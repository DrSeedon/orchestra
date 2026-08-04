"""#138 — gold anchors, final: normalised-space anchoring against the files on disk.

History (both failures kept on the record, not hidden):
  v1 reconstructed docs by joining snapshot chunks -> did NOT round-trip (9448 -> 10289 pieces).
  v2 anchored by RAW substring on disk -> lost 9/22 anchors to pure whitespace differences.
  v3 (this) anchors in WHITESPACE-NORMALISED space and maps indices back to raw offsets:
     20/22 file anchors recovered. The 2 genuine losses are files rewritten since the snapshot
     (CHANGELOG.md grew; BUGS.md was gutted into a pointer by #114) - those queries are scored
     on their log anchors only, or excluded, and this is stated in the results, never silently.
"""
import json, os, re, sqlite3

ROOT = "/mnt/data/Projects/Python/orchestra"
DB = os.environ.get("BENCH_DB", f"{ROOT}/data/bench134/vec134.db")
HERE = os.path.dirname(os.path.abspath(__file__))
conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
conn.row_factory = sqlite3.Row
qs = json.load(open(os.path.join(HERE, "..", "..", "134", "bench", "queries.json")))["queries"]


def norm_map(s):
    """Collapse whitespace runs to one space; return (normalised, norm_idx -> raw_idx)."""
    out, idx, prev_ws = [], [], False
    for i, ch in enumerate(s):
        if ch.isspace():
            if prev_ws:
                continue
            out.append(" "); idx.append(i); prev_ws = True
        else:
            out.append(ch); idx.append(i); prev_ws = False
    return "".join(out), idx


out = {"_meta": {
    "task": "#138 chunker-independent gold anchors v3 (normalised-space, disk)",
    "db": DB, "root": ROOT,
    "rule": "hit = the retrieved chunk's raw char span in its file overlaps the gold raw span",
    "prior_attempts": ["v1 reconstruct-from-chunks: no round-trip, discarded",
                       "v2 raw substring: lost 9/22 anchors to whitespace, discarded"],
}, "gold": [], "dropped": []}

st = {"file": 0, "log": 0, "drop": 0}
for i, q in enumerate(qs):
    entry = {"i": i, "q": q["q"], "anchors": []}
    for cid in q["gold"]:
        r = conn.execute("SELECT f.path, fc.text FROM file_chunks fc JOIN files f "
                         "ON f.file_id=fc.file_id WHERE fc.chunk_id=?", (cid,)).fetchone()
        if r:
            content = open(os.path.join(ROOT, r["path"]), encoding="utf-8", errors="replace").read()
            nc, idx = norm_map(content)
            nt = re.sub(r"\s+", " ", r["text"]).strip()
            p = nc.find(nt)
            if p < 0:
                out["dropped"].append({"i": i, "cid": cid, "path": r["path"],
                                       "reason": "text absent from disk (file rewritten since snapshot)"})
                st["drop"] += 1
                continue
            entry["anchors"].append({
                "kind": "file", "orig_chunk_id": cid, "path": r["path"],
                "span": [idx[p], idx[min(p + len(nt) - 1, len(idx) - 1)] + 1],
                "core": r["text"][:200]})
            st["file"] += 1
        else:
            r = conn.execute("SELECT log_id, kind FROM log_chunks WHERE chunk_id=?", (cid,)).fetchone()
            entry["anchors"].append({"kind": "log", "orig_chunk_id": cid,
                                     "log_id": r["log_id"], "log_kind": r["kind"]})
            st["log"] += 1
    entry["scorable"] = bool(entry["anchors"])
    out["gold"].append(entry)

dest = os.path.join(HERE, "gold_anchors_v3.json")
json.dump(out, open(dest, "w"), ensure_ascii=False, indent=1)
print(f"wrote {dest}")
print(f"file={st['file']} log={st['log']} dropped={st['drop']}")
for d in out["dropped"]:
    print(f"  DROPPED Q{d['i']} {d['path']}")
print(f"scorable queries: {sum(1 for g in out['gold'] if g['scorable'])}/28")

bad = 0
for g in out["gold"]:
    for a in g["anchors"]:
        if a["kind"] != "file":
            continue
        c = open(os.path.join(ROOT, a["path"]), encoding="utf-8", errors="replace").read()
        s, e = a["span"]
        got = re.sub(r"\s+", " ", c[s:e]).strip()
        want = re.sub(r"\s+", " ", a["core"]).strip()
        if not got.startswith(want[:60]):
            bad += 1
            print(f"  SPAN FAIL Q{g['i']} {a['path']}")
print(f"span validation failures: {bad}")
