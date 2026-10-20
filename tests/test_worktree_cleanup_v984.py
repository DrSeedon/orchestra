"""V-984: after a merge, recoverable generated output leaves the worker's copy; nothing unique does."""

import asyncio
import os
import subprocess
import uuid
from pathlib import Path

import pytest

from app import worktree_cleanup
from app.worktree_cleanup import clean_worktree
from tests.test_merge_operations import merge_db  # noqa: F401  (fixture)


def git(cwd, *args, check=True):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=check)


@pytest.fixture
def setup(tmp_path):
    main = tmp_path / "proj"
    main.mkdir()
    git(main, "init", "-b", "main")
    git(main, "config", "user.email", "t@t")
    git(main, "config", "user.name", "T")
    (main / ".gitignore").write_text("out/\n*.bin\n__pycache__/\n.env\n.venv/\n")
    (main / "src.py").write_text("x = 1\n")
    (main / "kept").mkdir()
    (main / "kept" / "deck.pdf").write_bytes(b"PDF-in-branch")
    git(main, "add", "-A")
    git(main, "commit", "-m", "init")
    wt = tmp_path / "wt"
    git(main, "worktree", "add", "-b", "task-V-1/w", str(wt), "main")
    # ignored output identical to a blob of the target branch (other path)
    (wt / "out").mkdir()
    (wt / "out" / "copy.pdf").write_bytes(b"PDF-in-branch")
    # ignored output the orchestrator already copied into the main checkout
    (main / "out").mkdir()
    (main / "out" / "render.bin").write_bytes(b"R" * 4096)
    (wt / "out" / "render.bin").write_bytes(b"R" * 4096)
    # ignored output that exists only in this copy
    (wt / "out" / "unique.bin").write_bytes(b"only here")
    # same path in main checkout but different bytes: still unique
    (main / "out" / "differs.bin").write_bytes(b"A" * 10)
    (wt / "out" / "differs.bin").write_bytes(b"B" * 10)
    # pure cache
    (wt / "__pycache__").mkdir()
    (wt / "__pycache__" / "src.cpython-312.pyc").write_bytes(b"pyc")
    # planted / environment files identical to the main checkout: must stay
    (main / ".env").write_text("SECRET=1\n")
    (wt / ".env").write_text("SECRET=1\n")
    (main / ".venv").mkdir()
    (wt / ".venv").mkdir()
    (main / ".venv" / "lib.bin").write_bytes(b"L")
    (wt / ".venv" / "lib.bin").write_bytes(b"L")
    # identical to main checkout but ignored only through info/exclude (Orchestra's own marks)
    common = Path(git(wt, "rev-parse", "--git-common-dir").stdout.strip())
    common = common if common.is_absolute() else (wt / common)
    (common / "info").mkdir(exist_ok=True)
    (common / "info" / "exclude").write_text("planted.txt\n")
    (main / "planted.txt").write_text("p")
    (wt / "planted.txt").write_text("p")
    return main, wt


def run(main, wt, **kw):
    return clean_worktree(str(wt), main_checkout=str(main), target_ref="main", **kw)


def test_recoverable_output_goes_and_unique_stays(setup):
    main, wt = setup

    res = run(main, wt, apply=True)

    assert res["state"] == "cleaned"
    assert not (wt / "out" / "copy.pdf").exists()
    assert not (wt / "out" / "render.bin").exists()
    assert not (wt / "__pycache__").exists()          # emptied cache dir removed too
    assert set(res["by_reason"]) == {"in_target_branch", "in_main_checkout", "cache"}
    assert (wt / "out" / "unique.bin").read_bytes() == b"only here"
    assert (wt / "out" / "differs.bin").read_bytes() == b"B" * 10
    assert (wt / ".env").exists() and (wt / ".venv" / "lib.bin").exists()
    assert (wt / "planted.txt").exists()
    assert res["kept_unique_files"] >= 2
    # the main checkout is never touched
    assert (main / "out" / "render.bin").exists() and (main / "out" / "differs.bin").exists()
    assert git(wt, "status", "--porcelain").stdout == ""


def test_dry_run_deletes_nothing(setup):
    main, wt = setup
    res = run(main, wt)
    assert res["state"] == "planned" and res["files"] == 3
    assert (wt / "out" / "copy.pdf").exists() and (wt / "out" / "render.bin").exists()


@pytest.mark.parametrize("dirt", ["modified", "untracked"])
def test_dirty_copy_is_left_alone(setup, dirt):
    main, wt = setup
    if dirt == "modified":
        (wt / "src.py").write_text("x = 2\n")
    else:
        (wt / "notes.md").write_text("wip")

    res = run(main, wt, apply=True)

    assert res["state"] == "refused"
    assert (wt / "out" / "copy.pdf").exists() and (wt / "out" / "render.bin").exists()


def test_copy_used_by_a_process_is_left_alone(setup):
    main, wt = setup
    proc = subprocess.Popen(["sleep", "30"], cwd=wt)
    try:
        res = run(main, wt, apply=True)
    finally:
        proc.kill()
        proc.wait()
    assert res["state"] == "refused" and str(proc.pid) in res["reason"]
    assert (wt / "out" / "render.bin").exists()


def test_open_file_inside_counts_as_busy(setup):
    main, wt = setup
    with (wt / "out" / "render.bin").open("rb"):
        assert run(main, wt, apply=True)["state"] == "refused"
    assert (wt / "out" / "render.bin").exists()


def test_file_changed_between_plan_and_delete_is_kept(setup, monkeypatch):
    main, wt = setup
    real = worktree_cleanup._refusal
    calls = {"n": 0}

    def refusal(path, g):
        calls["n"] += 1
        if calls["n"] == 2:   # the re-check right before deleting
            (wt / "out" / "render.bin").write_bytes(b"S" * 4096)
            os.utime(wt / "out" / "render.bin", ns=(1, 1))
        return real(path, g)

    monkeypatch.setattr(worktree_cleanup, "_refusal", refusal)
    run(main, wt, apply=True)
    assert (wt / "out" / "render.bin").read_bytes() == b"S" * 4096


def test_main_checkout_itself_is_refused(setup):
    main, _wt = setup
    assert clean_worktree(str(main), main_checkout=str(main), target_ref="main",
                          apply=True)["state"] == "refused"


async def _run_merge(monkeypatch, ok: bool):
    import app.merge_operations as operations

    monkeypatch.setattr("app.workspace.inspect_worktree_identity",
                        lambda _path: ("task-42/worker", "b" * 40))
    monkeypatch.setattr("app.workspace._resolve_repo", lambda wt, _fb: Path("/scope"))
    calls = []
    monkeypatch.setattr("app.worktree_cleanup.clean_worktree",
                        lambda wt, **kw: calls.append((wt, kw)) or {"state": "cleaned"})

    async def fake_execute(**_kwargs):
        return {
            "ok": ok, "state": "merged" if ok else "failed",
            "commit_point": "target_committed" if ok else "not_reached",
            "target_branch": "main", "target_before": "a" * 40,
            "target_after": "c" * 40 if ok else "a" * 40,
            "worker_branch": "task-42/worker", "worker_head": "b" * 40,
            "conflicts": [], "commits_merged": 1 if ok else 0,
            "lifecycle_status": {"ok": True}, "rag_backfill_status": "accepted",
            **({} if ok else {"error": "boom"}),
        }

    monkeypatch.setattr("app.routes.sessions.execute_merge_session", fake_execute)
    await operations.accept_merge_operation(
        operation_id=str(uuid.uuid4()), name="worker", scope="/scope/", target="main")
    await asyncio.wait_for(asyncio.gather(*list(operations._runner_tasks.values())), timeout=30)
    return calls


@pytest.mark.asyncio
async def test_successful_merge_cleans_the_worker_copy(merge_db, monkeypatch):  # noqa: F811
    calls = await _run_merge(monkeypatch, ok=True)
    assert calls == [("/worktree", {"main_checkout": "/scope", "target_ref": "main", "apply": True})]


@pytest.mark.asyncio
async def test_failed_merge_does_not_clean(merge_db, monkeypatch):  # noqa: F811
    assert await _run_merge(monkeypatch, ok=False) == []
