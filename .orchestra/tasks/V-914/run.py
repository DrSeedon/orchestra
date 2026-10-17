"""V-914 step 2 driver: arm A (statement only), Luna, 1 rep. Based on V-895/run.py (wf_adapters).
Usage (repo root): uv run --frozen python .orchestra/tasks/V-914/run.py [--only P01,P02]"""
import asyncio, json, os, re, shutil, subprocess, sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(Path(__file__).parent))
import scripts.wf_adapters as wa
from app.models import resolve_model
from tasks import T, WRAP

OUT = Path("/home/kesha/bench914"); RUNS = OUT / "runs"; FX = OUT / "fx"; SC = OUT / "score"
RAW = Path(__file__).parent / "raw"
for p in (RUNS, FX, SC, RAW): p.mkdir(parents=True, exist_ok=True)
GIT = "/home/kesha/orchestra/.git"
MODEL = resolve_model("luna"); SEM = asyncio.Semaphore(3)
SCOPE = os.environ.get("ORCHESTRA_SCOPE", "")
IDX = {r["commit"]: r for r in map(json.loads, open(Path(__file__).parent / "index.jsonl"))}
ONLY = set(sys.argv[2].split(",")) if len(sys.argv) > 2 and sys.argv[1] == "--only" else None
FLAG = re.compile(r"\.orchestra/tasks|--git-dir|git (?:log|show) |curl |wget |github\.com|/home/kesha/orchestra/(?!\.venv)|CHANGELOG", re.I)

_stdout = {}
_orig = wa._run_process
async def _wrapped(argv, prompt, cwd, timeout, *, env=None):
    rc, so, se = await _orig(argv, prompt, cwd, timeout, env=env)
    _stdout[str(cwd)] = so
    return rc, so, se
wa._run_process = _wrapped

def sh(c): return subprocess.run(c, shell=True, capture_output=True, text=True)

def turns(raw):
    n = 0
    for line in raw.splitlines():
        try: row = json.loads(line)
        except Exception: continue
        it = row.get("item") if isinstance(row, dict) else None
        if row.get("type") == "item.completed" and isinstance(it, dict) and it.get("type") != "reasoning": n += 1
    return n

def paid(u):
    return max(0, u.input_tokens - u.cache_read_tokens - u.cache_create_tokens) + u.cache_create_tokens + u.output_tokens

def build_fixture(tid, commit):
    d = FX / tid
    if d.exists(): return d
    full = sh(f"git --git-dir={GIT} rev-parse {commit}").stdout.strip()
    d.mkdir(parents=True)
    r = sh(f"git --git-dir={GIT} archive {full}^ app scripts pyproject.toml | tar -x -C {d}")
    assert r.returncode == 0, r.stderr
    return d

def score(tid, commit, work):
    """Hidden tests = the commit's test files, run in the commit's full tree with the model's app/scripts/pyproject."""
    full = sh(f"git --git-dir={GIT} rev-parse {commit}").stdout.strip()
    d = SC / tid
    if d.exists(): shutil.rmtree(d)
    d.mkdir(parents=True)
    sh(f"git --git-dir={GIT} archive {full} -- . ':!.orchestra/tasks' ':!artifacts' | tar -x -C {d}")
    for sub in ("app", "scripts"):
        shutil.rmtree(d / sub, ignore_errors=True)
        if (work / sub).exists(): shutil.copytree(work / sub, d / sub)
    if (work / "pyproject.toml").exists(): shutil.copy(work / "pyproject.toml", d / "pyproject.toml")
    tests = " ".join(IDX[commit]["test_files"])
    cmd = (f"cd {d} && PYTHONDONTWRITEBYTECODE=1 nice -n 15 timeout 600 /tmp/v914/venv/bin/python -m pytest {tests} "
           f"-q -p no:cacheprovider --no-header --tb=short -p no:randomly 2>&1 | tail -40")
    r = subprocess.run(["ssh", "-o", "BatchMode=yes", "kesha@localhost", cmd], capture_output=True, text=True)
    out = r.stdout
    m = re.search(r"(\d+) passed", out); f = re.search(r"(\d+) failed", out); e = re.search(r"(\d+) error", out)
    ok = bool(m) and not f and not e and "no tests ran" not in out
    return ok, out[-1500:]

async def run_one(tid):
    if (RAW / f"{tid}.json").exists() or (ONLY and tid not in ONLY): return
    spec = T[tid]; commit = spec["commit"]
    work = RUNS / tid
    if work.exists(): shutil.rmtree(work)
    shutil.copytree(build_fixture(tid, commit), work)
    async with SEM:
        t0 = time.time()
        res = await wa.run_adapter(WRAP + spec["prompt"], model=MODEL, cwd=work, timeout=1800, tools="all",
                                   network=True, mcp=False, billing_mode="subscription")
        dt = time.time() - t0
    raw = _stdout.pop(str(work), "")
    try:
        wa.persist_turn_usage(result=res, event_id=f"v914:{tid}", session_id="v914", scope=SCOPE, task_id="V-914")
    except Exception as ex:
        print("usage persist failed", tid, ex, file=sys.stderr)
    patch = sh(f"diff -ru {FX/tid} {work} --exclude=__pycache__").stdout
    (RAW / f"{tid}.patch").write_text(patch)
    (RAW / f"{tid}.log.txt").write_text(raw)
    if res.ok:
        ok, tail = await asyncio.to_thread(score, tid, commit, work)
    else:
        ok, tail = False, "run failed"
    u = res.usage
    row = dict(task=tid, commit=commit, name_req=spec["name_req"], ok=res.ok, stop_reason=res.stop_reason, error=res.error[:300],
               accepted=ok, test_tail=tail, paid_tokens=paid(u), output_tokens=u.output_tokens, input_tokens=u.input_tokens,
               cache_read_tokens=u.cache_read_tokens, cache_create_tokens=u.cache_create_tokens, turns=turns(raw),
               patch_lines=patch.count("\n"), seconds=round(dt, 1), contamination_flag=bool(FLAG.search(raw)),
               cost_usd_api_equiv=res.cost_usd, final_text=res.text)
    (RAW / f"{tid}.json").write_text(json.dumps(row, ensure_ascii=False, indent=1))
    print(tid, "ok" if res.ok else "FAIL", "ACC" if ok else "-", row["paid_tokens"], row["turns"], flush=True)

async def control(ids):
    for tid in ids:
        commit = T[tid]["commit"]; full = sh(f"git --git-dir={GIT} rev-parse {commit}").stdout.strip()
        ref = OUT / "ref" / tid
        if not ref.exists():
            ref.mkdir(parents=True); sh(f"git --git-dir={GIT} archive {full} app scripts pyproject.toml | tar -x -C {ref}")
        base_ok, _ = await asyncio.to_thread(score, tid + "_b", commit, build_fixture(tid, commit))
        ref_ok, tail = await asyncio.to_thread(score, tid + "_r", commit, ref)
        print("CONTROL", tid, "baseline_pass" if base_ok else "baseline_fail", "ref_pass" if ref_ok else "ref_FAIL", flush=True)

async def main():
    if sys.argv[1:2] == ["--control"]:
        await asyncio.gather(*(control(c) for c in (list(T)[i::3] for i in range(3)))); return
    await asyncio.gather(*(run_one(t) for t in T))
asyncio.run(main())
