"""#134 — retrieval benchmark over the LIVE corpus: embedder x fusion x reranker.

Metric: for each query, rank of the gold chunk in the returned list.
  RR   = 1/rank of the best gold hit (0 if not in top-K)   -> MRR
  R@k  = 1 if any gold in top-k
Paired t-test on per-query RR against the production baseline (hybrid RRF), same
queries for every configuration — the same statistical discipline as #133.

Configurations measured:
  vec        — vector only (local bge-m3-int8)
  fts        — FTS5 only
  hybrid     — vec + FTS5 fused by RRF  == PRODUCTION (app/rag.py search())
  *_rr_api   — hybrid top-N -> cohere/rerank-v3.5 -> top-5
  *_rr_local — hybrid top-N -> jina-reranker-v2-base-multilingual (local ONNX) -> top-5

Reranking is only meaningful over a CANDIDATE POOL, so retrieval runs with a deep
pool (RERANK_POOL) and the final cut is top-5 in every arm — otherwise the reranker
would be compared against a list it never saw.

Read-only against a COPY of vec.db. Never touches production.
"""
import json
import math
import os
import sqlite3
import struct
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.environ.get("BENCH_DB", "/tmp/vec134.db")
PROJECT = "/mnt/data/Projects/Python/orchestra"
RRF_K = 60
POOL_MULT = 4          # production value, app/rag.py:39
FINAL_K = 5            # search_memory default limit
RERANK_POOL = 50       # task spec: top-50 -> rerank -> top-5

OR_BASE = "https://openrouter.ai/api/v1"


def _key():
    """Lazy: only the API arm needs it. On the VPS there is no ~/.claude.json,
    and --no-api runs must not fail at import time."""
    return json.load(open(os.path.expanduser("~maxim/.claude.json")))[
        "mcpServers"]["websearch"]["env"]["OPENROUTER_API_KEY"]

_cost = {"rerank_units": 0, "rerank_usd": 0.0, "embed_calls": 0}


# ---------------------------------------------------------------- embedding
_embedder = None


def _get_embedder():
    """Same model + patched int8 config as production (app/rag.py:229-264)."""
    global _embedder
    if _embedder is None:
        # ORCHESTRA_ROOT lets the same script run on the laptop and on the VPS,
        # where the checkout lives under /home/kesha/orchestra.
        root = os.environ.get("ORCHESTRA_ROOT", "/mnt/data/Projects/Python/orchestra")
        sys.path.insert(0, root)
        os.environ.setdefault("FASTEMBED_CACHE_PATH", os.path.join(root, "data", "models"))
        from app.rag import _get_embedder as prod_embedder
        _embedder = prod_embedder()
    return _embedder


def embed_local(texts):
    return [list(map(float, v)) for v in _get_embedder().embed(texts)]


def _pack(vec):
    return struct.pack(f"{len(vec)}f", *vec)


# ---------------------------------------------------------------- retrieval
def _expand_query(query):
    import re
    words = [w for w in re.findall(r"\w+", query) if len(w) >= 3]
    return " OR ".join(f'"{w}"*' for w in words) if words else None


def vec_search(conn, qvec, pool):
    out = []
    for table, tag in (("vec_files", "file"), ("vec_logs", "log")):
        proj = "project=? AND " if True else ""
        sql = (f"SELECT chunk_id FROM {table} WHERE {proj}embedding MATCH ? "
               f"ORDER BY distance LIMIT ?")
        rows = conn.execute(sql, (PROJECT, _pack(qvec), pool * 3)).fetchall()
        out.append([(tag, r["chunk_id"]) for r in rows][:pool])
    return out  # [files, logs]


def fts_search(conn, query, pool):
    match = _expand_query(query) or ('"' + query.replace('"', '""') + '"')
    res = []
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
            rows = conn.execute(sql, (match, PROJECT, pool * 3)).fetchall()
        except Exception:
            safe = '"' + query.replace('"', '""') + '"'
            rows = conn.execute(sql, (safe, PROJECT, pool * 3)).fetchall()
        res.append([(tag, r["chunk_id"]) for r in rows][:pool])
    return res  # [files, logs]


def rrf(*lists, k=RRF_K):
    scores = {}
    for lst in lists:
        for rank, key in enumerate(lst):
            scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank)
    return sorted(scores, key=lambda m: scores[m], reverse=True)


def fetch_texts(conn, keys):
    """keys -> {key: text}. Two queries, batched."""
    out = {}
    fids = [k[1] for k in keys if k[0] == "file"]
    lids = [k[1] for k in keys if k[0] == "log"]
    if fids:
        ph = ",".join("?" * len(fids))
        for r in conn.execute(f"SELECT chunk_id, text FROM file_chunks WHERE chunk_id IN ({ph})", fids):
            out[("file", r["chunk_id"])] = r["text"]
    if lids:
        ph = ",".join("?" * len(lids))
        for r in conn.execute(f"SELECT chunk_id, text FROM log_chunks WHERE chunk_id IN ({ph})", lids):
            out[("log", r["chunk_id"])] = r["text"]
    return out


# ---------------------------------------------------------------- rerankers
def rerank_api(query, docs, model="cohere/rerank-v3.5", retries=3):
    """docs: list[str] -> list of indices, best first. Returns (order, elapsed)."""
    body = json.dumps({"model": model, "query": query,
                       "documents": docs, "top_n": len(docs)}).encode()
    last = None
    for a in range(retries):
        try:
            req = urllib.request.Request(f"{OR_BASE}/rerank", data=body, headers={
                "Authorization": f"Bearer {_key()}", "Content-Type": "application/json"})
            t0 = time.perf_counter()
            with urllib.request.urlopen(req, timeout=120) as r:
                d = json.loads(r.read())
            el = time.perf_counter() - t0
            u = d.get("usage") or {}
            _cost["rerank_units"] += u.get("search_units", 0)
            _cost["rerank_usd"] += float(u.get("cost", 0) or 0)
            return [x["index"] for x in d["results"]], el
        except Exception as e:
            last = e
            time.sleep(2 * (a + 1))
    raise RuntimeError(f"rerank_api failed: {last}")


_local_rr = None


def rerank_local(query, docs, model="jinaai/jina-reranker-v2-base-multilingual"):
    global _local_rr
    from fastembed.rerank.cross_encoder import TextCrossEncoder
    if _local_rr is None:
        _local_rr = TextCrossEncoder(model_name=model)
    t0 = time.perf_counter()
    scores = list(_local_rr.rerank(query, docs))
    el = time.perf_counter() - t0
    order = sorted(range(len(docs)), key=lambda i: scores[i], reverse=True)
    return order, el


# ---------------------------------------------------------------- scoring
def rr_and_hits(ranked_keys, gold_ids, k=FINAL_K):
    gold = set(gold_ids)
    for i, (_tag, cid) in enumerate(ranked_keys[:k], start=1):
        if cid in gold:
            return 1.0 / i, 1
    return 0.0, 0


def paired_t(a, b):
    """Paired t on per-query differences a-b. Returns (mean_diff, t, ci95_halfwidth)."""
    d = [x - y for x, y in zip(a, b)]
    n = len(d)
    m = sum(d) / n
    if n < 2:
        return m, 0.0, 0.0
    var = sum((x - m) ** 2 for x in d) / (n - 1)
    se = math.sqrt(var / n)
    if se == 0:
        return m, 0.0, 0.0
    # t_{0.975, df} approx for df=27 -> 2.052; task spec uses 2.16 (df=13). Use df-aware table.
    tcrit = {9: 2.262, 13: 2.160, 19: 2.093, 24: 2.064, 27: 2.052, 29: 2.045}.get(n - 1, 2.05)
    return m, m / se, tcrit * se


# ---------------------------------------------------------------- main
def main():
    qs = json.load(open(os.path.join(HERE, "queries.json")))["queries"]
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    conn.enable_load_extension(True)
    import sqlite_vec
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)

    arms = ["vec", "fts", "hybrid", "hybrid_rr_api", "hybrid_rr_local"]
    per_q = {a: {"rr": [], "hit1": [], "hit5": []} for a in arms}
    lat = {a: [] for a in arms}
    detail = []

    do_api = "--no-api" not in sys.argv
    do_local_rr = "--no-local-rr" not in sys.argv

    for item in qs:
        q, gold = item["q"], item["gold"]
        row = {"q": q, "gold": gold}

        t0 = time.perf_counter()
        qvec = embed_local([q])[0]
        t_embed = time.perf_counter() - t0

        t0 = time.perf_counter()
        v_files, v_logs = vec_search(conn, qvec, RERANK_POOL)
        t_vec = time.perf_counter() - t0
        t0 = time.perf_counter()
        f_files, f_logs = fts_search(conn, q, RERANK_POOL)
        t_fts = time.perf_counter() - t0

        # --- arm: vec only (production ordering semantics: pool then cut)
        vec_only = rrf(v_files, v_logs)
        # --- arm: fts only
        fts_only = rrf(f_files, f_logs)
        # --- arm: hybrid == production
        hybrid = rrf(v_files, f_files, v_logs, f_logs)

        for name, ranked, t in (("vec", vec_only, t_embed + t_vec),
                                ("fts", fts_only, t_fts),
                                ("hybrid", hybrid, t_embed + t_vec + t_fts)):
            rr, h5 = rr_and_hits(ranked, gold)
            _, h1 = rr_and_hits(ranked, gold, k=1)
            per_q[name]["rr"].append(rr)
            per_q[name]["hit1"].append(h1)
            per_q[name]["hit5"].append(h5)
            lat[name].append(t * 1000)
            row[name] = {"rr": rr, "hit5": h5,
                         "rank": (0 if rr == 0 else round(1 / rr))}

        # --- rerank arms: hybrid pool -> rerank -> top-5
        pool_keys = hybrid[:RERANK_POOL]
        texts = fetch_texts(conn, pool_keys)
        pool_keys = [k for k in pool_keys if k in texts]
        docs = [texts[k][:2000] for k in pool_keys]

        if do_api and docs:
            order, t_rr = rerank_api(q, docs)
            reranked = [pool_keys[i] for i in order]
            rr, h5 = rr_and_hits(reranked, gold)
            _, h1 = rr_and_hits(reranked, gold, k=1)
            per_q["hybrid_rr_api"]["rr"].append(rr)
            per_q["hybrid_rr_api"]["hit1"].append(h1)
            per_q["hybrid_rr_api"]["hit5"].append(h5)
            lat["hybrid_rr_api"].append((t_embed + t_vec + t_fts + t_rr) * 1000)
            row["hybrid_rr_api"] = {"rr": rr, "hit5": h5,
                                    "rank": (0 if rr == 0 else round(1 / rr)),
                                    "rerank_ms": round(t_rr * 1000)}

        if do_local_rr and docs:
            order, t_rr = rerank_local(q, docs)
            reranked = [pool_keys[i] for i in order]
            rr, h5 = rr_and_hits(reranked, gold)
            _, h1 = rr_and_hits(reranked, gold, k=1)
            per_q["hybrid_rr_local"]["rr"].append(rr)
            per_q["hybrid_rr_local"]["hit1"].append(h1)
            per_q["hybrid_rr_local"]["hit5"].append(h5)
            lat["hybrid_rr_local"].append((t_embed + t_vec + t_fts + t_rr) * 1000)
            row["hybrid_rr_local"] = {"rr": rr, "hit5": h5,
                                      "rank": (0 if rr == 0 else round(1 / rr)),
                                      "rerank_ms": round(t_rr * 1000)}

        detail.append(row)
        print(f"{q[:52]:54s} " + " ".join(
            f"{a}:{row[a]['rank'] if a in row else '-'}" for a in arms), flush=True)

    # ---------------- summary + paired t vs hybrid
    base = per_q["hybrid"]["rr"]
    summary = {}
    for a in arms:
        rrs = per_q[a]["rr"]
        if not rrs:
            continue
        n = len(rrs)
        md, t, ci = paired_t(rrs, base[:n]) if a != "hybrid" else (0.0, 0.0, 0.0)
        ls = sorted(lat[a])
        summary[a] = {
            "n": n,
            "MRR": sum(rrs) / n,
            "R@1": sum(per_q[a]["hit1"]) / n,
            "R@5": sum(per_q[a]["hit5"]) / n,
            "misses": sum(1 for x in rrs if x == 0),
            "delta_MRR_vs_hybrid": md,
            "t": t,
            "ci95": ci,
            "lat_median_ms": ls[len(ls) // 2],
        }

    out = {"summary": summary, "detail": detail, "cost": _cost,
           "config": {"RERANK_POOL": RERANK_POOL, "FINAL_K": FINAL_K,
                      "RRF_K": RRF_K, "n_queries": len(qs)}}
    json.dump(out, open(os.path.join(HERE, "retrieval_results.json"), "w"),
              ensure_ascii=False, indent=1)

    print(f"\n{'arm':18s} {'MRR':>7s} {'R@1':>6s} {'R@5':>6s} {'miss':>5s} "
          f"{'dMRR':>8s} {'t':>7s} {'lat_ms':>8s}")
    for a, s in summary.items():
        print(f"{a:18s} {s['MRR']:7.4f} {s['R@1']:6.2f} {s['R@5']:6.2f} "
              f"{s['misses']:5d} {s['delta_MRR_vs_hybrid']:+8.4f} {s['t']:+7.2f} "
              f"{s['lat_median_ms']:8.0f}")
    print(f"\ncost: {_cost}")


if __name__ == "__main__":
    main()
