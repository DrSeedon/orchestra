"""TDD tests for workspace.py — git worktree management."""

import subprocess
from pathlib import Path

import pytest


@pytest.fixture
def git_repo(tmp_path):
    """Create a minimal git repo for worktree tests."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, capture_output=True)
    (repo / "README.md").write_text("# test")
    (repo / "CLAUDE.md").write_text("# instructions")
    (repo / ".mcp.json").write_text("{}")
    (repo / ".env").write_text("SECRET=123")
    subprocess.run(["git", "add", "."], cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "branch", "-M", "main"], cwd=repo, capture_output=True, check=True)
    return repo


@pytest.fixture
def wt_root(tmp_path, monkeypatch):
    """Override WORKTREE_ROOT to tmp dir."""
    root = tmp_path / "worktrees"
    root.mkdir()
    monkeypatch.setattr("app.workspace.WORKTREE_ROOT", root)
    return root


class TestCreateWorktree:
    def test_success(self, git_repo, wt_root):
        from app.workspace import create_worktree
        wt = create_worktree(str(git_repo), "worker-1", "/mnt/data/Projects/test")
        assert Path(wt.path).exists()
        assert Path(wt.path).is_dir()
        assert wt.branch.startswith("feat/")

    def test_scope_namespaced_path(self, git_repo, wt_root):
        from app.workspace import create_worktree
        wt = create_worktree(str(git_repo), "worker-1", "/mnt/data/Projects/test")
        assert "worktrees" in wt.path
        assert "worker-1" in wt.path
        assert wt_root in Path(wt.path).parents or Path(wt.path).parent.parent == wt_root

    def test_branch_scoped(self, git_repo, wt_root):
        from app.workspace import create_worktree
        wt = create_worktree(str(git_repo), "worker-1", "/mnt/data/Projects/test")
        assert "/" in wt.branch.removeprefix("feat/")

    def test_copies_project_files(self, git_repo, wt_root):
        from app.workspace import create_worktree
        wt = create_worktree(str(git_repo), "worker-1", "/mnt/data/Projects/test")
        wt_path = Path(wt.path)
        assert (wt_path / "CLAUDE.md").exists()
        assert (wt_path / ".mcp.json").exists()
        assert (wt_path / ".env").exists()

    def test_copies_from_parent_fallback(self, git_repo, wt_root):
        from app.workspace import create_worktree
        (git_repo / "CLAUDE.md").unlink()
        parent = git_repo.parent
        (parent / "CLAUDE.md").write_text("# parent instructions")
        wt = create_worktree(str(git_repo), "worker-1", "/mnt/data/Projects/test")
        assert (Path(wt.path) / "CLAUDE.md").read_text() == "# parent instructions"

    def test_exists_raises(self, git_repo, wt_root):
        from app.workspace import create_worktree
        create_worktree(str(git_repo), "worker-1", "/mnt/data/Projects/test")
        with pytest.raises(ValueError, match="already exists"):
            create_worktree(str(git_repo), "worker-1", "/mnt/data/Projects/test")

    def test_bad_repo_raises(self, wt_root):
        from app.workspace import create_worktree
        with pytest.raises(ValueError, match="does not exist"):
            create_worktree("/nonexistent/path", "worker-1", "/scope")

    def test_not_git_repo_raises(self, tmp_path, wt_root):
        from app.workspace import create_worktree
        not_git = tmp_path / "not-a-repo"
        not_git.mkdir()
        with pytest.raises(RuntimeError, match="failed"):
            create_worktree(str(not_git), "worker-1", "/scope")

    def test_existing_branch_reuses(self, git_repo, wt_root):
        from app.workspace import create_worktree, remove_worktree
        wt1 = create_worktree(str(git_repo), "worker-1", "/scope")
        remove_worktree(str(git_repo), wt1.path)
        wt2 = create_worktree(str(git_repo), "worker-1", "/scope")
        assert Path(wt2.path).exists()
        assert wt2.branch == wt1.branch

    def test_different_scopes_no_collision(self, git_repo, wt_root):
        from app.workspace import create_worktree
        wt1 = create_worktree(str(git_repo), "worker-1", "/scope/a")
        wt2 = create_worktree(str(git_repo), "worker-1", "/scope/b")
        assert wt1.path != wt2.path
        assert wt1.branch != wt2.branch
        assert Path(wt1.path).exists()
        assert Path(wt2.path).exists()

    def test_base_branch_param(self, git_repo, wt_root):
        from app.workspace import create_worktree
        subprocess.run(["git", "branch", "feature/auth"], cwd=git_repo, capture_output=True, check=True)
        wt = create_worktree(str(git_repo), "worker-1", "/scope", base_branch="feature/auth")
        head = subprocess.run(
            ["git", "rev-parse", "feature/auth"], cwd=git_repo, capture_output=True, text=True,
        ).stdout.strip()
        base = subprocess.run(
            ["git", "merge-base", wt.branch, "feature/auth"], cwd=git_repo, capture_output=True, text=True,
        ).stdout.strip()
        assert base == head


class TestRemoveWorktree:
    def test_removes(self, git_repo, wt_root):
        from app.workspace import create_worktree, remove_worktree
        wt = create_worktree(str(git_repo), "worker-1", "/scope")
        assert Path(wt.path).exists()
        remove_worktree(str(git_repo), wt.path)
        assert not Path(wt.path).exists()

    def test_nonexistent_no_error(self, git_repo, wt_root):
        from app.workspace import remove_worktree
        remove_worktree(str(git_repo), "/nonexistent/path")

    def test_git_fail_warns(self, git_repo, wt_root, caplog):
        from app.workspace import create_worktree, remove_worktree
        import logging
        wt = create_worktree(str(git_repo), "worker-1", "/scope")
        (Path(wt.path) / ".git").unlink()
        with caplog.at_level(logging.WARNING):
            remove_worktree(str(git_repo), wt.path)


class TestSlugify:
    def test_path_to_slug(self):
        from app.workspace import _slugify
        slug = _slugify("/mnt/data/Projects/Python/Parsing")
        assert "/" not in slug
        assert len(slug) > 0
        assert slug.replace("-", "").replace("_", "").isalnum()

    def test_deterministic(self):
        from app.workspace import _slugify
        assert _slugify("/some/path") == _slugify("/some/path")

    def test_different_paths_different_slugs(self):
        from app.workspace import _slugify
        assert _slugify("/path/a") != _slugify("/path/b")
