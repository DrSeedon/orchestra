"""#17 — сведение запомненной личности воркера с живым git.

Оба сценария воспроизводят живые падения: мерж, отвергавший коммит воркера, сделанный за
время ожидания его же хода, и ремонт ветки, отказывавший именно потому, что git уже прав.
Стенд — настоящий репозиторий и настоящий worktree: подделка git тут ничего не доказала бы.
"""
import subprocess
import uuid
from datetime import datetime, timezone

import pytest


@pytest.fixture
def git_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=repo, capture_output=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=repo, capture_output=True)
    (repo / "README.md").write_text("# test")
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


@pytest.fixture
def db(tmp_path, monkeypatch):
    import app.db as dbmod

    monkeypatch.setattr(dbmod, "DB_PATH", tmp_path / "t.db")
    dbmod.init_db()
    return dbmod


def _row(sid, scope, worktree, branch):
    return {
        "id": sid, "name": "worker", "scope": scope, "cwd": scope, "model": "m",
        "system_prompt": "", "status": "idle", "session_id": None, "cost_usd": 0.0,
        "worktree_path": worktree, "branch": branch, "base_branch": "main",
        "is_orchestrator": False, "color": "",
        "created_at": datetime.now(timezone.utc).isoformat(), "finished_at": None,
        "task_id": "17", "needs_switch": 0,
    }


def _commit(cwd, message, *, amend=False):
    """Коммит с РЕАЛЬНЫМ изменением: у пустого коммита нечего сливать, и squash-мерж
    честно не создаёт ничего — тест зеленел бы на пустом месте."""
    from pathlib import Path

    path = Path(cwd) / f"{abs(hash(message)) % 10**8}.txt"
    path.write_text(message)
    subprocess.run(["git", "add", "-A"], cwd=cwd, capture_output=True, check=True)
    args = ["git", "commit", "--allow-empty", "-m", message]
    if amend:
        args.append("--amend")
    subprocess.run(args, cwd=cwd, capture_output=True, check=True)


def _head(cwd):
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=cwd,
                          capture_output=True, text=True, check=True).stdout.strip()


class TestClassifyHeadDrift:
    def test_same_identity_is_same(self, git_repo, wt_root):
        from app.workspace import classify_head_drift, create_worktree

        wt = create_worktree(str(git_repo), "worker", "17", base_branch="main")
        got = classify_head_drift(wt.path, wt.branch, _head(wt.path))
        assert got["class"] == "SAME"

    def test_worker_commit_on_same_branch_is_benign(self, git_repo, wt_root):
        from app.workspace import classify_head_drift, create_worktree

        wt = create_worktree(str(git_repo), "worker", "17", base_branch="main")
        pinned = _head(wt.path)
        _commit(wt.path, "worker commit")
        got = classify_head_drift(wt.path, wt.branch, pinned)
        assert got["class"] == "BENIGN_ADVANCE"
        assert got["actual_head"] == _head(wt.path) != pinned

    def test_amend_is_fatal_and_says_why(self, git_repo, wt_root):
        from app.workspace import classify_head_drift, create_worktree

        wt = create_worktree(str(git_repo), "worker", "17", base_branch="main")
        _commit(wt.path, "worker commit")
        pinned = _head(wt.path)
        _commit(wt.path, "worker commit rewritten", amend=True)
        got = classify_head_drift(wt.path, wt.branch, pinned)
        assert got["class"] == "FATAL"
        assert "rebase/amend/reset" in got["reason"]

    def test_branch_change_is_fatal_and_names_both(self, git_repo, wt_root):
        from app.workspace import classify_head_drift, create_worktree

        wt = create_worktree(str(git_repo), "worker", "17", base_branch="main")
        pinned = _head(wt.path)
        subprocess.run(["git", "checkout", "-b", "other"], cwd=wt.path,
                       capture_output=True, check=True)
        got = classify_head_drift(wt.path, wt.branch, pinned)
        assert got["class"] == "FATAL"
        assert wt.branch in got["reason"] and "other" in got["reason"]

    def test_unknown_pinned_commit_is_fatal_not_exception(self, git_repo, wt_root):
        from app.workspace import classify_head_drift, create_worktree

        wt = create_worktree(str(git_repo), "worker", "17", base_branch="main")
        got = classify_head_drift(wt.path, wt.branch, "0" * 40)
        assert got["class"] == "FATAL"
        assert "unknown to repository" in got["reason"]


async def _merge_with_wait(monkeypatch, db, git_repo, wt, sid, pinned_head, during_wait):
    """Прогнать мерж, выполнив during_wait() ровно в окне ожидания хода воркера."""
    import app.routes.sessions as S

    async def wait(session):
        during_wait()
        return True

    monkeypatch.setattr(S, "_wait_for_merge_idle", wait)
    return await S.execute_merge_session(
        session_id=sid, expected_name="worker", expected_scope=str(git_repo),
        expected_branch=wt.branch, expected_head=pinned_head, req={},
    )


@pytest.mark.asyncio
async def test_worker_commit_during_wait_is_merged_not_rejected(
    git_repo, wt_root, db, monkeypatch,
):
    """A: воркер коммитит, пока мерж ждёт его же хода. Раньше — отказ «worker HEAD changed»."""
    from app.workspace import create_worktree

    wt = create_worktree(str(git_repo), "worker", "17", base_branch="main")
    pinned = _head(wt.path)
    sid = str(uuid.uuid4())
    db.save_session(_row(sid, str(git_repo), wt.path, wt.branch))

    committed: list[str] = []

    def worker_commits():
        _commit(wt.path, "#17: worker commit before DONE")
        committed.append(_head(wt.path))

    res = await _merge_with_wait(monkeypatch, db, git_repo, wt, sid, pinned, worker_commits)
    assert res.get("ok") is True, res.get("error")
    assert res["head_drift"] == "BENIGN_ADVANCE"
    assert res["worker_head_pinned"] == pinned
    # Слит именно тот HEAD, который воркер сделал во время ожидания, а не запиннённый.
    # После squash-мержа ветка воркера переставляется, поэтому сверяем с записанным тогда.
    assert res["worker_head"] == committed[0] != pinned
    merged = subprocess.run(["git", "log", "--format=%s%n%b", "-1", "main"], cwd=git_repo,
                            capture_output=True, text=True, check=True).stdout
    assert "worker commit before DONE" in merged


@pytest.mark.asyncio
async def test_history_rewrite_during_wait_is_refused_with_reason(
    git_repo, wt_root, db, monkeypatch,
):
    from app.workspace import create_worktree

    wt = create_worktree(str(git_repo), "worker", "17", base_branch="main")
    _commit(wt.path, "worker commit")
    pinned = _head(wt.path)
    sid = str(uuid.uuid4())
    db.save_session(_row(sid, str(git_repo), wt.path, wt.branch))
    target_before = _head(git_repo)

    res = await _merge_with_wait(
        monkeypatch, db, git_repo, wt, sid, pinned,
        lambda: _commit(wt.path, "rewritten", amend=True),
    )
    assert res.get("ok") is False
    assert res["commit_point"] == "not_reached"
    assert "rebase/amend/reset" in res["error"]
    assert _head(git_repo) == target_before


@pytest.mark.asyncio
async def test_branch_change_during_wait_is_refused_with_reason(
    git_repo, wt_root, db, monkeypatch,
):
    from app.workspace import create_worktree

    wt = create_worktree(str(git_repo), "worker", "17", base_branch="main")
    pinned = _head(wt.path)
    sid = str(uuid.uuid4())
    db.save_session(_row(sid, str(git_repo), wt.path, wt.branch))

    def switch_away():
        subprocess.run(["git", "checkout", "-b", "sidetrack"], cwd=wt.path,
                       capture_output=True, check=True)

    res = await _merge_with_wait(monkeypatch, db, git_repo, wt, sid, pinned, switch_away)
    assert res.get("ok") is False
    assert "branch changed" in res["error"] and "sidetrack" in res["error"]


class TestAlreadyOnBranchIsRepairNotError:
    def test_base_contained_is_idempotent_success_without_moving_head(self, git_repo, wt_root):
        from app.workspace import create_worktree, switch_worktree_branch

        wt = create_worktree(str(git_repo), "worker", "17", base_branch="main")
        before = _head(wt.path)
        res = switch_worktree_branch(wt.path, wt.branch, from_ref="main", force=True)
        assert res["ok"] is True
        assert res["state"] == "already_on_branch"
        assert res["branch"] == wt.branch
        assert _head(wt.path) == before

    def test_other_base_is_refused_and_names_both(self, git_repo, wt_root):
        from app.workspace import create_worktree, switch_worktree_branch

        wt = create_worktree(str(git_repo), "worker", "17", base_branch="main")
        subprocess.run(["git", "branch", "feature/auth", "main"], cwd=git_repo,
                       capture_output=True, check=True)
        subprocess.run(["git", "checkout", "feature/auth"], cwd=git_repo,
                       capture_output=True, check=True)
        _commit(git_repo, "base moved ahead")
        subprocess.run(["git", "checkout", "main"], cwd=git_repo, capture_output=True, check=True)

        res = switch_worktree_branch(wt.path, wt.branch, from_ref="feature/auth", force=True)
        assert res["ok"] is False
        assert wt.branch in res["error"] and "feature/auth" in res["error"]

    def test_dirty_tree_still_refused(self, git_repo, wt_root):
        from pathlib import Path

        from app.workspace import create_worktree, switch_worktree_branch

        wt = create_worktree(str(git_repo), "worker", "17", base_branch="main")
        (Path(wt.path) / "dirty.txt").write_text("uncommitted")
        res = switch_worktree_branch(wt.path, wt.branch, from_ref="main", force=True)
        assert res["ok"] is False
        assert "dirty working tree" in res["error"]


@pytest.mark.asyncio
async def test_stale_db_is_repaired_and_merge_proceeds(git_repo, wt_root, db, monkeypatch):
    """B: git ушёл вперёд, БД отстала. Ремонт обязан починить, а не отказать «already on branch»."""
    import json

    import app.routes.sessions as S
    import app.tm as tm
    from app.workspace import create_worktree, inspect_worktree_identity

    wt = create_worktree(str(git_repo), "worker", "17", base_branch="main")
    subprocess.run(["git", "checkout", "-b", "task-18/worker"], cwd=wt.path,
                   capture_output=True, check=True)
    _commit(wt.path, "#18: работа воркера")
    sid = str(uuid.uuid4())
    db.save_session(_row(sid, str(git_repo), wt.path, "task-17/worker"))  # БД отстала

    monkeypatch.setattr(tm, "resolve_scoped_task_identity",
                        lambda scope, task_id: {"par_number": 18, "project_id": "p"})
    monkeypatch.setattr(tm, "api_update_task_if_current", lambda *a, **k: {"ok": True})

    # force=True — потому что на ветке лежит несмерженная работа: ровно тот случай, в котором
    # система и запиралась (мерж нельзя, ремонт «уже там» тоже нельзя).
    resp = await S.switch_branch(
        "worker", {"scope": str(git_repo), "task_id": "18", "force": True},
    )
    body = resp if isinstance(resp, dict) else json.loads(resp.body)
    assert body.get("ok") is True, body
    assert body.get("state") == "already_on_branch"
    assert db.get_session(sid)["branch"] == "task-18/worker"

    async def idle(session):
        return True

    monkeypatch.setattr(S, "_wait_for_merge_idle", idle)
    _branch, head = inspect_worktree_identity(wt.path)
    res = await S.execute_merge_session(
        session_id=sid, expected_name="worker", expected_scope=str(git_repo),
        expected_branch="task-18/worker", expected_head=head, req={},
    )
    assert res.get("ok") is True, res.get("error")
