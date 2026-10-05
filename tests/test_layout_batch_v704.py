from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from starlette.requests import Request


@pytest.mark.asyncio
@pytest.mark.parametrize("existing_candidate", ["worktree", "cwd", "scope"])
async def test_t014_run_job_uses_callers_worktree_for_local_relative_paths(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, existing_candidate: str,
):
    import app.routes.bg as route
    import app.bg_jobs as bg_jobs

    target = SimpleNamespace(id="target-session")
    monkeypatch.setattr(route.manager, "get_by_name", lambda _name, _scope: target)
    candidates = {name: tmp_path / name for name in ("worktree", "cwd", "scope")}
    candidates[existing_candidate].mkdir()
    sessions = {
        "target-session": {"scope": str(tmp_path / "target")},
        "caller-session": {
            "scope": str(candidates["scope"]),
            "cwd": str(candidates["cwd"]),
            "worktree_path": str(candidates["worktree"]),
        },
    }
    monkeypatch.setattr("app.db.get_session", lambda session_id: sessions.get(session_id))
    monkeypatch.setattr("app.work_review.assignment", lambda *_args: None)
    create = AsyncMock(return_value={"id": "bg-test", "type": "run", "status": "active"})
    monkeypatch.setattr(bg_jobs.bg_manager, "create", create)
    request = Request({
        "type": "http",
        "headers": [(b"x-orchestra-session-id", b"caller-session")],
    })

    await route.bg_job_create(
        route.BgJobCreateRequest(
            type="run", config={"command": "pwd"}, target_name="target",
            target_scope="/target", created_by="caller",
        ),
        request,
    )

    assert create.await_args.kwargs["config"]["cwd"] == str(candidates[existing_candidate])


def test_t075_pycache_under_orchestra_is_ignored_after_unignore_rules(tmp_path: Path):
    repository = tmp_path / "ignore-check"
    repository.mkdir()
    root = Path(__file__).resolve().parents[1]
    (repository / ".gitignore").write_bytes((root / ".gitignore").read_bytes())
    (repository / ".orchestra/tasks/V-704/__pycache__").mkdir(parents=True)
    target = repository / ".orchestra/tasks/V-704/__pycache__/probe.pyc"
    target.write_bytes(b"compiled")
    subprocess.run(["git", "init", "-q", str(repository)], check=True)

    result = subprocess.run(
        ["git", "-C", str(repository), "check-ignore", "-v", str(target)],
        text=True, capture_output=True,
    )

    assert result.returncode == 0
    assert ".orchestra/**/__pycache__/" in result.stdout


def test_t147_path_check_runs_without_historical_blob_inventory(tmp_path: Path):
    root = Path(__file__).resolve().parents[1]
    repository = tmp_path / "foreign-history"
    repository.mkdir()
    subprocess.run(["git", "init", "-q", str(repository)], check=True)
    subprocess.run(["git", "config", "user.email", "task704@example.invalid"], cwd=repository, check=True)
    subprocess.run(["git", "config", "user.name", "task704"], cwd=repository, check=True)
    evidence = repository / "tests/fixture.py"
    evidence.parent.mkdir(parents=True)
    evidence.write_text("LEGACY_PATH_FIXTURE: docs/tasks/ belongs to this fixture\n")
    subprocess.run(["git", "add", "-A"], cwd=repository, check=True)
    subprocess.run(["git", "commit", "-qm", "fixture without historical inventory"], cwd=repository, check=True)

    result = subprocess.run(
        [sys.executable, str(root / "scripts/check_orchestra_paths.py"),
         "--root", str(repository), "--json"],
        text=True, capture_output=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert '"unclassified_old_path_occurrences": 0' in result.stdout
