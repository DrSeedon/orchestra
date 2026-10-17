"""V-906 grading. T/K: both models grade each answer against the reference (blind to arm); cross-model grade is the primary one.
C: both models judge each (A,R) pair in seeded random order (blind to arm).
Usage (repo root): python .orchestra/tasks/V-906/grade.py <rc|creative>"""
import asyncio, glob, json, random, re, sys, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(Path(__file__).parent))
import scripts.wf_adapters as wa
from app.models import resolve_model
from tasks import ROOT as RC, CREATIVE, JUDGE_CRITERIA, GRADER_PROMPT
H = Path(__file__).parent; RAW = H / "raw"; G = H / "grades"; G.mkdir(exist_ok=True)
MODELS = {"luna": resolve_model("luna"), "sonnet": resolve_model("sonnet")}
SEM = asyncio.Semaphore(4)

async def ask(prompt, judge):
    scratch = Path(tempfile.mkdtemp(prefix="v913-g-"))
    async with SEM:
        res = await wa.run_adapter(prompt, model=MODELS[judge], cwd=scratch, timeout=600, tools="read",
                                   network=False, mcp=False, billing_mode="subscription")
    m = re.search(r"\{.*\}", res.text or "", re.S)
    try: return json.loads(m.group(0)), res
    except Exception: return None, res

def execs():
    for f in sorted(glob.glob(str(RAW / "*.json"))):
        r = json.load(open(f))
        if r["ok"]: yield r

async def grade_rc():
    jobs = []
    for r in execs():
        if r["group"] == "C": continue
        ref = RC[r["task"]]
        for judge in MODELS:
            out = G / f"rc-{r['run_id']}-{judge}.json"
            if out.exists(): continue
            prompt = (GRADER_PROMPT + f"\n\nReference root cause P: {ref['P']}\n\nSupporting facts S:\n"
                      + "\n".join(f"{i+1}. {s}" for i, s in enumerate(ref["S"]))
                      + f"\n\nFalse version D: {ref['D']}\n\nAnswer to grade:\n<<<\n{r['final_text']}\n>>>")
            async def one(prompt=prompt, judge=judge, out=out, r=r, n=len(ref["S"])):
                d, res = await ask(prompt, judge)
                ok = isinstance(d, dict) and isinstance(d.get("primary"), (int, float)) and isinstance(d.get("supporting"), list)
                out.write_text(json.dumps(dict(run_id=r["run_id"], judge=judge, ok=ok, grade=d if ok else None, raw=(res.text or "")[:500])))
            jobs.append(one())
    await asyncio.gather(*jobs)

async def judge_creative():
    rng = random.Random(906)
    pairs = []
    for f in sorted(glob.glob(str(RAW / "A-C*.json"))):
        a = json.load(open(f))
        if not a["ok"]: continue
        task, model, rep = a["task"], a["model"], a["rep"]
        op = RAW / f"R-{task}-{model}-r{rep}.json"
        if not op.exists(): continue
        o = json.load(open(op))
        if not o["ok"]: continue
        for judge in MODELS:
            pairs.append((task, model, rep, judge, rng.random() < 0.5, a["final_text"], o["final_text"]))
    jobs = []
    for task, model, rep, judge, flip, at, ot in pairs:
        out = G / f"cr-{task}-{model}-r{rep}-AR-{judge}.json"
        if out.exists(): continue
        x, y = (ot, at) if flip else (at, ot)
        prompt = (f"Brief given to the author: {CREATIVE[task]['brief']}\n\nFull assignment text:\n{CREATIVE[task]['prompt']}\n\n"
                  f"{JUDGE_CRITERIA}\n\nText X:\n<<<\n{x}\n>>>\n\nText Y:\n<<<\n{y}\n>>>")
        async def one(prompt=prompt, out=out, task=task, model=model, rep=rep, judge=judge, flip=flip):
            d, res = await ask(prompt, judge)
            w = (d or {}).get("winner")
            ok = w in ("X", "Y")
            a_wins = None if not ok else ((w == "Y") if flip else (w == "X"))
            out.write_text(json.dumps(dict(task=task, author_model=model, rep=rep, judge=judge, a_shown_as="Y" if flip else "X",
                                           ok=ok, a_wins=a_wins, reason=(d or {}).get("reason"), raw=(res.text or "")[:400])))
        jobs.append(one())
    await asyncio.gather(*jobs)

asyncio.run(grade_rc() if sys.argv[1] == "rc" else judge_creative())
