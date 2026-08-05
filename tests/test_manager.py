"""TDD tests for manager.py — SessionManager."""

import asyncio
import threading
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def db(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setattr("app.db.DB_PATH", db_path)
    from app.db import init_db
    init_db()
    return db_path


@pytest.fixture
def mgr(db, tmp_path, monkeypatch):
    wt_root = tmp_path / "worktrees"
    wt_root.mkdir()
    monkeypatch.setattr("app.workspace.WORKTREE_ROOT", wt_root)
    from app.manager import SessionManager
    return SessionManager()


@pytest.fixture(autouse=True)
def _isolate_pipelines_dir(monkeypatch):
    """Point PIPELINES_DIR at the REAL pipelines/ so ROLE_SYSTEM_PROMPT resolves.

    Was: isolated to an empty tmp dir, relying on the app/prompts legacy fallback
    to still produce prompts. That fallback is removed (single source = pipelines),
    so ROLE_SYSTEM_PROMPT now fails loud on a missing manifest. These tests don't
    test prompts — they need SOME valid pipeline, so use the real default.
    Tests that want a custom manifest override PIPELINES_DIR via ``pipeline_dir``.
    """
    import app.pipeline as pl
    from pathlib import Path
    real = Path(__file__).parent.parent / "pipelines"
    monkeypatch.setattr(pl, "PIPELINES_DIR", real)
    pl.load_pipeline.cache_clear()
    yield
    pl.load_pipeline.cache_clear()


class TestCreateSession:
    @pytest.mark.asyncio
    async def test_returns_session(self, mgr):
        from tests.conftest import make_backend_mock
        with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
            session = await mgr.create_session(
                name="worker-1",
                scope="/test/scope",
                cwd="/tmp",
                model="claude-sonnet-5[1m]",
            )
        assert session.name == "worker-1"
        assert session.id is not None
        assert len(session.id) > 0

    @pytest.mark.asyncio
    async def test_generates_uuid(self, mgr):
        from tests.conftest import make_backend_mock
        with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
            s1 = await mgr.create_session(name="w1", scope="/s", cwd="/tmp", model="claude-sonnet-5[1m]")
            s2 = await mgr.create_session(name="w2", scope="/s", cwd="/tmp", model="claude-sonnet-5[1m]")
        assert s1.id != s2.id

    @pytest.mark.asyncio
    async def test_validates_cwd(self, mgr):
        with pytest.raises(ValueError, match="does not exist"):
            await mgr.create_session(
                name="w", scope="/s", cwd="/nonexistent/path", model="claude-sonnet-5[1m]"
            )

    @pytest.mark.asyncio
    async def test_duplicate_name_scope_raises(self, mgr):
        from tests.conftest import make_backend_mock
        with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
            await mgr.create_session(name="w1", scope="/s", cwd="/tmp", model="claude-sonnet-5[1m]")
            with pytest.raises(ValueError, match="already exists"):
                await mgr.create_session(name="w1", scope="/s", cwd="/tmp", model="claude-sonnet-5[1m]")

    @pytest.mark.asyncio
    async def test_persists_to_db(self, mgr):
        from app.db import get_session_by_name
        from tests.conftest import make_backend_mock
        with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
            session = await mgr.create_session(name="w1", scope="/s", cwd="/tmp", model="claude-sonnet-5[1m]")
        db_row = get_session_by_name("w1", "/s")
        assert db_row is not None
        assert db_row["id"] == session.id

    @pytest.mark.asyncio
    async def test_with_worktree(self, mgr, tmp_path):
        import subprocess
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)
        subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=repo, capture_output=True)
        subprocess.run(["git", "config", "user.name", "T"], cwd=repo, capture_output=True)
        (repo / "f.txt").write_text("x")
        subprocess.run(["git", "add", "."], cwd=repo, capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", "i"], cwd=repo, capture_output=True, check=True)
        subprocess.run(["git", "branch", "-M", "main"], cwd=repo, capture_output=True, check=True)

        from tests.conftest import make_backend_mock
        with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
            session = await mgr.create_session(
                name="w1", scope="/s", cwd=str(repo),
                model="claude-sonnet-5[1m]", use_worktree=True, repo_path=str(repo),
            )
        assert session.worktree_path is not None
        assert session.branch is not None
        assert session._spawn_repo_path == str(repo.resolve())
        assert session._spawn_git_common_dir == str((repo / ".git").resolve())

    @pytest.mark.asyncio
    async def test_repo_preflight_runs_before_spawn_side_effects(self, mgr, tmp_path):
        repo = _git_repo(tmp_path)
        nested = repo / "nested"
        nested.mkdir()

        with patch(
            "app.manager.validate_repo_root",
            side_effect=ValueError("repo_path must be the Git repository root"),
        ) as validate, patch(
            "app.manager.publish_ready_session",
        ) as publish:
            with pytest.raises(ValueError, match="must be the Git repository root"):
                await mgr.create_session(
                    name="w1", scope="/s", cwd=str(nested), model="claude-sonnet-5[1m]",
                    use_worktree=True, repo_path=str(nested),
                )

        validate.assert_called_once_with(str(nested))
        publish.assert_not_called()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("repo_path", ["", None])
    async def test_missing_repo_path_fails_before_spawn_side_effects(
        self, mgr, repo_path,
    ):
        with patch("app.manager.publish_ready_session") as publish:
            with pytest.raises(
                ValueError, match="repo_path required when use_worktree=True",
            ):
                await mgr.create_session(
                    name="w1", scope="/s", cwd="/tmp", model="claude-sonnet-5[1m]",
                    use_worktree=True, repo_path=repo_path,
                )

        publish.assert_not_called()


class TestAtomicSpawnLifecycle:
    @pytest.mark.asyncio
    async def test_blocked_worktree_preparation_is_not_visible(
        self, mgr, tmp_path, monkeypatch,
    ):
        from app.db import get_session_by_name
        import app.manager as manager_module

        repo = _git_repo(tmp_path)
        entered = threading.Event()
        release = threading.Event()
        real_create = manager_module.create_worktree

        def blocked_create(*args, **kwargs):
            entered.set()
            assert release.wait(2)
            return real_create(*args, **kwargs)

        monkeypatch.setattr(manager_module, "create_worktree", blocked_create)
        spawn = asyncio.create_task(mgr.create_session(
            name="hidden", scope="/s", cwd=str(repo),
            model="claude-sonnet-5[1m]", use_worktree=True,
            repo_path=str(repo),
        ))
        assert await asyncio.to_thread(entered.wait, 2)

        assert get_session_by_name("hidden", "/s") is None
        assert mgr.get_by_name("hidden", "/s") is None
        assert [s for s in mgr.list_sessions("/s") if s["name"] == "hidden"] == []

        release.set()
        session = await spawn
        assert get_session_by_name("hidden", "/s")["id"] == session.id
        assert mgr.sessions[session.id] is session

    @pytest.mark.asyncio
    async def test_cancelled_blocked_git_waits_then_removes_worktree_and_branch(
        self, mgr, tmp_path, monkeypatch,
    ):
        import subprocess
        import app.manager as manager_module
        from app.db import get_session_by_name
        from app.workspace import _slugify

        repo = _git_repo(tmp_path)
        entered = threading.Event()
        release = threading.Event()
        cleanup_entered = threading.Event()
        cleanup_release = threading.Event()
        real_create = manager_module.create_worktree
        real_discard = manager_module.discard_prepared_worktree

        def blocked_create(*args, **kwargs):
            entered.set()
            assert release.wait(2)
            return real_create(*args, **kwargs)

        def blocked_discard(*args, **kwargs):
            cleanup_entered.set()
            assert cleanup_release.wait(2)
            return real_discard(*args, **kwargs)

        monkeypatch.setattr(manager_module, "create_worktree", blocked_create)
        monkeypatch.setattr(
            manager_module, "discard_prepared_worktree", blocked_discard,
        )
        spawn = asyncio.create_task(mgr.create_session(
            name="cancelled", scope="/s", cwd=str(repo),
            model="claude-sonnet-5[1m]", use_worktree=True,
            repo_path=str(repo),
        ))
        assert await asyncio.to_thread(entered.wait, 2)
        spawn.cancel()
        await asyncio.sleep(0)
        assert spawn.done() is False
        spawn.cancel()
        await asyncio.sleep(0)
        assert spawn.done() is False

        release.set()
        assert await asyncio.to_thread(cleanup_entered.wait, 2)
        spawn.cancel()
        await asyncio.sleep(0)
        assert spawn.done() is False
        cleanup_release.set()
        with pytest.raises(asyncio.CancelledError):
            await spawn

        branch = f"feat/{_slugify(str(repo.resolve()))}/cancelled"
        assert get_session_by_name("cancelled", "/s") is None
        assert mgr.get_by_name("cancelled", "/s") is None
        listing = subprocess.run(
            ["git", "worktree", "list", "--porcelain"], cwd=repo,
            capture_output=True, text=True, check=True,
        ).stdout
        assert listing.count("worktree ") == 1
        assert subprocess.run(
            ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{branch}"],
            cwd=repo,
        ).returncode == 1

    @pytest.mark.asyncio
    async def test_finalize_owns_resources_when_caller_is_cancelled(
        self, mgr, monkeypatch,
    ):
        import app.manager as manager_module
        from app.db import get_session_by_name

        entered = threading.Event()
        release = threading.Event()
        real_publish = manager_module.publish_ready_session

        def blocked_publish(row):
            entered.set()
            assert release.wait(2)
            return real_publish(row)

        monkeypatch.setattr(manager_module, "publish_ready_session", blocked_publish)
        spawn = asyncio.create_task(mgr.create_session(
            name="finalized", scope="/s", cwd="/tmp",
            model="claude-sonnet-5[1m]",
        ))
        assert await asyncio.to_thread(entered.wait, 2)
        spawn.cancel()
        await asyncio.sleep(0)
        spawn.cancel()
        await asyncio.sleep(0)
        assert spawn.done() is False

        release.set()
        session = await spawn

        row = get_session_by_name("finalized", "/s")
        assert row["id"] == session.id
        assert mgr.sessions[session.id] is session

    @pytest.mark.asyncio
    async def test_prepare_internal_cancellation_is_compensated(
        self, mgr, tmp_path, monkeypatch,
    ):
        import subprocess
        from app.db import get_session_by_name
        from app.session import AgentSession

        repo = _git_repo(tmp_path)

        async def cancelled_start(_session, *args, **kwargs):
            raise asyncio.CancelledError

        monkeypatch.setattr(AgentSession, "start", cancelled_start)

        with pytest.raises(asyncio.CancelledError):
            await mgr.create_session(
                name="internally-cancelled", scope="/s", cwd=str(repo),
                model="claude-sonnet-5[1m]", use_worktree=True,
                repo_path=str(repo),
            )

        assert get_session_by_name("internally-cancelled", "/s") is None
        listing = subprocess.run(
            ["git", "worktree", "list", "--porcelain"], cwd=repo,
            capture_output=True, text=True, check=True,
        ).stdout
        assert listing.count("worktree ") == 1
        assert "internally-cancelled" not in listing

    @pytest.mark.asyncio
    async def test_final_db_failure_aborts_runtime_before_git_cleanup(
        self, mgr, tmp_path, monkeypatch,
    ):
        import app.manager as manager_module
        from app.db import get_session_by_name
        from app.session import AgentSession, AgentStatus

        repo = _git_repo(tmp_path)
        order = []
        runtime = {}
        real_abort = AgentSession.abort_unpublished
        real_discard = manager_module.discard_prepared_worktree

        async def prepared_start(session, initial_message=None, *, persist=True):
            assert initial_message is None and persist is False
            session.status = AgentStatus.IDLE
            session._backend = AsyncMock()
            session._background_tasks.add(
                asyncio.create_task(asyncio.Event().wait())
            )
            session._listen_task = asyncio.create_task(asyncio.Event().wait())
            session._heartbeat_task = asyncio.create_task(asyncio.Event().wait())
            runtime["session"] = session

        async def record_abort(session):
            order.append("abort")
            await real_abort(session)

        def record_discard(repo_path, worktree):
            order.append("git")
            return real_discard(repo_path, worktree)

        monkeypatch.setattr(AgentSession, "start", prepared_start)
        monkeypatch.setattr(AgentSession, "abort_unpublished", record_abort)
        monkeypatch.setattr(
            manager_module, "discard_prepared_worktree", record_discard,
        )
        monkeypatch.setattr(
            manager_module, "publish_ready_session",
            lambda _row: (_ for _ in ()).throw(RuntimeError("final publish failed")),
        )

        with pytest.raises(RuntimeError, match="final publish failed"):
            await mgr.create_session(
                name="publish-failure", scope="/s", cwd=str(repo),
                model="claude-sonnet-5[1m]", use_worktree=True,
                repo_path=str(repo),
            )

        session = runtime["session"]
        assert order == ["abort", "git"]
        assert session._background_tasks == set()
        assert session._listen_task is None
        assert session._heartbeat_task is None
        assert session._backend is None
        assert get_session_by_name("publish-failure", "/s") is None
        assert list(mgr.sessions) == []

    @pytest.mark.asyncio
    async def test_same_identity_spawns_are_serialized_before_git(
        self, mgr, tmp_path, monkeypatch,
    ):
        import app.manager as manager_module

        repo = _git_repo(tmp_path)
        entered = threading.Event()
        release = threading.Event()
        real_create = manager_module.create_worktree
        calls = 0

        def blocked_create(*args, **kwargs):
            nonlocal calls
            calls += 1
            entered.set()
            assert release.wait(2)
            return real_create(*args, **kwargs)

        monkeypatch.setattr(manager_module, "create_worktree", blocked_create)
        first = asyncio.create_task(mgr.create_session(
            name="same", scope="/s", cwd=str(repo),
            model="claude-sonnet-5[1m]", use_worktree=True,
            repo_path=str(repo),
        ))
        assert await asyncio.to_thread(entered.wait, 2)
        second = asyncio.create_task(mgr.create_session(
            name="same", scope="/s", cwd=str(repo),
            model="claude-sonnet-5[1m]", use_worktree=True,
            repo_path=str(repo),
        ))
        await asyncio.sleep(0)
        assert calls == 1

        release.set()
        results = await asyncio.gather(first, second, return_exceptions=True)
        assert sum(not isinstance(item, BaseException) for item in results) == 1
        error = next(item for item in results if isinstance(item, BaseException))
        assert isinstance(error, ValueError)
        assert "already exists" in str(error)
        assert calls == 1

    @pytest.mark.asyncio
    async def test_same_repo_name_across_scopes_has_one_winner(self, mgr, tmp_path):
        from app import tm
        from app.db import get_all_sessions

        repo = _git_repo(tmp_path)
        with tm._conn() as conn:
            tm.ensure_project(conn, "a", scope="/a")
            tm.ensure_project(conn, "b", scope="/b")
            task_a = tm.create_task(conn, "a", "A", par_number=1)
            task_b = tm.create_task(conn, "b", "B", par_number=2)
        results = await asyncio.gather(
            mgr.create_session(
                name="repo-shared", scope="/a", cwd=str(repo),
                model="claude-sonnet-5[1m]", use_worktree=True,
                repo_path=str(repo), task_id="1",
            ),
            mgr.create_session(
                name="repo-shared", scope="/b", cwd=str(repo),
                model="claude-sonnet-5[1m]", use_worktree=True,
                repo_path=str(repo), task_id="2",
            ),
            return_exceptions=True,
        )

        assert sum(not isinstance(item, BaseException) for item in results) == 1
        assert sum(isinstance(item, BaseException) for item in results) == 1
        assert len([r for r in get_all_sessions() if r["name"] == "repo-shared"]) == 1
        with tm._conn() as conn:
            statuses = {
                tm.get_task_by_id(conn, task_a["id"])["status"],
                tm.get_task_by_id(conn, task_b["id"])["status"],
            }
        assert statuses == {"new", "in_progress"}

    @pytest.mark.asyncio
    async def test_invalid_task_preserves_archived_history(self, mgr):
        from app import tm
        from app.db import add_log, archive_session, get_logs, get_session, save_session

        with tm._conn() as conn:
            tm.ensure_project(conn, "project", scope="/s")
        archived = {
            "id": "archived-worker", "name": "history", "scope": "/s",
            "cwd": "/tmp", "model": "claude-sonnet-5[1m]", "system_prompt": "",
            "status": "idle", "session_id": None, "cost_usd": 0.0,
            "worktree_path": None, "branch": None, "is_orchestrator": False,
            "color": "", "created_at": datetime.now(timezone.utc).isoformat(),
            "finished_at": None,
        }
        save_session(archived)
        add_log("archived-worker", datetime.now(timezone.utc), "text", "history")
        archive_session("archived-worker")

        with pytest.raises(ValueError, match="not found in session project"):
            await mgr.create_session(
                name="history", scope="/s", cwd="/tmp",
                model="claude-sonnet-5[1m]", task_id="999",
            )

        assert get_session("archived-worker")["status"] == "archived"
        assert [row["content"] for row in get_logs("archived-worker")] == ["history"]

    @pytest.mark.asyncio
    async def test_successful_respawn_atomically_replaces_archived_history(self, mgr):
        from app.db import add_log, archive_session, get_logs, get_session, save_session

        archived = {
            "id": "old-worker", "name": "respawn", "scope": "/s",
            "cwd": "/tmp", "model": "claude-sonnet-5[1m]", "system_prompt": "",
            "status": "idle", "session_id": None, "cost_usd": 0.0,
            "worktree_path": None, "branch": None, "is_orchestrator": False,
            "color": "", "created_at": datetime.now(timezone.utc).isoformat(),
            "finished_at": None,
        }
        save_session(archived)
        add_log("old-worker", datetime.now(timezone.utc), "text", "old history")
        archive_session("old-worker")

        session = await mgr.create_session(
            name="respawn", scope="/s", cwd="/tmp",
            model="claude-sonnet-5[1m]",
        )

        assert get_session("old-worker") is None
        assert get_logs("old-worker") == []
        assert get_session(session.id)["status"] == "idle"

    @pytest.mark.asyncio
    async def test_spawn_updates_only_scoped_task_after_publication(self, mgr):
        from app import tm
        from app.db import get_session

        with tm._conn() as conn:
            tm.ensure_project(conn, "a", scope="/a")
            tm.ensure_project(conn, "b", scope="/b")
            task_a = tm.create_task(conn, "a", "A", par_number=93)
            task_b = tm.create_task(conn, "b", "B", par_number=93)

        session = await mgr.create_session(
            name="scoped-task", scope="/b", cwd="/tmp",
            model="claude-sonnet-5[1m]", task_id="93",
        )

        with tm._conn() as conn:
            assert tm.get_task_by_id(conn, task_a["id"])["status"] == "new"
            updated_b = tm.get_task_by_id(conn, task_b["id"])
        assert updated_b["status"] == "in_progress"
        assert updated_b["worker_session_id"] == session.id
        assert get_session(session.id)["status"] == "idle"

    @pytest.mark.asyncio
    async def test_task_update_failure_returns_ready_worker_warning(
        self, mgr, monkeypatch,
    ):
        from app import tm
        from app.db import get_session

        with tm._conn() as conn:
            tm.ensure_project(conn, "project", scope="/s")
            task = tm.create_task(conn, "project", "next", par_number=93)
        monkeypatch.setattr(
            tm,
            "api_update_task_if_current",
            lambda *_args, **_kwargs: {
                "ok": False, "error": "task revision changed",
            },
        )

        session = await mgr.create_session(
            name="warning", scope="/s", cwd="/tmp",
            model="claude-sonnet-5[1m]", task_id="93",
        )

        assert "worker is ready" in session._spawn_warning
        assert "task revision changed" in session._spawn_warning
        assert mgr.sessions[session.id] is session
        assert get_session(session.id)["status"] == "idle"
        with tm._conn() as conn:
            assert tm.get_task_by_id(conn, task["id"])["status"] == "new"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("failure_stage", ["worktree", "start", "publish"])
    async def test_spawn_failure_leaves_task_unchanged_and_cleans_git(
        self, mgr, tmp_path, monkeypatch, failure_stage,
    ):
        import subprocess
        import app.manager as manager_module
        from app import tm
        from app.db import get_session_by_name
        from app.session import AgentSession

        repo = _git_repo(tmp_path)
        with tm._conn() as conn:
            tm.ensure_project(conn, "project", scope="/s")
            task = tm.create_task(conn, "project", "next", par_number=93)

        if failure_stage == "worktree":
            monkeypatch.setattr(
                manager_module,
                "create_worktree",
                lambda *_args, **_kwargs: (_ for _ in ()).throw(
                    RuntimeError("worktree failed")
                ),
            )
        elif failure_stage == "start":
            monkeypatch.setattr(
                AgentSession,
                "start",
                AsyncMock(side_effect=RuntimeError("start failed")),
            )
        else:
            monkeypatch.setattr(
                manager_module,
                "publish_ready_session",
                lambda _row: (_ for _ in ()).throw(
                    RuntimeError("publish failed")
                ),
            )

        with pytest.raises(RuntimeError, match=failure_stage):
            await mgr.create_session(
                name=f"fail-{failure_stage}", scope="/s", cwd=str(repo),
                model="claude-sonnet-5[1m]", use_worktree=True,
                repo_path=str(repo), task_id="93",
            )

        with tm._conn() as conn:
            unchanged = tm.get_task_by_id(conn, task["id"])
        assert unchanged["status"] == "new"
        assert unchanged["worker_session_id"] in (None, "")
        assert get_session_by_name(f"fail-{failure_stage}", "/s") is None
        assert subprocess.run(
            [
                "git", "show-ref", "--verify", "--quiet",
                f"refs/heads/task-93/fail-{failure_stage}",
            ],
            cwd=repo,
        ).returncode == 1
        listing = subprocess.run(
            ["git", "worktree", "list", "--porcelain"], cwd=repo,
            capture_output=True, text=True, check=True,
        ).stdout
        assert listing.count("worktree ") == 1


class TestWorktreeBaseBranch:
    @pytest.mark.asyncio
    async def test_worktree_from_feature_branch(self, mgr, tmp_path):
        import subprocess
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)
        subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=repo, capture_output=True)
        subprocess.run(["git", "config", "user.name", "T"], cwd=repo, capture_output=True)
        (repo / "f.txt").write_text("x")
        subprocess.run(["git", "add", "."], cwd=repo, capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", "i"], cwd=repo, capture_output=True, check=True)
        subprocess.run(["git", "branch", "-M", "main"], cwd=repo, capture_output=True, check=True)
        subprocess.run(["git", "branch", "feature/auth"], cwd=repo, capture_output=True, check=True)

        from tests.conftest import make_backend_mock
        with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
            session = await mgr.create_session(
                name="w1", scope="/s", cwd=str(repo), model="claude-sonnet-5[1m]",
                use_worktree=True, repo_path=str(repo), base_branch="feature/auth",
            )
        head = subprocess.run(["git", "rev-parse", "feature/auth"], cwd=repo,
                              capture_output=True, text=True).stdout.strip()
        base = subprocess.run(["git", "merge-base", session.branch, "feature/auth"], cwd=repo,
                              capture_output=True, text=True).stdout.strip()
        assert base == head
        assert session.base_branch == "feature/auth"

    @pytest.mark.asyncio
    async def test_omitted_base_resolves_and_persists_master(self, mgr, tmp_path):
        import subprocess

        repo = _git_repo(tmp_path)
        subprocess.run(["git", "branch", "-m", "master"], cwd=repo, check=True)

        from app.db import get_session
        from tests.conftest import make_backend_mock
        with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
            session = await mgr.create_session(
                name="master-worker", scope="/s", cwd=str(repo), model="claude-sonnet-5[1m]",
                use_worktree=True, repo_path=str(repo),
            )

        assert session.base_branch == "master"
        assert get_session(session.id)["base_branch"] == "master"


def _git_repo(tmp_path):
    """Минимальный git-репо с веткой main для worktree-тестов."""
    import subprocess
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=repo, capture_output=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=repo, capture_output=True)
    (repo / "f.txt").write_text("x")
    subprocess.run(["git", "add", "."], cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "i"], cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "branch", "-M", "main"], cwd=repo, capture_output=True, check=True)
    return repo


class TestInjectSkillsGating:
    """Native skill copies are Claude-only and explicit-list only."""

    async def _run(self, mgr, tmp_path, role_mock, *, model="opus"):
        from tests.conftest import make_backend_mock
        repo = _git_repo(tmp_path)
        inject = MagicMock()
        with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()), \
             patch("app.manager.inject_skills_to_worktree", inject), \
             patch("app.manager.get_role", role_mock):
            await mgr.create_session(
                name="w1", scope="/s", cwd=str(repo), model=model,
                use_worktree=True, repo_path=str(repo),
            )
        return inject

    @pytest.mark.asyncio
    async def test_skills_all_skips_injection(self, mgr, tmp_path):
        rr = MagicMock(skills="all", is_orchestrator=False)
        inject = await self._run(mgr, tmp_path, lambda p, r: rr)
        inject.assert_not_called()

    @pytest.mark.asyncio
    async def test_skills_list_injects(self, mgr, tmp_path):
        rr = MagicMock(skills=["foo", "bar"], is_orchestrator=False)
        inject = await self._run(mgr, tmp_path, lambda p, r: rr)
        inject.assert_called_once()
        # resolved pipeline skills are passed through, not the role name
        assert inject.call_args.args[0] == ["foo", "bar"]

    @pytest.mark.asyncio
    async def test_codex_skills_list_does_not_inject(self, mgr, tmp_path):
        rr = MagicMock(skills=["foo", "bar"], is_orchestrator=False)
        inject = await self._run(
            mgr, tmp_path, lambda p, r: rr, model="gpt5.6sol",
        )
        inject.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_manifest_raises(self, mgr, tmp_path):
        # Was test_no_manifest_injects: legacy fallback let a spawn proceed (and
        # inject skills) when get_role raised FileNotFoundError. Fallback removed →
        # missing manifest is fail loud, spawn aborts before skill injection.
        def _raise(p, r):
            raise FileNotFoundError("no manifest")
        with pytest.raises((FileNotFoundError, ValueError)):
            await self._run(mgr, tmp_path, _raise)


class TestInjectSkillsRealCopy:
    """T0 AC: real injector actually copies skills/<name>.md → worktree/.claude/skills/<name>/SKILL.md.

    The mocked gating tests prove the resolved list is passed; this proves files land on disk.
    """

    def test_copies_pipeline_skills_to_worktree(self, tmp_path):
        from app.prompting import inject_skills_to_worktree
        wt = _git_repo(tmp_path)
        # codex-debate + html-artifacts are both real files in prompts/skills/
        inject_skills_to_worktree(["codex-debate", "html-artifacts"], str(wt))
        for name in ("codex-debate", "html-artifacts"):
            assert (wt / ".claude" / "skills" / name / "SKILL.md").is_file(), \
                f"{name} not injected into worktree"

    def test_tracked_skill_not_overwritten(self, tmp_path):
        """Task #12: a repo that versions its own `.claude/skills/<name>/SKILL.md` cannot
        exclude it (ignore rules skip tracked files) — injecting there dirties the worker's
        tree permanently and blocks every merge. The repo's version wins."""
        import subprocess
        from app.prompting import inject_skills_to_worktree
        wt = _git_repo(tmp_path)
        own = wt / ".claude" / "skills" / "codex-debate" / "SKILL.md"
        own.parent.mkdir(parents=True)
        own.write_text("# repo's own skill\n")
        subprocess.run(["git", "add", "-A"], cwd=wt, capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", "skill"], cwd=wt, capture_output=True, check=True)

        inject_skills_to_worktree(["codex-debate", "html-artifacts"], str(wt))

        assert own.read_text() == "# repo's own skill\n"
        # untracked skills are still injected — only the repo's own file is off limits
        assert (wt / ".claude" / "skills" / "html-artifacts" / "SKILL.md").is_file()

    def test_empty_list_is_noop(self, tmp_path):
        from app.prompting import inject_skills_to_worktree
        wt = tmp_path / "wt"
        wt.mkdir()
        inject_skills_to_worktree([], str(wt))
        assert not (wt / ".claude").exists()


class TestRefreshSkills:
    """Task #149: injection runs on every backend connect, not only at spawn.

    Two failures it fixes: copies going stale after the source skill is edited, and skills
    added to a role after spawn never arriving (orchestrators have no worktree at all, so
    the worktree-only call site reached none of them — `orchestra-agents` sat at 0 agents).
    The destination may be the user's real working repository, hence the safety assertions.
    """

    def _source(self, name="codex-debate"):
        from app.prompting import _SKILLS_DIR
        return _SKILLS_DIR / f"{name}.md"

    def test_stale_copy_is_refreshed(self, tmp_path):
        from app.prompting import inject_skills_to_worktree
        wt = _git_repo(tmp_path)
        dest = wt / ".claude" / "skills" / "codex-debate" / "SKILL.md"
        dest.parent.mkdir(parents=True)
        dest.write_text("# ancient version from spawn day\n")

        written = inject_skills_to_worktree(["codex-debate"], str(wt))

        assert dest.read_bytes() == self._source().read_bytes()
        assert written == 1

    def test_unchanged_copy_is_not_rewritten(self, tmp_path):
        """Steady state must cost zero writes — otherwise every connect swaps a file
        under a running CLI for no reason."""
        from app.prompting import inject_skills_to_worktree
        wt = _git_repo(tmp_path)
        inject_skills_to_worktree(["codex-debate"], str(wt))
        dest = wt / ".claude" / "skills" / "codex-debate" / "SKILL.md"
        before_mtime = dest.stat().st_mtime_ns

        written = inject_skills_to_worktree(["codex-debate"], str(wt))

        assert written == 0
        assert dest.stat().st_mtime_ns == before_mtime

    def test_tracked_and_untracked_in_one_repo(self, tmp_path):
        """Models the live seedon case: the same repo tracks some of the role's skills and
        not others. Tracked file untouched, untracked one delivered — in a single pass."""
        import subprocess
        from app.prompting import inject_skills_to_worktree
        wt = _git_repo(tmp_path)
        own = wt / ".claude" / "skills" / "codex-debate" / "SKILL.md"
        own.parent.mkdir(parents=True)
        own.write_text("# repo's own skill\n")
        subprocess.run(["git", "add", "-Af"], cwd=wt, capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", "own skill"], cwd=wt, capture_output=True, check=True)

        inject_skills_to_worktree(["codex-debate", "html-artifacts"], str(wt))

        assert own.read_text() == "# repo's own skill\n"
        assert (wt / ".claude" / "skills" / "html-artifacts" / "SKILL.md").read_bytes() \
            == self._source("html-artifacts").read_bytes()

    def test_injection_leaves_repo_clean_without_gitignore(self, tmp_path):
        """The expensive scenario, live in `games`: a repo that ignores `.claude/` NOWHERE.
        Without the exclude step we leave permanent untracked junk in the user's git status."""
        import subprocess
        from app.prompting import inject_skills_to_worktree
        wt = _git_repo(tmp_path)
        assert not (wt / ".gitignore").exists()

        inject_skills_to_worktree(["codex-debate"], str(wt))

        status = subprocess.run(
            ["git", "status", "--short"], cwd=wt, capture_output=True, text=True,
        ).stdout
        assert ".claude" not in status, f"injection dirtied the repo: {status!r}"

    def test_nothing_written_leaves_exclude_untouched(self, tmp_path):
        """No side effects in someone else's repo when we planted nothing."""
        from app.prompting import inject_skills_to_worktree
        wt = _git_repo(tmp_path)
        exclude = wt / ".git" / "info" / "exclude"
        before = exclude.read_text() if exclude.exists() else ""

        assert inject_skills_to_worktree(["no-such-skill-anywhere"], str(wt)) == 0

        after = exclude.read_text() if exclude.exists() else ""
        assert after == before

    def test_non_repo_path_is_skipped(self, tmp_path):
        """Git can't say who owns the file → writing on a guess is what dirties repos."""
        from app.prompting import inject_skills_to_worktree
        plain = tmp_path / "not-a-repo"
        plain.mkdir()

        assert inject_skills_to_worktree(["codex-debate"], str(plain)) == 0
        assert not (plain / ".claude").exists()


class TestResolveBaseBranch:
    """DESIGN §10: резолв base_branch по стратегии манифеста (B3).

    Тестируем ``_resolve_base_branch`` напрямую на инстансе manager, мокая
    ``app.manager.get_role`` (как в TestInjectSkillsGating) и подсовывая
    родителя в ``mgr.sessions`` через лёгкий объект с атрибутом ``branch``.
    """

    def _put_parent(self, mgr, name, scope, branch):
        """Лёгкий родитель в кэше сессий с нужной веткой (без БД)."""
        parent = MagicMock()
        parent.name = name
        parent.scope = scope
        parent.branch = branch
        mgr.sessions[name] = parent

    def test_strategy_main_uses_repository_mainline(self, mgr):
        rr = MagicMock(base_branch_strategy="main")
        with (
            patch("app.manager.get_role", lambda p, r: rr),
            patch("app.manager.resolve_git_base_branch", return_value="master") as resolve,
        ):
            out = mgr._resolve_base_branch(
                "", "default", "pm-glava", "", "/s", "/repo",
            )
        assert out == "master"
        resolve.assert_called_once_with("/repo")

    def test_strategy_parent_uses_parent_branch(self, mgr):
        rr = MagicMock(base_branch_strategy="parent")
        self._put_parent(mgr, "pm", "/s", "feature/x")
        with (
            patch("app.manager.get_role", lambda p, r: rr),
            patch("app.manager.resolve_git_base_branch", return_value="feature/x") as resolve,
        ):
            out = mgr._resolve_base_branch(
                "", "tasks-pm", "coder", "pm", "/s", "/repo",
            )
        assert out == "feature/x"
        resolve.assert_called_once_with("/repo", "feature/x")

    def test_strategy_parent_no_branch_resolves_repository_mainline(self, mgr, caplog):
        import logging
        rr = MagicMock(base_branch_strategy="parent")
        self._put_parent(mgr, "pm", "/s", "")  # у родителя нет ветки
        with (
            patch("app.manager.get_role", lambda p, r: rr),
            patch("app.manager.resolve_git_base_branch", return_value="master") as resolve,
            caplog.at_level(logging.WARNING),
        ):
            out = mgr._resolve_base_branch(
                "", "tasks-pm", "coder", "pm", "/s", "/repo",
            )
        assert out == "master"
        resolve.assert_called_once_with("/repo")
        assert any("resolving repository mainline" in rec.message for rec in caplog.records)

    def test_explicit_branch_overrides_strategy(self, mgr):
        # B3: явная ветка важнее strategy="parent" — get_role даже не зовётся.
        rr = MagicMock(base_branch_strategy="parent")
        self._put_parent(mgr, "pm", "/s", "feature/x")
        with patch("app.manager.resolve_git_base_branch", return_value="dev") as resolve:
            out = mgr._resolve_base_branch(
                "dev", "tasks-pm", "coder", "pm", "/s", "/repo",
            )
        assert out == "dev"
        resolve.assert_called_once_with("/repo", "dev")

    def test_no_manifest_returns_main(self, mgr):
        def _raise(p, r):
            raise FileNotFoundError("no manifest")
        with (
            patch("app.manager.get_role", _raise),
            patch("app.manager.resolve_git_base_branch", return_value="master") as resolve,
        ):
            out = mgr._resolve_base_branch(
                "", "nope", "coder", "pm", "/s", "/repo",
            )
        assert out == "master"
        resolve.assert_called_once_with("/repo")


class TestPersistLifecycle:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("loaded", [False, True])
    async def test_updates_loaded_and_detached_sessions(self, mgr, loaded):
        from app.db import get_session, save_session

        save_session({
            "id": f"life-{loaded}", "name": f"life-{loaded}", "scope": "/s",
            "cwd": "/tmp", "model": "claude-sonnet-5[1m]", "system_prompt": "", "status": "idle",
            "session_id": None, "cost_usd": 0.0, "worktree_path": "/tmp/wt",
            "branch": "task-90/w", "base_branch": "master", "needs_switch": 0,
            "task_id": "90", "is_orchestrator": False, "color": "",
            "created_at": datetime.now(timezone.utc).isoformat(), "finished_at": None,
        })
        session = mgr.get_by_name(f"life-{loaded}", "/s")
        session.loaded = loaded

        await mgr.persist_lifecycle(
            session,
            branch="task-90/w",
            base_branch="master",
            task_id="",
            needs_switch=True,
        )

        row = get_session(session.id)
        assert (row["branch"], row["base_branch"], row["task_id"], row["needs_switch"]) == (
            "task-90/w", "master", "", 1,
        )
        assert session.base_branch == "master"
        assert session.needs_switch is True

    @pytest.mark.asyncio
    async def test_updates_memory_before_async_db_write(self, mgr, monkeypatch):
        session = MagicMock(
            loaded=False,
            id="life-order",
            branch="task-1/w",
            base_branch="main",
            task_id="1",
            needs_switch=False,
            db_row=None,
        )
        observed = {}

        def fake_update(_session_id, **_fields):
            observed["snapshot"] = (
                session.branch,
                session.base_branch,
                session.task_id,
                session.needs_switch,
            )
            return True

        monkeypatch.setattr("app.manager.update_session_lifecycle", fake_update)

        await mgr.persist_lifecycle(
            session,
            branch="task-90/w",
            base_branch="master",
            task_id="",
            needs_switch=True,
        )

        assert observed["snapshot"] == ("task-90/w", "master", "", True)


class TestSendAndControl:
    @pytest.mark.asyncio
    async def test_send_routes(self, mgr):
        from tests.conftest import make_backend_mock
        with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
            session = await mgr.create_session(name="w1", scope="/s", cwd="/tmp", model="claude-sonnet-5[1m]")
            session.send = AsyncMock()
            await mgr.send(session.id, "hello")
        session.send.assert_awaited_once_with("hello")

    @pytest.mark.asyncio
    async def test_send_unknown_raises(self, mgr):
        with pytest.raises(KeyError):
            await mgr.send("nonexistent", "hello")

    @pytest.mark.asyncio
    async def test_send_rechecks_needs_switch_after_session_lock(
        self, mgr, monkeypatch,
    ):
        import app.manager as manager_module

        session = await mgr.create_session(
            name="w", scope="/s", cwd="/tmp", model="claude-sonnet-5[1m]",
        )
        session.worktree_path = "/wt"
        session.branch = "task-90/w"
        session.base_branch = "main"
        session.send = AsyncMock()
        switches = []

        def switch(*args, **kwargs):
            switches.append((args, kwargs))
            return {"ok": True, "branch": "adhoc-1/w"}

        monkeypatch.setattr(manager_module, "resolve_git_base_branch", lambda *_: "main")
        monkeypatch.setattr("app.workspace.switch_worktree_branch", switch)

        lock = mgr.get_session_lock(session.id)
        await lock.acquire()
        delivery = asyncio.create_task(mgr.send(session.id, "after merge"))
        await asyncio.sleep(0)
        await mgr.persist_lifecycle(
            session,
            branch="task-90/w",
            base_branch="main",
            task_id="",
            needs_switch=True,
        )
        lock.release()

        await delivery

        assert len(switches) == 1
        assert session.needs_switch is False
        session.send.assert_awaited_once_with("after merge")

    @pytest.mark.asyncio
    async def test_concurrent_sends_switch_once_and_deliver_serially(
        self, mgr, monkeypatch,
    ):
        import app.manager as manager_module

        session = await mgr.create_session(
            name="w", scope="/s", cwd="/tmp", model="claude-sonnet-5[1m]",
        )
        session.worktree_path = "/wt"
        session.branch = "task-90/w"
        session.base_branch = "main"
        session.needs_switch = True
        switch_count = 0
        active = 0
        max_active = 0
        delivered = []

        def switch(*_args, **_kwargs):
            nonlocal switch_count
            switch_count += 1
            return {"ok": True, "branch": "adhoc-1/w"}

        async def accept(message):
            nonlocal active, max_active
            assert not session._lifecycle_lock.locked()
            active += 1
            max_active = max(max_active, active)
            await asyncio.sleep(0)
            delivered.append(message)
            active -= 1

        session.send = AsyncMock(side_effect=accept)
        monkeypatch.setattr(manager_module, "resolve_git_base_branch", lambda *_: "main")
        monkeypatch.setattr("app.workspace.switch_worktree_branch", switch)

        await asyncio.gather(
            mgr.send(session.id, "first"),
            mgr.send(session.id, "second"),
        )

        assert switch_count == 1
        assert max_active == 1
        assert delivered == ["first", "second"]

    @pytest.mark.asyncio
    async def test_waiting_needs_switch_rejects_without_git_or_backend(
        self, mgr, monkeypatch,
    ):
        from app.session import AgentStatus

        session = await mgr.create_session(
            name="w", scope="/s", cwd="/tmp", model="claude-sonnet-5[1m]",
        )
        session.worktree_path = "/wt"
        session.needs_switch = True
        session.status = AgentStatus.WAITING
        session.send = AsyncMock()
        switch = MagicMock()
        monkeypatch.setattr("app.workspace.switch_worktree_branch", switch)

        with pytest.raises(RuntimeError, match="worker is waiting"):
            await mgr.send(session.id, "must wait")

        switch.assert_not_called()
        session.send.assert_not_awaited()
        assert session.needs_switch is True

    @pytest.mark.asyncio
    async def test_auto_switch_failure_keeps_quarantine_and_surfaces_git_error(
        self, mgr, monkeypatch,
    ):
        import app.manager as manager_module

        session = await mgr.create_session(
            name="w", scope="/s", cwd="/tmp", model="claude-sonnet-5[1m]",
        )
        session.worktree_path = "/wt"
        session.base_branch = "main"
        session.needs_switch = True
        session.send = AsyncMock()
        monkeypatch.setattr(manager_module, "resolve_git_base_branch", lambda *_: "main")
        monkeypatch.setattr(
            "app.workspace.switch_worktree_branch",
            lambda *_args, **_kwargs: {
                "ok": False,
                "state": "rolled_back",
                "error": "target contains uncommitted.txt",
            },
        )

        with pytest.raises(RuntimeError, match="target contains uncommitted.txt"):
            await mgr.send(session.id, "blocked")

        assert session.needs_switch is True
        session.send.assert_not_awaited()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("failing_helper", ["resolve", "switch"])
    async def test_auto_switch_exceptions_have_detail_and_keep_quarantine(
        self, mgr, monkeypatch, failing_helper,
    ):
        import app.manager as manager_module

        session = await mgr.create_session(
            name="w", scope="/s", cwd="/tmp", model="claude-sonnet-5[1m]",
        )
        session.worktree_path = "/wt"
        session.branch = "task-90/w"
        session.base_branch = "main"
        session.needs_switch = True
        session.send = AsyncMock()

        if failing_helper == "resolve":
            def resolve(*_args):
                raise TimeoutError

            switch = MagicMock()
        else:
            resolve = lambda *_args: "main"

            def switch(*_args, **_kwargs):
                raise TimeoutError

            monkeypatch.setattr(
                "app.workspace.inspect_worktree_identity",
                lambda *_args: ("task-90/w", "head"),
            )
        monkeypatch.setattr(manager_module, "resolve_git_base_branch", resolve)
        monkeypatch.setattr("app.workspace.switch_worktree_branch", switch)

        with pytest.raises(RuntimeError, match="TimeoutError"):
            await mgr.send(session.id, "blocked")

        assert session.needs_switch is True
        session.send.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_auto_switch_persist_failure_requarantines_without_delivery(
        self, mgr, monkeypatch,
    ):
        import app.manager as manager_module

        session = await mgr.create_session(
            name="w", scope="/s", cwd="/tmp", model="claude-sonnet-5[1m]",
        )
        session.worktree_path = "/wt"
        session.branch = "task-90/w"
        session.base_branch = "main"
        session.needs_switch = True
        session.send = AsyncMock()
        persist_calls = []

        async def persist(found, **fields):
            persist_calls.append(fields)
            if len(persist_calls) == 1:
                found.needs_switch = False
                raise RuntimeError("database unavailable")
            for key, value in fields.items():
                setattr(found, key, value)

        monkeypatch.setattr(manager_module, "resolve_git_base_branch", lambda *_: "main")
        monkeypatch.setattr(
            "app.workspace.switch_worktree_branch",
            lambda *_args, **_kwargs: {"ok": True, "branch": "adhoc-1/w"},
        )
        monkeypatch.setattr(mgr, "persist_lifecycle", persist)

        with pytest.raises(RuntimeError, match="database unavailable"):
            await mgr.send(session.id, "blocked")

        assert [call["needs_switch"] for call in persist_calls] == [False, True]
        assert session.branch == "adhoc-1/w"
        assert session.needs_switch is True
        session.send.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_send_waits_for_lifecycle_holder_before_git_and_backend(
        self, mgr, monkeypatch,
    ):
        import app.manager as manager_module

        session = await mgr.create_session(
            name="w", scope="/s", cwd="/tmp", model="claude-sonnet-5[1m]",
        )
        session.worktree_path = "/wt"
        session.base_branch = "main"
        session.needs_switch = True
        session.send = AsyncMock()
        switch = MagicMock(return_value={"ok": True, "branch": "adhoc-1/w"})
        monkeypatch.setattr(manager_module, "resolve_git_base_branch", lambda *_: "main")
        monkeypatch.setattr("app.workspace.switch_worktree_branch", switch)

        await session._lifecycle_lock.acquire()
        delivery = asyncio.create_task(mgr.send(session.id, "serialized"))
        await asyncio.sleep(0)
        await asyncio.sleep(0)

        assert mgr.get_session_lock(session.id).locked()
        switch.assert_not_called()
        session.send.assert_not_awaited()

        session._lifecycle_lock.release()
        await asyncio.wait_for(delivery, timeout=2)

        switch.assert_called_once()
        session.send.assert_awaited_once_with("serialized")

    @pytest.mark.asyncio
    @pytest.mark.parametrize("blocked_stage", ["switch", "persist", "backend"])
    async def test_delivery_owns_commit_point_despite_repeated_cancellation(
        self, mgr, monkeypatch, blocked_stage,
    ):
        import app.manager as manager_module

        session = await mgr.create_session(
            name="w", scope="/s", cwd="/tmp", model="claude-sonnet-5[1m]",
        )
        session.worktree_path = "/wt"
        session.branch = "task-90/w"
        session.base_branch = "main"
        session.needs_switch = True
        entered = threading.Event()
        release = threading.Event()
        switch_count = 0
        delivered = []

        def switch(*_args, **_kwargs):
            nonlocal switch_count
            switch_count += 1
            if blocked_stage == "switch":
                entered.set()
                assert release.wait(2)
            return {"ok": True, "branch": "adhoc-1/w"}

        async def persist(found, **fields):
            if blocked_stage == "persist":
                entered.set()
                assert await asyncio.to_thread(release.wait, 2)
            for key, value in fields.items():
                setattr(found, key, value)

        async def accept(message):
            if blocked_stage == "backend":
                entered.set()
                assert await asyncio.to_thread(release.wait, 2)
            delivered.append(message)

        session.send = AsyncMock(side_effect=accept)
        monkeypatch.setattr(manager_module, "resolve_git_base_branch", lambda *_: "main")
        monkeypatch.setattr("app.workspace.switch_worktree_branch", switch)
        monkeypatch.setattr(mgr, "persist_lifecycle", persist)

        delivery = asyncio.create_task(mgr.send(session.id, "exactly once"))
        assert await asyncio.to_thread(entered.wait, 2)
        delivery.cancel()
        await asyncio.sleep(0)
        delivery.cancel()
        await asyncio.sleep(0)

        assert delivery.done() is False
        assert mgr.get_session_lock(session.id).locked()
        release.set()
        await delivery

        assert switch_count == 1
        assert delivered == ["exactly once"]
        assert session.needs_switch is False

    @pytest.mark.asyncio
    async def test_running_send_preserves_mid_turn_delivery(self, mgr):
        from app.session import AgentStatus

        session = await mgr.create_session(
            name="w", scope="/s", cwd="/tmp", model="claude-sonnet-5[1m]",
        )
        session.status = AgentStatus.RUNNING
        session.needs_switch = False
        session.send = AsyncMock()

        await mgr.send(session.id, "steer")

        session.send.assert_awaited_once_with("steer")

    @pytest.mark.asyncio
    async def test_stop_and_remove(self, mgr):
        from tests.conftest import make_backend_mock
        with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
            session = await mgr.create_session(name="w1", scope="/s", cwd="/tmp", model="claude-sonnet-5[1m]")
            await mgr.remove(session.id)
        assert mgr.get(session.id) is None

    @pytest.mark.asyncio
    async def test_remove_deletes_from_dict_and_db(self, mgr):
        from app.db import get_session
        from tests.conftest import make_backend_mock
        with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
            session = await mgr.create_session(name="w1", scope="/s", cwd="/tmp", model="claude-sonnet-5[1m]")
            await mgr.remove(session.id)
        # v2.16: remove() — мягкое удаление (archive), а не DELETE. Сессия уходит
        # из runtime-словаря, а в БД помечается status='archived' (история жива).
        assert mgr.get(session.id) is None
        row = get_session(session.id)
        assert row is not None and row["status"] == "archived"

    @pytest.mark.asyncio
    async def test_loaded_remove_failure_keeps_session_unarchived(
        self, mgr, tmp_path, monkeypatch,
    ):
        from app.db import get_session, save_session
        from tests.conftest import make_backend_mock

        with patch(
            "app.session.AgentSession._make_backend",
            return_value=make_backend_mock(),
        ):
            session = await mgr.create_session(
                name="loaded-stuck",
                scope=str(tmp_path),
                cwd=str(tmp_path),
                model="claude-sonnet-5[1m]",
            )
        wt = tmp_path / "loaded-stuck-worktree"
        wt.mkdir()
        session.worktree_path = str(wt)
        save_session(session._to_db_dict())

        def fail_remove(*_args):
            raise RuntimeError("simulated git worktree remove failure")

        monkeypatch.setattr("app.manager.remove_worktree", fail_remove)

        with pytest.raises(RuntimeError, match="simulated git"):
            await mgr.remove(session.id)

        assert mgr.get(session.id) is session
        assert get_session(session.id)["status"] != "archived"

    @pytest.mark.asyncio
    async def test_detached_remove_deletes_worktree_before_archive(
        self, mgr, tmp_path, monkeypatch,
    ):
        from app.db import get_session, save_session

        wt = tmp_path / "detached-worktree"
        wt.mkdir()
        save_session({
            "id": "detached", "name": "detached", "scope": str(tmp_path),
            "cwd": str(wt), "model": "claude-sonnet-5[1m]",
            "system_prompt": "", "status": "idle", "session_id": None,
            "cost_usd": 0.0, "worktree_path": str(wt), "branch": "task-92/detached",
            "is_orchestrator": False, "color": "#818cf8",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "finished_at": None,
        })
        observed = []

        def fake_remove(_repo_path, worktree_path):
            observed.append(get_session("detached")["status"])
            Path(worktree_path).rmdir()

        monkeypatch.setattr("app.manager.remove_worktree", fake_remove)

        await mgr.remove("detached")

        assert observed == ["idle"]
        assert not wt.exists()
        assert get_session("detached")["status"] == "archived"

    @pytest.mark.asyncio
    async def test_detached_remove_failure_does_not_archive(
        self, mgr, tmp_path, monkeypatch,
    ):
        from app.db import get_session, save_session

        wt = tmp_path / "stuck-worktree"
        wt.mkdir()
        save_session({
            "id": "stuck", "name": "stuck", "scope": str(tmp_path),
            "cwd": str(wt), "model": "claude-sonnet-5[1m]",
            "system_prompt": "", "status": "idle", "session_id": None,
            "cost_usd": 0.0, "worktree_path": str(wt), "branch": "task-92/stuck",
            "is_orchestrator": False, "color": "#818cf8",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "finished_at": None,
        })

        def fail_remove(*_args):
            raise RuntimeError("simulated git worktree remove failure")

        monkeypatch.setattr("app.manager.remove_worktree", fail_remove)

        with pytest.raises(RuntimeError, match="simulated git"):
            await mgr.remove("stuck")

        assert wt.exists()
        assert get_session("stuck")["status"] == "idle"

    @pytest.mark.asyncio
    async def test_detached_missing_worktree_archives_idempotently(
        self, mgr, tmp_path,
    ):
        from app.db import get_session, save_session

        missing_wt = tmp_path / "already-gone"
        save_session({
            "id": "gone", "name": "gone", "scope": str(tmp_path),
            "cwd": str(missing_wt), "model": "claude-sonnet-5[1m]",
            "system_prompt": "", "status": "idle", "session_id": None,
            "cost_usd": 0.0, "worktree_path": str(missing_wt),
            "branch": "task-92/gone", "is_orchestrator": False,
            "color": "#818cf8",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "finished_at": None,
        })

        await mgr.remove("gone")

        assert get_session("gone")["status"] == "archived"


class TestListSessions:
    # ── Вес ответа = вероятность доставки (#65) ──
    # У юзера между нами и его машиной прозрачный посредник: ответы до ~15 КБ доходят
    # 10 из 10, крупные — 17 из 33, соединение виснет навсегда (замер perf). Список
    # опрашивается раз в 3 секунды, поэтому одно жирное поле, случайно попавшее в
    # to_dict(), превращает дашборд в рулетку. Так и было: system_prompt занимал 86.4%
    # веса ответа по проводу.
    # Порог проверяем ПОСЛЕ СЖАТИЯ: nginx отдаёт JSON с gzip_comp_level 6, и несжатый
    # размер врёт примерно вшестеро.
    RELIABLE_WIRE_BYTES = 15 * 1024   # выше этого доставка становится лотереей
    AGENTS_THAT_MUST_FIT = 10

    @staticmethod
    def _wire_bytes(payload) -> int:
        import gzip
        import json
        return len(gzip.compress(json.dumps(payload, ensure_ascii=False).encode(), 6))

    @staticmethod
    def _realistic_prompt(seed: int) -> str:
        """Промпт, который сжимается КАК ТЕКСТ, а не как повтор одной строки.

        Первая редакция теста брала `"ДЛИННЫЙ ПРОМПТ. " * 3000` и была зелёной даже с
        вернувшимся в ответ `system_prompt`: такая строка жмётся в 293 раза и веса не
        добавляет. Настоящие промпты жмутся в 5.1 раза (замер на живом ответе), эта
        болтанка из словаря — в 6.5, то есть тест меряет то же, что и провод.
        """
        import random
        rnd = random.Random(seed)
        vocab = [f"{w}{i}" for i, w in enumerate(
            ["агент", "задача", "ветка", "правило", "замер", "отчёт", "файл",
             "проверка", "сессия", "роль"] * 20)]
        return " ".join(rnd.choice(vocab) for _ in range(2000))

    @pytest.mark.asyncio
    async def test_heavy_fields_are_not_in_the_list(self, mgr):
        from tests.conftest import make_backend_mock
        with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
            session = await mgr.create_session(
                name="w1", scope="/s", cwd="/tmp", model="claude-sonnet-5[1m]",
                system_prompt=self._realistic_prompt(1),
            )
        session.last_summary = self._realistic_prompt(2)

        rows = mgr.list_sessions(scope="/s")
        assert rows, "список пуст — тест ничего не проверяет"
        for row in rows:
            assert "system_prompt" not in row, "промпт берётся роутом /api/sessions/{name}/prompt"
            assert "last_summary" not in row, "last_summary нужен только серверу"

    @pytest.mark.asyncio
    async def test_ten_agents_with_long_prompts_still_fit_in_a_deliverable_response(self, mgr):
        """Вес несут ПЕРСИСТЕНТНЫЕ строки, поэтому сессии убираются из памяти.

        У живой сессии `to_dict()` и так режет промпт до 500 символов (session.py),
        а строки из БД отдавались целиком — 18–44 КБ каждая. Тест, который держит
        сессии активными, проверяет единственный путь, где веса никогда и не было.
        """
        from tests.conftest import make_backend_mock
        with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
            for i in range(self.AGENTS_THAT_MUST_FIT):
                await mgr.create_session(
                    name=f"w{i}", scope="/s", cwd="/tmp", model="claude-sonnet-5[1m]",
                    system_prompt=self._realistic_prompt(i),
                )
        mgr.sessions.clear()          # теперь список соберётся из строк БД

        rows = mgr.list_sessions(scope="/s")
        assert len(rows) == self.AGENTS_THAT_MUST_FIT
        wire = self._wire_bytes(rows)
        assert wire < self.RELIABLE_WIRE_BYTES, (
            f"{wire} байт по проводу на {len(rows)} агентов против потолка "
            f"{self.RELIABLE_WIRE_BYTES}. В список приехало тяжёлое поле: ответ такого "
            "размера у юзера доходит примерно в половине попыток."
        )

    def test_runtime_for_persisted_row_is_explicit_or_unknown(self):
        from app.models import runtime_for_record

        assert runtime_for_record({
            "model": "claude-sonnet-4-6",
            "backend_type": "",
        }) == "claude"
        assert runtime_for_record({
            "model": "vendor/retired-model",
            "backend_type": "",
        }) == "unknown"
        assert runtime_for_record({
            "model": "gpt-misleading",
            "backend_type": "opencode",
        }) == "opencode"

    @pytest.mark.asyncio
    async def test_scope_filter(self, mgr):
        from tests.conftest import make_backend_mock
        with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
            await mgr.create_session(name="w1", scope="/a", cwd="/tmp", model="claude-sonnet-5[1m]")
            await mgr.create_session(name="w2", scope="/b", cwd="/tmp", model="claude-sonnet-5[1m]")
        result = mgr.list_sessions(scope="/a")
        assert len(result) == 1
        assert result[0]["name"] == "w1"

    @pytest.mark.asyncio
    async def test_merges_active_and_db(self, mgr):
        from tests.conftest import make_backend_mock
        with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
            session = await mgr.create_session(name="w1", scope="/s", cwd="/tmp", model="claude-sonnet-5[1m]")
        result = mgr.list_sessions()
        assert len(result) >= 1

    @pytest.mark.asyncio
    async def test_runtime_cache_policy_for_active_and_persisted_sessions(self, mgr):
        from tests.conftest import make_backend_mock
        with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
            claude = await mgr.create_session(
                name="claude-cache", scope="/s", cwd="/tmp",
                model="claude-sonnet-5[1m]",
            )
            codex = await mgr.create_session(
                name="codex-cache", scope="/s", cwd="/tmp",
                model="gpt-5.6-sol",
            )
        mgr.sessions.pop(codex.id)

        rows = {row["name"]: row for row in mgr.list_sessions(scope="/s")}
        assert rows[claude.name]["cache_ttl_seconds"] == 3600
        assert rows[claude.name]["cache_ttl_approximate"] is False
        assert rows[codex.name]["cache_ttl_seconds"] == 1800
        assert rows[codex.name]["cache_ttl_approximate"] is True


class TestRemoveScope:
    @pytest.mark.asyncio
    async def test_passes_orch_names_to_tg_bridge_when_flag_set(self, mgr, monkeypatch):
        """remove_scope с delete_tg_topics=True должен передать имена орков в tg_bridge."""
        from app.db import save_session
        save_session({
            "id": "orch-x", "name": "orch-x-orchestrator", "scope": "/scope-x",
            "cwd": "/tmp", "model": "claude-opus-5[1m]", "system_prompt": "",
            "status": "idle", "session_id": None,
            "cost_usd": 0.0, "worktree_path": None, "branch": None,
            "is_orchestrator": True, "color": "#818cf8",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "finished_at": None,
        })

        called = {}

        async def fake_remove(names):
            called["names"] = list(names)
            return {"deleted": list(names), "failed": [], "skipped": []}

        mgr.tg_topics_remover = fake_remove  # P3: wired callback, not tg_bridge import

        result = await mgr.remove_scope("/scope-x", delete_tg_topics=True)

        assert called["names"] == ["orch-x-orchestrator"]
        assert result["tg"]["deleted"] == ["orch-x-orchestrator"]

    @pytest.mark.asyncio
    async def test_skips_tg_bridge_when_flag_false(self, mgr, monkeypatch):
        from app.db import save_session
        save_session({
            "id": "orch-y", "name": "orch-y-orchestrator", "scope": "/scope-y",
            "cwd": "/tmp", "model": "claude-opus-5[1m]", "system_prompt": "",
            "status": "idle", "session_id": None,
            "cost_usd": 0.0, "worktree_path": None, "branch": None,
            "is_orchestrator": True, "color": "#818cf8",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "finished_at": None,
        })

        called = {"hit": False}

        async def fake_remove(names):
            called["hit"] = True
            return {}

        mgr.tg_topics_remover = fake_remove  # P3: wired callback, not tg_bridge import

        result = await mgr.remove_scope("/scope-y", delete_tg_topics=False)

        assert called["hit"] is False
        assert result["tg"] == {}

    @pytest.mark.asyncio
    async def test_removes_detached_worktree_before_scope_archive(
        self, mgr, tmp_path, monkeypatch,
    ):
        from app.db import get_session, save_session

        wt = tmp_path / "scope-detached"
        wt.mkdir()
        save_session({
            "id": "scope-detached", "name": "scope-detached",
            "scope": "/scope-detached", "cwd": str(wt),
            "model": "claude-sonnet-5[1m]", "system_prompt": "",
            "status": "idle", "session_id": None, "cost_usd": 0.0,
            "worktree_path": str(wt), "branch": "task-92/scope-detached",
            "is_orchestrator": False, "color": "#818cf8",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "finished_at": None,
        })
        removed = []

        def fake_remove(_repo_path, worktree_path):
            removed.append(worktree_path)
            Path(worktree_path).rmdir()

        monkeypatch.setattr("app.manager.remove_worktree", fake_remove)

        await mgr.remove_scope("/scope-detached")

        assert removed == [str(wt)]
        assert not wt.exists()
        assert get_session("scope-detached")["status"] == "archived"


class TestAutoResume:
    @pytest.mark.asyncio
    async def test_resumes_orchestrators(self, mgr):
        from app.db import save_session
        save_session({
            "id": "orch-1", "name": "orchestrator", "scope": "/tmp",
            "cwd": "/tmp", "model": "claude-opus-5[1m]", "system_prompt": "",
            "status": "idle", "session_id": "sdk-123",
            "cost_usd": 0.0, "worktree_path": None, "branch": None,
            "is_orchestrator": True, "role": "orchestrator", "pipeline": "default",
            "color": "#818cf8", "created_at": datetime.now(timezone.utc).isoformat(),
            "finished_at": None,
        })
        from tests.conftest import make_backend_mock
        with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
            await mgr.auto_resume_all()
        assert mgr.get("orch-1") is not None

    @pytest.mark.asyncio
    async def test_resume_normalizes_empty_pipeline(self, mgr):
        """Old migrated rows store pipeline='' → _load_from_db must normalize to
        DEFAULT_PIPELINE. Without it ROLE_SYSTEM_PROMPT('') fails loud (fallback
        removed) and pre-pipeline sessions can't resume."""
        from app.db import save_session, get_session_by_name
        from tests.conftest import make_backend_mock
        save_session({
            "id": "old-empty-pipe", "name": "oldw", "scope": "/tmp", "cwd": "/tmp",
            "model": "claude-sonnet-5[1m]", "system_prompt": "", "status": "idle",
            "session_id": None, "cost_usd": 0.0, "worktree_path": None, "branch": None,
            "is_orchestrator": False, "role": "worker", "pipeline": "",
            "color": "#fff", "created_at": datetime.now(timezone.utc).isoformat(),
            "finished_at": None,
        })
        row = get_session_by_name("oldw", "/tmp")
        with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
            session = await mgr._load_from_db(row)  # must NOT raise ValueError
        assert session.name == "oldw"
        assert session.system_prompt  # prompt built from default pipeline



class TestCanSpawn:
    def _write_role(self, roles_dir, name, frontmatter_body):
        (roles_dir / f"{name}.md").write_text(f"---\n{frontmatter_body}\n---\n\nBody for {name}.\n")

    @pytest.fixture
    def roles_dir(self, tmp_path, monkeypatch):
        # can_spawn is read from temp frontmatter (_PROMPTS_DIR). The prompt build
        # (ROLE_SYSTEM_PROMPT) reads real pipelines/ — the app/prompts fallback is
        # removed, so an empty PIPELINES_DIR would fail loud. These tests assert
        # spawn-whitelist behaviour and spawn role="worker" (present in default),
        # so point at the real default pipeline for the prompt step.
        from pathlib import Path
        prompts = tmp_path / "prompts"
        rdir = prompts / "roles"
        rdir.mkdir(parents=True)
        (prompts / "base.md").write_text("BASE")
        monkeypatch.setattr("app.prompting._PROMPTS_DIR", prompts)
        monkeypatch.setattr("app.prompting._SKILLS_DIR", prompts / "skills")
        import app.pipeline as pl
        monkeypatch.setattr(pl, "PIPELINES_DIR", Path(__file__).parent.parent / "pipelines")
        pl.load_pipeline.cache_clear()
        return rdir

    # REMOVED (#34): six unit tests of role_can_spawn (absent / YAML-null / non-list /
    # [] / whitelist / missing file). The function itself is gone — it had no callers in
    # app/ since 1bff39a, and `can_spawn` was never present in any role frontmatter, before
    # or after the pipelines/ migration. Spawn rights are decided solely by the manifest
    # (validate_spawn), covered by tests/test_pipeline.py + tests/test_default_pipeline.py.

    @pytest.mark.asyncio
    async def test_whitelist_allows_listed(self, mgr, roles_dir):
        from app.db import save_session
        from tests.conftest import make_backend_mock
        self._write_role(roles_dir, "boss", "name: boss\ncan_spawn: [worker]")
        self._write_role(roles_dir, "worker", "name: worker")
        save_session({
            "id": "p-1", "name": "parent", "scope": "/s", "cwd": "/tmp",
            "model": "claude-sonnet-5[1m]", "system_prompt": "", "status": "idle", "session_id": None,
            "cost_usd": 0.0, "worktree_path": None, "branch": None,
            "is_orchestrator": False, "color": "#fff",
            "created_at": datetime.now(timezone.utc).isoformat(), "finished_at": None,
            "role": "boss",
        })
        with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
            session = await mgr.create_session(
                name="child", scope="/s", cwd="/tmp", model="claude-sonnet-5[1m]",
                role="worker", parent_name="parent",
            )
        assert session.name == "child"

    # REMOVED: test_whitelist_blocks_unlisted + test_empty_can_spawn_blocks_all.
    # They tested the legacy frontmatter can_spawn fallback (role_can_spawn reading
    # app/prompts/roles/*.md) triggered when validate_spawn hits FileNotFoundError.
    # app/prompts is removed and the manifest is the single source — spawn-whitelist
    # enforcement is now covered by validate_spawn / TestRolesCatalogFromManifest.
    # These tested removed legacy behaviour, so they're deleted (not "broken").

    @pytest.mark.asyncio
    async def test_unknown_parent_fails_open(self, mgr, roles_dir):
        from tests.conftest import make_backend_mock
        self._write_role(roles_dir, "worker", "name: worker")
        with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
            session = await mgr.create_session(
                name="child", scope="/s", cwd="/tmp", model="claude-sonnet-5[1m]",
                role="worker", parent_name="ghost-parent",
            )
        assert session.name == "child"


class TestCustomMcp:
    def test_parse_none_is_empty(self):
        from app.manager import _parse_custom_mcp
        assert _parse_custom_mcp(None) == {}
        assert _parse_custom_mcp("") == {}

    def test_parse_dict_passthrough(self):
        from app.manager import _parse_custom_mcp
        d = {"playwright": {"command": "npx", "args": ["-y", "@playwright/mcp"]}}
        assert _parse_custom_mcp(d) == d

    def test_parse_json_string(self):
        from app.manager import _parse_custom_mcp
        raw = '{"playwright": {"command": "npx"}}'
        assert _parse_custom_mcp(raw) == {"playwright": {"command": "npx"}}

    def test_parse_invalid_json_is_empty(self):
        from app.manager import _parse_custom_mcp
        assert _parse_custom_mcp("{not json") == {}

    def test_parse_non_dict_is_empty(self):
        from app.manager import _parse_custom_mcp
        assert _parse_custom_mcp("[1, 2, 3]") == {}
        assert _parse_custom_mcp(42) == {}

    def test_parse_strips_orchestra_key(self):
        from app.manager import _parse_custom_mcp
        raw = {"orchestra": {"command": "evil"}, "playwright": {"command": "npx"}}
        assert _parse_custom_mcp(raw) == {"playwright": {"command": "npx"}}

    def test_make_mcp_config_merges_extra(self):
        from app.manager import _make_mcp_config
        cfg = _make_mcp_config("w", "/s", "worker", extra={"playwright": {"command": "npx"}})
        assert "orchestra" in cfg
        assert cfg["playwright"] == {"command": "npx"}

    def test_make_mcp_config_extra_cannot_override_orchestra(self):
        from app.manager import _make_mcp_config
        cfg = _make_mcp_config("w", "/s", "worker", extra={"orchestra": {"command": "evil"}})
        assert cfg["orchestra"]["command"] != "evil"

    @pytest.mark.asyncio
    async def test_create_session_wires_custom_mcp(self, mgr):
        from tests.conftest import make_backend_mock
        custom = {"playwright": {"command": "npx", "args": ["-y", "@playwright/mcp"]}}
        with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
            session = await mgr.create_session(
                name="w24a", scope="/s", cwd="/tmp", model="claude-sonnet-5[1m]",
                role="worker", mcp_servers=custom,
            )
        assert session.mcp_servers_custom == custom
        assert "playwright" in session.mcp_servers
        assert "orchestra" in session.mcp_servers

    @pytest.mark.asyncio
    async def test_create_session_persists_custom_mcp(self, mgr):
        import json
        from app.db import get_session_by_name
        from tests.conftest import make_backend_mock
        custom = {"playwright": {"command": "npx"}}
        with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
            await mgr.create_session(
                name="w24b", scope="/s", cwd="/tmp", model="claude-sonnet-5[1m]",
                role="worker", mcp_servers=custom,
            )
        row = get_session_by_name("w24b", "/s")
        assert json.loads(row["mcp_servers_custom"]) == custom

    @pytest.mark.asyncio
    async def test_load_from_db_remerges_custom_mcp(self, mgr):
        import json
        from app.db import save_session, get_session_by_name
        from tests.conftest import make_backend_mock
        custom = {"playwright": {"command": "npx"}}
        save_session({
            "id": "r-24", "name": "w24c", "scope": "/s", "cwd": "/tmp",
            "model": "claude-sonnet-5[1m]", "system_prompt": "", "status": "idle", "session_id": None,
            "cost_usd": 0.0, "worktree_path": None, "branch": None,
            "is_orchestrator": False, "color": "#fff",
            "created_at": datetime.now(timezone.utc).isoformat(), "finished_at": None,
            "role": "worker", "pipeline": "default", "mcp_servers_custom": json.dumps(custom),
        })
        row = get_session_by_name("w24c", "/s")
        with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
            session = await mgr._load_from_db(row)
        assert session.mcp_servers_custom == custom
        assert "playwright" in session.mcp_servers
        assert "orchestra" in session.mcp_servers


# ── Stage 3: loader integration (pipeline manifest) ─────────────────────────

# Мини-манифест, повторяющий ключевые роли tasks-pm для тестов фильтра/изоляции.
_MINI_MANIFEST = """\
name: testpipe
description: Test pipeline
validation: fail-closed
defaults:
  model: opus
  skills: all
  mcp_servers: all
  prompt_layers:
    orchestrator: [base.md, "roles/{role}.md", _pipeline.md]
    worker: [base.md, "roles/{role}.md"]
roles:
  pm-glava: {kind: orchestrator, label: ПМ Глава, order: 1, can_spawn: [pm-fichi, secretary]}
  pm-fichi: {kind: orchestrator, label: Фича ПМ, order: 2, can_spawn: [coder, secretary]}
  coder: {kind: orchestrator, label: Кодер, order: 4, can_spawn: [secretary], allow_unrouted_workers: true}
  secretary: {kind: worker, label: Секретарь, can_spawn: []}
  worker: {kind: worker, label: Воркер, can_spawn: []}
"""


def _write_pipeline(root, name, manifest_text, prompts=None):
    """Создать pipelines/<name>/ с pipeline.yaml + prompts/* в tmp-корне root."""
    pdir = root / name
    (pdir / "prompts" / "roles").mkdir(parents=True)
    (pdir / "pipeline.yaml").write_text(manifest_text)
    prompts = prompts or {}
    for rel, content in prompts.items():
        target = pdir / "prompts" / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    return pdir


@pytest.fixture
def pipeline_dir(tmp_path, monkeypatch):
    """tmp pipelines/ с манифестом testpipe + базовыми слоями промптов.

    Монкипатчит ``app.pipeline.PIPELINES_DIR`` и чистит lru_cache загрузчика,
    чтобы манифест читался из tmp, а не из реального дерева (которого нет).
    """
    import app.pipeline as pl
    root = tmp_path / "pipelines"
    root.mkdir()
    _write_pipeline(root, "testpipe", _MINI_MANIFEST, prompts={
        "base.md": "BASE-LAYER",
        "roles/pm-glava.md": "ROLE pm-glava",
        "roles/pm-fichi.md": "ROLE pm-fichi",
        "roles/coder.md": "ROLE coder",
        "roles/secretary.md": "ROLE secretary",
        "roles/worker.md": "ROLE worker",
        "_pipeline.md": "PIPELINE-LAYER",
    })
    monkeypatch.setattr(pl, "PIPELINES_DIR", root)
    pl.load_pipeline.cache_clear()
    yield root
    pl.load_pipeline.cache_clear()


class TestRoleSystemPromptFailLoud:
    """app/prompts legacy-fallback удалён → нет манифеста ИЛИ роли → ValueError (fail loud).

    Раньше здесь был TestUpstreamFallbackCharacterization (3 теста) — он проверял
    _UPSTREAM_ROLE_SYSTEM_PROMPT, который РЕАЛЬНО собирал промпт из app/prompts при
    отсутствии манифеста. Тот код удалён (единый источник = pipelines/), поэтому
    тесты его поведения удалены, а не «сломались». Новое поведение — fail loud."""

    def test_no_manifest_raises(self, db):
        import app.pipeline as pl
        pl.load_pipeline.cache_clear()
        from app.manager import ROLE_SYSTEM_PROMPT
        with pytest.raises(ValueError, match="not resolvable"):
            ROLE_SYSTEM_PROMPT("ghost-pipe-no-manifest", "orchestrator", "/s")


class TestRoleSystemPromptManifest:
    def test_static_layers_from_manifest(self, pipeline_dir, db):
        """ROLE_SYSTEM_PROMPT берёт статику из pipelines/<name>/prompts/ (изоляция)."""
        from app.manager import ROLE_SYSTEM_PROMPT
        out = ROLE_SYSTEM_PROMPT("testpipe", "coder", "/s")
        assert "BASE-LAYER" in out
        assert "ROLE coder" in out
        assert "PIPELINE-LAYER" in out  # coder — orchestrator → _pipeline.md есть

    def test_worker_role_no_pipeline_layer(self, pipeline_dir, db):
        """Воркер (kind:worker) НЕ получает _pipeline.md."""
        from app.manager import ROLE_SYSTEM_PROMPT
        out = ROLE_SYSTEM_PROMPT("testpipe", "secretary")
        assert "BASE-LAYER" in out
        assert "ROLE secretary" in out
        assert "PIPELINE-LAYER" not in out

    def test_orchestrator_gets_filtered_catalog(self, pipeline_dir, db):
        """Оркестратор pm-glava видит каталог только pm-fichi+secretary (can_spawn)."""
        from app.manager import ROLE_SYSTEM_PROMPT
        out = ROLE_SYSTEM_PROMPT("testpipe", "pm-glava", "/s")
        assert "pm-fichi" in out
        assert "secretary" in out
        # coder и worker НЕ в can_spawn pm-glava → нет их записей в каталоге
        # (проверяем заголовок записи ### `name`, т.к. слово worker есть в шапке каталога)
        assert "### `coder`" not in out
        assert "### `worker`" not in out

    def test_unknown_role_raises(self, pipeline_dir, db):
        """Роли нет в манифесте (KeyError) → fail loud (ValueError), НЕ молчаливый
        fallback. Раньше делегировал в _UPSTREAM_ROLE_SYSTEM_PROMPT (app/prompts,
        удалён). Теперь роль обязана быть в pipeline.yaml или это ошибка."""
        from app.manager import ROLE_SYSTEM_PROMPT
        with pytest.raises(ValueError, match="not resolvable"):
            ROLE_SYSTEM_PROMPT("testpipe", "my-custom-worker")


class TestRolesCatalogFromManifest:
    def test_pm_glava_shows_only_pm_fichi_and_secretary(self, pipeline_dir):
        from app.manager import _roles_catalog_from_manifest
        cat = _roles_catalog_from_manifest("testpipe", "pm-glava")
        assert "### `pm-fichi`" in cat
        assert "### `secretary`" in cat
        assert "### `coder`" not in cat
        assert "### `worker`" not in cat

    def test_sorted_by_order(self, pipeline_dir):
        """pm-fichi (order 2) перед secretary (order 100, дефолт)."""
        from app.manager import _roles_catalog_from_manifest
        cat = _roles_catalog_from_manifest("testpipe", "pm-glava")
        assert cat.index("pm-fichi") < cat.index("secretary")

    def test_star_can_spawn_shows_all(self, tmp_path, monkeypatch):
        """can_spawn=['*'] → каталог показывает ВСЕ роли пайплайна."""
        import app.pipeline as pl
        root = tmp_path / "pipelines"
        root.mkdir()
        manifest = (
            "name: starpipe\nvalidation: fail-open\n"
            "roles:\n"
            "  boss: {kind: orchestrator, label: Boss, order: 0, can_spawn: ['*']}\n"
            "  a: {kind: worker, label: A, order: 1, can_spawn: []}\n"
            "  b: {kind: worker, label: B, order: 2, can_spawn: []}\n"
        )
        _write_pipeline(root, "starpipe", manifest, prompts={"base.md": "B"})
        monkeypatch.setattr(pl, "PIPELINES_DIR", root)
        pl.load_pipeline.cache_clear()
        from app.manager import _roles_catalog_from_manifest
        cat = _roles_catalog_from_manifest("starpipe", "boss")
        pl.load_pipeline.cache_clear()
        assert "### `a`" in cat
        assert "### `b`" in cat
        # S1: wildcard НЕ включает саму роль-родителя.
        assert "### `boss`" not in cat


class TestPromptIsolation:
    def test_app_prompts_not_read_in_manifest_path(self, pipeline_dir, db, monkeypatch):
        """Манифест-путь НЕ читает app/prompts/ — отсутствие _PROMPTS_DIR не ломает."""
        # Указываем _PROMPTS_DIR на несуществующий путь — manifest-путь должен работать.
        monkeypatch.setattr("app.prompting._PROMPTS_DIR", Path("/nonexistent/app/prompts"))
        from app.manager import ROLE_SYSTEM_PROMPT
        out = ROLE_SYSTEM_PROMPT("testpipe", "coder", "/s")
        assert "BASE-LAYER" in out  # из pipelines/testpipe/prompts/, не из app/prompts/
        assert "ROLE coder" in out


class TestPromptBlocksFailLoud:
    """#108 T2: сбой сборки блока промпта не смеет притворяться пустым списком.

    Раньше оба блока были обёрнуты в `except Exception: return ""`. Агент получал
    промпт БЕЗ списка воркеров/оркестраторов и читал это как «их нет» — то есть
    плодил дубликаты вместо переиспользования. При этом объемлющая
    ROLE_SYSTEM_PROMPT в своём докстринге объявляет «Fail loud».
    """

    def _boom(self, *_a, **_kw):
        raise KeyError("name")

    def test_workers_block_logs_and_marks_on_failure(self, db, monkeypatch, caplog):
        import logging
        from app import manager
        monkeypatch.setattr(manager, "get_all_sessions", self._boom)
        with caplog.at_level(logging.ERROR, logger="app.manager"):
            out = manager._workers_block("/s")
        assert out != ""                        # НЕ пустая строка — иначе агент решит «воркеров нет»
        assert "⚠️" in out and "unavailable" in out
        assert "list_agents" in out             # обходной путь агенту дан
        assert "KeyError" in caplog.text        # класс исключения в логе

    def test_other_orchestrators_block_logs_and_marks_on_failure(self, db, monkeypatch, caplog):
        import logging
        from app import manager
        monkeypatch.setattr(manager, "get_all_sessions", self._boom)
        with caplog.at_level(logging.ERROR, logger="app.manager"):
            out = manager._other_orchestrators_block("/s")
        assert out != ""
        assert "⚠️" in out and "unavailable" in out
        assert "list_orchestrators" in out
        assert "KeyError" in caplog.text

    def test_healthy_path_unchanged(self, db):
        """На здоровой БД поведение прежнее: воркеров нет → пустой блок, не маркер."""
        from app import manager
        assert manager._workers_block("/s") == ""
        assert manager._other_orchestrators_block("/s") == ""

    def test_unexpected_exception_propagates(self, db, monkeypatch):
        """except сужен: неожиданное исключение летит наверх, а не глотается."""
        from app import manager

        def _weird(*_a, **_kw):
            raise RuntimeError("something genuinely unexpected")

        monkeypatch.setattr(manager, "get_all_sessions", _weird)
        with pytest.raises(RuntimeError):
            manager._workers_block("/s")


class TestValidateSpawnIntegration:
    @pytest.mark.asyncio
    async def test_forbidden_spawn_blocked_before_side_effect(self, mgr, pipeline_dir, tmp_path):
        """pm-glava НЕ может спавнить coder (нет в can_spawn) — ValueError ДО worktree."""
        from app.db import save_session
        from tests.conftest import make_backend_mock
        import subprocess
        repo = tmp_path / "repo2"
        repo.mkdir()
        subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)
        subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=repo, capture_output=True)
        subprocess.run(["git", "config", "user.name", "T"], cwd=repo, capture_output=True)
        (repo / "f.txt").write_text("x")
        subprocess.run(["git", "add", "."], cwd=repo, capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", "i"], cwd=repo, capture_output=True, check=True)
        subprocess.run(["git", "branch", "-M", "main"], cwd=repo, capture_output=True, check=True)

        save_session({
            "id": "pg-1", "name": "glava", "scope": "/s", "cwd": "/tmp",
            "model": "opus", "system_prompt": "", "status": "idle", "session_id": None,
            "cost_usd": 0.0, "worktree_path": None, "branch": None,
            "is_orchestrator": True, "color": "",
            "created_at": datetime.now(timezone.utc).isoformat(), "finished_at": None,
            "role": "pm-glava", "pipeline": "testpipe",
        })
        wt_calls = {"n": 0}
        real_cw = __import__("app.workspace", fromlist=["create_worktree"]).create_worktree

        def counting_cw(*a, **k):
            wt_calls["n"] += 1
            return real_cw(*a, **k)

        with patch("app.manager.create_worktree", side_effect=counting_cw):
            with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
                with pytest.raises(ValueError, match="cannot spawn"):
                    await mgr.create_session(
                        name="child-coder", scope="/s", cwd=str(repo), model="opus",
                        role="coder", parent_name="glava",
                        use_worktree=True, repo_path=str(repo), pipeline="testpipe",
                    )
        assert wt_calls["n"] == 0, "worktree не должен создаваться при запрещённом спавне"

    @pytest.mark.asyncio
    async def test_allowed_spawn_passes(self, mgr, pipeline_dir):
        """pm-glava МОЖЕТ спавнить secretary (в can_spawn)."""
        from app.db import save_session
        from tests.conftest import make_backend_mock
        save_session({
            "id": "pg-2", "name": "glava", "scope": "/s", "cwd": "/tmp",
            "model": "opus", "system_prompt": "", "status": "idle", "session_id": None,
            "cost_usd": 0.0, "worktree_path": None, "branch": None,
            "is_orchestrator": True, "color": "",
            "created_at": datetime.now(timezone.utc).isoformat(), "finished_at": None,
            "role": "pm-glava", "pipeline": "testpipe",
        })
        with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
            session = await mgr.create_session(
                name="sec-1", scope="/s", cwd="/tmp", model="opus",
                role="secretary", parent_name="glava", pipeline="testpipe",
            )
        assert session.name == "sec-1"

    # REMOVED: test_fallback_when_no_manifest — tested the legacy _role_can_spawn
    # frontmatter fallback (app/prompts) that fired on FileNotFoundError. That
    # fallback is removed (single source = pipelines, fail loud on missing manifest).

    def _mk_prompts(self, monkeypatch):
        import tempfile
        d = tempfile.mkdtemp()
        prompts = Path(d) / "prompts"
        (prompts / "roles").mkdir(parents=True)
        (prompts / "base.md").write_text("BASE")
        monkeypatch.setattr("app.prompting._PROMPTS_DIR", prompts)
        monkeypatch.setattr("app.prompting._SKILLS_DIR", prompts / "skills")
        return str(prompts)


class TestIsOrchestratorDenormalization:
    @pytest.mark.asyncio
    async def test_is_orch_from_manifest_kind(self, mgr, pipeline_dir):
        """coder (kind:orchestrator в манифесте) → session.is_orchestrator=True,
        хотя в frozenset апстрима его нет."""
        from tests.conftest import make_backend_mock
        with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
            session = await mgr.create_session(
                name="coder-1", scope="/s", cwd="/tmp", model="opus",
                role="coder", is_orchestrator=True, pipeline="testpipe",
            )
        assert session.is_orchestrator is True
        assert session.pipeline == "testpipe"

    @pytest.mark.asyncio
    async def test_worker_kind_is_not_orchestrator(self, mgr, pipeline_dir):
        """secretary (kind:worker) → is_orchestrator=False даже при is_orchestrator=True arg."""
        from app.db import save_session
        from tests.conftest import make_backend_mock
        save_session({
            "id": "pg-3", "name": "glava", "scope": "/s", "cwd": "/tmp",
            "model": "opus", "system_prompt": "", "status": "idle", "session_id": None,
            "cost_usd": 0.0, "worktree_path": None, "branch": None,
            "is_orchestrator": True, "color": "",
            "created_at": datetime.now(timezone.utc).isoformat(), "finished_at": None,
            "role": "pm-glava", "pipeline": "testpipe",
        })
        with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
            session = await mgr.create_session(
                name="sec-2", scope="/s", cwd="/tmp", model="opus",
                role="secretary", parent_name="glava", pipeline="testpipe",
            )
        assert session.is_orchestrator is False

    @pytest.mark.asyncio
    async def test_fallback_is_orch_when_no_manifest(self, mgr):
        """Нет манифеста → is_orch из is_orchestrator_role(role) (frozenset)."""
        from tests.conftest import make_backend_mock
        with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
            session = await mgr.create_session(
                name="orch-fb", scope="/s", cwd="/tmp", model="claude-sonnet-5[1m]",
                role="orchestrator", is_orchestrator=True,
            )
        assert session.is_orchestrator is True


class TestPipelineInheritance:
    @pytest.mark.asyncio
    async def test_child_inherits_parent_pipeline(self, mgr, pipeline_dir):
        """Воркер без явного pipeline наследует пайплайн родителя."""
        from app.db import save_session
        from tests.conftest import make_backend_mock
        save_session({
            "id": "pg-4", "name": "coderboss", "scope": "/s", "cwd": "/tmp",
            "model": "opus", "system_prompt": "", "status": "idle", "session_id": None,
            "cost_usd": 0.0, "worktree_path": None, "branch": None,
            "is_orchestrator": True, "color": "",
            "created_at": datetime.now(timezone.utc).isoformat(), "finished_at": None,
            "role": "coder", "pipeline": "testpipe",
        })
        with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
            # coder.allow_unrouted_workers=true → generic worker (без role) допустим;
            # пайплайн наследуется от родителя coderboss (testpipe).
            session = await mgr.create_session(
                name="w-inh", scope="/s", cwd="/tmp", model="opus",
                parent_name="coderboss",
            )
        assert session.pipeline == "testpipe"

    @pytest.mark.asyncio
    async def test_root_defaults_to_default_pipeline(self, mgr, monkeypatch):
        """Корневой оркестратор без parent и без pipeline → DEFAULT_PIPELINE."""
        from tests.conftest import make_backend_mock
        from app.pipeline import DEFAULT_PIPELINE
        with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
            session = await mgr.create_session(
                name="root-orch", scope="/s", cwd="/tmp", model="claude-sonnet-5[1m]",
                role="orchestrator", is_orchestrator=True,
            )
        assert session.pipeline == DEFAULT_PIPELINE

    @pytest.mark.asyncio
    async def test_auto_found_parent_pipeline_inherited(self, mgr, pipeline_dir):
        """Воркер без явного parent_name авто-находит оркестратора в scope и
        наследует ЕГО пайплайн (не DEFAULT)."""
        from tests.conftest import make_backend_mock
        with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
            # активный оркестратор coder в scope с pipeline=testpipe
            await mgr.create_session(
                name="coderboss2", scope="/s", cwd="/tmp", model="opus",
                role="coder", is_orchestrator=True, pipeline="testpipe",
            )
            # generic worker без parent_name → авто-находит coderboss2 → testpipe
            worker = await mgr.create_session(
                name="auto-w", scope="/s", cwd="/tmp", model="opus",
            )
        assert worker.pipeline == "testpipe"
        assert worker.parent_name == "coderboss2"


class TestProfileInheritance:
    """Профиль Claude протягивается через create_session и наследуется детьми.

    Зеркало TestPipelineInheritance, но дефолт профиля — пусто (env процесса),
    а не константа.
    """

    @pytest.mark.asyncio
    async def test_root_with_profile_persists(self, mgr):
        """Корневой оркестратор с явным profile → session.profile и персист в БД."""
        from app.db import get_session_by_name
        from tests.conftest import make_backend_mock
        with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
            session = await mgr.create_session(
                name="root-orch", scope="/s", cwd="/tmp", model="claude-sonnet-5[1m]",
                role="orchestrator", is_orchestrator=True, profile="work",
            )
        assert session.profile == "work"
        row = get_session_by_name("root-orch", "/s")
        assert row is not None
        assert row["profile"] == "work"

    @pytest.mark.asyncio
    async def test_child_inherits_parent_profile(self, mgr):
        """Ребёнок без явного profile наследует профиль родителя."""
        from app.db import save_session
        from tests.conftest import make_backend_mock
        save_session({
            "id": "pp-1", "name": "boss", "scope": "/s", "cwd": "/tmp",
            "model": "opus", "system_prompt": "", "status": "idle", "session_id": None,
            "cost_usd": 0.0, "worktree_path": None, "branch": None,
            "is_orchestrator": True, "color": "",
            "created_at": datetime.now(timezone.utc).isoformat(), "finished_at": None,
            "role": "orchestrator", "pipeline": "", "profile": "work",
        })
        with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
            session = await mgr.create_session(
                name="child", scope="/s", cwd="/tmp", model="opus",
                parent_name="boss",
            )
        assert session.profile == "work"

    @pytest.mark.asyncio
    async def test_explicit_profile_overrides_inheritance(self, mgr):
        """Явный profile у ребёнка переопределяет наследование от родителя."""
        from app.db import save_session
        from tests.conftest import make_backend_mock
        save_session({
            "id": "pp-2", "name": "boss2", "scope": "/s", "cwd": "/tmp",
            "model": "opus", "system_prompt": "", "status": "idle", "session_id": None,
            "cost_usd": 0.0, "worktree_path": None, "branch": None,
            "is_orchestrator": True, "color": "",
            "created_at": datetime.now(timezone.utc).isoformat(), "finished_at": None,
            "role": "orchestrator", "pipeline": "", "profile": "work",
        })
        with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
            session = await mgr.create_session(
                name="child2", scope="/s", cwd="/tmp", model="opus",
                parent_name="boss2", profile="personal",
            )
        assert session.profile == "personal"

    @pytest.mark.asyncio
    async def test_no_profile_anywhere_is_empty(self, mgr):
        """Профиля нет ни явно, ни у родителя → session.profile == '' (env процесса)."""
        from tests.conftest import make_backend_mock
        with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
            session = await mgr.create_session(
                name="w-noprof", scope="/s", cwd="/tmp", model="claude-sonnet-5[1m]",
                role="orchestrator", is_orchestrator=True,
            )
        assert session.profile == ""

    @pytest.mark.asyncio
    async def test_auto_found_parent_profile_inherited(self, mgr):
        """Воркер без явного parent_name авто-находит оркестратора в scope и
        наследует ЕГО профиль."""
        from tests.conftest import make_backend_mock
        with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
            await mgr.create_session(
                name="orch-prof", scope="/s", cwd="/tmp", model="opus",
                role="orchestrator", is_orchestrator=True, profile="work",
            )
            worker = await mgr.create_session(
                name="auto-w-prof", scope="/s", cwd="/tmp", model="opus",
            )
        assert worker.profile == "work"
        assert worker.parent_name == "orch-prof"
class TestSystemPromptAppend:
    @pytest.mark.asyncio
    async def test_worker_custom_prompt_appended(self, mgr):
        from tests.conftest import make_backend_mock
        with patch("app.manager.ROLE_SYSTEM_PROMPT", return_value="ROLE_BASE"):
            with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
                session = await mgr.create_session(
                    name="w-sp1", scope="/s", cwd="/tmp", model="claude-sonnet-5[1m]",
                    role="worker", system_prompt="CUSTOM",
                )
        assert "ROLE_BASE" in session.system_prompt
        assert "CUSTOM" in session.system_prompt
        assert session.system_prompt.index("ROLE_BASE") < session.system_prompt.index("CUSTOM")

    @pytest.mark.asyncio
    async def test_orchestrator_custom_prompt_appended(self, mgr):
        from tests.conftest import make_backend_mock
        with patch("app.manager.ROLE_SYSTEM_PROMPT", return_value="ROLE_BASE"):
            with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
                session = await mgr.create_session(
                    name="w-sp2", scope="/s", cwd="/tmp", model="claude-sonnet-5[1m]",
                    role="orchestrator", system_prompt="CUSTOM",
                )
        assert "ROLE_BASE" in session.system_prompt
        assert "CUSTOM" in session.system_prompt
        assert session.system_prompt.index("ROLE_BASE") < session.system_prompt.index("CUSTOM")

    @pytest.mark.asyncio
    async def test_orchestrator_no_custom_prompt_uses_role_base(self, mgr):
        from tests.conftest import make_backend_mock
        with patch("app.manager.ROLE_SYSTEM_PROMPT", return_value="ROLE_BASE"):
            with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
                session = await mgr.create_session(
                    name="w-sp3", scope="/s", cwd="/tmp", model="claude-sonnet-5[1m]",
                    role="orchestrator",
                )
        assert session.system_prompt == "ROLE_BASE"


class TestChangeOrchestratorScope:
    async def _make_orch(self, mgr, name="orch", scope="/old/proj"):
        from tests.conftest import make_backend_mock
        with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
            s = await mgr.create_session(
                name=name, scope=scope, cwd="/tmp", model="claude-opus-5",
                is_orchestrator=True,
            )
        s.session_id = "sdk-resume-token"
        from app.session import AgentStatus
        s.status = AgentStatus.IDLE
        return s

    async def _make_worker(self, mgr, name="w1", scope="/old/proj"):
        from tests.conftest import make_backend_mock
        with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
            s = await mgr.create_session(name=name, scope=scope, cwd="/tmp", model="claude-sonnet-5[1m]")
        from app.session import AgentStatus
        s.status = AgentStatus.IDLE
        return s

    @pytest.mark.asyncio
    async def test_happy_path_updates_runtime_and_db(self, mgr, tmp_path):
        from app.db import get_session
        orch = await self._make_orch(mgr)
        newdir = tmp_path / "newproj"
        newdir.mkdir()
        res = await mgr.change_orchestrator_scope("orch", "/old/proj", str(newdir), str(newdir))
        assert res["ok"] is True
        assert orch.scope == str(newdir)
        assert orch.cwd == str(newdir)
        # mcp env rebuilt with new scope
        assert orch.mcp_servers["orchestra"]["env"]["ORCHESTRA_SCOPE"] == str(newdir)
        # db reflects change
        assert get_session(orch.id)["scope"] == str(newdir)
        # context preserved
        assert orch.session_id == "sdk-resume-token"

    @pytest.mark.asyncio
    async def test_disconnects_backend(self, mgr, tmp_path):
        orch = await self._make_orch(mgr)
        newdir = tmp_path / "newproj"; newdir.mkdir()
        orch._disconnect_backend = AsyncMock()
        await mgr.change_orchestrator_scope("orch", "/old/proj", str(newdir), str(newdir))
        orch._disconnect_backend.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_rejects_when_running(self, mgr, tmp_path):
        from app.session import AgentStatus
        orch = await self._make_orch(mgr)
        orch.status = AgentStatus.RUNNING
        newdir = tmp_path / "newproj"; newdir.mkdir()
        res = await mgr.change_orchestrator_scope("orch", "/old/proj", str(newdir), str(newdir))
        assert res.get("ok") is not True
        assert "running" in res["error"].lower()

    @pytest.mark.asyncio
    async def test_rejects_non_orchestrator(self, mgr, tmp_path):
        w = await self._make_worker(mgr, name="w1")
        newdir = tmp_path / "newproj"; newdir.mkdir()
        res = await mgr.change_orchestrator_scope("w1", "/old/proj", str(newdir), str(newdir))
        assert res.get("ok") is not True
        assert "orchestrator" in res["error"].lower()

    @pytest.mark.asyncio
    async def test_rejects_when_live_workers_in_old_scope(self, mgr, tmp_path):
        orch = await self._make_orch(mgr)
        await self._make_worker(mgr, name="w1", scope="/old/proj")
        newdir = tmp_path / "newproj"; newdir.mkdir()
        res = await mgr.change_orchestrator_scope("orch", "/old/proj", str(newdir), str(newdir))
        assert res.get("ok") is not True
        assert "worker" in res["error"].lower()
        assert "w1" in res["error"]

    @pytest.mark.asyncio
    async def test_rejects_nonexistent_cwd(self, mgr):
        await self._make_orch(mgr)
        res = await mgr.change_orchestrator_scope("orch", "/old/proj", "/new/proj", "/nonexistent/xyz")
        assert res.get("ok") is not True
        assert "error" in res

    @pytest.mark.asyncio
    async def test_not_found(self, mgr, tmp_path):
        newdir = tmp_path / "newproj"; newdir.mkdir()
        res = await mgr.change_orchestrator_scope("ghost", "/old/proj", str(newdir), str(newdir))
        assert res.get("ok") is not True
        assert "not" in res["error"].lower()

    @pytest.mark.asyncio
    async def test_drains_persist_before_db_write(self, mgr, tmp_path):
        # fence: any in-flight _persist() must be drained BEFORE change_scope()
        # so the transaction's cwd write is the last writer (no stale clobber).
        orch = await self._make_orch(mgr)
        newdir = tmp_path / "newproj"; newdir.mkdir()
        order = []
        orch._drain_persist = AsyncMock(side_effect=lambda: order.append("drain"))
        import app.db as dbmod
        real_change = dbmod.change_scope
        def traced(*a, **k):
            order.append("change_scope")
            return real_change(*a, **k)
        with patch("app.db.change_scope", side_effect=traced):
            res = await mgr.change_orchestrator_scope("orch", "/old/proj", str(newdir), str(newdir))
        assert res["ok"] is True
        orch._drain_persist.assert_awaited_once()
        assert order == ["drain", "change_scope"]  # drain strictly before the write

    @pytest.mark.asyncio
    async def test_db_cwd_is_new_after_inflight_persist(self, mgr, tmp_path):
        # end-to-end: even with several queued _persist() (old cwd snapshots)
        # the final DB cwd must be the new one — _drain_persist awaits ALL,
        # not just the last submitted future.
        from app.db import get_session
        orch = await self._make_orch(mgr)
        newdir = tmp_path / "newproj"; newdir.mkdir()
        orch._persist(); orch._persist(); orch._persist()  # queue stale snapshots
        assert orch._persist_task is not None
        res = await mgr.change_orchestrator_scope("orch", "/old/proj", str(newdir), str(newdir))
        assert res["ok"] is True
        assert get_session(orch.id)["cwd"] == str(newdir)
        # all drained before the transaction → nothing left to clobber
        assert orch._persist_task.done() and not orch._persist_dirty


class TestChangeScopeUnloadedWorkerGuard:
    @pytest.mark.asyncio
    async def test_rejects_unloaded_active_worker_in_old_scope(self, mgr, tmp_path):
        """An active worker row in the DB but NOT in self.sessions must still block."""
        from tests.conftest import make_backend_mock
        from app.session import AgentStatus
        from app.db import save_session, get_session
        with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
            orch = await mgr.create_session(
                name="orch", scope="/old/proj", cwd="/tmp",
                model="claude-opus-5", is_orchestrator=True,
            )
        orch.session_id = "sdk-tok"
        orch.status = AgentStatus.IDLE
        # Worker row exists in DB only (not loaded into manager.sessions)
        save_session({
            "id": "ghost-worker-id", "name": "ghostw", "scope": "/old/proj",
            "cwd": "/tmp", "model": "claude-sonnet-5[1m]", "system_prompt": "",
            "status": "idle", "session_id": "x", "cost_usd": 0.0,
            "worktree_path": None, "branch": None, "is_orchestrator": False,
            "color": "", "created_at": datetime.now(timezone.utc).isoformat(),
            "finished_at": None, "role": "worker",
        })
        newdir = tmp_path / "newproj"; newdir.mkdir()
        res = await mgr.change_orchestrator_scope("orch", "/old/proj", str(newdir), str(newdir))
        assert res.get("ok") is not True
        assert "ghostw" in res["error"]
        assert get_session(orch.id)["scope"] == "/old/proj"  # not moved

    @pytest.mark.asyncio
    async def test_archived_worker_does_not_block(self, mgr, tmp_path):
        from tests.conftest import make_backend_mock
        from app.session import AgentStatus
        from app.db import save_session
        with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
            orch = await mgr.create_session(
                name="orch", scope="/old/proj", cwd="/tmp",
                model="claude-opus-5", is_orchestrator=True,
            )
        orch.session_id = "sdk-tok"
        orch.status = AgentStatus.IDLE
        save_session({
            "id": "dead-worker-id", "name": "deadw", "scope": "/old/proj",
            "cwd": "/tmp", "model": "claude-sonnet-5[1m]", "system_prompt": "",
            "status": "archived", "session_id": "x", "cost_usd": 0.0,
            "worktree_path": None, "branch": None, "is_orchestrator": False,
            "color": "", "created_at": datetime.now(timezone.utc).isoformat(),
            "finished_at": None, "role": "worker",
        })
        newdir = tmp_path / "newproj"; newdir.mkdir()
        res = await mgr.change_orchestrator_scope("orch", "/old/proj", str(newdir), str(newdir))
        assert res["ok"] is True


class TestManagerLifecycle:
    @pytest.mark.asyncio
    async def test_shutdown_rebinds_background_primitives_for_next_event_loop(self, mgr):
        mgr.start_background_tasks()
        await asyncio.sleep(0)

        await mgr.shutdown_all()

        assert mgr._cleanup_task is None
        assert mgr._wt_cleanup_task is None
        assert mgr._session_locks == {}


class TestLiveChildren:
    """Orphan-guard: _live_children finds active sub-workers of a parent."""

    def _row(self, name, parent_name, status, scope="/proj"):
        from datetime import datetime, timezone
        return {
            "id": f"id-{name}", "name": name, "scope": scope,
            "cwd": "/tmp", "model": "claude-sonnet-5[1m]", "system_prompt": "",
            "status": status, "session_id": "x", "cost_usd": 0.0,
            "worktree_path": None, "branch": None, "is_orchestrator": False,
            "color": "", "created_at": datetime.now(timezone.utc).isoformat(),
            "finished_at": None, "role": "worker", "parent_name": parent_name,
        }

    def test_finds_live_children_from_db(self, mgr):
        from app.db import save_session
        save_session(self._row("child-a", "parent-w", "idle"))
        save_session(self._row("child-b", "parent-w", "running"))
        assert mgr._live_children("parent-w", "/proj") == ["child-a", "child-b"]

    def test_archived_children_not_blocking(self, mgr):
        from app.db import save_session
        save_session(self._row("child-dead", "parent-w", "archived"))
        assert mgr._live_children("parent-w", "/proj") == []

    def test_only_own_children(self, mgr):
        from app.db import save_session
        save_session(self._row("mine", "parent-w", "idle"))
        save_session(self._row("other", "another-parent", "idle"))
        assert mgr._live_children("parent-w", "/proj") == ["mine"]

    def test_scope_isolation(self, mgr):
        from app.db import save_session
        save_session(self._row("here", "parent-w", "idle", scope="/proj"))
        save_session(self._row("elsewhere", "parent-w", "idle", scope="/other"))
        assert mgr._live_children("parent-w", "/proj") == ["here"]

    def test_empty_parent_name_returns_empty(self, mgr):
        assert mgr._live_children("", "/proj") == []

    def test_no_children_returns_empty(self, mgr):
        from app.db import save_session
        save_session(self._row("lonely", "", "idle"))
        assert mgr._live_children("parent-w", "/proj") == []
