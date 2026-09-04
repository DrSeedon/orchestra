import subprocess

import pytest


PROJECT_CONTEXT = """PROJECT CONTEXT:
- Scale: production orchestration platform
- Stack: Python, FastAPI, SQLite, Codex app-server
- What matters: provenance and data integrity
"""
PROJECT_CONTEXT_FILE = """schema_version = 1
scale = "production test platform"
users = "review receipt tests"
stack = "Python and SQLite"
philosophy = "explicit receipts"
what_matters = "provenance and data integrity"
what_does_not_matter = "deployment ceremony"
"""


def _prepare_project_context(repo):
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "receipt@test.invalid"], cwd=repo, check=True,
    )
    subprocess.run(["git", "config", "user.name", "Receipt Test"], cwd=repo, check=True)
    owner = repo / ".orchestra/project-context.toml"
    owner.parent.mkdir()
    owner.write_text(PROJECT_CONTEXT_FILE, encoding="utf-8")
    subprocess.run(
        ["git", "add", ".orchestra/project-context.toml"], cwd=repo, check=True,
    )
    subprocess.run(["git", "commit", "-m", "test owner"], cwd=repo, check=True, capture_output=True)
    shown = subprocess.run(
        ["git", "show", "main:.orchestra/project-context.toml"],
        cwd=repo, check=True, capture_output=True, text=True,
    ).stdout
    assert shown == PROJECT_CONTEXT_FILE, "receipt fixture did not establish its context owner"


def _readiness():
    return {
        "policy": "worker-weekly-v1",
        "state": "available",
        "model": "gpt-5.6-sol",
        "provider": "codex",
        "weekly_utilization": 1,
        "threshold": 95,
        "observed_at": 2_000_000_000,
        "valid_until": 2_000_000_300,
        "alternatives": [],
        "reason": "test",
    }


@pytest.mark.asyncio
async def test_start_receipt_uses_resolved_model_task_artifact_and_reserved_round(
    tmp_path, monkeypatch,
):
    import app.mcp_stdio as mcp

    _prepare_project_context(tmp_path)
    captured = {}

    async def fake_api(method, path, **kwargs):
        if path == "/api/usage/readiness":
            return _readiness()
        if method == "GET":
            return {
                "id": "requester-436",
                "cwd": str(tmp_path),
                "worktree_path": str(tmp_path),
                "scope": str(tmp_path),
                "task_id": "436",
            }
        captured.update(kwargs["json"])
        return {"id": "bg-436"}

    monkeypatch.setattr(mcp, "_api", fake_api)
    monkeypatch.setattr(mcp, "_codex_bin", lambda: "/usr/bin/codex")
    monkeypatch.setattr(mcp, "WORKER_NAME", "receipt-start-436")
    monkeypatch.setattr(mcp, "SCOPE", str(tmp_path))

    await mcp.codex_review(
        context=PROJECT_CONTEXT,
        target=".orchestra/tasks/436/plan.md",
        output=".orchestra/tasks/436/review.md",
        mode="exec",
        model="gpt5.6luna",
    )

    assert "receipt_id" in captured, "T2 start path must create a durable review receipt"
    assert captured["receipt"]["reviewer_model"] == "gpt-5.6-luna"
    assert captured["receipt"]["runtime"] == "codex"
    assert captured["receipt"]["task_id"] == "436"
    assert captured["receipt"]["artifact_path"].endswith(".orchestra/tasks/436/review.md")
    assert captured["receipt"]["round"] == 1
