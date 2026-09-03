"""Why does local bge-m3 give +0.144 when #8 recorded +0.237 on the same triplets?

Hypotheses:
 H1 pooling: #8 says CLS. If the run that produced +0.237 used MEAN, margins differ.
 H2 normalization: True vs False.
 H3 prefixes: bge-m3 needs none, but E5-style "query:/passage:" may have leaked in.
Vary one factor at a time, same triplets, same cosine.
"""
import json, os, math, itertools

os.environ.setdefault("FASTEMBED_CACHE_PATH", "/mnt/data/Projects/Python/orchestra/data/models")
from fastembed import TextEmbedding
from fastembed.common.model_description import PoolingType, ModelSource

HF = "AlpEge/bge-m3-onnx-int8"
TRIPLETS = json.load(open('/tmp/emb133/triplets.json'))


def cos(a, b):
    return sum(x * y for x, y in zip(a, b)) / (
        math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(x * x for x in b)))


def run(pooling, norm, prefix, tag):
    name = f"{HF}-{tag}"
    if name not in {m["model"] for m in TextEmbedding.list_supported_models()}:
        TextEmbedding.add_custom_model(
            model=name, pooling=pooling, normalization=norm,
            sources=ModelSource(hf=HF), dim=1024, model_file="model_quantized.onnx")
    emb = TextEmbedding(model_name=name)
    flat = []
    for q, rel, dis in TRIPLETS:
        if prefix:
            flat += [f"query: {q}", f"passage: {rel}", f"passage: {dis}"]
        else:
            flat += [q, rel, dis]
    v = [x.tolist() for x in emb.embed(flat)]
    m = [cos(v[3*i], v[3*i+1]) - cos(v[3*i], v[3*i+2]) for i in range(len(TRIPLETS))]
    return sum(m)/len(m), min(m), m


for pooling, tag_p in [(PoolingType.CLS, "cls"), (PoolingType.MEAN, "mean")]:
    for norm in (True, False):
        for prefix in (False, True):
            tag = f"{tag_p}-n{int(norm)}-p{int(prefix)}"
            try:
                avg, mn, m = run(pooling, norm, prefix, tag)
                flag = "  <== matches #8" if avg > 0.22 and mn > 0.15 else ""
                print(f"{tag:16s} avg={avg:+.4f} min={mn:+.4f}{flag}")
            except Exception as e:
                print(f"{tag:16s} ERROR {str(e)[:60]}")
