"""#138 — layer 4: does REWRITING the query help? #135 only ever touched fusion/ranking params.

Runs against the untouched #134 snapshot indexes, so gold is exact chunk_id and the control arm
must reproduce MRR 0.4893 / R@3 0.64 / R@5 0.75 byte-for-byte. If it doesn't, the harness is
broken and no arm result may be read (rag-max personal rule).

Arms:
  prod     original query (control)
  hyde     hand-written hypothetical ANSWER passage in our docs' voice
  keyword  hand-written technical identifiers, symptom words dropped
  q+hyde   original + hyde concatenated (RRF over both, i.e. multi-query)

PASS/FAIL FIXED BEFORE RUNNING: paired |t| > 2.052 AND |dMRR| > 0.1048. Both, or NOT PROVEN.

CEILING CAVEAT: the rewrites are HUMAN and were written knowing the subsystem. That makes every
number here an optimistic upper bound on what an automatic rewriter could do, not a shippable gain.
"""
import json, os, sqlite3, struct, sys, statistics as st

ROOT = os.environ.get("ORCHESTRA_ROOT", "/mnt/data/Projects/Python/orchestra")
DB = os.environ["BENCH_DB"]
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.environ.get("OUT", os.path.join(HERE, "rewrite_results.json"))
PROJ = "/mnt/data/Projects/Python/orchestra"
RRF_K, POOL_MULT, FINAL_K = 60, 4, 5

sys.path.insert(0, ROOT)
os.environ.setdefault("FASTEMBED_CACHE_PATH", os.path.join(ROOT, "data", "models"))
import app.rag as rag
import sqlite_vec

conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
conn.enable_load_extension(True); sqlite_vec.load(conn); conn.enable_load_extension(False)
conn.row_factory = sqlite3.Row

qs = json.load(open(os.path.join(HERE, "..", "..", "134", "bench", "queries.json")))["queries"]
rw = {r["i"]: r for r in json.load(open(os.path.join(HERE, "rewrite_queries.json")))["rewrites"]}


def embed(t):
    return [list(map(float, v)) for v in rag._get_embedder().embed(t)]


def _pack(v):
    return struct.pack(f"{len(v)}f", *v)


def legs(text):
    """The four production legs for one query string."""
    pool = FINAL_K * POOL_MULT
    qv = embed([text])[0]
    fv = [("file", r["chunk_id"]) for r in conn.execute(
        "SELECT chunk_id FROM vec_files WHERE project=? AND embedding MATCH ? ORDER BY distance "
        "LIMIT ?", (PROJ, _pack(qv), pool * 3))][:pool]
    lv = [("log", r["chunk_id"]) for r in conn.execute(
        "SELECT chunk_id FROM vec_logs WHERE project=? AND embedding MATCH ? ORDER BY distance "
        "LIMIT ?", (PROJ, _pack(qv), pool * 3))][:pool]
    m = rag.RagMemory._expand_query(text) or ('"' + text.replace('"', '""') + '"')
    try:
        ff = [("file", r["chunk_id"]) for r in conn.execute(
            "SELECT ft.rowid AS chunk_id FROM fts_files ft JOIN file_chunks fc ON fc.chunk_id=ft.rowid "
            "JOIN files f ON f.file_id=fc.file_id WHERE fts_files MATCH ? AND f.project=? "
            "ORDER BY rank LIMIT ?", (m, PROJ, pool * 3))][:pool]
    except Exception:
        ff = []
    try:
        lf = [("log", r["chunk_id"]) for r in conn.execute(
            "SELECT ft.rowid AS chunk_id FROM fts_logs ft JOIN log_chunks lc ON lc.chunk_id=ft.rowid "
            "JOIN logs_indexed li ON li.log_id=lc.log_id WHERE fts_logs MATCH ? AND li.project=? "
            "ORDER BY rank LIMIT ?", (m, PROJ, pool * 3))][:pool]
    except Exception:
        lf = []
    return [fv, ff, lv, lf]


def score(ranked, gold):
    for pos, (kind, key) in enumerate(ranked[:FINAL_K], start=1):
        if key in gold:
            return 1.0 / pos, pos
    return 0.0, 0


ARMS = ["prod", "hyde", "keyword", "q+hyde"]
res = {a: [] for a in ARMS}
for i, q in enumerate(qs):
    gold = set(q["gold"])
    base = legs(q["q"])
    hy = legs(rw[i]["hyde"])
    kw = legs(rw[i]["keyword"])
    for arm, ranked in (
            ("prod", rag.RagMemory._rrf(*base)),
            ("hyde", rag.RagMemory._rrf(*hy)),
            ("keyword", rag.RagMemory._rrf(*kw)),
            ("q+hyde", rag.RagMemory._rrf(*base, *hy))):
        rr, rank = score(ranked, gold)
        res[arm].append({"i": i, "q": q["q"], "rr": rr, "rank": rank})

print(f"{'arm':<10}{'MRR':>9}{'R@3':>7}{'R@5':>7}")
summ = {}
for a in ARMS:
    d = res[a]
    summ[a] = {"MRR": st.mean(x["rr"] for x in d),
               "R@3": sum(1 for x in d if 0 < x["rank"] <= 3) / len(d),
               "R@5": sum(1 for x in d if x["rank"] > 0) / len(d)}
    print(f"{a:<10}{summ[a]['MRR']:>9.4f}{summ[a]['R@3']:>7.2f}{summ[a]['R@5']:>7.2f}")

ctl = summ["prod"]
ok = abs(ctl["MRR"] - 0.4893) < 0.0005 and abs(ctl["R@3"] - 0.64) < 0.01 and abs(ctl["R@5"] - 0.75) < 0.01
print(f"\nCONTROL reproduces #134 baseline (0.4893/0.64/0.75): {'YES' if ok else 'NO -- HARNESS BROKEN'}")
if not ok:
    print("Per rag-max rule: fix the harness, do not interpret arm results.")

base = [x["rr"] for x in res["prod"]]
print(f"\n{'arm':<10}{'dMRR':>10}{'t':>8}   verdict (need |t|>2.052 AND |d|>0.1048)")
for a in ARMS[1:]:
    cur = [x["rr"] for x in res[a]]
    d = [x - y for x, y in zip(cur, base)]
    m = st.mean(d)
    se = st.stdev(d) / len(d) ** 0.5 if st.stdev(d) else 0
    t = m / se if se else 0.0
    print(f"{a:<10}{m:>+10.4f}{t:>8.2f}   "
          f"{'PROVEN' if abs(t) > 2.052 and abs(m) > 0.1048 else 'NOT PROVEN'}")

# per-label breakdown: does rewriting help the fixed_state group specifically?
labels = {x["i"]: x["label"] for x in json.load(open(os.path.join(HERE, "labels.json")))["labels"]}
print(f"\n{'label':<15}{'n':>3}" + "".join(f"{a:>10}" for a in ARMS))
for g in sorted(set(labels.values())):
    idx = [i for i in labels if labels[i] == g]
    line = f"{g:<15}{len(idx):>3}"
    for a in ARMS:
        line += f"{st.mean(res[a][i]['rr'] for i in idx):>10.4f}"
    print(line)

json.dump({"summary": summ, "detail": res}, open(OUT, "w"), ensure_ascii=False, indent=1)
print(f"\nwrote {OUT}")
