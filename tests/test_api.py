"""TDD tests for main.py — HTTP API endpoints."""

import asyncio
import os
import stat
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def db(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setattr("app.db.DB_PATH", db_path)
    wt_root = tmp_path / "worktrees"
    wt_root.mkdir()
    monkeypatch.setattr("app.workspace.WORKTREE_ROOT", wt_root)
    import app.routes.system as sysmod
    monkeypatch.setattr(sysmod, "_ALLOWED_ROOTS", ["/tmp", str(tmp_path)])
    from app.db import init_db
    init_db()


@pytest.fixture
def client(db):
    from tests.conftest import make_backend_mock
    with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
        from app.main import app, manager
        manager.sessions.clear()
        with TestClient(app) as c:
            yield c


def _save_merge_session_record(session) -> None:
    from datetime import datetime, timezone
    from app.db import save_session

    save_session({
        "id": session.id,
        "name": session.name,
        "scope": session.scope,
        "cwd": session.worktree_path,
        "model": "claude-sonnet-5[1m]",
        "system_prompt": "",
        "status": session.status.value,
        "session_id": None,
        "cost_usd": 0.0,
        "worktree_path": session.worktree_path,
        "branch": getattr(session, "branch", "") or "",
        "base_branch": getattr(session, "base_branch", "") or "",
        "needs_switch": 0,
        "task_id": getattr(session, "task_id", "") or "",
        "is_orchestrator": False,
        "color": "",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "finished_at": None,
    })


def _prepare_detached_merge(monkeypatch, session, *, head: str = "a" * 40):
    import app.main as mainmod
    import app.routes.sessions as sessmod
    from app.manager import SessionManager

    _save_merge_session_record(session)
    local_manager = SessionManager()
    monkeypatch.setattr(mainmod.manager, "get_by_name", lambda *_args: session)
    monkeypatch.setattr(mainmod.manager, "get", lambda _session_id: None)
    monkeypatch.setattr(
        mainmod.manager, "get_session_lock", local_manager.get_session_lock,
    )
    monkeypatch.setattr(
        mainmod.manager, "persist_lifecycle", local_manager.persist_lifecycle,
    )
    monkeypatch.setattr(
        "app.workspace.inspect_worktree_identity",
        lambda _path: (session.branch, head),
    )
    # Дрейф личности (#17) считается по НАСТОЯЩЕМУ git, а worktree здесь выдуманный.
    # Эти тесты про другое — про пин и про статусы RAG, — поэтому дрейфа тут нет по условию.
    # Поведение классификатора проверяется на живом репозитории в tests/test_identity_drift.py.
    monkeypatch.setattr(
        "app.workspace.classify_head_drift",
        lambda _path, branch, expected: {
            "class": "SAME",
            "actual_branch": branch or session.branch,
            "actual_head": expected or head,
            "reason": "",
        },
    )
    monkeypatch.setattr(sessmod, "_session_base_branch", lambda *_args: "main")
    monkeypatch.setattr("app.rag_service.is_enabled", lambda: False)
    return local_manager


class TestDashboard:
    def test_root_returns_html(self, client):
        r = client.get("/")
        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]


class TestCreateSession:
    def test_201(self, client):
        r = client.post("/api/sessions", json={
            "name": "worker-1",
            "scope": "/tmp",
            "cwd": "/tmp",
            "model": "claude-sonnet-5[1m]",
        })
        assert r.status_code == 201
        data = r.json()
        assert data["name"] == "worker-1"
        assert "id" in data

    def test_422_bad_name(self, client):
        r = client.post("/api/sessions", json={
            "name": "worker/bad",
            "scope": "/tmp",
            "cwd": "/tmp",
            "model": "claude-sonnet-5[1m]",
        })
        assert r.status_code == 422

    def test_422_empty_name(self, client):
        r = client.post("/api/sessions", json={
            "name": "",
            "scope": "/tmp",
            "cwd": "/tmp",
            "model": "claude-sonnet-5[1m]",
        })
        assert r.status_code == 422

    def test_409_duplicate(self, client):
        body = {"name": "w1", "scope": "/tmp", "cwd": "/tmp", "model": "claude-sonnet-5[1m]"}
        r1 = client.post("/api/sessions", json=body)
        assert r1.status_code == 201
        r2 = client.post("/api/sessions", json=body)
        assert r2.status_code == 409

    def test_422_bad_cwd(self, client):
        r = client.post("/api/sessions", json={
            "name": "w1",
            "scope": "/tmp",
            "cwd": "/nonexistent/path",
            "model": "claude-sonnet-5[1m]",
        })
        assert r.status_code == 422


class TestGetSessions:
    def test_list_empty(self, client):
        r = client.get("/api/sessions")
        assert r.status_code == 200
        # May contain bootstrap orchestrator from startup — just check it's a list
        assert isinstance(r.json(), list)

    def test_list_with_scope(self, client):
        client.post("/api/sessions", json={"name": "w1", "scope": "/a", "cwd": "/tmp", "model": "claude-sonnet-5[1m]"})
        client.post("/api/sessions", json={"name": "w2", "scope": "/b", "cwd": "/tmp", "model": "claude-sonnet-5[1m]"})
        r = client.get("/api/sessions", params={"scope": "/a"})
        assert r.status_code == 200
        data = r.json()
        assert len(data) == 1
        assert data[0]["name"] == "w1"

    def test_get_by_name(self, client):
        client.post("/api/sessions", json={"name": "w1", "scope": "/s", "cwd": "/tmp", "model": "claude-sonnet-5[1m]"})
        r = client.get("/api/sessions/w1", params={"scope": "/s"})
        assert r.status_code == 200
        assert r.json()["name"] == "w1"

    def test_get_404(self, client):
        r = client.get("/api/sessions/nonexistent", params={"scope": "/s"})
        assert r.status_code == 404


class TestHibernateSession:
    def test_loaded_session_hibernates(self, client, monkeypatch):
        import app.routes.system as sysmod

        session = SimpleNamespace(
            loaded=True,
            hibernate_now=AsyncMock(return_value={
                "ok": True,
                "state": "hibernated",
            }),
        )
        monkeypatch.setattr(sysmod.manager, "get_by_name", lambda *_args: session)

        response = client.post(
            "/api/sessions/worker/hibernate",
            json={"scope": "/project"},
        )

        assert response.status_code == 200
        assert response.json() == {"ok": True, "state": "hibernated"}
        session.hibernate_now.assert_awaited_once_with()

    def test_detached_session_is_already_process_free(self, client, monkeypatch):
        import app.routes.system as sysmod

        session = SimpleNamespace(loaded=False, hibernate_now=AsyncMock())
        monkeypatch.setattr(sysmod.manager, "get_by_name", lambda *_args: session)

        response = client.post(
            "/api/sessions/worker/hibernate",
            json={"scope": "/project"},
        )

        assert response.status_code == 200
        assert response.json() == {
            "ok": True,
            "state": "already_process_free",
        }
        session.hibernate_now.assert_not_awaited()

    def test_ineligible_session_returns_conflict(self, client, monkeypatch):
        import app.routes.system as sysmod

        session = SimpleNamespace(
            loaded=True,
            hibernate_now=AsyncMock(return_value={
                "ok": False,
                "reason": "not_idle",
                "error": "session is running",
            }),
        )
        monkeypatch.setattr(sysmod.manager, "get_by_name", lambda *_args: session)

        response = client.post(
            "/api/sessions/worker/hibernate",
            json={"scope": "/project"},
        )

        assert response.status_code == 409
        assert response.json()["reason"] == "not_idle"

    def test_teardown_error_includes_exception_class(self, client, monkeypatch):
        import app.routes.system as sysmod

        session = SimpleNamespace(
            loaded=True,
            hibernate_now=AsyncMock(side_effect=TimeoutError()),
        )
        monkeypatch.setattr(sysmod.manager, "get_by_name", lambda *_args: session)

        response = client.post(
            "/api/sessions/worker/hibernate",
            json={"scope": "/project"},
        )

        assert response.status_code == 500
        assert response.json()["error"] == "TimeoutError: "

    def test_missing_session_returns_not_found(self, client, monkeypatch):
        import app.routes.system as sysmod

        monkeypatch.setattr(sysmod.manager, "get_by_name", lambda *_args: None)

        response = client.post(
            "/api/sessions/missing/hibernate",
            json={"scope": "/project"},
        )

        assert response.status_code == 404


@pytest.fixture
def bug_state(tmp_path, monkeypatch):
    import app.routes.system as sysmod

    state = tmp_path / "state"
    monkeypatch.setattr(sysmod, "_BUG_STATE_ROOT_CACHE", state)
    monkeypatch.setattr(sysmod, "_BUG_VALIDATED_DIRS", {})
    return state


class TestBugReports:
    def test_publish_read_and_private_modes(self, client, bug_state):
        description = "Location: app/x.py:7\n" + ("trace <unsafe>\n" * 8192)

        response = client.post("/api/report_bug", json={
            "title": "full trace",
            "description": description,
            "reporter": "worker",
            "scope": "/project",
        })
        reader = client.get("/api/report_bug")

        assert response.status_code == 200
        assert response.json()["view_url"] == "/api/report_bug"
        assert response.json()["record_id"].endswith(".md")
        assert reader.status_code == 200
        assert description in reader.text
        assert "## [" in reader.text

        inbox = bug_state / "bug-inbox"
        for directory in (bug_state, inbox, inbox / "tmp", inbox / "records"):
            assert stat.S_IMODE(directory.stat().st_mode) == 0o700
        record = next((inbox / "records").iterdir())
        assert stat.S_IMODE(record.stat().st_mode) == 0o600

    def test_legacy_and_snapshot_exclude_later_publish(self, bug_state):
        import app.routes.system as sysmod

        sysmod._bug_snapshot()
        legacy = bug_state / "bug-inbox" / "legacy.md"
        legacy.write_text("# migrated\n")
        legacy.chmod(0o600)
        sysmod._publish_bug_record("\nfirst-record\n")
        snapshot = sysmod._bug_snapshot()
        stream = sysmod._stream_bug_snapshot(snapshot)

        first_chunk = next(stream)
        sysmod._publish_bug_record("\nsecond-record\n")
        captured = first_chunk + b"".join(stream)

        assert b"# migrated" in captured
        assert b"first-record" in captured
        assert b"second-record" not in captured
        assert b"second-record" in b"".join(
            sysmod._stream_bug_snapshot(sysmod._bug_snapshot())
        )

    @pytest.mark.asyncio
    async def test_route_offloads_blocking_publish(self, monkeypatch):
        import app.routes.system as sysmod

        loop = asyncio.get_running_loop()
        started = asyncio.Event()
        release = threading.Event()

        def blocking_publish(_entry):
            loop.call_soon_threadsafe(started.set)
            release.wait()
            return "/state/record.md", "record.md"

        request = SimpleNamespace(json=AsyncMock(return_value={"title": "blocked"}))
        monkeypatch.setattr(sysmod, "_publish_bug_record", blocking_publish)

        task = asyncio.create_task(sysmod.report_bug_endpoint(request))
        await started.wait()
        assert task.done() is False
        release.set()
        result = await task

        assert result["record_id"] == "record.md"

    def test_concurrent_large_and_subprocess_records_are_complete(
        self, bug_state,
    ):
        import app.routes.system as sysmod

        entries = [f"\nmarker-{i}\n" + (chr(65 + i % 26) * 131072) for i in range(32)]
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(sysmod._publish_bug_record, entries))

        env = os.environ.copy()
        env["STATE_DIRECTORY"] = str(bug_state)
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "from app.routes.system import _publish_bug_record; "
                "_publish_bug_record('\\nsubprocess-marker\\n')",
            ],
            cwd=Path(__file__).parent.parent,
            env=env,
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0, result.stderr
        records = list((bug_state / "bug-inbox" / "records").glob("*.md"))
        assert len(records) == 33
        bodies = [record.read_text() for record in records]
        for i, entry in enumerate(entries):
            matches = [body for body in bodies if f"\nmarker-{i}\n" in body]
            assert matches == [entry]
        assert sum("subprocess-marker" in body for body in bodies) == 1

    def test_partial_write_never_becomes_visible(self, bug_state, monkeypatch):
        import app.routes.system as sysmod

        real_write = sysmod.os.write
        calls = 0

        def interrupted_write(fd, payload):
            nonlocal calls
            calls += 1
            if calls == 1:
                return real_write(fd, payload[:7])
            raise OSError("simulated partial write")

        monkeypatch.setattr(sysmod.os, "write", interrupted_write)

        with pytest.raises(OSError, match="simulated partial write"):
            sysmod._publish_bug_record("complete-record")

        assert sysmod._bug_snapshot()["records"] == []

    def test_failure_after_publish_keeps_one_complete_record(
        self, bug_state, monkeypatch,
    ):
        import app.routes.system as sysmod

        sysmod._bug_snapshot()
        real_sync = sysmod._sync_fd
        calls = 0

        def fail_directory_sync(fd):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("simulated directory fsync")
            real_sync(fd)

        monkeypatch.setattr(sysmod, "_sync_fd", fail_directory_sync)
        with pytest.raises(OSError, match="simulated directory fsync"):
            sysmod._publish_bug_record("whole-record")

        monkeypatch.setattr(sysmod, "_sync_fd", real_sync)
        monkeypatch.setattr(sysmod, "_BUG_VALIDATED_DIRS", {})
        snapshot = sysmod._bug_snapshot()
        body = b"".join(sysmod._stream_bug_snapshot(snapshot))
        assert len(snapshot["records"]) == 1
        assert body == b"whole-record"

    def test_empty_exception_text_still_returns_class(
        self, client, bug_state, monkeypatch,
    ):
        import app.routes.system as sysmod

        monkeypatch.setattr(
            sysmod, "_publish_bug_record", MagicMock(side_effect=TimeoutError()),
        )
        response = client.post("/api/report_bug", json={"title": "timeout"})

        assert response.status_code == 500
        assert response.json()["error"] == "TimeoutError"

    def test_git_environment_is_sanitized(self, tmp_path, monkeypatch):
        import app.routes.system as sysmod

        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)
        safe = tmp_path / "safe"
        safe.mkdir()
        monkeypatch.setenv("GIT_DIR", str(repo / ".git"))
        monkeypatch.setenv("GIT_WORK_TREE", str(repo))

        sysmod._assert_bug_path_outside_git(safe)

    def test_state_directory_inside_worktree_is_rejected(self, tmp_path, monkeypatch):
        import app.routes.system as sysmod

        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)
        monkeypatch.setenv("STATE_DIRECTORY", str(repo / "state"))
        monkeypatch.setattr(sysmod, "_BUG_STATE_ROOT_CACHE", None)

        with pytest.raises(RuntimeError, match="inside Git metadata"):
            sysmod._bug_state_root()

    def test_state_root_symlink_is_rejected(self, tmp_path, monkeypatch):
        import app.routes.system as sysmod

        target = tmp_path / "target"
        target.mkdir()
        state_link = tmp_path / "state-link"
        state_link.symlink_to(target, target_is_directory=True)
        monkeypatch.setattr(sysmod, "_BUG_STATE_ROOT_CACHE", state_link)
        monkeypatch.setattr(sysmod, "_BUG_VALIDATED_DIRS", {})

        with pytest.raises((NotADirectoryError, RuntimeError, OSError)):
            sysmod._publish_bug_record("must-not-follow-root")
        assert list(target.iterdir()) == []

    @pytest.mark.parametrize("kind", ["worktree", "git-dir", "bare", "missing-child"])
    def test_git_paths_are_rejected(self, tmp_path, kind):
        import app.routes.system as sysmod

        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)
        if kind == "worktree":
            candidate = repo
        elif kind == "git-dir":
            candidate = repo / ".git"
        elif kind == "missing-child":
            candidate = repo / "missing" / "state"
        else:
            candidate = tmp_path / "bare.git"
            subprocess.run(
                ["git", "init", "--bare", str(candidate)],
                capture_output=True,
                check=True,
            )

        with pytest.raises(RuntimeError, match="inside Git metadata"):
            sysmod._assert_bug_path_outside_git(candidate)

    @pytest.mark.parametrize("component", ["bug-inbox", "tmp", "records"])
    def test_descendant_symlink_after_validation_is_rejected(
        self, bug_state, tmp_path, monkeypatch, component,
    ):
        import app.routes.system as sysmod

        target = tmp_path / "target"
        target.mkdir()
        sysmod._bug_snapshot()
        inbox = bug_state / "bug-inbox"
        replaced = inbox if component == "bug-inbox" else inbox / component
        if component == "bug-inbox":
            for child in inbox.iterdir():
                child.rmdir()
        replaced.rmdir()
        replaced.symlink_to(target, target_is_directory=True)
        monkeypatch.setattr(sysmod, "_BUG_VALIDATED_DIRS", {})

        with pytest.raises((NotADirectoryError, RuntimeError, OSError)):
            sysmod._publish_bug_record("must-not-land-in-target")
        assert list(target.iterdir()) == []

    def test_legacy_and_record_symlinks_are_rejected(self, bug_state, tmp_path):
        import app.routes.system as sysmod

        sysmod._bug_snapshot()
        target = tmp_path / "target.md"
        target.write_text("secret")
        inbox = bug_state / "bug-inbox"
        (inbox / "legacy.md").symlink_to(target)
        with pytest.raises((RuntimeError, OSError)):
            sysmod._bug_snapshot()
        (inbox / "legacy.md").unlink()
        (inbox / "records" / "redirect.md").symlink_to(target)
        with pytest.raises((RuntimeError, OSError)):
            sysmod._bug_snapshot()


class TestSendMessage:
    def test_send(self, client):
        client.post("/api/sessions", json={"name": "w1", "scope": "/s", "cwd": "/tmp", "model": "claude-sonnet-5[1m]"})
        r = client.post("/api/sessions/w1/send", json={"message": "hello", "scope": "/s"})
        assert r.status_code == 200

    def test_send_404(self, client):
        r = client.post("/api/sessions/ghost/send", json={"message": "hi", "scope": "/s"})
        assert r.status_code == 404


class TestInterrupt:
    def test_interrupt(self, client):
        client.post("/api/sessions", json={"name": "w1", "scope": "/s", "cwd": "/tmp", "model": "claude-sonnet-5[1m]"})
        r = client.post("/api/sessions/w1/interrupt", json={"scope": "/s"})
        assert r.status_code == 200


class TestDeleteSession:
    def test_delete(self, client):
        client.post("/api/sessions", json={"name": "w1", "scope": "/s", "cwd": "/tmp", "model": "claude-sonnet-5[1m]"})
        r = client.delete("/api/sessions/w1", params={"scope": "/s"})
        assert r.status_code == 200
        r2 = client.get("/api/sessions/w1", params={"scope": "/s"})
        assert r2.status_code == 404

    def test_delete_404(self, client):
        r = client.delete("/api/sessions/ghost", params={"scope": "/s"})
        assert r.status_code == 404


class TestLogs:
    def test_logs_empty(self, client):
        client.post("/api/sessions", json={"name": "w1", "scope": "/s", "cwd": "/tmp", "model": "claude-sonnet-5[1m]"})
        r = client.get("/api/sessions/w1/logs", params={"scope": "/s"})
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_logs_404(self, client):
        r = client.get("/api/sessions/ghost/logs", params={"scope": "/s"})
        assert r.status_code == 404


class TestStats:
    def test_stats(self, client):
        r = client.get("/api/stats")
        assert r.status_code == 200
        data = r.json()
        assert "total_sessions" in data

    def test_stats_with_scope(self, client):
        r = client.get("/api/stats", params={"scope": "/s"})
        assert r.status_code == 200


class TestTestLockApi:
    def test_acquire_and_status_and_release(self, client):
        # свободен
        st = client.get("/api/test-lock", params={"scope": "/s"})
        assert st.status_code == 200
        assert st.json()["held"] is False

        # захват
        r = client.post("/api/test-lock/acquire", json={"scope": "/s", "holder": "coder-a", "reason": "suite"})
        assert r.status_code == 200
        assert r.json()["acquired"] is True

        # занято другим
        r2 = client.post("/api/test-lock/acquire", json={"scope": "/s", "holder": "coder-b", "reason": "x"})
        assert r2.status_code == 200
        assert r2.json()["acquired"] is False
        assert r2.json()["holder"] == "coder-a"

        # статус
        st2 = client.get("/api/test-lock", params={"scope": "/s"})
        assert st2.status_code == 200
        assert st2.json()["held"] is True
        assert st2.json()["holder"] == "coder-a"

        # релиз
        rel = client.post("/api/test-lock/release", json={"scope": "/s", "holder": "coder-a"})
        assert rel.status_code == 200
        assert rel.json()["released"] is True


class TestOrchestrators:
    def test_list_orchestrators(self, client):
        r = client.get("/api/orchestrators")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_list_orchestrators_exposes_runtime_cache_policy(self, client):
        for name, model in (
            ("claude-orch", "claude-opus-5[1m]"),
            ("codex-orch", "gpt-5.6-sol"),
        ):
            response = client.post("/api/sessions", json={
                "name": name,
                "scope": f"/tmp/{name}",
                "cwd": "/tmp",
                "model": model,
                "is_orchestrator": True,
                "role": "orchestrator",
            })
            assert response.status_code == 201

        rows = {row["name"]: row for row in client.get("/api/orchestrators").json()}
        assert rows["claude-orch"]["cache_ttl_seconds"] == 3600
        assert rows["claude-orch"]["cache_ttl_approximate"] is False
        assert rows["codex-orch"]["cache_ttl_seconds"] == 1800
        assert rows["codex-orch"]["cache_ttl_approximate"] is True


def test_create_request_accepts_base_branch():
    from app.routes.sessions import CreateSessionRequest
    req = CreateSessionRequest(name="w1", cwd="/tmp", model="claude-sonnet-5[1m]",
                               use_worktree=True, repo_path="/tmp",
                               base_branch="feature/auth")
    assert req.base_branch == "feature/auth"


def test_create_request_base_branch_default_empty():
    # Sentinel "" = авто-резолв базовой ветки по стратегии пайплайна (DESIGN §10).
    # Резолв в "main" происходит в manager/workspace, а не в дефолте запроса.
    from app.routes.sessions import CreateSessionRequest
    req = CreateSessionRequest(name="w1", cwd="/tmp", model="claude-sonnet-5[1m]")
    assert req.base_branch == ""


@pytest.mark.asyncio
async def test_merge_endpoint_passes_target(db, monkeypatch):
    import app.main as mainmod
    import app.routes.sessions as sessmod
    import asyncio
    captured = {}

    async def fake_execute(**kwargs):
        captured.update(kwargs)
        return {"ok": True, "commits_merged": 1, "branch": "task-1/w", "merged_commits": {}}
    monkeypatch.setattr(sessmod, "execute_merge_session", fake_execute)

    class FakeSession:
        loaded = True
        class _S:
            value = "idle"
        status = _S()
        _lifecycle_lock = asyncio.Lock()
        worktree_path = "/wt"
        scope = "/s"
        id = "sid"
        name = "w"
        branch = "task-1/w"
        def _persist(self):
            pass
    session = FakeSession()
    monkeypatch.setattr(mainmod.manager, "get_by_name", lambda name, scope: session)

    res = await sessmod.merge_session("w", {"scope": "/s", "target": "feature/auth"})
    assert captured["session_id"] == "sid"
    assert captured["expected_branch"] == "task-1/w"
    assert captured["req"]["target"] == "feature/auth"
    assert res["ok"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("loaded", [False, True])
async def test_merge_persists_actual_branch_and_base_for_loaded_or_detached(
    db, monkeypatch, loaded,
):
    import app.main as mainmod
    import app.routes.sessions as sessmod
    from app.db import get_session, save_session
    from app.manager import SessionManager
    from datetime import datetime, timezone

    save_session({
        "id": f"merge-{loaded}", "name": f"merge-{loaded}", "scope": "/s",
        "cwd": "/wt", "model": "claude-sonnet-5[1m]", "system_prompt": "", "status": "idle",
        "session_id": None, "cost_usd": 0.0, "worktree_path": "/wt",
        "branch": "task-90/w", "base_branch": "master", "needs_switch": 0,
        "task_id": "90", "is_orchestrator": False, "color": "",
        "created_at": datetime.now(timezone.utc).isoformat(), "finished_at": None,
    })
    local_manager = SessionManager()
    found = local_manager.get_by_name(f"merge-{loaded}", "/s")
    found.loaded = loaded

    monkeypatch.setattr(mainmod.manager, "get_by_name", lambda *_args: found)
    monkeypatch.setattr(
        mainmod.manager, "get", lambda session_id: found if loaded else None,
    )
    monkeypatch.setattr(
        mainmod.manager, "get_session_lock", local_manager.get_session_lock,
    )
    monkeypatch.setattr(
        mainmod.manager, "persist_lifecycle", local_manager.persist_lifecycle,
    )
    monkeypatch.setattr(
        sessmod, "_session_base_branch",
        lambda _session, requested="": requested or "master",
    )
    monkeypatch.setattr(
        "app.workspace.merge_worktree_to_main",
        lambda *_args, **_kwargs: {
            "ok": True,
            "commits_merged": 1,
            "branch": "task-90/w",
            "merged_commits": {},
        },
    )
    monkeypatch.setattr(
        "app.workspace.inspect_worktree_identity",
        lambda _path: ("task-90/w", "a" * 40),
    )
    monkeypatch.setattr("app.rag_service.is_enabled", lambda: False)

    result = await sessmod.merge_session(f"merge-{loaded}", {"scope": "/s"})

    assert result["ok"] is True
    row = get_session(f"merge-{loaded}")
    assert (row["branch"], row["base_branch"], row["task_id"], row["needs_switch"]) == (
        "task-90/w", "master", "", 1,
    )
    assert found.branch == "task-90/w"
    assert found.base_branch == "master"
    if loaded:
        assert found.needs_switch is True


@pytest.mark.asyncio
async def test_merge_rejects_ambiguous_legacy_base_before_git(db, monkeypatch):
    import app.main as mainmod
    import app.routes.sessions as sessmod

    session = type("Session", (), {
        "id": "legacy",
        "name": "legacy",
        "scope": "/s",
        "worktree_path": "/wt",
        "base_branch": "",
        "branch": "task-90/legacy",
        "loaded": False,
        "status": type("Status", (), {"value": "idle"})(),
    })()
    _save_merge_session_record(session)
    merge_called = False

    def fake_merge(*_args, **_kwargs):
        nonlocal merge_called
        merge_called = True
        return {"ok": True}

    monkeypatch.setattr(mainmod.manager, "get_by_name", lambda *_args: session)
    monkeypatch.setattr(mainmod.manager, "get", lambda _session_id: None)
    monkeypatch.setattr(
        "app.workspace.inspect_worktree_identity",
        lambda _path: (session.branch, "a" * 40),
    )
    monkeypatch.setattr(
        sessmod,
        "_session_base_branch",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            ValueError("cannot resolve repository mainline; pass base_branch explicitly")
        ),
    )
    monkeypatch.setattr("app.workspace.merge_worktree_to_main", fake_merge)

    response = await sessmod.merge_session("legacy", {"scope": "/s"})

    assert response.status_code == 400
    assert merge_called is False


@pytest.mark.asyncio
async def test_merge_links_commits_with_normalized_sqlite_results(db, monkeypatch):
    import json
    import app.main as mainmod
    import app.routes.sessions as sessmod
    from app import tm

    with tm._conn() as conn:
        tm.ensure_project(conn, "project", scope="/s")
        task = tm.create_task(conn, "project", "Link target", par_number=90)

    class FakeSession:
        loaded = False
        status = type("Status", (), {"value": "idle"})()
        worktree_path = "/wt"
        scope = "/s"
        id = "link-results"
        name = "worker"
        branch = "task-90/worker"

    session = FakeSession()
    _save_merge_session_record(session)

    async def persist_lifecycle(found, **fields):
        for key, value in fields.items():
            setattr(found, key, value)

    monkeypatch.setattr(mainmod.manager, "get_by_name", lambda *_args: session)
    monkeypatch.setattr(mainmod.manager, "get", lambda _session_id: None)
    monkeypatch.setattr(mainmod.manager, "persist_lifecycle", persist_lifecycle)
    monkeypatch.setattr(sessmod, "_session_base_branch", lambda *_args: "main")
    monkeypatch.setattr(
        "app.workspace.merge_worktree_to_main",
        lambda *_args, **_kwargs: {
            "ok": True,
            "commits_merged": 1,
            "branch": "task-90/worker",
            "merged_commits": {
                "90": [{"hash": "abc123", "message": "#90: work"}],
                "999": [{"hash": "def456", "message": "#999: missing"}],
            },
        },
    )
    monkeypatch.setattr(
        "app.workspace.inspect_worktree_identity",
        lambda _path: (session.branch, "a" * 40),
    )
    monkeypatch.setattr("app.rag_service.is_enabled", lambda: False)

    result = await sessmod.merge_session("worker", {"scope": "/s"})

    assert result["linked_tasks"]["90"] == {
        "ok": True,
        "added": 1,
        "task_id": task["id"],
    }
    assert result["linked_tasks"]["999"] == {
        "ok": False,
        "added": 0,
        "error": "task '999' not found",
    }
    with tm._conn() as conn:
        linked = tm.resolve_task_ref(conn, "90", "project")
    commits = json.loads(linked["git_commits"])
    assert [commit["hash"] for commit in commits] == ["abc123"]
    assert tm.link_commits_to_task(
        "90", [{"hash": "abc123", "message": "#90: work"}], project_id="project",
    ) == {"ok": True, "added": 0, "task_id": task["id"]}


@pytest.mark.asyncio
@pytest.mark.parametrize("next_task_id", ["not-a-task", "999"])
async def test_merge_rejects_invalid_or_missing_next_task_before_git(
    db, monkeypatch, next_task_id,
):
    import app.routes.sessions as sessmod
    from app import tm

    with tm._conn() as conn:
        tm.ensure_project(conn, "project", scope="/s")
    session = type("Session", (), {
        "loaded": False,
        "status": type("Status", (), {"value": "idle"})(),
        "worktree_path": "/wt",
        "scope": "/s",
        "id": f"invalid-next-{next_task_id}",
        "name": "worker",
        "branch": "task-90/worker",
        "base_branch": "main",
    })()
    _prepare_detached_merge(monkeypatch, session)

    monkeypatch.setattr(
        "app.workspace.inspect_worktree_identity",
        lambda *_args: (_ for _ in ()).throw(AssertionError("Git inspection must not run")),
    )
    monkeypatch.setattr(
        "app.workspace.merge_worktree_to_main",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("merge must not run")),
    )

    response = await sessmod.merge_session(
        "worker", {"scope": "/s", "next_task_id": next_task_id},
    )

    assert response.status_code == 400


@pytest.mark.asyncio
async def test_execute_merge_session_rejects_removed_and_respawned_identity(db, monkeypatch):
    import app.routes.sessions as sessmod
    from app.db import delete_session

    old = type("Session", (), {
        "loaded": False,
        "status": type("Status", (), {"value": "idle"})(),
        "worktree_path": "/old-wt",
        "scope": "/s",
        "id": "old-session",
        "name": "worker",
        "branch": "task-90/worker",
        "base_branch": "main",
    })()
    _save_merge_session_record(old)
    delete_session(old.id)
    replacement = type("Session", (), {
        "loaded": False,
        "status": type("Status", (), {"value": "idle"})(),
        "worktree_path": "/new-wt",
        "scope": "/s",
        "id": "new-session",
        "name": "worker",
        "branch": "task-91/worker",
        "base_branch": "main",
    })()
    _save_merge_session_record(replacement)
    monkeypatch.setattr(
        "app.workspace.merge_worktree_to_main",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("merge must not run")),
    )

    result = await sessmod.execute_merge_session(
        session_id=old.id,
        expected_name=old.name,
        expected_scope=old.scope,
        expected_branch=old.branch,
        expected_head="a" * 40,
        req={"scope": "/s"},
    )

    assert result["ok"] is False
    assert result["state"] == "failed"
    assert result["commit_point"] == "not_reached"
    assert result["_http_status"] == 404


@pytest.mark.asyncio
async def test_execute_merge_session_passes_pinned_branch_and_head_into_repo_lock(
    db, monkeypatch,
):
    import app.routes.sessions as sessmod

    session = type("Session", (), {
        "loaded": False,
        "status": type("Status", (), {"value": "idle"})(),
        "worktree_path": "/wt",
        "scope": "/s",
        "id": "pinned-session",
        "name": "worker",
        "branch": "task-42/worker",
        "base_branch": "main",
    })()
    _prepare_detached_merge(monkeypatch, session)
    captured = {}

    def fake_merge(*_args, **kwargs):
        captured.update(kwargs)
        return {
            "ok": True, "commits_merged": 0, "branch": session.branch,
            "merged_commits": {},
        }

    monkeypatch.setattr("app.workspace.merge_worktree_to_main", fake_merge)
    monkeypatch.setattr(
        "app.workspace.inspect_worktree_identity",
        lambda *_args: (_ for _ in ()).throw(
            AssertionError("durable operation supplied the pinned head")
        ),
    )

    result = await sessmod.execute_merge_session(
        session_id=session.id,
        expected_name=session.name,
        expected_scope=session.scope,
        expected_branch=session.branch,
        expected_head="b" * 40,
        req={"scope": "/s", "target": "main"},
    )

    assert result["ok"] is True
    assert captured["expected_worker_branch"] == session.branch
    assert captured["expected_worker_head"] == "b" * 40


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["accepted", "coalesced", "not_ready"])
async def test_merge_exposes_raw_rag_backfill_status(db, monkeypatch, status):
    import app.routes.sessions as sessmod

    session = type("Session", (), {
        "loaded": False,
        "status": type("Status", (), {"value": "idle"})(),
        "worktree_path": "/wt",
        "scope": "/s",
        "id": f"rag-status-{status}",
        "name": "worker",
        "branch": "task-42/worker",
        "base_branch": "main",
    })()
    _prepare_detached_merge(monkeypatch, session)
    monkeypatch.setattr(
        "app.workspace.merge_worktree_to_main",
        lambda *_args, **_kwargs: {
            "ok": True, "commits_merged": 1, "branch": session.branch,
            "merged_commits": {},
        },
    )
    scheduled = []

    def fake_schedule(scope, session_name=""):
        scheduled.append(scope)
        return status

    monkeypatch.setattr("app.rag_service.schedule_backfill", fake_schedule)

    result = await sessmod.execute_merge_session(
        session_id=session.id,
        expected_name=session.name,
        expected_scope=session.scope,
        expected_branch=session.branch,
        expected_head="b" * 40,
        req={"scope": "/s", "target": "main"},
    )

    assert result["rag_backfill_status"] == status
    assert scheduled == ["/s"]


@pytest.mark.asyncio
async def test_merge_returns_before_blocked_rag_backfill(db, monkeypatch):
    import asyncio
    import app.routes.sessions as sessmod
    from app import rag_service

    session = type("Session", (), {
        "loaded": False,
        "status": type("Status", (), {"value": "idle"})(),
        "worktree_path": "/wt",
        "scope": "/s",
        "id": "rag-does-not-block",
        "name": "worker",
        "branch": "task-42/worker",
        "base_branch": "main",
    })()
    _prepare_detached_merge(monkeypatch, session)
    monkeypatch.setattr(
        "app.workspace.merge_worktree_to_main",
        lambda *_args, **_kwargs: {
            "ok": True, "commits_merged": 1, "branch": session.branch,
            "merged_commits": {},
        },
    )
    monkeypatch.setattr(rag_service, "_RAG_ENABLED", True)
    monkeypatch.setattr(rag_service, "_initialized", True)
    monkeypatch.setattr(rag_service, "_backfill_tasks", {})
    monkeypatch.setattr(rag_service, "_backfill_dirty", set())
    started = asyncio.Event()
    release = asyncio.Event()

    async def blocked_backfill(_scope, session_name=None):
        started.set()
        await release.wait()
        return {"files": 1, "logs": 0}

    monkeypatch.setattr(rag_service, "backfill_scope", blocked_backfill)

    result = await sessmod.execute_merge_session(
        session_id=session.id,
        expected_name=session.name,
        expected_scope=session.scope,
        expected_branch=session.branch,
        expected_head="b" * 40,
        req={"scope": "/s", "target": "main"},
    )

    assert result["rag_backfill_status"] == "accepted"
    task = rag_service._backfill_tasks["/s"]
    assert not task.done()
    await started.wait()

    release.set()
    await task


@pytest.mark.asyncio
async def test_merge_revision_change_keeps_git_success_and_skips_task_update(
    db, monkeypatch,
):
    import app.routes.sessions as sessmod
    from app import tm
    from app.db import get_session

    with tm._conn() as conn:
        tm.ensure_project(conn, "project", scope="/s")
        task = tm.create_task(conn, "project", "next", par_number=43)
    session = type("Session", (), {
        "loaded": False,
        "status": type("Status", (), {"value": "idle"})(),
        "worktree_path": "/wt",
        "scope": "/s",
        "id": "revision-race",
        "name": "worker",
        "branch": "task-42/worker",
        "base_branch": "main",
    })()
    _prepare_detached_merge(monkeypatch, session)

    def merge_and_change_revision(*_args, **_kwargs):
        with tm._conn() as conn:
            conn.execute(
                "UPDATE tm_tasks SET sync_revision=sync_revision+1 WHERE id=?",
                (task["id"],),
            )
        return {"ok": True, "commits_merged": 1, "branch": session.branch,
                "merged_commits": {}}

    monkeypatch.setattr("app.workspace.merge_worktree_to_main", merge_and_change_revision)
    monkeypatch.setattr(
        "app.workspace.switch_worktree_branch",
        lambda *_args, **_kwargs: {"ok": True, "branch": "task-43/worker"},
    )

    result = await sessmod.merge_session(
        "worker", {"scope": "/s", "next_task_id": "43"},
    )

    assert result["ok"] is True
    assert result["switch"]["ok"] is True
    assert result["task_status"]["ok"] is False
    assert "revision" in result["task_status"]["error"]
    assert result["task_status"]["quarantined"] is True
    with tm._conn() as conn:
        assert tm.get_task_by_id(conn, task["id"])["status"] == "new"
    row = get_session(session.id)
    assert (row["task_id"], row["needs_switch"], row["branch"]) == (
        "", 1, "task-43/worker",
    )


@pytest.mark.asyncio
async def test_merge_switch_failure_stays_merge_success_and_keeps_quarantine(
    db, monkeypatch,
):
    import app.routes.sessions as sessmod
    from app import tm
    from app.db import get_session

    with tm._conn() as conn:
        tm.ensure_project(conn, "project", scope="/s")
        task = tm.create_task(conn, "project", "next", par_number=43)
    session = type("Session", (), {
        "loaded": False,
        "status": type("Status", (), {"value": "idle"})(),
        "worktree_path": "/wt",
        "scope": "/s",
        "id": "switch-failure",
        "name": "worker",
        "branch": "task-42/worker",
        "base_branch": "main",
    })()
    _prepare_detached_merge(monkeypatch, session)
    monkeypatch.setattr(
        "app.workspace.merge_worktree_to_main",
        lambda *_args, **_kwargs: {
            "ok": True, "commits_merged": 1, "branch": session.branch,
            "merged_commits": {},
        },
    )
    monkeypatch.setattr(
        "app.workspace.switch_worktree_branch",
        lambda *_args, **_kwargs: {"ok": False, "error": "target is dirty"},
    )

    result = await sessmod.merge_session(
        "worker", {"scope": "/s", "next_task_id": "43"},
    )

    assert result["ok"] is True
    assert result["switch"] == {"ok": False, "error": "target is dirty"}
    assert result["task_status"]["ok"] is False
    with tm._conn() as conn:
        assert tm.get_task_by_id(conn, task["id"])["status"] == "new"
    row = get_session(session.id)
    assert (row["task_id"], row["needs_switch"], row["branch"]) == (
        "", 1, session.branch,
    )


@pytest.mark.asyncio
async def test_merge_switch_exception_stays_merge_success_and_keeps_quarantine(
    db, monkeypatch,
):
    import app.routes.sessions as sessmod
    from app import tm
    from app.db import get_session

    with tm._conn() as conn:
        tm.ensure_project(conn, "project", scope="/s")
        task = tm.create_task(conn, "project", "next", par_number=43)
    session = type("Session", (), {
        "loaded": False,
        "status": type("Status", (), {"value": "idle"})(),
        "worktree_path": "/wt",
        "scope": "/s",
        "id": "switch-exception",
        "name": "worker",
        "branch": "task-42/worker",
        "base_branch": "main",
    })()
    _prepare_detached_merge(monkeypatch, session)
    monkeypatch.setattr(
        "app.workspace.merge_worktree_to_main",
        lambda *_args, **_kwargs: {
            "ok": True, "commits_merged": 1, "branch": session.branch,
            "merged_commits": {},
        },
    )
    monkeypatch.setattr(
        "app.workspace.switch_worktree_branch",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("simulated switch crash")
        ),
    )

    result = await sessmod.merge_session(
        "worker", {"scope": "/s", "next_task_id": "43"},
    )

    assert result["ok"] is True
    assert result["switch"]["ok"] is False
    assert "simulated switch crash" in result["switch"]["error"]
    assert result["task_status"]["ok"] is False
    with tm._conn() as conn:
        assert tm.get_task_by_id(conn, task["id"])["status"] == "new"
    row = get_session(session.id)
    assert (row["task_id"], row["needs_switch"], row["branch"]) == (
        "", 1, session.branch,
    )


@pytest.mark.asyncio
async def test_merge_quarantine_persistence_retries_before_returning(
    db, monkeypatch,
):
    import app.main as mainmod
    import app.routes.sessions as sessmod
    from app.db import get_session

    session = type("Session", (), {
        "loaded": False,
        "status": type("Status", (), {"value": "idle"})(),
        "worktree_path": "/wt",
        "scope": "/s",
        "id": "quarantine-retry",
        "name": "worker",
        "branch": "task-42/worker",
        "base_branch": "main",
    })()
    local_manager = _prepare_detached_merge(monkeypatch, session)
    persist_calls = 0

    async def fail_once(found, **fields):
        nonlocal persist_calls
        persist_calls += 1
        if persist_calls == 1:
            raise RuntimeError("transient DB failure")
        await local_manager.persist_lifecycle(found, **fields)

    monkeypatch.setattr(mainmod.manager, "persist_lifecycle", fail_once)
    monkeypatch.setattr(
        "app.workspace.merge_worktree_to_main",
        lambda *_args, **_kwargs: {
            "ok": True, "commits_merged": 1, "branch": session.branch,
            "merged_commits": {},
        },
    )

    result = await sessmod.merge_session("worker", {"scope": "/s"})

    assert result["ok"] is True
    assert result["lifecycle_status"] == {
        "ok": True, "recovered": True, "warning": "transient DB failure",
    }
    assert persist_calls == 2
    row = get_session(session.id)
    assert (row["task_id"], row["needs_switch"], row["branch"]) == (
        "", 1, session.branch,
    )


@pytest.mark.asyncio
async def test_merge_switch_persistence_failure_is_partial_and_keeps_task_unchanged(
    db, monkeypatch,
):
    import app.main as mainmod
    import app.routes.sessions as sessmod
    from app import tm
    from app.db import get_session

    with tm._conn() as conn:
        tm.ensure_project(conn, "project", scope="/s")
        task = tm.create_task(conn, "project", "next", par_number=43)
    session = type("Session", (), {
        "loaded": False,
        "status": type("Status", (), {"value": "idle"})(),
        "worktree_path": "/wt",
        "scope": "/s",
        "id": "switch-persist-failure",
        "name": "worker",
        "branch": "task-42/worker",
        "base_branch": "main",
    })()
    local_manager = _prepare_detached_merge(monkeypatch, session)
    persist_calls = 0

    async def fail_switched_persistence(found, **fields):
        nonlocal persist_calls
        persist_calls += 1
        if persist_calls > 1:
            raise RuntimeError("session DB unavailable")
        await local_manager.persist_lifecycle(found, **fields)

    monkeypatch.setattr(mainmod.manager, "persist_lifecycle", fail_switched_persistence)
    monkeypatch.setattr(
        "app.workspace.merge_worktree_to_main",
        lambda *_args, **_kwargs: {
            "ok": True, "commits_merged": 1, "branch": session.branch,
            "merged_commits": {},
        },
    )
    monkeypatch.setattr(
        "app.workspace.switch_worktree_branch",
        lambda *_args, **_kwargs: {"ok": True, "branch": "task-43/worker"},
    )

    result = await sessmod.merge_session(
        "worker", {"scope": "/s", "next_task_id": "43"},
    )

    assert result["ok"] is True
    assert result["switch"]["ok"] is False
    assert result["switch"]["state"] == "persistence_failed"
    assert "branch switched to task-43/worker" in result["switch"]["error"]
    assert result["task_status"]["ok"] is False
    with tm._conn() as conn:
        assert tm.get_task_by_id(conn, task["id"])["status"] == "new"
    row = get_session(session.id)
    assert (row["task_id"], row["needs_switch"], row["branch"]) == (
        "", 1, session.branch,
    )


@pytest.mark.asyncio
async def test_merge_task_db_exception_is_explicit_without_reversing_git_success(
    db, monkeypatch,
):
    import app.routes.sessions as sessmod
    from app import tm
    from app.db import get_session

    with tm._conn() as conn:
        tm.ensure_project(conn, "project", scope="/s")
        tm.create_task(conn, "project", "next", par_number=43)
    session = type("Session", (), {
        "loaded": False,
        "status": type("Status", (), {"value": "idle"})(),
        "worktree_path": "/wt",
        "scope": "/s",
        "id": "task-db-failure",
        "name": "worker",
        "branch": "task-42/worker",
        "base_branch": "main",
    })()
    _prepare_detached_merge(monkeypatch, session)
    monkeypatch.setattr(
        "app.workspace.merge_worktree_to_main",
        lambda *_args, **_kwargs: {
            "ok": True, "commits_merged": 1, "branch": session.branch,
            "merged_commits": {},
        },
    )
    monkeypatch.setattr(
        "app.workspace.switch_worktree_branch",
        lambda *_args, **_kwargs: {"ok": True, "branch": "task-43/worker"},
    )
    monkeypatch.setattr(
        tm,
        "api_update_task_if_current",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError()),
    )

    result = await sessmod.merge_session(
        "worker", {"scope": "/s", "next_task_id": "43"},
    )

    assert result["ok"] is True
    assert result["switch"]["ok"] is True
    assert result["task_status"] == {
        "ok": False, "error": "RuntimeError", "quarantined": True,
    }
    row = get_session(session.id)
    assert (row["task_id"], row["needs_switch"], row["branch"]) == (
        "", 1, "task-43/worker",
    )


@pytest.mark.asyncio
async def test_wip_uses_persisted_base(monkeypatch):
    import app.main as mainmod
    import app.routes.sessions as sessmod

    session = type("Session", (), {
        "worktree_path": "/wt",
        "base_branch": "master",
        "to_dict": lambda self: {"context_pct": 0, "status": "idle"},
    })()
    captured = {}

    def fake_wip(_path, base_ref=""):
        captured["base_ref"] = base_ref
        return {"uncommitted": [], "unmerged_commits": []}

    monkeypatch.setattr(mainmod.manager, "get_by_name", lambda *_args: session)
    monkeypatch.setattr(sessmod, "_session_base_branch", lambda *_args: "master")
    monkeypatch.setattr("app.workspace.branch_wip_status", fake_wip)

    result = await sessmod.session_wip("w", scope="/s")

    assert captured["base_ref"] == "master"
    assert not result.get("error")


@pytest.mark.asyncio
async def test_kill_guard_compares_against_persisted_base(tmp_path, monkeypatch):
    import app.main as mainmod
    import app.routes.sessions as sessmod
    from unittest.mock import AsyncMock

    wt = tmp_path / "wt"
    wt.mkdir()
    session = type("Session", (), {
        "id": "sid",
        "loaded": False,
        "status": type("Status", (), {"value": "idle"})(),
        "scope": "/s",
        "worktree_path": str(wt),
        "base_branch": "master",
    })()
    captured = {}

    class Proc:
        returncode = 0

        def __init__(self, stdout=b""):
            self.stdout = stdout

        async def communicate(self):
            return self.stdout, b""

    async def fake_subprocess(*args, **_kwargs):
        return Proc(b"")

    def fake_content_status(path, base_ref):
        captured.update(path=path, base_ref=base_ref)
        return {
            "base_ref": base_ref,
            "commits_ahead": 0,
            "content_merged": True,
            "reason": "ancestor",
        }

    monkeypatch.setattr(mainmod.manager, "get_by_name", lambda *_args: session)
    monkeypatch.setattr(mainmod.manager, "_live_children", lambda *_args: [])
    monkeypatch.setattr(mainmod.manager, "remove", AsyncMock())
    monkeypatch.setattr(sessmod, "_session_base_branch", lambda *_args: "master")
    monkeypatch.setattr(sessmod.asyncio, "create_subprocess_exec", fake_subprocess)
    monkeypatch.setattr("app.workspace.branch_content_status", fake_content_status)

    result = await sessmod.delete_session("w", scope="/s")

    assert result == {"ok": True}
    assert captured == {"path": str(wt), "base_ref": "master"}


def _create_delete_guard_repo(tmp_path, name):
    repo = tmp_path / name
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    (repo / "base.txt").write_text("base\n")
    subprocess.run(["git", "add", "base.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "base"], cwd=repo, check=True)
    subprocess.run(["git", "branch", "-M", "main"], cwd=repo, check=True)
    wt = tmp_path / f"{name}-wt"
    branch = f"{name}-worker"
    subprocess.run(
        ["git", "worktree", "add", "-b", branch, str(wt), "main"],
        cwd=repo,
        check=True,
    )
    return repo, wt, branch


@pytest.mark.asyncio
async def test_kill_allows_squash_merged_content_after_base_advances(
    tmp_path, monkeypatch,
):
    import app.main as mainmod
    import app.routes.sessions as sessmod

    repo, wt, branch = _create_delete_guard_repo(tmp_path, "squash-delete")
    (wt / "one.txt").write_text("one\n")
    subprocess.run(["git", "add", "one.txt"], cwd=wt, check=True)
    subprocess.run(["git", "commit", "-m", "worker one"], cwd=wt, check=True)
    (wt / "two.txt").write_text("two\n")
    subprocess.run(["git", "add", "two.txt"], cwd=wt, check=True)
    subprocess.run(["git", "commit", "-m", "worker two"], cwd=wt, check=True)
    subprocess.run(["git", "merge", "--squash", branch], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "squash worker"], cwd=repo, check=True)
    (repo / "base-only.txt").write_text("later\n")
    subprocess.run(["git", "add", "base-only.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "advance base"], cwd=repo, check=True)

    session = type("Session", (), {
        "id": "sid",
        "loaded": False,
        "status": type("Status", (), {"value": "idle"})(),
        "scope": "/s",
        "worktree_path": str(wt),
        "base_branch": "main",
    })()
    remove = AsyncMock()
    monkeypatch.setattr(mainmod.manager, "get_by_name", lambda *_args: session)
    monkeypatch.setattr(mainmod.manager, "_live_children", lambda *_args: [])
    monkeypatch.setattr(mainmod.manager, "remove", remove)

    result = await sessmod.delete_session("w", scope="/s")

    assert result == {"ok": True}
    remove.assert_awaited_once_with("sid")


@pytest.mark.asyncio
async def test_kill_blocks_real_unmerged_content(tmp_path, monkeypatch):
    import app.main as mainmod
    import app.routes.sessions as sessmod

    _repo, wt, _branch = _create_delete_guard_repo(tmp_path, "unmerged-delete")
    (wt / "worker-only.txt").write_text("must survive\n")
    subprocess.run(["git", "add", "worker-only.txt"], cwd=wt, check=True)
    subprocess.run(["git", "commit", "-m", "worker only"], cwd=wt, check=True)
    head_before = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=wt,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    session = type("Session", (), {
        "id": "sid",
        "loaded": False,
        "status": type("Status", (), {"value": "idle"})(),
        "scope": "/s",
        "worktree_path": str(wt),
        "base_branch": "main",
    })()
    remove = AsyncMock()
    monkeypatch.setattr(mainmod.manager, "get_by_name", lambda *_args: session)
    monkeypatch.setattr(mainmod.manager, "_live_children", lambda *_args: [])
    monkeypatch.setattr(mainmod.manager, "remove", remove)

    response = await sessmod.delete_session("w", scope="/s")

    assert response.status_code == 400
    assert "content-change" in response.body.decode()
    remove.assert_not_awaited()
    assert subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=wt,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip() == head_before


@pytest.mark.asyncio
async def test_kill_blocks_content_detector_error(tmp_path, monkeypatch):
    import app.main as mainmod
    import app.routes.sessions as sessmod

    wt = tmp_path / "wt"
    wt.mkdir()
    session = type("Session", (), {
        "id": "sid",
        "loaded": False,
        "status": type("Status", (), {"value": "idle"})(),
        "scope": "/s",
        "worktree_path": str(wt),
        "base_branch": "main",
    })()

    class Proc:
        returncode = 0

        async def communicate(self):
            return b"", b""

    async def clean_status(*_args, **_kwargs):
        return Proc()

    remove = AsyncMock()
    monkeypatch.setattr(mainmod.manager, "get_by_name", lambda *_args: session)
    monkeypatch.setattr(mainmod.manager, "_live_children", lambda *_args: [])
    monkeypatch.setattr(mainmod.manager, "remove", remove)
    monkeypatch.setattr(sessmod, "_session_base_branch", lambda *_args: "main")
    monkeypatch.setattr(sessmod.asyncio, "create_subprocess_exec", clean_status)
    monkeypatch.setattr(
        "app.workspace.branch_content_status",
        lambda *_args: {"error": "detector exploded"},
    )

    response = await sessmod.delete_session("w", scope="/s")

    assert response.status_code == 400
    assert "detector exploded" in response.body.decode()
    remove.assert_not_awaited()


@pytest.mark.asyncio
async def test_kill_reports_worktree_remove_failure(monkeypatch):
    import app.main as mainmod
    import app.routes.sessions as sessmod
    from unittest.mock import AsyncMock

    session = type("Session", (), {"id": "sid"})()
    monkeypatch.setattr(mainmod.manager, "get_by_name", lambda *_args: session)
    monkeypatch.setattr(
        mainmod.manager,
        "remove",
        AsyncMock(side_effect=RuntimeError("git worktree remove failed: locked")),
    )

    response = await sessmod.delete_session("w", scope="/s", force=True)

    assert response.status_code == 500
    assert "git worktree remove failed: locked" in response.body.decode()


@pytest.mark.asyncio
async def test_delete_orchestrator_reports_worktree_remove_failure(monkeypatch):
    import app.routes.system as sysmod
    from unittest.mock import AsyncMock

    monkeypatch.setattr(
        sysmod.manager,
        "remove_scope",
        AsyncMock(side_effect=RuntimeError("git worktree remove failed: locked")),
    )

    response = await sysmod.delete_orchestrator("orch", scope="/s")

    assert response.status_code == 500
    assert "git worktree remove failed: locked" in response.body.decode()


@pytest.mark.asyncio
async def test_send_delegates_auto_switch_to_manager(monkeypatch):
    import app.main as mainmod
    import app.routes.sessions as sessmod
    from unittest.mock import AsyncMock

    session = type("Session", (), {
        "id": "sid",
        "name": "w",
        "cwd": "/wt",
        "worktree_path": "/wt",
        "branch": "task-90/w",
        "base_branch": "master",
        "task_id": "",
        "needs_switch": True,
        "parent_name": "orch",
    })()
    monkeypatch.setattr(mainmod.manager, "ensure_loaded", AsyncMock(return_value=session))
    monkeypatch.setattr(mainmod.manager, "send", AsyncMock())

    result = await sessmod.send_message(
        "w", sessmod.SendRequest(message="next", scope="/s"),
    )

    assert result["ok"] is True
    mainmod.manager.send.assert_awaited_once()
    delivered_to, delivered_message = mainmod.manager.send.await_args.args
    assert delivered_to == "sid"
    assert delivered_message.endswith("next")


@pytest.mark.asyncio
@pytest.mark.parametrize("force", [False, True])
async def test_switch_uses_persisted_base_when_from_ref_is_omitted(monkeypatch, force):
    import app.main as mainmod
    import app.routes.sessions as sessmod

    session = type("Session", (), {
        "id": "sid",
        "name": "w",
        "scope": "/s",
        "loaded": False,
        "status": type("Status", (), {"value": "idle"})(),
        "worktree_path": "/wt",
        "base_branch": "master",
    })()
    captured = {}

    # **kwargs: маршрут передаёт ещё recreate_from_base (#61); дубль сигнатуры в моке
    # ломался бы на каждом новом параметре, не проверяя ничего по существу.
    def fake_switch(_wt, new_branch, from_ref="", force=False, **kwargs):
        captured.update(new_branch=new_branch, from_ref=from_ref, force=force)
        return {"ok": True, "branch": new_branch}

    async def persist_lifecycle(found, **fields):
        for key, value in fields.items():
            setattr(found, key, value)

    monkeypatch.setattr(mainmod.manager, "get_by_name", lambda *_args: session)
    monkeypatch.setattr(mainmod.manager, "persist_lifecycle", persist_lifecycle)
    monkeypatch.setattr(sessmod, "_session_base_branch", lambda *_args: "master")
    monkeypatch.setattr("app.workspace.switch_worktree_branch", fake_switch)
    monkeypatch.setattr(
        "app.tm.resolve_scoped_task_identity",
        lambda *_args: {"id": 91, "project_id": "project", "par_number": 91,
                       "sync_revision": 0},
    )
    monkeypatch.setattr(
        "app.tm.api_update_task_if_current",
        lambda *_args, **_kwargs: {"ok": True},
    )

    result = await sessmod.switch_branch(
        "w", {"scope": "/s", "task_id": "91", "force": force},
    )

    assert result["ok"] is True
    assert captured["from_ref"] == "master"
    assert captured["force"] is force
    assert session.base_branch == "master"
    assert session.branch == "task-91/w"


@pytest.mark.asyncio
async def test_switch_updates_duplicate_task_number_only_in_session_project(db, monkeypatch):
    import app.main as mainmod
    import app.routes.sessions as sessmod
    from app import tm
    from app.manager import SessionManager

    with tm._conn() as conn:
        tm.ensure_project(conn, "project-a", scope="/a")
        tm.ensure_project(conn, "project-b", scope="/b")
        task_a = tm.create_task(conn, "project-a", "A", par_number=91)
        task_b = tm.create_task(conn, "project-b", "B", par_number=91)
    session = type("Session", (), {
        "id": "scoped-switch",
        "name": "w",
        "scope": "/b",
        "loaded": False,
        "status": type("Status", (), {"value": "idle"})(),
        "worktree_path": "/wt",
        "branch": "task-90/w",
        "base_branch": "main",
        "task_id": "90",
    })()
    _save_merge_session_record(session)
    local_manager = SessionManager()
    found = local_manager.get_by_name("w", "/b")
    monkeypatch.setattr(mainmod.manager, "get_by_name", lambda *_args: found)
    monkeypatch.setattr(
        mainmod.manager, "get_session_lock", local_manager.get_session_lock,
    )
    monkeypatch.setattr(
        mainmod.manager, "persist_lifecycle", local_manager.persist_lifecycle,
    )
    monkeypatch.setattr(sessmod, "_session_base_branch", lambda *_args: "main")
    monkeypatch.setattr(
        "app.workspace.switch_worktree_branch",
        lambda *_args, **_kwargs: {"ok": True, "branch": "task-91/w"},
    )

    result = await sessmod.switch_branch(
        "w", {"scope": "/b", "task_id": "91", "force": True},
    )

    assert result["ok"] is True
    assert result["task_status"]["ok"] is True
    with tm._conn() as conn:
        assert tm.get_task_by_id(conn, task_a["id"])["status"] == "new"
        assert tm.get_task_by_id(conn, task_b["id"])["status"] == "in_progress"


@pytest.mark.asyncio
async def test_switch_persistence_failure_quarantines_and_does_not_update_task(
    db, monkeypatch,
):
    import app.main as mainmod
    import app.routes.sessions as sessmod
    from app.db import get_session, save_session
    from app.manager import SessionManager
    from datetime import datetime, timezone

    save_session({
        "id": "switch-persist-failure", "name": "w", "scope": "/s",
        "cwd": "/wt", "model": "claude-sonnet-5[1m]", "system_prompt": "",
        "status": "idle", "session_id": None, "cost_usd": 0.0,
        "worktree_path": "/wt", "branch": "task-90/w", "base_branch": "main",
        "needs_switch": 0, "task_id": "90", "is_orchestrator": False,
        "color": "", "created_at": datetime.now(timezone.utc).isoformat(),
        "finished_at": None,
    })
    local_manager = SessionManager()
    found = local_manager.get_by_name("w", "/s")
    real_persist = local_manager.persist_lifecycle
    persist_calls = 0

    async def fail_assigned_lifecycle(session, **fields):
        nonlocal persist_calls
        persist_calls += 1
        if persist_calls == 2:
            raise RuntimeError("simulated lifecycle write failure")
        await real_persist(session, **fields)

    task_update = MagicMock()
    monkeypatch.setattr(mainmod.manager, "get_by_name", lambda *_args: found)
    monkeypatch.setattr(
        mainmod.manager, "get_session_lock", local_manager.get_session_lock,
    )
    monkeypatch.setattr(
        mainmod.manager, "persist_lifecycle", fail_assigned_lifecycle,
    )
    monkeypatch.setattr(sessmod, "_session_base_branch", lambda *_args: "main")
    monkeypatch.setattr(
        "app.workspace.switch_worktree_branch",
        lambda *_args, **_kwargs: {"ok": True, "branch": "task-91/w"},
    )
    monkeypatch.setattr(
        "app.tm.resolve_scoped_task_identity",
        lambda *_args: {"id": 91, "project_id": "project", "par_number": 91,
                       "sync_revision": 0},
    )
    monkeypatch.setattr("app.tm.api_update_task_if_current", task_update)

    result = await sessmod.switch_branch(
        "w", {"scope": "/s", "task_id": "91", "force": True},
    )

    assert result["ok"] is False
    assert result["state"] == "persistence_failed"
    assert "simulated lifecycle write failure" in result["error"]
    assert result["task_status"]["ok"] is False
    row = get_session("switch-persist-failure")
    assert (row["branch"], row["task_id"], row["needs_switch"]) == (
        "task-91/w", "", 1,
    )
    task_update.assert_not_called()


@pytest.mark.asyncio
async def test_switch_task_cas_failure_requarantines_new_branch(db, monkeypatch):
    import app.main as mainmod
    import app.routes.sessions as sessmod
    from app.db import get_session, save_session
    from app.manager import SessionManager
    from datetime import datetime, timezone

    save_session({
        "id": "switch-task-cas-failure", "name": "w", "scope": "/s",
        "cwd": "/wt", "model": "claude-sonnet-5[1m]", "system_prompt": "",
        "status": "idle", "session_id": None, "cost_usd": 0.0,
        "worktree_path": "/wt", "branch": "task-90/w", "base_branch": "main",
        "needs_switch": 0, "task_id": "90", "is_orchestrator": False,
        "color": "", "created_at": datetime.now(timezone.utc).isoformat(),
        "finished_at": None,
    })
    local_manager = SessionManager()
    found = local_manager.get_by_name("w", "/s")
    monkeypatch.setattr(mainmod.manager, "get_by_name", lambda *_args: found)
    monkeypatch.setattr(
        mainmod.manager, "get_session_lock", local_manager.get_session_lock,
    )
    monkeypatch.setattr(
        mainmod.manager, "persist_lifecycle", local_manager.persist_lifecycle,
    )
    monkeypatch.setattr(sessmod, "_session_base_branch", lambda *_args: "main")
    monkeypatch.setattr(
        "app.workspace.switch_worktree_branch",
        lambda *_args, **_kwargs: {"ok": True, "branch": "task-91/w"},
    )
    monkeypatch.setattr(
        "app.tm.resolve_scoped_task_identity",
        lambda *_args: {"id": 91, "project_id": "project", "par_number": 91,
                       "sync_revision": 0},
    )
    monkeypatch.setattr(
        "app.tm.api_update_task_if_current",
        lambda *_args, **_kwargs: {
            "ok": False, "error": "task revision changed from 0 to 1",
        },
    )

    result = await sessmod.switch_branch(
        "w", {"scope": "/s", "task_id": "91", "force": True},
    )

    assert result["ok"] is False
    assert result["state"] == "task_assignment_failed"
    assert result["task_status"]["quarantined"] is True
    row = get_session("switch-task-cas-failure")
    assert (row["branch"], row["task_id"], row["needs_switch"]) == (
        "task-91/w", "", 1,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("stored_base_branch", ["master", ""])
async def test_switch_failure_restores_previous_lifecycle_and_does_not_update_task(
    db, monkeypatch, stored_base_branch,
):
    import app.main as mainmod
    import app.routes.sessions as sessmod
    from app.db import get_session, save_session
    from app.manager import SessionManager
    from datetime import datetime, timezone

    save_session({
        "id": "switch-normal-failure", "name": "w", "scope": "/s",
        "cwd": "/wt", "model": "claude-sonnet-5[1m]", "system_prompt": "",
        "status": "idle", "session_id": None, "cost_usd": 0.0,
        "worktree_path": "/wt", "branch": "task-90/w",
        "base_branch": stored_base_branch,
        "needs_switch": 0, "task_id": "90", "is_orchestrator": False,
        "color": "", "created_at": datetime.now(timezone.utc).isoformat(),
        "finished_at": None,
    })
    local_manager = SessionManager()
    found = local_manager.get_by_name("w", "/s")
    task_update = MagicMock()
    monkeypatch.setattr(mainmod.manager, "get_by_name", lambda *_args: found)
    monkeypatch.setattr(mainmod.manager, "get_session_lock", local_manager.get_session_lock)
    monkeypatch.setattr(mainmod.manager, "persist_lifecycle", local_manager.persist_lifecycle)
    monkeypatch.setattr(sessmod, "_session_base_branch", lambda *_args: "master")
    monkeypatch.setattr(
        "app.workspace.switch_worktree_branch",
        lambda *_args, **_kwargs: {"ok": False, "error": "target busy"},
    )
    monkeypatch.setattr(
        "app.tm.resolve_scoped_task_identity",
        lambda *_args: {"id": 91, "project_id": "project", "par_number": 91,
                       "sync_revision": 0},
    )
    monkeypatch.setattr("app.tm.api_update_task_if_current", task_update)

    result = await sessmod.switch_branch(
        "w", {"scope": "/s", "task_id": "91", "force": True},
    )

    # waited_seconds добавлено в #27 намеренно: ожидание лока обязано быть видно и в отказе.
    assert result["ok"] is False and result["error"] == "target busy"
    assert "waited_seconds" in result
    row = get_session("switch-normal-failure")
    assert (row["branch"], row["base_branch"], row["task_id"], row["needs_switch"]) == (
        "task-90/w", stored_base_branch, "90", 0,
    )
    task_update.assert_not_called()


@pytest.mark.asyncio
async def test_switch_rollback_failure_persists_quarantine_for_detached_reload(
    db, monkeypatch,
):
    import app.main as mainmod
    import app.routes.sessions as sessmod
    from app.db import get_session, save_session
    from app.manager import SessionManager
    from datetime import datetime, timezone

    save_session({
        "id": "switch-rollback-failure", "name": "w", "scope": "/s",
        "cwd": "/wt", "model": "claude-sonnet-5[1m]", "system_prompt": "",
        "status": "idle", "session_id": None, "cost_usd": 0.0,
        "worktree_path": "/wt", "branch": "task-90/w", "base_branch": "master",
        "needs_switch": 0, "task_id": "90", "is_orchestrator": False,
        "color": "", "created_at": datetime.now(timezone.utc).isoformat(),
        "finished_at": None,
    })
    local_manager = SessionManager()
    found = local_manager.get_by_name("w", "/s")
    task_update = MagicMock()
    monkeypatch.setattr(mainmod.manager, "get_by_name", lambda *_args: found)
    monkeypatch.setattr(mainmod.manager, "get_session_lock", local_manager.get_session_lock)
    monkeypatch.setattr(mainmod.manager, "persist_lifecycle", local_manager.persist_lifecycle)
    monkeypatch.setattr(sessmod, "_session_base_branch", lambda *_args: "master")
    monkeypatch.setattr(
        "app.workspace.switch_worktree_branch",
        lambda *_args, **_kwargs: {
            "ok": False,
            "state": "rollback_failed",
            "error": "checkout failed; rollback failed",
            "actual_branch": "task-91/w",
            "actual_head": "deadbeef",
        },
    )
    monkeypatch.setattr(
        "app.tm.resolve_scoped_task_identity",
        lambda *_args: {"id": 91, "project_id": "project", "par_number": 91,
                       "sync_revision": 0},
    )
    monkeypatch.setattr("app.tm.api_update_task_if_current", task_update)

    result = await sessmod.switch_branch(
        "w", {"scope": "/s", "task_id": "91", "force": True},
    )

    assert result["state"] == "rollback_failed"
    row = get_session("switch-rollback-failure")
    assert (row["branch"], row["task_id"], row["needs_switch"]) == (
        "task-91/w", "", 1,
    )
    reloaded = SessionManager().get_by_name("w", "/s")
    assert reloaded.branch == "task-91/w"
    assert reloaded.task_id == ""
    assert reloaded.needs_switch is True
    task_update.assert_not_called()


@pytest.mark.asyncio
async def test_switch_rejects_non_boolean_force():
    import app.routes.sessions as sessmod

    response = await sessmod.switch_branch(
        "w", {"scope": "/s", "task_id": "91", "force": "true"},
    )

    assert response.status_code == 400
    assert "force must be a boolean" in response.body.decode()


@pytest.mark.asyncio
async def test_merge_waits_for_running_worker_to_finish_turn(db, monkeypatch):
    import asyncio
    import app.main as mainmod
    import app.routes.sessions as sessmod

    class Status:
        value = "running"

    class FakeSession:
        loaded = True
        status = Status()
        _lifecycle_lock = asyncio.Lock()
        worktree_path = "/wt"
        scope = "/s"
        id = "merge-finish"
        name = "w"
        branch = "task-90/w"
        base_branch = "master"

        async def wait_for_turn_completion(self):
            wait_started.set()
            await turn_finished.wait()
            return self.status.value == "idle"

        async def interrupt(self):
            raise AssertionError("merge must not interrupt the worker")

    session = FakeSession()
    _save_merge_session_record(session)
    merge_called = False
    wait_started = asyncio.Event()
    turn_finished = asyncio.Event()

    def fake_merge(*_args, **_kwargs):
        nonlocal merge_called
        merge_called = True
        return {"ok": True, "merged_commits": {}}

    monkeypatch.setattr("app.workspace.merge_worktree_to_main", fake_merge)
    monkeypatch.setattr(mainmod.manager, "get_by_name", lambda name, scope: session)
    monkeypatch.setattr(mainmod.manager, "get", lambda _session_id: session)
    monkeypatch.setattr(
        "app.workspace.inspect_worktree_identity",
        lambda _path: (session.branch, "a" * 40),
    )
    monkeypatch.setattr(sessmod, "_session_base_branch", lambda *_args: "master")

    async def persist_lifecycle(_session, **_fields):
        return None

    monkeypatch.setattr(mainmod.manager, "persist_lifecycle", persist_lifecycle)

    merge_task = asyncio.create_task(
        sessmod.merge_session("w", {"scope": "/s"}),
    )
    await asyncio.wait_for(wait_started.wait(), timeout=0.2)
    assert merge_called is False
    assert merge_task.done() is False

    session.status.value = "idle"
    turn_finished.set()
    result = await asyncio.wait_for(merge_task, timeout=0.2)

    assert result["ok"] is True
    assert merge_called is True


@pytest.mark.asyncio
async def test_merge_rejects_waiting_worker_without_merging(db, monkeypatch):
    import asyncio
    import app.main as mainmod
    import app.routes.sessions as sessmod

    class Status:
        value = "waiting"

    class FakeSession:
        loaded = True
        status = Status()
        _lifecycle_lock = asyncio.Lock()
        worktree_path = "/wt"
        scope = "/s"
        id = "merge-running"
        name = "w"
        branch = "task-90/w"
        base_branch = "master"

    session = FakeSession()
    _save_merge_session_record(session)
    merge_called = False

    def fake_merge(*_args, **_kwargs):
        nonlocal merge_called
        merge_called = True
        return {"ok": True, "merged_commits": {}}

    monkeypatch.setattr("app.workspace.merge_worktree_to_main", fake_merge)
    monkeypatch.setattr(mainmod.manager, "get_by_name", lambda name, scope: session)
    monkeypatch.setattr(mainmod.manager, "get", lambda _session_id: session)
    monkeypatch.setattr(
        "app.workspace.inspect_worktree_identity",
        lambda _path: (session.branch, "a" * 40),
    )
    monkeypatch.setattr(sessmod, "_session_base_branch", lambda *_args: "master")

    response = await sessmod.merge_session("w", {"scope": "/s"})

    assert response.status_code == 400
    assert "waiting" in response.body.decode()
    assert merge_called is False


@pytest.mark.asyncio
async def test_switch_waits_for_running_worker_to_finish_turn(db, monkeypatch):
    import asyncio
    import app.main as mainmod
    import app.routes.sessions as sessmod

    class Status:
        value = "running"

    class FakeSession:
        loaded = True
        status = Status()
        worktree_path = "/wt"
        scope = "/s"
        id = "switch-finish"
        name = "w"
        base_branch = "main"
        _lifecycle_lock = asyncio.Lock()

        async def wait_for_turn_completion(self):
            wait_started.set()
            await turn_finished.wait()
            return self.status.value == "idle"

        async def interrupt(self):
            raise AssertionError("switch must not interrupt the worker")

    session = FakeSession()
    wait_started = asyncio.Event()
    turn_finished = asyncio.Event()
    switch_called = False

    def fake_switch(*_args, **_kwargs):
        nonlocal switch_called
        switch_called = True
        return {"ok": True, "branch": "task-91/w"}

    async def persist_lifecycle(found, **fields):
        for key, value in fields.items():
            setattr(found, key, value)

    monkeypatch.setattr(mainmod.manager, "get_by_name", lambda *_args: session)
    monkeypatch.setattr(mainmod.manager, "persist_lifecycle", persist_lifecycle)
    monkeypatch.setattr(sessmod, "_session_base_branch", lambda *_args: "main")
    monkeypatch.setattr("app.workspace.switch_worktree_branch", fake_switch)
    monkeypatch.setattr(
        "app.tm.resolve_scoped_task_identity",
        lambda *_args: {"id": 91, "project_id": "project", "par_number": 91,
                       "sync_revision": 0},
    )
    monkeypatch.setattr(
        "app.tm.api_update_task_if_current",
        lambda *_args, **_kwargs: {"ok": True},
    )

    switch_task = asyncio.create_task(
        sessmod.switch_branch("w", {"scope": "/s", "task_id": "91"}),
    )
    await asyncio.wait_for(wait_started.wait(), timeout=0.2)
    assert switch_called is False
    assert switch_task.done() is False

    interrupt_status_published = asyncio.Event()
    interrupt_ack = asyncio.Event()

    async def finish_interrupt():
        async with session._lifecycle_lock:
            session.status.value = "idle"
            turn_finished.set()
            interrupt_status_published.set()
            await interrupt_ack.wait()

    interrupt_task = asyncio.create_task(finish_interrupt())
    await asyncio.wait_for(interrupt_status_published.wait(), timeout=0.2)
    await asyncio.sleep(0)
    assert switch_called is False
    assert switch_task.done() is False

    interrupt_ack.set()
    await asyncio.wait_for(interrupt_task, timeout=0.2)
    result = await asyncio.wait_for(switch_task, timeout=0.2)

    assert result["ok"] is True
    assert switch_called is True


@pytest.mark.asyncio
async def test_merge_and_switch_hold_lifecycle_lock_against_worker_wakeup(db, monkeypatch):
    import asyncio
    import threading
    import app.main as mainmod
    import app.routes.sessions as sessmod

    observed = {"persist_locked": []}

    class Status:
        value = "idle"

    class FakeSession:
        loaded = True
        status = Status()
        _lifecycle_lock = asyncio.Lock()
        worktree_path = "/wt"
        scope = "/s"
        id = "merge-switch-lock"
        name = "w"
        branch = "task-42/w"
        base_branch = "main"

        def _persist(self):
            observed["persist_locked"].append(self._lifecycle_lock.locked())

    session = FakeSession()
    _save_merge_session_record(session)
    from app import tm
    with tm._conn() as conn:
        tm.ensure_project(conn, "project", scope="/s")
        tm.create_task(conn, "project", "next", par_number=43)
    loop = asyncio.get_running_loop()
    wake_attempted = threading.Event()
    wake_entered = asyncio.Event()

    async def wake_worker():
        wake_attempted.set()
        async with session._lifecycle_lock:
            wake_entered.set()

    def fake_merge(*_args, **_kwargs):
        observed["merge_locked"] = session._lifecycle_lock.locked()
        loop.call_soon_threadsafe(lambda: asyncio.create_task(wake_worker()))
        assert wake_attempted.wait(1)
        return {"ok": True, "merged_commits": {}}

    def fake_switch(*_args, **_kwargs):
        observed["switch_locked"] = session._lifecycle_lock.locked()
        observed["wake_blocked_during_switch"] = not wake_entered.is_set()
        return {"ok": True, "branch": "task-43/w"}

    async def persist_lifecycle(found, **fields):
        observed["persist_locked"].append(found._lifecycle_lock.locked())
        for key, value in fields.items():
            setattr(found, key, value)

    monkeypatch.setattr("app.workspace.merge_worktree_to_main", fake_merge)
    monkeypatch.setattr("app.workspace.switch_worktree_branch", fake_switch)
    monkeypatch.setattr("app.rag_service.is_enabled", lambda: False)
    monkeypatch.setattr(mainmod.manager, "get_by_name", lambda name, scope: session)
    monkeypatch.setattr(mainmod.manager, "get", lambda _session_id: session)
    monkeypatch.setattr(
        "app.workspace.inspect_worktree_identity",
        lambda _path: (session.branch, "a" * 40),
    )
    monkeypatch.setattr(mainmod.manager, "persist_lifecycle", persist_lifecycle)
    monkeypatch.setattr(
        sessmod, "_session_base_branch",
        lambda _session, requested="": requested or "master",
    )

    result = await sessmod.merge_session("w", {
        "scope": "/s",
        "target": "main",
        "next_task_id": "43",
    })
    await asyncio.wait_for(wake_entered.wait(), timeout=1)

    assert result["switch"]["ok"] is True
    assert observed["merge_locked"] is True
    assert observed["switch_locked"] is True
    assert observed["wake_blocked_during_switch"] is True
    assert observed["persist_locked"] and all(observed["persist_locked"])


class TestPipelines:
    def test_list_valid_only(self, client):
        r = client.get("/api/pipelines")
        assert r.status_code == 200
        data = r.json()
        names = [p["name"] for p in data]
        assert "default" in names
        # все возвращённые — валидны (поле valid не отдаётся, но битых быть не должно)
        for p in data:
            assert "name" in p and "description" in p and "roles" in p

    def test_excludes_invalid(self, client, monkeypatch):
        import app.routes.system as sysmod
        monkeypatch.setattr(sysmod, "list_pipelines", lambda: [
            {"name": "good", "description": "d", "roles": ["pm"], "valid": True, "error": None},
            {"name": "broken", "description": "", "roles": [], "valid": False, "error": "boom"},
        ])
        r = client.get("/api/pipelines")
        names = [p["name"] for p in r.json()]
        assert "good" in names
        assert "broken" not in names


class TestProfiles:
    def test_list_contains_personal(self, client):
        r = client.get("/api/profiles")
        assert r.status_code == 200
        names = [p["name"] for p in r.json()]
        assert "personal" in names

    def test_create_and_update(self, client):
        r = client.post("/api/profiles", json={"name": "work", "config_dir": "/tmp/x"})
        assert r.status_code == 200
        g = client.get("/api/profiles").json()
        work = [p for p in g if p["name"] == "work"]
        assert len(work) == 1
        assert work[0]["config_dir"] == "/tmp/x"

        # повторный POST с другим config_dir — обновляет, не дублирует
        r2 = client.post("/api/profiles", json={"name": "work", "config_dir": "/tmp/y"})
        assert r2.status_code == 200
        g2 = client.get("/api/profiles").json()
        work2 = [p for p in g2 if p["name"] == "work"]
        assert len(work2) == 1
        assert work2[0]["config_dir"] == "/tmp/y"

    def test_create_invalid_name_400(self, client):
        r = client.post("/api/profiles", json={"name": "a b!", "config_dir": "/tmp/x"})
        assert r.status_code == 400

    def test_delete_profile(self, client):
        client.post("/api/profiles", json={"name": "work", "config_dir": "/tmp/x"})
        r = client.delete("/api/profiles/work")
        assert r.status_code == 200
        names = [p["name"] for p in client.get("/api/profiles").json()]
        assert "work" not in names

    def test_delete_personal_protected(self, client):
        r = client.delete("/api/profiles/personal")
        assert r.status_code == 409
        names = [p["name"] for p in client.get("/api/profiles").json()]
        assert "personal" in names

    # ── C1: мягкая валидация config_dir ──

    def test_create_existing_dir_no_warning(self, client, tmp_path):
        """config_dir указывает на существующую папку → 200, warning отсутствует."""
        cfg = tmp_path / "claude-cfg"
        cfg.mkdir()
        r = client.post("/api/profiles", json={"name": "work", "config_dir": str(cfg)})
        assert r.status_code == 200
        body = r.json()
        assert body["warning"] is None
        # профиль реально в списке
        g = client.get("/api/profiles").json()
        assert any(p["name"] == "work" and p["config_dir"] == str(cfg) for p in g)

    def test_create_missing_dir_warns_but_saves(self, client, tmp_path):
        """Несуществующий config_dir → 200 (НЕ ошибка), warning есть, профиль СОХРАНЁН."""
        missing = tmp_path / "does-not-exist"
        r = client.post("/api/profiles", json={"name": "work", "config_dir": str(missing)})
        assert r.status_code == 200
        body = r.json()
        assert body["warning"] is not None
        assert str(missing) in body["warning"]
        # несмотря на warning — профиль сохранён и виден в GET
        g = client.get("/api/profiles").json()
        assert any(p["name"] == "work" and p["config_dir"] == str(missing) for p in g)
        # warning-ответ содержит и сам список профилей
        assert any(p["name"] == "work" for p in body["profiles"])

    def test_create_empty_config_dir_no_warning(self, client):
        """Пустой config_dir (как у personal) → warning отсутствует."""
        r = client.post("/api/profiles", json={"name": "noenv", "config_dir": ""})
        assert r.status_code == 200
        assert r.json()["warning"] is None

    def test_create_tilde_expands_existing(self, client, tmp_path, monkeypatch):
        """C3: путь вида ``~/.claude-work`` нормализуется через expanduser.

        HOME подменяем на tmp_path и создаём реальную ``.claude-work`` —
        warning не должен появиться, что доказывает раскрытие тильды.
        """
        work = tmp_path / ".claude-work"
        work.mkdir()
        monkeypatch.setenv("HOME", str(tmp_path))
        r = client.post("/api/profiles", json={"name": "work", "config_dir": "~/.claude-work"})
        assert r.status_code == 200
        assert r.json()["warning"] is None

    def test_create_tilde_missing_warns(self, client, tmp_path, monkeypatch):
        """C3: ``~/.claude-work`` без реальной папки → warning (но сохранён as-is)."""
        monkeypatch.setenv("HOME", str(tmp_path))  # пусто, .claude-work не создаём
        r = client.post("/api/profiles", json={"name": "work", "config_dir": "~/.claude-work"})
        assert r.status_code == 200
        body = r.json()
        assert body["warning"] is not None
        # хранится исходная (нераскрытая) строка — expanduser только для проверки
        g = client.get("/api/profiles").json()
        assert any(p["config_dir"] == "~/.claude-work" for p in g)


@pytest.mark.asyncio
async def test_create_session_passes_pipeline_and_profile(monkeypatch):
    import app.main as mainmod
    import app.routes.sessions as sessmod
    import app.routes.system as sysmod
    captured = {}

    async def fake_create(**kwargs):
        captured.update(kwargs)

        class _Sess:
            def to_dict(self):
                return {"name": kwargs["name"], "id": "sid"}
        return _Sess()

    monkeypatch.setattr(mainmod.manager, "create_session", fake_create)
    monkeypatch.setattr(sysmod, "_is_safe_path", lambda p: True)

    req = sessmod.CreateSessionRequest(
        name="w1", cwd="/tmp", model="claude-sonnet-5[1m]",
        pipeline="default", profile="work",
    )
    await sessmod.create_session(req)
    assert captured["pipeline"] == "default"
    assert captured["profile"] == "work"


@pytest.mark.asyncio
async def test_create_worktree_response_contains_server_repo_metadata(
    monkeypatch, tmp_path,
):
    import subprocess

    import app.main as mainmod
    import app.routes.sessions as sessmod
    import app.routes.system as sysmod

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)
    repo_root = str(repo.resolve())
    common_dir = str((repo / ".git").resolve())

    async def fake_create(**kwargs):
        repo.rename(tmp_path / "repo-moved-after-start")

        class _Sess:
            _spawn_warning = ""
            _spawn_repo_path = repo_root
            _spawn_git_common_dir = common_dir

            def to_dict(self):
                return {
                    "name": kwargs["name"],
                    "worktree_path": "/actual/worktrees/w1",
                    "branch": "task-88/w1",
                }

        return _Sess()

    monkeypatch.setattr(mainmod.manager, "create_session", fake_create)
    monkeypatch.setattr(sysmod, "_is_safe_path", lambda p: True)

    req = sessmod.CreateSessionRequest(
        name="w1", cwd=str(repo), model="gpt-5.6-sol",
        use_worktree=True, repo_path=str(repo),
    )
    result = await sessmod.create_session(req)

    assert result["repo_path"] == repo_root
    assert result["git_common_dir"] == common_dir


class TestChangeScopeEndpoint:
    def test_success(self, client, tmp_path):
        newdir = tmp_path / "newproj"; newdir.mkdir()
        from app.main import manager
        with patch.object(manager, "change_orchestrator_scope",
                          new=AsyncMock(return_value={"ok": True, "scope": str(newdir), "cwd": str(newdir)})) as m:
            r = client.post("/api/orchestrators/orch/change-scope", json={
                "old_scope": "/tmp", "new_scope": str(newdir),
            })
        assert r.status_code == 200
        assert r.json()["ok"] is True
        # new_cwd defaults to new_scope
        m.assert_awaited_once_with("orch", "/tmp", str(newdir), str(newdir))

    def test_explicit_cwd(self, client, tmp_path):
        newdir = tmp_path / "newproj"; newdir.mkdir()
        cwddir = tmp_path / "cwddir"; cwddir.mkdir()
        from app.main import manager
        with patch.object(manager, "change_orchestrator_scope",
                          new=AsyncMock(return_value={"ok": True})) as m:
            client.post("/api/orchestrators/orch/change-scope", json={
                "old_scope": "/tmp", "new_scope": str(newdir), "new_cwd": str(cwddir),
            })
        m.assert_awaited_once_with("orch", "/tmp", str(newdir), str(cwddir))

    def test_403_unsafe_path(self, client):
        r = client.post("/api/orchestrators/orch/change-scope", json={
            "old_scope": "/tmp", "new_scope": "/etc/passwd",
        })
        assert r.status_code == 403

    def test_409_on_manager_error(self, client, tmp_path):
        newdir = tmp_path / "newproj"; newdir.mkdir()
        from app.main import manager
        with patch.object(manager, "change_orchestrator_scope",
                          new=AsyncMock(return_value={"error": "live workers in scope"})):
            r = client.post("/api/orchestrators/orch/change-scope", json={
                "old_scope": "/tmp", "new_scope": str(newdir),
            })
        assert r.status_code == 409
        assert "error" in r.json()

    def test_422_missing_fields(self, client):
        r = client.post("/api/orchestrators/orch/change-scope", json={"old_scope": "/tmp"})
        assert r.status_code == 422

    def test_403_sibling_prefix_escape(self, client, tmp_path):
        # /tmp_evil must NOT pass just because it shares the "/tmp" prefix
        from app.main import manager
        with patch.object(manager, "change_orchestrator_scope", new=AsyncMock()) as m:
            r = client.post("/api/orchestrators/orch/change-scope", json={
                "old_scope": "/tmp", "new_scope": "/tmproot_escape",
            })
        assert r.status_code == 403
        m.assert_not_awaited()


class TestDeleteOrphanGuard:
    """kill (DELETE) a parent with live children → blocked unless force."""

    def _mk(self, client, name, parent_name="", role="full-cycle"):
        body = {"name": name, "scope": "/tmp", "cwd": "/tmp",
                "model": "claude-sonnet-5[1m]", "role": role}
        if parent_name:
            # `worker` is terminal (can_spawn: []), so the parent must be a
            # fan-out role; the orphan guard itself is role-agnostic.
            body["parent_name"] = parent_name
            body["role"] = "worker"
        r = client.post("/api/sessions", json=body)
        assert r.status_code == 201, r.text

    def test_blocks_kill_with_live_child(self, client):
        self._mk(client, "par")
        self._mk(client, "kid", parent_name="par")
        r = client.delete("/api/sessions/par", params={"scope": "/tmp"})
        assert r.status_code == 400
        assert "child" in r.json()["error"]
        assert "kid" in r.json()["error"]

    def test_force_overrides(self, client):
        self._mk(client, "par2")
        self._mk(client, "kid2", parent_name="par2")
        r = client.delete("/api/sessions/par2", params={"scope": "/tmp", "force": "true"})
        assert r.status_code == 200

    def test_no_children_not_blocked(self, client):
        self._mk(client, "lonely")
        r = client.delete("/api/sessions/lonely", params={"scope": "/tmp"})
        assert r.status_code == 200
