"""#138 — chunking: the one parameter #135 left open. Measured on disk-anchored gold.

Arms (all local, $0):
  prod       production chunker as shipped (control)
  crumb      + the heading breadcrumb that app/rag.py:150 computes and then DISCARDS
  md2500     MD_MAX_CHUNK 1500 -> 2500
  md800      MD_MAX_CHUNK 1500 -> 800
  crumb2500  breadcrumb + 2500 (interaction)

Scoring: chunk_id is an artifact of one chunking config, so a file hit = the retrieved chunk's
raw character span overlaps the gold span (gold_anchors_v3.json). Log legs are identical across
arms (md rechunking never touches logs) and are computed once, with exact chunk_id matching.

PASS/FAIL FIXED BEFORE RUNNING (per #135, both required):
  paired |t| > 2.052 (df=n-1)  AND  |dMRR| > 0.1048 (this sample's split-half noise floor).
Either alone -> NOT PROVEN.
"""
import json, os, re, sqlite3, struct, sys, time, statistics as st
import numpy as np

ROOT = os.environ.get("ORCHESTRA_ROOT", "/mnt/data/Projects/Python/orchestra")
DB = os.environ["BENCH_DB"]
ANCHORS = os.environ["GOLD_ANCHORS"]
OUT = os.environ.get("OUT", "/home/kesha/orchestra/data/bench138/rechunk_results.json")
FILES_ROOT = os.environ.get("FILES_ROOT", ROOT)
PROJ = "/mnt/data/Projects/Python/orchestra"
RRF_K, POOL_MULT, FINAL_K = 60, 4, 5

sys.path.insert(0, ROOT)
os.environ.setdefault("FASTEMBED_CACHE_PATH", os.path.join(ROOT, "data", "models"))
import app.rag as rag

conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
conn.enable_load_extension(True)
import sqlite_vec
sqlite_vec.load(conn)
conn.enable_load_extension(False)
conn.row_factory = sqlite3.Row
GOLD = json.load(open(ANCHORS))["gold"]


def embed(texts):
    return [list(map(float, v)) for v in rag._get_embedder().embed(texts)]


def _pack(v):
    return struct.pack(f"{len(v)}f", *v)


def indexed_paths():
    return [r["path"] for r in conn.execute(
        "SELECT DISTINCT f.path FROM files f JOIN file_chunks fc ON fc.file_id=f.file_id "
        "WHERE f.project=?", (PROJ,)).fetchall()]


# ---------- chunkers: production logic with two switches ----------
def chunk_md(content, md_max, crumb):
    lines = content.split("\n")
    sections, stack, buf, cr = [], [], [], ""

    def flush():
        text = "\n".join(buf).strip()
        if text:
            sections.append((cr, text))

    for line in lines:
        m = rag._HEADING_RE.match(line)
        if m:
            flush(); buf.clear()
            level = len(m.group(1)); title = m.group(2).strip()
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, title))
            cr = " > ".join(t for _, t in stack)
        buf.append(line)
    flush()
    if not sections:
        return [(c, "") for c in (rag._split_paragraphs(content, md_max) or rag._chunk(content))]

    res, pending, pcr = [], "", ""
    for cr_i, text in sections:
        if len(text) > md_max:
            if pending:
                res.append((pending.strip(), pcr)); pending = ""
            for part in rag._split_paragraphs(text, md_max):
                res.append((part, cr_i))
            continue
        if pending and len(pending) + len(text) + 2 > md_max:
            res.append((pending.strip(), pcr)); pending, pcr = text, cr_i
        else:
            if not pending:
                pcr = cr_i
            pending = (pending + "\n\n" + text) if pending else text
        if len(pending) >= rag.MD_MIN_MERGE:
            res.append((pending.strip(), pcr)); pending = ""
    if pending.strip():
        res.append((pending.strip(), pcr))
    return res


def build(cfg, paths):
    """-> texts (what gets embedded/indexed), spans [(path,start,end)] of the BODY on disk."""
    texts, spans = [], []
    for path in paths:
        fp = os.path.join(FILES_ROOT, path)
        if not os.path.exists(fp):
            continue
        content = open(fp, encoding="utf-8", errors="replace").read()
        if not content.strip():
            continue
        if path.endswith(".md"):
            pieces = chunk_md(content, cfg["md_max"], cfg["crumb"])
        else:
            pieces = [(c, "") for c in rag._chunk(content)]
        cursor = 0
        for body, cr in pieces:
            for part in (rag._chunk(body) if len(body) > rag.CHUNK_CHAR_LIMIT else [body]):
                probe = part[:100]
                i = content.find(probe, cursor)
                if i < 0:
                    i = content.find(probe)
                if i < 0:
                    i = cursor
                spans.append((path, i, i + len(part)))
                # the breadcrumb is what production INTENDED to prepend but never did
                texts.append(f"{cr}\n{part}" if (cfg["crumb"] and cr
                                                 and not part.lstrip().startswith("#")) else part)
                cursor = max(cursor, i)
    return texts, spans


def log_legs():
    pool = FINAL_K * POOL_MULT
    cache = {}
    for g in GOLD:
        qv = embed([g["q"]])[0]
        rows = conn.execute("SELECT chunk_id FROM vec_logs WHERE project=? AND embedding MATCH ? "
                            "ORDER BY distance LIMIT ?", (PROJ, _pack(qv), pool * 3)).fetchall()
        lv = [("log", r["chunk_id"]) for r in rows][:pool]
        match = rag.RagMemory._expand_query(g["q"]) or ('"' + g["q"].replace('"', '""') + '"')
        try:
            rows = conn.execute(
                "SELECT ft.rowid AS chunk_id FROM fts_logs ft JOIN log_chunks lc ON lc.chunk_id=ft.rowid "
                "JOIN logs_indexed li ON li.log_id=lc.log_id WHERE fts_logs MATCH ? AND li.project=? "
                "ORDER BY rank LIMIT ?", (match, PROJ, pool * 3)).fetchall()
        except Exception:
            rows = []
        cache[g["i"]] = (lv, [("log", r["chunk_id"]) for r in rows][:pool], qv)
    return cache


def run_arm(name, cfg, paths, cache):
    t0 = time.time()
    texts, spans = build(cfg, paths)
    M = np.array([v for i in range(0, len(texts), 64) for v in embed(texts[i:i + 64])],
                 dtype="float32")
    M /= (np.linalg.norm(M, axis=1, keepdims=True) + 1e-9)
    mem = sqlite3.connect(":memory:")
    mem.execute("CREATE VIRTUAL TABLE fts USING fts5(text, tokenize='unicode61')")
    mem.executemany("INSERT INTO fts(rowid,text) VALUES(?,?)", list(enumerate(texts)))
    mem.commit()

    pool = FINAL_K * POOL_MULT
    per_q = []
    for g in GOLD:
        if not g["anchors"]:
            continue
        lv, lf, qv = cache[g["i"]]
        q = np.array(qv, dtype="float32"); q /= (np.linalg.norm(q) + 1e-9)
        sims = M @ q
        fv = [("file", int(i)) for i in np.argsort(-sims)[:pool]]
        match = rag.RagMemory._expand_query(g["q"]) or ('"' + g["q"].replace('"', '""') + '"')
        try:
            ff = [("file", r[0]) for r in mem.execute(
                "SELECT rowid FROM fts WHERE fts MATCH ? ORDER BY rank LIMIT ?",
                (match, pool)).fetchall()]
        except Exception:
            ff = []
        ranked = rag.RagMemory._rrf(fv, ff, lv, lf)
        fa = [a for a in g["anchors"] if a["kind"] == "file"]
        la = {a["orig_chunk_id"] for a in g["anchors"] if a["kind"] == "log"}
        rr, rank = 0.0, 0
        for pos, (kind, key) in enumerate(ranked[:FINAL_K], start=1):
            if kind == "log":
                hit = key in la
            else:
                p, s, e = spans[key]
                hit = any(a["path"] == p and not (e <= a["span"][0] or s >= a["span"][1]) for a in fa)
            if hit:
                rr, rank = 1.0 / pos, pos
                break
        per_q.append({"i": g["i"], "q": g["q"], "rr": rr, "rank": rank})
    return {"arm": name, "cfg": cfg, "n_chunks": len(texts), "n_q": len(per_q),
            "MRR": st.mean(x["rr"] for x in per_q),
            "R@3": sum(1 for x in per_q if 0 < x["rank"] <= 3) / len(per_q),
            "R@5": sum(1 for x in per_q if x["rank"] > 0) / len(per_q),
            "secs": round(time.time() - t0, 1), "detail": per_q}


ARMS = {"prod": dict(md_max=1500, crumb=False),
        "crumb": dict(md_max=1500, crumb=True),
        "md2500": dict(md_max=2500, crumb=False),
        "md800": dict(md_max=800, crumb=False),
        "crumb2500": dict(md_max=2500, crumb=True)}

if __name__ == "__main__":
    paths = indexed_paths()
    print(f"indexed files: {len(paths)}")
    cache = log_legs()
    res = {}
    for n, c in ARMS.items():
        r = run_arm(n, c, paths, cache)
        res[n] = r
        print(f"{n:<11} chunks={r['n_chunks']:<6} n={r['n_q']:<3} MRR={r['MRR']:.4f} "
              f"R@3={r['R@3']:.2f} R@5={r['R@5']:.2f} ({r['secs']}s)")
    base = [x["rr"] for x in res["prod"]["detail"]]
    print(f"\n{'arm':<11}{'dMRR':>10}{'t':>8}   verdict (need |t|>2.052 AND |d|>0.1048)")
    for n in ARMS:
        if n == "prod":
            continue
        cur = [x["rr"] for x in res[n]["detail"]]
        d = [a - b for a, b in zip(cur, base)]
        m = st.mean(d)
        se = st.stdev(d) / len(d) ** 0.5 if len(d) > 1 and st.stdev(d) else 0
        t = m / se if se else 0.0
        print(f"{n:<11}{m:>+10.4f}{t:>8.2f}   "
              f"{'PROVEN' if abs(t) > 2.052 and abs(m) > 0.1048 else 'NOT PROVEN'}")
    json.dump(res, open(OUT, "w"), ensure_ascii=False, indent=1)
    print(f"\nwrote {OUT}")
