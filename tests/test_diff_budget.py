"""#250: merge must refuse a diff too large to review.

Insertions count; deletions do not (dead-code removal is healthy).
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


@pytest.fixture
def git_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, capture_output=True)
    (repo / "README.md").write_text("# test\n")
    subprocess.run(["git", "add", "."], cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "branch", "-M", "main"], cwd=repo, capture_output=True, check=True)
    return repo


@pytest.fixture
def wt_root(tmp_path, monkeypatch):
    root = tmp_path / "worktrees"
    root.mkdir()
    monkeypatch.setattr("app.workspace.WORKTREE_ROOT", root)
    return root


def _commit_in_worktree(git_repo, wt_root, name: str, relpath: str, text: str, msg: str):
    from app.workspace import create_worktree

    wt = create_worktree(str(git_repo), name, base_branch="main")
    path = Path(wt.path) / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    subprocess.run(["git", "add", "."], cwd=wt.path, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", msg], cwd=wt.path, capture_output=True, check=True)
    return wt


def test_merge_refuses_when_insertions_exceed_budget(git_repo, wt_root):
    """Oracle: 2001 insertions must not land. 2000 is the backtested ceiling."""
    from app.workspace import merge_worktree_to_main

    payload = "".join(f"line-{i}\n" for i in range(2001))
    wt = _commit_in_worktree(git_repo, wt_root, "huge", "dump.txt", payload, "too big")
    res = merge_worktree_to_main(wt.path, str(git_repo))
    assert res.get("ok") is False, res
    err = (res.get("error") or "").lower()
    assert "2000" in err or "insertion" in err
    assert "split" in err
    assert res.get("diff_budget_waived") is False


def test_merge_allows_large_deletion_under_insertion_budget(git_repo, wt_root):
    bulky = git_repo / "legacy.txt"
    bulky.write_text("".join(f"old-{i}\n" for i in range(900)))
    subprocess.run(["git", "add", "."], cwd=git_repo, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "legacy"], cwd=git_repo, capture_output=True, check=True)

    from app.workspace import create_worktree, merge_worktree_to_main

    wt = create_worktree(str(git_repo), "delete-legacy", base_branch="main")
    (Path(wt.path) / "legacy.txt").unlink()
    subprocess.run(["git", "add", "-A"], cwd=wt.path, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "drop dead code"], cwd=wt.path, capture_output=True, check=True)
    res = merge_worktree_to_main(wt.path, str(git_repo))
    assert res.get("ok") is True, res


def test_merge_allows_exact_budget(git_repo, wt_root):
    from app.workspace import merge_worktree_to_main

    payload = "".join(f"line-{i}\n" for i in range(2000))
    wt = _commit_in_worktree(git_repo, wt_root, "exact", "ok.txt", payload, "at limit")
    res = merge_worktree_to_main(wt.path, str(git_repo))
    assert res.get("ok") is True, res
    assert res.get("diff_budget_waived") is False


def test_orchestrator_waiver_lands_and_is_visible(git_repo, wt_root):
    from app.workspace import merge_worktree_to_main

    payload = "".join(f"line-{i}\n" for i in range(2001))
    wt = _commit_in_worktree(git_repo, wt_root, "waived", "dump.txt", payload, "big on purpose")
    res = merge_worktree_to_main(
        wt.path, str(git_repo),
        waive_diff_budget=True, waived_by="Orchestra-orchestrator",
    )
    assert res.get("ok") is True, res
    assert res.get("diff_budget_waived") is True
    assert res.get("diff_budget_waived_by") == "Orchestra-orchestrator"
    assert res.get("diff_insertions") == 2001
    assert res.get("diff_budget_limit") == 2000


def test_worker_role_cannot_waive():
    from app.diff_budget import may_waive_diff_budget

    assert may_waive_diff_budget(caller_role="worker") is False
    assert may_waive_diff_budget(caller_role="full-cycle") is False
    assert may_waive_diff_budget(caller_role="orchestrator") is True
    assert may_waive_diff_budget(caller_role="sub-orchestrator") is True
    assert may_waive_diff_budget(caller_role="worker", cookie_ok=True) is True
    assert may_waive_diff_budget(caller_is_orchestrator=True) is True
