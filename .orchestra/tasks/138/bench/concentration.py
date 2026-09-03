"""#138 follow-up: P1 held in only 8/19. So is the §8 gain BROAD or CONCENTRATED?

If the whole 0.5088 -> 0.6289 move comes from the 8 queries where logs actually sit above gold,
then the honest claim is not "logs hurt file queries" but "logs hurt the SUBSET of file queries
they outrank, and are inert elsewhere" - which is a different, narrower, and more defensible fix.
"""
import json, os, sqlite3, struct, sys, statistics as st

ROOT = os.environ.get("ORCHESTRA_ROOT", "/mnt/data/Projects/Python/orchestra")
DB = os.environ["BENCH_DB"]
HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = "/mnt/data/Projects/Python/orchestra"
FINAL_K, POOL_MULT = 5, 4
sys.path.insert(0, ROOT)
os.environ.setdefault("FASTEMBED_CACHE_PATH", os.path.join(ROOT, "data", "models"))
import app.rag as rag, sqlite_vec
conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
conn.enable_load_extension(True); sqlite_vec.load(conn); conn.enable_load_extension(False)
conn.row_factory = sqlite3.Row
qs = json.load(open(os.environ.get("QUERIES", os.path.join(HERE, "queries134.json"))))["queries"]
_pack = lambda v: struct.pack(f"{len(v)}f", *v)

def legs(text):
    pool = FINAL_K * POOL_MULT
    qv = [list(map(float, v)) for v in rag._get_embedder().embed([text])][0]
    fv=[("file",r["chunk_id"]) for r in conn.execute("SELECT chunk_id FROM vec_files WHERE project=? AND embedding MATCH ? ORDER BY distance LIMIT ?",(PROJ,_pack(qv),pool*3))][:pool]
    lv=[("log",r["chunk_id"]) for r in conn.execute("SELECT chunk_id FROM vec_logs WHERE project=? AND embedding MATCH ? ORDER BY distance LIMIT ?",(PROJ,_pack(qv),pool*3))][:pool]
    m=rag.RagMemory._expand_query(text) or ('"'+text.replace('"','""')+'"')
    ff=[("file",r["chunk_id"]) for r in conn.execute("SELECT ft.rowid AS chunk_id FROM fts_files ft JOIN file_chunks fc ON fc.chunk_id=ft.rowid JOIN files f ON f.file_id=fc.file_id WHERE fts_files MATCH ? AND f.project=? ORDER BY rank LIMIT ?",(m,PROJ,pool*3))][:pool]
    lf=[("log",r["chunk_id"]) for r in conn.execute("SELECT ft.rowid AS chunk_id FROM fts_logs ft JOIN log_chunks lc ON lc.chunk_id=ft.rowid JOIN logs_indexed li ON li.log_id=lc.log_id WHERE fts_logs MATCH ? AND li.project=? ORDER BY rank LIMIT ?",(m,PROJ,pool*3))][:pool]
    return fv,ff,lv,lf

def rr(ranked,gold):
    for p,(k,key) in enumerate(ranked[:FINAL_K],1):
        if key in gold: return 1.0/p
    return 0.0

is_log=lambda c: conn.execute("SELECT 1 FROM log_chunks WHERE chunk_id=?",(c,)).fetchone() is not None
file_qs=[i for i,q in enumerate(qs) if not any(is_log(c) for c in q["gold"])]

affected, inert = [], []
for i in file_qs:
    gold=set(qs[i]["gold"]); fv,ff,lv,lf=legs(qs[i]["q"])
    full=rag.RagMemory._rrf(fv,ff,lv,lf); fo=rag.RagMemory._rrf(fv,ff)
    pf=next((p for p,(k,key) in enumerate(full,1) if key in gold), None)
    logs_above = sum(1 for k,_ in full[:(pf-1)] if k=="log") if pf else 0
    rec=(i, rr(full,gold), rr(fo,gold))
    (affected if logs_above>0 else inert).append(rec)

for name,grp in (("logs ABOVE gold (P1 true)",affected),("logs inert (P1 false)",inert)):
    if not grp: continue
    f=st.mean(x[1] for x in grp); o=st.mean(x[2] for x in grp)
    print(f"{name:<28} n={len(grp):<3} prod={f:.4f}  files-only={o:.4f}  delta={o-f:+.4f}")
allf=st.mean(x[1] for x in affected+inert); allo=st.mean(x[2] for x in affected+inert)
print(f"{'ALL file-gold queries':<28} n={len(file_qs):<3} prod={allf:.4f}  files-only={allo:.4f}  delta={allo-allf:+.4f}")
tot=(allo-allf)*len(file_qs)
part=(st.mean(x[2] for x in affected)-st.mean(x[1] for x in affected))*len(affected)
print(f"\nshare of the total gain contributed by the {len(affected)} affected queries: {part/tot:.1%}")
