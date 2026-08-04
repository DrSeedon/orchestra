"""#138 — logs take 49.3% of top-5 slots. Are they ANSWERS or CONVERSATION ABOUT the answer?

Motivating observation (distractors.log): for Q20 the whole top-4 is orchestrator messages
that ASSIGN or DISCUSS the merge investigation, while the document holding the finding is absent.
A task assignment restates the question in the question's own words, so it is a near-perfect
lexical+semantic match for the query while containing NO answer. That is a structural trap
that no fusion weight can see.

Arm: drop the log legs entirely (files only), same everything else. If MRR does not fall,
logs are contributing noise, not answers, for this query style.
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
labels = {x["i"]: x["label"] for x in json.load(open(os.path.join(HERE, "labels.json")))["labels"]}
_pack = lambda v: struct.pack(f"{len(v)}f", *v)


def all_legs(text):
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
        "JOIN files f ON f.file_id=fc.file_id WHERE fts_files MATCH ? AND f.project=? ORDER BY rank LIMIT ?",
        (m, PROJ, pool * 3))][:pool]
    lf = [("log", r["chunk_id"]) for r in conn.execute(
        "SELECT ft.rowid AS chunk_id FROM fts_logs ft JOIN log_chunks lc ON lc.chunk_id=ft.rowid "
        "JOIN logs_indexed li ON li.log_id=lc.log_id WHERE fts_logs MATCH ? AND li.project=? "
        "ORDER BY rank LIMIT ?", (m, PROJ, pool * 3))][:pool]
    return fv, ff, lv, lf


def score(ranked, gold):
    for pos, (k, key) in enumerate(ranked[:FINAL_K], 1):
        if key in gold:
            return 1.0 / pos
    return 0.0


arms = {"prod (4 legs)": lambda l: rag.RagMemory._rrf(*l),
        "files only": lambda l: rag.RagMemory._rrf(l[0], l[1]),
        "logs only": lambda l: rag.RagMemory._rrf(l[2], l[3])}
res = {a: [] for a in arms}
gold_in_log = 0
for i, q in enumerate(qs):
    gold = set(q["gold"])
    is_log = any(conn.execute("SELECT 1 FROM log_chunks WHERE chunk_id=?", (c,)).fetchone() for c in gold)
    gold_in_log += bool(is_log)
    legs = all_legs(q["q"])
    for a, f in arms.items():
        res[a].append(score(f(legs), gold))

print(f"queries whose gold is (at least partly) a LOG chunk: {gold_in_log}/{len(qs)}\n")
print(f"{'arm':<16}{'MRR':>9}{'R@5':>7}")
for a in arms:
    print(f"{a:<16}{st.mean(res[a]):>9.4f}{sum(1 for x in res[a] if x>0)/len(res[a]):>7.2f}")

base = res["prod (4 legs)"]
print(f"\n{'arm':<16}{'dMRR':>10}{'t':>8}   verdict (|t|>2.052 AND |d|>0.1048)")
for a in arms:
    if a == "prod (4 legs)":
        continue
    d = [x - y for x, y in zip(res[a], base)]
    m = st.mean(d); s = st.stdev(d)/len(d)**0.5 if st.stdev(d) else 0
    t = m/s if s else 0.0
    print(f"{a:<16}{m:>+10.4f}{t:>8.2f}   {'PROVEN' if abs(t)>2.052 and abs(m)>0.1048 else 'NOT PROVEN'}")

# split by whether the gold itself lives in a log
print(f"\n{'subset':<26}{'n':>3}" + "".join(f"{a:>16}" for a in arms))
for name, want in (("gold IS a log chunk", True), ("gold is a FILE chunk", False)):
    idx = []
    for i, q in enumerate(qs):
        is_log = any(conn.execute("SELECT 1 FROM log_chunks WHERE chunk_id=?", (c,)).fetchone()
                     for c in q["gold"])
        if is_log == want:
            idx.append(i)
    line = f"{name:<26}{len(idx):>3}"
    for a in arms:
        line += f"{st.mean(res[a][i] for i in idx):>16.4f}"
    print(line)
