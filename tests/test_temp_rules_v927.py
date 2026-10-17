"""V-927/V-934 — временные правила: файл в git, промпт, срок, права, разовое уведомление, живая сессия."""

import asyncio
import subprocess
import sys
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import temp_rules
from tests.test_hot_apply import _run_one_turn, _worker
from tests.test_session import _MockBackend

ORCH_SCOPE = ROOT = B_SCOPE = ""  # real tmp git repos, set by the `env` fixture


def iso(delta_hours: float) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=delta_hours)).isoformat()


def session_row(name, *, scope=None, role="orchestrator", orch=True):
    scope = scope or ORCH_SCOPE
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
    this = sys.modules[__name__]
    for name in ("ORCH_SCOPE", "B_SCOPE", "ROOT"):
        repo = tmp_path / name.lower()
        repo.mkdir()
        for cmd in (["init", "-q", "-b", "main"], ["config", "user.name", "t"],
                    ["config", "user.email", "t@example.com"]):
            subprocess.run(["git", "-C", str(repo), *cmd], check=True)
        if name != "B_SCOPE":
            (repo / ".orchestra").mkdir()
            (repo / ".orchestra" / "layout.json").write_text("{}")
        (repo / "README").write_text("x")
        subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-qm", "init"], check=True)
        monkeypatch.setattr(this, name, str(repo))
    monkeypatch.setattr(temp_rules, "ORCHESTRA_SCOPE", ROOT)
    monkeypatch.setattr(temp_rules, "_migrated", False)
    temp_rules._warned.clear()
    db.init_db()
    actors = {
        "orch": session_row("orch-a"),
        "other": session_row("orch-b", scope=B_SCOPE),
        "root": session_row("Orchestra-orchestrator", scope=ROOT),
        "worker": session_row("w1", role="worker", orch=False),
    }
    for row in actors.values():
        db.save_session(row)
    return actors


def block(role="worker", is_orch=False, scope=None, name="w1"):
    return temp_rules.active_block(role=role, is_orch=is_orch, scope=scope or ORCH_SCOPE, name=name)


def test_rule_reaches_target_role_only(env):
    temp_rules.add_rule(env["orch"], "USE-SONNET", "why", ["workers"], "expires", iso(1))
    assert "USE-SONNET" in block("worker", False)
    assert "USE-SONNET" not in block("orchestrator", True, name="orch-a")
    assert "USE-SONNET" not in block("worker", False, scope=B_SCOPE)


def test_agent_and_role_targets(env):
    temp_rules.add_rule(env["orch"], "ONLY-W1", "why", ["agent:w1"], "expires", iso(1))
    temp_rules.add_rule(env["orch"], "ONLY-REVIEWER", "why", ["reviewer"], "expires", iso(1))
    assert "ONLY-W1" in block(name="w1") and "ONLY-W1" not in block(name="w2")
    assert "ONLY-REVIEWER" in block(role="reviewer") and "ONLY-REVIEWER" not in block()


def test_expired_rule_drops_without_cleanup_and_notify_rule_stays(env, monkeypatch):
    temp_rules.add_rule(env["orch"], "GONE", "why", ["all"], "expires", iso(1))
    temp_rules.add_rule(env["orch"], "STAYS", "why", ["all"], "review", iso(1))
    assert "GONE" in block() and "STAYS" in block()
    later = datetime.now(timezone.utc) + timedelta(hours=2)
    monkeypatch.setattr(temp_rules, "_now", lambda: later)
    assert "GONE" not in block()
    assert "STAYS" in block()


def test_invalid_rules_rejected(env):
    with pytest.raises(temp_rules.RuleError, match="past"):
        temp_rules.add_rule(env["orch"], "x", "why", ["all"], "expires", iso(-1))
    with pytest.raises(temp_rules.RuleError, match="text"):
        temp_rules.add_rule(env["orch"], "   ", "why", ["all"], "expires", iso(1))
    with pytest.raises(temp_rules.RuleError, match="timezone"):
        temp_rules.add_rule(env["orch"], "x", "why", ["all"], "expires", "2099-01-01T00:00:00")
    with pytest.raises(temp_rules.RuleError, match="targets"):
        temp_rules.add_rule(env["orch"], "x", "why", [], "expires", iso(1))


def test_permissions(env):
    def refused(call):
        with pytest.raises(temp_rules.RuleError) as caught:
            call()
        assert caught.value.status_code in (403, 404)  # a foreign project's rule is not even visible

    refused(lambda: temp_rules.add_rule(env["worker"], "x", "why", ["all"], "expires", iso(1)))
    refused(lambda: temp_rules.add_rule(env["orch"], "x", "why", ["all"], "expires", iso(1), project=B_SCOPE))
    refused(lambda: temp_rules.add_rule(env["orch"], "x", "why", ["all"], "expires", iso(1), project="*"))
    own = temp_rules.add_rule(env["orch"], "mine", "why", ["all"], "expires", iso(1))
    assert own["project"] == ORCH_SCOPE
    refused(lambda: temp_rules.remove_rule(env["other"], own["id"]))
    refused(lambda: temp_rules.update_rule(env["other"], own["id"], keep=True))
    everywhere = temp_rules.add_rule(env["root"], "global", "why", ["orchestrators"], "expires", iso(1), project="*")
    refused(lambda: temp_rules.remove_rule(env["orch"], everywhere["id"]))
    assert "global" in block("orchestrator", True, scope="/proj/b", name="orch-b")
    assert [r["id"] for r in temp_rules.list_rules(env["other"])] == [everywhere["id"]]
    temp_rules.remove_rule(env["orch"], own["id"])
    assert "mine" not in block()


def test_block_is_last_and_order_is_stable(env):
    a = temp_rules.add_rule(env["orch"], "FIRST", "why", ["all"], "expires", iso(1))
    temp_rules.add_rule(env["orch"], "SECOND", "why", ["all"], "expires", iso(2))
    agent = dict(role="worker", is_orch=False, scope=ORCH_SCOPE, name="w1")
    prompt = temp_rules.with_block("BASE\n\n<worker-memory>\nM\n</worker-memory>", **agent)
    assert prompt.rstrip().endswith("</temporary-rules>")
    assert prompt.index("FIRST") < prompt.index("SECOND")
    assert temp_rules.with_block(prompt, **agent) == prompt
    assert temp_rules.fingerprint(**agent) == temp_rules.block_fingerprint(prompt)
    temp_rules.remove_rule(env["orch"], a["id"])
    assert "FIRST" not in temp_rules.with_block(prompt, **agent)


def test_notice_sent_once_survives_restart_and_rearms_on_extend(env, monkeypatch):
    rule = temp_rules.add_rule(env["orch"], "R", "why", ["all"], "review", iso(1))
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
    temp_rules.add_rule(env["orch"], "R", "why", ["all"], "review", iso(1))
    monkeypatch.setattr(temp_rules, "_now", lambda: datetime.now(timezone.utc) + timedelta(hours=2))
    assert asyncio.run(temp_rules.notify_due(MagicMock(send=AsyncMock(side_effect=RuntimeError("down"))))) == 0
    assert asyncio.run(temp_rules.notify_due(MagicMock(send=AsyncMock()))) == 1


def test_keep_removes_deadline_and_stops_notices(env, monkeypatch):
    rule = temp_rules.add_rule(env["orch"], "K", "why", ["all"], "review", iso(1))
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
    rule = temp_rules.add_rule(env["orch"], "RULE-LIVE", "why", ["workers"], "expires", iso(1))
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
    body = {"text": "HTTP-RULE", "reason": "why", "targets": ["all"], "mode": "expires", "expires_at": iso(1)}

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


def test_reason_is_mandatory_in_every_mode(env):
    for mode, date in (("expires", iso(1)), ("review", iso(1)), ("permanent", "")):
        with pytest.raises(temp_rules.RuleError, match="reason"):
            temp_rules.add_rule(env["orch"], "x", "  ", ["all"], mode, date)


def test_permanent_mode_has_no_date_and_never_ends(env, monkeypatch):
    with pytest.raises(temp_rules.RuleError, match="no expires_at"):
        temp_rules.add_rule(env["orch"], "x", "why", ["all"], "permanent", iso(1))
    with pytest.raises(temp_rules.RuleError, match="required"):
        temp_rules.add_rule(env["orch"], "x", "why", ["all"], "review")
    with pytest.raises(temp_rules.RuleError, match="mode"):
        temp_rules.add_rule(env["orch"], "x", "why", ["all"], "forever", iso(1))
    rule = temp_rules.add_rule(env["orch"], "FOREVER", "why", ["all"], "permanent")
    assert rule["mode"] == "permanent" and rule["expires_at"] is None
    monkeypatch.setattr(temp_rules, "_now", lambda: datetime.now(timezone.utc) + timedelta(days=900))
    assert "FOREVER" in block()
    assert asyncio.run(temp_rules.notify_due(MagicMock(send=AsyncMock()))) == 0


def test_block_shows_mode_date_reason_and_author(env):
    temp_rules.add_rule(env["orch"], "T1", "REASON-ONE", ["all"], "expires", iso(1))
    temp_rules.add_rule(env["orch"], "T2", "REASON-TWO", ["all"], "review", iso(1))
    temp_rules.add_rule(env["orch"], "T3", "REASON-THREE", ["all"], "permanent")
    lines = {l.split()[1]: l for l in block().splitlines() if l.startswith("- ")}
    assert "expires" in lines["T1"] and "REASON-ONE" in lines["T1"]
    assert "review" in lines["T2"] and "REASON-TWO" in lines["T2"]
    assert "permanent" in lines["T3"] and "REASON-THREE" in lines["T3"]
    assert all("orch-a" in l for l in lines.values())


def test_orchestrator_module_reaches_orchestrators_not_workers():
    from app.pipeline import build_system_prompt

    assert "temp_rule_set" not in build_system_prompt("default", "worker")
    for role in ("orchestrator", "sub-orchestrator"):
        prompt = build_system_prompt("default", role)
        assert "temp_rule_set" in prompt, role
        # the static text must never contain the runtime block tag, or strip_block would eat it
        assert "<temporary-rules>" not in prompt, role


def _due_review_rule(env, monkeypatch, **kw):
    rule = temp_rules.add_rule(env["orch"], "R", "why", ["all"], "review", iso(1), **kw)
    monkeypatch.setattr(temp_rules, "_now", lambda: datetime.now(timezone.utc) + timedelta(hours=2))
    return rule


def _archive(db, row):
    db.save_session({**row, "status": "archived"})


def test_archived_author_notice_goes_to_live_project_orchestrator(env, monkeypatch):
    from app import db
    rule = _due_review_rule(env, monkeypatch)
    db.save_session(session_row("orch-a2", role="sub-orchestrator"))
    _archive(db, env["orch"])
    sender = MagicMock(send=AsyncMock())
    assert asyncio.run(temp_rules.notify_due(sender)) == 1
    assert sender.send.await_args.args[0] == "id-orch-a2"
    assert rule["id"] in sender.send.await_args.args[1]
    assert asyncio.run(temp_rules.notify_due(sender)) == 0


def test_global_rule_notice_of_gone_author_goes_to_orchestra_project_orchestrator(env, monkeypatch):
    from app import db
    temp_rules.add_rule(env["root"], "G", "why", ["all"], "review", iso(1), project="*")
    db.save_session(session_row("root-successor", scope=ROOT))
    monkeypatch.setattr(temp_rules, "_now", lambda: datetime.now(timezone.utc) + timedelta(hours=2))
    _archive(db, env["root"])
    sender = MagicMock(send=AsyncMock())
    assert asyncio.run(temp_rules.notify_due(sender)) == 1
    assert sender.send.await_args.args[0] == "id-root-successor"


def test_no_live_recipient_keeps_notice_pending_and_warns_once(env, monkeypatch, caplog):
    from app import db
    rule = _due_review_rule(env, monkeypatch)
    _archive(db, env["orch"])
    temp_rules._warned_no_recipient.clear()
    sender = MagicMock(send=AsyncMock())
    with caplog.at_level("WARNING", logger="app.temp_rules"):
        for _ in range(3):
            assert asyncio.run(temp_rules.notify_due(sender)) == 0
    assert sum(rule["id"] in r.getMessage() for r in caplog.records) == 1
    assert not sender.send.await_args_list
    # an orchestrator appears later → the same notice is delivered, not lost
    db.save_session(session_row("orch-new"))
    assert asyncio.run(temp_rules.notify_due(sender)) == 1


def git(repo, *args):
    return subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True, check=True).stdout


def rules_file(repo):
    return Path(repo) / ".orchestra" / "temp-rules.yaml"


def test_rule_is_written_to_the_project_file_and_committed_alone(env):
    (Path(ORCH_SCOPE) / "someone-elses.txt").write_text("dirty tree")
    (Path(ORCH_SCOPE) / "README").write_text("edited by someone")
    rule = temp_rules.add_rule(env["orch"], "IN-GIT", "because", ["all"], "expires", iso(1))
    assert "IN-GIT" in rules_file(ORCH_SCOPE).read_text() and rule["id"] in rules_file(ORCH_SCOPE).read_text()
    assert git(ORCH_SCOPE, "show", "--name-only", "--format=%s", "HEAD").split() [-1] == ".orchestra/temp-rules.yaml"
    assert rule["id"] in git(ORCH_SCOPE, "log", "-1", "--format=%s")
    status = git(ORCH_SCOPE, "status", "--porcelain")
    assert "someone-elses.txt" in status and "README" in status and "temp-rules" not in status
    assert not rules_file(B_SCOPE).exists()


def test_global_rule_lives_in_the_orchestra_repository(env):
    rule = temp_rules.add_rule(env["root"], "EVERYWHERE", "why", ["all"], "expires", iso(1), project="*")
    assert rule["id"] in rules_file(ROOT).read_text() and not rules_file(ORCH_SCOPE).exists()
    assert "EVERYWHERE" in block(scope=B_SCOPE)


def test_two_calls_in_a_row_both_land(env):
    errors = []

    def put(n):
        try:
            temp_rules.add_rule(env["orch"], f"RACE-{n}", "why", ["all"], "expires", iso(1))
        except Exception as error:  # noqa: BLE001
            errors.append(error)

    threads = [threading.Thread(target=put, args=(n,)) for n in range(6)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert not errors
    text = block()
    assert all(f"RACE-{n}" in text for n in range(6))
    assert git(ORCH_SCOPE, "log", "--format=%s").count("temp-rules: set") == 6


def test_hand_edit_is_honoured_and_bad_entries_are_skipped_once(env, caplog):
    temp_rules.add_rule(env["orch"], "GOOD", "why", ["all"], "expires", iso(1))
    path = rules_file(ORCH_SCOPE)
    path.write_text(path.read_text() + (
        "- id: rule-noreason\n  mode: permanent\n  targets: [all]\n  author: x\n  created_at: '2026-10-17'\n  text: NO-REASON\n"
        "- id: rule-nodate\n  mode: review\n  targets: [all]\n  author: x\n  created_at: '2026-10-17'\n  text: NO-DATE\n  reason: r\n"
        "- id: rule-hand\n  mode: permanent\n  targets: [all]\n  author: me\n  created_at: '2026-10-17'\n  text: HAND-ADDED\n  reason: r\n"))
    with caplog.at_level("WARNING", logger="app.temp_rules"):
        for _ in range(3):
            text = block()
    assert "GOOD" in text and "HAND-ADDED" in text and "NO-REASON" not in text and "NO-DATE" not in text
    warned = [r.getMessage() for r in caplog.records]
    assert sum("rule-noreason" in m for m in warned) == 1 and sum("rule-nodate" in m for m in warned) == 1


def test_broken_file_never_breaks_prompt_building(env):
    path = rules_file(ORCH_SCOPE)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("rules: [unclosed")
    assert block() == ""
    with pytest.raises(temp_rules.RuleError) as caught:
        temp_rules.add_rule(env["orch"], "x", "why", ["all"], "expires", iso(1))
    assert caught.value.status_code == 409


def test_global_entry_in_a_foreign_repository_is_ignored(env):
    path = rules_file(B_SCOPE)
    path.parent.mkdir(parents=True)
    path.write_text(
        "rules:\n- id: rule-evil\n  project: '*'\n  mode: permanent\n  targets: [all]\n  author: x\n"
        "  created_at: '2026-10-17'\n  text: FOREIGN-GLOBAL\n  reason: r\n")
    assert "FOREIGN-GLOBAL" not in block(scope=B_SCOPE) and "FOREIGN-GLOBAL" not in block()


def test_commit_is_refused_off_mainline_and_nothing_is_left_behind(env):
    git(ORCH_SCOPE, "checkout", "-q", "-b", "side")
    with pytest.raises(temp_rules.RuleError, match="mainline"):
        temp_rules.add_rule(env["orch"], "x", "why", ["all"], "expires", iso(1))
    assert not rules_file(ORCH_SCOPE).exists()


def test_failed_commit_restores_the_file(env):
    hook = Path(ORCH_SCOPE) / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\nexit 1\n")
    hook.chmod(0o755)
    with pytest.raises(temp_rules.RuleError, match="commit"):
        temp_rules.add_rule(env["orch"], "x", "why", ["all"], "expires", iso(1))
    assert not rules_file(ORCH_SCOPE).exists() and "temp-rules" not in git(ORCH_SCOPE, "status", "--porcelain")


def test_update_and_remove_are_committed_and_take_effect(env):
    rule = temp_rules.add_rule(env["orch"], "LIVE", "why", ["all"], "review", iso(1))
    temp_rules.update_rule(env["orch"], rule["id"], keep=True)
    assert "permanent" in rules_file(ORCH_SCOPE).read_text() and "permanent" in block()
    temp_rules.remove_rule(env["orch"], rule["id"])
    assert "LIVE" not in block() and "remove" in git(ORCH_SCOPE, "log", "-1", "--format=%s")


def test_database_table_is_moved_into_files_without_a_gap(env):
    from app import db
    with db._conn() as conn:
        conn.execute(
            """CREATE TABLE temp_rules (id TEXT PRIMARY KEY, text TEXT NOT NULL, project TEXT NOT NULL,
            targets TEXT NOT NULL, expires_at TEXT, on_expire TEXT NOT NULL, author_session_id TEXT NOT NULL,
            author_name TEXT NOT NULL, created_at TEXT NOT NULL, removed_at TEXT, notified_at TEXT,
            reason TEXT NOT NULL DEFAULT '')""")
        ins = "INSERT INTO temp_rules VALUES(?,?,?,?,?,?,?,?,?,?,?,?)"
        conn.execute(ins, ("rule-old-global", "OLD-GLOBAL", "*", '["orchestrators"]', iso(24), "remove",
                           "id-x", "Orchestra-orchestrator", iso(-1), None, None, "old reason"))
        conn.execute(ins, ("rule-old-local", "OLD-LOCAL", ORCH_SCOPE, '["all"]', None, "notify",
                           "id-x", "orch-a", iso(-1), None, None, ""))
        conn.execute(ins, ("rule-old-gone", "OLD-REMOVED", ORCH_SCOPE, '["all"]', iso(5), "remove",
                           "id-x", "orch-a", iso(-1), iso(-1), None, "r"))
        conn.execute(ins, ("rule-old-over", "OLD-EXPIRED", ORCH_SCOPE, '["all"]', iso(-5), "remove",
                           "id-x", "orch-a", iso(-9), None, None, "r"))
    first = block("orchestrator", True, name="orch-a")
    assert "OLD-GLOBAL" in first and "OLD-LOCAL" in first
    assert "OLD-REMOVED" not in first and "OLD-EXPIRED" not in first
    assert "old reason" in first and "OLD-GLOBAL" in rules_file(ROOT).read_text()
    assert "move rules from the database" in git(ROOT, "log", "-1", "--format=%s")
    with db._conn() as conn:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "temp_rules" not in tables and "temp_rules_moved_to_git" in tables
    temp_rules._migrated = False  # another process: nothing left to move, nothing duplicated
    assert block("orchestrator", True, name="orch-a") == first
    assert rules_file(ROOT).read_text().count("rule-old-global") == 1


def test_project_without_orchestra_layout_is_refused_not_broken(env):
    other = session_row("orch-b2", scope=B_SCOPE)
    with pytest.raises(temp_rules.RuleError, match="layout"):
        temp_rules.add_rule(other, "x", "why", ["all"], "expires", iso(1))
    assert not (Path(B_SCOPE) / ".orchestra").exists()
