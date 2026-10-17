"""V-910 arm A driver. Usage (repo root of the worktree): REP=1 python .orchestra/tasks/V-910/run_a.py <pilot|main> [--only Q01,...] [--models luna,sonnet]
Raw results: raw_a/<qid>-<model>-r<rep>.json (existing files are skipped)."""
import asyncio, json, os, re, shutil, subprocess, sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(Path(__file__).parent))
import scripts.wf_adapters as wa
from app.models import resolve_model
from app.kb_index import kb_index_block
from questions import Q

CORPUS = Path("/home/kesha/bench910/corpus"); RUNS = Path("/home/kesha/bench910/runs"); RUNS.mkdir(exist_ok=True)
RAW = Path(__file__).parent / "raw_a"; RAW.mkdir(exist_ok=True)
MODELS = {"luna": resolve_model("luna"), "sonnet": resolve_model("sonnet")}
SEM = {"luna": asyncio.Semaphore(3), "sonnet": asyncio.Semaphore(3)}
REP = os.environ.get("REP", "1"); SCOPE = os.environ.get("ORCHESTRA_SCOPE", "")
INDEX = kb_index_block(str(CORPUS))
PROMPT = """You are an agent in a project whose accumulated knowledge lives in markdown files: topic notes in .orchestra/kb/ and task reports in .orchestra/tasks/<id>/report.md. Your working directory is the project root.

{index}

Use the injected topic index, then search exact symbols, errors or distinctive terms in the knowledge base and task reports:
rg -n -i -F -e '<symbol>' -e '<symptom>' .orchestra/kb .orchestra/tasks
Read the matching section with its conditions and evidence.

Question (the wording may differ from the wording of the record): {q}

Find which file or files hold the answer and answer briefly from them. Limits: at most 3 search calls in total (rg / grep / Grep / Glob / ls / find; each call counts as one). Opening and reading a file you have already located (cat / sed / Read) is not a search call and is unlimited. Do not use anything outside this directory.
Finish with exactly two lines:
FILES: <path1>[, <path2>]   (at most 2 paths relative to the project root)
ANSWER: <1-3 sentences>"""
FLAG = re.compile(r"V-910|bench-kb-search|questions\.py|reference\.json|/home/kesha/orchestra|/home/kesha/bench910/(?!runs)", re.I)
SEARCH = re.compile(r"(^|[\s|;&(`'\"])(rg|grep|egrep|fgrep|find|fd|ls|ag|ack|tree)(\s|$)")

_stdout = {}
_orig = wa._run_process
async def _wrapped(argv, prompt, cwd, timeout, *, env=None):
    argv = list(argv)
    is_claude = "--output-format" in argv
    if is_claude:
        argv[argv.index("--output-format") + 1] = "stream-json"; argv.append("--verbose")
    rc, so, se = await _orig(argv, prompt, cwd, timeout, env=env)
    _stdout[str(cwd)] = so
    if is_claude and rc == 0:
        for l in reversed(so.splitlines()):
            try: row = json.loads(l)
            except Exception: continue
            if isinstance(row, dict) and row.get("type") == "result": so = l; break
    return rc, so, se
wa._run_process = _wrapped

def trace(model, raw):
    """-> (search_calls, read_calls, commands) from the raw stream."""
    s = r = 0; cmds = []
    for line in raw.splitlines():
        try: row = json.loads(line)
        except Exception: continue
        if model == "luna":
            it = row.get("item") if isinstance(row, dict) else None
            if row.get("type") == "item.completed" and isinstance(it, dict) and it.get("type") == "command_execution":
                c = str(it.get("command", "")); cmds.append(c[:300])
                if SEARCH.search(c): s += 1
                else: r += 1
        else:
            if row.get("type") == "assistant":
                for b in (row.get("message") or {}).get("content") or []:
                    if isinstance(b, dict) and b.get("type") == "tool_use":
                        n = b.get("name", ""); cmds.append(f"{n} {json.dumps(b.get('input'), ensure_ascii=False)[:250]}")
                        if n in ("Grep", "Glob"): s += 1
                        else: r += 1
    return s, r, cmds

def paid(model, u):
    fresh = max(0, u.input_tokens - u.cache_read_tokens - u.cache_create_tokens) if model == "luna" else u.input_tokens
    return fresh + u.cache_create_tokens + u.output_tokens

def parse_files(text):
    m = re.search(r"FILES:\s*(.+)", text)
    if not m: return []
    return [x.strip().strip("`*") .removeprefix("./") for x in re.split(r"[,\s]+(?=\S)", m.group(1).strip()) if x.strip().strip("`*")][:2]

async def run_one(q, model):
    rid = f"{q['id']}-{model}-r{REP}"
    if (RAW / f"{rid}.json").exists() or (ONLY and q["id"] not in ONLY) or model not in MODELSEL: return
    work = RUNS / rid
    if work.exists(): shutil.rmtree(work)
    subprocess.run(["cp", "-a", str(CORPUS), str(work)], check=True)
    prompt = PROMPT.format(index=INDEX, q=q["q"])
    async with SEM[model]:
        t0 = time.time()
        res = await wa.run_adapter(prompt, model=MODELS[model], cwd=work, timeout=900, tools=("all" if model == "luna" else "read"),
                                   network=(model == "luna"), mcp=False, billing_mode="subscription")
        dt = time.time() - t0
    raw = _stdout.pop(str(work), "")
    s, r, cmds = trace(model, raw)
    try:
        wa.persist_turn_usage(result=res, event_id=f"v910:{rid}", session_id="v910", scope=SCOPE, task_id="V-910")
    except Exception as e:
        print("usage persist failed", rid, e, file=sys.stderr)
    row = dict(run_id=rid, qid=q["id"], kind=q["kind"], model=model, rep=REP, ok=res.ok, stop_reason=res.stop_reason,
               error=res.error[:300], search_calls=s, read_calls=r, files=parse_files(res.text), final_text=res.text,
               paid_tokens=paid(model, res.usage), output_tokens=res.usage.output_tokens, input_tokens=res.usage.input_tokens,
               cache_read_tokens=res.usage.cache_read_tokens, cache_create_tokens=res.usage.cache_create_tokens,
               cost_usd_api_equiv=res.cost_usd, seconds=round(dt, 1), contamination_flag=bool(FLAG.search(" ".join(cmds).replace(str(work), "")) or re.search(r"(^|[\s'\"=])(\.\./|~/|/(home|opt|tmp|etc|var|usr)/)", " ".join(cmds).replace(str(work), "")) or '"web_search"' in raw),
               commands=cmds)
    (RAW / f"{rid}.json").write_text(json.dumps(row, ensure_ascii=False, indent=1))
    (RUNS / f"{rid}.stream.txt").write_text(raw)
    shutil.rmtree(work, ignore_errors=True)
    print(rid, "ok" if res.ok else "FAIL", s, r, row["paid_tokens"], row["files"], flush=True)

ONLY = None; MODELSEL = {"luna", "sonnet"}
async def main():
    global ONLY, MODELSEL
    phase = sys.argv[1]
    for i, a in enumerate(sys.argv):
        if a == "--only": ONLY = set(sys.argv[i + 1].split(","))
        if a == "--models": MODELSEL = set(sys.argv[i + 1].split(","))
    qs = [q for q in Q if phase != "pilot" or q["id"] in ("K01", "R05", "S01")]
    await asyncio.gather(*[run_one(q, m) for q in qs for m in MODELS])
asyncio.run(main())
