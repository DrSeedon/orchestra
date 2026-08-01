"""TDD tests for workspace.py — git worktree management."""

import shutil
import subprocess
import sys
import threading
from contextlib import contextmanager
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


class TestValidateRepoRoot:
    def test_accepts_primary_git_root(self, git_repo):
        from app.workspace import validate_repo_root

        assert validate_repo_root(f"{git_repo}/") == git_repo.resolve()

    def test_missing_path_raises(self, tmp_path):
        from app.workspace import validate_repo_root

        missing = tmp_path / "missing"
        with pytest.raises(ValueError, match="repo_path does not exist"):
            validate_repo_root(str(missing))

    def test_standalone_non_git_raises(self, tmp_path):
        from app.workspace import validate_repo_root

        not_git = tmp_path / "not-git"
        not_git.mkdir()
        with pytest.raises(ValueError, match="repo_path is not a Git repository"):
            validate_repo_root(str(not_git))

    def test_nested_directory_reports_discovered_root(self, git_repo):
        from app.workspace import validate_repo_root

        nested = git_repo / "src"
        nested.mkdir()
        with pytest.raises(ValueError, match="must be the Git repository root") as exc:
            validate_repo_root(str(nested))
        assert str(nested) in str(exc.value)
        assert str(git_repo) in str(exc.value)

    def test_linked_worktree_raises(self, git_repo, tmp_path):
        from app.workspace import validate_repo_root

        linked = tmp_path / "linked"
        subprocess.run(
            ["git", "worktree", "add", "-b", "linked-test", str(linked)],
            cwd=git_repo, capture_output=True, check=True,
        )
        with pytest.raises(ValueError, match="primary Git repository root"):
            validate_repo_root(str(linked))

    def test_primary_worktree_with_separate_git_dir_is_rejected(self, tmp_path):
        from app.workspace import validate_repo_root

        repo = tmp_path / "repo"
        git_dir = tmp_path / "repo-git"
        subprocess.run(
            ["git", "init", "--separate-git-dir", str(git_dir), str(repo)],
            capture_output=True, check=True,
        )

        with pytest.raises(
            ValueError, match="primary Git repository root.*gitfile repositories",
        ):
            validate_repo_root(str(repo))

    def test_symlinked_git_dir_is_rejected(self, git_repo, tmp_path):
        from app.workspace import validate_repo_root

        external_git_dir = tmp_path / "external-git-dir"
        (git_repo / ".git").rename(external_git_dir)
        (git_repo / ".git").symlink_to(external_git_dir, target_is_directory=True)

        with pytest.raises(
            ValueError, match="primary Git repository root.*external Git directories",
        ):
            validate_repo_root(str(git_repo))

    def test_bare_repository_raises(self, tmp_path):
        from app.workspace import validate_repo_root

        bare = tmp_path / "bare.git"
        subprocess.run(["git", "init", "--bare", str(bare)], capture_output=True, check=True)
        with pytest.raises(ValueError, match="bare Git repository.*primary working tree"):
            validate_repo_root(str(bare))


class TestCreateWorktree:
    def test_success(self, git_repo, wt_root):
        from app.workspace import _slugify, create_worktree
        wt = create_worktree(str(git_repo), "worker-1")
        assert Path(wt.path).exists()
        assert Path(wt.path).is_dir()
        assert wt.branch.startswith("feat/")

    def test_repo_namespaced_path(self, git_repo, wt_root):
        from app.workspace import _slugify, create_worktree
        wt = create_worktree(str(git_repo), "worker-1")
        assert "worktrees" in wt.path
        assert "worker-1" in wt.path
        assert wt_root in Path(wt.path).parents or Path(wt.path).parent.parent == wt_root
        assert Path(wt.path).parent.name == _slugify(str(git_repo.resolve()))

    def test_branch_namespaced_by_repo(self, git_repo, wt_root):
        from app.workspace import _slugify, create_worktree
        wt = create_worktree(str(git_repo), "worker-1")
        assert wt.branch == f"feat/{_slugify(str(git_repo.resolve()))}/worker-1"

    def test_copies_project_files(self, git_repo, wt_root):
        from app.workspace import create_worktree
        wt = create_worktree(str(git_repo), "worker-1")
        wt_path = Path(wt.path)
        assert (wt_path / "CLAUDE.md").exists()
        assert (wt_path / ".mcp.json").exists()
        assert (wt_path / ".env").exists()

    def test_copies_from_parent_fallback(self, git_repo, wt_root):
        from app.workspace import create_worktree
        (git_repo / "CLAUDE.md").unlink()
        parent = git_repo.parent
        (parent / "CLAUDE.md").write_text("# parent instructions")
        wt = create_worktree(str(git_repo), "worker-1")
        assert (Path(wt.path) / "CLAUDE.md").read_text() == "# parent instructions"

    def test_exists_raises(self, git_repo, wt_root):
        from app.workspace import create_worktree
        create_worktree(str(git_repo), "worker-1")
        with pytest.raises(ValueError, match="already exists"):
            create_worktree(str(git_repo), "worker-1")

    def test_injected_claude_dir_not_dirty(self, git_repo, wt_root):
        """create_worktree excludes `.claude/` → injected skills don't dirty the tree
        or block merge (repo has no `.claude/` in .gitignore = external-repo case)."""
        from app.workspace import create_worktree
        wt = create_worktree(str(git_repo), "worker-1")
        wt_path = Path(wt.path)
        (wt_path / ".claude" / "skills" / "foo").mkdir(parents=True)
        (wt_path / ".claude" / "skills" / "foo" / "SKILL.md").write_text("x")
        status = subprocess.run(
            ["git", "status", "--porcelain"], cwd=wt_path, capture_output=True, text=True,
        )
        assert status.stdout.strip() == ""

    def test_exclude_claude_dir_idempotent(self, git_repo, wt_root):
        from app.workspace import create_worktree, _exclude_claude_dir
        wt = create_worktree(str(git_repo), "worker-1")
        _exclude_claude_dir(Path(wt.path))  # second call (create already ran it once)
        common = subprocess.run(
            ["git", "rev-parse", "--git-common-dir"],
            cwd=wt.path, capture_output=True, text=True,
        ).stdout.strip()
        exclude = (Path(wt.path) / common / "info" / "exclude").resolve()
        assert exclude.read_text().count(".claude/") == 1

    def test_bad_repo_raises(self, wt_root):
        from app.workspace import create_worktree
        with pytest.raises(ValueError, match="does not exist"):
            create_worktree("/nonexistent/path", "worker-1")

    def test_not_git_repo_raises(self, tmp_path, wt_root):
        from app.workspace import create_worktree
        not_git = tmp_path / "not-a-repo"
        not_git.mkdir()
        with pytest.raises(ValueError, match="repo_path is not a Git repository"):
            create_worktree(str(not_git), "worker-1")

    def test_nested_repo_path_raises_instead_of_using_parent(self, git_repo, wt_root):
        from app.workspace import create_worktree

        nested = git_repo / "nested"
        nested.mkdir()
        with pytest.raises(ValueError, match="must be the Git repository root"):
            create_worktree(str(nested), "worker-1")

    def test_worktree_belongs_to_requested_repo(self, git_repo, wt_root):
        from app.workspace import create_worktree

        wt = create_worktree(str(git_repo), "worker-1")
        common = subprocess.run(
            ["git", "rev-parse", "--git-common-dir"],
            cwd=wt.path, capture_output=True, text=True, check=True,
        ).stdout.strip()
        assert Path(common).resolve() == (git_repo / ".git").resolve()

    def test_existing_branch_reuses(self, git_repo, wt_root):
        from app.workspace import create_worktree, remove_worktree
        wt1 = create_worktree(str(git_repo), "worker-1")
        remove_worktree(str(git_repo), wt1.path)
        wt2 = create_worktree(str(git_repo), "worker-1")
        assert Path(wt2.path).exists()
        assert wt2.branch == wt1.branch

    def test_branch_inspection_error_does_not_create_or_delete_ref(
        self, git_repo, wt_root, monkeypatch,
    ):
        import app.workspace as workspace
        from app.workspace import _slugify, create_worktree

        real_git_cmd = workspace._git_cmd

        def fail_show_ref(args, **kwargs):
            if args[:4] == ["git", "show-ref", "--verify", "--quiet"]:
                return subprocess.CompletedProcess(args, 128, "", "simulated read failure")
            return real_git_cmd(args, **kwargs)

        monkeypatch.setattr(workspace, "_git_cmd", fail_show_ref)
        with pytest.raises(RuntimeError, match="cannot inspect branch.*simulated read failure"):
            create_worktree(str(git_repo), "worker-inspect")

        branch_ref = f"refs/heads/feat/{_slugify(str(git_repo.resolve()))}/worker-inspect"
        assert subprocess.run(
            ["git", "show-ref", "--verify", branch_ref],
            cwd=git_repo, capture_output=True,
        ).returncode != 0

    def test_failed_add_does_not_delete_concurrently_advanced_ref(
        self, git_repo, wt_root, monkeypatch,
    ):
        import app.workspace as workspace
        from app.workspace import _slugify, create_worktree

        external_oid = subprocess.run(
            ["git", "commit-tree", "HEAD^{tree}", "-p", "HEAD", "-m", "external"],
            cwd=git_repo, capture_output=True, text=True, check=True,
        ).stdout.strip()
        real_git_cmd = workspace._git_cmd
        branch_ref = f"refs/heads/feat/{_slugify(str(git_repo.resolve()))}/worker-cas"

        def fail_add_after_advance(args, **kwargs):
            if args[:3] == ["git", "worktree", "add"]:
                real_git_cmd(
                    ["git", "update-ref", branch_ref, external_oid],
                    cwd=str(git_repo), capture_output=True, text=True,
                )
                return subprocess.CompletedProcess(args, 1, "", "simulated add failure")
            return real_git_cmd(args, **kwargs)

        monkeypatch.setattr(workspace, "_git_cmd", fail_add_after_advance)
        with pytest.raises(RuntimeError, match="worktree add failed"):
            create_worktree(str(git_repo), "worker-cas")

        assert subprocess.run(
            ["git", "rev-parse", branch_ref], cwd=git_repo,
            capture_output=True, text=True, check=True,
        ).stdout.strip() == external_oid

    def test_rollback_on_copy_failure(self, git_repo, wt_root, monkeypatch):
        # Task #39 Fix 5a: if PROJECT_FILES copy raises after `git worktree add`,
        # the just-created worktree must be rolled back (no orphan on disk/in git).
        import app.workspace as ws
        from app.workspace import _slugify, create_worktree

        real_git_cmd = ws._git_cmd

        def fail_copy(args, **kwargs):
            if args[:2] == ["cp", "-p"]:
                return subprocess.CompletedProcess(
                    args, returncode=1, stdout="", stderr="disk full",
                )
            return real_git_cmd(args, **kwargs)

        monkeypatch.setattr(ws, "_git_cmd", fail_copy)
        with pytest.raises(OSError, match="disk full"):
            create_worktree(str(git_repo), "worker-x")
        wt_path = wt_root / _slugify(str(git_repo.resolve())) / "worker-x"
        assert not wt_path.exists()
        listing = subprocess.run(
            ["git", "worktree", "list"], cwd=git_repo, capture_output=True, text=True,
        )
        assert "worker-x" not in listing.stdout
        branch_ref = f"refs/heads/feat/{_slugify(str(git_repo.resolve()))}/worker-x"
        assert subprocess.run(
            ["git", "show-ref", "--verify", branch_ref],
            cwd=git_repo, capture_output=True,
        ).returncode != 0

    def test_setup_cleanup_restores_ref_when_worktree_removal_fails(
        self, git_repo, wt_root, monkeypatch,
    ):
        import app.workspace as workspace
        from app.workspace import _slugify, create_worktree

        real_git_cmd = workspace._git_cmd

        def fail_copy_and_remove(args, **kwargs):
            if args[:2] == ["cp", "-p"]:
                return subprocess.CompletedProcess(args, 1, "", "disk full")
            if args[:3] == ["git", "worktree", "remove"]:
                return subprocess.CompletedProcess(args, 1, "", "metadata busy")
            return real_git_cmd(args, **kwargs)

        monkeypatch.setattr(workspace, "_git_cmd", fail_copy_and_remove)
        with pytest.raises(RuntimeError, match="worktree remove: metadata busy"):
            create_worktree(str(git_repo), "worker-partial")

        branch = f"feat/{_slugify(str(git_repo.resolve()))}/worker-partial"
        assert subprocess.run(
            ["git", "show-ref", "--verify", f"refs/heads/{branch}"],
            cwd=git_repo, capture_output=True,
        ).returncode == 0
        assert subprocess.run(
            ["git", "worktree", "list", "--porcelain"],
            cwd=git_repo, capture_output=True, text=True, check=True,
        ).stdout.find("worker-partial") >= 0

    def test_different_repos_no_collision(self, tmp_path, git_repo, wt_root):
        from app.workspace import create_worktree
        other = tmp_path / "other-repo"
        other.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=other, check=True)
        subprocess.run(["git", "config", "user.email", "t@t"], cwd=other, check=True)
        subprocess.run(["git", "config", "user.name", "t"], cwd=other, check=True)
        (other / "f.txt").write_text("x")
        subprocess.run(["git", "add", "-A"], cwd=other, check=True)
        subprocess.run(["git", "commit", "-qm", "init"], cwd=other, check=True)
        subprocess.run(["git", "branch", "-M", "main"], cwd=other, check=True)

        wt1 = create_worktree(str(git_repo), "worker-1")
        wt2 = create_worktree(str(other), "worker-1")
        assert wt1.path != wt2.path
        assert wt1.branch != wt2.branch
        assert Path(wt1.path).exists()
        assert Path(wt2.path).exists()

    def test_base_branch_param(self, git_repo, wt_root):
        from app.workspace import create_worktree
        subprocess.run(["git", "branch", "feature/auth"], cwd=git_repo, capture_output=True, check=True)
        wt = create_worktree(str(git_repo), "worker-1", base_branch="feature/auth")
        head = subprocess.run(
            ["git", "rev-parse", "feature/auth"], cwd=git_repo, capture_output=True, text=True,
        ).stdout.strip()
        base = subprocess.run(
            ["git", "merge-base", wt.branch, "feature/auth"], cwd=git_repo, capture_output=True, text=True,
        ).stdout.strip()
        assert base == head


class TestResolveBaseBranch:
    def test_master_only_repository(self, git_repo, wt_root):
        from app.workspace import create_worktree, resolve_base_branch

        subprocess.run(["git", "branch", "-m", "master"], cwd=git_repo, check=True)
        assert resolve_base_branch(str(git_repo)) == "master"
        wt = create_worktree(str(git_repo), "master-worker")
        assert subprocess.run(
            ["git", "merge-base", wt.branch, "master"], cwd=git_repo,
            capture_output=True, text=True, check=True,
        ).stdout.strip() == subprocess.run(
            ["git", "rev-parse", "master"], cwd=git_repo,
            capture_output=True, text=True, check=True,
        ).stdout.strip()

    def test_current_feature_checkout_does_not_override_mainline(self, git_repo):
        from app.workspace import resolve_base_branch

        subprocess.run(["git", "checkout", "-b", "feature/current"], cwd=git_repo, check=True)
        assert resolve_base_branch(str(git_repo)) == "main"

    def test_both_well_known_branches_require_explicit_base(self, git_repo):
        from app.workspace import resolve_base_branch

        subprocess.run(["git", "branch", "master"], cwd=git_repo, check=True)
        with pytest.raises(ValueError, match="both main and master"):
            resolve_base_branch(str(git_repo))
        assert resolve_base_branch(str(git_repo), "refs/heads/master") == "master"

    def test_symbolic_remote_head_disambiguates_main_and_master(self, git_repo):
        from app.workspace import resolve_base_branch

        subprocess.run(["git", "branch", "master"], cwd=git_repo, check=True)
        head = subprocess.run(
            ["git", "rev-parse", "main"], cwd=git_repo,
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        subprocess.run(
            ["git", "update-ref", "refs/remotes/origin/main", head],
            cwd=git_repo, check=True,
        )
        subprocess.run(
            ["git", "symbolic-ref", "refs/remotes/origin/HEAD",
             "refs/remotes/origin/main"],
            cwd=git_repo, check=True,
        )
        assert resolve_base_branch(str(git_repo)) == "main"

    def test_custom_trunk_requires_explicit_base(self, git_repo):
        from app.workspace import resolve_base_branch

        subprocess.run(["git", "branch", "-m", "trunk"], cwd=git_repo, check=True)
        with pytest.raises(ValueError, match="pass base_branch explicitly"):
            resolve_base_branch(str(git_repo))
        assert resolve_base_branch(str(git_repo), "trunk") == "trunk"


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
        wt = create_worktree(str(git_repo), "worker-1", worktree_cfg=cfg)
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
        wt = create_worktree(str(git_repo), "worker-1", worktree_cfg=cfg)
        wt_path = Path(wt.path)
        assert (wt_path / "copied.txt").read_text() == "yes"
        assert not (wt_path / "extra.txt").exists()

    def test_none_cfg_falls_back_to_project_files(self, git_repo, wt_root):
        from app.workspace import create_worktree
        # worktree_cfg=None → старое поведение: весь PROJECT_FILES, симлинков нет
        wt = create_worktree(str(git_repo), "worker-1", worktree_cfg=None)
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
        wt = create_worktree(str(git_repo), "worker-1", worktree_cfg=cfg)
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
        wt = create_worktree(str(repo), "w1", worktree_cfg=cfg)
        assert not (Path(wt.path) / "docs_work").exists()  # побег отброшен

    def test_rollback_on_symlink_failure(self, git_repo, wt_root, monkeypatch):
        import app.workspace as ws
        from app.pipeline import Symlink, Worktree
        from app.workspace import _slugify, create_worktree
        (git_repo / "docs_work").mkdir()

        def boom(*a, **k):
            raise OSError("symlink failed")

        monkeypatch.setattr(ws.os, "symlink", boom)
        cfg = Worktree(symlinks=[Symlink(source="docs_work", target="docs_work")],
                       copies=["CLAUDE.md"])
        with pytest.raises(OSError, match="symlink failed"):
            create_worktree(str(git_repo), "worker-x", worktree_cfg=cfg)
        wt_path = wt_root / _slugify(str(git_repo.resolve())) / "worker-x"
        assert not wt_path.exists()
        listing = subprocess.run(
            ["git", "worktree", "list"], cwd=git_repo, capture_output=True, text=True,
        )
        assert "worker-x" not in listing.stdout


class TestSwitchWorktreeBranch:
    def test_new_branch_creation_failure_restores_original_without_quarantine(
        self, git_repo, wt_root, monkeypatch,
    ):
        import app.workspace as workspace
        from app.workspace import create_worktree, switch_worktree_branch

        wt = create_worktree(str(git_repo), "worker-create-fail", task_id="1")
        old_branch = wt.branch
        old_head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=wt.path,
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        target = "task-2/worker-create-fail"

        def fail_create(_repo, _branch, _oid):
            raise RuntimeError("simulated branch creation failure")

        monkeypatch.setattr(workspace, "_create_branch_ref", fail_create)

        result = switch_worktree_branch(
            wt.path, target, from_ref="main", force=True,
        )

        assert result["ok"] is False
        assert result.get("state") != "rollback_failed"
        assert "simulated branch creation failure" in result["error"]
        assert subprocess.run(
            ["git", "branch", "--show-current"], cwd=wt.path,
            capture_output=True, text=True, check=True,
        ).stdout.strip() == old_branch
        assert subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=wt.path,
            capture_output=True, text=True, check=True,
        ).stdout.strip() == old_head
        assert subprocess.run(
            ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{target}"],
            cwd=git_repo, capture_output=True,
        ).returncode == 1

    def test_force_busy_target_preserves_original_branch_and_refs(
        self, git_repo, wt_root,
    ):
        from app.workspace import create_worktree, switch_worktree_branch

        wt = create_worktree(str(git_repo), "worker-busy", task_id="1")
        (Path(wt.path) / "worker.txt").write_text("unmerged")
        subprocess.run(["git", "add", "worker.txt"], cwd=wt.path, check=True)
        subprocess.run(["git", "commit", "-m", "worker work"], cwd=wt.path, check=True)
        old_branch = wt.branch
        old_head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=wt.path,
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        target = "task-2/worker-busy"
        subprocess.run(["git", "branch", target, "main"], cwd=git_repo, check=True)
        target_head = subprocess.run(
            ["git", "rev-parse", target], cwd=git_repo,
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        owner = wt_root / "target-owner"
        subprocess.run(
            ["git", "worktree", "add", str(owner), target],
            cwd=git_repo, capture_output=True, check=True,
        )

        result = switch_worktree_branch(
            wt.path, target, from_ref="main", force=True,
        )

        assert result["ok"] is False
        assert "checked out in another worktree" in result["error"]
        assert subprocess.run(
            ["git", "branch", "--show-current"], cwd=wt.path,
            capture_output=True, text=True, check=True,
        ).stdout.strip() == old_branch
        assert subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=wt.path,
            capture_output=True, text=True, check=True,
        ).stdout.strip() == old_head
        assert subprocess.run(
            ["git", "rev-parse", target], cwd=git_repo,
            capture_output=True, text=True, check=True,
        ).stdout.strip() == target_head
        assert subprocess.run(
            ["git", "status", "--porcelain"], cwd=wt.path,
            capture_output=True, text=True, check=True,
        ).stdout == ""

    def test_force_merge_conflict_rolls_back_all_git_state(
        self, git_repo, wt_root,
    ):
        from app.workspace import create_worktree, switch_worktree_branch

        conflict_path = "shared file.txt"
        (Path(git_repo) / conflict_path).write_text("base\n")
        subprocess.run(["git", "add", conflict_path], cwd=git_repo, check=True)
        subprocess.run(["git", "commit", "-m", "shared base"], cwd=git_repo, check=True)
        target = "task-2/worker-conflict"
        subprocess.run(["git", "branch", target], cwd=git_repo, check=True)
        target_owner = wt_root / "conflict-owner"
        subprocess.run(
            ["git", "worktree", "add", str(target_owner), target],
            cwd=git_repo, capture_output=True, check=True,
        )
        (target_owner / "shared.txt").write_text("target\n")
        subprocess.run(["git", "add", "shared.txt"], cwd=target_owner, check=True)
        subprocess.run(["git", "commit", "-m", "target edit"], cwd=target_owner, check=True)
        subprocess.run(
            ["git", "worktree", "remove", str(target_owner)],
            cwd=git_repo, capture_output=True, check=True,
        )
        target_head = subprocess.run(
            ["git", "rev-parse", target], cwd=git_repo,
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        (Path(git_repo) / "shared.txt").write_text("main\n")
        subprocess.run(["git", "add", "shared.txt"], cwd=git_repo, check=True)
        subprocess.run(["git", "commit", "-m", "main edit"], cwd=git_repo, check=True)
        wt = create_worktree(str(git_repo), "worker-conflict", task_id="1")
        old_branch = wt.branch
        old_head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=wt.path,
            capture_output=True, text=True, check=True,
        ).stdout.strip()

        result = switch_worktree_branch(
            wt.path, target, from_ref="main", force=True,
        )

        assert result["ok"] is False
        assert result["conflicts"] == ["shared.txt"]
        assert subprocess.run(
            ["git", "branch", "--show-current"], cwd=wt.path,
            capture_output=True, text=True, check=True,
        ).stdout.strip() == old_branch
        assert subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=wt.path,
            capture_output=True, text=True, check=True,
        ).stdout.strip() == old_head
        assert subprocess.run(
            ["git", "rev-parse", target], cwd=git_repo,
            capture_output=True, text=True, check=True,
        ).stdout.strip() == target_head
        assert subprocess.run(
            ["git", "status", "--porcelain"], cwd=wt.path,
            capture_output=True, text=True, check=True,
        ).stdout == ""
        assert subprocess.run(
            ["git", "rev-parse", "--quiet", "--verify", "MERGE_HEAD"],
            cwd=wt.path, capture_output=True,
        ).returncode != 0

    def test_rollback_command_failure_returns_actual_snapshot(
        self, git_repo, wt_root, monkeypatch,
    ):
        import app.workspace as workspace
        from app.workspace import create_worktree, switch_worktree_branch

        wt = create_worktree(str(git_repo), "worker-rollback", task_id="1")
        target = "task-2/worker-rollback"
        subprocess.run(["git", "branch", target, "main"], cwd=git_repo, check=True)
        real_git_cmd = workspace._git_cmd

        def fail_checkout(args, **kwargs):
            if args == ["git", "checkout", target]:
                return subprocess.CompletedProcess(args, 1, "", "target checkout failed")
            if args == ["git", "checkout", wt.branch]:
                return subprocess.CompletedProcess(args, 1, "", "restore checkout failed")
            return real_git_cmd(args, **kwargs)

        monkeypatch.setattr(workspace, "_git_cmd", fail_checkout)
        result = switch_worktree_branch(
            wt.path, target, from_ref="main", force=True,
        )

        assert result["ok"] is False
        assert result["state"] == "rollback_failed"
        assert result["actual_branch"] == "HEAD"
        assert result["actual_head"]
        assert "restore checkout failed" in result["error"]

    def test_rollback_does_not_rewind_concurrently_advanced_target(
        self, git_repo, wt_root, monkeypatch,
    ):
        import app.workspace as workspace
        from app.workspace import create_worktree, switch_worktree_branch

        wt = create_worktree(str(git_repo), "worker-concurrent", task_id="1")
        target = "task-2/worker-concurrent"
        subprocess.run(["git", "branch", target, "main"], cwd=git_repo, check=True)
        external_oid = subprocess.run(
            ["git", "commit-tree", "HEAD^{tree}", "-p", "HEAD", "-m", "external"],
            cwd=git_repo, capture_output=True, text=True, check=True,
        ).stdout.strip()
        real_git_cmd = workspace._git_cmd

        def fail_checkout_after_advance(args, **kwargs):
            if args == ["git", "checkout", target]:
                real_git_cmd(
                    ["git", "update-ref", f"refs/heads/{target}", external_oid],
                    cwd=str(git_repo), capture_output=True, text=True,
                )
                return subprocess.CompletedProcess(args, 1, "", "simulated checkout failure")
            return real_git_cmd(args, **kwargs)

        monkeypatch.setattr(workspace, "_git_cmd", fail_checkout_after_advance)
        result = switch_worktree_branch(
            wt.path, target, from_ref="main", force=True,
        )

        assert result["ok"] is False
        assert result["state"] == "rollback_failed"
        assert "changed concurrently" in result["error"]
        assert subprocess.run(
            ["git", "rev-parse", target], cwd=git_repo,
            capture_output=True, text=True, check=True,
        ).stdout.strip() == external_oid

    def test_created_target_claimed_elsewhere_is_preserved_and_quarantined(
        self, git_repo, wt_root, monkeypatch,
    ):
        import app.workspace as workspace
        from app.workspace import create_worktree, switch_worktree_branch

        wt = create_worktree(str(git_repo), "worker-claimed", task_id="1")
        target = "task-2/worker-claimed"
        claimant = wt_root / "target-claimant"
        real_git_cmd = workspace._git_cmd

        def claim_before_checkout(args, **kwargs):
            if args == ["git", "checkout", target]:
                subprocess.run(
                    ["git", "worktree", "add", str(claimant), target],
                    cwd=git_repo, capture_output=True, check=True,
                )
                return subprocess.CompletedProcess(args, 128, "", "branch became busy")
            return real_git_cmd(args, **kwargs)

        monkeypatch.setattr(workspace, "_git_cmd", claim_before_checkout)
        result = switch_worktree_branch(
            wt.path, target, from_ref="main", force=True,
        )

        assert result["ok"] is False
        assert result["state"] == "rollback_failed"
        assert "ownership is uncertain" in result["error"]
        assert subprocess.run(
            ["git", "branch", "--show-current"], cwd=claimant,
            capture_output=True, text=True, check=True,
        ).stdout.strip() == target
        assert subprocess.run(
            ["git", "show-ref", "--verify", f"refs/heads/{target}"],
            cwd=git_repo, capture_output=True,
        ).returncode == 0

    def test_successful_force_switch_retains_original_branch(
        self, git_repo, wt_root,
    ):
        from app.workspace import create_worktree, switch_worktree_branch

        wt = create_worktree(str(git_repo), "worker-retained", task_id="1")
        (Path(wt.path) / "unmerged.txt").write_text("retain me")
        subprocess.run(["git", "add", "unmerged.txt"], cwd=wt.path, check=True)
        subprocess.run(["git", "commit", "-m", "unmerged"], cwd=wt.path, check=True)
        old_head = subprocess.run(
            ["git", "rev-parse", wt.branch], cwd=git_repo,
            capture_output=True, text=True, check=True,
        ).stdout.strip()

        result = switch_worktree_branch(
            wt.path, "task-2/worker-retained", from_ref="main", force=True,
        )

        assert result == {"ok": True, "branch": "task-2/worker-retained"}
        assert subprocess.run(
            ["git", "rev-parse", wt.branch], cwd=git_repo,
            capture_output=True, text=True, check=True,
        ).stdout.strip() == old_head

    def test_same_branch_is_rejected_without_mutation(self, git_repo, wt_root):
        from app.workspace import create_worktree, switch_worktree_branch

        wt = create_worktree(str(git_repo), "worker-same", task_id="1")
        old_head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=wt.path,
            capture_output=True, text=True, check=True,
        ).stdout.strip()

        result = switch_worktree_branch(
            wt.path, wt.branch, from_ref="main", force=True,
        )

        assert result["ok"] is False
        assert "already on branch" in result["error"]
        assert subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=wt.path,
            capture_output=True, text=True, check=True,
        ).stdout.strip() == old_head

    def test_symbolic_ref_operational_error_aborts_before_mutation(
        self, git_repo, wt_root, monkeypatch,
    ):
        import app.workspace as workspace
        from app.workspace import create_worktree, switch_worktree_branch

        wt = create_worktree(str(git_repo), "worker-symbolic", task_id="1")
        old_head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=wt.path,
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        real_git_cmd = workspace._git_cmd

        def fail_symbolic_ref(args, **kwargs):
            if args == ["git", "symbolic-ref", "--quiet", "--short", "HEAD"]:
                return subprocess.CompletedProcess(args, 128, "", "inspection failed")
            return real_git_cmd(args, **kwargs)

        monkeypatch.setattr(workspace, "_git_cmd", fail_symbolic_ref)
        result = switch_worktree_branch(
            wt.path, "task-2/worker-symbolic", from_ref="main", force=True,
        )

        assert result == {
            "ok": False,
            "error": "cannot inspect current branch: inspection failed",
        }
        assert subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=wt.path,
            capture_output=True, text=True, check=True,
        ).stdout.strip() == old_head
        assert subprocess.run(
            ["git", "show-ref", "--verify", "refs/heads/task-2/worker-symbolic"],
            cwd=git_repo, capture_output=True,
        ).returncode != 0

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
        wt = create_worktree(str(git_repo), "worker-1", base_branch="feature/auth")

        # Со старым hardcode refs/heads/main: HEAD воркера — НЕ ancestor main (есть расхождение)
        # → --is-ancestor возвращает 1 → функция вернула бы error "unmerged commits"
        # С from_ref=refs/heads/feature/auth: HEAD == feature/auth → ancestor → ok
        result = switch_worktree_branch(wt.path, "task-2/worker-1",
                                        from_ref="refs/heads/feature/auth")
        assert result.get("ok") is True, f"expected ok, got: {result}"

    def test_squash_merged_content_switches_after_base_advances(self, git_repo, wt_root):
        from app.workspace import create_worktree, switch_worktree_branch

        wt = create_worktree(str(git_repo), "worker-squash")
        (Path(wt.path) / "one.txt").write_text("one")
        subprocess.run(["git", "add", "one.txt"], cwd=wt.path, check=True)
        subprocess.run(["git", "commit", "-m", "worker one"], cwd=wt.path, check=True)
        (Path(wt.path) / "two.txt").write_text("two")
        subprocess.run(["git", "add", "two.txt"], cwd=wt.path, check=True)
        subprocess.run(["git", "commit", "-m", "worker two"], cwd=wt.path, check=True)

        subprocess.run(["git", "merge", "--squash", wt.branch], cwd=git_repo, check=True)
        subprocess.run(["git", "commit", "-m", "squash worker"], cwd=git_repo, check=True)
        (Path(git_repo) / "base-only.txt").write_text("later")
        subprocess.run(["git", "add", "base-only.txt"], cwd=git_repo, check=True)
        subprocess.run(["git", "commit", "-m", "advance base"], cwd=git_repo, check=True)

        result = switch_worktree_branch(
            wt.path,
            "task-2/worker-squash",
            from_ref="main",
        )

        assert result == {"ok": True, "branch": "task-2/worker-squash"}
        current = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=wt.path,
            capture_output=True,
            text=True,
            check=True,
        )
        assert current.stdout.strip() == "task-2/worker-squash"
        assert subprocess.run(
            ["git", "diff", "--quiet", "main..HEAD"],
            cwd=wt.path,
        ).returncode == 0

    def test_real_unmerged_content_blocks_without_moving_or_creating_branch(
        self, git_repo, wt_root,
    ):
        from app.workspace import create_worktree, switch_worktree_branch

        wt = create_worktree(str(git_repo), "worker-unmerged")
        (Path(wt.path) / "worker-only.txt").write_text("must survive")
        subprocess.run(["git", "add", "worker-only.txt"], cwd=wt.path, check=True)
        subprocess.run(["git", "commit", "-m", "unmerged worker work"], cwd=wt.path, check=True)
        head_before = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=wt.path,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        branch_before = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=wt.path,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

        result = switch_worktree_branch(
            wt.path,
            "task-2/worker-unmerged",
            from_ref="main",
        )

        assert result["ok"] is False
        assert "content-change" in result["error"]
        assert "force=True" in result["error"]
        assert subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=wt.path,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip() == head_before
        assert subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=wt.path,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip() == branch_before
        assert subprocess.run(
            ["git", "show-ref", "--verify", "refs/heads/task-2/worker-unmerged"],
            cwd=git_repo,
            capture_output=True,
        ).returncode != 0

    @pytest.mark.parametrize("driver_name", ["keep", "keep=ours"])
    def test_custom_merge_driver_cannot_execute_or_false_allow(
        self, git_repo, wt_root, tmp_path, driver_name,
    ):
        from app.workspace import create_worktree, switch_worktree_branch

        (Path(git_repo) / ".gitattributes").write_text(
            f"protected.txt merge={driver_name}\n"
        )
        (Path(git_repo) / "protected.txt").write_text("base\n")
        subprocess.run(
            ["git", "add", ".gitattributes", "protected.txt"],
            cwd=git_repo,
            check=True,
        )
        subprocess.run(["git", "commit", "-m", "configure merge path"], cwd=git_repo, check=True)
        marker = tmp_path / "driver-ran"
        subprocess.run(
            [
                "git",
                "config",
                f"merge.{driver_name}.driver",
                f"sh -c 'touch {marker}'",
            ],
            cwd=git_repo,
            check=True,
        )
        wt = create_worktree(str(git_repo), "worker-driver")

        (Path(git_repo) / "protected.txt").write_text("main\n")
        subprocess.run(["git", "add", "protected.txt"], cwd=git_repo, check=True)
        subprocess.run(["git", "commit", "-m", "main content"], cwd=git_repo, check=True)
        (Path(wt.path) / "protected.txt").write_text("worker\n")
        subprocess.run(["git", "add", "protected.txt"], cwd=wt.path, check=True)
        subprocess.run(["git", "commit", "-m", "worker content"], cwd=wt.path, check=True)
        head_before = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=wt.path,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

        result = switch_worktree_branch(
            wt.path,
            "task-2/worker-driver",
            from_ref="main",
        )

        assert result["ok"] is False
        assert "conflict" in result["error"]
        assert not marker.exists()
        assert subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=wt.path,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip() == head_before
        assert subprocess.run(
            ["git", "show-ref", "--verify", "refs/heads/task-2/worker-driver"],
            cwd=git_repo,
            capture_output=True,
        ).returncode != 0

    def test_builtin_union_driver_cannot_false_allow(self, git_repo, wt_root):
        from app.workspace import create_worktree, switch_worktree_branch

        (Path(git_repo) / ".gitattributes").write_text("protected.txt merge=union\n")
        (Path(git_repo) / "protected.txt").write_text("common\nold\n")
        subprocess.run(
            ["git", "add", ".gitattributes", "protected.txt"],
            cwd=git_repo,
            check=True,
        )
        subprocess.run(["git", "commit", "-m", "configure union"], cwd=git_repo, check=True)
        wt = create_worktree(str(git_repo), "worker-union")

        (Path(git_repo) / "protected.txt").write_text("common\nmain\n")
        subprocess.run(["git", "add", "protected.txt"], cwd=git_repo, check=True)
        subprocess.run(["git", "commit", "-m", "main edit"], cwd=git_repo, check=True)
        (Path(wt.path) / "protected.txt").write_text("common\n")
        subprocess.run(["git", "add", "protected.txt"], cwd=wt.path, check=True)
        subprocess.run(["git", "commit", "-m", "worker delete"], cwd=wt.path, check=True)
        head_before = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=wt.path,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

        result = switch_worktree_branch(
            wt.path,
            "task-2/worker-union",
            from_ref="main",
        )

        assert result["ok"] is False
        assert "conflict" in result["error"]
        assert subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=wt.path,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip() == head_before
        assert subprocess.run(
            ["git", "show-ref", "--verify", "refs/heads/task-2/worker-union"],
            cwd=git_repo,
            capture_output=True,
        ).returncode != 0

    def test_git_status_failure_blocks_before_reset(
        self, git_repo, wt_root, monkeypatch,
    ):
        import app.workspace as workspace
        from app.workspace import create_worktree, switch_worktree_branch

        wt = create_worktree(str(git_repo), "worker-status")
        head_before = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=wt.path,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        real_git_cmd = workspace._git_cmd

        def fail_status(args, **kwargs):
            if args == ["git", "status", "--porcelain"]:
                return subprocess.CompletedProcess(args, 128, "", "status exploded")
            return real_git_cmd(args, **kwargs)

        monkeypatch.setattr(workspace, "_git_cmd", fail_status)
        result = switch_worktree_branch(
            wt.path,
            "task-2/worker-status",
            from_ref="main",
        )

        assert result == {"ok": False, "error": "git status failed: status exploded"}
        assert subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=wt.path,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip() == head_before

    def test_detached_verified_head_can_create_branch(self, git_repo, wt_root):
        from app.workspace import create_worktree, switch_worktree_branch

        wt = create_worktree(str(git_repo), "worker-detached")
        subprocess.run(["git", "checkout", "--detach"], cwd=wt.path, check=True)

        result = switch_worktree_branch(
            wt.path,
            "task-2/worker-detached",
            from_ref="main",
        )

        assert result == {"ok": True, "branch": "task-2/worker-detached"}
        assert subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=wt.path,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip() == "task-2/worker-detached"

    def test_content_status_fails_closed_on_missing_base(self, git_repo, wt_root):
        from app.workspace import branch_content_status, create_worktree

        wt = create_worktree(str(git_repo), "worker-missing-base")

        result = branch_content_status(wt.path, "does-not-exist")

        assert "git rev-list failed" in result["error"]

    def test_content_status_fails_closed_on_malformed_count(
        self, git_repo, wt_root, monkeypatch,
    ):
        import app.workspace as workspace
        from app.workspace import branch_content_status, create_worktree

        wt = create_worktree(str(git_repo), "worker-malformed")
        real_git_cmd = workspace._git_cmd

        def malformed_count(args, **kwargs):
            if args[:2] == ["git", "rev-list"]:
                return subprocess.CompletedProcess(args, 0, "not-a-number\n", "")
            return real_git_cmd(args, **kwargs)

        monkeypatch.setattr(workspace, "_git_cmd", malformed_count)

        assert "invalid count" in branch_content_status(wt.path, "main")["error"]


class TestMergeTarget:
    def _wt_with_commit(self, git_repo, wt_root, name, base):
        from app.workspace import create_worktree
        wt = create_worktree(str(git_repo), name, base_branch=base)
        (Path(wt.path) / "new.txt").write_text("data")
        subprocess.run(["git", "add", "."], cwd=wt.path, capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", "work"], cwd=wt.path, capture_output=True, check=True)
        return wt

    def _reject_target_commits(self, git_repo):
        hook = Path(git_repo) / ".git" / "hooks" / "pre-commit"
        hook.write_text("#!/bin/sh\necho 'rejecting hook' >&2\nexit 1\n")
        hook.chmod(0o755)

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

    def test_expected_worker_identity_mismatch_is_not_reached(
        self, git_repo, wt_root,
    ):
        from app.workspace import merge_worktree_to_main

        wt = self._wt_with_commit(git_repo, wt_root, "pinned-worker", "main")
        target_before = subprocess.run(
            ["git", "rev-parse", "main"], cwd=git_repo,
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        worker_head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=wt.path,
            capture_output=True, text=True, check=True,
        ).stdout.strip()

        result = merge_worktree_to_main(
            wt.path,
            str(git_repo),
            target_branch="main",
            expected_worker_branch=wt.branch,
            expected_worker_head="0" * 40,
        )

        assert result["ok"] is False
        assert result["state"] == "failed"
        assert result["commit_point"] == "not_reached"
        assert result["worker_branch"] == wt.branch
        assert result["worker_head"] == worker_head
        assert "worker HEAD changed" in result["error"]
        assert result["target_after"] == target_before
        assert subprocess.run(
            ["git", "rev-parse", "main"], cwd=git_repo,
            capture_output=True, text=True, check=True,
        ).stdout.strip() == target_before

    def test_unobservable_final_target_snapshot_is_partial_unknown(
        self, git_repo, wt_root, monkeypatch,
    ):
        import app.workspace as workspace
        from app.workspace import merge_worktree_to_main

        wt = self._wt_with_commit(git_repo, wt_root, "snapshot-fail", "main")
        target_before = subprocess.run(
            ["git", "rev-parse", "main"], cwd=git_repo,
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        real_git_cmd = workspace._git_cmd
        target_ref_calls = 0

        def fail_final_snapshot(args, **kwargs):
            nonlocal target_ref_calls
            if args == ["git", "show-ref", "--verify", "refs/heads/main"]:
                target_ref_calls += 1
                if target_ref_calls == 3:
                    return subprocess.CompletedProcess(
                        args, 128, "", "simulated final ref inspection failure",
                    )
            return real_git_cmd(args, **kwargs)

        monkeypatch.setattr(workspace, "_git_cmd", fail_final_snapshot)

        result = merge_worktree_to_main(
            wt.path, str(git_repo), target_branch="main",
        )

        assert target_ref_calls == 3
        assert result["ok"] is False
        assert result["state"] == "partial"
        assert result["commit_point"] == "unknown"
        assert result["target_before"] == target_before
        assert result["target_after"] == ""
        assert result["error"]
        assert subprocess.run(
            ["git", "rev-parse", "main"], cwd=git_repo,
            capture_output=True, text=True, check=True,
        ).stdout.strip() != target_before

    def test_main_head_restored_after_merge(self, git_repo, wt_root):
        """После merge в feature/auth основной репо должен вернуться на main (save/restore HEAD)."""
        from app.workspace import merge_worktree_to_main
        subprocess.run(["git", "branch", "feature/auth"], cwd=git_repo, capture_output=True, check=True)
        wt = self._wt_with_commit(git_repo, wt_root, "worker-3", "feature/auth")
        merge_worktree_to_main(wt.path, str(git_repo), target_branch="feature/auth")
        head = subprocess.run(["git", "symbolic-ref", "--short", "HEAD"], cwd=git_repo,
                              capture_output=True, text=True).stdout.strip()
        assert head == "main", f"expected main, got {head}"

    def test_merge_child_into_checked_out_parent_branch(self, git_repo, wt_root):
        from app.workspace import create_worktree, merge_worktree_to_main

        parent = create_worktree(str(git_repo), "parent", base_branch="main")
        child = create_worktree(
            str(git_repo), "child", task_id="90", base_branch=parent.branch,
        )
        (Path(child.path) / "child.txt").write_text("child work")
        subprocess.run(
            ["git", "add", "child.txt"], cwd=child.path,
            capture_output=True, check=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "#90: child work"], cwd=child.path,
            capture_output=True, check=True,
        )
        target_before = subprocess.run(
            ["git", "rev-parse", parent.branch], cwd=git_repo,
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        worker_head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=child.path,
            capture_output=True, text=True, check=True,
        ).stdout.strip()

        result = merge_worktree_to_main(
            child.path, str(git_repo), target_branch=parent.branch,
        )

        assert result["ok"] is True
        assert result["state"] == "merged"
        assert result["commit_point"] == "target_committed"
        assert result["target_branch"] == parent.branch
        assert result["target_before"] == target_before
        assert result["target_after"] != target_before
        assert result["worker_branch"] == child.branch
        assert result["worker_head"] == worker_head
        assert result["conflicts"] == []
        assert (Path(parent.path) / "child.txt").read_text() == "child work"
        assert subprocess.run(
            ["git", "branch", "--show-current"], cwd=parent.path,
            capture_output=True, text=True, check=True,
        ).stdout.strip() == parent.branch
        parent_head = subprocess.run(
            ["git", "rev-parse", parent.branch], cwd=git_repo,
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        child_head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=child.path,
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        assert child_head == parent_head
        assert subprocess.run(
            ["git", "branch", "--show-current"], cwd=child.path,
            capture_output=True, text=True, check=True,
        ).stdout.strip() == child.branch
        assert not (Path(git_repo) / "child.txt").exists()

    def test_conflict_returns_typed_snapshot_without_mutation(
        self, git_repo, wt_root,
    ):
        from app.workspace import create_worktree, merge_worktree_to_main

        conflict_path = "shared file.txt"
        (Path(git_repo) / conflict_path).write_text("base\n")
        subprocess.run(["git", "add", conflict_path], cwd=git_repo, check=True)
        subprocess.run(["git", "commit", "-m", "base"], cwd=git_repo, check=True)
        worker = create_worktree(str(git_repo), "worker-merge-conflict", base_branch="main")
        (Path(worker.path) / conflict_path).write_text("worker\n")
        subprocess.run(["git", "add", conflict_path], cwd=worker.path, check=True)
        subprocess.run(["git", "commit", "-m", "worker edit"], cwd=worker.path, check=True)
        worker_head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=worker.path,
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        (Path(git_repo) / conflict_path).write_text("main\n")
        subprocess.run(["git", "add", conflict_path], cwd=git_repo, check=True)
        subprocess.run(["git", "commit", "-m", "main edit"], cwd=git_repo, check=True)
        target_before = subprocess.run(
            ["git", "rev-parse", "main"], cwd=git_repo,
            capture_output=True, text=True, check=True,
        ).stdout.strip()

        result = merge_worktree_to_main(
            worker.path, str(git_repo), target_branch="main",
        )

        assert result["ok"] is False
        assert result["state"] == "conflict"
        assert result["commit_point"] == "not_reached"
        assert result["target_branch"] == "main"
        assert result["target_before"] == target_before
        assert result["target_after"] == target_before
        assert result["worker_branch"] == worker.branch
        assert result["worker_head"] == worker_head
        assert result["conflicts"] == [conflict_path]

    def test_dirty_checked_out_target_is_rejected_without_stash(
        self, git_repo, wt_root,
    ):
        from app.workspace import create_worktree, merge_worktree_to_main

        parent = create_worktree(str(git_repo), "parent", base_branch="main")
        child = create_worktree(
            str(git_repo), "child", task_id="90", base_branch=parent.branch,
        )
        (Path(child.path) / "child.txt").write_text("child work")
        subprocess.run(["git", "add", "child.txt"], cwd=child.path, check=True)
        subprocess.run(["git", "commit", "-m", "child work"], cwd=child.path, check=True)
        parent_head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=parent.path,
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        child_head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=child.path,
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        (Path(parent.path) / "local-wip.txt").write_text("do not touch")

        result = merge_worktree_to_main(
            child.path, str(git_repo), target_branch=parent.branch,
        )

        assert result["ok"] is False
        assert "target working tree is dirty" in result["error"]
        assert "local-wip.txt" in result["error"]
        assert subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=parent.path,
            capture_output=True, text=True, check=True,
        ).stdout.strip() == parent_head
        assert subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=child.path,
            capture_output=True, text=True, check=True,
        ).stdout.strip() == child_head
        assert (Path(parent.path) / "local-wip.txt").read_text() == "do not touch"
        assert subprocess.run(
            ["git", "stash", "list"], cwd=git_repo,
            capture_output=True, text=True, check=True,
        ).stdout == ""

    def test_prunable_target_worktree_is_rejected_without_exception(
        self, git_repo, wt_root,
    ):
        from app.workspace import create_worktree, merge_worktree_to_main

        parent = create_worktree(str(git_repo), "parent", base_branch="main")
        child = create_worktree(
            str(git_repo), "child", task_id="90", base_branch=parent.branch,
        )
        (Path(child.path) / "child.txt").write_text("child work")
        subprocess.run(["git", "add", "child.txt"], cwd=child.path, check=True)
        subprocess.run(["git", "commit", "-m", "child work"], cwd=child.path, check=True)
        child_head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=child.path,
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        shutil.rmtree(parent.path)

        result = merge_worktree_to_main(
            child.path, str(git_repo), target_branch=parent.branch,
        )

        assert result["ok"] is False
        assert "prunable worktree" in result["error"]
        assert str(Path(parent.path).resolve()) in result["error"]
        assert subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=child.path,
            capture_output=True, text=True, check=True,
        ).stdout.strip() == child_head

    def test_dirty_primary_target_is_rejected_without_stash(self, git_repo, wt_root):
        from app.workspace import merge_worktree_to_main

        wt = self._wt_with_commit(git_repo, wt_root, "worker-4", "main")
        (Path(git_repo) / "dirty.txt").write_text("dirty")

        res = merge_worktree_to_main(wt.path, str(git_repo))
        assert res.get("ok") is False
        assert "target working tree is dirty" in res["error"]
        assert "dirty.txt" in res["error"]
        assert subprocess.run(
            ["git", "stash", "list"], cwd=git_repo,
            capture_output=True, text=True, check=True,
        ).stdout == ""

    def test_external_bug_report_does_not_weaken_dirty_target_guard(
        self, git_repo, wt_root, tmp_path, monkeypatch,
    ):
        import app.routes.system as system
        from app.workspace import create_worktree, merge_worktree_to_main

        monkeypatch.setattr(system, "_BUG_STATE_ROOT_CACHE", tmp_path / "state")
        monkeypatch.setattr(system, "_BUG_VALIDATED_DIRS", {})
        first = self._wt_with_commit(git_repo, wt_root, "bug-report-clean", "main")
        system._publish_bug_record("external report")

        clean_result = merge_worktree_to_main(first.path, str(git_repo))

        assert clean_result["ok"] is True
        assert subprocess.run(
            ["git", "status", "--porcelain"], cwd=git_repo,
            capture_output=True, text=True, check=True,
        ).stdout == ""

        second = create_worktree(str(git_repo), "bug-report-dirty", base_branch="main")
        (Path(second.path) / "second.txt").write_text("second")
        subprocess.run(
            ["git", "add", "second.txt"], cwd=second.path,
            capture_output=True, check=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "second work"], cwd=second.path,
            capture_output=True, check=True,
        )
        (Path(git_repo) / "human-wip.txt").write_text("do not hide me")
        system._publish_bug_record("second external report")

        dirty_result = merge_worktree_to_main(second.path, str(git_repo))

        assert dirty_result["ok"] is False
        assert "target working tree is dirty" in dirty_result["error"]
        assert "human-wip.txt" in dirty_result["error"]

    def test_related_commit_failure_rolls_back_target_and_preserves_worker(
        self, git_repo, wt_root,
    ):
        from app.workspace import merge_worktree_to_main

        wt = self._wt_with_commit(git_repo, wt_root, "related-reject", "main")
        target_head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=git_repo,
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        worker_head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=wt.path,
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        self._reject_target_commits(git_repo)

        result = merge_worktree_to_main(wt.path, str(git_repo), target_branch="main")

        assert result["ok"] is False
        assert result["state"] == "failed"
        assert result["commit_point"] == "rolled_back"
        assert "squash commit failed" in result["error"]
        assert "rejecting hook" in result["error"]
        assert subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=git_repo,
            capture_output=True, text=True, check=True,
        ).stdout.strip() == target_head
        assert subprocess.run(
            ["git", "status", "--porcelain"], cwd=git_repo,
            capture_output=True, text=True, check=True,
        ).stdout == ""
        assert subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=wt.path,
            capture_output=True, text=True, check=True,
        ).stdout.strip() == worker_head

    def test_unrelated_commit_failure_rolls_back_target_and_preserves_worker(
        self, git_repo, wt_root,
    ):
        from app.workspace import create_worktree, merge_worktree_to_main

        wt = create_worktree(str(git_repo), "unrelated-reject", base_branch="main")
        subprocess.run(
            ["git", "checkout", "--orphan", "unrelated-worker"],
            cwd=wt.path, capture_output=True, check=True,
        )
        subprocess.run(
            ["git", "rm", "-rf", "."], cwd=wt.path,
            capture_output=True, check=True,
        )
        (Path(wt.path) / "unrelated.txt").write_text("unrelated work")
        subprocess.run(["git", "add", "unrelated.txt"], cwd=wt.path, check=True)
        subprocess.run(
            ["git", "commit", "-m", "unrelated work"], cwd=wt.path,
            capture_output=True, check=True,
        )
        target_head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=git_repo,
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        worker_head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=wt.path,
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        self._reject_target_commits(git_repo)

        result = merge_worktree_to_main(wt.path, str(git_repo), target_branch="main")

        assert result["ok"] is False
        assert result["state"] == "failed"
        assert result["commit_point"] == "rolled_back"
        assert result.get("strategy") != "cherry-pick"
        assert "squash commit failed" in result["error"]
        assert "rejecting hook" in result["error"]
        assert subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=git_repo,
            capture_output=True, text=True, check=True,
        ).stdout.strip() == target_head
        assert subprocess.run(
            ["git", "status", "--porcelain"], cwd=git_repo,
            capture_output=True, text=True, check=True,
        ).stdout == ""
        assert subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=wt.path,
            capture_output=True, text=True, check=True,
        ).stdout.strip() == worker_head


class TestRemoveWorktree:
    def test_removes(self, git_repo, wt_root):
        from app.workspace import create_worktree, remove_worktree
        wt = create_worktree(str(git_repo), "worker-1")
        assert Path(wt.path).exists()
        remove_worktree(str(git_repo), wt.path)
        assert not Path(wt.path).exists()

    def test_nonexistent_no_error(self, git_repo, wt_root):
        from app.workspace import remove_worktree
        remove_worktree(str(git_repo), "/nonexistent/path")

    def test_locked_git_failure_raises_and_keeps_worktree(self, git_repo, wt_root):
        from app.workspace import create_worktree, remove_worktree
        wt = create_worktree(str(git_repo), "worker-1")
        subprocess.run(
            ["git", "worktree", "lock", wt.path],
            cwd=git_repo, check=True,
        )

        with pytest.raises(RuntimeError, match="cannot remove a locked working tree"):
            remove_worktree(str(git_repo), wt.path)

        assert Path(wt.path).exists()

    def test_acquires_merge_lock(self, git_repo, wt_root, monkeypatch):
        # Task #39 Fix 4: remove_worktree must hold .git/orchestra-merge.lock
        # (LOCK_EX) so it can't race a concurrent merge_worktree_to_main.
        import app.workspace as ws
        from app.workspace import create_worktree, remove_worktree

        wt = create_worktree(str(git_repo), "worker-1")
        flocks = []
        monkeypatch.setattr(ws.fcntl, "flock", lambda f, op: flocks.append(op))
        remove_worktree(str(git_repo), wt.path)
        assert ws.fcntl.LOCK_EX in flocks  # exclusive lock taken
        assert ws.fcntl.LOCK_UN in flocks  # and released


class TestDiscardPreparedWorktree:
    def test_removes_unpublished_worktree_and_its_created_branch(
        self, git_repo, wt_root,
    ):
        from app.workspace import create_worktree, discard_prepared_worktree

        wt = create_worktree(str(git_repo), "cancelled-worker", task_id="93")
        (Path(wt.path) / "unpublished.txt").write_text("prepared only")

        discard_prepared_worktree(str(git_repo), wt)

        assert not Path(wt.path).exists()
        assert subprocess.run(
            ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{wt.branch}"],
            cwd=git_repo,
        ).returncode == 1
        assert str(Path(wt.path).resolve()) not in subprocess.run(
            ["git", "worktree", "list", "--porcelain"],
            cwd=git_repo, capture_output=True, text=True, check=True,
        ).stdout

    def test_preserves_branch_that_predated_spawn(self, git_repo, wt_root):
        from app.workspace import create_worktree, discard_prepared_worktree

        branch = "task-93/existing-worker"
        subprocess.run(["git", "branch", branch], cwd=git_repo, check=True)
        wt = create_worktree(str(git_repo), "existing-worker", task_id="93")
        assert wt.branch_created is False

        discard_prepared_worktree(str(git_repo), wt)

        assert not Path(wt.path).exists()
        assert subprocess.run(
            ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{branch}"],
            cwd=git_repo,
        ).returncode == 0

    def test_preserves_worktree_when_created_branch_ownership_changed(
        self, git_repo, wt_root,
    ):
        from app.workspace import create_worktree, discard_prepared_worktree

        wt = create_worktree(str(git_repo), "changed-worker", task_id="93")
        (Path(wt.path) / "owned.txt").write_text("new commit")
        subprocess.run(["git", "add", "owned.txt"], cwd=wt.path, check=True)
        subprocess.run(
            ["git", "commit", "-m", "external change"], cwd=wt.path, check=True,
        )

        with pytest.raises(RuntimeError, match="ownership changed"):
            discard_prepared_worktree(str(git_repo), wt)

        assert Path(wt.path).exists()
        assert subprocess.run(
            ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{wt.branch}"],
            cwd=git_repo,
        ).returncode == 0

    def test_missing_directory_with_registration_fails_loud(
        self, git_repo, wt_root,
    ):
        from app.workspace import create_worktree, discard_prepared_worktree

        wt = create_worktree(str(git_repo), "missing-worker", task_id="93")
        shutil.rmtree(wt.path)

        with pytest.raises(RuntimeError, match="missing but .* remains registered"):
            discard_prepared_worktree(str(git_repo), wt)

        assert str(Path(wt.path).resolve()) in subprocess.run(
            ["git", "worktree", "list", "--porcelain"],
            cwd=git_repo, capture_output=True, text=True, check=True,
        ).stdout
        assert subprocess.run(
            ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{wt.branch}"],
            cwd=git_repo,
        ).returncode == 0


class TestRepoLock:
    def test_path_is_stable_across_processes_and_excludes_second_holder(
        self, git_repo,
    ):
        import fcntl
        from app.workspace import _repo_lock_path

        lock_path = _repo_lock_path(git_repo)
        assert lock_path.parent == (git_repo / ".git").resolve()
        code = (
            "from app.workspace import _repo_lock_path; import sys; "
            "print(_repo_lock_path(sys.argv[1]))"
        )
        child_path = subprocess.run(
            [sys.executable, "-c", code, str(git_repo)],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        assert child_path == str(lock_path)

        contender = (
            "import fcntl,sys; f=open(sys.argv[1],'a');\n"
            "try:\n fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB); print('acquired')\n"
            "except BlockingIOError:\n print('blocked')\n"
        )
        with open(lock_path, "a") as held:
            fcntl.flock(held, fcntl.LOCK_EX)
            output = subprocess.run(
                [sys.executable, "-c", contender, str(lock_path)],
                capture_output=True, text=True, check=True,
            ).stdout.strip()
            assert output == "blocked"
            fcntl.flock(held, fcntl.LOCK_UN)

    def test_symlink_lock_entry_is_rejected(self, git_repo, tmp_path):
        from app.workspace import _repo_lock_path, repo_mutation_lock

        lock_path = _repo_lock_path(git_repo)
        target = tmp_path / "outside-lock"
        target.write_text("")
        lock_path.symlink_to(target)

        with pytest.raises(OSError):
            with repo_mutation_lock(git_repo):
                pass

    def test_switch_and_remove_do_not_enter_repo_mutation_together(
        self, git_repo, wt_root, monkeypatch,
    ):
        import app.workspace as workspace
        from app.workspace import create_worktree, remove_worktree, switch_worktree_branch

        wt = create_worktree(str(git_repo), "serialized-worker", task_id="1")
        real_git_cmd = workspace._git_cmd
        real_repo_lock = workspace.repo_mutation_lock
        switch_inside = threading.Event()
        release_switch = threading.Event()
        remove_attempted = threading.Event()
        remove_done = threading.Event()

        @contextmanager
        def observed_repo_lock(repo):
            if threading.current_thread().name == "remove-op":
                remove_attempted.set()
            with real_repo_lock(repo):
                yield

        def block_switch_reset(args, **kwargs):
            if (
                threading.current_thread().name == "switch-op"
                and args[:3] == ["git", "reset", "--hard"]
            ):
                switch_inside.set()
                assert release_switch.wait(2)
            return real_git_cmd(args, **kwargs)

        monkeypatch.setattr(workspace, "repo_mutation_lock", observed_repo_lock)
        monkeypatch.setattr(workspace, "_git_cmd", block_switch_reset)
        switch_result = {}

        def run_switch():
            switch_result.update(switch_worktree_branch(
                wt.path, "task-2/serialized-worker", from_ref="main", force=True,
            ))

        def run_remove():
            remove_worktree(str(git_repo), wt.path)
            remove_done.set()

        switch_thread = threading.Thread(target=run_switch, name="switch-op")
        remove_thread = threading.Thread(target=run_remove, name="remove-op")
        switch_thread.start()
        assert switch_inside.wait(2)
        remove_thread.start()
        assert remove_attempted.wait(2)
        assert remove_done.is_set() is False
        release_switch.set()
        switch_thread.join(2)
        remove_thread.join(2)

        assert switch_result["ok"] is True
        assert remove_done.is_set() is True
        assert not Path(wt.path).exists()


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
        wt_alive = create_worktree(str(git_repo), "alive-worker")
        wt_stale = create_worktree(str(git_repo), "stale-worker")

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
        wt = create_worktree(str(git_repo), "dirty-worker")
        (Path(wt.path) / "uncommitted.txt").write_text("dirty")

        monkeypatch.setattr("app.db.get_all_sessions", lambda: [])

        removed = cleanup_stale_worktrees()
        assert len(removed) == 0
        assert Path(wt.path).exists()

    def test_failed_removal_is_not_reported(self, git_repo, wt_root, monkeypatch):
        from app.workspace import create_worktree, cleanup_stale_worktrees

        wt = create_worktree(str(git_repo), "locked-worker")
        subprocess.run(
            ["git", "worktree", "lock", wt.path],
            cwd=git_repo, check=True,
        )
        monkeypatch.setattr("app.db.get_all_sessions", lambda: [])

        removed = cleanup_stale_worktrees()

        assert removed == []
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


class TestSyncAgentsMd:
    """Codex reads AGENTS.md, not CLAUDE.md — the mirror must stay current, and must never
    overwrite an AGENTS.md the repo itself tracks (Orchestra is public)."""

    def test_created_on_worktree_creation(self, git_repo, wt_root):
        from app.workspace import create_worktree
        wt = create_worktree(str(git_repo), "w1")
        assert (Path(wt.path) / "AGENTS.md").read_text() == "# instructions"

    def test_refreshes_stale_mirror(self, git_repo, wt_root):
        from app.workspace import create_worktree, sync_agents_md
        wt = create_worktree(str(git_repo), "w1")
        (Path(wt.path) / "CLAUDE.md").write_text("# instructions v2")
        assert sync_agents_md(wt.path) is True
        assert (Path(wt.path) / "AGENTS.md").read_text() == "# instructions v2"

    def test_noop_when_already_in_sync(self, git_repo, wt_root):
        from app.workspace import create_worktree, sync_agents_md
        wt = create_worktree(str(git_repo), "w1")
        agents = Path(wt.path) / "AGENTS.md"
        before = agents.stat().st_mtime_ns
        assert sync_agents_md(wt.path) is False
        assert agents.stat().st_mtime_ns == before

    def test_tracked_agents_md_untouched(self, git_repo, wt_root):
        from app.workspace import create_worktree, sync_agents_md
        (git_repo / "AGENTS.md").write_text("# the repo's own rules")
        subprocess.run(["git", "add", "AGENTS.md"], cwd=git_repo, capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", "own agents"], cwd=git_repo, capture_output=True, check=True)
        wt = create_worktree(str(git_repo), "w1")
        assert sync_agents_md(wt.path) is False
        assert (Path(wt.path) / "AGENTS.md").read_text() == "# the repo's own rules"

    def test_no_claude_md_no_mirror(self, git_repo, wt_root):
        from app.workspace import create_worktree, sync_agents_md
        wt = create_worktree(str(git_repo), "w1")
        (Path(wt.path) / "CLAUDE.md").unlink()
        (Path(wt.path) / "AGENTS.md").unlink()
        assert sync_agents_md(wt.path) is False
        assert not (Path(wt.path) / "AGENTS.md").exists()

    def test_mirror_does_not_dirty_tree(self, git_repo, wt_root):
        from app.workspace import create_worktree, sync_agents_md
        wt = create_worktree(str(git_repo), "w1")
        (Path(wt.path) / "CLAUDE.md").write_text("# instructions v2")
        sync_agents_md(wt.path)
        status = subprocess.run(
            ["git", "status", "--porcelain"], cwd=wt.path, capture_output=True, text=True,
        ).stdout
        assert "AGENTS.md" not in status

    def test_symlink_agents_md_untouched(self, git_repo, wt_root, tmp_path):
        from app.workspace import create_worktree, sync_agents_md
        wt = create_worktree(str(git_repo), "w1")
        outside = tmp_path / "somebody-elses.md"
        outside.write_text("# not ours")
        agents = Path(wt.path) / "AGENTS.md"
        agents.unlink()
        agents.symlink_to(outside)
        (Path(wt.path) / "CLAUDE.md").write_text("# instructions v2")
        assert sync_agents_md(wt.path) is False
        assert outside.read_text() == "# not ours"

    def test_git_failure_does_not_overwrite(self, git_repo, wt_root, monkeypatch):
        from app.workspace import create_worktree, sync_agents_md
        import app.workspace as ws
        wt = create_worktree(str(git_repo), "w1")
        (Path(wt.path) / "CLAUDE.md").write_text("# instructions v2")
        real = ws._git_cmd

        def fake(args, **kwargs):
            if "ls-files" in args:
                return subprocess.CompletedProcess(args, 128, stdout="", stderr="fatal: not a git repository")
            return real(args, **kwargs)

        monkeypatch.setattr(ws, "_git_cmd", fake)
        assert sync_agents_md(wt.path) is False
        assert (Path(wt.path) / "AGENTS.md").read_text() == "# instructions"

    def test_noop_still_excludes_old_worktree(self, git_repo, wt_root):
        from app.workspace import create_worktree, sync_agents_md
        wt = create_worktree(str(git_repo), "w1")
        common = subprocess.run(
            ["git", "rev-parse", "--git-common-dir"], cwd=wt.path, capture_output=True, text=True,
        ).stdout.strip()
        exclude = Path(common) / "info" / "exclude"
        exclude.write_text("")  # simulate a worktree created before AGENTS.md joined the list
        assert sync_agents_md(wt.path) is False  # already in sync
        assert "AGENTS.md" in exclude.read_text()

    def test_no_tmp_file_left_behind(self, git_repo, wt_root):
        from app.workspace import create_worktree, sync_agents_md
        wt = create_worktree(str(git_repo), "w1")
        (Path(wt.path) / "CLAUDE.md").write_text("# instructions v2")
        assert sync_agents_md(wt.path) is True
        assert not (Path(wt.path) / "AGENTS.md.tmp").exists()

    def test_existing_tmp_name_untouched(self, git_repo, wt_root):
        from app.workspace import create_worktree, sync_agents_md
        wt = create_worktree(str(git_repo), "w1")
        stray = Path(wt.path) / "AGENTS.md.tmp"
        stray.write_text("# somebody else's temp")
        (Path(wt.path) / "CLAUDE.md").write_text("# instructions v2")
        assert sync_agents_md(wt.path) is True
        assert stray.read_text() == "# somebody else's temp"

    def test_tmp_cleaned_up_when_move_fails(self, git_repo, wt_root, monkeypatch):
        from app.workspace import create_worktree, sync_agents_md
        import app.workspace as ws
        wt = create_worktree(str(git_repo), "w1")
        (Path(wt.path) / "CLAUDE.md").write_text("# instructions v2")
        real = ws._git_cmd

        def fake(args, **kwargs):
            if args[0] == "mv":
                return subprocess.CompletedProcess(args, 1, stdout="", stderr="mv: boom")
            return real(args, **kwargs)

        monkeypatch.setattr(ws, "_git_cmd", fake)
        with pytest.raises(OSError):
            sync_agents_md(wt.path)
        assert not list(Path(wt.path).glob(".AGENTS.md.*.tmp"))
        assert (Path(wt.path) / "AGENTS.md").read_text() == "# instructions"
