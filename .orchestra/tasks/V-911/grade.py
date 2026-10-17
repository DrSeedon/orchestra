"""V-911 grading: both models grade each answer against the blind checklist (0/0.5/1 per finding), not knowing the arm.
Usage (repo root): python .orchestra/tasks/V-911/grade.py"""
import asyncio, glob, json, random, re, sys, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(Path(__file__).parent))
import scripts.wf_adapters as wa
from app.models import resolve_model
from tasks import RESEARCH, GRADER_PROMPT
H = Path(__file__).parent; RAW = H / "raw"; G = H / "grades"; G.mkdir(exist_ok=True)
MODELS = {"luna": resolve_model("luna"), "sonnet": resolve_model("sonnet")}
SEM = asyncio.Semaphore(4)

def final(rid):
    r = json.load(open(RAW / f"{rid}.json"))
    return r["final_text"] if r["ok"] else ""

async def ask(prompt, judge):
    scratch = Path(tempfile.mkdtemp(prefix="v911-g-"))
    async with SEM:
        res = await wa.run_adapter(prompt, model=MODELS[judge], cwd=scratch, timeout=600, tools="read",
                                   network=(judge == "luna"), mcp=False, billing_mode="subscription")
    m = re.search(r"\{.*\}", res.text or "", re.S)
    try: return json.loads(m.group(0)), res
    except Exception: return None, res

def execs():
    for f in sorted(glob.glob(str(RAW / "*.json"))):
        r = json.load(open(f))
        if r["stage"] == "exec": yield r

async def grade_research():
    jobs = []
    for r in execs():
        if r["kind"] != "research" or not r["ok"]: continue
        for judge in MODELS:
            out = G / f"res-{r['run_id']}-{judge}.json"
            if out.exists() and json.load(open(out)).get("ok"): continue
            cl = RESEARCH[r["task"]]["checklist"]
            prompt = (GRADER_PROMPT + "\n\nChecklist of key findings:\n" + "\n".join(f"{i+1}. {c}" for i, c in enumerate(cl))
                      + f"\n\nAnswer to grade:\n<<<\n{r['final_text']}\n>>>")
            async def one(prompt=prompt, judge=judge, out=out, r=r, n=len(cl)):
                d, res = await ask(prompt, judge)
                sc = d.get("scores") if d else None
                ok = isinstance(sc, list) and len(sc) == n
                out.write_text(json.dumps(dict(run_id=r["run_id"], judge=judge, ok=ok, scores=sc if ok else None, raw=res.text[:500])))
            jobs.append(one())
    await asyncio.gather(*jobs)

asyncio.run(grade_research())
