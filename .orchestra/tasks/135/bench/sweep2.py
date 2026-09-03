"""#135 sweep 2 — query-side and fusion-side arms. Zero cost, read-only.

Sweep 1 proved pool depth and RRF_K are inert (pool>=15 gives byte-identical rank
vectors). The remaining zero-cost levers are on the QUERY side (what FTS matches)
and in how the two modalities are weighted.

Arms:
  prod          — production baseline
  df_stop_N     — drop query terms whose document frequency exceeds N% of the corpus.
                  Stopwords are derived FROM THE CORPUS, not hand-picked, so this
                  does not encode my guess about which words matter.
  vecw_N        — weight the vector legs N x against FTS legs in RRF
  ftsw_N        — weight the FTS legs N x
  df_stop+vecw  — combination of whichever two win individually
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
POOL = 20
RRF_K = 60
DEEP = 200

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


def terms(query):
    return [w for w in re.findall(r"\w+", query) if len(w) >= 3]


def expand_all(query):
    w = terms(query)
    return " OR ".join(f'"{x}"*' for x in w) if w else None


_df_cache = {}


def doc_freq(conn, term, total):
    """Fraction of file_chunks containing this term (prefix form), cached."""
    key = term.lower()
    if key in _df_cache:
        return _df_cache[key]
    try:
        n = conn.execute(
            "SELECT count(*) c FROM fts_files WHERE fts_files MATCH ?",
            (f'"{term}"*',)).fetchone()["c"]
    except Exception:
        n = 0
    f = n / total if total else 0.0
    _df_cache[key] = f
    return f


def expand_df_stop(conn, query, total, thresh):
    """Drop terms appearing in more than `thresh` of chunks — corpus-derived stopwords."""
    w = terms(query)
    keep = [x for x in w if doc_freq(conn, x, total) <= thresh]
    if not keep:
        keep = w  # never produce an empty query
    return " OR ".join(f'"{x}"*' for x in keep)


def legs_for(conn, query_match, qvec, depth=DEEP):
    legs = {}
    for table, tag in (("vec_files", "file"), ("vec_logs", "log")):
        rows = conn.execute(
            f"SELECT chunk_id FROM {table} WHERE project=? AND embedding MATCH ? "
            f"ORDER BY distance LIMIT ?", (PROJECT, _pack(qvec), depth)).fetchall()
        legs[f"vec_{tag}"] = [(tag, r["chunk_id"]) for r in rows]
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
            rows = conn.execute(sql, (query_match, PROJECT, depth)).fetchall()
        except Exception:
            rows = []
        legs[f"fts_{tag}"] = [(tag, r["chunk_id"]) for r in rows]
    return legs


def rrf_w(weighted_lists, k=RRF_K):
    """weighted_lists: [(list, weight)]"""
    scores = {}
    for lst, w in weighted_lists:
        for rank, key in enumerate(lst):
            scores[key] = scores.get(key, 0.0) + w / (k + rank)
    return sorted(scores, key=lambda m: scores[m], reverse=True)


def fuse(legs, pool=POOL, vec_w=1.0, fts_w=1.0):
    return rrf_w([(legs["vec_file"][:pool], vec_w), (legs["vec_log"][:pool], vec_w),
                  (legs["fts_file"][:pool], fts_w), (legs["fts_log"][:pool], fts_w)])


def rr_at(ranked, gold, kmax=FINAL_K):
    g = set(gold)
    for i, (_t, cid) in enumerate(ranked[:kmax], start=1):
        if cid in g:
            return 1.0 / i, i
    return 0.0, None


def paired_t(a, b):
    d = [x - y for x, y in zip(a, b)]
    n = len(d)
    m = sum(d) / n
    if n < 2:
        return m, 0.0
    var = sum((x - m) ** 2 for x in d) / (n - 1)
    se = math.sqrt(var / n)
    return m, (m / se if se > 0 else 0.0)


def main():
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    conn.enable_load_extension(True)
    import sqlite_vec
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)

    total = conn.execute("SELECT count(*) c FROM file_chunks").fetchone()["c"]
    queries = json.load(open(os.environ["QUERIES"]))["queries"]

    arm_names = ["prod", "vecw2", "vecw3", "ftsw2"] + \
                [f"df_stop{int(t*100)}" for t in (0.5, 0.2, 0.1, 0.05, 0.02)] + \
                ["df_stop10_vecw2"]
    per_arm = {n: {"rr": [], "ranks": []} for n in arm_names}

    for item in queries:
        q, gold = item["q"], item["gold"]
        qvec = embed([q])[0]
        m_all = expand_all(q) or ('"' + q.replace('"', '""') + '"')
        legs_all = legs_for(conn, m_all, qvec)

        variants = {
            "prod": fuse(legs_all),
            "vecw2": fuse(legs_all, vec_w=2.0),
            "vecw3": fuse(legs_all, vec_w=3.0),
            "ftsw2": fuse(legs_all, fts_w=2.0),
        }
        for t in (0.5, 0.2, 0.1, 0.05, 0.02):
            m = expand_df_stop(conn, q, total, t)
            legs = legs_for(conn, m, qvec)
            variants[f"df_stop{int(t*100)}"] = fuse(legs)
            if t == 0.1:
                variants["df_stop10_vecw2"] = fuse(legs, vec_w=2.0)

        for n in arm_names:
            rr, rank = rr_at(variants[n], gold)
            per_arm[n]["rr"].append(rr)
            per_arm[n]["ranks"].append(rank)
        print(".", end="", flush=True)
    print()

    base = per_arm["prod"]["rr"]
    print(f"\n{'arm':<20}{'MRR':>8}{'R@3':>8}{'R@5':>8}{'dMRR':>9}{'t':>8}  verdict")
    summary = []
    for n in arm_names:
        v = per_arm[n]
        N = len(v["rr"])
        mrr = sum(v["rr"]) / N
        r3 = sum(1 for r in v["ranks"] if r and r <= 3) / N
        r5 = sum(1 for r in v["ranks"] if r and r <= 5) / N
        md, t = paired_t(v["rr"], base)
        verdict = "" if n == "prod" else ("SIGNIFICANT" if abs(t) > 2.052 else "not proven")
        print(f"{n:<20}{mrr:>8.4f}{r3:>8.2f}{r5:>8.2f}{md:>+9.4f}{t:>+8.2f}  {verdict}")
        summary.append({"arm": n, "mrr": mrr, "r3": r3, "r5": r5, "dmrr": md, "t": t})

    json.dump({"per_arm": per_arm, "summary": summary},
              open(os.environ.get("OUT", "sweep2_results.json"), "w"),
              ensure_ascii=False, indent=1)
    print("WROTE", os.environ.get("OUT"))


if __name__ == "__main__":
    main()
