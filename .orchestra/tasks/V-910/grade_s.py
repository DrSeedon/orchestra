"""Blind cross-family grading of S answers (current in-force conclusion). Writes grades_s.json."""
import asyncio, glob, json, re, sys, tempfile
from pathlib import Path
H = Path(__file__).parent; sys.path.insert(0, str(H)); sys.path.insert(0, str(H.parents[2]))
import scripts.wf_adapters as wa
from app.models import resolve_model
from questions import Q
rub = {q["id"]: (q["q"], q["rubric"]) for q in Q if q["kind"] == "S"}
M = {"luna": resolve_model("luna"), "sonnet": resolve_model("sonnet")}
async def one(f):
    r = json.load(open(f))
    if r["qid"] not in rub or not r["ok"]: return None
    q, ru = rub[r["qid"]]; judge = "sonnet" if r["model"] == "luna" else "luna"
    p = (f"Grade an answer against a reference.\nQuestion: {q}\nReference (the conclusion in force now): {ru}\n"
         f"Answer to grade:\n{r['final_text']}\n\nIs the answer's stated current conclusion consistent with the reference "
         f"(it must not present the withdrawn/old conclusion as current)? Reply with one line of JSON: {{\"correct\": 0 or 1, \"why\": \"...\"}}")
    with tempfile.TemporaryDirectory() as d:
        res = await wa.run_adapter(p, model=M[judge], cwd=Path(d), timeout=300, tools="read", network=False, mcp=False, billing_mode="subscription")
    m = re.search(r'"correct"\s*:\s*([01])', res.text or "")
    return dict(run_id=r["run_id"], judge=judge, correct=int(m.group(1)) if m else None, text=(res.text or "")[:300])
async def main():
    out = [x for x in await asyncio.gather(*[one(f) for f in sorted(glob.glob(str(H / "raw_a/*.json")))]) if x]
    json.dump(out, open(H / "grades_s.json", "w"), ensure_ascii=False, indent=1)
    for q in rub:
        g = [x for x in out if x["run_id"].startswith(q)]
        print(q, [x["correct"] for x in g])
asyncio.run(main())
