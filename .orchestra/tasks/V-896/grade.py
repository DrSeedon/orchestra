"""V-896 grading. Research: both models grade each answer against the checklist (blind to arm).
Creative: both models judge each (A,B) and (A,C) pair in a seeded random order (blind to arm).
Usage (repo root): python .orchestra/tasks/V-896/grade.py <research|creative>"""
import asyncio, glob, json, random, re, sys, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(Path(__file__).parent))
import scripts.wf_adapters as wa
from app.models import resolve_model
from tasks import RESEARCH, CREATIVE, JUDGE_CRITERIA, GRADER_PROMPT
H = Path(__file__).parent; RAW = H / "raw"; G = H / "grades"; G.mkdir(exist_ok=True)
MODELS = {"luna": resolve_model("luna"), "sonnet": resolve_model("sonnet")}
SEM = asyncio.Semaphore(4)

def final(rid):
    r = json.load(open(RAW / f"{rid}.json"))
    return r["final_text"] if r["ok"] else ""

async def ask(prompt, judge):
    scratch = Path(tempfile.mkdtemp(prefix="v896-g-"))
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
        if r["kind"] != "research": continue
        for judge in MODELS:
            out = G / f"res-{r['run_id']}-{judge}.json"
            if out.exists(): continue
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

async def judge_creative():
    rng = random.Random(896)
    pairs = []
    for f in sorted(glob.glob(str(RAW / "A-K*.json"))):
        a = json.load(open(f))
        if not a["ok"]: continue
        task, model, rep = a["task"], a["model"], a["rep"]
        for other in ("B", "C"):
            op = RAW / f"{other}-{task}-{model}-r{rep}.json"
            if not op.exists(): continue
            o = json.load(open(op))
            if not o["ok"]: continue
            for judge in MODELS:
                flip = rng.random() < 0.5  # True: A shown as Y
                pairs.append((task, model, rep, other, judge, flip, a["final_text"], o["final_text"]))
    jobs = []
    for task, model, rep, other, judge, flip, at, ot in pairs:
        out = G / f"cr-{task}-{model}-r{rep}-A{other}-{judge}.json"
        if out.exists(): continue
        x, y = (ot, at) if flip else (at, ot)
        prompt = (f"Brief given to the author: {CREATIVE[task]['brief']}\n\nFull assignment text:\n{CREATIVE[task]['prompt']}\n\n"
                  f"{JUDGE_CRITERIA}\n\nText X:\n<<<\n{x}\n>>>\n\nText Y:\n<<<\n{y}\n>>>")
        async def one(prompt=prompt, out=out, task=task, model=model, rep=rep, other=other, judge=judge, flip=flip):
            d, res = await ask(prompt, judge)
            w = (d or {}).get("winner")
            ok = w in ("X", "Y")
            a_wins = None if not ok else ((w == "Y") if flip else (w == "X"))
            out.write_text(json.dumps(dict(task=task, author_model=model, rep=rep, other=other, judge=judge, a_shown_as="Y" if flip else "X",
                                           ok=ok, a_wins=a_wins, reason=(d or {}).get("reason"), raw=res.text[:400])))
        jobs.append(one())
    await asyncio.gather(*jobs)

asyncio.run(grade_research() if sys.argv[1] == "research" else judge_creative())
