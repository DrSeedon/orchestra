"""#138 — the split wins only at budget 10. Is that a fair trade, or is prod just as good at 10?

If prod-fused ALSO reaches 0.82 when you let it show 10 chunks, the split buys nothing and the
whole recommendation collapses to "show more chunks". That is the control I owe before proposing
any change. Compare like-for-like at every budget.
"""
import json, os, sqlite3, struct, sys, statistics as st
ROOT=os.environ.get("ORCHESTRA_ROOT","/mnt/data/Projects/Python/orchestra"); DB=os.environ["BENCH_DB"]
HERE=os.path.dirname(os.path.abspath(__file__)); PROJ="/mnt/data/Projects/Python/orchestra"
sys.path.insert(0,ROOT); os.environ.setdefault("FASTEMBED_CACHE_PATH",os.path.join(ROOT,"data","models"))
import app.rag as rag, sqlite_vec
conn=sqlite3.connect(f"file:{DB}?mode=ro",uri=True)
conn.enable_load_extension(True); sqlite_vec.load(conn); conn.enable_load_extension(False)
conn.row_factory=sqlite3.Row
qs=json.load(open(os.environ.get("QUERIES",os.path.join(HERE,"queries134.json"))))["queries"]
_pack=lambda v: struct.pack(f"{len(v)}f",*v)
def legs(text,pool):
    qv=[list(map(float,v)) for v in rag._get_embedder().embed([text])][0]
    fv=[("file",r["chunk_id"]) for r in conn.execute("SELECT chunk_id FROM vec_files WHERE project=? AND embedding MATCH ? ORDER BY distance LIMIT ?",(PROJ,_pack(qv),pool*3))][:pool]
    lv=[("log",r["chunk_id"]) for r in conn.execute("SELECT chunk_id FROM vec_logs WHERE project=? AND embedding MATCH ? ORDER BY distance LIMIT ?",(PROJ,_pack(qv),pool*3))][:pool]
    m=rag.RagMemory._expand_query(text) or ('"'+text.replace('"','""')+'"')
    ff=[("file",r["chunk_id"]) for r in conn.execute("SELECT ft.rowid AS chunk_id FROM fts_files ft JOIN file_chunks fc ON fc.chunk_id=ft.rowid JOIN files f ON f.file_id=fc.file_id WHERE fts_files MATCH ? AND f.project=? ORDER BY rank LIMIT ?",(m,PROJ,pool*3))][:pool]
    lf=[("log",r["chunk_id"]) for r in conn.execute("SELECT ft.rowid AS chunk_id FROM fts_logs ft JOIN log_chunks lc ON lc.chunk_id=ft.rowid JOIN logs_indexed li ON li.log_id=lc.log_id WHERE fts_logs MATCH ? AND li.project=? ORDER BY rank LIMIT ?",(m,PROJ,pool*3))][:pool]
    return fv,ff,lv,lf
is_log=lambda c: conn.execute("SELECT 1 FROM log_chunks WHERE chunk_id=?",(c,)).fetchone() is not None
data=[]
for i,q in enumerate(qs):
    gold=set(q["gold"]); fv,ff,lv,lf=legs(q["q"],40)
    data.append((gold,rag.RagMemory._rrf(fv,ff,lv,lf),rag.RagMemory._rrf(fv,ff),rag.RagMemory._rrf(lv,lf),
                 any(is_log(c) for c in gold)))
print(f"{'budget':>7}{'prod fused':>12}{'split n/2+n/2':>15}{'prod MRR':>10}{'split MRR':>11}")
for b in (5,6,8,10,12):
    pf=[]; sp=[]; pm=[]; sm=[]
    for gold,fused,F,L,_ in data:
        sh=fused[:b]; pf.append(any(k in gold for _,k in sh))
        pm.append(next((1/j for j,(k,key) in enumerate(sh,1) if key in gold),0.0))
        nf=b//2; nl=b-nf; s=F[:nf]+L[:nl]; sp.append(any(k in gold for _,k in s))
        rf=next((1/j for j,(k,key) in enumerate(F[:nf],1) if key in gold),0.0)
        rl=next((1/j for j,(k,key) in enumerate(L[:nl],1) if key in gold),0.0)
        sm.append(max(rf,rl))
    print(f"{b:>7}{st.mean(pf):>12.2f}{st.mean(sp):>15.2f}{st.mean(pm):>10.4f}{st.mean(sm):>11.4f}")
