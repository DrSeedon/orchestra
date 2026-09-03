"""#138 — MECHANISM check, not effect size. Answers the orchestrator's gate question.

The §8 conclusion rests on n=19 / n=9 means, and the bench resolves ~0.10 MRR. So instead of
asking "how big is the effect", ask "does the predicted CAUSAL CHAIN actually occur, and is it
what produces the observed move?" That is a count of events, not a difference of means, so it
does not depend on sample size.

§8.1 predicts, for a query whose gold is a FILE chunk:
  P1. log chunks physically occupy slots ABOVE the gold's file position;
  P2. removing exactly those log chunks is what promotes gold (not some other reshuffle);
  P3. the displacing logs are disproportionately ASSIGNMENT/DISCUSSION text - they restate the
      question without containing the answer.

Each prediction is falsifiable on its own:
  P1 false -> logs are not in the way at all; the §8 gain came from somewhere else.
  P2 false -> gold rises for an unrelated reason; the mechanism story is wrong.
  P3 false -> logs do displace, but not because they echo the question; §8.1's WHY is wrong
              even if §8's WHAT holds.
"""
import json, os, re, sqlite3, struct, sys, collections, statistics as st

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

ASSIGN = re.compile(
    r"НОВАЯ ЗАДАЧА|ЧТО НУЖНО|ЗАДАЧА:|ЧТО ВЫЯСНИТЬ|Research:|исследуй|выясни|проверь|"
    r"ФАЗА \d|Awaiting approval|\[from:", re.I)


def legs(text):
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


def is_log(cid):
    return conn.execute("SELECT 1 FROM log_chunks WHERE chunk_id=?", (cid,)).fetchone() is not None


def log_text(cid):
    r = conn.execute("SELECT text, kind FROM log_chunks WHERE chunk_id=?", (cid,)).fetchone()
    return (r["text"] or "", r["kind"]) if r else ("", "?")


# baseline rate of assignment-like text among ALL indexed log chunks (the null for P3)
allrows = conn.execute("SELECT lc.text FROM log_chunks lc JOIN logs_indexed li ON li.log_id=lc.log_id "
                       "WHERE li.project=?", (PROJ,)).fetchall()
base_rate = sum(1 for r in allrows if ASSIGN.search(r["text"] or "")) / len(allrows)

file_gold_qs = [i for i, q in enumerate(qs) if not any(is_log(c) for c in q["gold"])]
print(f"queries whose gold is a FILE chunk: {len(file_gold_qs)}")
print(f"baseline assignment-marker rate over all {len(allrows)} log chunks: {base_rate:.1%}\n")

p1_hits = p1_total = 0
displacers = []
promoted = same = 0
rows_out = []
for i in file_gold_qs:
    gold = set(qs[i]["gold"])
    fv, ff, lv, lf = legs(qs[i]["q"])
    full = rag.RagMemory._rrf(fv, ff, lv, lf)
    filesonly = rag.RagMemory._rrf(fv, ff)

    def pos(ranked):
        for p, (k, key) in enumerate(ranked, 1):
            if key in gold:
                return p
        return None

    pf, pfo = pos(full), pos(filesonly)
    # P1: how many LOG chunks sit above gold in the fused list?
    above_logs = []
    if pf:
        for k, key in full[:pf - 1]:
            if k == "log":
                above_logs.append(key)
    p1_total += 1
    if above_logs:
        p1_hits += 1
    displacers.extend(above_logs)
    # P2: does gold actually rise when logs are gone?
    if pf and pfo and pfo < pf:
        promoted += 1
    elif pf and pfo and pfo == pf:
        same += 1
    rows_out.append((i, pf, pfo, len(above_logs), qs[i]["q"][:44]))

print("=== P1/P2 per query (gold in a FILE) ===")
print(f"{'Q':<4}{'rank_full':>10}{'rank_filesonly':>16}{'logs_above':>12}  query")
for i, pf, pfo, na, q in rows_out:
    print(f"{i:<4}{str(pf):>10}{str(pfo):>16}{na:>12}  {q}")

print(f"\nP1: queries where >=1 LOG sits above gold: {p1_hits}/{p1_total}")
print(f"P2: gold's rank improves when log legs removed: {promoted}/{p1_total} "
      f"(unchanged {same})")

# P3: are the displacing logs disproportionately assignment/discussion text?
uniq = list(dict.fromkeys(displacers))
n_assign = 0
kinds = collections.Counter()
print(f"\n=== P3: the {len(uniq)} distinct log chunks that outrank a file gold ===")
for cid in uniq:
    t, k = log_text(cid)
    kinds[k] += 1
    a = bool(ASSIGN.search(t))
    n_assign += a
    print(f"  [{'ASSIGN' if a else '      '}] {k:<10} {t[:88].strip()}")
rate = n_assign / len(uniq) if uniq else 0
print(f"\nP3: assignment-marker rate among displacers: {n_assign}/{len(uniq)} = {rate:.1%}")
print(f"    baseline over whole log corpus:          {base_rate:.1%}")
print(f"    kinds of displacers: {dict(kinds)}")

# binomial tail: could this rate arise by chance from the baseline?
from math import comb
n, kk = len(uniq), n_assign
p_val = sum(comb(n, j) * base_rate**j * (1-base_rate)**(n-j) for j in range(kk, n+1)) if n else 1
print(f"    one-sided binomial p (>= {kk} of {n} at baseline {base_rate:.3f}): {p_val:.4f}")

print("\n=== VERDICT ===")
print(f"P1 {'HOLDS' if p1_hits/max(p1_total,1) > 0.5 else 'FAILS'}: "
      f"logs physically occupy slots above the file gold in {p1_hits}/{p1_total} queries")
print(f"P2 {'HOLDS' if promoted > 0 else 'FAILS'}: removing logs promotes gold in {promoted}/{p1_total}")
print(f"P3 {'HOLDS' if rate > base_rate and p_val < 0.05 else 'NOT ESTABLISHED'}: "
      f"displacers are {rate:.1%} assignment-like vs {base_rate:.1%} baseline (p={p_val:.4f})")
