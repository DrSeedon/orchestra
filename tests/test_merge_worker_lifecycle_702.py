from __future__ import annotations

import subprocess


def test_merge_refuses_the_workers_own_branch(tmp_path):
    from app.workspace import merge_worktree_to_main

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "base"], cwd=repo, check=True, capture_output=True)
    before = subprocess.run(
        ["git", "rev-parse", "main"], cwd=repo, check=True, capture_output=True, text=True,
    ).stdout.strip()

    result = merge_worktree_to_main(str(repo), str(repo), target_branch="main")

    after = subprocess.run(
        ["git", "rev-parse", "main"], cwd=repo, check=True, capture_output=True, text=True,
    ).stdout.strip()
    assert result["ok"] is False
    assert "same commit" in result["error"]
    assert result["commits_merged"] == 0
    assert before == after


