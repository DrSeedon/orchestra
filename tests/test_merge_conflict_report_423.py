from pathlib import Path
import subprocess


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True,
    )


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "tracked.txt").write_text("base\n")
    _git(repo, "add", "tracked.txt")
    _git(repo, "commit", "-m", "initial")
    _git(repo, "branch", "-M", "main")
    return repo


def _commit(path: Path, message: str) -> None:
    _git(path, "add", ".")
    _git(path, "commit", "-m", message)


def test_conflict_paths_and_resolution_action_are_preserved(tmp_path, monkeypatch):
    import app.merge_operations as operations
    import app.workspace as workspace

    repo = _repo(tmp_path)
    worktree_root = tmp_path / "worktrees"
    worktree_root.mkdir()
    monkeypatch.setattr(workspace, "WORKTREE_ROOT", worktree_root)
    worker = workspace.create_worktree(
        str(repo), "conflict-worker", task_id="423", base_branch="main",
    )
    worker_path = Path(worker.path)
    (worker_path / "tracked.txt").write_text("worker\n")
    _commit(worker_path, "worker change")

    (repo / "tracked.txt").write_text("target\n")
    _commit(repo, "target change")

    raw = workspace.merge_worktree_to_main(
        worker.path, str(repo), target_branch="main", waive_diff_budget=True,
    )
    assert raw["ok"] is False
    assert raw["conflicts"] == ["tracked.txt"]
    assert raw["error"] == "merge conflict in 1 file(s): tracked.txt"

    normalized = operations.normalize_merge_result(
        "423-conflict-operation",
        raw,
        operations.normalize_request(
            name="conflict-worker", scope=str(repo), target="main",
        ),
    )
    assert normalized["git"]["conflicts"] == ["tracked.txt"]
    assert normalized["error"]["code"] == "CONFLICT"
    assert normalized["error"]["code"] != "NO_COMMITS_MERGED"
    assert normalized["next_action"]["code"] == "RESOLVE_ON_WORKER_THEN_NEW_OPERATION"
    assert "tracked.txt" in normalized["error"]["message"]


def test_empty_branch_keeps_no_commits_merged_behavior(tmp_path, monkeypatch):
    import app.workspace as workspace

    repo = _repo(tmp_path)
    worktree_root = tmp_path / "worktrees"
    worktree_root.mkdir()
    monkeypatch.setattr(workspace, "WORKTREE_ROOT", worktree_root)
    worker = workspace.create_worktree(
        str(repo), "empty-worker", task_id="423", base_branch="main",
    )
    worker_path = Path(worker.path)
    (worker_path / "transient.txt").write_text("temporary\n")
    _commit(worker_path, "add transient file")
    _git(worker_path, "rm", "transient.txt")
    _git(worker_path, "commit", "-m", "remove transient file")

    result = workspace.merge_worktree_to_main(
        worker.path, str(repo), target_branch="main", waive_diff_budget=True,
    )

    assert result["ok"] is False
    assert result["code"] == "NO_COMMITS_MERGED"
    assert result["commits_merged"] == 0
    assert result["conflicts"] == []
    assert result["error"] == "merge produced no new commits"


def test_conflict_path_reader_preserves_newlines(tmp_path):
    import app.workspace as workspace

    repo = _repo(tmp_path)
    path = repo / "line\nbreak.txt"
    path.write_text("base\n")
    _commit(repo, "add unusual path")
    _git(repo, "checkout", "-b", "worker")
    path.write_text("worker\n")
    _commit(repo, "worker change")
    _git(repo, "checkout", "main")
    path.write_text("target\n")
    _commit(repo, "target change")

    merge = subprocess.run(
        ["git", "merge", "--squash", "worker"],
        cwd=repo, capture_output=True, text=True,
    )
    assert merge.returncode != 0
    assert workspace._conflict_paths(str(repo)) == ["line\nbreak.txt"]
    _git(repo, "reset", "--merge")
