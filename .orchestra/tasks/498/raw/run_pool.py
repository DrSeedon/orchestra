#!/usr/bin/env python3
"""#498 row 3: does gpt-6-astra draw on the SAME codex.primary pool as Sol/Luna?

The account is shared with other live workers, so the counter drifts on its own.
Design handles that instead of ignoring it:

  Phase A  quiet window, no calls from us      -> background drift rate
  Phase B  Spark calls (own bucket, per vendor) -> POSITIVE CONTROL that the
           apparatus can attribute a burn to the right bucket
  Phase C  Astra burn, concurrent, long outputs -> does codex.primary move
           faster than background while codex_bengalfox stays flat
  Phase D  quiet window again                   -> background drift rate, after

Verdict rule fixed BEFORE the run:
  shared  <- codex.primary rises during C at a rate clearly above the A/D
            background rate, and no new limit id appears for astra
  separate<- a new limit id appears, or codex.primary rise during C is
            indistinguishable from the A/D background rate
"""
import concurrent.futures as cf
import json
import subprocess
import time
from pathlib import Path

BASE = Path("/tmp/astra498")
LOG = []

BURN_PROMPT = (
    "Write a detailed technical reference document of at least 3000 words about "
    "designing fault-tolerant distributed job queues: delivery semantics, idempotency, "
    "backpressure, retry and dead-letter policy, observability, and failure drills. "
    "Output only the document body. Do not use any tools."
)


def snapshot(label):
    p = subprocess.run(["python3", str(BASE / "ratelimits.py"), label],
                       capture_output=True, text=True, timeout=90)
    d = json.loads(p.stdout)
    r = (d.get("result") or {}).get("rateLimitsByLimitId") or {}
    s = {
        "t": time.time(),
        "label": label,
        "fetched_at": d.get("fetched_at"),
        "limit_ids": sorted(r.keys()),
        "codex_pct": ((r.get("codex") or {}).get("primary") or {}).get("usedPercent"),
        "spark_5h_pct": ((r.get("codex_bengalfox") or {}).get("primary") or {}).get("usedPercent"),
        "spark_7d_pct": ((r.get("codex_bengalfox") or {}).get("secondary") or {}).get("usedPercent"),
    }
    LOG.append(s)
    print(json.dumps(s), flush=True)
    return s


def call(model, prompt, effort="high", timeout=900):
    cmd = ["codex", "exec", "--skip-git-repo-check", "--ignore-user-config",
           "-C", "/tmp/astra498/burn", "-s", "read-only", "--json",
           "-c", f"model_reasoning_effort={effort}", "-c", "approval_policy=never",
           "-m", model, prompt]
    t0 = time.time()
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return {"model": model, "effort": effort, "error": "timeout", "wall_s": timeout}
    usage, chars = {}, 0
    for line in p.stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            e = json.loads(line)
        except Exception:
            continue
        if e.get("type") == "turn.completed":
            usage = e.get("usage") or {}
        if e.get("type") == "item.completed" and (e.get("item") or {}).get("type") == "agent_message":
            chars += len((e["item"].get("text") or ""))
    return {"model": model, "effort": effort, "rc": p.returncode,
            "wall_s": round(time.time() - t0, 1), "usage": usage,
            "answer_chars": chars, "stderr_tail": p.stderr[-200:]}


def quiet(label, minutes):
    end = time.time() + minutes * 60
    while time.time() < end:
        snapshot(label)
        time.sleep(60)
    snapshot(label + "_end")


(BASE / "burn").mkdir(exist_ok=True)
runs = []

# ---- Phase A: background
snapshot("A_quiet_start")
quiet("A_quiet", 5)

# ---- Phase B: Spark positive control (vendor says Spark has its own limit)
snapshot("B_spark_before")
for i in range(3):
    r = call("gpt-5.3-codex-spark", BURN_PROMPT, effort="high", timeout=420)
    r["phase"] = f"B_spark_{i}"
    runs.append(r)
    print(json.dumps(r), flush=True)
    snapshot(f"B_after_spark_{i}")

# ---- Phase B2: does the CLI report Astra reasoning tokens at all?
r = call("gpt-6-astra",
         "Without using any tools, prove rigorously whether every positive integer "
         "can be written as the sum of at most four squares, then compute the number "
         "of representations of 2026 as an ordered sum of four squares. Show the reasoning.",
         effort="high", timeout=600)
r["phase"] = "B2_astra_reasoning_probe"
runs.append(r)
print(json.dumps(r), flush=True)
snapshot("B2_after_astra_reasoning_probe")

# ---- Phase C: Astra burn, concurrent
snapshot("C_burn_before")
ROUNDS, WIDTH = 4, 4
for rnd in range(ROUNDS):
    with cf.ThreadPoolExecutor(max_workers=WIDTH) as ex:
        futs = [ex.submit(call, "gpt-6-astra", BURN_PROMPT, "high", 600)
                for _ in range(WIDTH)]
        for f in futs:
            r = f.result()
            r["phase"] = f"C_burn_r{rnd}"
            runs.append(r)
            print(json.dumps(r), flush=True)
    snapshot(f"C_after_round_{rnd}")
    (BASE / "pool_results.json").write_text(json.dumps({"runs": runs, "snaps": LOG}, indent=1))

# ---- Phase D: background again
quiet("D_quiet", 5)

(BASE / "pool_results.json").write_text(json.dumps({"runs": runs, "snaps": LOG}, indent=1))
print("POOL_DONE", flush=True)
