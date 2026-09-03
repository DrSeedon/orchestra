"""#138 — gold anchors v2: anchor to the LIVE FILE on disk, not to a lossy reconstruction.

v1 rebuilt each document by joining snapshot chunks with '\n'. That does NOT round-trip:
the shipped chunker merges small sections and strips whitespace, so re-chunking the join
produced 10289 pieces where the snapshot had 9448 (CLAUDE.md 33 -> 44). Any arm comparison
on top of that would have measured my join artifact. Verified and discarded.

v2: chunk the real files. 451/459 files reproduce the snapshot chunk count exactly from disk,
so disk == the corpus the #134 numbers were measured on, except for 8 files edited since.
For gold whose text is no longer present on disk, the anchor is dropped and the query is
excluded from file-side scoring (recorded explicitly, not silently).
"""
import json, os, re, sqlite3, sys

ROOT = "/mnt/data/Projects/Python/orchestra"
DB = os.environ.get("BENCH_DB", f"{ROOT}/data/bench134/vec134.db")
HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = ROOT

conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
conn.row_factory = sqlite3.Row
qs = json.load(open(os.path.join(HERE, "..", "..", "134", "bench", "queries.json")))["queries"]

norm = lambda s: re.sub(r"\s+", " ", s).strip()

out = {"_meta": {
    "task": "#138 chunker-independent gold anchors, v2 (disk-anchored)",
    "db": DB,
    "rule": "hit = retrieved chunk's char span in its file overlaps the gold span in the same file",
    "v1_discarded": "reconstruct-from-chunks did not round-trip (9448 -> 10289 pieces); see docstring",
}, "gold": [], "dropped": []}

stats = {"file_ok": 0, "file_dropped": 0, "log": 0}
for i, q in enumerate(qs):
    entry = {"i": i, "q": q["q"], "anchors": []}
    for cid in q["gold"]:
        r = conn.execute(
            "SELECT f.path, fc.text FROM file_chunks fc JOIN files f ON f.file_id=fc.file_id "
            "WHERE fc.chunk_id=?", (cid,)).fetchone()
        if r:
            path = r["path"]
            disk = os.path.join(ROOT, path)
            content = open(disk, encoding="utf-8", errors="replace").read()
            pos = content.find(r["text"])
            if pos >= 0:
                span = (pos, pos + len(r["text"]))
            else:
                # whitespace-tolerant: locate via normalised text, map back by anchoring on a
                # distinctive raw prefix/suffix token run
                nc, nt = norm(content), norm(r["text"])
                if nt not in nc:
                    out["dropped"].append({"i": i, "cid": cid, "path": path,
                                           "reason": "gold text no longer on disk (file edited since snapshot)"})
                    stats["file_dropped"] += 1
                    continue
                head = r["text"][:60].strip()
                pos = content.find(head)
                if pos < 0:
                    out["dropped"].append({"i": i, "cid": cid, "path": path,
                                           "reason": "normalised match but no raw anchor"})
                    stats["file_dropped"] += 1
                    continue
                span = (pos, pos + len(r["text"]))
            entry["anchors"].append({"kind": "file", "orig_chunk_id": cid, "path": path,
                                     "span": span, "core": r["text"][:200]})
            stats["file_ok"] += 1
        else:
            r = conn.execute("SELECT text, log_id, kind FROM log_chunks WHERE chunk_id=?",
                             (cid,)).fetchone()
            entry["anchors"].append({"kind": "log", "orig_chunk_id": cid,
                                     "log_id": r["log_id"], "log_kind": r["kind"],
                                     "core": r["text"][:200]})
            stats["log"] += 1
    out["gold"].append(entry)

dest = os.path.join(HERE, "gold_anchors_v2.json")
json.dump(out, open(dest, "w"), ensure_ascii=False, indent=1)
print(f"wrote {dest}")
print(f"file anchors ok={stats['file_ok']} dropped={stats['file_dropped']} log={stats['log']}")
for d in out["dropped"]:
    print(f"  DROPPED Q{d['i']} {d['path']}: {d['reason']}")
n_scorable = sum(1 for g in out["gold"] if g["anchors"])
print(f"queries with >=1 usable anchor: {n_scorable}/28")

# validate: every file anchor's span really contains its core, on disk
bad = 0
for g in out["gold"]:
    for a in g["anchors"]:
        if a["kind"] != "file":
            continue
        c = open(os.path.join(ROOT, a["path"]), encoding="utf-8", errors="replace").read()
        s, e = a["span"]
        if a["core"][:50] not in c[s:e]:
            bad += 1
            print(f"  SPAN FAIL Q{g['i']} {a['path']}")
print(f"span validation failures: {bad}")
