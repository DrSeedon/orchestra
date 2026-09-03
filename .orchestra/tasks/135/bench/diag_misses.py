"""#135 — diagnose WHY gold chunks never surface. Read-only, no external APIs.

For each query: does the gold chunk exist in the index at all? If yes, what is its
rank in each unbounded ranked list (vec-files, vec-logs, fts-files, fts-logs) and in
the fused RRF list? "Not in index" and "in index at rank 40" lead to different fixes.

Also reports, per gold chunk, the exact text and which retrieval leg (if any) can see it.
"""
import json
import os
import re
import sqlite3
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.environ.get("BENCH_DB")
PROJECT = os.environ.get("BENCH_PROJECT", "/mnt/data/Projects/Python/orchestra")
RRF_K = 60
DEEP = int(os.environ.get("DEEP", "2000"))  # unbounded-ish probe depth

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


def gold_exists(conn, cid):
    """Is this chunk_id present in file_chunks or log_chunks, and is it embedded+indexed?"""
    r = conn.execute("SELECT fc.chunk_id, fc.text, f.path, f.project FROM file_chunks fc "
                     "JOIN files f ON f.file_id=fc.file_id WHERE fc.chunk_id=?", (cid,)).fetchone()
    if r:
        has_vec = conn.execute("SELECT 1 FROM vec_files WHERE chunk_id=?", (cid,)).fetchone()
        has_fts = conn.execute("SELECT 1 FROM fts_files WHERE rowid=?", (cid,)).fetchone()
        return {"source": "file", "path": r["path"], "project": r["project"],
                "text": r["text"], "in_vec": bool(has_vec), "in_fts": bool(has_fts)}
    r = conn.execute("SELECT lc.chunk_id, lc.text, lc.kind, lc.log_id, li.project FROM log_chunks lc "
                     "JOIN logs_indexed li ON li.log_id=lc.log_id WHERE lc.chunk_id=?", (cid,)).fetchone()
    if r:
        has_vec = conn.execute("SELECT 1 FROM vec_logs WHERE chunk_id=?", (cid,)).fetchone()
        has_fts = conn.execute("SELECT 1 FROM fts_logs WHERE rowid=?", (cid,)).fetchone()
        return {"source": "log", "kind": r["kind"], "log_id": r["log_id"],
                "project": r["project"], "text": r["text"],
                "in_vec": bool(has_vec), "in_fts": bool(has_fts)}
    return None


def deep_lists(conn, query, qvec, depth):
    """Four ranked legs, each to `depth`. Same SQL shape as production."""
    out = {}
    for table, tag in (("vec_files", "file"), ("vec_logs", "log")):
        rows = conn.execute(
            f"SELECT chunk_id FROM {table} WHERE project=? AND embedding MATCH ? "
            f"ORDER BY distance LIMIT ?", (PROJECT, _pack(qvec), depth)).fetchall()
        out[f"vec_{tag}"] = [(tag, r["chunk_id"]) for r in rows]
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
        out[f"fts_{tag}"] = [(tag, r["chunk_id"]) for r in rows]
    return out


def rrf(*lists, k=RRF_K):
    scores = {}
    for lst in lists:
        for rank, key in enumerate(lst):
            scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank)
    return sorted(scores, key=lambda m: scores[m], reverse=True)


def rank_of(lst, gold_ids):
    """1-based rank of best gold hit in a list of (tag, cid); None if absent."""
    gold = set(gold_ids)
    for i, (_t, cid) in enumerate(lst, start=1):
        if cid in gold:
            return i
    return None


def main():
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    conn.enable_load_extension(True)
    import sqlite_vec
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)

    qpath = os.environ.get("QUERIES") or os.path.join(
        HERE, "..", "..", "134", "bench", "queries.json")
    queries = json.load(open(qpath))["queries"]
    only = os.environ.get("ONLY")
    if only:
        idxs = [int(x) for x in only.split(",")]
        queries = [queries[i] for i in idxs]

    report = []
    for item in queries:
        q, gold = item["q"], item["gold"]
        rec = {"q": q, "gold": gold, "gold_chunks": [], "ranks": {}}
        for cid in gold:
            info = gold_exists(conn, cid)
            rec["gold_chunks"].append({"chunk_id": cid, "found": info is not None,
                                       **({} if info is None else {
                                           "source": info["source"],
                                           "path": info.get("path"),
                                           "kind": info.get("kind"),
                                           "project": info.get("project"),
                                           "in_vec": info["in_vec"],
                                           "in_fts": info["in_fts"],
                                           "len": len(info["text"]),
                                           "text_head": info["text"][:400]})})
        # app/rag.py:33 MODEL_PREFIX=False — bge-m3 uses CLS pooling, no query:/passage: prefix.
        qvec = embed([q])[0]
        legs = deep_lists(conn, q, qvec, DEEP)
        for name, lst in legs.items():
            rec["ranks"][name] = rank_of(lst, gold)
            rec["ranks"][f"{name}_len"] = len(lst)
        # production shape: each leg cut to pool=20, then RRF
        pool = 20
        fused_prod = rrf(*[l[:pool] for l in legs.values()])
        rec["ranks"]["rrf_pool20"] = rank_of(fused_prod, gold)
        fused_deep = rrf(*legs.values())
        rec["ranks"]["rrf_deep"] = rank_of(fused_deep, gold)
        report.append(rec)
        print(json.dumps(rec, ensure_ascii=False)[:600], flush=True)

    out = os.environ.get("OUT", os.path.join(HERE, "diag_misses.json"))
    json.dump(report, open(out, "w"), ensure_ascii=False, indent=1)
    print("WROTE", out)


if __name__ == "__main__":
    main()
