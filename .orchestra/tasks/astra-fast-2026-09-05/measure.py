"""Small user-authorized Standard/Fast latency probe; no tools or project context."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import statistics
import subprocess
import time

ROOT = Path(__file__).parent
SCRATCH = "/mnt/data/astra-fast-bench.aYnQwX"
LINES = int(os.environ.get("ASTRA_BENCH_LINES", "60"))
EXPECTED = "\n".join(f"{i:03d}: amber birch cedar dune ember frost grove hazel iris jade." for i in range(1, LINES + 1))
PROMPT = f"Do not use tools. Copy the following {LINES} lines exactly, with no introduction, code fences or extra text:\n" + EXPECTED
SEQUENCE = [("control", "default"), ("control", "default")]
SEQUENCE += [(str(pair), tier) for pair in range(4)
             for tier in (("default", "fast") if pair % 2 == 0 else ("fast", "default"))]


async def run(index, pair, tier):
    command = ["timeout", "--kill-after=5s", "90s", "codex", "exec",
               "--ignore-user-config", "--ignore-rules", "--ephemeral",
               "--skip-git-repo-check", "-C", SCRATCH, "-s", "read-only",
               "-m", "gpt-6-astra", "-c", 'model_reasoning_effort="medium"',
               "-c", "project_doc_max_bytes=0", "-c", f'service_tier="{tier}"',
               "--enable", "fast_mode", "--disable", "apps", "--disable", "shell_tool",
               "--disable", "multi_agent", "--json", PROMPT]
    started = time.perf_counter()
    row = {"index": index, "pair": pair, "requested_tier": tier,
           "loadavg": os.getloadavg(), "started_utc": time.time(), "lines": LINES,
           "cli_version": subprocess.check_output(["codex", "--version"], text=True).strip(),
           "launcher_sha256": hashlib.sha256(Path("/home/maxim/.local/bin/codex").read_bytes()).hexdigest()}
    proc = await asyncio.create_subprocess_exec(*command, cwd=SCRATCH,
        stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE)
    stderr = asyncio.create_task(proc.stderr.read())
    events, texts = [], []
    async for line in proc.stdout:
        try:
            event = json.loads(line)
        except ValueError:
            continue
        kind = event.get("type")
        events.append(kind)
        elapsed = time.perf_counter() - started
        if kind == "turn.started":
            row["turn_started_s"] = elapsed
        if kind == "turn.completed":
            row["turn_completed_s"] = elapsed
            row["usage"] = event.get("usage", {})
        item = event.get("item", {})
        if kind == "item.completed":
            if item.get("type") == "agent_message":
                texts.append(item.get("text", ""))
                row.setdefault("first_message_completed_s", elapsed)
            else:
                row.setdefault("non_message_items", []).append(item.get("type"))
    row["returncode"] = await proc.wait()
    row["elapsed_s"] = time.perf_counter() - started
    row["stderr_bytes"] = len(await stderr)
    answer = "\n".join(texts).strip()
    row["exact_output"] = answer == EXPECTED
    row["output_sha256"] = hashlib.sha256(answer.encode()).hexdigest()
    row["events"] = events
    row["valid"] = (row["returncode"] == 0 and row["exact_output"]
                    and "turn.completed" in events and not row.get("non_message_items"))
    return row


async def main():
    rows = []
    with (ROOT / f"measurements-{LINES}.jsonl").open("x") as output:
        for index, (pair, tier) in enumerate(SEQUENCE):
            row = await run(index, pair, tier)
            rows.append(row)
            output.write(json.dumps(row) + "\n")
            output.flush()
            print(json.dumps(row), flush=True)
            if not row["valid"]:
                print("Stopped: failed/invalid run; no automatic retries.", flush=True)
                return
    summaries = {tier: statistics.median(r["elapsed_s"] for r in rows
                 if r["requested_tier"] == tier and r["pair"] != "control")
                 for tier in ("default", "fast")}
    print(json.dumps({"median_seconds": summaries,
                      "standard_over_fast": summaries["default"] / summaries["fast"]}), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
