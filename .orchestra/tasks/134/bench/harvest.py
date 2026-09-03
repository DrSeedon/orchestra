"""Harvest candidate gold chunks from the LIVE corpus for the #134 retrieval benchmark.

Why not reuse #133 triplets: a triplet is an isolated 2-way cosine comparison. A reranker
and the hybrid both act on a RANKING produced from the whole corpus, so they are invisible
to that metric. #134 needs (query -> gold chunk_id) pairs scored by MRR/Recall@k over all
68k chunks.

This script only DUMPS candidates; the queries and ground truth are written by hand into
queries.json afterwards (a chunk sampled at random is not a question anyone would ask).
"""
import json
import sqlite3
import sys

DB = "/mnt/data/Projects/Python/orchestra/data/vec.db"
PROJECT = "/mnt/data/Projects/Python/orchestra"


def main(n: int, seed: int, min_len: int, kind: str) -> None:
    c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    if kind == "file":
        sql = ("SELECT fc.chunk_id, f.path, fc.text FROM file_chunks fc "
               "JOIN files f ON f.file_id=fc.file_id "
               "WHERE f.project=? AND length(fc.text)>? "
               "ORDER BY substr(fc.chunk_id*?, -6) LIMIT ?")
        rows = c.execute(sql, (PROJECT, min_len, seed, n)).fetchall()
        out = [{"chunk_id": r["chunk_id"], "source": "file", "path": r["path"],
                "text": r["text"]} for r in rows]
    else:
        sql = ("SELECT lc.chunk_id, lc.kind, lc.author, lc.text FROM log_chunks lc "
               "JOIN logs_indexed li ON li.log_id=lc.log_id "
               "WHERE li.project=? AND length(lc.text)>? "
               "ORDER BY substr(lc.chunk_id*?, -6) LIMIT ?")
        rows = c.execute(sql, (PROJECT, min_len, seed, n)).fetchall()
        out = [{"chunk_id": r["chunk_id"], "source": "log", "kind": r["kind"],
                "author": r["author"], "text": r["text"]} for r in rows]
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main(n=int(sys.argv[1]), seed=int(sys.argv[2]), min_len=int(sys.argv[3]),
         kind=sys.argv[4] if len(sys.argv) > 4 else "file")
