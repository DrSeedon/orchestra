"""#138 — what actually OCCUPIES the top-5 when gold does not? Names the competitor, not the score.

#135 proved the failures are ranking, not coverage, and that no fusion parameter fixes them.
It never asked what the winning chunks ARE. If the top-5 is full of vendored third-party docs
or near-duplicate boilerplate, the fix is corpus hygiene, not ranking.
"""
import json, os, sqlite3, struct, sys, collections

ROOT = os.environ.get("ORCHESTRA_ROOT", "/mnt/data/Projects/Python/orchestra")
DB = os.environ["BENCH_DB"]
HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = "/mnt/data/Projects/Python/orchestra"
FINAL_K, POOL_MULT = 5, 4

sys.path.insert(0, ROOT)
os.environ.setdefault("FASTEMBED_CACHE_PATH", os.path.join(ROOT, "data", "models"))
import app.rag as rag
import sqlite_vec

conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
conn.enable_load_extension(True); sqlite_vec.load(conn); conn.enable_load_extension(False)
conn.row_factory = sqlite3.Row
qs = json.load(open(os.environ.get("QUERIES", os.path.join(HERE, "queries134.json"))))["queries"]
labels = {x["i"]: x["label"] for x in json.load(open(os.path.join(HERE, "labels.json")))["labels"]}


def _pack(v):
    return struct.pack(f"{len(v)}f", *v)


def search(text):
    pool = FINAL_K * POOL_MULT
    qv = [list(map(float, v)) for v in rag._get_embedder().embed([text])][0]
    fv = [("file", r["chunk_id"]) for r in conn.execute(
        "SELECT chunk_id FROM vec_files WHERE project=? AND embedding MATCH ? ORDER BY distance LIMIT ?",
        (PROJ, _pack(qv), pool * 3))][:pool]
    lv = [("log", r["chunk_id"]) for r in conn.execute(
        "SELECT chunk_id FROM vec_logs WHERE project=? AND embedding MATCH ? ORDER BY distance LIMIT ?",
        (PROJ, _pack(qv), pool * 3))][:pool]
    m = rag.RagMemory._expand_query(text) or ('"' + text.replace('"', '""') + '"')
    ff = [("file", r["chunk_id"]) for r in conn.execute(
        "SELECT ft.rowid AS chunk_id FROM fts_files ft JOIN file_chunks fc ON fc.chunk_id=ft.rowid "
        "JOIN files f ON f.file_id=fc.file_id WHERE fts_files MATCH ? AND f.project=? ORDER BY rank "
        "LIMIT ?", (m, PROJ, pool * 3))][:pool]
    lf = [("log", r["chunk_id"]) for r in conn.execute(
        "SELECT ft.rowid AS chunk_id FROM fts_logs ft JOIN log_chunks lc ON lc.chunk_id=ft.rowid "
        "JOIN logs_indexed li ON li.log_id=lc.log_id WHERE fts_logs MATCH ? AND li.project=? "
        "ORDER BY rank LIMIT ?", (m, PROJ, pool * 3))][:pool]
    return rag.RagMemory._rrf(fv, ff, lv, lf)[:FINAL_K]


def describe(kind, cid):
    if kind == "file":
        r = conn.execute("SELECT f.path, fc.text FROM file_chunks fc JOIN files f ON f.file_id=fc.file_id "
                         "WHERE fc.chunk_id=?", (cid,)).fetchone()
        return (r["path"], r["text"]) if r else ("?", "")
    r = conn.execute("SELECT lc.text, lc.kind, lc.author FROM log_chunks lc WHERE lc.chunk_id=?",
                     (cid,)).fetchone()
    return (f"LOG:{r['kind']}/{r['author']}", r["text"]) if r else ("?", "")


bucket = collections.Counter()
occupancy = collections.Counter()
misses = []
for i, q in enumerate(qs):
    gold = set(q["gold"])
    top = search(q["q"])
    hit = any(k in gold for _, k in top)
    for kind, key in top:
        path, _ = describe(kind, key)
        if kind == "log":
            occupancy["log"] += 1
        elif path.startswith("data/"):
            occupancy["file:data/ (vendored)"] += 1
        elif path.startswith("docs/tasks"):
            occupancy["file:docs/tasks"] += 1
        elif path.startswith("docs/"):
            occupancy["file:docs/ other"] += 1
        else:
            occupancy["file:root (CLAUDE/CHANGELOG/...)"] += 1
    if not hit:
        misses.append(i)
        print(f"\n### MISS Q{i} [{labels[i]}] {q['q']}")
        for pos, (kind, key) in enumerate(top, 1):
            path, txt = describe(kind, key)
            print(f"   {pos}. {path}  :: {txt[:110].strip()}")

print(f"\n=== top-5 occupancy across all {len(qs)} queries ({len(qs)*5} slots) ===")
for k, v in occupancy.most_common():
    print(f"{v:>4} ({v/(len(qs)*5):5.1%})  {k}")
print(f"\ncorpus share for reference: data/ = 20.6% of file chunks")
print(f"misses: {misses}")
