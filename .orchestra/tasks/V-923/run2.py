"""V-923 driver: Luna x N reps per task with early stop, no_edit label, scoring control.
Based on V-914/run.py. Usage (repo root):
  uv run --frozen python .orchestra/tasks/V-923/run2.py control [ids]   # parent red / reference green
  uv run --frozen python .orchestra/tasks/V-923/run2.py run [ids]       # attempts, appends to runs.jsonl
Early stop (per task, counted over attempts WITH an edit): first 3 edit-attempts 3/3 accepted -> ceiling;
0/3 accepted with all three failing on a real test failure (not run error, not no_edit) -> floor.
no_edit = empty diff of app/scripts/pyproject against the fixture; reported separately, not counted as a fail,
retried up to MAX_EXTRA times per task."""
import asyncio, json, os, re, shutil, subprocess, sys, time
from pathlib import Path
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT))
import scripts.wf_adapters as wa
from app.models import resolve_model

OUT = Path("/home/kesha/bench923"); RUNS = OUT / "runs"; FX = OUT / "fx"; SC = OUT / "score"
VENV = OUT / "venv/bin/python"
for p in (RUNS, FX, SC): p.mkdir(parents=True, exist_ok=True)
LOG = HERE / "runs.jsonl"; CTRL = HERE / "control.jsonl"
GIT = "/home/kesha/orchestra/.git"
MODEL = resolve_model("luna"); SEM = asyncio.Semaphore(3)
REPS = int(os.environ.get("REPS", 10)); MAX_EXTRA = 3
SCOPE = os.environ.get("ORCHESTRA_SCOPE", "")
TASKS = {t["id"]: t for t in json.load(open(HERE / "tasks.json"))["tasks"]}
IDX = {r["commit"]: r for r in map(json.loads, open(HERE.parent / "V-914/index.jsonl"))}
WRAP = ("You are working in the current directory, a snapshot of a software project (no git history, no tests). "
        "Work only inside this directory; do not read or list anything outside it.\n\n")
FMT = "\n\nEdit the files in this directory in place. Final answer: two or three sentences saying what you changed."
FLAG = re.compile(r"\.orchestra/tasks|--git-dir|git (?:log|show) |github\.com|/home/kesha/orchestra(?!/worktrees/\S*/runs)|/home/kesha/bench923/(?!runs)", re.I)

_stdout = {}
_orig = wa._run_process
async def _wrapped(argv, prompt, cwd, timeout, *, env=None):
    rc, so, se = await _orig(argv, prompt, cwd, timeout, env=env)
    _stdout[str(cwd)] = so
    return rc, so, se
wa._run_process = _wrapped

def sh(c): return subprocess.run(c, shell=True, capture_output=True, text=True)
def full(commit): return sh(f"git --git-dir={GIT} rev-parse {commit}").stdout.strip()

def paid(u):
    return max(0, u.input_tokens - u.cache_read_tokens - u.cache_create_tokens) + u.cache_create_tokens + u.output_tokens

def turns(raw):
    n = 0
    for line in raw.splitlines():
        try: row = json.loads(line)
        except Exception: continue
        it = row.get("item") if isinstance(row, dict) else None
        if isinstance(row, dict) and row.get("type") == "item.completed" and isinstance(it, dict) and it.get("type") != "reasoning": n += 1
    return n

def build_fixture(tid):
    d = FX / tid
    if d.exists(): return d
    c = TASKS[tid]["commit"]
    d.mkdir(parents=True)
    r = sh(f"git --git-dir={GIT} archive {full(c)}^ app scripts pyproject.toml | tar -x -C {d}")
    assert r.returncode == 0, r.stderr
    return d

def score(key, commit, work):
    """Hidden tests = commit's test files, run in the commit's full tree (git-init'ed, branch main) with work's app/scripts/pyproject."""
    d = SC / key
    if d.exists(): shutil.rmtree(d)
    d.mkdir(parents=True)
    sh(f"git --git-dir={GIT} archive {full(commit)} -- . ':!.orchestra/tasks' ':!artifacts' | tar -x -C {d}")
    for sub in ("app", "scripts"):
        shutil.rmtree(d / sub, ignore_errors=True)
        if (work / sub).exists(): shutil.copytree(work / sub, d / sub)
    if (work / "pyproject.toml").exists(): shutil.copy(work / "pyproject.toml", d / "pyproject.toml")
    sh(f"cd {d} && git init -q && git add -A && git -c user.name=x -c user.email=x@x commit -qm x && git branch -M main")
    tests = " ".join(IDX[commit]["test_files"])
    cmd = (f"cd {d} && PYTHONDONTWRITEBYTECODE=1 nice -n 15 timeout 600 {VENV} -m pytest {tests} "
           f"-q -p no:cacheprovider --no-header --tb=short -p no:randomly 2>&1 | grep -E \"passed|failed|error|no tests ran|^FAILED|^ERROR\" | tail -15")
    r = subprocess.run(["ssh", "-o", "BatchMode=yes", "kesha@localhost", cmd], capture_output=True, text=True)
    out = r.stdout
    m = re.search(r"(\d+) passed", out); f = re.search(r"(\d+) failed", out); e = re.search(r"(\d+) error", out)
    ok = bool(m) and not f and not e and "no tests ran" not in out
    shutil.rmtree(d, ignore_errors=True)
    return ok, out[-1200:]

def diff_of(fx, work):
    return sh(f"diff -ru {fx} {work} --exclude=__pycache__ --exclude=.pytest_cache").stdout

async def attempt(tid, rep):
    spec = TASKS[tid]; work = RUNS / f"{tid}_{rep}"
    if work.exists(): shutil.rmtree(work)
    fx = build_fixture(tid); shutil.copytree(fx, work)
    async with SEM:
        t0 = time.time()
        res = await wa.run_adapter(WRAP + spec["prompt"] + FMT, model=MODEL, cwd=work, timeout=1800, tools="all",
                                   network=True, mcp=False, billing_mode="subscription")
        dt = time.time() - t0
    raw = _stdout.pop(str(work), "")
    try:
        wa.persist_turn_usage(result=res, event_id=f"v923:{tid}:{rep}", session_id="v923", scope=SCOPE, task_id="V-923")
    except Exception as ex:
        print("usage persist failed", tid, ex, file=sys.stderr)
    patch = diff_of(fx, work)
    no_edit = patch.strip() == ""
    if res.ok and not no_edit:
        ok, tail = await asyncio.to_thread(score, f"{tid}_{rep}", spec["commit"], work)
    else:
        ok, tail = False, ("run failed" if not res.ok else "no_edit")
    (OUT / "patches").mkdir(exist_ok=True)
    (OUT / "patches" / f"{tid}_{rep}.patch").write_text(patch)
    u = res.usage
    row = dict(task=tid, rep=rep, commit=spec["commit"], run_ok=res.ok, no_edit=no_edit, accepted=ok, error=res.error[:300],
               stop_reason=res.stop_reason, test_tail=tail, paid_tokens=paid(u), output_tokens=u.output_tokens,
               input_tokens=u.input_tokens, cache_read_tokens=u.cache_read_tokens, cache_create_tokens=u.cache_create_tokens,
               turns=turns(raw), patch_lines=patch.count("\n"), seconds=round(dt, 1), contamination_flag=bool(FLAG.search(raw)),
               cost_usd_api_equiv=res.cost_usd, final_text=res.text[:800])
    with open(LOG, "a") as f: f.write(json.dumps(row, ensure_ascii=False) + "\n")
    shutil.rmtree(work, ignore_errors=True)
    print(tid, rep, "ACC" if ok else ("NOEDIT" if no_edit else "-"), row["paid_tokens"], flush=True)
    return row

def load_rows():
    return [json.loads(l) for l in open(LOG)] if LOG.exists() else []

def early(rows):
    ed = [r for r in rows if r["run_ok"] and not r["no_edit"]]
    if len(ed) < 3: return None
    first = ed[:3]
    if all(r["accepted"] for r in first): return "ceiling"
    if not any(r["accepted"] for r in first): return "floor"
    return None

async def run_task(tid):
    rows = [r for r in load_rows() if r["task"] == tid]
    rep = max([r["rep"] for r in rows], default=0)
    while True:
        rows = [r for r in load_rows() if r["task"] == tid]
        ed = [r for r in rows if r["run_ok"] and not r["no_edit"]]
        noed = [r for r in rows if r["no_edit"]]
        stop = early(rows)
        if stop or len(ed) >= REPS or len(noed) > MAX_EXTRA or len(rows) >= REPS + MAX_EXTRA + 2: break
        rep += 1
        # first wave runs 3 attempts concurrently only through the semaphore, decision is taken after
        await attempt(tid, rep)
    rows = [r for r in load_rows() if r["task"] == tid]
    print("DONE", tid, early(rows) or "full", sum(r["accepted"] for r in rows), len(rows), flush=True)

async def control(ids):
    for tid in ids:
        c = TASKS[tid]["commit"]
        ref = OUT / "ref" / tid
        if not ref.exists():
            ref.mkdir(parents=True); sh(f"git --git-dir={GIT} archive {full(c)} app scripts pyproject.toml | tar -x -C {ref}")
        base_ok, bt = await asyncio.to_thread(score, tid + "_b", c, build_fixture(tid))
        ref_ok, rt = await asyncio.to_thread(score, tid + "_r", c, ref)
        row = dict(task=tid, commit=c, parent_red=not base_ok, reference_green=ref_ok, base_tail=bt[-400:], ref_tail=rt[-400:])
        with open(CTRL, "a") as f: f.write(json.dumps(row) + "\n")
        print("CONTROL", tid, "parent_red" if not base_ok else "PARENT_GREEN", "ref_green" if ref_ok else "REF_RED", flush=True)

async def main():
    mode = sys.argv[1]; ids = sys.argv[2].split(",") if len(sys.argv) > 2 else list(TASKS)
    if mode == "control":
        await asyncio.gather(*(control(ids[i::3]) for i in range(3)))
    else:
        await asyncio.gather(*(run_task(t) for t in ids))
asyncio.run(main())
