"""#133 вариант A — единый прогон: локальная bge-m3-int8 + все API-модели, ОДИН код, один день.

Лечит исходную болезнь #8: baseline и кандидаты меряются разным кодом в разное время,
поэтому расхождение невозможно диагностировать. Здесь всё идёт через один cos() и одни
триплеты, сырые косинусы сохраняются по каждому триплету.

Запуск: nice -n 15 .venv/bin/python bench_all.py
"""
import json, os, sys, time, math, urllib.request

os.environ.setdefault("FASTEMBED_CACHE_PATH", "/mnt/data/Projects/Python/orchestra/data/models")

DATA = json.load(open('/tmp/emb133/triplets_v2.json'))
TRIPLETS = [(t["q"], t["rel"], t["dis"]) for t in DATA["triplets"]]
KEY = json.load(open('/home/maxim/.claude.json'))['mcpServers']['websearch']['env']['OPENROUTER_API_KEY']
URL = "https://openrouter.ai/api/v1/embeddings"

API_MODELS = [
    "baai/bge-m3",
    "openai/text-embedding-3-large",
    "openai/text-embedding-3-small",
    "qwen/qwen3-embedding-8b",
    "google/gemini-embedding-001",
    "openai/text-embedding-ada-002",
]
LOCAL = "AlpEge/bge-m3-onnx-int8"


def cos(a, b):
    return sum(x * y for x, y in zip(a, b)) / (
        math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(x * x for x in b)))


def flat_texts():
    out = []
    for q, r, d in TRIPLETS:
        out += [q, r, d]
    return out


def embed_api(model, texts, retries=4):
    body = json.dumps({"model": model, "input": texts}).encode()
    last = None
    for a in range(retries):
        try:
            req = urllib.request.Request(URL, data=body, headers={
                "Authorization": f"Bearer {KEY}", "Content-Type": "application/json"})
            t0 = time.perf_counter()
            with urllib.request.urlopen(req, timeout=180) as r:
                d = json.loads(r.read())
            return ([i["embedding"] for i in sorted(d["data"], key=lambda x: x["index"])],
                    time.perf_counter() - t0)
        except Exception as e:
            last = e
            time.sleep(3 * (a + 1))
    raise RuntimeError(f"{model}: {last}")


def embed_local(texts):
    from fastembed import TextEmbedding
    from fastembed.common.model_description import PoolingType, ModelSource
    if LOCAL not in {m["model"] for m in TextEmbedding.list_supported_models()}:
        TextEmbedding.add_custom_model(
            model=LOCAL, pooling=PoolingType.CLS, normalization=True,
            sources=ModelSource(hf=LOCAL), dim=1024, model_file="model_quantized.onnx")
    emb = TextEmbedding(model_name=LOCAL)
    t0 = time.perf_counter()
    v = [x.tolist() for x in emb.embed(texts)]
    return v, time.perf_counter() - t0, emb


def score(vecs):
    per = []
    for i, (q, r, d) in enumerate(TRIPLETS):
        cr = cos(vecs[3 * i], vecs[3 * i + 1])
        cd = cos(vecs[3 * i], vecs[3 * i + 2])
        per.append({"i": i + 1, "q": q[:48], "rel": round(cr, 4),
                    "dis": round(cd, 4), "margin": round(cr - cd, 4)})
    m = [p["margin"] for p in per]
    rels = [p["rel"] for p in per]
    diss = [p["dis"] for p in per]
    m_sorted = sorted(m)
    return {
        "avg_margin": round(sum(m) / len(m), 4),
        "min_margin": round(min(m), 4),
        "median_margin": round(m_sorted[len(m_sorted) // 2], 4),
        "negatives": sum(1 for x in m if x <= 0),
        "rel_range": [round(min(rels), 4), round(max(rels), 4)],
        "dis_range": [round(min(diss), 4), round(max(diss), 4)],
        "per_triplet": per,
    }


if __name__ == "__main__":
    texts = flat_texts()
    results = {}

    v, el, emb = embed_local(texts)
    lat = []
    for _ in range(5):
        t = time.perf_counter(); list(emb.embed([TRIPLETS[0][0]])); lat.append((time.perf_counter() - t) * 1000)
    lat.sort()
    r = score(v)
    r.update({"dim": len(v[0]), "batch_s": round(el, 2), "query_ms": round(lat[2], 1),
              "transport": "local"})
    results["LOCAL " + LOCAL] = r
    print(f"{'LOCAL '+LOCAL:38s} dim={r['dim']:5d} avg={r['avg_margin']:+.4f} "
          f"min={r['min_margin']:+.4f} neg={r['negatives']} q={r['query_ms']:.0f}ms")

    for m in API_MODELS:
        try:
            v, el = embed_api(m, texts)
            lat = []
            for _ in range(3):
                _v, e = embed_api(m, [TRIPLETS[0][0]]); lat.append(e * 1000)
            lat.sort()
            r = score(v)
            r.update({"dim": len(v[0]), "batch_s": round(el, 2),
                      "query_ms": round(lat[1], 1), "transport": "openrouter"})
            results[m] = r
            print(f"{m:38s} dim={r['dim']:5d} avg={r['avg_margin']:+.4f} "
                  f"min={r['min_margin']:+.4f} neg={r['negatives']} q={r['query_ms']:.0f}ms")
        except Exception as e:
            results[m] = {"error": str(e)}
            print(f"{m:38s} ERROR {str(e)[:70]}")

    json.dump({"meta": DATA["_meta"], "results": results},
              open('/tmp/emb133/results_v2.json', 'w'), ensure_ascii=False, indent=1)
    print("\n-> /tmp/emb133/results_v2.json")
