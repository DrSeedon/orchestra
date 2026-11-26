"""Wave 33 tests: automatic & idempotent Hub worker self-cleanup."""

from __future__ import annotations

import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest

from app import backend_hub as hub, db, hub_workspace as hw, manager as mgr_mod



def _save_test_session(sid: str, name: str, scope: str, cwd: str, ws_id: str, status: str, worktree_path: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    db.save_session({
        "id": sid,
        "name": name,
        "scope": scope,
        "cwd": cwd,
        "model": "hub-gemini-4-neon",
        "system_prompt": "",
        "backend_type": "hub",
        "session_id": ws_id,
        "status": status,
        "cost_usd": 0.0,
        "worktree_path": worktree_path,
        "branch": f"task-1/{name}",
        "is_orchestrator": 0,
        "color": "",
        "created_at": now,
        "finished_at": now if status == "archived" else None,
    })


class RealFsHubSsh:
    """Fake HubSsh executing real filesystem removals & hw._SCRUB_SCRIPT inside temp HOME."""

    def __init__(self, home_dir: Path, host_tag: str = "vmi3407579"):
        self.home = home_dir
        self.host_tag = host_tag
        self.ws_root = self.home / "orchestra-ws" / self.host_tag
        self.ws_root.mkdir(parents=True, exist_ok=True)
        self.removed: list[str] = []
        self.scrubbed: list[tuple[str, str]] = []
        self.fail_remove: set[str] = set()
        self.fail_scrub: set[str] = set()

    async def root(self) -> str:
        return str(self.ws_root)

    async def assert_file_policy(self, remote_dir: str) -> None:
        return None

    async def remove(self, remote_dir: str) -> None:
        if remote_dir in self.fail_remove:
            raise hw.HubWorkspaceError("simulated SSH timeout on remove")
        hw._check_remote(remote_dir, base_ok=False)
        root = await self.root()
        if not hw.is_safe_hub_workspace_dir(remote_dir, expected_root=root):
            raise hw.HubWorkspaceError("refusing to remove a path outside the workspace root")
        self.removed.append(remote_dir)
        shutil.rmtree(remote_dir, ignore_errors=True)

    async def scrub_traces(self, ws_id: str, thread_id: str) -> None:
        if ws_id in self.fail_scrub:
            raise hw.HubWorkspaceError("simulated SSH failure on scrub_traces")
        env = dict(os.environ, HOME=str(self.home))
        proc = subprocess.run(
            ["bash", "-s", "--", ws_id, thread_id or "-", "-"],
            input=hw._SCRUB_SCRIPT,
            text=True,
            capture_output=True,
            env=env,
        )
        assert proc.returncode == 0, proc.stderr
        self.scrubbed.append((ws_id, thread_id))


class TrackingMc:
    def __init__(self, projects: dict[str, dict] | None = None, threads: dict[str, dict] | None = None):
        self.projects = projects or {}
        self.threads = threads or {}
        self.calls: list[tuple[str, dict]] = []
        self.fail_delete: set[str] = set()
        self.fail_interrupt: set[str] = set()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        pass

    async def tool_call(self, name: str, args: dict):
        self.calls.append((name, dict(args)))
        if name == "t3_project_read":
            pid = args["projectId"]
            if pid not in self.projects:
                raise RuntimeError(f"project_not_found: {pid}")
            return dict(self.projects[pid])
        if name == "t3_project_list":
            return {"projects": list(self.projects.values()), "nextCursor": None}
        if name == "t3_project_delete":
            pid = args["projectId"]
            if pid in self.fail_delete:
                raise OSError(f"network failure deleting {pid}")
            if pid not in self.projects:
                raise RuntimeError(f"project_not_found: {pid}")
            self.projects.pop(pid, None)
            self.threads = {tid: t for tid, t in self.threads.items() if t.get("projectId") != pid}
            return {"ok": True}
        if name == "t3_thread_read":
            tid = args["threadId"]
            th = self.threads.get(tid)
            if th is None:
                raise RuntimeError(f"thread_not_found: {tid}")
            return {"thread": {"threadId": tid, "projectId": th.get("projectId", ""), "pendingRequestCount": 0}, "items": []}
        if name == "t3_thread_interrupt":
            tid = args["threadId"]
            if tid in self.fail_interrupt:
                raise OSError(f"network failure interrupting {tid}")
            return {"ok": True}
        if name == "t3_thread_wait":
            return {"status": "interrupted", "timedOut": False}
        if name == "t3_thread_organize":
            tid = args["threadId"]
            if tid in self.threads:
                self.threads[tid]["archived"] = True
            return {"ok": True}
        return {}


@pytest.mark.asyncio
async def test_archive_ephemeral_hub_project_deletes_project_dir_and_scrubs_logs(tmp_path, monkeypatch):
    monkeypatch.setattr(hw, "STATE_DIR", tmp_path / "records")
    monkeypatch.delenv("MULTICODE_HUB_PROVIDER_LOG_DIR", raising=False)

    home = tmp_path / "hub-home"
    ssh = RealFsHubSsh(home)
    ws_id = "hub-14474479f3524833"
    tid = "mcp:11112222-3333-4444-5555-666677778888"
    pid = "mcp:aaaa1111-2222-3333-4444-555566667777"
    remote_dir = ssh.ws_root / ws_id
    remote_dir.mkdir(parents=True)
    (remote_dir / "work.txt").write_text("artifact", encoding="utf-8")

    # Provider traces that MUST be removed + unrelated traces that MUST stay.
    claude_dir = home / ".claude" / "projects" / f"-home-u-orchestra-ws-vmi3407579-{ws_id}"
    claude_dir.mkdir(parents=True)
    (claude_dir / "transcript.jsonl").write_text("{}", encoding="utf-8")
    other_claude = home / ".claude" / "projects" / "-home-u-permanent-repo"
    other_claude.mkdir(parents=True)
    (other_claude / "keep.jsonl").write_text("{}", encoding="utf-8")

    prov_dir = home / ".t3" / "userdata" / "logs" / "provider"
    prov_dir.mkdir(parents=True)
    ev1 = prov_dir / "events.mcp-11112222-3333-4444-5555-666677778888.log"
    ev2 = prov_dir / "events.mcp-11112222-3333-4444-5555-666677778888.log.1"
    ev_other = prov_dir / "events.mcp-99999999-0000-0000-0000-000000000000.log"
    for f in (ev1, ev2, ev_other):
        f.write_text("log", encoding="utf-8")

    wt = tmp_path / "wt"
    wt.mkdir()
    state = hw.WorkspaceState(
        ws_id=ws_id,
        worktree=str(wt),
        remote_dir=str(remote_dir),
        project_id=pid,
        thread_id=tid,
        ephemeral_project=True,
    )
    state.save()

    mc = TrackingMc(
        projects={pid: {"id": pid, "title": "hub-v41-hub-voice", "workspaceRoot": str(remote_dir)}},
        threads={tid: {"id": tid, "projectId": pid, "archived": False}},
    )

    await hw.archive_workspace(state, ssh, mc)

    assert pid not in mc.projects
    assert ("t3_project_delete", {"projectId": pid, "force": True}) in mc.calls
    assert not remote_dir.exists()
    assert not claude_dir.exists()
    assert not ev1.exists() and not ev2.exists()
    assert other_claude.exists() and ev_other.exists()

    saved = hw.WorkspaceState.load(ws_id)
    assert saved is not None
    assert saved.archived is True
    assert saved.remote_released is True
    assert hw.is_traces_scrubbed(ws_id) is True


@pytest.mark.asyncio
async def test_permanent_user_project_is_never_deleted_only_thread_archived(tmp_path, monkeypatch):
    monkeypatch.setattr(hw, "STATE_DIR", tmp_path / "records")
    home = tmp_path / "hub-home"
    ssh = RealFsHubSsh(home)
    ws_id = "hub-2222333344445555"
    pid = "mcp:perm-project"
    tid = "mcp:thread-in-perm"
    remote_dir = ssh.ws_root / ws_id
    remote_dir.mkdir(parents=True)
    perm_dir = tmp_path / "permanent" / "Orchestra"
    perm_dir.mkdir(parents=True)

    wt = tmp_path / "wt-perm"
    wt.mkdir()
    state = hw.WorkspaceState(
        ws_id=ws_id,
        worktree=str(wt),
        remote_dir=str(remote_dir),
        project_id=pid,
        thread_id=tid,
    )
    state.save()

    mc = TrackingMc(
        projects={pid: {"id": pid, "title": "Orchestra", "workspaceRoot": str(perm_dir)}},
        threads={tid: {"id": tid, "projectId": pid, "archived": False}},
    )

    await hw.archive_workspace(state, ssh, mc)

    # Permanent project and its directory stay intact; only the thread is archived.
    assert pid in mc.projects
    assert not any(name == "t3_project_delete" for name, _ in mc.calls)
    assert ("t3_thread_organize", {"threadId": tid, "action": "archive"}) in mc.calls
    assert mc.threads[tid]["archived"] is True
    assert perm_dir.exists()
    # Ephemeral workspace directory under orchestra-ws/ is still removed safely.
    assert not remote_dir.exists()


@pytest.mark.asyncio
async def test_janitor_cleans_archived_and_deleted_but_never_touches_live_idle_or_running(tmp_path, monkeypatch):
    monkeypatch.setattr(hw, "STATE_DIR", tmp_path / "records")
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "w33-janitor.db")
    db.init_db()

    home = tmp_path / "hub-home"
    ssh = RealFsHubSsh(home)
    prov_dir = home / ".t3" / "userdata" / "logs" / "provider"
    prov_dir.mkdir(parents=True)

    def make_worker(ws_id: str, pid: str, tid: str, title: str, wt_name: str, status: str | None,
                    *, archived=False, remote_released=False, traces_scrubbed=False, pending_sync=None):
        wt = tmp_path / "wt" / wt_name
        wt.mkdir(parents=True, exist_ok=True)
        rdir = ssh.ws_root / ws_id
        rdir.mkdir(parents=True, exist_ok=True)
        (rdir / "data.txt").write_text(ws_id, encoding="utf-8")
        cdir = home / ".claude" / "projects" / f"-home-u-orchestra-ws-vmi3407579-{ws_id}"
        cdir.mkdir(parents=True, exist_ok=True)
        stid = tid.replace(":", "-")
        ev = prov_dir / f"events.{stid}.log"
        ev.write_text("trace", encoding="utf-8")
        st = hw.WorkspaceState(
            ws_id=ws_id,
            worktree=str(wt),
            remote_dir=str(rdir),
            project_id=pid,
            thread_id=tid,
            archived=archived,
            remote_released=remote_released,
                pending_sync=pending_sync or {},
        )
        st.save()
        if status is not None:
            _save_test_session(f"sess-{ws_id}", wt_name, str(tmp_path / "scope"), str(wt), ws_id, status, str(wt))
        return {"ws_id": ws_id, "pid": pid, "tid": tid, "title": title, "rdir": rdir, "cdir": cdir, "ev": ev}

    idle_w = make_worker("hub-1c46f88486404102", "mcp:idle-p", "mcp:idle-t1111", "hub-polyus-stylization-neon", "polyus-stylization-neon", "idle")
    run_w = make_worker("hub-2222222222222222", "mcp:run-p", "mcp:run-t2222", "hub-active-runner", "active-runner", "running")
    arch_w = make_worker("hub-318b89b9238749c0", "mcp:arch-p", "mcp:arch-t3333", "hub-eis-scope-1411", "eis-scope-1411", "archived")
    del_w = make_worker("hub-4444444444444444", "mcp:del-p", "mcp:del-t4444", "hub-deleted", "deleted-worker", None, archived=True, remote_released=True, traces_scrubbed=False)
    pend_w = make_worker("hub-5555555555555555", "mcp:pend-p", "mcp:pend-t5555", "hub-pending", "pending-worker", "archived", pending_sync={"phase": "report"})

    projects = {
        w["pid"]: {"id": w["pid"], "title": w["title"], "workspaceRoot": str(w["rdir"])}
        for w in (idle_w, run_w, arch_w, pend_w)
    }
    threads = {
        w["tid"]: {"id": w["tid"], "projectId": w["pid"], "archived": False}
        for w in (idle_w, run_w, arch_w, pend_w)
    }
    mc = TrackingMc(projects=projects, threads=threads)

    r1 = await hub.cleanup_orphaned_hub_artifacts(ssh=ssh, mc=mc)
    assert r1["errors"] == []
    assert arch_w["pid"] in r1["projects_deleted"]
    assert str(arch_w["rdir"]) in r1["dirs_removed"]
    assert set(r1["traces_scrubbed"]) == {arch_w["ws_id"], del_w["ws_id"]}

    # Archived & deleted workers cleaned up completely.
    assert not arch_w["rdir"].exists() and not arch_w["cdir"].exists() and not arch_w["ev"].exists()
    assert not del_w["cdir"].exists() and not del_w["ev"].exists()
    assert arch_w["pid"] not in mc.projects
    assert hw.WorkspaceState.load(arch_w["ws_id"]).remote_released is True
    assert hw.is_traces_scrubbed(arch_w["ws_id"]) is True
    assert hw.is_traces_scrubbed(del_w["ws_id"]) is True

    # Live idle/running and pending_sync workers MUST remain completely untouched.
    for untouched in (idle_w, run_w, pend_w):
        assert untouched["pid"] in mc.projects
        assert untouched["rdir"].exists()
        assert untouched["cdir"].exists()
        assert untouched["ev"].exists()

    # Second run is strictly idempotent: zero deletions, zero new scrubs.
    r2 = await hub.cleanup_orphaned_hub_artifacts(ssh=ssh, mc=mc)
    assert r2["projects_deleted"] == []
    assert r2["dirs_removed"] == []
    assert r2["traces_scrubbed"] == []
    assert r2["already_clean"] == 2
    assert r2["kept"] == 3


@pytest.mark.asyncio
async def test_path_traversal_and_unsafe_paths_blocked(tmp_path, monkeypatch):
    monkeypatch.setattr(hw, "STATE_DIR", tmp_path / "records")
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "w33-traversal.db")
    db.init_db()

    home = tmp_path / "hub-home"
    ssh = RealFsHubSsh(home)
    important = home / "important-user-data"
    important.mkdir(parents=True)
    (important / "keep.txt").write_text("safe", encoding="utf-8")

    # Unit checks for path guards
    assert hw.is_ephemeral_hub_dir(f"{ssh.ws_root}/hub-0123456789abcdef") is True
    assert hw.is_ephemeral_hub_dir(f"{ssh.ws_root}/../important-user-data") is False
    assert hw.is_ephemeral_hub_dir(f"{ssh.ws_root}/proj-b43baa0cf2a2") is False
    assert hw.is_ephemeral_hub_dir(str(important)) is False
    assert hw.is_safe_hub_workspace_dir(f"{ssh.ws_root}/hub-0123456789abcdef", expected_root=str(ssh.ws_root)) is True
    assert hw.is_safe_hub_workspace_dir(str(important), expected_root=str(ssh.ws_root)) is False
    assert hw.is_safe_hub_workspace_dir(f"{ssh.ws_root}/hub-0123456789abcdef/../important-user-data", expected_root=str(ssh.ws_root)) is False
    assert hw.is_safe_hub_workspace_dir(f"{ssh.ws_root}/hub-bad;rm -rf /", expected_root=str(ssh.ws_root)) is False

    # Even if a corrupted WorkspaceState points to an external/traversal path, janitor refuses to delete it.
    bad_state = hw.WorkspaceState(
        ws_id="hub-deadbeef00001111",
        worktree=str(tmp_path / "wt-bad"),
        remote_dir=str(important),
        project_id="",
        thread_id="",
        archived=True,
    )
    bad_state.save()
    mc = TrackingMc()
    report = await hub.cleanup_orphaned_hub_artifacts(ssh=ssh, mc=mc)
    assert report["dirs_removed"] == []
    assert any("refused unsafe workspace path" in e for e in report["errors"])
    assert (important / "keep.txt").exists()


@pytest.mark.asyncio
async def test_manager_remove_network_failure_after_durable_archive_does_not_block_db_archive(tmp_path, monkeypatch):
    monkeypatch.setattr(hw, "STATE_DIR", tmp_path / "records")
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "w33-mgr.db")
    db.init_db()

    from app.bg_jobs import bg_manager

    home = tmp_path / "hub-home"
    ssh = RealFsHubSsh(home)
    ws_id = "hub-6666777788889999"
    pid = "mcp:netfail-p"
    tid = "mcp:netfail-t"
    wt = tmp_path / "wt-netfail"
    wt.mkdir()
    rdir = ssh.ws_root / ws_id
    rdir.mkdir(parents=True)

    state = hw.WorkspaceState(
        ws_id=ws_id,
        worktree=str(wt),
        remote_dir=str(rdir),
        project_id=pid,
        thread_id=tid,
        ephemeral_project=True,
    )
    state.save()

    sid = "sess-netfail"
    _save_test_session(sid, "worker-netfail", str(tmp_path / "scope"), str(wt), ws_id, "idle", str(wt))

    # Simulate transport failure AFTER thread archival during remote project/dir deletion.
    mc = TrackingMc(
        projects={pid: {"id": pid, "title": "hub-worker-netfail", "workspaceRoot": str(rdir)}},
        threads={tid: {"id": tid, "projectId": pid, "archived": False}},
    )
    mc.fail_delete.add(pid)
    ssh.fail_remove.add(str(rdir))

    monkeypatch.setattr(hw.HubSsh, "from_env", classmethod(lambda _cls: ssh))
    monkeypatch.setattr(hub.MultiCodeClient, "from_env", classmethod(lambda _cls: mc))
    monkeypatch.setattr(hub, "hub_configured", lambda: None)
    monkeypatch.setattr(bg_manager, "cancel_by_session", AsyncMock())
    monkeypatch.setattr(mgr_mod, "remove_worktree", Mock())

    mgr = mgr_mod.SessionManager()
    monkeypatch.setattr(mgr, "_cleanup_cli_home", Mock())
    monkeypatch.setattr(mgr, "_schedule_hub_orphan_cleanup", Mock())

    # Must NOT raise and MUST archive session in SQLite despite remote cleanup failure.
    await mgr.remove(sid)
    assert db.get_session(sid)["status"] == "archived"
    persisted_ws = hw.WorkspaceState.load(ws_id)
    assert persisted_ws.archived is True
    assert persisted_ws.remote_released is False

    # Once network recovers, janitor finishes remote cleanup cleanly.
    mc.fail_delete.clear()
    ssh.fail_remove.clear()
    janitor = await hub.cleanup_orphaned_hub_artifacts(ssh=ssh, mc=mc)
    assert janitor["errors"] == []
    assert pid in janitor["projects_deleted"]
    assert not rdir.exists()
    assert hw.WorkspaceState.load(ws_id).remote_released is True


@pytest.mark.asyncio
async def test_delete_session_force_archives_db_even_if_hub_transport_totally_down(tmp_path, monkeypatch):
    monkeypatch.setattr(hw, "STATE_DIR", tmp_path / "records")
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "w33-force.db")
    db.init_db()

    from app.bg_jobs import bg_manager

    home = tmp_path / "hub-home"
    ssh = RealFsHubSsh(home)
    ws_id = "hub-777788889999aaaa"
    pid = "mcp:down-p"
    tid = "mcp:down-t"
    wt = tmp_path / "wt-down"
    wt.mkdir()
    rdir = ssh.ws_root / ws_id
    rdir.mkdir(parents=True)

    state = hw.WorkspaceState(
        ws_id=ws_id,
        worktree=str(wt),
        remote_dir=str(rdir),
        project_id=pid,
        thread_id=tid,
        ephemeral_project=True,
    )
    state.save()

    sid = "sess-down"
    scope = tmp_path / "scope"
    scope.mkdir()
    _save_test_session(sid, "worker-down", str(scope), str(wt), ws_id, "idle", str(wt))

    # Pre-archive t3_thread_interrupt fails completely, yet force=True still archives DB row.
    mc = TrackingMc(
        projects={pid: {"id": pid, "title": "hub-worker-down", "workspaceRoot": str(rdir)}},
        threads={tid: {"id": tid, "projectId": pid, "archived": False}},
    )
    mc.fail_interrupt.add(tid)

    monkeypatch.setattr(hw.HubSsh, "from_env", classmethod(lambda _cls: ssh))
    monkeypatch.setattr(hub.MultiCodeClient, "from_env", classmethod(lambda _cls: mc))
    monkeypatch.setattr(hub, "hub_configured", lambda: None)
    monkeypatch.setattr(bg_manager, "cancel_by_session", AsyncMock())
    monkeypatch.setattr(mgr_mod, "remove_worktree", Mock())

    mgr = mgr_mod.SessionManager()
    monkeypatch.setattr(mgr, "_cleanup_cli_home", Mock())
    monkeypatch.setattr(mgr, "_schedule_hub_orphan_cleanup", Mock())

    await mgr.remove(sid, force=True)
    assert db.get_session(sid)["status"] == "archived"
    # Transport down prevented remote release; janitor picks it up once transport recovers.
    assert hw.WorkspaceState.load(ws_id).remote_released is False
    mc.fail_interrupt.clear()
    janitor = await hub.cleanup_orphaned_hub_artifacts(ssh=ssh, mc=mc)
    assert pid in janitor["projects_deleted"]
    assert not rdir.exists()
