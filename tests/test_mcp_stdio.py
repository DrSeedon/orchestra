import json

import pytest
from unittest.mock import AsyncMock, patch
from datetime import datetime, timedelta, timezone


@pytest.mark.asyncio
async def test_task_create_returns_fields_needed_by_dashboard_card(monkeypatch):
    import app.mcp_stdio as m

    monkeypatch.setattr(m, "SCOPE", "/scope")

    async def fake_api(method, path, **kwargs):
        assert method == "POST"
        assert path == "/api/tm/tasks"
        assert kwargs["json"]["description"] == "Long task description"
        return {
            "par": "113",
            "id": 987,
            "title": "Task card",
            "project": "orchestra",
            "price_rub": 0,
            "status": "new",
        }

    with patch.object(m, "_api", side_effect=fake_api):
        raw = await m.task_create(
            title="Task card",
            project="orchestra",
            description="Long task description",
            assignee="frontend",
            priority=1,
        )

    result = json.loads(raw)
    assert result["description"] == "Long task description"
    assert result["assignee"] == "frontend"
    assert result["priority"] == 1
    assert result["task_id"] == 987


@pytest.mark.asyncio
async def test_spawn_passes_base_branch(monkeypatch):
    import app.mcp_stdio as m
    monkeypatch.setattr(m, "SCOPE", "/s")
    monkeypatch.setattr(m, "WORKER_NAME", "coder-auth")
    captured = {}
    async def fake_api(method, path, **kw):
        if path == "/api/sessions":
            captured.update(kw.get("json", {}))
            return {
                "worktree_path": "/worktrees/w-step1",
                "branch": "task-1/w-step1",
                "repo_path": "/s",
                "git_common_dir": "/s/.git",
            }
        return {"ok": True}
    with patch.object(m, "_api", side_effect=fake_api):
        await m.spawn_worker(name="w-step1", task="do it", repo_path="/s",
                             model="claude-sonnet-5[1m]", base_branch="feature/auth")
    assert captured["base_branch"] == "feature/auth"
    assert captured["use_worktree"] is True


@pytest.mark.asyncio
async def test_spawn_base_branch_default_empty(monkeypatch):
    # Sentinel "" = авто-резолв базовой ветки по стратегии пайплайна (DESIGN §10):
    # parent → от ветки родителя, иначе main. Явная ветка переопределяет стратегию.
    import app.mcp_stdio as m
    monkeypatch.setattr(m, "SCOPE", "/s")
    monkeypatch.setattr(m, "WORKER_NAME", "x")
    captured = {}
    async def fake_api(method, path, **kw):
        if path == "/api/sessions":
            captured.update(kw.get("json", {}))
            return {
                "worktree_path": "/worktrees/w",
                "branch": "task-1/w",
                "repo_path": "/s",
                "git_common_dir": "/s/.git",
            }
        return {"ok": True}
    with patch.object(m, "_api", side_effect=fake_api):
        await m.spawn_worker(name="w", task="t", repo_path="/s", model="claude-sonnet-5[1m]")
    assert captured["base_branch"] == ""


@pytest.mark.asyncio
async def test_spawn_marks_parent_as_initial_task_sender(monkeypatch):
    import app.mcp_stdio as m
    monkeypatch.setattr(m, "SCOPE", "/s")
    monkeypatch.setattr(m, "WORKER_NAME", "parent-orchestrator")
    calls = []

    async def fake_api(method, path, **kw):
        calls.append((method, path, kw.get("json")))
        if path == "/api/sessions":
            return {
                "worktree_path": "/worktrees/child",
                "branch": "task-1/child",
                "repo_path": "/s",
                "git_common_dir": "/s/.git",
            }
        return {"ok": True}

    with patch.object(m, "_api", side_effect=fake_api):
        await m.spawn_worker(
            name="child",
            task="do it",
            repo_path="/s",
            model="claude-opus-5[1m]",
        )

    send_call = next(call for call in calls if call[1] == "/api/sessions/child/send")
    assert send_call[2]["sender"] == "parent-orchestrator"


@pytest.mark.asyncio
async def test_spawn_reports_exact_repo_mapping_when_scope_differs(monkeypatch, tmp_path):
    import app.mcp_stdio as m

    repo = tmp_path / "new-project"
    monkeypatch.setattr(m, "SCOPE", "/logical/orchestrator-project")
    monkeypatch.setattr(m, "WORKER_NAME", "parent-orchestrator")
    calls = []

    async def fake_api(method, path, **kw):
        calls.append((method, path, kw.get("json")))
        if path == "/api/sessions":
            return {
                "worktree_path": "/actual/worktrees/child",
                "branch": "task-88/child",
                "repo_path": "/server/canonical/new-project",
                "git_common_dir": "/server/git/new-project",
            }
        return {"ok": True}

    with patch.object(m, "_api", side_effect=fake_api):
        out = await m.spawn_worker(
            name="child", task="do it", repo_path=str(repo),
            model="gpt-5.6-sol", task_id="88",
        )

    create_body = calls[0][2]
    assert create_body["scope"] == "/logical/orchestrator-project"
    assert create_body["cwd"] == str(repo)
    assert create_body["repo_path"] == str(repo)
    assert "Worktree: /actual/worktrees/child" in out
    assert "Repository: /server/canonical/new-project" in out
    assert "Git common dir: /server/git/new-project" in out
    assert "Branch: task-88/child" in out


@pytest.mark.asyncio
async def test_spawn_api_error_does_not_send_initial_task(monkeypatch):
    import app.mcp_stdio as m

    monkeypatch.setattr(m, "SCOPE", "/s")
    calls = []

    async def fake_api(method, path, **kw):
        calls.append(path)
        return {"error": "repo_path must be the Git repository root"}

    with patch.object(m, "_api", side_effect=fake_api):
        out = await m.spawn_worker(
            name="child", task="do it", repo_path="/repo/nested",
            model="gpt-5.6-sol",
        )

    assert calls == ["/api/sessions"]
    assert out == "Spawn failed: repo_path must be the Git repository root"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response, missing",
    [
        ({
            "branch": "task-88/child",
            "repo_path": "/repo",
            "git_common_dir": "/repo/.git",
        }, "worktree_path"),
        ({
            "worktree_path": "/actual/worktrees/child",
            "repo_path": "/repo",
            "git_common_dir": "/repo/.git",
        }, "branch"),
        ({
            "worktree_path": "/actual/worktrees/child",
            "branch": "task-88/child",
            "git_common_dir": "/repo/.git",
        }, "repo_path"),
        ({
            "worktree_path": "/actual/worktrees/child",
            "branch": "task-88/child",
            "repo_path": "/repo",
        }, "git_common_dir"),
        ({
            "worktree_path": 123,
            "branch": "task-88/child",
            "repo_path": "/repo",
            "git_common_dir": "/repo/.git",
        }, "worktree_path"),
        ({
            "worktree_path": "/actual/worktrees/child",
            "branch": [],
            "repo_path": "/repo",
            "git_common_dir": "/repo/.git",
        }, "branch"),
        ({
            "worktree_path": "/actual/worktrees/child",
            "branch": "task-88/child",
            "repo_path": " ",
            "git_common_dir": "/repo/.git",
        }, "repo_path"),
    ],
)
async def test_spawn_malformed_success_fails_loud_without_task(
    monkeypatch, response, missing,
):
    import app.mcp_stdio as m

    monkeypatch.setattr(m, "SCOPE", "/s")
    calls = []

    async def fake_api(method, path, **kw):
        calls.append(path)
        return response

    with patch.object(m, "_api", side_effect=fake_api):
        out = await m.spawn_worker(
            name="child", task="do it", repo_path="/repo",
            model="gpt-5.6-sol",
        )

    assert calls == ["/api/sessions"]
    assert "malformed API response" in out
    assert missing in out
    assert "worker may have been created" in out.lower()
    assert "Worktree:" not in out


@pytest.mark.asyncio
async def test_spawn_task_delivery_error_reports_created_worker(monkeypatch):
    import app.mcp_stdio as m

    monkeypatch.setattr(m, "SCOPE", "/s")
    calls = []

    async def fake_api(method, path, **kw):
        calls.append(path)
        if path == "/api/sessions":
            return {
                "worktree_path": "/worktrees/child",
                "branch": "task-88/child",
                "repo_path": "/repo",
                "git_common_dir": "/repo/.git",
            }
        return {"error": "delivery unavailable"}

    with patch.object(m, "_api", side_effect=fake_api):
        out = await m.spawn_worker(
            name="child", task="do it", repo_path="/repo",
            model="gpt-5.6-sol",
        )

    assert calls == ["/api/sessions", "/api/sessions/child/send"]
    assert "worker 'child' was created" in out.lower()
    assert "initial task delivery failed: delivery unavailable" in out
    assert "Worktree: /worktrees/child" in out
    assert "Task sent." not in out


@pytest.mark.asyncio
async def test_acquire_test_lock_uses_worker_as_holder(monkeypatch):
    import app.mcp_stdio as m
    monkeypatch.setattr(m, "SCOPE", "/s")
    monkeypatch.setattr(m, "WORKER_NAME", "coder-auth")
    captured = {}
    async def fake_api(method, path, **kw):
        captured["path"] = path
        captured["json"] = kw.get("json")
        return {"acquired": True, "holder": None}
    with patch.object(m, "_api", side_effect=fake_api):
        out = await m.acquire_test_lock(reason="full suite before merge")
    assert captured["path"] == "/api/test-lock/acquire"
    assert captured["json"]["holder"] == "coder-auth"
    assert captured["json"]["scope"] == "/s"
    assert captured["json"]["reason"] == "full suite before merge"
    assert "acquired" in out.lower() or "взял" in out.lower()


@pytest.mark.asyncio
async def test_acquire_test_lock_reports_holder_when_busy(monkeypatch):
    import app.mcp_stdio as m
    monkeypatch.setattr(m, "SCOPE", "/s")
    monkeypatch.setattr(m, "WORKER_NAME", "coder-b")
    async def fake_api(method, path, **kw):
        return {"acquired": False, "holder": "coder-a"}
    with patch.object(m, "_api", side_effect=fake_api):
        out = await m.acquire_test_lock(reason="x")
    assert "coder-a" in out  # держатель указан в отказе


@pytest.mark.asyncio
async def test_release_and_status(monkeypatch):
    import app.mcp_stdio as m
    monkeypatch.setattr(m, "SCOPE", "/s")
    monkeypatch.setattr(m, "WORKER_NAME", "coder-a")
    calls = {}
    async def fake_api(method, path, **kw):
        calls[path] = kw.get("json") or kw.get("params")
        if path == "/api/test-lock/release":
            return {"released": True}
        if path == "/api/test-lock":
            return {"held": True, "holder": "coder-a", "reason": "r", "acquired_at": "t"}
        return {}
    with patch.object(m, "_api", side_effect=fake_api):
        rel = await m.release_test_lock()
        st = await m.test_lock_status()
    assert "/api/test-lock/release" in calls
    assert "coder-a" in st  # статус упоминает держателя
    assert "released" in rel.lower() or "освобод" in rel.lower()

@pytest.mark.asyncio
async def test_merge_worker_with_next_task_id(monkeypatch):
    """next_task_id передаётся в body запроса к /api/sessions/{name}/merge."""
    import app.mcp_stdio as m
    monkeypatch.setattr(m, "SCOPE", "/s")
    monkeypatch.setattr(m, "WORKER_NAME", "orch")
    captured = {}
    async def fake_api(method, path, **kw):
        captured["path"] = path
        captured["json"] = kw.get("json", {})
        return {"ok": True, "commits_merged": 1, "branch": "task-42/w", "merged_commits": {}}
    with patch.object(m, "_api", side_effect=fake_api):
        out = await m.merge_worker(name="coder", target="main", next_task_id="task-43")
    assert captured["path"] == "/api/sessions/coder/merge"
    assert captured["json"]["next_task_id"] == "task-43"
    assert captured["json"]["target"] == "main"


@pytest.mark.asyncio
async def test_merge_worker_no_next_task_id(monkeypatch):
    """Без next_task_id ключ next_task_id не отправляется в body."""
    import app.mcp_stdio as m
    monkeypatch.setattr(m, "SCOPE", "/s")
    monkeypatch.setattr(m, "WORKER_NAME", "orch")
    captured = {}
    async def fake_api(method, path, **kw):
        captured["json"] = kw.get("json", {})
        return {"ok": True, "commits_merged": 1, "branch": "task-42/w", "merged_commits": {}}
    with patch.object(m, "_api", side_effect=fake_api):
        await m.merge_worker(name="coder")
    assert "next_task_id" not in captured["json"]
    assert "target" not in captured["json"]


@pytest.mark.asyncio
async def test_merge_worker_formats_normalized_and_legacy_link_results(monkeypatch):
    import app.mcp_stdio as m

    monkeypatch.setattr(m, "SCOPE", "/s")

    async def fake_api(*_args, **_kwargs):
        return {
            "ok": True,
            "commits_merged": 1,
            "branch": "task-90/worker",
            "linked_tasks": {
                "90": {"ok": True, "added": 2, "task_id": 1},
                "91": {"id": 2, "par_number": 91, "git_commits": "[]"},
                "999": {"ok": False, "added": 0, "error": "task '999' not found"},
                "998": None,
            },
        }

    with patch.object(m, "_api", side_effect=fake_api):
        output = await m.merge_worker(name="worker", target="main")

    assert "→ 90: 2 commits linked" in output
    assert "→ 91: commits linked" in output
    assert "⚠️ 999: FAILED — task '999' not found" in output
    assert "⚠️ 998: FAILED — task not found" in output
    assert "FAILED — unknown" not in output


@pytest.mark.asyncio
async def test_switch_and_wip_defaults_defer_to_persisted_base(monkeypatch):
    import app.mcp_stdio as m
    monkeypatch.setattr(m, "SCOPE", "/s")
    calls = []

    async def fake_api(method, path, **kwargs):
        calls.append((method, path, kwargs))
        if path.endswith("/switch-branch"):
            return {"ok": True, "branch": "task-91/coder"}
        return {
            "uncommitted": [], "unmerged_commits": [], "changed_files": [],
            "context_pct": 0, "status": "idle",
        }

    with patch.object(m, "_api", side_effect=fake_api):
        await m.switch_worker_branch(name="coder", task_id="91")
        await m.worker_wip(name="coder")

    assert calls[0][2]["json"]["from_ref"] == ""
    assert calls[0][2]["json"]["force"] is False
    assert calls[1][2]["params"]["base_ref"] == ""


@pytest.mark.asyncio
async def test_switch_worker_branch_forwards_explicit_force(monkeypatch):
    import app.mcp_stdio as m
    monkeypatch.setattr(m, "SCOPE", "/s")
    captured = {}

    async def fake_api(_method, _path, **kwargs):
        captured.update(kwargs["json"])
        return {"ok": True, "branch": "task-91/coder"}

    with patch.object(m, "_api", side_effect=fake_api):
        await m.switch_worker_branch(name="coder", task_id="91", force=True)

    assert captured["force"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [
    {"ok": False, "error": "target branch is busy"},
    {
        "ok": False,
        "state": "rollback_failed",
        "error": "checkout failed; rollback failed: restore HEAD denied",
        "actual_branch": "task-90/coder",
    },
])
async def test_switch_worker_branch_renders_failure_without_new_contract(
    monkeypatch, payload,
):
    import app.mcp_stdio as m
    monkeypatch.setattr(m, "SCOPE", "/s")

    async def fake_api(_method, _path, **_kwargs):
        return payload

    with patch.object(m, "_api", side_effect=fake_api):
        output = await m.switch_worker_branch(name="coder", task_id="91", force=True)

    assert output == f"Switch failed: {payload['error']}"


@pytest.mark.asyncio
async def test_kill_worker_force_param(monkeypatch):
    """force=True передаётся как строчный параметр в DELETE-запрос."""
    import app.mcp_stdio as m
    monkeypatch.setattr(m, "SCOPE", "/s")
    monkeypatch.setattr(m, "WORKER_NAME", "orch")
    captured = {}
    async def fake_api(method, path, **kw):
        captured["method"] = method
        captured["path"] = path
        captured["params"] = kw.get("params", {})
        return {"ok": True}
    with patch.object(m, "_api", side_effect=fake_api):
        await m.kill_worker(name="coder", force=True)
    assert captured["method"] == "DELETE"
    assert captured["path"] == "/api/sessions/coder"
    assert captured["params"]["force"] == "true"


@pytest.mark.asyncio
async def test_kill_worker_force_false_default(monkeypatch):
    """force=False (default) → params force='false'."""
    import app.mcp_stdio as m
    monkeypatch.setattr(m, "SCOPE", "/s")
    monkeypatch.setattr(m, "WORKER_NAME", "orch")
    captured = {}
    async def fake_api(method, path, **kw):
        captured["params"] = kw.get("params", {})
        return {"ok": True}
    with patch.object(m, "_api", side_effect=fake_api):
        await m.kill_worker(name="coder")
    assert captured["params"]["force"] == "false"


@pytest.mark.asyncio
async def test_send_message_cross_scope_warning(monkeypatch):
    """Если worker принадлежит другому parent → warning в ответе."""
    import app.mcp_stdio as m
    monkeypatch.setattr(m, "SCOPE", "/s")
    monkeypatch.setattr(m, "WORKER_NAME", "orch-a")
    async def fake_api(method, path, **kw):
        return {"ok": True, "parent_name": "orch-b"}
    with patch.object(m, "_api", side_effect=fake_api):
        out = await m.send_message(to="coder", message="hi")
    assert "⚠️" in out or "warning" in out.lower() or "orch-b" in out


@pytest.mark.asyncio
async def test_send_message_same_parent_no_warning(monkeypatch):
    """Сообщение воркеру того же родителя → нет предупреждения."""
    import app.mcp_stdio as m
    monkeypatch.setattr(m, "SCOPE", "/s")
    monkeypatch.setattr(m, "WORKER_NAME", "orch-a")
    async def fake_api(method, path, **kw):
        return {"ok": True, "parent_name": "orch-a"}
    with patch.object(m, "_api", side_effect=fake_api):
        out = await m.send_message(to="coder", message="hi")
    assert "⚠️" not in out


@pytest.mark.asyncio
async def test_list_agents_groups_by_parent(monkeypatch):
    """list_agents группирует сессии на Orchestrators / Your workers / Other workers."""
    import app.mcp_stdio as m
    monkeypatch.setattr(m, "SCOPE", "/s")
    monkeypatch.setattr(m, "WORKER_NAME", "orch-a")
    monkeypatch.setattr(m, "ROLE", "orchestrator")
    sessions = [
        {"name": "orch-a", "scope": "/s", "role": "orchestrator", "parent_name": "", "status": "idle", "model": "opus"},
        {"name": "my-coder", "scope": "/s", "role": "worker", "parent_name": "orch-a", "status": "idle", "model": "sonnet"},
        {"name": "their-coder", "scope": "/s", "role": "worker", "parent_name": "orch-b", "status": "idle", "model": "sonnet"},
    ]
    async def fake_api(method, path, **kw):
        if path == "/api/sessions":
            return sessions
        if path == "/api/role-icons":
            return {}
        return {}
    with patch.object(m, "_api", side_effect=fake_api):
        out = await m.list_agents()
    assert "## Orchestrators" in out
    assert "## Your workers" in out
    assert "## Other orchestrators' workers" in out
    assert "orch-a" in out
    assert "my-coder" in out
    assert "their-coder" in out


def test_cache_pill_uses_exact_and_approximate_runtime_policies():
    import app.mcp_stdio as m

    recent = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    expired = (datetime.now(timezone.utc) - timedelta(minutes=37)).isoformat()

    assert m._cache_pill({
        "status": "running",
        "cache_ttl_seconds": 1800,
        "cache_ttl_approximate": True,
    }) == "🔥 hot ≈30m"
    assert m._cache_pill({
        "status": "idle",
        "last_turn_ts": recent,
        "cache_ttl_seconds": 1800,
        "cache_ttl_approximate": True,
    }).startswith("🔥 hot ≈")
    assert m._cache_pill({
        "status": "idle",
        "last_turn_ts": expired,
        "cache_ttl_seconds": 1800,
        "cache_ttl_approximate": True,
    }) == "🧊? unknown (+7m past ≈30m)"
    assert m._cache_pill({
        "status": "idle",
        "last_turn_ts": expired,
        "cache_ttl_seconds": 3600,
        "cache_ttl_approximate": False,
    }).startswith("🟡 warm ")
    assert m._cache_pill({
        "status": "idle",
        "last_turn_ts": recent,
        "cache_ttl_seconds": 0,
        "cache_ttl_approximate": True,
    }) == ""
    assert m._cache_pill({"status": "running"}) == ""


def test_read_only_access_mode_hides_mutating_tools():
    import app.mcp_stdio as m

    visible = m._tool_names_for_access_mode(
        {"list_agents", "get_worker_logs", "send_message", "spawn_worker", "kill_worker"},
        "read-only",
    )

    assert visible == {"list_agents", "get_worker_logs"}


def test_full_access_mode_preserves_all_tools():
    import app.mcp_stdio as m

    names = {"list_agents", "send_message", "spawn_worker"}
    assert m._tool_names_for_access_mode(names, "full") == names


def test_unknown_access_mode_is_rejected():
    import app.mcp_stdio as m

    with pytest.raises(ValueError, match="ORCHESTRA_ACCESS_MODE"):
        m._tool_names_for_access_mode({"list_agents", "spawn_worker"}, "typo")


@pytest.mark.asyncio
async def test_bg_create_cron_command_sends_fail_closed_type(monkeypatch):
    import app.mcp_stdio as m

    monkeypatch.setattr(m, "SCOPE", "/scope")
    monkeypatch.setattr(m, "WORKER_NAME", "intent-hunter")
    captured = {}

    async def fake_api(method, path, **kwargs):
        captured.update(kwargs["json"])
        return {"id": "bg-monitor", "type": "cron_command", "status": "active"}

    with patch.object(m, "_api", side_effect=fake_api):
        result = await m.bg_create(
            type="cron_command",
            message="new intent found",
            cron_expr="*/15 * * * *",
            command="python3 monitor.py",
            pattern="^FOUND:",
            timeout_seconds=0,
        )

    assert captured == {
        "type": "cron_command",
        "config": {
            "cron_expr": "*/15 * * * *",
            "command": "python3 monitor.py",
            "pattern": "^FOUND:",
        },
        "message": "new intent found",
        "target_name": "intent-hunter",
        "target_scope": "/scope",
        "timeout_seconds": 0,
        "created_by": "intent-hunter",
    }
    assert "type=cron_command" in result
