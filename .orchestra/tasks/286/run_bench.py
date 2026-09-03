#!/usr/bin/env python3
"""Run the preregistered #286 Luna/Spark pairs; raw artifacts stay on real disk."""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import threading
import time
from pathlib import Path


HERE = Path(__file__).resolve().parent
WORKTREE = Path(subprocess.check_output(
    ["git", "rev-parse", "--show-toplevel"], cwd=HERE, text=True,
).strip())
COMMON_GIT = Path(subprocess.check_output(
    ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
    cwd=HERE, text=True,
).strip())
SOURCE_REPO = COMMON_GIT.parent
CODEX = shutil.which("codex") or "codex"
MODELS = ("gpt-5.6-luna", "gpt-5.3-codex-spark")

TASKS = {
    "silence-upsert": {
        "base": "d0023db6c5137abcd167026475221827b39f56af",
        "future": "cfdb1d0e04d79cf628032c2c6426cebe4b1443c4",
        "prompt": "silence-upsert.txt",
        "allowed": ["app/db.py"],
        "oracle_paths": ["tests/test_quota_alert_state.py"],
        "oracle_sha256": ["21b355181967837008612738fe9315c2211e13afba4d9433c3bc34a594ca7331"],
        "command": (
            "uv run python -m pytest -q "
            "tests/test_quota_alert_state.py::test_mark_announced_can_restore_missing_state_row "
            "tests/test_quota_alert_state.py::test_silence_claim_is_taken_once_and_then_confirmed_forever"
        ),
    },
    "no-quota-suffix": {
        "base": "029d7573d8998ed818c0a8da5cad46cf1407c684",
        "future": "9268255cf199a0b95e9001e803c3f13544256896",
        "prompt": "no-quota-suffix.txt",
        "allowed": ["app/session_turns.py"],
        "oracle_paths": ["tests/test_turn_ended_no_quota_suffix.py"],
        "oracle_sha256": ["8a72aee377002be4aa9f212fe1985a6322ec5bb38c71c511922916bded51a563"],
        "command": "uv run python -m pytest -q tests/test_turn_ended_no_quota_suffix.py",
    },
}


def run(cmd: list[str], *, cwd: Path | None = None, timeout: int = 300, **kwargs):
    return subprocess.run(cmd, cwd=cwd, text=True, timeout=timeout, **kwargs)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def archive_snapshot(base: str, destination: Path) -> None:
    destination.mkdir(parents=True)
    archive = subprocess.Popen(
        ["git", "archive", base], cwd=SOURCE_REPO, stdout=subprocess.PIPE,
    )
    assert archive.stdout is not None
    extract = subprocess.run(["tar", "-x", "-C", str(destination)], stdin=archive.stdout)
    archive.stdout.close()
    archive_rc = archive.wait()
    if archive_rc or extract.returncode:
        raise RuntimeError(f"archive failed: git={archive_rc}, tar={extract.returncode}")


def git_bytes(revision: str, path: str) -> bytes:
    return subprocess.check_output(["git", "show", f"{revision}:{path}"], cwd=SOURCE_REPO)


def prepare_seed(task_name: str, root: Path) -> dict:
    spec = TASKS[task_name]
    seed = root / "seeds" / task_name
    archive_snapshot(spec["base"], seed)
    for path in spec["oracle_paths"]:
        target = seed / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(git_bytes(spec["future"], path))
    got_hashes = [sha256(seed / path) for path in spec["oracle_paths"]]
    if got_hashes != spec["oracle_sha256"]:
        raise RuntimeError(f"oracle hash mismatch for {task_name}: {got_hashes}")
    run(["git", "init", "-q"], cwd=seed, check=True)
    run(["git", "add", "-A"], cwd=seed, check=True)
    run(["git", "commit", "-q", "-m", f"#286 frozen fixture {task_name}"], cwd=seed, check=True)
    future_probe = run(
        ["git", "cat-file", "-e", f"{spec['future']}^{{commit}}"],
        cwd=seed, capture_output=True,
    )
    if future_probe.returncode == 0:
        raise RuntimeError(f"future implementation reachable in seed {task_name}")
    red = run(shlex.split(spec["command"]), cwd=seed, capture_output=True, timeout=600)
    if red.returncode == 0:
        raise RuntimeError(f"fixture is not RED: {task_name}")
    red_text = red.stdout + red.stderr
    if "ERROR collecting" in red_text or "ImportError" in red_text or "ModuleNotFoundError" in red_text:
        raise RuntimeError(f"fixture broken rather than RED: {task_name}\n{red_text[-3000:]}")
    return {
        "task": task_name,
        "seed": str(seed),
        "seed_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=seed, text=True).strip(),
        "future_unreachable": True,
        "oracle_sha256": got_hashes,
        "red_exit": red.returncode,
        "red_tail": "\n".join(red_text.splitlines()[-14:]),
    }


def clone_for(task_name: str, model: str, root: Path, fixture: dict) -> tuple[Path, dict]:
    slug = "luna" if model.endswith("luna") else "spark"
    clone = root / "runs" / f"{task_name}-{slug}" / "repo"
    clone.parent.mkdir(parents=True)
    proc = run(
        ["git", "clone", "--quiet", "--no-local", fixture["seed"], str(clone)],
        capture_output=True, timeout=600,
    )
    if proc.returncode:
        raise RuntimeError(f"clone failed: {proc.stderr}")
    run(["git", "remote", "remove", "origin"], cwd=clone, check=True)
    alternates = clone / ".git" / "objects" / "info" / "alternates"
    future_probe = run(
        ["git", "cat-file", "-e", f"{TASKS[task_name]['future']}^{{commit}}"],
        cwd=clone, capture_output=True,
    )
    hashes = [sha256(clone / path) for path in TASKS[task_name]["oracle_paths"]]
    proof = {
        "seed_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=clone, text=True).strip(),
        "alternates_absent": not alternates.exists(),
        "future_implementation_unreachable": future_probe.returncode != 0,
        "oracle_sha256_before": hashes,
    }
    if not all((proof["alternates_absent"], proof["future_implementation_unreachable"])):
        raise RuntimeError(f"isolation proof failed: {proof}")
    return clone, proof


def scan_event(event: dict, metrics: dict, received_s: float) -> None:
    event_type = event.get("type")
    if metrics["first_event_seconds"] is None:
        metrics["first_event_seconds"] = received_s
    item = event.get("item") if isinstance(event.get("item"), dict) else {}
    item_type = item.get("type")
    action_types = {"command_execution", "mcp_tool_call", "file_change", "web_search", "agent_message"}
    if item_type in action_types and metrics["cold_start_seconds"] is None:
        metrics["cold_start_seconds"] = received_s
    if event_type == "item.completed" and item_type in action_types - {"agent_message"}:
        metrics["tool_calls"] += 1
        failed = False
        if item_type == "command_execution":
            exit_code = item.get("exit_code")
            failed = item.get("status") == "failed" or (isinstance(exit_code, int) and exit_code != 0)
            if isinstance(item.get("command"), str):
                metrics["commands"].append(item["command"])
        elif item_type == "mcp_tool_call":
            failed = item.get("status") in {"failed", "error"} or bool(item.get("is_error"))
        if failed:
            metrics["tool_failures"].append({
                "type": item_type,
                "exit_code": item.get("exit_code"),
                "status": item.get("status"),
                "command": item.get("command"),
            })
    if event_type == "turn.completed" and isinstance(event.get("usage"), dict):
        metrics["usage"] = {
            "input_tokens": int(event["usage"].get("input_tokens") or 0),
            "cached_input_tokens": int(event["usage"].get("cached_input_tokens") or 0),
            "output_tokens": int(event["usage"].get("output_tokens") or 0),
        }


def model_turn(task_name: str, model: str, root: Path, fixture: dict) -> dict:
    spec = TASKS[task_name]
    clone, proof = clone_for(task_name, model, root, fixture)
    out_dir = clone.parent
    final_path = out_dir / "final.txt"
    events_path = out_dir / "events.jsonl"
    stderr_path = out_dir / "stderr.txt"
    unit = f"b286-{task_name[:8]}-{'luna' if model.endswith('luna') else 'spark'}"
    cmd = [
        "sudo", "systemd-run", "--quiet", "--collect", "--wait", "--pipe",
        f"--unit={unit}", "-p", "User=kesha", "-p", f"WorkingDirectory={clone}",
        "-p", "Environment=HOME=/home/kesha", "-p", "MemoryMax=2G",
        "-p", "InaccessiblePaths=/home/kesha/orchestra",
        "-p", "InaccessiblePaths=/home/kesha/orchestra-archive",
        CODEX, "exec", "--json", "--ephemeral", "--dangerously-bypass-approvals-and-sandbox",
        "-m", model, "-c", 'model_reasoning_effort="high"', "-o", str(final_path), "-",
    ]
    prompt = (HERE / "prompts" / spec["prompt"]).read_text(encoding="utf-8")
    stream_metrics = {
        "first_event_seconds": None,
        "cold_start_seconds": None,
        "tool_calls": 0,
        "tool_failures": [],
        "commands": [],
        "usage": {},
    }
    started_wall = time.time()
    started_mono = time.monotonic()
    with events_path.open("w", encoding="utf-8") as events_file, stderr_path.open("w", encoding="utf-8") as stderr_file:
        proc = subprocess.Popen(
            cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=stderr_file,
            text=True, bufsize=1,
        )
        assert proc.stdin is not None and proc.stdout is not None

        def read_stdout() -> None:
            for line in proc.stdout:
                received_s = time.monotonic() - started_mono
                events_file.write(line)
                events_file.flush()
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(event, dict):
                    scan_event(event, stream_metrics, received_s)

        reader = threading.Thread(target=read_stdout, daemon=True)
        reader.start()
        proc.stdin.write(prompt)
        proc.stdin.close()
        timed_out = False
        try:
            exit_code = proc.wait(timeout=900)
        except subprocess.TimeoutExpired:
            timed_out = True
            run(["sudo", "systemctl", "kill", unit], capture_output=True)
            exit_code = proc.wait(timeout=30)
        reader.join(timeout=30)
    ended_wall = time.time()
    final = final_path.read_text(encoding="utf-8") if final_path.exists() else ""
    oracle_hashes_after = [sha256(clone / path) for path in spec["oracle_paths"]]
    oracle_unchanged = oracle_hashes_after == spec["oracle_sha256"]
    grade = run(shlex.split(spec["command"]), cwd=clone, capture_output=True, timeout=600)
    status = subprocess.check_output(["git", "status", "--short"], cwd=clone, text=True)
    changed_paths = []
    for line in status.splitlines():
        path = line[3:]
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        changed_paths.append(path)
    diff = subprocess.check_output(["git", "diff", "--no-ext-diff"], cwd=clone, text=True)
    (out_dir / "diff.patch").write_text(diff, encoding="utf-8")
    allowed_exact = set(changed_paths) == set(spec["allowed"])
    passed = grade.returncode == 0 and oracle_unchanged and allowed_exact and bool(diff.strip())
    claims_success = bool(re.search(r"\b(done|implemented|complete|completed|pass(?:ed)?|green)\b", final, re.I))
    admits_failure = bool(re.search(r"\b(fail(?:ed|ure)?|blocked|cannot|unable|red)\b", final, re.I))
    if passed:
        outcome = "PASS"
    elif not final.strip() or admits_failure:
        outcome = "LOUD_FAIL"
    elif claims_success:
        outcome = "SILENT_FALSE_SUCCESS"
    else:
        outcome = "FAIL_UNCLASSIFIED"
    usage = stream_metrics["usage"]
    fresh = max(0, usage.get("input_tokens", 0) - usage.get("cached_input_tokens", 0))
    luna_equivalent = (
        fresh * 0.20
        + usage.get("cached_input_tokens", 0) * 0.02
        + usage.get("output_tokens", 0) * 1.20
    ) / 1_000_000
    commands_text = "\n".join(stream_metrics["commands"]).lower()
    leakage_markers = [
        marker for marker in (
            "/home/kesha/orchestra", "orchestra-archive", "git fetch", "github.com",
            spec["future"][:12],
        ) if marker.lower() in commands_text
    ]
    result = {
        "task": task_name,
        "model": model,
        "started_at": started_wall,
        "ended_at": ended_wall,
        "wall_seconds": round(ended_wall - started_wall, 3),
        "exit_code": exit_code,
        "timed_out": timed_out,
        "prompt_chars": len(prompt),
        "proof": proof,
        **stream_metrics,
        "tool_failure_count": len(stream_metrics["tool_failures"]),
        "oracle_sha256_after": oracle_hashes_after,
        "oracle_unchanged": oracle_unchanged,
        "grade_exit": grade.returncode,
        "grade_tail": "\n".join((grade.stdout + grade.stderr).splitlines()[-14:]),
        "changed_paths": changed_paths,
        "allowed_paths_exact": allowed_exact,
        "diff_sha256": sha256(out_dir / "diff.patch"),
        "diff_patch": diff,
        "outcome": outcome,
        "final": final,
        "virtual_api_equivalent_usd": round(luna_equivalent, 8) if model.endswith("luna") else None,
        "luna_priced_trace_sensitivity_usd": round(luna_equivalent, 8),
        "leakage_markers": leakage_markers,
        "raw": {
            "events": str(events_path),
            "stderr": str(stderr_path),
            "diff": str(out_dir / "diff.patch"),
        },
    }
    (out_dir / "metrics.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def reused_222() -> dict:
    source = WORKTREE / "docs" / "tasks" / "222" / "blind-grades.json"
    rows = json.loads(source.read_text(encoding="utf-8"))
    return {
        "source": str(source.relative_to(WORKTREE)),
        "sha256": sha256(source),
        "confirmatory_rows": len(rows),
        "models_key": {"m7p": "gpt-5.3-codex-spark", "q2v": "gpt-5.6-luna"},
        "rows": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prepare-only", action="store_true")
    args = parser.parse_args()
    prereg_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=WORKTREE, text=True).strip()
    suffix = f"fixture-{time.time_ns()}" if args.prepare_only else prereg_sha[:12]
    root = Path(f"/var/tmp/orchestra-bench-286-{suffix}")
    if root.exists():
        raise SystemExit(f"refusing to reuse existing root: {root}")
    root.mkdir(parents=True)
    fixtures = [prepare_seed(name, root) for name in TASKS]
    if args.prepare_only:
        print(json.dumps(fixtures, ensure_ascii=False, indent=2))
        return
    runs = []
    by_name = {row["task"]: row for row in fixtures}
    for task_name in TASKS:
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(model_turn, task_name, model, root, by_name[task_name]) for model in MODELS]
            for future in futures:
                runs.append(future.result())
    payload = {
        "schema_version": 1,
        "prereg_commit": prereg_sha,
        "generated_at": time.time(),
        "codex_version": subprocess.check_output([CODEX, "--version"], text=True).strip(),
        "root": str(root),
        "fixtures": fixtures,
        "reused_222": reused_222(),
        "new_confirmatory_runs": runs,
    }
    output = root / "data.json"
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
