"""Reproduce #513 without invoking a real reviewer or touching production state."""

from __future__ import annotations

import asyncio
import json
import subprocess
import tempfile
from pathlib import Path

import app.db as db
import app.mcp_stdio as mcp
from app.review_coverage import coverage_decision, resolve_implementation_subject


def _git(cwd: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=True,
    )
    return completed.stdout.strip()


def _make_worktrees(root: Path) -> tuple[Path, Path]:
    actor = root / "actor"
    worker = root / "worker"
    actor.mkdir()
    _git(actor, "init", "-b", "main")
    _git(actor, "config", "user.email", "probe@example.test")
    _git(actor, "config", "user.name", "probe")
    (actor / "README.md").write_text("base\n", encoding="utf-8")
    _git(actor, "add", "README.md")
    _git(actor, "commit", "-m", "base")
    _git(actor, "branch", "task-513/worker")
    _git(actor, "worktree", "add", str(worker), "task-513/worker")
    (worker / "app").mkdir()
    (worker / "app/widget.py").write_text("VALUE = 1\n", encoding="utf-8")
    _git(worker, "add", "app/widget.py")
    _git(worker, "commit", "-m", "production change")
    return actor, worker


async def _scenario(*, detach_actor: bool) -> dict[str, object]:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        actor, worker = _make_worktrees(root)
        worker_subject = resolve_implementation_subject(str(worker), "main")
        if detach_actor:
            _git(actor, "checkout", "--detach", str(worker_subject["worker_head"]))

        db.DB_PATH = root / "probe.db"
        db.init_db()
        jobs: list[dict] = []

        async def fake_api(method: str, path: str, **kwargs):
            if path == "/api/usage/readiness":
                return {
                    "state": "available",
                    "model": "gpt-5.6-luna",
                    "provider": "codex",
                    "utilization": 1,
                    "reason": "probe",
                }
            if method == "GET" and path == "/api/sessions/orchestrator-513":
                return {
                    "id": "orchestrator-session",
                    "name": "orchestrator-513",
                    "cwd": str(actor),
                    "worktree_path": str(actor),
                    "scope": "/scope",
                    "task_id": "",
                    "base_branch": "main",
                    "is_orchestrator": True,
                }
            if method == "POST" and path == "/api/bg/jobs":
                jobs.append(kwargs["json"])
                return {"id": "bg-probe"}
            raise AssertionError((method, path, kwargs))

        mcp._api = fake_api
        mcp._codex_bin = lambda: "/usr/bin/codex"
        mcp.WORKER_NAME = "orchestrator-513"
        mcp.SCOPE = "/scope"
        await mcp.codex_review(
            context="PROJECT CONTEXT:\n- deterministic #513 probe",
            output=str(root / "review.md"),
            mode="implementation",
            model="gpt5.6luna",
        )
        receipt_id = jobs[0]["receipt_id"]
        db.review_receipt_finish(
            receipt_id,
            {
                "status": "completed",
                "completed_at": "2026-09-04T12:00:00+00:00",
                "return_code": 0,
                "artifact_exists": 1,
                "artifact_bytes": 10,
                "jsonl_response_present": 1,
                "coverage_outcome": "reviewed",
            },
        )
        receipt = db.review_receipt_get(receipt_id)
        assert receipt is not None
        decision = coverage_decision(
            scope="/scope",
            session_id="worker-session",
            task_id="513",
            target_sha=str(worker_subject["target_sha"]),
            worker_head=str(worker_subject["worker_head"]),
            production_paths=list(worker_subject["production_paths"]),
            production_snapshot_sha256=str(
                worker_subject["production_snapshot_sha256"]
            ),
            active=True,
            before="2026-09-04T12:01:00+00:00",
        )
        return {
            "detach_actor": detach_actor,
            "same_target_sha": receipt["target_sha"] == worker_subject["target_sha"],
            "same_worker_head": receipt["worker_head"] == worker_subject["worker_head"],
            "same_snapshot": (
                receipt["production_snapshot_sha256"]
                == worker_subject["production_snapshot_sha256"]
            ),
            "receipt_session_id": receipt["session_id"],
            "receipt_task_id": receipt["task_id"],
            "receipt_production_paths_json": receipt["production_paths_json"],
            "worker_gate_status": decision["status"],
            "worker_gate_reason": decision["reason"],
        }


async def main() -> None:
    print(json.dumps([
        await _scenario(detach_actor=False),
        await _scenario(detach_actor=True),
    ], indent=2))


if __name__ == "__main__":
    asyncio.run(main())
