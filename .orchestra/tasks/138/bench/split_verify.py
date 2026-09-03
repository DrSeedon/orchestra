"""#138 — is the 'within' scoring legitimate, or did I pick the metric that flatters my design?

Fair objection: I measured three scorings and reported the best one. That is exactly the
goalpost-moving the method forbids. So here the claim is tested on a metric that CANNOT be
accused of favouring the split, and on the only question that matters operationally:

  Does the answer appear ANYWHERE the agent will see it, and at what cost in items read?

Prod shows 5 chunks. The split shows nf+nl chunks. If the split needs 10 chunks to beat a
5-chunk baseline, it wins on recall by spending context - that must be stated, not hidden.
So: hold the BUDGET equal. Compare prod top-5 against split designs whose two lists sum to 5.

Metric: R@budget - is gold among the items shown at all (rank-free, no scoring choice), plus
'first-hit position within its own list' for latency-of-reading. Both computed for every arm.
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

def legs(text,pool):
    qv=[list(map(float,v)) for v in rag._get_embedder().embed([text])][0]
    fv=[("file",r["chunk_id"]) for r in conn.execute("SELECT chunk_id FROM vec_files WHERE project=? AND embedding MATCH ? ORDER BY distance LIMIT ?",(PROJ,_pack(qv),pool*3))][:pool]
    lv=[("log",r["chunk_id"]) for r in conn.execute("SELECT chunk_id FROM vec_logs WHERE project=? AND embedding MATCH ? ORDER BY distance LIMIT ?",(PROJ,_pack(qv),pool*3))][:pool]
    m=rag.RagMemory._expand_query(text) or ('"'+text.replace('"','""')+'"')
    ff=[("file",r["chunk_id"]) for r in conn.execute("SELECT ft.rowid AS chunk_id FROM fts_files ft JOIN file_chunks fc ON fc.chunk_id=ft.rowid JOIN files f ON f.file_id=fc.file_id WHERE fts_files MATCH ? AND f.project=? ORDER BY rank LIMIT ?",(m,PROJ,pool*3))][:pool]
    lf=[("log",r["chunk_id"]) for r in conn.execute("SELECT ft.rowid AS chunk_id FROM fts_logs ft JOIN log_chunks lc ON lc.chunk_id=ft.rowid JOIN logs_indexed li ON li.log_id=lc.log_id WHERE fts_logs MATCH ? AND li.project=? ORDER BY rank LIMIT ?",(m,PROJ,pool*3))][:pool]
    return fv,ff,lv,lf

is_log=lambda c: conn.execute("SELECT 1 FROM log_chunks WHERE chunk_id=?",(c,)).fetchone() is not None
hit=lambda items,gold: any(k in gold for _,k in items)

ARMS={"prod fused top5":None,"split 3+2":(3,2),"split 2+3":(2,3),"split 4+1":(4,1),"split 5+5":(5,5)}
res={a:[] for a in ARMS}; pos={a:[] for a in ARMS}
for i,q in enumerate(qs):
    gold=set(q["gold"]); fv,ff,lv,lf=legs(q["q"],5*POOL_MULT)
    fused=rag.RagMemory._rrf(fv,ff,lv,lf); F=rag.RagMemory._rrf(fv,ff); L=rag.RagMemory._rrf(lv,lf)
    for a,cfg in ARMS.items():
        if cfg is None:
            shown=fused[:5]
            p=next((j for j,(k,key) in enumerate(shown,1) if key in gold), None)
        else:
            nf,nl=cfg; shown=F[:nf]+L[:nl]
            pf=next((j for j,(k,key) in enumerate(F[:nf],1) if key in gold), None)
            pl=next((j for j,(k,key) in enumerate(L[:nl],1) if key in gold), None)
            p=min([x for x in (pf,pl) if x] or [None]) if (pf or pl) else None
        res[a].append(1 if hit(shown,gold) else 0)
        pos[a].append(p)

file_qs=[i for i,q in enumerate(qs) if not any(is_log(c) for c in q["gold"])]
log_qs=[i for i,q in enumerate(qs) if any(is_log(c) for c in q["gold"])]
print(f"{'arm':<18}{'budget':>7}{'R@budget':>10}{'file-gold':>11}{'log-gold':>10}{'med.pos':>9}")
for a in ARMS:
    b=5 if ARMS[a] is None else sum(ARMS[a])
    ps=[p for p in pos[a] if p]
    print(f"{a:<18}{b:>7}{st.mean(res[a]):>10.2f}"
          f"{st.mean(res[a][i] for i in file_qs):>11.2f}{st.mean(res[a][i] for i in log_qs):>10.2f}"
          f"{st.median(ps) if ps else float('nan'):>9.1f}")

print("\n=== EQUAL BUDGET (5 items): does any query LOSE its answer vs prod? ===")
for a in ARMS:
    if ARMS[a] is None or sum(ARMS[a])!=5: continue
    lost=[i for i in range(len(qs)) if res["prod fused top5"][i] and not res[a][i]]
    won=[i for i in range(len(qs)) if not res["prod fused top5"][i] and res[a][i]]
    print(f"{a:<12} lost={lost}  won={won}")
