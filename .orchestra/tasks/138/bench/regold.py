"""#138 — solve the reindexing obstacle: remap gold from chunk_id to a chunker-independent anchor.

Problem (#135 §10): rechunking changes chunk_id, so gold pairs from #134 break, and the
CHUNK_SIZE / MD_MAX_CHUNK question stays permanently unmeasurable.

Solution: gold is not really "chunk 6000". Gold is "the passage of CHANGELOG.md that answers
this query". Anchor it as a CHARACTER SPAN in the reconstructed source document. Any future
chunking is then scored by: does the top-k contain a chunk that overlaps the gold span?

Reconstruction source: the SNAPSHOT's own stored chunks (not the live file), so the anchor is
valid for the corpus the #134/#135 numbers were measured on. Files drift; the snapshot does not.
"""
import json, os, sqlite3, sys

DB = os.environ.get("BENCH_DB", "/mnt/data/Projects/Python/orchestra/data/bench134/vec134.db")
HERE = os.path.dirname(os.path.abspath(__file__))
QUERIES = os.path.join(HERE, "..", "..", "134", "bench", "queries.json")
PROJ = "/mnt/data/Projects/Python/orchestra"

conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
conn.row_factory = sqlite3.Row
qs = json.load(open(QUERIES))["queries"]


def file_chunks_in_order(path):
    """All snapshot chunks of one file, in chunk_id order (= document order, id=file_id*STRIDE+idx)."""
    return conn.execute(
        "SELECT fc.chunk_id, fc.text FROM file_chunks fc JOIN files f ON f.file_id=fc.file_id "
        "WHERE f.project=? AND f.path=? ORDER BY fc.chunk_id", (PROJ, path)).fetchall()


out = {"_meta": {
    "task": "#138 chunker-independent gold anchors",
    "db": DB,
    "rule": "A retrieved chunk COUNTS as a hit if its text overlaps the gold span by >= MIN_OVERLAP "
            "characters of the gold's distinctive core, OR contains the gold anchor substring.",
    "why": "chunk_id is an artifact of one chunking config; the ANSWER is a region of a document.",
}, "gold": []}

stats = {"file": 0, "log": 0, "span_ok": 0}
for i, q in enumerate(qs):
    entry = {"i": i, "q": q["q"], "anchors": []}
    for cid in q["gold"]:
        r = conn.execute(
            "SELECT f.path, fc.text FROM file_chunks fc JOIN files f ON f.file_id=fc.file_id "
            "WHERE fc.chunk_id=?", (cid,)).fetchone()
        if r:
            stats["file"] += 1
            chunks = file_chunks_in_order(r["path"])
            doc, off, span = "", None, None
            for c in chunks:
                if c["chunk_id"] == cid:
                    off = len(doc)
                    span = (off, off + len(c["text"]))
                doc += c["text"] + "\n"
            assert span, f"chunk {cid} not found in its own file listing"
            entry["anchors"].append({
                "kind": "file", "orig_chunk_id": cid, "path": r["path"],
                "span": span, "doc_len": len(doc),
                "core": r["text"][:200],
            })
            stats["span_ok"] += 1
        else:
            r = conn.execute(
                "SELECT lc.text, lc.log_id, lc.kind FROM log_chunks lc WHERE lc.chunk_id=?",
                (cid,)).fetchone()
            stats["log"] += 1
            entry["anchors"].append({
                "kind": "log", "orig_chunk_id": cid, "log_id": r["log_id"],
                "log_kind": r["kind"], "core": r["text"][:200],
            })
    out["gold"].append(entry)

dest = os.path.join(HERE, "gold_anchors.json")
json.dump(out, open(dest, "w"), ensure_ascii=False, indent=1)
print(f"wrote {dest}")
print(f"file anchors={stats['file']} (spans resolved={stats['span_ok']}), log anchors={stats['log']}")

# --- validation: does the anchor round-trip? re-find each span's core in its reconstructed doc
bad = 0
for e in out["gold"]:
    for a in e["anchors"]:
        if a["kind"] != "file":
            continue
        chunks = file_chunks_in_order(a["path"])
        doc = "".join(c["text"] + "\n" for c in chunks)
        s, t = a["span"]
        if a["core"] not in doc[s:t]:
            bad += 1
            print(f"  ROUND-TRIP FAIL Q{e['i']} {a['path']}")
print(f"round-trip failures: {bad}")
