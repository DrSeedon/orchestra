"""Second sweep: more rerank id variants + latency + usage/pricing of the working one."""
import json, time, urllib.request, urllib.error

KEY = json.load(open('/home/maxim/.claude.json'))['mcpServers']['websearch']['env']['OPENROUTER_API_KEY']
BASE = "https://openrouter.ai/api/v1"


def call(path, body):
    req = urllib.request.Request(f"{BASE}{path}", data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"})
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            return r.status, json.loads(r.read()), time.perf_counter() - t0
    except urllib.error.HTTPError as e:
        return e.code, e.read()[:300].decode('utf-8', 'replace'), time.perf_counter() - t0
    except Exception as e:
        return None, repr(e), time.perf_counter() - t0


B = {"query": "почему воркер игнорирует правило и вызывает запрещённый инструмент",
     "documents": ["агент напечатал tool call текстом вместо вызова",
                   "Codex грузит AGENTS.md максимум на 32 KiB и режет посреди фразы",
                   "как приготовить борщ"],
     "top_n": 3}

CANDS = ["rerank-v3.5", "cohere/rerank-v3.5", "cohere/rerank-3.5", "cohere/rerank-v4",
         "cohere/rerank-multilingual-v3.5", "cohere/rerank-v3.5-multilingual",
         "jina-reranker-v2", "jina/reranker-v2", "bge-reranker-v2-m3",
         "qwen/qwen3-reranker", "mixedbread/mxbai-rerank-large-v2",
         "zerank-1", "zeroentropy/zerank-1", "zeroentropy/zerank-1-small",
         "nvidia/nv-rerankqa-mistral-4b-v3", "amazon/rerank-v1", "google/rerank"]

res = {}
for m in CANDS:
    s, d, el = call("/rerank", dict(B, model=m))
    ok = s == 200
    res[m] = {"status": s, "elapsed_s": round(el, 3), "resp": d if not ok else
              {"model": d.get("model"), "usage": d.get("usage"),
               "results": [(r["index"], r["relevance_score"]) for r in d.get("results", [])]}}
    print(f"{m:38s} {s} {el:5.2f}s {json.dumps(res[m]['resp'], ensure_ascii=False)[:170]}")

json.dump(res, open("probe_rerank2.json", "w"), ensure_ascii=False, indent=1)
