"""Frozen regression oracles for #416 merge failure reason preservation."""

from pathlib import Path
import subprocess

import pytest


@pytest.mark.parametrize(
    ("raw_error", "expected_message"),
    [
        pytest.param(
            "target working tree is dirty (1 file(s): .orchestra/tasks/49/) "
            "— commit or discard first",
            "target working tree is dirty (1 file(s): .orchestra/tasks/49/) "
            "— commit or discard first",
            id="existing-raw-error",
        ),
        pytest.param(
            "",
            "merge produced no new commits",
            id="empty-raw-error",
        ),
    ],
)
def test_t1_noop_preserves_existing_error_or_uses_default(raw_error, expected_message):
    import app.merge_operations as operations

    raw = {
        "ok": True,
        "state": "merged",
        "commit_point": "not_reached",
        "target_branch": "main",
        "target_before": "a" * 40,
        "target_after": "a" * 40,
        "worker_branch": "task-416/worker",
        "worker_head": "b" * 40,
        "conflicts": [],
        "commits_merged": 0,
    }
    if raw_error:
        raw["error"] = raw_error

    result = operations.normalize_merge_result(
        "t1-operation",
        raw,
        operations.normalize_request(name="worker", scope="/scope", target="main"),
    )

    assert result["operation_state"] == "FAILED"
    assert result["commit_point"] == "NOT_REACHED"
    assert result["git"]["status"] == "FAILED"
    assert result["error"]["code"] == "NO_COMMITS_MERGED"
    assert result["error"]["message"] == expected_message


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True,
    )


def _make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "README.md").write_text("base\n")
    tracked_tasks = repo / ".orchestra" / "tasks" / "README.md"
    tracked_tasks.parent.mkdir(parents=True)
    tracked_tasks.write_text("tracked tasks root\n")
    _git(repo, "add", "README.md", ".orchestra/tasks/README.md")
    _git(repo, "commit", "-m", "initial")
    _git(repo, "branch", "-M", "main")
    return repo


def test_t2_dirty_target_path_files_and_action_reach_merge_caller(
    tmp_path, monkeypatch,
):
    import app.mcp_stdio as mcp
    import app.merge_operations as operations
    import app.workspace as workspace

    repo = _make_repo(tmp_path)
    worktree_root = tmp_path / "worktrees"
    worktree_root.mkdir()
    monkeypatch.setattr(workspace, "WORKTREE_ROOT", worktree_root)
    worker = workspace.create_worktree(
        str(repo), "reason-worker", task_id="416", base_branch="main",
    )
    worker_path = Path(worker.path)
    (worker_path / "worker.txt").write_text("worker payload\n")
    _git(worker_path, "add", "worker.txt")
    _git(worker_path, "commit", "-m", "#416: worker payload")
    dirty_file = repo / ".orchestra" / "tasks" / "49" / "research.md"
    dirty_file.parent.mkdir(parents=True)
    dirty_file.write_text("untracked target WIP\n")
    target_before = _git(repo, "rev-parse", "main").stdout.strip()

    raw = workspace.merge_worktree_to_main(
        worker.path, str(repo), target_branch="main", waive_diff_budget=True,
    )

    # The first assertion isolates the workspace message from normalization.
    assert str(repo.resolve()) in raw["error"]
    assert ".orchestra/tasks/49/" in raw["error"]
    normalized = operations.normalize_merge_result(
        "t2-operation",
        raw,
        operations.normalize_request(
            name="reason-worker", scope=str(repo), target="main",
            waive_diff_budget=True,
        ),
    )
    delivered = mcp._merge_tool_result(normalized)
    text = delivered.content[0].text

    assert raw["ok"] is False
    assert raw["target_before"] == raw["target_after"] == target_before
    assert normalized["error"]["code"] == "NO_COMMITS_MERGED"
    assert normalized["error"]["message"] == raw["error"]
    assert normalized["next_action"]["code"] == "CLEAN_TARGET_THEN_NEW_OPERATION"
    assert delivered.isError is True
    assert str(repo.resolve()) in text
    assert ".orchestra/tasks/49/" in text
    assert "Clean the target worktree, then start a new merge operation." in text
    assert "verify the worker branch" not in text
    assert "merge produced no new commits" not in text
    assert dirty_file.read_text() == "untracked target WIP\n"
    assert _git(repo, "rev-parse", "main").stdout.strip() == target_before
