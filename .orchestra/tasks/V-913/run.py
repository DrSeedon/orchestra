"""V-906 driver. Usage (repo root): REP=1 python .orchestra/tasks/V-906/run.py <pilot|main> [--only runid,...] [--tasks T1,K1]
pilot = arm A on T tasks only; main = everything (skips runs whose raw/*.json exists)."""
import asyncio, json, os, re, shutil, sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(Path(__file__).parent))
import scripts.wf_adapters as wa
from app.models import resolve_model
from tasks import ROOT as RC, CREATIVE, WRAP, PHRASE

OUT = Path("/home/kesha/bench906"); RUNS = Path("/home/kesha/bench913/runs"); LOGS = Path("/home/kesha/bench913/logs")
RAW = Path(__file__).parent / "raw"
for p in (RUNS, LOGS, RAW): p.mkdir(parents=True, exist_ok=True)
MODELS = {"sonnet": resolve_model("sonnet")}  # V-913: Sonnet only, now with a filtered shell
SEM = {"sonnet": asyncio.Semaphore(3)}
SCOPE = os.environ.get("ORCHESTRA_SCOPE", "")
REP = os.environ.get("REP", "1")
ALL = {**{k: dict(v, group=v["kind"]) for k, v in RC.items()}, **{k: dict(v, group="C") for k, v in CREATIVE.items()}}
CODEWRAP = WRAP
CREWRAP = ("You are working in an empty scratch directory. Work only inside this directory.\n\n")

ONLY = None; TASKSEL = None
_stdout = {}
_orig = wa._run_process
async def _wrapped(argv, prompt, cwd, timeout, *, env=None):
    rc, so, se = await _orig(argv, prompt, cwd, timeout, env=env)
    _stdout[str(cwd)] = so
    return rc, so, se
wa._run_process = _wrapped

def luna_items(raw):
    n = 0; cmds = []
    for line in raw.splitlines():
        try: row = json.loads(line)
        except Exception: continue
        it = row.get("item") if isinstance(row, dict) else None
        if row.get("type") == "item.completed" and isinstance(it, dict) and it.get("type") != "reasoning":
            n += 1
            if it.get("type") == "command_execution": cmds.append(str(it.get("command", ""))[:300])
    return n, cmds

def turns(model, raw):
    try:
        if model == "luna": return luna_items(raw)[0]
        return json.loads(raw).get("num_turns")
    except Exception:
        return None

def paid(model, u):
    fresh = max(0, u.input_tokens - u.cache_read_tokens - u.cache_create_tokens) if model == "luna" else u.input_tokens
    return fresh + u.cache_create_tokens + u.output_tokens

FLAG = re.compile(r"\.orchestra/tasks|curl |wget |github\.com|/home/kesha/orchestra/(?!\.venv)|8239760c|bec4f378|e86fc63f|fbc9e40d|10698051|17a7d398|d1bd9580|495eb220|V-882|V-756", re.I)

def listing(d):
    return {str(p.relative_to(d)) for p in d.rglob("*") if p.is_file() and ".pytest_cache" not in p.parts and "__pycache__" not in p.parts}

async def run_one(rid, task, arm, model):
    if (RAW / f"{rid}.json").exists() or (ONLY and rid not in ONLY) or (TASKSEL and task not in TASKSEL): return
    grp = ALL[task]["group"]
    base = ALL[task]["prompt"]
    prompt = base + (f"\n\n{PHRASE}" if arm == "R" else "")
    prompt = (CREWRAP if grp == "C" else CODEWRAP) + prompt
    work = RUNS / rid
    if work.exists(): shutil.rmtree(work)
    shutil.copytree(OUT / "fx" / task, work)
    before = listing(work)
    async with SEM[model]:
        t0 = time.time()
        res = await wa.run_adapter(prompt, model=MODELS[model], cwd=work, timeout=1800, tools="all",
                                   network=True, mcp=False, billing_mode="subscription")
        dt = time.time() - t0
    raw = _stdout.pop(str(work), "")
    (LOGS / f"{rid}.txt").write_text(raw)
    created = sorted(listing(work) - before)
    try:
        wa.persist_turn_usage(result=res, event_id=f"v913:{rid}", session_id="v913", scope=SCOPE, task_id="V-913")
    except Exception as e:
        print("usage persist failed", rid, e, file=sys.stderr)
    cmds = luna_items(raw)[1] if model == "luna" else []
    row = dict(run_id=rid, task=task, group=grp, arm=arm, model=model, rep=REP, ok=res.ok, stop_reason=res.stop_reason,
               error=res.error[:300], paid_tokens=paid(model, res.usage), output_tokens=res.usage.output_tokens,
               input_tokens=res.usage.input_tokens, cache_read_tokens=res.usage.cache_read_tokens,
               cache_create_tokens=res.usage.cache_create_tokens, turns=turns(model, raw),
               cost_usd_api_equiv=res.cost_usd, seconds=round(dt, 1), contamination_flag=bool(FLAG.search(raw)),
               files_created=[f for f in created if not f.startswith("tests/__") ][:30], commands=cmds, final_text=res.text)
    (RAW / f"{rid}.json").write_text(json.dumps(row, ensure_ascii=False, indent=1))
    print(rid, "ok" if res.ok else "FAIL", row["paid_tokens"], row["turns"], flush=True)

async def main():
    global ONLY, TASKSEL
    phase = sys.argv[1]
    for i, a in enumerate(sys.argv):
        if a == "--only": ONLY = set(sys.argv[i + 1].split(","))
        if a == "--tasks": TASKSEL = set(sys.argv[i + 1].split(","))
    jobs = []
    for task in ALL:
        if ALL[task]["group"] != "T": continue  # V-913: group T only
        for model in MODELS:
            for arm in (("A",) if phase == "pilot" else ("A", "R")):
                jobs.append(run_one(f"{arm}-{task}-{model}-r{REP}", task, arm, model))
    await asyncio.gather(*jobs)
asyncio.run(main())
