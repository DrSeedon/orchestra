"""Validate frozen questions: gold matches, acceptable sets, lexical overlap of question with the gold window."""
import re, sys, json, pathlib, collections
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from questions import Q
C = pathlib.Path("/home/kesha/bench910/corpus")
files = {str(p.relative_to(C)): p.read_text() for p in sorted((C/".orchestra").rglob("*.md"))}
tok = lambda s: [w[:5] for w in re.findall(r"[a-zа-яё0-9_]{5,}", s.lower())]
df = collections.Counter()
for t in files.values(): df.update(set(tok(t)))
out = {}
for q in Q:
    rx = re.compile(q["gold"]); acc = [f for f, t in files.items() if rx.search(t) and f != ".orchestra/kb/README.md"]
    qs = set(tok(q["q"])); best = []
    for f in acc:
        t = files[f]; m = rx.search(t); w = t[max(0, m.start()-1500): m.end()+1500]
        sh = sorted(s for s in qs & set(tok(w)) if df[s] <= 8)
        if not best or len(sh) < len(best): best = sh  # most favourable file for the "paraphrase" claim? use min -> report both
    allsh = max((sorted(s for s in qs & set(tok(files[f][max(0,rx.search(files[f]).start()-1500): rx.search(files[f]).end()+1500])) if df[s] <= 8) for f in acc), key=len, default=[])
    out[q["id"]] = dict(kind=q["kind"], acceptable=acc, shared_rare_max=allsh)
    print(q["id"], q["kind"], len(acc), acc[:3], "SHARED:", allsh)
json.dump(out, open(pathlib.Path(__file__).parent/"reference.json", "w"), ensure_ascii=False, indent=1)
