#!/usr/bin/env python3
"""#498 rows 3/4/10: identical closed ticket on gpt-6-astra vs gpt-5.6-sol.

Design notes (why it is shaped this way):
 - Runs are INTERLEAVED A/B/A/B (wall-clock metrics are load-dependent).
 - A raw rate-limit snapshot is taken after EVERY run, so a move of
   codex.primary is attributable to the model that just ran (row 3).
 - codex_bengalfox (Spark) is recorded in every snapshot as the negative
   control: it must stay flat, proving the snapshot can tell buckets apart.
 - Each run gets a FRESH copy of the ticket, so every run starts genuinely red.
 - The oracle is verified by THIS script, not by the model's own claim, and the
   test file is hashed before/after to detect oracle mutation.
"""
import hashlib
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

BASE = Path("/tmp/astra498")
SRC = BASE / "ticket_src"
OUT = BASE / "ab"
OUT.mkdir(exist_ok=True)

PROMPT = """Ticket T1 - fix humanize_ranges so its acceptance test passes.

Files: rangefmt.py
Test (immutable): python3 -m pytest test_rangefmt.py -q
AC: that command exits 0 with every test passing.

The acceptance test is immutable: NEVER edit, delete, rename, skip, xfail, or weaken it.
Do not modify test_rangefmt.py, any fixture, any conftest.py, or any test configuration.
The spec is the module docstring in rangefmt.py.

Implement the fix in rangefmt.py, run the test command, and finish by reporting DONE with the final test output."""

MODELS = ["gpt-6-astra", "gpt-5.6-sol"]
RUNS = 3


def snapshot(label):
    p = subprocess.run(["python3", str(BASE / "ratelimits.py"), label],
                       capture_output=True, text=True, timeout=90)
    try:
        d = json.loads(p.stdout)
    except Exception:
        return {"label": label, "error": p.stdout[-400:] + p.stderr[-400:]}
    r = (d.get("result") or {}).get("rateLimitsByLimitId") or {}
    return {
        "label": label,
        "fetched_at": d.get("fetched_at"),
        "limit_ids": sorted(r.keys()),
        "codex_primary_used_pct": ((r.get("codex") or {}).get("primary") or {}).get("usedPercent"),
        "codex_primary_resets_at": ((r.get("codex") or {}).get("primary") or {}).get("resetsAt"),
        "spark_primary_used_pct": ((r.get("codex_bengalfox") or {}).get("primary") or {}).get("usedPercent"),
        "spark_secondary_used_pct": ((r.get("codex_bengalfox") or {}).get("secondary") or {}).get("usedPercent"),
    }


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def one_run(model, idx):
    work = OUT / f"work_{model.replace('.', '_')}_{idx}"
    if work.exists():
        shutil.rmtree(work)
    shutil.copytree(SRC, work)
    test_sha_before = sha(work / "test_rangefmt.py")

    cmd = [
        "codex", "exec", "--skip-git-repo-check", "--ignore-user-config",
        "-C", str(work), "-s", "workspace-write", "--json",
        "-c", "model_reasoning_effort=high", "-c", "approval_policy=never",
        "-m", model, PROMPT,
    ]
    t0 = time.time()
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=900,
                       stdin=subprocess.DEVNULL)
    wall = time.time() - t0

    events = []
    for line in p.stdout.splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                events.append(json.loads(line))
            except Exception:
                pass
    (OUT / f"events_{model}_{idx}.jsonl").write_text(
        "\n".join(json.dumps(e) for e in events))

    usage = {}
    item_types = {}
    messages = []
    for e in events:
        if e.get("type") == "turn.completed":
            usage = e.get("usage") or {}
        if e.get("type") == "item.completed":
            it = e.get("item") or {}
            item_types[it.get("type")] = item_types.get(it.get("type"), 0) + 1
            if it.get("type") == "agent_message":
                messages.append(it.get("text") or "")

    # independent verification of the AC, by us, not by the model's claim
    v = subprocess.run(["python3", "-m", "pytest", "test_rangefmt.py", "-q"],
                       cwd=work, capture_output=True, text=True, timeout=120)
    test_sha_after = sha(work / "test_rangefmt.py")

    final = messages[-1] if messages else ""
    return {
        "model": model,
        "run": idx,
        "rc": p.returncode,
        "wall_s": round(wall, 1),
        "loadavg": os.getloadavg()[0],
        "usage": usage,
        "item_types": item_types,
        "agent_messages": len(messages),
        "final_message_chars": len(final),
        "final_message_tail": final[-600:],
        "ac_green": v.returncode == 0,
        "ac_output_tail": v.stdout.strip().splitlines()[-1] if v.stdout.strip() else "",
        "oracle_untouched": test_sha_before == test_sha_after,
        "stderr_tail": p.stderr[-300:],
    }


results = []
snaps = [snapshot("t0_before_all")]
print(json.dumps(snaps[-1]), flush=True)

for i in range(RUNS):
    for model in MODELS:
        r = one_run(model, i)
        results.append(r)
        print(json.dumps({k: v for k, v in r.items() if k != "final_message_tail"}), flush=True)
        s = snapshot(f"after_{model}_run{i}")
        snaps.append(s)
        print(json.dumps(s), flush=True)
        (BASE / "ab_results.json").write_text(
            json.dumps({"results": results, "snapshots": snaps}, indent=1))

(BASE / "ab_results.json").write_text(
    json.dumps({"results": results, "snapshots": snaps}, indent=1))
print("AB_DONE", flush=True)
