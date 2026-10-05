"""Measure the synchronous session preparation stages on disposable Git clones."""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

from app import workspace
from app.manager import SessionManager
from app.pipeline import get_worktree_config


BASE = Path(__file__).resolve().parent


def run_case(label: str, source: Path) -> dict:
    root = BASE / f"profile-{label}"
    clone = root / "repo"
    output = root / "worktrees"
    root.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "clone", "--shared", "--no-checkout", str(source), str(clone)],
        check=True, capture_output=True, text=True,
    )
    workspace.WORKTREE_ROOT = output
    git_stages: list[dict] = []
    original_git_cmd = workspace._git_cmd

    def timed_git_cmd(args, *a, **kw):
        started = time.monotonic()
        try:
            return original_git_cmd(args, *a, **kw)
        finally:
            tokens = [str(part) for part in args]
            if tokens[0] == "git":
                command = "git " + " ".join(
                    part for part in tokens[1:]
                    if not part.startswith("/") and not part.startswith("refs/")
                )
                command = " ".join(command.split()[:3])
            else:
                command = Path(tokens[0]).name
            git_stages.append({
                "command": command,
                "seconds": round(time.monotonic() - started, 4),
            })

    workspace._git_cmd = timed_git_cmd
    try:
        started = time.monotonic()
        worktree = workspace.create_worktree(
            str(clone), f"v699-{label}", worktree_cfg=get_worktree_config("default"),
        )
        worktree_seconds = time.monotonic() - started

        manager = SessionManager()
        started = time.monotonic()
        prompt, _overlay = manager.assemble_prompt(
            pipeline="default", role="worker", scope=str(source), is_orch=False,
            name=f"v699-{label}", owned_dirs=[], branch=worktree.branch,
            stored_overlay="", old_prompt="", repository_path=worktree.path,
            parent_name="orchestrator",
        )
        prompt_seconds = time.monotonic() - started
        tree = subprocess.run(
            ["git", "-C", str(clone), "ls-tree", "-r", "-l", "-z", "HEAD"],
            capture_output=True, check=True,
        ).stdout.split(b"\0")
        blobs = [item.split(b"\t", 1)[0].split() for item in tree if item]
        blob_sizes = [int(meta[3]) for meta in blobs if len(meta) >= 4 and meta[1] == b"blob"]
        return {
            "case": label,
            "tracked_files": len(blob_sizes),
            "tracked_bytes": sum(blob_sizes),
            "create_worktree_seconds": round(worktree_seconds, 4),
            "assemble_prompt_seconds": round(prompt_seconds, 4),
            "prompt_chars": len(prompt),
            "git_commands": git_stages,
        }
    finally:
        workspace._git_cmd = original_git_cmd


if __name__ == "__main__":
    cases = [arg.split("=", 1) for arg in sys.argv[1:]]
    if not cases or any(len(case) != 2 for case in cases):
        raise SystemExit("usage: measure_create_stages.py label=/path/to/repo [...]")
    results = [run_case(label, Path(source)) for label, source in cases]
    output = BASE / "stage_measurements.json"
    output.write_text(json.dumps(results, indent=2) + "\n")
    print(output.read_text(), end="")
