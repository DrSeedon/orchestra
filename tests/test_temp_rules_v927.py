"""V-927 — временные правила: промпт, срок, права, разовое уведомление, живая сессия."""

import asyncio
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import temp_rules
from tests.test_hot_apply import _run_one_turn, _worker
from tests.test_session import _MockBackend

ORCH_SCOPE = "/proj/a"
ROOT = "/home/kesha/orchestra"


def iso(delta_hours: float) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=delta_hours)).isoformat()


def session_row(name, *, scope=ORCH_SCOPE, role="orchestrator", orch=True):
    return {
        "id": f"id-{name}", "name": name, "scope": scope, "cwd": scope, "model": "test",
        "system_prompt": "", "status": "idle", "session_id": None, "cost_usd": 0.0,
        "worktree_path": "", "branch": "", "base_branch": "main", "needs_switch": 0,
        "is_orchestrator": orch, "color": "", "role": role, "parent_id": "", "parent_name": "",
        "created_at": datetime.now(timezone.utc).isoformat(), "finished_at": None,
    }


@pytest.fixture
def env(tmp_path, monkeypatch):
    from app import db

    isolated = tmp_path / "rules.sqlite"
    real_connect = sqlite3.connect
    production = db._DEFAULT_DB_PATH.resolve()

    def guarded(database, *a, **k):
        if Path(str(database)).resolve() == production:
            raise AssertionError("temp rules test touched the production DB")
        return real_connect(database, *a, **k)

    monkeypatch.setattr(db, "DB_PATH", isolated)
    monkeypatch.setattr(sqlite3, "connect", guarded)
    monkeypatch.setattr(temp_rules, "ORCHESTRA_SCOPE", ROOT)
    db.init_db()
    actors = {
        "orch": session_row("orch-a"),
        "other": session_row("orch-b", scope="/proj/b"),
        "root": session_row("Orchestra-orchestrator", scope=ROOT),
        "worker": session_row("w1", role="worker", orch=False),
    }
    for row in actors.values():
        db.save_session(row)
    return actors


def block(role="worker", is_orch=False, scope=ORCH_SCOPE, name="w1"):
    return temp_rules.active_block(role=role, is_orch=is_orch, scope=scope, name=name)


def test_rule_reaches_target_role_only(env):
    temp_rules.add_rule(env["orch"], "USE-SONNET", ["workers"], iso(1))
    assert "USE-SONNET" in block("worker", False)
    assert "USE-SONNET" not in block("orchestrator", True, name="orch-a")
    assert "USE-SONNET" not in block("worker", False, scope="/proj/b")


def test_agent_and_role_targets(env):
    temp_rules.add_rule(env["orch"], "ONLY-W1", ["agent:w1"], iso(1))
    temp_rules.add_rule(env["orch"], "ONLY-REVIEWER", ["reviewer"], iso(1))
    assert "ONLY-W1" in block(name="w1") and "ONLY-W1" not in block(name="w2")
    assert "ONLY-REVIEWER" in block(role="reviewer") and "ONLY-REVIEWER" not in block()


def test_expired_rule_drops_without_cleanup_and_notify_rule_stays(env, monkeypatch):
    temp_rules.add_rule(env["orch"], "GONE", ["all"], iso(1))
    temp_rules.add_rule(env["orch"], "STAYS", ["all"], iso(1), on_expire="notify")
    assert "GONE" in block() and "STAYS" in block()
    later = datetime.now(timezone.utc) + timedelta(hours=2)
    monkeypatch.setattr(temp_rules, "_now", lambda: later)
    assert "GONE" not in block()
    assert "STAYS" in block()


def test_invalid_rules_rejected(env):
    with pytest.raises(temp_rules.RuleError, match="past"):
        temp_rules.add_rule(env["orch"], "x", ["all"], iso(-1))
    with pytest.raises(temp_rules.RuleError, match="text"):
        temp_rules.add_rule(env["orch"], "   ", ["all"], iso(1))
    with pytest.raises(temp_rules.RuleError, match="timezone"):
        temp_rules.add_rule(env["orch"], "x", ["all"], "2099-01-01T00:00:00")
    with pytest.raises(temp_rules.RuleError, match="targets"):
        temp_rules.add_rule(env["orch"], "x", [], iso(1))


def test_permissions(env):
    def refused(call):
        with pytest.raises(temp_rules.RuleError) as caught:
            call()
        assert caught.value.status_code == 403

    refused(lambda: temp_rules.add_rule(env["worker"], "x", ["all"], iso(1)))
    refused(lambda: temp_rules.add_rule(env["orch"], "x", ["all"], iso(1), project="/proj/b"))
    refused(lambda: temp_rules.add_rule(env["orch"], "x", ["all"], iso(1), project="*"))
    own = temp_rules.add_rule(env["orch"], "mine", ["all"], iso(1))
    assert own["project"] == ORCH_SCOPE
    refused(lambda: temp_rules.remove_rule(env["other"], own["id"]))
    refused(lambda: temp_rules.update_rule(env["other"], own["id"], keep=True))
    everywhere = temp_rules.add_rule(env["root"], "global", ["orchestrators"], iso(1), project="*")
    refused(lambda: temp_rules.remove_rule(env["orch"], everywhere["id"]))
    assert "global" in block("orchestrator", True, scope="/proj/b", name="orch-b")
    assert [r["id"] for r in temp_rules.list_rules(env["other"])] == [everywhere["id"]]
    temp_rules.remove_rule(env["orch"], own["id"])
    assert "mine" not in block()


def test_block_is_last_and_order_is_stable(env):
    a = temp_rules.add_rule(env["orch"], "FIRST", ["all"], iso(1))
    temp_rules.add_rule(env["orch"], "SECOND", ["all"], iso(2))
    agent = dict(role="worker", is_orch=False, scope=ORCH_SCOPE, name="w1")
    prompt = temp_rules.with_block("BASE\n\n<worker-memory>\nM\n</worker-memory>", **agent)
    assert prompt.rstrip().endswith("</temporary-rules>")
    assert prompt.index("FIRST") < prompt.index("SECOND")
    assert temp_rules.with_block(prompt, **agent) == prompt
    assert temp_rules.fingerprint(**agent) == temp_rules.block_fingerprint(prompt)
    temp_rules.remove_rule(env["orch"], a["id"])
    assert "FIRST" not in temp_rules.with_block(prompt, **agent)


def test_notice_sent_once_survives_restart_and_rearms_on_extend(env, monkeypatch):
    rule = temp_rules.add_rule(env["orch"], "R", ["all"], iso(1), on_expire="notify")
    sender = MagicMock(send=AsyncMock())
    assert asyncio.run(temp_rules.notify_due(sender)) == 0
    later = datetime.now(timezone.utc) + timedelta(hours=2)
    monkeypatch.setattr(temp_rules, "_now", lambda: later)
    assert asyncio.run(temp_rules.notify_due(sender)) == 1
    assert sender.send.await_args.args[0] == env["orch"]["id"]
    assert rule["id"] in sender.send.await_args.args[1]
    # a fresh process reads the same DB mark → no second notice
    assert asyncio.run(temp_rules.notify_due(MagicMock(send=AsyncMock()))) == 0
    temp_rules.update_rule(env["orch"], rule["id"], expires_at=(later + timedelta(hours=1)).isoformat())
    monkeypatch.setattr(temp_rules, "_now", lambda: later + timedelta(hours=2))
    assert asyncio.run(temp_rules.notify_due(sender)) == 1


def test_failed_delivery_is_retried_not_lost(env, monkeypatch):
    temp_rules.add_rule(env["orch"], "R", ["all"], iso(1), on_expire="notify")
    monkeypatch.setattr(temp_rules, "_now", lambda: datetime.now(timezone.utc) + timedelta(hours=2))
    assert asyncio.run(temp_rules.notify_due(MagicMock(send=AsyncMock(side_effect=RuntimeError("down"))))) == 0
    assert asyncio.run(temp_rules.notify_due(MagicMock(send=AsyncMock()))) == 1


def test_keep_removes_deadline_and_stops_notices(env, monkeypatch):
    rule = temp_rules.add_rule(env["orch"], "K", ["all"], iso(1), on_expire="notify")
    kept = temp_rules.update_rule(env["orch"], rule["id"], keep=True)
    assert kept["expires_at"] is None
    monkeypatch.setattr(temp_rules, "_now", lambda: datetime.now(timezone.utc) + timedelta(days=30))
    assert "K" in block()
    assert asyncio.run(temp_rules.notify_due(MagicMock(send=AsyncMock()))) == 0


@pytest.mark.asyncio
async def test_live_session_gets_and_loses_rule(env, monkeypatch):
    import app.manager as manager
    monkeypatch.setattr("app.session.save_session", MagicMock())
    monkeypatch.setattr("app.session.add_log", MagicMock(return_value=1))
    monkeypatch.setattr("app.bg_jobs.bg_manager", None)
    monkeypatch.setattr(manager, "ROLE_SYSTEM_PROMPT", lambda *a, **k: "BASE")

    def live():
        s = _worker(prompt_overlay="")
        s.scope = ORCH_SCOPE
        s._current_prompt = "BASE"
        s._prompt_injected = True
        return s

    s = live()
    assert "RULE-LIVE" not in await _run_one_turn(s, _MockBackend())
    rule = temp_rules.add_rule(env["orch"], "RULE-LIVE", ["workers"], iso(1))
    sent = await _run_one_turn(s, _MockBackend())
    assert "RULE-LIVE" in sent and "role instructions were updated" in sent
    assert s._current_prompt.rstrip().endswith("</temporary-rules>")

    temp_rules.remove_rule(env["orch"], rule["id"])
    sent = await _run_one_turn(s, _MockBackend())
    assert "RULE-LIVE" not in sent and "role instructions were updated" in sent
    again = await _run_one_turn(s, _MockBackend())
    assert "role instructions were updated" not in again


def test_http_route_enforces_proof_and_scope(env, monkeypatch):
    from app.mcp_proof import issue_mcp_proof
    from app.routes.temp_rules import router

    monkeypatch.setenv("INTERNAL_TOKEN", "tok-927")
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    body = {"text": "HTTP-RULE", "targets": ["all"], "expires_at": iso(1)}

    def headers(actor, proof=None):
        return {"x-orchestra-session-id": actor["id"],
                "x-orchestra-mcp-proof": proof or issue_mcp_proof(actor["id"])}

    assert client.post("/api/temp-rules", json=body).status_code == 403
    assert client.post("/api/temp-rules", json=body, headers=headers(env["orch"], "forged")).status_code == 403
    assert client.post("/api/temp-rules", json={**body, "project": "*"}, headers=headers(env["orch"])).status_code == 403
    assert client.post("/api/temp-rules", json={**body, "project": "*"}, headers=headers(env["root"])).status_code == 200
    assert client.post("/api/temp-rules", json={**body, "expires_at": iso(-1)}, headers=headers(env["orch"])).status_code == 422
    listed = client.get("/api/temp-rules", headers=headers(env["other"])).json()
    assert [r["text"] for r in listed] == ["HTTP-RULE"]
