#!/usr/bin/env python3
"""V-775 advisor experiment: minimal bash-tool agent loop on Messages API, optional advisor tool.
Usage: agent.py <label> <base> <oracle> <task_file> <executor> <effort> <advisor|none> "<oracle test files>"
Writes data/v775/runs/<label>/{result.json,oracle.txt}. Key read from .env, never printed."""
import json, os, subprocess, sys, time
from pathlib import Path
import anthropic

label, base, oracle, task_file, executor, effort, advisor, ofiles = sys.argv[1:9]
REPO = "/home/kesha/orchestra"
ROOT = Path("/home/kesha/orchestra/worktrees/home-kesha-orchestra/research-anthropic-api/data/v775")
PY = "/opt/orchestra/runtimes/20260817-b0b72d65-py312-rag-v2/bin/python"
out = ROOT / "runs" / label; out.mkdir(parents=True, exist_ok=True)
if (out / "result.json").exists(): sys.exit(0)
wt = ROOT / "wt" / label
if wt.exists():
    subprocess.run(["trash", str(wt)])
wt.parent.mkdir(parents=True, exist_ok=True)
subprocess.run(["git", "-C", REPO, "branch", "-f", f"v775-{label}", base], check=True)
subprocess.run(["git", "clone", "-q", "--no-local", "--single-branch", "--branch", f"v775-{label}", REPO, str(wt)], check=True)
subprocess.run(["git", "-C", REPO, "branch", "-D", f"v775-{label}"], capture_output=True)
subprocess.run(["git", "-C", str(wt), "remote", "remove", "origin"])

key = next(l.split("=", 1)[1].strip().strip("\"'") for l in Path(REPO, ".env").read_text().splitlines()
           if l.startswith("ORCHESTRA_CLAUDE_CREDIT_API_KEY="))
client = anthropic.Anthropic(api_key=key, max_retries=3, timeout=900)

PRICE = {  # in, out, cache write 5m, cache read  ($/MTok); haiku has >100k tier
    "claude-haiku-5-5": ((0.10, 0.50, 0.125, 0.01), (0.50, 2.50, 0.625, 0.05)),
    "claude-sonnet-5-5": ((2, 10, 2.5, 0.10),) * 2,
    "claude-opus-5-5": ((4, 20, 5, 0.20),) * 2,
}
def cost(model, u):
    lo, hi = PRICE[model]
    n = u["input_tokens"] + u.get("cache_read_input_tokens", 0) + u.get("cache_creation_input_tokens", 0)
    p = hi if n > 100_000 else lo
    return (u["input_tokens"] * p[0] + u["output_tokens"] * p[1]
            + u.get("cache_creation_input_tokens", 0) * p[2] + u.get("cache_read_input_tokens", 0) * p[3]) / 1e6

SYSTEM = f"""You are a software engineer working in a git repository at {wt} (your cwd). You have one tool, bash.
Python with the project's dependencies: {PY} (run tests as `{PY} -m pytest -q -p no:cacheprovider <files>`).
Do the task fully, run relevant tests yourself, do not commit. Never run the full test suite; run only specific test files.
When finished, reply with a short final summary."""
if advisor != "none":
    SYSTEM += """

You have access to an `advisor` tool backed by a stronger reviewer model. It takes NO parameters — when you call advisor(), your entire conversation history is automatically forwarded.
Call advisor BEFORE substantive work — before writing, before committing to an interpretation. If the task requires orientation first (finding files, reading code), do that, then call advisor.
Also call advisor: when you believe the task is complete (after making the deliverable durable by writing files), when stuck, and when considering a change of approach.
On tasks longer than a few steps, call advisor at least once before committing to an approach and once before declaring done.
Give the advice serious weight; if it fails empirically or you have primary-source evidence against it, adapt."""

tools = [{"name": "bash", "description": "Run a bash command in the repo. Output truncated to 12000 chars.",
          "input_schema": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}}]
betas = []
if advisor != "none":
    tools.append({"type": "advisor_20260301", "name": "advisor", "model": advisor})
    betas.append("advisor-tool-2026-03-01")

def run_bash(cmd):
    try:
        r = subprocess.run(["bash", "-c", cmd], cwd=wt, capture_output=True, text=True, timeout=300)
        s = r.stdout + r.stderr
    except subprocess.TimeoutExpired:
        s = "TIMEOUT 300s"
    return s[:12000] + ("\n...[truncated]" if len(s) > 12000 else "")

messages = [{"role": "user", "content": Path(task_file).read_text()}]
log, total, nadv, turns = [], 0.0, 0, 0
t0 = time.time()
while turns < 80:
    turns += 1
    kw = dict(model=executor, max_tokens=24000, system=SYSTEM, tools=tools, messages=messages,
              output_config={"effort": effort}, extra_body={"cache_control": {"type": "ephemeral"}})
    r = client.beta.messages.create(betas=betas, **kw) if betas else client.messages.create(**kw)
    u = r.usage.model_dump()
    its = u.get("iterations") or [dict(u, type="message")]
    for it in its:
        m = it.get("model") or executor
        c = cost(m, it)
        total += c
        if it.get("type") == "advisor_message": nadv += 1
        log.append({"turn": turns, "type": it.get("type"), "model": m, "in": it["input_tokens"], "out": it["output_tokens"],
                    "cr": it.get("cache_read_input_tokens", 0), "cw": it.get("cache_creation_input_tokens", 0), "usd": round(c, 5)})
    messages.append({"role": "assistant", "content": [b.model_dump(exclude_none=True) for b in r.content]})
    if r.stop_reason == "pause_turn":
        continue
    calls = [b for b in r.content if b.type == "tool_use"]
    if not calls:
        break
    res = [{"type": "tool_result", "tool_use_id": b.id, "content": run_bash(b.input.get("command", ""))} for b in calls]
    messages.append({"role": "user", "content": res})
secs = round(time.time() - t0)

subprocess.run(["git", "-C", str(wt), "add", "-A"], capture_output=True)
(out / "diff.patch").write_text(subprocess.run(["git", "-C", str(wt), "diff", "--cached", base], capture_output=True, text=True).stdout)
for f in ofiles.split():
    d = subprocess.run(["git", "-C", REPO, "show", f"{oracle}:{f}"], capture_output=True, text=True).stdout
    (wt / f).write_text(d)
tests = " ".join(f for f in ofiles.split() if f.startswith("tests/") and f.endswith(".py"))
o = subprocess.run(f"{PY} -m pytest -q -p no:cacheprovider {tests}", shell=True, cwd=wt, capture_output=True, text=True)
(out / "oracle.txt").write_text(o.stdout + o.stderr)
(out / "result.json").write_text(json.dumps({"label": label, "executor": executor, "effort": effort, "advisor": advisor,
    "usd": round(total, 4), "advisor_calls": nadv, "turns": turns, "seconds": secs, "iterations": log}, indent=1))
print(label, "usd", round(total, 4), "adv", nadv, "turns", turns, "sec", secs, "|", (o.stdout.strip().splitlines() or [""])[-1])
