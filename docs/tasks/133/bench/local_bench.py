"""Reproduce the #8 baseline locally: bge-m3-int8 via fastembed, same triplets, same metric.

Purpose is control: if this does NOT land near +0.237 avg / +0.180 min, my harness is
wrong and every API number in this task is invalid.
"""
import json, os, time, math

os.environ.setdefault("FASTEMBED_CACHE_PATH", "/mnt/data/Projects/Python/orchestra/data/models")
from fastembed import TextEmbedding
from fastembed.common.model_description import PoolingType, ModelSource

MODEL = "AlpEge/bge-m3-onnx-int8"
TRIPLETS = json.load(open('/tmp/emb133/triplets.json'))


def cos(a, b):
    s = sum(x * y for x, y in zip(a, b))
    return s / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(x * x for x in b)))


if MODEL not in {m["model"] for m in TextEmbedding.list_supported_models()}:
    TextEmbedding.add_custom_model(
        model=MODEL, pooling=PoolingType.CLS, normalization=True,
        sources=ModelSource(hf=MODEL), dim=1024, model_file="model_quantized.onnx",
    )

t0 = time.perf_counter()
emb = TextEmbedding(model_name=MODEL)
load_s = time.perf_counter() - t0

flat = []
for q, rel, dis in TRIPLETS:
    flat += [q, rel, dis]
vecs = [v.tolist() for v in emb.embed(flat)]

margins, rels, diss = [], [], []
for i in range(len(TRIPLETS)):
    q, rel, dis = vecs[3 * i], vecs[3 * i + 1], vecs[3 * i + 2]
    cr, cd = cos(q, rel), cos(q, dis)
    margins.append(cr - cd); rels.append(cr); diss.append(cd)

lats = []
for _ in range(5):
    t = time.perf_counter()
    list(emb.embed(["ссора с девушкой"]))
    lats.append((time.perf_counter() - t) * 1000)
lats.sort()

res = {
    "model": MODEL + " (local int8)", "dim": len(vecs[0]),
    "avg_margin": sum(margins) / len(margins), "min_margin": min(margins),
    "rel_range": [min(rels), max(rels)], "dis_range": [min(diss), max(diss)],
    "margins": margins, "load_s": load_s, "query_lat_ms_median": lats[2],
}
print(json.dumps(res, ensure_ascii=False, indent=1))
print(f"\nCONTROL vs #8: avg {res['avg_margin']:+.4f} (ожидалось +0.237), "
      f"min {res['min_margin']:+.4f} (ожидалось +0.180)")
json.dump(res, open('/tmp/emb133/local_results.json', 'w'), ensure_ascii=False, indent=1)
