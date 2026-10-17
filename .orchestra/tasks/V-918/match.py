import sys, os, json, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import llm
from concurrent.futures import ThreadPoolExecutor
S = json.load(open("vet_sonnet.json")); L = json.load(open("vet_luna.json"))
def mech(t):
    m = re.search(r'"mechanism"\s*:\s*"(.*?)"\s*\}', t, re.S); return m.group(1) if m else t[:300]
bad = [f[:-10] for f in sorted(os.listdir("raw")) if f.startswith("bad-") and f.endswith(".review.md")]
model = sys.argv[1]; out = f"match_{model}.json"; res = json.load(open(out)) if os.path.exists(out) else {}
def one(rid):
    if rid in res and not res[rid].startswith("ERR"): return
    cid = rid.split(".r")[0][4:]
    p = ("Below is an automated code review of a commit, and a description of a defect in that commit that was found and fixed later (two descriptions by two independent analysts). "
         "Does ANY finding in the review point at this same defect (same root problem in the same code area, even if worded differently or with a different suggested fix)? "
         "Being merely in the same file or a vague warning is NOT a match. Reply with ONLY JSON, no prose, no fence: {\"hit\":\"yes|no\",\"finding\":\"quote or 'none'\",\"why\":\"one sentence\"}\n\n"
         f"# DEFECT (analyst 1)\n{mech(S[cid])}\n\n# DEFECT (analyst 2)\n{mech(L[cid])}\n\n# REVIEW\n{open(f'raw/{rid}.review.md').read()}")
    res[rid] = llm.run(model, p).strip(); json.dump(res, open(out, "w"), indent=1)
with ThreadPoolExecutor(5) as ex: list(ex.map(one, bad))
