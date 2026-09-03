"""Probe OpenRouter for rerank capability BY REQUEST (catalog is known-unreliable, #133).

Tries: (a) plausible rerank endpoint paths, (b) rerank model ids on /embeddings and
/rerank, (c) whether /models lists anything rerank-shaped. Raw statuses saved.
"""
import json, urllib.request, urllib.error

KEY = json.load(open('/home/maxim/.claude.json'))['mcpServers']['websearch']['env']['OPENROUTER_API_KEY']
BASE = "https://openrouter.ai/api/v1"

def call(path, body=None, method=None):
    url = f"{BASE}{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method or ("POST" if data else "GET"),
                                 headers={"Authorization": f"Bearer {KEY}",
                                          "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, r.read()[:600].decode('utf-8', 'replace')
    except urllib.error.HTTPError as e:
        return e.code, e.read()[:600].decode('utf-8', 'replace')
    except Exception as e:
        return None, repr(e)

RERANK_BODY = {
    "model": "PLACEHOLDER",
    "query": "как чинить зависший воркер",
    "documents": ["воркер завис из-за MCP", "как приготовить борщ"],
    "top_n": 2,
}

MODELS = [
    "cohere/rerank-v3.5", "cohere/rerank-english-v3.0", "cohere/rerank-multilingual-v3.0",
    "jina/jina-reranker-v2-base-multilingual", "jinaai/jina-reranker-v2-base-multilingual",
    "baai/bge-reranker-v2-m3", "BAAI/bge-reranker-v2-m3", "mixedbread-ai/mxbai-rerank-large-v1",
    "voyage/rerank-2", "voyageai/rerank-2", "qwen/qwen3-reranker-8b", "qwen/qwen3-reranker-4b",
]
PATHS = ["/rerank", "/reranks", "/rerankings", "/v1/rerank", "/embeddings/rerank"]

out = {"paths": {}, "models_on_rerank": {}, "models_on_embeddings": {}, "catalog": {}}

# (a) endpoint paths — probe with a known-ish model id
for p in PATHS:
    b = dict(RERANK_BODY, model="cohere/rerank-v3.5")
    s, t = call(p, b)
    out["paths"][p] = {"status": s, "body": t}
    print(f"POST {p:24s} -> {s} {t[:160]}")

# (b) model ids on the most plausible path + embeddings path
for m in MODELS:
    s, t = call("/rerank", dict(RERANK_BODY, model=m))
    out["models_on_rerank"][m] = {"status": s, "body": t}
    s2, t2 = call("/embeddings", {"model": m, "input": ["тест"]})
    out["models_on_embeddings"][m] = {"status": s2, "body": t2}
    print(f"{m:44s} rerank={s} emb={s2} | {t[:90]}")

# (c) catalog scan for rerank-shaped ids
s, t = call("/models")
try:
    full = json.loads(urllib.request.urlopen(urllib.request.Request(
        f"{BASE}/models", headers={"Authorization": f"Bearer {KEY}"}), timeout=60).read())
    ids = [m["id"] for m in full.get("data", [])]
    hits = [i for i in ids if "rerank" in i.lower() or "embed" in i.lower()]
    out["catalog"] = {"status": s, "total": len(ids), "rerank_or_embed_ids": hits}
    print(f"\ncatalog: {len(ids)} models, rerank/embed-shaped ids: {hits}")
except Exception as e:
    out["catalog"] = {"status": s, "error": repr(e)}
    print("catalog error", e)

json.dump(out, open("probe_rerank.json", "w"), ensure_ascii=False, indent=1)
