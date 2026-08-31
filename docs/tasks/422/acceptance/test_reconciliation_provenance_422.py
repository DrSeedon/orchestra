from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path


TASK_DIR = Path(__file__).resolve().parents[1]


def _run(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )


def test_reconcile_rejects_paired_summary_and_receipt_forgery(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    copied_task = repo / "docs" / "tasks" / "422"
    copied_task.parent.mkdir(parents=True)
    shutil.copytree(TASK_DIR, copied_task)

    assert _run("git", "init", "-q", cwd=repo).returncode == 0
    assert _run("git", "config", "user.email", "test@example.invalid", cwd=repo).returncode == 0
    assert _run("git", "config", "user.name", "Task 422 test", cwd=repo).returncode == 0
    assert _run(
        "git",
        "add",
        "docs/tasks/422/evidence/replay-summary.json",
        "docs/tasks/422/evidence/raw",
        cwd=repo,
    ).returncode == 0
    assert _run("git", "commit", "-q", "-m", "immutable source", cwd=repo).returncode == 0
    source_commit = _run("git", "rev-parse", "HEAD", cwd=repo).stdout.strip()

    evidence = copied_task / "evidence"
    summary_path = evidence / "replay-summary.json"
    source_summary_sha256 = hashlib.sha256(summary_path.read_bytes()).hexdigest()
    (evidence / "reconciliation-provenance.json").write_text(
        json.dumps(
            {
                "schema": "orchestra-422-reconciliation-provenance-v1",
                "source_commit": source_commit,
                "source_summary_sha256": source_summary_sha256,
            }
        )
        + "\n"
    )

    summary = json.loads(summary_path.read_text())
    forged_run = next(
        run
        for run in summary["runs"]
        if json.loads((copied_task / run["raw_receipt"]).read_text()).get("loop_ok")
        and run["outcome"] != "success"
    )
    receipt_path = copied_task / forged_run["raw_receipt"]
    receipt = json.loads(receipt_path.read_text())
    receipt["outcome"] = "success"
    receipt["evidence"] = "PAIR_FORGERY"
    receipt_path.write_text(json.dumps(receipt, sort_keys=True, indent=2) + "\n")
    forged_run["outcome"] = "success"
    forged_run["evidence"] = "PAIR_FORGERY"
    forged_run["raw_receipt_sha256"] = hashlib.sha256(receipt_path.read_bytes()).hexdigest()
    summary_path.write_text(json.dumps(summary, sort_keys=True, indent=2) + "\n")

    result = _run(sys.executable, str(copied_task / "run_free_lane_replay.py"), "reconcile", cwd=repo)

    assert result.returncode != 0, "paired summary+receipt forgery was accepted"
    assert "immutable reconciliation source mismatch" in result.stderr
