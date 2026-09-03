#!/usr/bin/env python3
"""Run the preregistered #222 Spark/Luna pairs; generated data stays on real disk."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import random
import shutil
import subprocess
import time
import urllib.request
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
MODELS = {
    "m7p": "gpt-5.3-codex-spark",
    "q2v": "gpt-5.6-luna",
}
BASES = {
    "code": ("bench222-base-code", "886d61baad3bbf6cf60274aa3551a9656b319762", []),
    "text": ("bench222-base-text", "0d7e688433747a5f43fee83a5cc539f1699e1ac2", ["20564d6c7239074f76cd5fe6ff25a0989def9c98"]),
    "ambiguous": ("bench222-base-amb", "2758d2995046d415e8dc8ea6caddb0cf0fde87e7", ["e9a93b00a5a0c2ea1fa0a1e5a9863523360f5474"]),
    "ctx100": ("bench222-base-ctx", "12383469f6139390503fcb06d661334019ddc55b", ["8da9eed6"]),
    "ctx164": ("bench222-base-ctx", "12383469f6139390503fcb06d661334019ddc55b", ["8da9eed6"]),
}
TARGET_CHARS = {"ctx100": 390_000, "ctx164": 650_522}


def run(cmd: list[str], *, cwd: Path | None = None, **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, text=True, **kwargs)


def usage_snapshot() -> dict:
    token = os.environ["INTERNAL_TOKEN"]
    req = urllib.request.Request(
        "http://127.0.0.1:8888/api/usage",
        headers={"Authorization": f"Bearer {token}"},
    )
    with urllib.request.urlopen(req, timeout=10) as response:
        payload = json.load(response)
    return {
        "ts": time.time(),
        "codex_primary": payload["codex"]["primary"]["utilization"],
        "codex_spark": payload["codex"]["spark"]["primary"]["utilization"],
        "raw_codex": payload["codex"],
    }


def clone_for(case: str, rep: int, label: str, root: Path) -> tuple[Path, dict]:
    branch, expected_base, future = BASES[case]
    clone = root / f"{case}-r{rep}-{label}" / "repo"
    clone.parent.mkdir(parents=True)
    proc = run([
        "git", "clone", "--quiet", "--no-local", "--single-branch",
        "--branch", branch, str(SOURCE_REPO), str(clone),
    ], capture_output=True)
    if proc.returncode:
        raise RuntimeError(f"clone failed: {proc.stderr}")
    run(["git", "remote", "remove", "origin"], cwd=clone, check=True)
    got_base = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=clone, text=True).strip()
    if got_base != expected_base:
        raise RuntimeError(f"wrong base for {case}: {got_base} != {expected_base}")
    alternates = clone / ".git" / "objects" / "info" / "alternates"
    if alternates.exists():
        raise RuntimeError(f"shared object store leaked into {clone}")
    unreachable = {}
    for sha in [*future, subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=WORKTREE, text=True).strip()]:
        probe = run(["git", "cat-file", "-e", f"{sha}^{{commit}}"], cwd=clone, capture_output=True)
        unreachable[sha] = probe.returncode != 0
        if probe.returncode == 0:
            raise RuntimeError(f"future commit {sha} is reachable in {clone}")
    unit = f"b222-probe-{case[:5]}-{rep}-{label}"
    isolation = run([
        "sudo", "systemd-run", "--quiet", "--collect", "--wait", "--pipe",
        f"--unit={unit}", "-p", "User=kesha", "-p", f"WorkingDirectory={clone}",
        "-p", "InaccessiblePaths=/home/kesha/orchestra",
        "-p", "InaccessiblePaths=/home/kesha/orchestra-archive",
        "/bin/sh", "-c",
        "test ! -r /home/kesha/orchestra/.git/HEAD && test ! -r /home/kesha/orchestra-archive/README.md",
    ], capture_output=True)
    if isolation.returncode:
        raise RuntimeError(f"namespace isolation failed: {isolation.stderr}")
    proof = {
        "base": got_base,
        "alternates_absent": True,
        "future_commits_unreachable": unreachable,
        "parent_repo_and_archive_inaccessible": True,
    }
    return clone, proof


def context_prompt(clone: Path, case: str, rep: int) -> tuple[str, list[str]]:
    chunks = []
    for path in sorted((clone / "app").glob("*.py")):
        chunks.append(f"# FILE: app/{path.name}\n")
        chunks.append(path.read_text(encoding="utf-8"))
        chunks.append("\n")
    corpus = "".join(chunks)
    if "BENCH-NEEDLE" in corpus:
        raise RuntimeError("source corpus already contains benchmark markers")
    target = TARGET_CHARS[case]
    if len(corpus) < target:
        raise RuntimeError(f"corpus too short: {len(corpus)} < {target}")
    corpus = corpus[:target]
    rng = random.Random(22_000 + rep)
    values = [f"{rng.randrange(1000, 10000):04d}" for _ in range(5)]
    inserts = []
    for depth, value in zip((0.05, 0.25, 0.50, 0.75, 0.95), values):
        inserts.append((int(len(corpus) * depth), f"\n# BENCH-NEEDLE: control value = {value}\n"))
    for offset, marker in reversed(inserts):
        corpus = corpus[:offset] + marker + corpus[offset:]
    prefix = (HERE / "prompts" / "context.txt").read_text(encoding="utf-8")
    return prefix + "\n\n" + corpus, values


def prompt_for(case: str, clone: Path, rep: int) -> tuple[str, list[str] | None]:
    if case.startswith("ctx"):
        return context_prompt(clone, case, rep)
    filename = {"code": "code.txt", "text": "text.txt", "ambiguous": "ambiguous.txt"}[case]
    return (HERE / "prompts" / filename).read_text(encoding="utf-8"), None


def parse_events(stdout: str) -> dict:
    events = []
    for line in stdout.splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            events.append(value)
    tool_types = {"command_execution", "mcp_tool_call", "file_change", "web_search"}
    tool_calls = 0
    commands = []
    last_usage = {}

    def walk(value):
        nonlocal tool_calls, last_usage
        if isinstance(value, dict):
            if value.get("type") in tool_types:
                tool_calls += 1
            if value.get("type") == "command_execution" and isinstance(value.get("command"), str):
                commands.append(value["command"])
            if {"input_tokens", "output_tokens"} <= set(value):
                last_usage = {
                    "input_tokens": int(value.get("input_tokens") or 0),
                    "cached_input_tokens": int(value.get("cached_input_tokens") or 0),
                    "output_tokens": int(value.get("output_tokens") or 0),
                }
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    for event in events:
        walk(event)
    fresh = max(0, last_usage.get("input_tokens", 0) - last_usage.get("cached_input_tokens", 0))
    luna_cost = (
        fresh * 0.2
        + last_usage.get("cached_input_tokens", 0) * 0.02
        + last_usage.get("output_tokens", 0) * 1.2
    ) / 1_000_000
    return {
        "events": len(events),
        "turns": sum(1 for event in events if event.get("type") == "turn.completed"),
        "tool_calls": tool_calls,
        "commands": commands,
        "usage": last_usage,
        "luna_virtual_cost_if_applicable": round(luna_cost, 8),
    }


def one_run(case: str, rep: int, label: str, root: Path, *, pilot: bool = False) -> dict:
    model = MODELS[label]
    clone, proof = clone_for("code" if pilot else case, rep, label, root)
    if pilot:
        prompt, expected = "Reply exactly PILOT_OK and do not use tools.", None
    else:
        prompt, expected = prompt_for(case, clone, rep)
    out_dir = clone.parent
    last_message = clone / "last-message.txt"
    before = usage_snapshot()
    unit = f"b222-{'pilot' if pilot else case[:5]}-{rep}-{label}"
    cmd = [
        "sudo", "systemd-run", "--quiet", "--collect", "--wait", "--pipe",
        f"--unit={unit}", "-p", "User=kesha", "-p", f"WorkingDirectory={clone}",
        "-p", "Environment=HOME=/home/kesha", "-p", "MemoryMax=2G",
        "-p", "InaccessiblePaths=/home/kesha/orchestra",
        "-p", "InaccessiblePaths=/home/kesha/orchestra-archive",
        CODEX, "exec", "--json", "--ephemeral", "--dangerously-bypass-approvals-and-sandbox",
        "-m", model, "-c", 'model_reasoning_effort="high"',
        "-o", str(last_message), "-",
    ]
    started = time.time()
    try:
        proc = run(cmd, input=prompt, capture_output=True, timeout=900)
        timed_out = False
    except subprocess.TimeoutExpired as exc:
        proc = subprocess.CompletedProcess(cmd, 124, exc.stdout or "", exc.stderr or "timeout")
        timed_out = True
    ended = time.time()
    after = usage_snapshot()
    stdout = proc.stdout if isinstance(proc.stdout, str) else (proc.stdout or b"").decode()
    stderr = proc.stderr if isinstance(proc.stderr, str) else (proc.stderr or b"").decode()
    (out_dir / "events.jsonl").write_text(stdout, encoding="utf-8")
    (out_dir / "stderr.txt").write_text(stderr, encoding="utf-8")
    final = last_message.read_text(encoding="utf-8") if last_message.exists() else ""
    (out_dir / "final.txt").write_text(final, encoding="utf-8")
    diff = subprocess.check_output(["git", "diff", "--no-ext-diff"], cwd=clone, text=True)
    status = subprocess.check_output(["git", "status", "--short"], cwd=clone, text=True)
    (out_dir / "diff.patch").write_text(diff, encoding="utf-8")
    (out_dir / "status.txt").write_text(status, encoding="utf-8")
    parsed = parse_events(stdout)
    command_text = "\n".join(parsed["commands"]).lower()
    leakage_markers = [
        marker for marker in (
            "/home/kesha/orchestra", "orchestra-archive", "git fetch", "github.com",
            "20564d6", "e9a93b00", "#221", "#186", "#199",
        ) if marker.lower() in command_text
    ]
    metrics = {
        "case": "pilot" if pilot else case,
        "rep": rep,
        "label": label,
        "model": model,
        "started_at": started,
        "ended_at": ended,
        "wall_seconds": round(ended - started, 3),
        "exit_code": proc.returncode,
        "timed_out": timed_out,
        "proof": proof,
        "usage_before": before,
        "usage_after": after,
        "pool_delta_primary": after["codex_primary"] - before["codex_primary"],
        "pool_delta_spark": after["codex_spark"] - before["codex_spark"],
        "expected": expected,
        "prompt_chars": len(prompt),
        "final": final,
        "status": status,
        "leakage_markers": leakage_markers,
        "invalid_for_leakage": bool(leakage_markers),
        **parsed,
    }
    if model != "gpt-5.6-luna":
        metrics["luna_virtual_cost_if_applicable"] = None
    (out_dir / "metrics.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    return metrics


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pilot", action="store_true")
    args = parser.parse_args()
    prereg_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=WORKTREE, text=True).strip()
    suffix = "-pilot" if args.pilot else ""
    root = Path(f"/var/tmp/orchestra-bench-222-{prereg_sha[:12]}{suffix}")
    if root.exists():
        raise SystemExit(f"refusing to reuse existing run root: {root}")
    root.mkdir(parents=True)
    all_metrics = []
    if args.pilot:
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(one_run, "code", 0, label, root, pilot=True) for label in MODELS]
            for future in futures:
                all_metrics.append(future.result())
    else:
        for case in ("code", "text", "ambiguous", "ctx100", "ctx164"):
            for rep in (1, 2):
                with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                    futures = [pool.submit(one_run, case, rep, label, root) for label in MODELS]
                    for future in futures:
                        all_metrics.append(future.result())
    (root / "all-metrics.json").write_text(
        json.dumps(all_metrics, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    print(root)


if __name__ == "__main__":
    main()
