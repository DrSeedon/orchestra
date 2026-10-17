"""V-910 arm B queries against the index built by build_b.py (bot venv, rag.py imported read-only)."""
import json, sys, time
from pathlib import Path
sys.dont_write_bytecode = True
sys.path.insert(0, "/opt/kesha-bot"); sys.path.insert(0, str(Path(__file__).parent))
import rag
from questions import Q
OUT = Path("/home/kesha/bench910/b")
r = rag.RagMemory(path=OUT / "vec.db", msg_db=OUT / "stub_messages.db", readonly=True)
def paths(chunk_ids):
    if not chunk_ids: return {}
    ph = ",".join("?" * len(chunk_ids))
    return {x["chunk_id"]: x["path"] for x in r.conn.execute(
        f"SELECT fc.chunk_id, f.path FROM file_chunks fc JOIN files f ON f.file_id=fc.file_id WHERE fc.chunk_id IN ({ph})", chunk_ids)}
res = {}
for q in Q:
    t0 = time.time(); qv = r._embed([q["q"]], is_query=True)[0]; out = {}
    for limit in (5, 10):
        pool = limit * rag.POOL_MULT
        v = [("f", c) for c in r._vec_search_files(qv, pool)]; f = [("f", c) for c in r._fts_search_files(q["q"], pool)]
        fused = r._rrf(v, f)[:limit]
        ids = [k[1] for k in fused] + [k[1] for k in v[:limit]] + [k[1] for k in f[:limit]]
        pm = paths(list(set(ids)))
        out[f"hybrid{limit}"] = [pm[k[1]] for k in fused]; out[f"vec{limit}"] = [pm[k[1]] for k in v[:limit]]; out[f"fts{limit}"] = [pm[k[1]] for k in f[:limit]]
    res[q["id"]] = out; print(q["id"], round(time.time() - t0, 2), out["hybrid5"][:3], flush=True)
json.dump(res, open(Path(__file__).parent / "b_results.json", "w"), ensure_ascii=False, indent=1)
