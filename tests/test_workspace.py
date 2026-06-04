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

    def test_rollback_on_copy_failure(self, git_repo, wt_root, monkeypatch):
        # Task #39 Fix 5a: if PROJECT_FILES copy raises after `git worktree add`,
        # the just-created worktree must be rolled back (no orphan on disk/in git).
        import app.workspace as ws
        from app.workspace import create_worktree

        def boom(*a, **k):
            raise OSError("disk full")

        monkeypatch.setattr(ws.shutil, "copy2", boom)
        with pytest.raises(OSError, match="disk full"):
            create_worktree(str(git_repo), "worker-x", "/scope")
        wt_path = wt_root / "scope" / "worker-x"
        assert not wt_path.exists()
        listing = subprocess.run(
            ["git", "worktree", "list"], cwd=git_repo, capture_output=True, text=True,
        )
        assert "worker-x" not in listing.stdout

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


class TestCreateWorktreeManifest:
    """worktree_cfg из манифеста: copies/symlinks вместо хардкода PROJECT_FILES."""

    def test_symlink_from_manifest_created(self, git_repo, wt_root):
        from app.pipeline import Symlink, Worktree
        from app.workspace import create_worktree
        # docs_work живёт в основном репо (gitignored в реальности)
        (git_repo / "docs_work").mkdir()
        (git_repo / "docs_work" / "marker.txt").write_text("docs")
        cfg = Worktree(symlinks=[Symlink(source="docs_work", target="docs_work")],
                       copies=["CLAUDE.md"])
        wt = create_worktree(str(git_repo), "worker-1", "/scope", worktree_cfg=cfg)
        link = Path(wt.path) / "docs_work"
        assert link.is_symlink()
        assert link.resolve() == (git_repo / "docs_work").resolve()
        assert (link / "marker.txt").read_text() == "docs"

    def test_copies_from_manifest_only(self, git_repo, wt_root):
        from app.pipeline import Worktree
        from app.workspace import create_worktree
        # Untracked-файлы в основном репо (как .env/.mcp.json в реальном gitignore):
        # копируются ТОЛЬКО те, что в манифесте. extra.txt не в copies → не копируется.
        (git_repo / "copied.txt").write_text("yes")   # untracked, в copies
        (git_repo / "extra.txt").write_text("no")     # untracked, НЕ в copies
        cfg = Worktree(symlinks=[], copies=["copied.txt"])
        wt = create_worktree(str(git_repo), "worker-1", "/scope", worktree_cfg=cfg)
        wt_path = Path(wt.path)
        assert (wt_path / "copied.txt").read_text() == "yes"
        assert not (wt_path / "extra.txt").exists()

    def test_none_cfg_falls_back_to_project_files(self, git_repo, wt_root):
        from app.workspace import create_worktree
        # worktree_cfg=None → старое поведение: весь PROJECT_FILES, симлинков нет
        wt = create_worktree(str(git_repo), "worker-1", "/scope", worktree_cfg=None)
        wt_path = Path(wt.path)
        assert (wt_path / "CLAUDE.md").exists()
        assert (wt_path / ".env").exists()
        assert (wt_path / ".mcp.json").exists()
        assert not (wt_path / "docs_work").exists()

    def test_missing_symlink_source_skipped(self, git_repo, wt_root):
        from app.pipeline import Symlink, Worktree
        from app.workspace import create_worktree
        # source не существует → не падаем, симлинк не создан
        cfg = Worktree(symlinks=[Symlink(source="docs_work", target="docs_work")],
                       copies=["CLAUDE.md"])
        wt = create_worktree(str(git_repo), "worker-1", "/scope", worktree_cfg=cfg)
        assert not (Path(wt.path) / "docs_work").exists()
        assert (Path(wt.path) / "CLAUDE.md").exists()

    def test_symlink_source_escapes_via_real_symlink_skipped(self, tmp_path, wt_root):
        """source='docs_work' безопасен в спеке, но если repo/docs_work — симлинк
        НАРУЖУ (за repo и repo.parent) → resolved-containment отбрасывает, симлинк
        не создаётся (закрыт symlink-побег, который строковый валидатор не ловит)."""
        import os
        from app.pipeline import Symlink, Worktree
        from app.workspace import create_worktree
        # Репо на уровень глубже: repo.parent = work, evil — вне work.
        work = tmp_path / "work"
        work.mkdir()
        repo = work / "repo"
        repo.mkdir()
        subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)
        subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=repo, capture_output=True)
        subprocess.run(["git", "config", "user.name", "T"], cwd=repo, capture_output=True)
        (repo / "README.md").write_text("x")
        subprocess.run(["git", "add", "."], cwd=repo, capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", "i"], cwd=repo, capture_output=True, check=True)
        subprocess.run(["git", "branch", "-M", "main"], cwd=repo, capture_output=True, check=True)
        evil = tmp_path / "evil"          # вне repo.parent (work)
        evil.mkdir()
        (evil / "secret.txt").write_text("leak")
        os.symlink(str(evil), str(repo / "docs_work"))   # docs_work → наружу
        cfg = Worktree(symlinks=[Symlink(source="docs_work", target="docs_work")], copies=[])
        wt = create_worktree(str(repo), "w1", "/scope", worktree_cfg=cfg)
        assert not (Path(wt.path) / "docs_work").exists()  # побег отброшен

    def test_rollback_on_symlink_failure(self, git_repo, wt_root, monkeypatch):
        import app.workspace as ws
        from app.pipeline import Symlink, Worktree
        from app.workspace import create_worktree
        (git_repo / "docs_work").mkdir()

        def boom(*a, **k):
            raise OSError("symlink failed")

        monkeypatch.setattr(ws.os, "symlink", boom)
        cfg = Worktree(symlinks=[Symlink(source="docs_work", target="docs_work")],
                       copies=["CLAUDE.md"])
        with pytest.raises(OSError, match="symlink failed"):
            create_worktree(str(git_repo), "worker-x", "/scope", worktree_cfg=cfg)
        wt_path = wt_root / "scope" / "worker-x"
        assert not wt_path.exists()
        listing = subprocess.run(
            ["git", "worktree", "list"], cwd=git_repo, capture_output=True, text=True,
        )
        assert "worker-x" not in listing.stdout


class TestSwitchWorktreeBranch:
    def test_from_ref_used_for_merge_check(self, git_repo, wt_root):
        """switch_worktree_branch использует from_ref, а не hardcode main.

        Diverged-сценарий: feature/auth уходит вперёд main (коммит только в feature/auth).
        Воркер ответвлён от feature/auth — является ancestor feature/auth (ok).
        Старый код проверял --is-ancestor HEAD refs/heads/main → feature/auth ≠ ancestor main
        → возвращал error. Новый код с from_ref=refs/heads/feature/auth → ok=True.
        """
        from app.workspace import create_worktree, switch_worktree_branch

        # Создаём ветку фичи от текущего main-HEAD
        subprocess.run(["git", "branch", "feature/auth"], cwd=git_repo,
                       capture_output=True, check=True)

        # Делаем коммит ТОЛЬКО в feature/auth — main и feature/auth расходятся
        subprocess.run(["git", "checkout", "feature/auth"], cwd=git_repo,
                       capture_output=True, check=True)
        (Path(git_repo) / "feat.txt").write_text("feature work")
        subprocess.run(["git", "add", "."], cwd=git_repo, capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", "feat commit"], cwd=git_repo,
                       capture_output=True, check=True)
        subprocess.run(["git", "checkout", "main"], cwd=git_repo,
                       capture_output=True, check=True)

        # Воркер ответвляется от feature/auth (HEAD воркера == HEAD feature/auth → ancestor feature/auth)
        wt = create_worktree(str(git_repo), "worker-1", "/scope", base_branch="feature/auth")

        # Со старым hardcode refs/heads/main: HEAD воркера — НЕ ancestor main (есть расхождение)
        # → --is-ancestor возвращает 1 → функция вернула бы error "unmerged commits"
        # С from_ref=refs/heads/feature/auth: HEAD == feature/auth → ancestor → ok
        result = switch_worktree_branch(wt.path, "task-2/worker-1",
                                        from_ref="refs/heads/feature/auth")
        assert result.get("ok") is True, f"expected ok, got: {result}"


class TestMergeTarget:
    def _wt_with_commit(self, git_repo, wt_root, name, base):
        from app.workspace import create_worktree
        wt = create_worktree(str(git_repo), name, "/scope", base_branch=base)
        (Path(wt.path) / "new.txt").write_text("data")
        subprocess.run(["git", "add", "."], cwd=wt.path, capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", "work"], cwd=wt.path, capture_output=True, check=True)
        return wt

    def test_merge_into_feature_branch(self, git_repo, wt_root):
        from app.workspace import merge_worktree_to_main
        subprocess.run(["git", "branch", "feature/auth"], cwd=git_repo, capture_output=True, check=True)
        wt = self._wt_with_commit(git_repo, wt_root, "worker-1", "feature/auth")
        res = merge_worktree_to_main(wt.path, str(git_repo), target_branch="feature/auth")
        assert res["ok"] is True
        log_feat = subprocess.run(["git", "log", "--oneline", "feature/auth"], cwd=git_repo,
                                  capture_output=True, text=True).stdout
        log_main = subprocess.run(["git", "log", "--oneline", "main"], cwd=git_repo,
                                  capture_output=True, text=True).stdout
        assert "work" in log_feat
        assert "work" not in log_main

    def test_default_target_is_main(self, git_repo, wt_root):
        from app.workspace import merge_worktree_to_main
        wt = self._wt_with_commit(git_repo, wt_root, "worker-2", "main")
        res = merge_worktree_to_main(wt.path, str(git_repo))
        assert res["ok"] is True
        log_main = subprocess.run(["git", "log", "--oneline", "main"], cwd=git_repo,
                                  capture_output=True, text=True).stdout
        assert "work" in log_main

    def test_main_head_restored_after_merge(self, git_repo, wt_root):
        """После merge в feature/auth основной репо должен вернуться на main (save/restore HEAD)."""
        from app.workspace import merge_worktree_to_main
        subprocess.run(["git", "branch", "feature/auth"], cwd=git_repo, capture_output=True, check=True)
        wt = self._wt_with_commit(git_repo, wt_root, "worker-3", "feature/auth")
        merge_worktree_to_main(wt.path, str(git_repo), target_branch="feature/auth")
        head = subprocess.run(["git", "symbolic-ref", "--short", "HEAD"], cwd=git_repo,
                              capture_output=True, text=True).stdout.strip()
        assert head == "main", f"expected main, got {head}"

    def test_stash_pop_error_returned(self, git_repo, wt_root, monkeypatch):
        """Если stash pop возвращает ошибку — merge_worktree_to_main должен вернуть ok=False."""
        from app.workspace import merge_worktree_to_main
        import subprocess as real_subprocess

        wt = self._wt_with_commit(git_repo, wt_root, "worker-4", "main")
        # Делаем main "dirty" — чтобы функция вызвала stash (did_stash=True)
        (Path(git_repo) / "dirty.txt").write_text("dirty")

        original_run = real_subprocess.run

        def patched_run(cmd, **kw):
            # stash pop — симулируем провал (конфликт при восстановлении)
            if isinstance(cmd, list) and "stash" in cmd and "pop" in cmd:
                result = type("R", (), {"returncode": 1, "stdout": "", "stderr": "conflict during pop"})()
                return result
            return original_run(cmd, **kw)

        monkeypatch.setattr("app.workspace.subprocess.run", patched_run)
        res = merge_worktree_to_main(wt.path, str(git_repo))
        assert res.get("ok") is False, f"expected ok=False on stash pop failure, got: {res}"
        assert res.get("state") in ("stash_pop_failed", "dirty"), f"unexpected state: {res}"


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

    def test_acquires_merge_lock(self, git_repo, wt_root, monkeypatch):
        # Task #39 Fix 4: remove_worktree must hold .git/orchestra-merge.lock
        # (LOCK_EX) so it can't race a concurrent merge_worktree_to_main.
        import app.workspace as ws
        from app.workspace import create_worktree, remove_worktree

        wt = create_worktree(str(git_repo), "worker-1", "/scope")
        flocks = []
        monkeypatch.setattr(ws.fcntl, "flock", lambda f, op: flocks.append(op))
        remove_worktree(str(git_repo), wt.path)
        assert ws.fcntl.LOCK_EX in flocks  # exclusive lock taken
        assert ws.fcntl.LOCK_UN in flocks  # and released


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


class TestCleanupStaleWorktrees:
    def test_removes_stale_keeps_alive(self, git_repo, wt_root, monkeypatch):
        from app.workspace import create_worktree, cleanup_stale_worktrees
        wt_alive = create_worktree(str(git_repo), "alive-worker", "/scope")
        wt_stale = create_worktree(str(git_repo), "stale-worker", "/scope")

        monkeypatch.setattr("app.db.get_all_sessions", lambda: [
            {"worktree_path": wt_alive.path},
        ])

        removed = cleanup_stale_worktrees()
        assert len(removed) == 1
        assert wt_stale.path in removed[0]
        assert Path(wt_alive.path).exists()
        assert not Path(wt_stale.path).exists()

    def test_skips_dirty_worktree(self, git_repo, wt_root, monkeypatch):
        from app.workspace import create_worktree, cleanup_stale_worktrees
        wt = create_worktree(str(git_repo), "dirty-worker", "/scope")
        (Path(wt.path) / "uncommitted.txt").write_text("dirty")

        monkeypatch.setattr("app.db.get_all_sessions", lambda: [])

        removed = cleanup_stale_worktrees()
        assert len(removed) == 0
        assert Path(wt.path).exists()

    def test_skips_non_worktree_dirs(self, wt_root, monkeypatch):
        from app.workspace import cleanup_stale_worktrees
        scope_dir = wt_root / "some-scope"
        scope_dir.mkdir()
        random_dir = scope_dir / "not-a-worktree"
        random_dir.mkdir()

        monkeypatch.setattr("app.db.get_all_sessions", lambda: [])

        removed = cleanup_stale_worktrees()
        assert len(removed) == 0
        assert random_dir.exists()

    def test_empty_worktree_root(self, wt_root, monkeypatch):
        from app.workspace import cleanup_stale_worktrees
        monkeypatch.setattr("app.db.get_all_sessions", lambda: [])
        removed = cleanup_stale_worktrees()
        assert removed == []
