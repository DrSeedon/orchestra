"""Tests for HubBackend orchestrator role: preamble, live workers snapshot, and outbox commands."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import uuid

import pytest

from app import backend_hub as hub, db, hub_outbox as ob


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    db_file = tmp_path / "test_orchestra.db"
    monkeypatch.setattr(db, "DB_PATH", db_file)
    db.init_db()
    return db_file


def _insert_session(
    *,
    sid: str,
    name: str,
    scope: str,
    role: str = "worker",
    is_orchestrator: int = 0,
    parent_name: str = "",
    parent_id: str = "",
    model: str = "hub-gpt-6-luna",
    status: str = "idle",
    branch: str = "",
    worktree_path: str = "",
) -> None:
    with db._conn() as conn:
        conn.execute(
            """INSERT INTO sessions (
                id, name, scope, cwd, model, role, is_orchestrator,
                parent_name, parent_id, status, branch, worktree_path, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))""",
            (
                sid, name, scope, worktree_path or scope, model, role, is_orchestrator,
                parent_name, parent_id, status, branch, worktree_path,
            ),
        )


def test_ordinary_worker_contract_unchanged():
    raw = "\n".join([
        json.dumps({"tool": "send_message", "args": {"message": "done"}}),
        json.dumps({"tool": "spawn_worker", "args": {"name": "w1", "task": "hi"}}),
        json.dumps({"tool": "merge_worker", "args": {"worker": "w1"}}),
        json.dumps({"tool": "close_worker", "args": {"worker": "w1"}}),
    ]).encode()
    entries, dropped = ob.parse_outbox(raw)
    assert [e["tool"] for e in entries] == ["send_message"]
    assert len(dropped) == 3
    assert all("is not available to hub workers" in d for d in dropped)

    worker_who = ob.Identity(
        session_id="w-1", name="worker-a", scope="/tmp/proj", parent_name="orch", role="worker",
    )
    pre = hub.hub_preamble(worker_who, has_link=True)
    assert "\"tool\":\"send_message\"" in pre
    assert "spawn_worker" not in pre
    assert "<orchestra-workers" not in pre


@pytest.mark.asyncio
async def test_worker_cannot_execute_orchestrator_tools_even_if_injected(isolated_db):
    worker_who = ob.Identity(
        session_id="w-1", name="worker-a", scope="/tmp/proj", parent_name="orch", role="worker",
    )
    calls = []

    async def fake_call(method: str, path: str, body: dict):
        calls.append((method, path, body))
        return {"ok": True}

    report = await ob.execute(
        [
            {"tool": "spawn_worker", "args": {"name": "x", "task": "t"}},
            {"tool": "send_to_worker", "args": {"worker": "x", "message": "hi"}},
            {"tool": "merge_worker", "args": {"worker": "x"}},
            {"tool": "close_worker", "args": {"worker": "x"}},
        ],
        worker_who,
        fake_call,
    )
    assert calls == []
    assert report.done == []
    assert len(report.rejected) == 4
    assert all("restricted to role='orchestrator'" in r for r in report.rejected)


def test_orchestrator_preamble_and_followup_snapshot(isolated_db, tmp_path):
    scope = str(tmp_path / "hydrogen-sandbox")
    wt = tmp_path / "wt-child1"
    wt.mkdir(parents=True)
    subprocess.run(["git", "init", "-b", "adhoc-child1", str(wt)], check=True, capture_output=True)
    (wt / "hello.py").write_text("x = 1\n")
    subprocess.run(["git", "-C", str(wt), "add", "hello.py"], check=True)
    subprocess.run(
        ["git", "-C", str(wt), "-c", "user.name=Test", "-c", "user.email=t@t", "commit", "-m", "init"],
        check=True, capture_output=True,
    )
    head_sha = subprocess.check_output(["git", "-C", str(wt), "rev-parse", "HEAD"], text=True).strip()

    _insert_session(
        sid="orch-1", name="hydrogen-orch", scope=scope,
        role="orchestrator", is_orchestrator=1, model="hub-gemini-4-hydrogen",
    )
    _insert_session(
        sid="c-1", name="child1", scope=scope, role="worker",
        parent_name="hydrogen-orch", parent_id="orch-1",
        model="hub-gpt-6-luna", status="idle", branch="adhoc-child1", worktree_path=str(wt),
    )
    # Foreign worker under another parent & another scope must NOT leak into snapshot
    _insert_session(
        sid="c-foreign", name="foreign-child", scope=scope, role="worker",
        parent_name="other-orch", parent_id="orch-2",
        model="hub-gpt-6-luna", status="running", branch="adhoc-foreign",
    )

    orch_who = ob.Identity(
        session_id="orch-1", name="hydrogen-orch", scope=scope,
        role="orchestrator", is_orchestrator=True,
    )
    pre = hub.hub_preamble(orch_who, has_link=True)
    assert "## Role: Orchestrator (hub session)" in pre
    assert "\"tool\":\"spawn_worker\"" in pre
    assert "\"tool\":\"send_to_worker\"" in pre
    assert "\"tool\":\"merge_worker\"" in pre
    assert "\"tool\":\"close_worker\"" in pre
    assert f"child1 | status=idle | model=hub-gpt-6-luna | role=worker | branch=adhoc-child1 | head={head_sha}" in pre
    assert "foreign-child" not in pre

    # Follow-up turn (_prompt with first=False) also injects fresh workers snapshot
    bridge = ob.HubBridge(lambda: orch_who)
    backend = hub.HubBackend("hub-gemini-4-hydrogen", scope, scope=scope, role="orchestrator", bridge=bridge)
    second_prompt = backend._prompt("[from:child1] DONE", first=False)
    assert "<orchestra-workers" in second_prompt
    assert head_sha in second_prompt
    assert "[from:child1] DONE" in second_prompt


@pytest.mark.asyncio
async def test_orchestrator_outbox_spawn_send_merge_close_and_scope_isolation(isolated_db, tmp_path):
    scope = str(tmp_path / "hydrogen-sandbox")
    Path(scope).mkdir(parents=True)
    wt = tmp_path / "wt-kid"
    wt.mkdir(parents=True)
    subprocess.run(["git", "init", "-b", "adhoc-kid", str(wt)], check=True, capture_output=True)
    (wt / "hello_hydrogen.py").write_text("def greet(): return 'hi'\n")
    subprocess.run(["git", "-C", str(wt), "add", "hello_hydrogen.py"], check=True)
    subprocess.run(
        ["git", "-C", str(wt), "-c", "user.name=Test", "-c", "user.email=t@t", "commit", "-m", "feat"],
        check=True, capture_output=True,
    )
    head_sha = subprocess.check_output(["git", "-C", str(wt), "rev-parse", "HEAD"], text=True).strip()

    _insert_session(
        sid="orch-1", name="hydrogen-orch", scope=scope,
        role="orchestrator", is_orchestrator=1, model="hub-gemini-4-hydrogen",
    )
    _insert_session(
        sid="c-other", name="not-my-kid", scope=scope, role="worker",
        parent_name="someone-else", parent_id="orch-99",
        model="hub-gpt-6-luna", status="idle", branch="adhoc-other", worktree_path=str(wt),
    )

    orch_who = ob.Identity(
        session_id="orch-1", name="hydrogen-orch", scope=scope,
        role="orchestrator", is_orchestrator=True,
    )

    calls: list[tuple[str, str, dict]] = []
    merge_polls = 0

    async def fake_api(method: str, path: str, body: dict):
        nonlocal merge_polls
        calls.append((method, path, body))
        if method == "POST" and path == "/api/sessions":
            _insert_session(
                sid="c-kid", name=body["name"], scope=body["scope"], role=body["role"],
                parent_name=body["parent_name"], parent_id="orch-1",
                model=body["model"], status="idle", branch=f"adhoc-{body['name']}", worktree_path=str(wt),
            )
            return {
                "id": "c-kid",
                "name": body["name"],
                "worktree_path": str(wt),
                "branch": f"adhoc-{body['name']}",
                "repo_path": scope,
                "git_common_dir": str(Path(scope) / ".git"),
            }
        if method == "POST" and path.endswith("/initial-deliveries"):
            return {"ok": True, "delivery_state": "QUEUED", "delivery_id": body["delivery_id"]}
        if method == "POST" and path.endswith("/send"):
            return {"ok": True, "delivery_state": "QUEUED", "delivery_id": body["delivery_id"]}
        if method == "POST" and path == "/api/merge-operations":
            return {"result": {"operation_id": body["operation_id"], "operation_state": "RUNNING"}}
        if method == "GET" and path.startswith("/api/merge-operations/"):
            merge_polls += 1
            op_id = path.rsplit("/", 1)[-1]
            return {"result": {"operation_id": op_id, "operation_state": "SUCCEEDED"}}
        if method == "DELETE" and path.startswith("/api/sessions/"):
            return {"ok": True}
        if method == "POST" and path.endswith("/progress"):
            return {"ok": True}
        raise AssertionError(f"Unexpected API call: {method} {path}")

    raw_outbox = "\n".join([
        json.dumps({
            "tool": "spawn_worker",
            "args": {
                "name": "kid",
                "task": "Create hello_hydrogen.py and run unittest",
                "model": "hub-gpt-6-luna",
                "role": "worker",
                "base_branch": "main",
                "description": "lifecycle=one-shot; test worker",
            },
        }),
        json.dumps({"tool": "send_to_worker", "args": {"worker": "kid", "message": "Check edge cases"}}),
        json.dumps({"tool": "merge_worker", "args": {"worker": "kid", "target_branch": "main"}}),
        json.dumps({"tool": "close_worker", "args": {"worker": "kid", "reason": "merged cleanly"}}),
        # Ownership violations must be terminally rejected without touching API
        json.dumps({"tool": "send_to_worker", "args": {"worker": "not-my-kid", "message": "hijack"}}),
        json.dumps({"tool": "close_worker", "args": {"worker": "not-my-kid"}}),
        json.dumps({"tool": "update_progress", "args": {"percent": 100, "status": "all done"}}),
    ]).encode()

    entries, parse_dropped = ob.parse_outbox(raw_outbox, role="orchestrator")
    assert parse_dropped == []
    for e in entries:
        e["_delivery_id"] = str(uuid.uuid4())

    report = await ob.execute(entries, orch_who, fake_api)
    assert report.done == [
        "spawn_worker",
        "send_to_worker",
        "merge_worker",
        "close_worker",
        "update_progress",
    ]
    assert len(report.rejected) == 2
    assert all("not a direct child" in r for r in report.rejected)
    assert merge_polls == 1

    # Verify spawn_worker payload & merge_worker auto-resolved 40-char expected_head
    spawn_call = next(c for c in calls if c[0] == "POST" and c[1] == "/api/sessions")
    assert spawn_call[2]["parent_name"] == "hydrogen-orch"
    assert spawn_call[2]["scope"] == scope
    assert spawn_call[2]["use_worktree"] is True
    merge_call = next(c for c in calls if c[0] == "POST" and c[1] == "/api/merge-operations")
    assert merge_call[2]["expected_head"] == head_sha
    assert merge_call[2]["target"] == "main"


@pytest.mark.asyncio
async def test_finalizing_turn_defers_incoming_child_report():
    backend = hub.HubBackend("hub-gemini-4-hydrogen", "/tmp", scope="/tmp", role="orchestrator")
    backend._ssh = object()  # connected marker
    backend._turn_active = True
    backend._finalizing_turn = True
    with pytest.raises(RuntimeError, match="finalizing sync"):
        await backend.send("[from:kid] finished")


@pytest.mark.asyncio
async def test_spawn_worker_rejects_orchestrator_role_and_non_multicast_claude(isolated_db, tmp_path):
    scope = str(tmp_path / "hydrogen-sandbox")
    Path(scope).mkdir(parents=True)
    orch_who = ob.Identity(
        session_id="orch-1", name="hydrogen-orch", scope=scope,
        role="orchestrator", is_orchestrator=True,
    )
    calls = []

    async def fake_api(method: str, path: str, body: dict):
        calls.append((method, path, body))
        return {"ok": True}

    report = await ob.execute(
        [
            {"tool": "spawn_worker", "args": {"name": "sub", "task": "t", "role": "orchestrator"}},
            {"tool": "spawn_worker", "args": {"name": "cl", "task": "t", "model": "hub-claude-opus-5-5"}},
        ],
        orch_who,
        fake_api,
    )
    assert len(calls) == 2
    assert calls[0][2]["model"] == "hub-claude-opus-5-5"
    assert len(report.done) == 1
    assert len(report.rejected) == 1
    assert "non-orchestrator worker role" in report.rejected[0]
