"""Seeded random choice of question targets (no cherry-picking). Corpus = pinned snapshot."""
import random, re, pathlib
C = pathlib.Path("/home/kesha/bench910/corpus/.orchestra")
rng = random.Random(910)
secs = []
for p in sorted((C/"kb").glob("*.md")):
    if p.name in ("README.md","history.md"): continue
    t = p.read_text(); parts = re.split(r"(?m)^(##+ .*)$", t)
    for i in range(1, len(parts), 2):
        if len(parts[i+1]) > 600: secs.append((f"kb/{p.name}", parts[i].strip("# ").strip()[:70], len(parts[i+1])))
reps = []
for p in sorted((C/"tasks").glob("*/report.md")):
    t = p.read_text(); parts = re.split(r"(?m)^(##+ .*)$", t)
    for i in range(1, len(parts), 2):
        if 600 < len(parts[i+1]) < 6000: reps.append((f"tasks/{p.parent.name}/report.md", parts[i].strip("# ").strip()[:70], len(parts[i+1])))
print(len(secs), len(reps))
kb = rng.sample(secs, 16); rp = rng.sample(reps, 34)
for x in kb: print("KB ", x)
for x in rp: print("REP", x)
