"""Follow-up: the vec arm showed p=0.027. Real signal, or multiplicity + confound?"""
import json, os, random, statistics as st, sqlite3
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
detail = json.load(open(os.path.join(HERE,"..","..","134","bench","retrieval_results.json")))["detail"]
labels = {x["i"]: x["label"] for x in json.load(open(os.path.join(HERE,"labels.json")))["labels"]}
ARMS = ["vec","fts","hybrid","hybrid_rr_api"]
rows=[{"i":i,"label":labels[i],**{a:d[a]["rr"] for a in ARMS}} for i,d in enumerate(detail)]
groups=sorted({r["label"] for r in rows})

print("=== ORCHESTRATOR'S ACTUAL QUESTION: symptom_first vs fixed_state ===")
random.seed(2138)
for arm in ARMS:
    A=[r[arm] for r in rows if r["label"]=="symptom_first"]
    B=[r[arm] for r in rows if r["label"]=="fixed_state"]
    obs=st.mean(A)-st.mean(B)
    pool=A+B; nA=len(A); cnt=0; N=20000
    for _ in range(N):
        random.shuffle(pool)
        if (st.mean(pool[:nA])-st.mean(pool[nA:])) >= obs: cnt+=1
    print(f"{arm:<16} symptom={st.mean(A):.4f} fixed={st.mean(B):.4f} delta={obs:+.4f} "
          f"one-sided p={cnt/N:.4f}  (nA={nA}, nB={len(B)})")

print("\n4 arms tested -> Bonferroni-corrected alpha for 0.05 is 0.0125")

print("\n=== leave-one-out fragility of the vec-arm contrast ===")
A=[(r['i'],r['vec']) for r in rows if r["label"]=="symptom_first"]
B=[(r['i'],r['vec']) for r in rows if r["label"]=="fixed_state"]
base=st.mean(v for _,v in A)-st.mean(v for _,v in B)
print(f"full delta={base:+.4f}")
worst=[]
for drop_i,_ in A+B:
    a=[v for i,v in A if i!=drop_i]; b=[v for i,v in B if i!=drop_i]
    worst.append((st.mean(a)-st.mean(b), drop_i))
worst.sort()
for d,i in worst[:4]: print(f"  drop Q{i}: delta={d:+.4f}")
print(f"  ... max delta={worst[-1][0]:+.4f} (drop Q{worst[-1][1]})")

DB="/mnt/data/Projects/Python/orchestra/data/bench134/vec134.db"
conn=sqlite3.connect(f"file:{DB}?mode=ro",uri=True)
qs=json.load(open(os.path.join(HERE,"..","..","134","bench","queries.json")))["queries"]
print("\n=== CONFOUND: gold source (file vs log) by label ===")
for g in groups:
    srcs=[]
    for r in rows:
        if r["label"]!=g: continue
        for cid in qs[r["i"]]["gold"]:
            f=conn.execute("SELECT 1 FROM file_chunks WHERE chunk_id=?", (cid,)).fetchone()
            srcs.append("file" if f else "log")
    print(f"{g:<15} {dict(Counter(srcs))}")

print("\n=== CONFOUND: gold chunk length (chars) by label ===")
for g in groups:
    lens=[]
    for r in rows:
        if r["label"]!=g: continue
        for cid in qs[r["i"]]["gold"]:
            t=conn.execute("SELECT text FROM file_chunks WHERE chunk_id=?", (cid,)).fetchone()
            if not t: t=conn.execute("SELECT text FROM log_chunks WHERE chunk_id=?", (cid,)).fetchone()
            if t: lens.append(len(t[0]))
    print(f"{g:<15} n={len(lens)} median={st.median(lens):.0f} mean={st.mean(lens):.0f}")

print("\n=== CONFOUND: does query LENGTH / wording differ by label? ===")
for g in groups:
    L=[len(qs[r["i"]]["q"]) for r in rows if r["label"]==g]
    print(f"{g:<15} n={len(L)} median_query_chars={st.median(L):.0f}")
