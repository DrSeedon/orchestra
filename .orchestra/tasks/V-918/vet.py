import sys, json, os, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import llm
from concurrent.futures import ThreadPoolExecutor
Q = ("Below is an ORIGIN commit diff followed by LATER FIX commits that changed lines the origin introduced. Decide: did a later fix correct a real defect "
"(wrong behavior, crash, data loss, security hole, race, broken contract) that was introduced by the ORIGIN diff and could in principle be seen by reading the origin diff alone? "
"Not a defect: new requirement, feature extension, refactor, style, UX preference, policy change, adaptation to a later external change, or a fix of a different problem that merely touched the same lines. "
"Reply with ONLY one line of JSON, no prose, no code fence: {\"verdict\":\"yes|no|unclear\",\"mechanism\":\"one sentence naming the defect in the origin and the file/function, or why not\"}\n\n")
c = json.load(open('cand.json')); model = sys.argv[1]; out = f'vet_{model}.json'
res = json.load(open(out)) if os.path.exists(out) else {}
def one(x):
    if x['id'] in res and 'ERR' not in res[x['id']][:5]: return
    t = open(f"packets/{x['id']}.md").read()[:70000]
    r = llm.run(model, Q + t)
    res[x['id']] = r.strip()
    json.dump(res, open(out, 'w'), indent=1)
with ThreadPoolExecutor(6) as ex: list(ex.map(one, c))
