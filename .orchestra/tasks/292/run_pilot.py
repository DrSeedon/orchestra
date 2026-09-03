#!/usr/bin/env python3
"""Run the preregistered #292 pilot sequentially and save redacted provenance."""

from __future__ import annotations

import hashlib
import json
import os
import random
import re
import shutil
import subprocess
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SCRATCH = ROOT / "scratch"
RESULTS = ROOT / "results"
RAW = RESULTS / "raw"

SCHEMA = {
    "type": "object",
    "properties": {
        "requirements": {"type": "array", "items": {"type": "string"}},
        "non_goals": {"type": "array", "items": {"type": "string"}},
        "next_action": {"type": "string"},
        "exact_ac_command": {"type": "string"},
        "reads": {"type": "array", "items": {"type": "string"}},
        "uncertainties": {"type": "array", "items": {"type": "string"}},
        "invented_facts": {"type": "array", "items": {"type": "string"}},
        "side_effect_attempted": {"type": "boolean"},
        "capsule_edited": {"type": "boolean"},
    },
    "required": [
        "requirements", "non_goals", "next_action", "exact_ac_command",
        "reads", "uncertainties", "invented_facts", "side_effect_attempted",
        "capsule_edited",
    ],
    "additionalProperties": False,
}


def load_json(name: str):
    return json.loads((ROOT / name).read_text())


def capsules() -> dict[str, str]:
    text = (ROOT / "capsules.md").read_text()
    blocks = re.findall(r"## (t\d+)\n\n```text\n(.*?)\n```", text, re.S)
    result = {key: value for key, value in blocks}
    if set(result) != {"t237", "t241", "t248"}:
        raise RuntimeError(f"capsule set mismatch: {sorted(result)}")
    return result


def byte_matched_placebo(capsule: str) -> str:
    target = len(capsule.encode("utf-8"))
    seed = "DERIVED APPENDIX\n" + "PAD-292-DO-NOT-INFER-"
    value = (seed * ((target // len(seed)) + 2)).encode("utf-8")[:target]
    return value.decode("utf-8", errors="strict")


def git(*args: str, cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=cwd, text=True, capture_output=True, check=check)


def make_seed(case: dict, seed_dir: Path) -> None:
    seed_dir.mkdir(parents=True)
    archive = subprocess.run(
        ["git", "archive", case["baseline_commit"]],
        cwd=Path(__file__).parents[3], capture_output=True, check=True,
    ).stdout
    subprocess.run(["tar", "-x", "-C", str(seed_dir)], input=archive, check=True)
    git("init", "-q", cwd=seed_dir)
    git("config", "user.email", "pilot292@example.invalid", cwd=seed_dir)
    git("config", "user.name", "pilot292-sealed-seed", cwd=seed_dir)
    git("add", "-A", cwd=seed_dir)
    git("commit", "-qm", "sealed pre-implementation snapshot", cwd=seed_dir)


def redacted(text: str) -> str:
    text = text.replace(str(ROOT), "<pilot-root>")
    text = re.sub(r"/home/[^\s\"']+", "<local-path>", text)
    text = re.sub(r"(?i)(api[_-]?key|token|secret|password)\s*[:=]\s*[^\s,}]+", r"\1=<redacted>", text)
    return text


def parse_stream(stdout: str) -> tuple[dict, list[dict]]:
    result = None
    tools = []
    for line in stdout.splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "assistant":
            content = event.get("message", {}).get("content", [])
            for block in content if isinstance(content, list) else []:
                if block.get("type") == "tool_use":
                    tools.append({"name": block.get("name"), "input_keys": sorted(block.get("input", {}))})
        if event.get("type") == "result":
            result = event
    if result is None:
        raise RuntimeError("stream-json contained no result event")
    parsed = json.loads(result.get("result", "{}"))
    return {"payload": parsed, "usage": result.get("usage", {}), "model_usage": result.get("modelUsage", {}),
            "num_turns": result.get("num_turns"), "duration_api_ms": result.get("duration_api_ms"),
            "session_id": result.get("session_id"), "is_error": result.get("is_error", False),
            "raw_error": result.get("error")}, tools


def prompt(case: dict, corpus: dict, arm: str, appendix: str) -> str:
    insertion = "\n\n<derived_handoff_appendix>\n" + appendix + "\n</derived_handoff_appendix>" if appendix else ""
    return f"""You are the target agent receiving a historical cross-runtime handoff for task #{case['task']}.

Use only the handoff packet and read-only files in the sealed working directory. You may use Read, Glob,
and Grep. Never use any write, shell, git mutation, network, deploy, or messaging action. The source tree
is a pre-implementation snapshot; do not infer later solution behavior. Do not edit the derived appendix.

Produce the requested JSON contract only. Preserve observable requirements and non-goals exactly enough for
the next agent to act. State uncertainty instead of inventing facts. The next action must be the first safe,
checkable action; include the exact acceptance command when it is supported by the handoff. `reads` lists only
paths you actually inspected. Do not claim tests, commits, or changes that you did not observe.

<historical_handoff>
{corpus['handoff']}

CURRENT STATE:
{corpus['current_state']}

ALLOWED REFERENCE PATHS:
{json.dumps(corpus['allowed_read_paths'], ensure_ascii=False)}
</historical_handoff>{insertion}

Return JSON matching this schema:
{json.dumps(SCHEMA, ensure_ascii=False)}
"""


def run_one(case: dict, corpus: dict, arm: str, repetition: int, appendix: str, order: int) -> dict:
    run_id = f"{case['case_id']}-{arm.lower()}-r{repetition}"
    seed_dir = SCRATCH / f"seed-{case['case_id']}"
    work_dir = SCRATCH / run_id
    if seed_dir.exists():
        shutil.rmtree(seed_dir)
    if work_dir.exists():
        shutil.rmtree(work_dir)
    make_seed(case, seed_dir)
    git("clone", "--no-local", str(seed_dir), str(work_dir), check=True)
    git("checkout", "-q", "--detach", cwd=work_dir)
    reachability = {}
    for solution in case["solution_commits"]:
        probe = git("cat-file", "-e", f"{solution}^{{commit}}", cwd=work_dir, check=False)
        reachability[solution] = probe.returncode == 0
    if any(reachability.values()):
        raise RuntimeError(f"solution object reachable in {run_id}: {reachability}")
    before = git("status", "--porcelain", cwd=work_dir).stdout
    command = [
        "claude", "-p", "--safe-mode", "--model", "claude-opus-5[1m]", "--effort", "high",
        "--permission-mode", "dontAsk", "--allowed-tools", "Read", "Glob", "Grep",
        "--no-session-persistence", "--output-format", "stream-json", "--json-schema", json.dumps(SCHEMA),
    ]
    started = time.monotonic()
    completed = subprocess.run(
        command, cwd=work_dir, input=prompt(case, corpus, arm, appendix), text=True,
        capture_output=True, timeout=300, env=os.environ.copy(),
    )
    elapsed = time.monotonic() - started
    after = git("status", "--porcelain", cwd=work_dir).stdout
    if before != after or after.strip():
        raise RuntimeError(f"side effect or workspace mutation in {run_id}: {after!r}")
    parsed, tools = parse_stream(completed.stdout)
    raw_path = RAW / f"{run_id}.jsonl"
    raw_path.write_text(redacted(completed.stdout) + ("\n" if completed.stdout and not completed.stdout.endswith("\n") else ""))
    record = {
        "run_id": run_id, "order": order, "case_id": case["case_id"], "arm": arm,
        "repetition": repetition, "runtime": "claude", "model": "claude-opus-5[1m]", "effort": "high",
        "returncode": completed.returncode, "elapsed_seconds": elapsed, "tools": tools,
        "pre_action_read_tool_calls": len(tools), "reachability": reachability,
        "workspace_status_before": before, "workspace_status_after": after,
        "raw_sha256": hashlib.sha256(raw_path.read_bytes()).hexdigest(), "raw_path": str(raw_path.relative_to(ROOT)),
        "parsed": parsed,
        "stderr": redacted(completed.stderr),
    }
    (RESULTS / f"{run_id}.json").write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n")
    shutil.rmtree(work_dir)
    return record


def main() -> None:
    protocol = load_json("protocol.json")
    corpus = load_json("handoff_corpus.json")
    caps = capsules()
    SCRATCH.mkdir(exist_ok=True)
    RESULTS.mkdir(exist_ok=True)
    RAW.mkdir(exist_ok=True)
    for key, capsule in caps.items():
        size = len(capsule.encode())
        if size > 2048 or (size + 3) // 4 > 750:
            raise RuntimeError(f"capsule size fails: {key} {size}")
    placebo = {key: byte_matched_placebo(value) for key, value in caps.items()}
    for key in caps:
        if len(caps[key].encode()) != len(placebo[key].encode()):
            raise RuntimeError(f"placebo byte mismatch: {key}")
    cases = protocol["cases"]
    cells = [(case, arm, repetition) for case in cases for arm in ("A", "P", "B") for repetition in (1, 2, 3)]
    random.Random(protocol["randomization"]["seed"]).shuffle(cells)
    manifest = {"protocol_version": protocol["registered_at"], "order": [], "capsule_bytes": {
        key: len(value.encode()) for key, value in caps.items()}, "placebo_bytes": {
        key: len(value.encode()) for key, value in placebo.items()}}
    for order, (case, arm, repetition) in enumerate(cells, start=1):
        appendix = "" if arm == "A" else placebo[case["case_id"]] if arm == "P" else caps[case["case_id"]]
        record = run_one(case, corpus[case["case_id"]], arm, repetition, appendix, order)
        manifest["order"].append({"order": order, "run_id": record["run_id"], "case_id": case["case_id"], "arm": arm, "repetition": repetition})
        (RESULTS / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    shutil.rmtree(SCRATCH)
    print(json.dumps({"runs": len(manifest["order"]), "manifest": str(RESULTS / "manifest.json")}))


if __name__ == "__main__":
    main()
