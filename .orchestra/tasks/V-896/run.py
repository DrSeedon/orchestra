"""V-896 driver. Phase 1: arms A, C and the B rewrite step. Phase 2: B execution from saved rewrites.
Usage (repo root): REP=1 python .orchestra/tasks/V-896/run.py <1|2> [--only runid,...] [--tasks R1,K1]"""
import asyncio, json, os, re, shutil, sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(Path(__file__).parent))
import scripts.wf_adapters as wa
from app.models import resolve_model
from tasks import RESEARCH, CREATIVE, WRAP, C_SUFFIX

OUT = Path("/home/kesha/bench896"); RUNS = OUT / "runs"; LOGS = OUT / "logs"
RAW = Path(__file__).parent / "raw"
for p in (RUNS, LOGS, RAW): p.mkdir(parents=True, exist_ok=True)
MODELS = {"luna": resolve_model("luna"), "sonnet": resolve_model("sonnet")}
SEM = {"luna": asyncio.Semaphore(3), "sonnet": asyncio.Semaphore(3)}
SCOPE = os.environ.get("ORCHESTRA_SCOPE", "")
REP = os.environ.get("REP", "1")
ALL = {**{k: dict(v, kind="research") for k, v in RESEARCH.items()}, **{k: dict(v, kind="creative") for k, v in CREATIVE.items()}}

REWRITE = ("I want a deeper version of this task, not a bigger one. Before rewriting it: (1) say what a top "
           "professional in this field would do here that I'm not asking for; (2) name the rawest material they "
           "would start from instead of what has already been digested for me; (3) name the specific methods and "
           "tools they would use; (4) say what, other than you or me, would show the result is right. Then rewrite "
           "my prompt to ask for exactly that.\n\nTask:\n<<<\n{task}\n>>>\n\nAnswer the four questions, then give "
           "the rewritten prompt in a single fenced block. Keep the same goal and the same final-answer format.")

ONLY = None; TASKSEL = None
_stdout = {}
_orig = wa._run_process
async def _wrapped(argv, prompt, cwd, timeout, *, env=None):
    rc, so, se = await _orig(argv, prompt, cwd, timeout, env=env)
    _stdout[str(cwd)] = so
    return rc, so, se
wa._run_process = _wrapped

def turns(model, raw):
    try:
        if model == "luna":
            n = 0
            for line in raw.splitlines():
                try: row = json.loads(line)
                except Exception: continue
                it = row.get("item") if isinstance(row, dict) else None
                if row.get("type") == "item.completed" and isinstance(it, dict) and it.get("type") not in ("reasoning",):
                    n += 1
            return n
        return json.loads(raw).get("num_turns")
    except Exception:
        return None

def paid(model, u):
    fresh = max(0, u.input_tokens - u.cache_read_tokens - u.cache_create_tokens) if model == "luna" else u.input_tokens
    return fresh + u.cache_create_tokens + u.output_tokens

FLAG = re.compile(r"\.orchestra/tasks|curl |wget |github\.com|web_search\b|/home/kesha/orchestra/(?!\.venv)|V-624|#52\b|#78\b", re.I)

async def call(rid, model, task, prompt, tools):
    work = RUNS / rid
    if work.exists(): shutil.rmtree(work)
    shutil.copytree(OUT / "fx" / task, work)
    async with SEM[model]:
        t0 = time.time()
        res = await wa.run_adapter(WRAP + prompt, model=MODELS[model], cwd=work, timeout=1800, tools=tools,
                                   network=(model == "luna"), mcp=False, billing_mode="subscription")
        dt = time.time() - t0
    raw = _stdout.pop(str(work), "")
    (LOGS / f"{rid}.txt").write_text(raw)
    try:
        wa.persist_turn_usage(result=res, event_id=f"v896:{rid}", session_id="v896", scope=SCOPE, task_id="V-896")
    except Exception as e:
        print("usage persist failed", rid, e, file=sys.stderr)
    return work, res, raw, dt

def record(rid, task, arm, model, stage, res, raw, dt, note):
    row = dict(run_id=rid, task=task, kind=ALL[task]["kind"], arm=arm, model=model, rep=REP, stage=stage, ok=res.ok,
               stop_reason=res.stop_reason, error=res.error[:300], note=note,
               paid_tokens=paid(model, res.usage), output_tokens=res.usage.output_tokens,
               input_tokens=res.usage.input_tokens, cache_read_tokens=res.usage.cache_read_tokens,
               cache_create_tokens=res.usage.cache_create_tokens, turns=turns(model, raw),
               cost_usd_api_equiv=res.cost_usd, seconds=round(dt, 1), contamination_flag=bool(FLAG.search(raw)),
               final_text=res.text)
    (RAW / f"{rid}.json").write_text(json.dumps(row, ensure_ascii=False, indent=1))
    print(rid, "ok" if res.ok else "FAIL", row["paid_tokens"], row["turns"], flush=True)

def skip(rid, task):
    return (RAW / f"{rid}.json").exists() or (ONLY and rid not in ONLY) or (TASKSEL and task not in TASKSEL)

async def exec_run(rid, task, arm, model, prompt):
    if skip(rid, task): return
    work, res, raw, dt = await call(rid, model, task, prompt, "all")
    record(rid, task, arm, model, "exec", res, raw, dt, "" if res.ok else "run failed")

async def rewrite_run(task, model):
    rid = f"B-rw-{task}-{model}-r{REP}"
    if skip(rid, task): return
    work, res, raw, dt = await call(rid, model, task, REWRITE.format(task=ALL[task]["prompt"]), "read")
    blocks = re.findall(r"```(?:\w*)\n(.*?)```", res.text, re.S) if res.ok else []
    record(rid, task, "B", model, "rewrite", res, raw, dt, "ok" if blocks else "no fenced block")
    if blocks:
        (RAW / f"{rid}.rewritten.txt").write_text(blocks[-1].strip())

async def main():
    global ONLY, TASKSEL
    phase = sys.argv[1]
    for i, a in enumerate(sys.argv):
        if a == "--only": ONLY = set(sys.argv[i + 1].split(","))
        if a == "--tasks": TASKSEL = set(sys.argv[i + 1].split(","))
    jobs = []
    for task in ALL:
        for model in MODELS:
            if phase == "1":
                p = ALL[task]["prompt"]
                jobs.append(exec_run(f"A-{task}-{model}-r{REP}", task, "A", model, p))
                jobs.append(exec_run(f"C-{task}-{model}-r{REP}", task, "C", model, p + C_SUFFIX))
                jobs.append(rewrite_run(task, model))
            elif phase == "A":
                jobs.append(exec_run(f"A-{task}-{model}-r{REP}", task, "A", model, ALL[task]["prompt"]))
            else:
                f = RAW / f"B-rw-{task}-{model}-r{REP}.rewritten.txt"
                if f.exists():
                    jobs.append(exec_run(f"B-{task}-{model}-r{REP}", task, "B", model, f.read_text()))
                elif not skip(f"B-{task}-{model}-r{REP}", task):
                    print("no rewrite for", task, model)
    await asyncio.gather(*jobs)
asyncio.run(main())
