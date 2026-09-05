"""#145 — does reviving the breadcrumb (app/rag.py:150) actually improve retrieval? Measure, then decide.

Arms (2 per run, per my own #138 sizing lesson; prod is the control and must reproduce exactly):
  prod        shipped chunker (control)  -> MUST give MRR 0.4893 / R@3 0.64 / R@5 0.75
  crumb       + breadcrumb prepended, EXACTLY as the dead code intended (stale stack and all)

Why not more arms at once: #138 ran 5 arms and died at 83 min CPU with nothing to show.

Scoring: chunk_id is an artifact of one chunking config, so a file hit = the retrieved chunk's
raw character span overlaps the gold span (gold_anchors_v3.json, 20/22 anchors, 0 round-trip
failures). Log legs are IDENTICAL across arms (md rechunking never touches logs) -> computed once.

Budget is held equal at 5 shown chunks in every arm (#138 lesson: comparing 10 shown against 5
measures context spend, not design).

PASS/FAIL FIXED BEFORE RUNNING, both required:
  paired |t| > 2.052 (df=n-1)  AND  |dMRR| > 0.1048 (this sample's split-half noise floor).
Either alone -> NOT PROVEN. A dead-code revival is not justified by aesthetics.
"""
import json, os, re, sqlite3, struct, sys, time, statistics as st
import numpy as np

ROOT = os.environ.get("ORCHESTRA_ROOT", "/mnt/data/Projects/Python/orchestra")
DB = os.environ["BENCH_DB"]
ANCHORS = os.environ["GOLD_ANCHORS"]
FILES_ROOT = os.environ.get("FILES_ROOT", ROOT)
OUT = os.environ.get("OUT", "/home/kesha/orchestra/data/bench145/crumb_results.json")
ARMS_ENV = os.environ.get("ARMS", "prod,crumb")
PROJ = "/mnt/data/Projects/Python/orchestra"
RRF_K, POOL_MULT, FINAL_K = 60, 4, 5

sys.path.insert(0, ROOT)
os.environ.setdefault("FASTEMBED_CACHE_PATH", os.path.join(ROOT, "data", "models"))
import app.rag as rag
import sqlite_vec

conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
conn.enable_load_extension(True); sqlite_vec.load(conn); conn.enable_load_extension(False)
conn.row_factory = sqlite3.Row
GOLD = json.load(open(ANCHORS))["gold"]
_pack = lambda v: struct.pack(f"{len(v)}f", *v)
embed = lambda ts: [list(map(float, v)) for v in rag._get_embedder().embed(ts)]
FENCE = re.compile(r"^\s*(```|~~~)")


def sections_of(content, fence_aware):
    """Split into (crumb, text). fence_aware=True ignores '# ...' lines inside code fences —
    626 of 8053 heading matches in our corpus are shell comments (81 files)."""
    lines, out, stack, buf, crumb, infence = content.split("\n"), [], [], [], "", False

    def flush():
        t = "\n".join(buf).strip()
        if t:
            out.append((crumb, t))

    for line in lines:
        if fence_aware and FENCE.match(line):
            infence = not infence
            buf.append(line)
            continue
        m = rag._HEADING_RE.match(line)
        if m and not (fence_aware and infence):
            flush(); buf.clear()
            lv = len(m.group(1)); ti = m.group(2).strip()
            while stack and stack[-1][0] >= lv:
                stack.pop()
            stack.append((lv, ti))
            crumb = " > ".join(t for _, t in stack)
        buf.append(line)
    flush()
    return out


def chunk_md(content, crumb_on, fence_aware):
    secs = sections_of(content, fence_aware)
    if not secs:
        return [(c, "") for c in (rag._split_paragraphs(content, rag.MD_MAX_CHUNK) or rag._chunk(content))]
    res, pending, pcr = [], "", ""
    for cr, text in secs:
        if len(text) > rag.MD_MAX_CHUNK:
            if pending:
                res.append((pending.strip(), pcr)); pending = ""
            for part in rag._split_paragraphs(text, rag.MD_MAX_CHUNK):
                res.append((part, cr))
            continue
        if pending and len(pending) + len(text) + 2 > rag.MD_MAX_CHUNK:
            res.append((pending.strip(), pcr)); pending, pcr = text, cr
        else:
            if not pending:
                pcr = cr
            pending = (pending + "\n\n" + text) if pending else text
        if len(pending) >= rag.MD_MIN_MERGE:
            res.append((pending.strip(), pcr)); pending = ""
    if pending.strip():
        res.append((pending.strip(), pcr))
    return res


def build(cfg, paths):
    """-> texts (embedded/indexed), spans [(path,start,end)] of the BODY on disk.
    The span is always the BODY, never the crumb: the anchor must stay comparable across arms."""
    texts, spans = [], []
    for path in paths:
        fp = os.path.join(FILES_ROOT, path)
        if not os.path.exists(fp):
            continue
        content = open(fp, encoding="utf-8", errors="replace").read()
        if not content.strip():
            continue
        if path.endswith(".md"):
            pieces = chunk_md(content, cfg["crumb"], cfg["fence"])
        else:
            pieces = [(c, "") for c in rag._chunk(content)]
        cursor = 0
        for body, cr in pieces:
            for part in (rag._chunk(body) if len(body) > rag.CHUNK_CHAR_LIMIT else [body]):
                i = content.find(part[:100], cursor)
                if i < 0:
                    i = content.find(part[:100])
                if i < 0:
                    i = cursor
                spans.append((path, i, i + len(part)))
                texts.append(f"{cr}\n{part}" if (cfg["crumb"] and cr
                                                 and not part.lstrip().startswith("#")) else part)
                cursor = max(cursor, i)
    return texts, spans


def log_legs():
    pool = FINAL_K * POOL_MULT
    cache = {}
    for g in GOLD:
        qv = embed([g["q"]])[0]
        lv = [("log", r["chunk_id"]) for r in conn.execute(
            "SELECT chunk_id FROM vec_logs WHERE project=? AND embedding MATCH ? ORDER BY distance LIMIT ?",
            (PROJ, _pack(qv), pool * 3))][:pool]
        m = rag.RagMemory._expand_query(g["q"]) or ('"' + g["q"].replace('"', '""') + '"')
        try:
            lf = [("log", r["chunk_id"]) for r in conn.execute(
                "SELECT ft.rowid AS chunk_id FROM fts_logs ft JOIN log_chunks lc ON lc.chunk_id=ft.rowid "
                "JOIN logs_indexed li ON li.log_id=lc.log_id WHERE fts_logs MATCH ? AND li.project=? "
                "ORDER BY rank LIMIT ?", (m, PROJ, pool * 3))][:pool]
        except Exception:
            lf = []
        cache[g["i"]] = (lv, lf, qv)
    return cache


def run_arm(name, cfg, paths, cache):
    t0 = time.time()
    texts, spans = build(cfg, paths)
    M = np.array([v for i in range(0, len(texts), 64) for v in embed(texts[i:i + 64])], dtype="float32")
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
        fv = [("file", int(i)) for i in np.argsort(-(M @ q))[:pool]]
        m = rag.RagMemory._expand_query(g["q"]) or ('"' + g["q"].replace('"', '""') + '"')
        try:
            ff = [("file", r[0]) for r in mem.execute(
                "SELECT rowid FROM fts WHERE fts MATCH ? ORDER BY rank LIMIT ?", (m, pool))]
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


ALL_ARMS = {
    "prod":       dict(crumb=False, fence=False),
    "crumb":      dict(crumb=True,  fence=False),
    "fence":      dict(crumb=False, fence=True),
    "crumbfence": dict(crumb=True,  fence=True),
}

if __name__ == "__main__":
    paths = [r["path"] for r in conn.execute(
        "SELECT DISTINCT f.path FROM files f JOIN file_chunks fc ON fc.file_id=f.file_id "
        "WHERE f.project=?", (PROJ,))]
    print(f"indexed files: {len(paths)}", flush=True)
    cache = log_legs()
    names = [a.strip() for a in ARMS_ENV.split(",") if a.strip()]
    res = {}
    for n in names:
        r = run_arm(n, ALL_ARMS[n], paths, cache)
        res[n] = r
        print(f"{n:<11} chunks={r['n_chunks']:<6} n={r['n_q']:<3} MRR={r['MRR']:.4f} "
              f"R@3={r['R@3']:.2f} R@5={r['R@5']:.2f} ({r['secs']}s)", flush=True)
    if "prod" in res:
        base = [x["rr"] for x in res["prod"]["detail"]]
        print(f"\n{'arm':<11}{'dMRR':>10}{'t':>8}   verdict (need |t|>2.052 AND |d|>0.1048)")
        for n in names:
            if n == "prod":
                continue
            cur = [x["rr"] for x in res[n]["detail"]]
            d = [a - b for a, b in zip(cur, base)]
            m = st.mean(d)
            sd = st.stdev(d) if len(d) > 1 else 0
            t = m / (sd / len(d) ** 0.5) if sd else 0.0
            print(f"{n:<11}{m:>+10.4f}{t:>8.2f}   "
                  f"{'PROVEN' if abs(t) > 2.052 and abs(m) > 0.1048 else 'NOT PROVEN'}")
    json.dump(res, open(OUT, "w"), ensure_ascii=False, indent=1)
    print(f"\nwrote {OUT}", flush=True)
