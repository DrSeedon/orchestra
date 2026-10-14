"""V-821: workers get a partial (sparse) copy of the repository.

Guards the mechanics that carry the policy: the copy is created from the manifest rule, a change the
copy cannot stage blocks the merge with a way out, a task switch recomputes the task's own directories,
and switching the rule off gives a full copy again.
"""

import subprocess
from pathlib import Path

import pytest

from app.pipeline import Sparse, SparseProject, Worktree


def git(cwd, *args, check=True):
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=check,
    )


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    git(root, "init")
    git(root, "config", "user.email", "t@t")
    git(root, "config", "user.name", "T")
    files = {
        "README.md": "readme",
        "src/app.py": "print('x')\n",
        "artifacts/V-9/old.bin": "old",
        "artifacts/V-1/mine.txt": "mine",
        "artifacts/task-V-3/prev.txt": "prev",
        "artifacts/tooling/run.sh": "#!/bin/sh\n",
        ".orchestra/tasks/V-1/report.md": "r1",
        ".orchestra/tasks/V-2/report.md": "r2",
        ".orchestra/tasks/V-7/report.md": "r7",
        ".orchestra/tasks/V-8/report.md": "r8",
        ".orchestra/tasks/224/unit.service": "u",
        ".orchestra/kb/topic.md": "see [r](../tasks/V-2/report.md)\n",
        "tests/test_x.py": 'P = ROOT / ".orchestra" / "tasks" / "224" / "unit.service"\n',
    }
    for rel, body in files.items():
        f = root / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(body)
    git(root, "add", "-A")
    git(root, "commit", "-m", "init")
    git(root, "branch", "-M", "main")
    return root


@pytest.fixture
def wt_root(tmp_path, monkeypatch):
    root = tmp_path / "worktrees"
    root.mkdir()
    monkeypatch.setattr("app.workspace.WORKTREE_ROOT", root)
    return root


def cfg(**kw):
    base = dict(
        enabled=True,
        exclude=["artifacts", ".orchestra/tasks"],
        own=[".orchestra/tasks/{id}", "artifacts/{id}", "artifacts/task-{id}"],
    )
    base.update(kw)
    return Worktree(copies=[], sparse=Sparse(**base))


def present(wt, rel):
    return (Path(wt.path) / rel).exists()


def test_sparse_copy_has_own_dirs_and_source_but_not_the_rest(repo, wt_root):
    from app.workspace import create_worktree

    wt = create_worktree(str(repo), "w1", task_id="V-1", worktree_cfg=cfg())

    assert present(wt, "src/app.py")
    assert present(wt, ".orchestra/tasks/V-1/report.md")
    assert present(wt, "artifacts/V-1/mine.txt")
    assert not present(wt, ".orchestra/tasks/V-2/report.md")
    assert not present(wt, "artifacts/V-9/old.bin")
    assert git(wt.path, "status", "--porcelain").stdout == ""
    # the rule belongs to this worktree; the main checkout stays whole
    assert git(repo, "config", "--get", "core.sparseCheckout", check=False).stdout.strip() != "true"
    assert (repo / "artifacts/V-9/old.bin").exists()


def test_references_from_kb_and_tests_pull_their_dirs_in(repo, wt_root):
    from app.workspace import create_worktree

    wt = create_worktree(
        str(repo), "w2", task_id="V-1",
        worktree_cfg=cfg(reference_scan=[".orchestra/kb", "tests"]),
    )

    assert present(wt, ".orchestra/tasks/V-2/report.md")      # ../tasks/V-2/... in a KB note
    assert present(wt, ".orchestra/tasks/224/unit.service")   # "tasks" / "224" in a test
    assert not present(wt, ".orchestra/tasks/V-7/report.md")  # mentioned nowhere
    assert not present(wt, "artifacts/V-9/old.bin")


def test_project_override_adds_dir_and_can_switch_the_rule_off(repo, wt_root):
    from app.workspace import create_worktree

    on = cfg(projects={"*/proj": SparseProject(include=["artifacts/tooling"])})
    wt = create_worktree(str(repo), "w3", task_id="V-1", worktree_cfg=on)
    assert present(wt, "artifacts/tooling/run.sh")
    assert not present(wt, "artifacts/V-9/old.bin")

    off = cfg(projects={"*/proj": SparseProject(enabled=False)})
    full = create_worktree(str(repo), "w4", task_id="V-1", worktree_cfg=off)
    assert present(full, "artifacts/V-9/old.bin")
    assert present(full, ".orchestra/tasks/V-7/report.md")


def test_disabled_or_missing_manifest_gives_a_full_copy(repo, wt_root):
    from app.workspace import create_worktree

    a = create_worktree(str(repo), "w5", task_id="V-1", worktree_cfg=cfg(enabled=False))
    b = create_worktree(str(repo), "w6", task_id="V-2", worktree_cfg=None)
    for wt in (a, b):
        assert present(wt, "artifacts/V-9/old.bin")


def test_failing_rule_setup_falls_back_to_a_full_copy(repo, wt_root, monkeypatch):
    from app import sparse_worktree
    from app.workspace import create_worktree

    monkeypatch.setattr(sparse_worktree, "apply_patterns", lambda *a, **k: "boom")
    wt = create_worktree(str(repo), "w7", task_id="V-1", worktree_cfg=cfg())
    assert present(wt, "artifacts/V-9/old.bin")
    assert git(wt.path, "status", "--porcelain").stdout == ""


def test_change_outside_the_copy_blocks_merge_with_the_way_out(repo, wt_root):
    from app.workspace import create_worktree, merge_worktree_to_main

    wt = create_worktree(str(repo), "w8", task_id="V-1", worktree_cfg=cfg())
    # a script rewrites a tracked file that is not in the copy: git add -A "succeeds" and stages nothing
    victim = Path(wt.path) / "artifacts/V-9/old.bin"
    victim.parent.mkdir(parents=True, exist_ok=True)
    victim.write_text("new")
    (Path(wt.path) / "src/app.py").write_text("print('y')\n")
    git(wt.path, "add", "-A", check=False)
    git(wt.path, "commit", "-m", "work", check=False)

    res = merge_worktree_to_main(wt.path, str(repo), target_branch="main")

    assert res["ok"] is False
    assert "working tree is dirty" in res["error"]
    assert "sparse checkout" in res["error"]
    assert "git sparse-checkout add /artifacts/V-9/" in res["error"]
    assert (repo / "artifacts/V-9/old.bin").read_text() == "old"

    # following the advice makes the change committable and the merge goes through
    git(wt.path, "sparse-checkout", "add", "/artifacts/V-9/")
    git(wt.path, "add", "-A")
    git(wt.path, "commit", "-m", "outside change")
    assert merge_worktree_to_main(wt.path, str(repo), target_branch="main")["ok"] is True
    assert (repo / "artifacts/V-9/old.bin").read_text() == "new"


def test_change_inside_the_copy_merges_without_extra_steps(repo, wt_root):
    from app.workspace import create_worktree, merge_worktree_to_main

    wt = create_worktree(str(repo), "w9", task_id="V-1", worktree_cfg=cfg())
    (Path(wt.path) / "src/app.py").write_text("print('z')\n")
    (Path(wt.path) / ".orchestra/tasks/V-1/report.md").write_text("done")
    git(wt.path, "add", "-A")
    git(wt.path, "commit", "-m", "work")

    assert merge_worktree_to_main(wt.path, str(repo), target_branch="main")["ok"] is True
    assert (repo / "src/app.py").read_text() == "print('z')\n"


def test_switch_recomputes_the_tasks_own_directories(repo, wt_root):
    from app.workspace import create_worktree, switch_worktree_branch

    wt = create_worktree(str(repo), "w10", task_id="V-1", worktree_cfg=cfg())
    assert present(wt, ".orchestra/tasks/V-1/report.md")
    assert not present(wt, "artifacts/task-V-3/prev.txt")

    result = switch_worktree_branch(wt.path, "task-V-3/w10", from_ref="main")

    assert result["ok"] is True
    assert present(wt, "artifacts/task-V-3/prev.txt")
    assert not present(wt, ".orchestra/tasks/V-1/report.md")
    assert git(wt.path, "status", "--porcelain").stdout == ""


def test_switch_leaves_a_full_copy_alone(repo, wt_root):
    from app.workspace import create_worktree, switch_worktree_branch

    wt = create_worktree(str(repo), "w11", task_id="V-1", worktree_cfg=cfg(enabled=False))
    assert switch_worktree_branch(wt.path, "task-V-3/w11", from_ref="main")["ok"] is True
    assert present(wt, ".orchestra/tasks/V-8/report.md")


class TestConvertExistingWorktree:
    def _full(self, repo, wt_root, name="c1"):
        from app.workspace import create_worktree

        return create_worktree(str(repo), name, task_id="V-1", worktree_cfg=cfg(enabled=False))

    def test_dry_run_changes_nothing_and_apply_converts(self, repo, wt_root):
        from app.workspace import convert_worktree_to_sparse

        wt = self._full(repo, wt_root)
        dry = convert_worktree_to_sparse(wt.path, cfg())
        assert dry["state"] == "would_convert"
        assert present(wt, "artifacts/V-9/old.bin")

        done = convert_worktree_to_sparse(wt.path, cfg(), apply=True)
        assert done["state"] == "converted" and done["status_clean"] is True
        assert not present(wt, "artifacts/V-9/old.bin")
        assert present(wt, "artifacts/V-1/mine.txt")
        assert present(wt, "src/app.py")
        assert convert_worktree_to_sparse(wt.path, cfg(), apply=True)["state"] == "skipped"

    @pytest.mark.parametrize("dirty", ["modified", "untracked"])
    def test_refuses_and_keeps_every_file_when_the_tree_is_not_clean(self, repo, wt_root, dirty):
        from app.workspace import convert_worktree_to_sparse

        wt = self._full(repo, wt_root, f"c-{dirty}")
        target = Path(wt.path) / ("src/app.py" if dirty == "modified" else "artifacts/V-9/draft.txt")
        target.write_text("mine")

        result = convert_worktree_to_sparse(wt.path, cfg(), apply=True)

        assert result["state"] == "refused"
        assert target.read_text() == "mine"
        assert present(wt, "artifacts/V-9/old.bin")

    def test_ignored_files_in_excluded_dirs_survive_and_are_reported(self, repo, wt_root):
        from app.workspace import convert_worktree_to_sparse

        (repo / ".gitignore").write_text("*.big\n")
        git(repo, "add", "-A")
        git(repo, "commit", "-m", "ignore")
        wt = self._full(repo, wt_root, "c-ign")
        keep = Path(wt.path) / "artifacts/V-9/render.big"
        keep.write_text("x" * 2048)

        done = convert_worktree_to_sparse(wt.path, cfg(), apply=True)

        assert done["state"] == "converted"
        assert keep.read_text() == "x" * 2048
        assert not present(wt, "artifacts/V-9/old.bin")
        assert "artifacts" in done["left_on_disk_mb"]

    def test_a_process_inside_blocks_unless_allowed(self, repo, wt_root, monkeypatch):
        import app.workspace as workspace

        wt = self._full(repo, wt_root, "c-busy")
        monkeypatch.setattr(workspace, "_processes_inside", lambda _p: [4242])

        assert workspace.convert_worktree_to_sparse(wt.path, cfg(), apply=True)["state"] == "refused"
        assert present(wt, "artifacts/V-9/old.bin")
        assert workspace.convert_worktree_to_sparse(
            wt.path, cfg(), apply=True, allow_busy=True)["state"] == "converted"

    def test_rule_off_for_the_project_skips(self, repo, wt_root):
        from app.workspace import convert_worktree_to_sparse

        wt = self._full(repo, wt_root, "c-off")
        off = cfg(projects={"*/proj": SparseProject(enabled=False)})
        assert convert_worktree_to_sparse(wt.path, off, apply=True)["state"] == "skipped"


def test_promoting_taskless_work_gives_the_new_task_its_own_dirs(repo, wt_root):
    from app.workspace import create_worktree, promote_worktree_branch

    wt = create_worktree(str(repo), "w12", worktree_cfg=cfg())
    git(wt.path, "branch", "-m", "adhoc-1/w12")
    (Path(wt.path) / "src/app.py").write_text("print('p')\n")
    git(wt.path, "add", "-A")
    git(wt.path, "commit", "-m", "adhoc work")
    head = git(wt.path, "rev-parse", "HEAD").stdout.strip()
    assert not present(wt, "artifacts/task-V-3/prev.txt")

    result = promote_worktree_branch(
        wt.path, "task-V-3/w12", from_ref="main", expected_branch="adhoc-1/w12", expected_head=head)

    assert result["ok"] is True, result
    assert present(wt, "artifacts/task-V-3/prev.txt")
