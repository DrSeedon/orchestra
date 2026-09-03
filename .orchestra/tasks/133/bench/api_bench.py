"""Cosine separation margin for OpenRouter-hosted embedding models.

Same metric as kesha #8: margin = cos(query, relevant) - cos(query, distractor),
on the identical 5 Russian triplets, so numbers are comparable to bge-m3-int8 local.
"""
import json, os, sys, time, math, urllib.request

KEY = json.load(open('/home/maxim/.claude.json'))['mcpServers']['websearch']['env']['OPENROUTER_API_KEY']
URL = "https://openrouter.ai/api/v1/embeddings"
TRIPLETS = json.load(open('/tmp/emb133/triplets.json'))


def embed(model, texts, retries=3):
    """Returns (vectors, elapsed_seconds). Batched single request."""
    body = json.dumps({"model": model, "input": texts}).encode()
    req = urllib.request.Request(URL, data=body, headers={
        "Authorization": f"Bearer {KEY}", "Content-Type": "application/json"})
    last = None
    for a in range(retries):
        try:
            t0 = time.perf_counter()
            with urllib.request.urlopen(req, timeout=90) as r:
                d = json.loads(r.read())
            el = time.perf_counter() - t0
            vecs = [item["embedding"] for item in sorted(d["data"], key=lambda x: x["index"])]
            return vecs, el, d.get("usage", {})
        except Exception as e:
            last = e
            time.sleep(2 * (a + 1))
    raise RuntimeError(f"{model}: {last}")


def cos(a, b):
    s = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    return s / (na * nb)


def bench(model):
    flat = []
    for q, rel, dis in TRIPLETS:
        flat += [q, rel, dis]
    vecs, el, usage = embed(model, flat)
    margins, rels, diss = [], [], []
    for i in range(len(TRIPLETS)):
        q, rel, dis = vecs[3 * i], vecs[3 * i + 1], vecs[3 * i + 2]
        cr, cd = cos(q, rel), cos(q, dis)
        margins.append(cr - cd); rels.append(cr); diss.append(cd)
    # single-query latency, median of 5, measured separately from the batch
    lats = []
    for _ in range(5):
        _, e, _u = embed(model, ["ссора с девушкой"])
        lats.append(e * 1000)
    lats.sort()
    return {
        "model": model, "dim": len(vecs[0]),
        "avg_margin": sum(margins) / len(margins), "min_margin": min(margins),
        "rel_range": [min(rels), max(rels)], "dis_range": [min(diss), max(diss)],
        "margins": margins,
        "batch15_s": el, "query_lat_ms_median": lats[2],
        "usage": usage,
    }


if __name__ == "__main__":
    out = {}
    for m in sys.argv[1:]:
        try:
            r = bench(m)
            out[m] = r
            print(f"{m:38s} dim={r['dim']:5d} avg={r['avg_margin']:+.4f} min={r['min_margin']:+.4f} "
                  f"rel={r['rel_range'][0]:.2f}-{r['rel_range'][1]:.2f} "
                  f"dis={r['dis_range'][0]:.2f}-{r['dis_range'][1]:.2f} q={r['query_lat_ms_median']:.0f}ms")
        except Exception as e:
            out[m] = {"error": str(e)}
            print(f"{m:38s} ERROR {e}")
    json.dump(out, open('/tmp/emb133/api_results.json', 'w'), ensure_ascii=False, indent=1)
