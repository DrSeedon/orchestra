"""#138 Phase 2 — which SPLIT design actually delivers the measured gain? Decide before coding.

Two candidate implementations of "separate lists":
  A. GROUP the existing fused top-5 by source.  Presentation-only, zero retrieval change.
  B. Run each corpus's own RRF and return top-N of EACH.  Retrieval change.

They are not equivalent. §8.2 showed the file answer is often absent from the fused top-5
entirely (Q14 gold sits at fused rank 32). Grouping a list that never contained the answer
cannot surface it. This measures both, so the plan rests on numbers, not on my intuition.

Also answers the orchestrator's hard constraint: the 9 log-gold queries MUST NOT regress.
Trading file recall for log recall is not an improvement, it is moving the problem.
"""
import json, os, sqlite3, struct, sys, statistics as st

ROOT = os.environ.get("ORCHESTRA_ROOT", "/mnt/data/Projects/Python/orchestra")
DB = os.environ["BENCH_DB"]
HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = "/mnt/data/Projects/Python/orchestra"
POOL_MULT = 4
sys.path.insert(0, ROOT)
os.environ.setdefault("FASTEMBED_CACHE_PATH", os.path.join(ROOT, "data", "models"))
import app.rag as rag, sqlite_vec

conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
conn.enable_load_extension(True); sqlite_vec.load(conn); conn.enable_load_extension(False)
conn.row_factory = sqlite3.Row
qs = json.load(open(os.environ.get("QUERIES", os.path.join(HERE, "queries134.json"))))["queries"]
_pack = lambda v: struct.pack(f"{len(v)}f", *v)


def legs(text, pool):
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
        "JOIN files f ON f.file_id=fc.file_id WHERE fts_files MATCH ? AND f.project=? ORDER BY rank LIMIT ?",
        (m, PROJ, pool * 3))][:pool]
    lf = [("log", r["chunk_id"]) for r in conn.execute(
        "SELECT ft.rowid AS chunk_id FROM fts_logs ft JOIN log_chunks lc ON lc.chunk_id=ft.rowid "
        "JOIN logs_indexed li ON li.log_id=lc.log_id WHERE fts_logs MATCH ? AND li.project=? "
        "ORDER BY rank LIMIT ?", (m, PROJ, pool * 3))][:pool]
    return fv, ff, lv, lf


def rr_of(items, gold):
    for p, (k, key) in enumerate(items, 1):
        if key in gold:
            return 1.0 / p
    return 0.0


is_log = lambda c: conn.execute("SELECT 1 FROM log_chunks WHERE chunk_id=?", (c,)).fetchone() is not None

designs = {}
for i, q in enumerate(qs):
    gold = set(q["gold"])
    fv, ff, lv, lf = legs(q["q"], 5 * POOL_MULT)
    fused = rag.RagMemory._rrf(fv, ff, lv, lf)
    files_r = rag.RagMemory._rrf(fv, ff)
    logs_r = rag.RagMemory._rrf(lv, lf)

    # PROD: single fused top-5
    designs.setdefault("prod fused top5", []).append(rr_of(fused[:5], gold))
    # A: group the SAME fused top-5 by source (presentation only)
    top5 = fused[:5]
    grouped = [x for x in top5 if x[0] == "file"] + [x for x in top5 if x[0] == "log"]
    designs.setdefault("A: group fused top5", []).append(rr_of(grouped, gold))
    # B variants: own RRF per corpus, N each. Agent reads both lists, so score over the
    # concatenation files-then-logs (the order the agent actually sees).
    for nf, nl in ((5, 5), (3, 3), (5, 3), (3, 5)):
        designs.setdefault(f"B: files{nf}+logs{nl}", []).append(
            rr_of(files_r[:nf] + logs_r[:nl], gold))

file_qs = [i for i, q in enumerate(qs) if not any(is_log(c) for c in q["gold"])]
log_qs = [i for i, q in enumerate(qs) if any(is_log(c) for c in q["gold"])]

print(f"{'design':<24}{'MRR all':>9}{'file-gold':>11}{'log-gold':>10}{'R@any':>8}{'items':>7}")
for name, vals in designs.items():
    n_items = 5 if name.startswith(("prod", "A")) else int(name.split("files")[1].split("+")[0]) + int(name.split("logs")[1])
    print(f"{name:<24}{st.mean(vals):>9.4f}{st.mean(vals[i] for i in file_qs):>11.4f}"
          f"{st.mean(vals[i] for i in log_qs):>10.4f}"
          f"{sum(1 for v in vals if v > 0)/len(vals):>8.2f}{n_items:>7}")

print("\n=== orchestrator's constraint: log-gold queries must NOT regress vs prod ===")
base_log = st.mean(designs["prod fused top5"][i] for i in log_qs)
for name, vals in designs.items():
    if name == "prod fused top5":
        continue
    m = st.mean(vals[i] for i in log_qs)
    print(f"{name:<24} log-gold {m:.4f} vs prod {base_log:.4f}  "
          f"{'OK' if m >= base_log - 1e-9 else 'REGRESSION'}")
