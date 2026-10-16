"""V-895 driver. Phase 1: arms A, C and the B rewrite step. Phase 2: B execution from saved rewrites.
Usage: python .orchestra/tasks/V-895/run.py <phase> [--only runid,...]   (run from the repo root)"""
import asyncio, json, os, re, shutil, sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(Path(__file__).parent))
import scripts.wf_adapters as wa
from app.models import resolve_model
from tasks import TASKS, WRAP, C_SUFFIX
from oracle import score

OUT = Path("/home/kesha/bench895"); RUNS = OUT / "runs"; LOGS = OUT / "logs"
RAW = Path(__file__).parent / "raw"
for p in (RUNS, LOGS, RAW): p.mkdir(parents=True, exist_ok=True)
MODELS = {"luna": resolve_model("luna"), "sonnet": resolve_model("sonnet")}
SEM = {"luna": asyncio.Semaphore(3), "sonnet": asyncio.Semaphore(3)}
SCOPE = os.environ.get("ORCHESTRA_SCOPE", "")

REWRITE = ("I want a deeper version of this task, not a bigger one. Before rewriting it: (1) say what a top "
           "professional in this field would do here that I'm not asking for; (2) name the rawest material they "
           "would start from instead of what has already been digested for me; (3) name the specific methods and "
           "tools they would use; (4) say what, other than you or me, would show the result is right. Then rewrite "
           "my prompt to ask for exactly that.\n\nTask:\n<<<\n{task}\n>>>\n\nAnswer the four questions, then give "
           "the rewritten prompt in a single fenced block. Keep the same goal and the same final-answer format.")

ONLY = None
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
    if model == "luna":
        fresh = max(0, u.input_tokens - u.cache_read_tokens - u.cache_create_tokens)
    else:
        fresh = u.input_tokens
    return fresh + u.cache_create_tokens + u.output_tokens

FLAG = re.compile(r"\.orchestra/tasks|curl |wget |github\.com|web_search\b|/home/kesha/orchestra/(?!\.venv)|\bV-(753|814|841|817)\b|CHANGELOG", re.I)

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
        wa.persist_turn_usage(result=res, event_id=f"v895:{rid}", session_id="v895", scope=SCOPE, task_id="V-895")
    except Exception as e:
        print("usage persist failed", rid, e, file=sys.stderr)
    return work, res, raw, dt

def record(rid, task, arm, model, stage, work, res, raw, dt, accepted, note):
    row = dict(run_id=rid, task=task, kind=TASKS[task]["kind"], arm=arm, model=model, stage=stage, ok=res.ok,
               stop_reason=res.stop_reason, error=res.error[:300], accepted=accepted, note=note,
               paid_tokens=paid(model, res.usage), output_tokens=res.usage.output_tokens,
               input_tokens=res.usage.input_tokens, cache_read_tokens=res.usage.cache_read_tokens,
               cache_create_tokens=res.usage.cache_create_tokens, turns=turns(model, raw),
               cost_usd_api_equiv=res.cost_usd, seconds=round(dt, 1), contamination_flag=bool(FLAG.search(raw)),
               final_text=res.text)
    (RAW / f"{rid}.json").write_text(json.dumps(row, ensure_ascii=False, indent=1))
    print(rid, "ok" if res.ok else "FAIL", "acc" if accepted else "-", row["paid_tokens"], row["turns"], flush=True)

async def exec_run(rid, task, arm, model, prompt, stage="exec"):
    if (RAW / f"{rid}.json").exists() or (ONLY and rid not in ONLY): return
    work, res, raw, dt = await call(rid, model, task, prompt, "all")
    if res.ok:
        acc, note = score(task, res.text, work)
    else:
        acc, note = False, "run failed"
    record(rid, task, arm, model, stage, work, res, raw, dt, acc, note)

async def rewrite_run(task, model):
    rid = f"B-rw-{task}-{model}"
    if (RAW / f"{rid}.json").exists() or (ONLY and rid not in ONLY): return
    work, res, raw, dt = await call(rid, model, task, REWRITE.format(task=TASKS[task]["prompt"]), "read")
    blocks = re.findall(r"```(?:\w*)\n(.*?)```", res.text, re.S) if res.ok else []
    note = "ok" if blocks else "no fenced block"
    record(rid, task, "B", model, "rewrite", work, res, raw, dt, False, note)
    if blocks:
        (RAW / f"{rid}.rewritten.txt").write_text(blocks[-1].strip())

async def main():
    phase = sys.argv[1]
    global ONLY
    ONLY = set(sys.argv[3].split(",")) if len(sys.argv) > 3 and sys.argv[2] == "--only" else None
    jobs = []
    for task in TASKS:
        for model in MODELS:
            if phase == "1":
                p = TASKS[task]["prompt"]
                jobs.append(exec_run(f"A-{task}-{model}", task, "A", model, p))
                jobs.append(exec_run(f"C-{task}-{model}", task, "C", model, p + C_SUFFIX))
                jobs.append(rewrite_run(task, model))
            else:
                f = RAW / f"B-rw-{task}-{model}.rewritten.txt"
                if f.exists():
                    jobs.append(exec_run(f"B-{task}-{model}", task, "B", model, f.read_text()))
                else:
                    print("no rewrite for", task, model)
    await asyncio.gather(*jobs)
asyncio.run(main())
