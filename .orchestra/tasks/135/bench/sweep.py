"""#135 — zero-cost retrieval sweep. No external APIs, read-only snapshot.

Arms (all end at top-5, same as production):
  prod        — POOL_MULT=4 (pool=20), RRF_K=60, 4 legs summed          [baseline]
  pool_N      — POOL_MULT sweep, everything else identical
  rrfk_N      — RRF_K sweep at production pool
  norm        — per-modality max: fuse (vec_file,fts_file) and (vec_log,fts_log)
                separately, then combine — removes the "breadth beats depth" bias
                caused by a chunk being structurally visible to at most 2 of 4 legs
  pool+norm   — the two best-performing knobs together

Metric: R@3 / R@5 / MRR, paired t vs prod on per-query RR. Threshold 2.052 (df=27).
"""
import json
import math
import os
import re
import sqlite3
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.environ.get("BENCH_DB")
PROJECT = os.environ.get("BENCH_PROJECT", "/mnt/data/Projects/Python/orchestra")
FINAL_K = 5
DEEP = 400  # deep enough to cover every pool setting we sweep

_embedder = None


def _get_embedder():
    global _embedder
    if _embedder is None:
        root = os.environ.get("ORCHESTRA_ROOT", "/mnt/data/Projects/Python/orchestra")
        sys.path.insert(0, root)
        os.environ.setdefault("FASTEMBED_CACHE_PATH", os.path.join(root, "data", "models"))
        from app.rag import _get_embedder as prod_embedder
        _embedder = prod_embedder()
    return _embedder


def embed(texts):
    return [list(map(float, v)) for v in _get_embedder().embed(texts)]


def _pack(vec):
    return struct.pack(f"{len(vec)}f", *vec)


def _expand_query(query):
    words = [w for w in re.findall(r"\w+", query) if len(w) >= 3]
    return " OR ".join(f'"{w}"*' for w in words) if words else None


def deep_legs(conn, query, qvec, depth=DEEP):
    """The four production legs, retrieved deep once and sliced per-arm afterwards."""
    legs = {}
    for table, tag in (("vec_files", "file"), ("vec_logs", "log")):
        rows = conn.execute(
            f"SELECT chunk_id FROM {table} WHERE project=? AND embedding MATCH ? "
            f"ORDER BY distance LIMIT ?", (PROJECT, _pack(qvec), depth)).fetchall()
        legs[f"vec_{tag}"] = [(tag, r["chunk_id"]) for r in rows]
    match = _expand_query(query) or ('"' + query.replace('"', '""') + '"')
    f_sql = ("SELECT ft.rowid AS chunk_id FROM fts_files ft "
             "JOIN file_chunks fc ON fc.chunk_id=ft.rowid "
             "JOIN files f ON f.file_id=fc.file_id "
             "WHERE fts_files MATCH ? AND f.project=? ORDER BY rank LIMIT ?")
    l_sql = ("SELECT ft.rowid AS chunk_id FROM fts_logs ft "
             "JOIN log_chunks lc ON lc.chunk_id=ft.rowid "
             "JOIN logs_indexed li ON li.log_id=lc.log_id "
             "WHERE fts_logs MATCH ? AND li.project=? ORDER BY rank LIMIT ?")
    for sql, tag in ((f_sql, "file"), (l_sql, "log")):
        try:
            rows = conn.execute(sql, (match, PROJECT, depth)).fetchall()
        except Exception:
            safe = '"' + query.replace('"', '""') + '"'
            rows = conn.execute(sql, (safe, PROJECT, depth)).fetchall()
        legs[f"fts_{tag}"] = [(tag, r["chunk_id"]) for r in rows]
    return legs


def rrf(lists, k):
    scores = {}
    for lst in lists:
        for rank, key in enumerate(lst):
            scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank)
    return sorted(scores, key=lambda m: scores[m], reverse=True)


def rrf_scores(lists, k):
    scores = {}
    for lst in lists:
        for rank, key in enumerate(lst):
            scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank)
    return scores


def arm_prod(legs, pool, k=60):
    return rrf([l[:pool] for l in legs.values()], k)


def arm_modality_norm(legs, pool, k=60):
    """Fuse within modality first, then merge the two modality rankings by RRF.

    Rationale: a file chunk can never appear in a log leg and vice versa, so summing
    over 4 legs rewards *modality breadth* a gold chunk structurally cannot have.
    """
    f = rrf([legs["vec_file"][:pool], legs["fts_file"][:pool]], k)
    l = rrf([legs["vec_log"][:pool], legs["fts_log"][:pool]], k)
    return rrf([f, l], k)


def rr_at(ranked, gold, kmax=FINAL_K):
    g = set(gold)
    for i, (_t, cid) in enumerate(ranked[:kmax], start=1):
        if cid in g:
            return 1.0 / i, i
    return 0.0, None


def paired_t(a, b):
    """Paired t of a-b. Returns (mean_diff, t, n)."""
    d = [x - y for x, y in zip(a, b)]
    n = len(d)
    m = sum(d) / n
    if n < 2:
        return m, 0.0, n
    var = sum((x - m) ** 2 for x in d) / (n - 1)
    se = math.sqrt(var / n)
    return m, (m / se if se > 0 else 0.0), n


def main():
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    conn.enable_load_extension(True)
    import sqlite_vec
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)

    qpath = os.environ.get("QUERIES")
    queries = json.load(open(qpath))["queries"]

    arms = {}
    arms["prod"] = lambda legs: arm_prod(legs, 20, 60)
    for p in (5, 10, 15, 20, 30, 50, 100, 200):
        arms[f"pool{p}"] = (lambda p: lambda legs: arm_prod(legs, p, 60))(p)
    for k in (1, 5, 10, 20, 60, 120):
        arms[f"rrfk{k}"] = (lambda k: lambda legs: arm_prod(legs, 20, k))(k)
    arms["norm"] = lambda legs: arm_modality_norm(legs, 20, 60)
    for p in (50, 100, 200):
        arms[f"norm_pool{p}"] = (lambda p: lambda legs: arm_modality_norm(legs, p, 60))(p)
    for k in (1, 10):
        arms[f"norm_pool100_k{k}"] = (lambda k: lambda legs: arm_modality_norm(legs, 100, k))(k)

    per_arm = {name: {"rr": [], "hit3": [], "hit5": [], "ranks": []} for name in arms}

    for item in queries:
        q, gold = item["q"], item["gold"]
        qvec = embed([q])[0]
        legs = deep_legs(conn, q, qvec)
        for name, fn in arms.items():
            ranked = fn(legs)
            rr, rank = rr_at(ranked, gold)
            per_arm[name]["rr"].append(rr)
            per_arm[name]["ranks"].append(rank)
            per_arm[name]["hit3"].append(1 if (rank and rank <= 3) else 0)
            per_arm[name]["hit5"].append(1 if (rank and rank <= 5) else 0)
        print(".", end="", flush=True)
    print()

    base = per_arm["prod"]["rr"]
    rows = []
    for name, v in per_arm.items():
        n = len(v["rr"])
        mrr = sum(v["rr"]) / n
        r3 = sum(v["hit3"]) / n
        r5 = sum(v["hit5"]) / n
        md, t, _ = paired_t(v["rr"], base)
        rows.append((name, mrr, r3, r5, md, t))

    print(f"\n{'arm':<20}{'MRR':>8}{'R@3':>8}{'R@5':>8}{'dMRR':>9}{'t':>8}  verdict")
    for name, mrr, r3, r5, md, t in rows:
        verdict = "" if name == "prod" else (
            "SIGNIFICANT" if abs(t) > 2.052 else "not proven")
        print(f"{name:<20}{mrr:>8.4f}{r3:>8.2f}{r5:>8.2f}{md:>+9.4f}{t:>+8.2f}  {verdict}")

    out = os.environ.get("OUT", os.path.join(HERE, "sweep_results.json"))
    json.dump({"per_arm": {k: v for k, v in per_arm.items()},
               "summary": [{"arm": n, "mrr": m, "r3": a, "r5": b, "dmrr": d, "t": t}
                           for n, m, a, b, d, t in rows]},
              open(out, "w"), ensure_ascii=False, indent=1)
    print("WROTE", out)


if __name__ == "__main__":
    main()
