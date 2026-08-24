#!/usr/bin/env python3
"""Run the frozen paired prompt experiment in isolated temporary git repositories."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EVAL = ROOT / "eval"
RAW = ROOT / "raw"
SCRATCH = Path("/mnt/data/task250-eval-scratch-250")
MODEL = "gpt-5.6-luna"
ORDER = [
    ("t03_fallback_classifier", "candidate"),
    ("t03_fallback_classifier", "baseline"),
    ("t01_route_switch", "baseline"),
    ("t01_route_switch", "candidate"),
    ("t05_ledger_exactly_once", "candidate"),
    ("t05_ledger_exactly_once", "baseline"),
    ("t04_prompt_collection", "baseline"),
    ("t04_prompt_collection", "candidate"),
    ("t02_kill_path", "candidate"),
    ("t02_kill_path", "baseline"),
    ("t06_manifest_parser", "baseline"),
    ("t06_manifest_parser", "candidate"),
]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(command: list[str], cwd: Path, **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(command, cwd=cwd, text=True, **kwargs)


def tool_calls(events_path: Path) -> int:
    count = 0
    tool_types = {
        "command_execution", "file_change", "mcp_tool_call", "dynamic_tool_call",
        "web_search", "computer_initialize_state",
    }
    for line in events_path.read_text(errors="replace").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") != "item.completed":
            continue
        if (event.get("item") or {}).get("type") in tool_types:
            count += 1
    return count


def main() -> int:
    if SCRATCH.exists():
        if SCRATCH != Path("/mnt/data/task250-eval-scratch-250"):
            raise RuntimeError("refusing unexpected scratch path")
        shutil.rmtree(SCRATCH)
    SCRATCH.mkdir(parents=True)
    RAW.mkdir(parents=True, exist_ok=True)

    baseline = (ROOT / "baseline-prompt.md").read_text()
    candidate = (ROOT / "candidate-prompt.md").read_text()
    summaries = []

    for index, (task, arm) in enumerate(ORDER, start=1):
        run_id = f"{index:02d}-{task}-{arm}"
        work = SCRATCH / run_id
        out = RAW / run_id
        shutil.copytree(EVAL / "fixtures" / task, work)
        out.mkdir(parents=True, exist_ok=True)

        run(["git", "init", "-q"], work, check=True)
        run(["git", "config", "user.email", "eval@example.invalid"], work, check=True)
        run(["git", "config", "user.name", "Task 250 Eval"], work, check=True)
        run(["git", "add", "."], work, check=True)
        run(["git", "commit", "-qm", "frozen fixture"], work, check=True)

        task_text = (EVAL / "tasks" / f"{task}.md").read_text()
        prompt = baseline + ("\n" + candidate if arm == "candidate" else "") + "\n" + task_text
        (out / "prompt.txt").write_text(prompt)
        events_path = out / "events.jsonl"
        stderr_path = out / "stderr.txt"
        last_path = out / "last-message.txt"
        command = [
            "codex", "exec", "--json", "--ephemeral", "--ignore-user-config",
            "--ignore-rules", "-m", MODEL, "-s", "workspace-write",
            "-C", str(work), "-o", str(last_path), prompt,
        ]
        started = time.monotonic()
        timed_out = False
        with events_path.open("w") as stdout, stderr_path.open("w") as stderr:
            try:
                result = subprocess.run(
                    command, text=True, stdout=stdout, stderr=stderr, timeout=900,
                )
                returncode = result.returncode
            except subprocess.TimeoutExpired:
                timed_out = True
                returncode = 124
        elapsed = time.monotonic() - started

        diff = run(["git", "diff", "--binary"], work, capture_output=True, check=True).stdout
        changed = run(
            ["git", "diff", "--name-only"], work, capture_output=True, check=True,
        ).stdout.splitlines()
        (out / "diff.patch").write_text(diff)
        shutil.copy2(work / "tests" / "test_target.py", out / "test_target.py")
        production = next((work / "src").glob("*.py"))
        fixture_production = next((EVAL / "fixtures" / task / "src").glob("*.py"))
        metadata = {
            "run_id": run_id,
            "task": task,
            "arm": arm,
            "model": MODEL,
            "returncode": returncode,
            "timed_out": timed_out,
            "elapsed_seconds": round(elapsed, 3),
            "tool_calls": tool_calls(events_path),
            "changed_files": changed,
            "production_sha256": sha256(production),
            "fixture_production_sha256": sha256(fixture_production),
        }
        (out / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
        summaries.append(metadata)

    (RAW / "run-summary.json").write_text(json.dumps(summaries, indent=2) + "\n")
    shutil.rmtree(SCRATCH)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

