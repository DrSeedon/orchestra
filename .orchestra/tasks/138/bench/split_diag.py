"""#138 — WHY does every split design regress log-gold queries? Artifact or real?

Suspicion: I scored the split as a CONCATENATION files-then-logs, so a log answer that was
rank 1 in the log list is scored as rank nf+1. That penalises logs by construction - it
assumes the agent reads strictly top-down and stops. That is a scoring choice, not a property
of the design, and it must be separated from any real regression.

Three scorings of the SAME split output:
  concat      files-then-logs (what split_design.py did)  - pessimistic for logs
  best-of     credit the better rank across the two lists - optimistic, assumes agent reads both
  within     rank inside the list where gold actually is  - measures each list's own quality
If 'within' shows no regression, the split is fine and only my presentation metric was wrong.
"""
import json, os, sqlite3, struct, sys, statistics as st

ROOT = os.environ.get("ORCHESTRA_ROOT", "/mnt/data/Projects/Python/orchestra")
DB = os.environ["BENCH_DB"]; HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = "/mnt/data/Projects/Python/orchestra"; POOL_MULT = 4
sys.path.insert(0, ROOT)
os.environ.setdefault("FASTEMBED_CACHE_PATH", os.path.join(ROOT, "data", "models"))
import app.rag as rag, sqlite_vec
conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
conn.enable_load_extension(True); sqlite_vec.load(conn); conn.enable_load_extension(False)
conn.row_factory = sqlite3.Row
qs = json.load(open(os.environ.get("QUERIES", os.path.join(HERE, "queries134.json"))))["queries"]
_pack = lambda v: struct.pack(f"{len(v)}f", *v)

def legs(text, pool):
    qv=[list(map(float,v)) for v in rag._get_embedder().embed([text])][0]
    fv=[("file",r["chunk_id"]) for r in conn.execute("SELECT chunk_id FROM vec_files WHERE project=? AND embedding MATCH ? ORDER BY distance LIMIT ?",(PROJ,_pack(qv),pool*3))][:pool]
    lv=[("log",r["chunk_id"]) for r in conn.execute("SELECT chunk_id FROM vec_logs WHERE project=? AND embedding MATCH ? ORDER BY distance LIMIT ?",(PROJ,_pack(qv),pool*3))][:pool]
    m=rag.RagMemory._expand_query(text) or ('"'+text.replace('"','""')+'"')
    ff=[("file",r["chunk_id"]) for r in conn.execute("SELECT ft.rowid AS chunk_id FROM fts_files ft JOIN file_chunks fc ON fc.chunk_id=ft.rowid JOIN files f ON f.file_id=fc.file_id WHERE fts_files MATCH ? AND f.project=? ORDER BY rank LIMIT ?",(m,PROJ,pool*3))][:pool]
    lf=[("log",r["chunk_id"]) for r in conn.execute("SELECT ft.rowid AS chunk_id FROM fts_logs ft JOIN log_chunks lc ON lc.chunk_id=ft.rowid JOIN logs_indexed li ON li.log_id=lc.log_id WHERE fts_logs MATCH ? AND li.project=? ORDER BY rank LIMIT ?",(m,PROJ,pool*3))][:pool]
    return fv,ff,lv,lf

def rr(items,gold):
    for p,(k,key) in enumerate(items,1):
        if key in gold: return 1.0/p
    return 0.0

is_log=lambda c: conn.execute("SELECT 1 FROM log_chunks WHERE chunk_id=?",(c,)).fetchone() is not None
rows={}
for i,q in enumerate(qs):
    gold=set(q["gold"]); fv,ff,lv,lf=legs(q["q"],5*POOL_MULT)
    fused=rag.RagMemory._rrf(fv,ff,lv,lf)[:5]
    F=rag.RagMemory._rrf(fv,ff)[:5]; L=rag.RagMemory._rrf(lv,lf)[:5]
    rows[i]={"prod":rr(fused,gold),"concat":rr(F+L,gold),
             "best":max(rr(F,gold),rr(L,gold)),
             "within":rr(F,gold) if not any(is_log(c) for c in gold) else rr(L,gold)}

file_qs=[i for i,q in enumerate(qs) if not any(is_log(c) for c in q["gold"])]
log_qs=[i for i,q in enumerate(qs) if any(is_log(c) for c in q["gold"])]
print(f"{'scoring':<10}{'all':>9}{'file-gold':>11}{'log-gold':>10}")
for k in ("prod","concat","best","within"):
    print(f"{k:<10}{st.mean(rows[i][k] for i in rows):>9.4f}"
          f"{st.mean(rows[i][k] for i in file_qs):>11.4f}{st.mean(rows[i][k] for i in log_qs):>10.4f}")

print("\n=== per-query, log-gold subset: where does gold sit in the LOG list? ===")
for i in log_qs:
    print(f"  Q{i:<3} prod={rows[i]['prod']:.3f} within_log_list={rows[i]['within']:.3f}  {qs[i]['q'][:50]}")
