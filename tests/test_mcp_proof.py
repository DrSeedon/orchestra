"""#281 — общий INTERNAL_TOKEN + поддельный X-Orchestra-Session-Id не делает оркестратора.

Оракул: «подделка проходит» на сегодняшнем коде. «Роут ответил 200» целью не является.
Не проверяем имя/роль из тела — это самообъявление (#276).
"""
from __future__ import annotations

import pytest
from starlette.requests import Request

from tests.test_acceptance import _session_row


def _req(*, session_id: str = "", proof: str = "", cookie: str = "") -> Request:
    headers: list[tuple[bytes, bytes]] = []
    if session_id:
        headers.append((b"x-orchestra-session-id", session_id.encode()))
    if proof:
        headers.append((b"x-orchestra-mcp-proof", proof.encode()))
    if cookie:
        headers.append((b"cookie", f"session={cookie}".encode()))
    return Request({"type": "http", "method": "POST", "path": "/", "headers": headers})


@pytest.fixture
def proof_db(tmp_path, monkeypatch):
    import app.db as dbmod
    import app.tm as tm

    monkeypatch.setattr(dbmod, "DB_PATH", tmp_path / "proof.db")
    dbmod.init_db()
    row = _session_row(str(tmp_path))
    row["id"] = "orch-session"
    row["name"] = "Orchestra-orchestrator"
    row["role"] = "orchestrator"
    row["is_orchestrator"] = 1
    dbmod.save_session(row)
    worker = dict(row)
    worker["id"] = "worker-session"
    worker["name"] = "worker"
    worker["role"] = "worker"
    worker["is_orchestrator"] = 0
    dbmod.save_session(worker)
    with tm._conn() as conn:
        tm.ensure_project(conn, "proj", scope="/scope")
    return tmp_path


def test_spoofed_session_id_cannot_waive(proof_db):
    """Сегодня True: HTTP верит заголовку сессии при общем токене."""
    from app.diff_budget import request_may_waive_diff_budget

    allowed = request_may_waive_diff_budget(_req(session_id="orch-session"))
    assert allowed is False, (
        "подделка X-Orchestra-Session-Id прошла как оркестратор — один curl"
    )


@pytest.mark.asyncio
async def test_spoofed_session_id_cannot_store_acceptance_command(proof_db):
    """HTTP POST с общим токеном не должен записать acceptance_command."""
    import app.tm as tm
    from app.routes.tm import TmTaskCreate, tm_create_task

    result = await tm_create_task(
        TmTaskCreate(
            title="spoof-acc",
            project="proj",
            scope="/scope",
            acceptance_command="true",
        ),
        _req(session_id="orch-session"),
    )
    status = getattr(result, "status_code", 200)
    assert status == 403, status
    with tm._conn() as conn:
        stored = conn.execute(
            "SELECT acceptance_command FROM tm_tasks WHERE title='spoof-acc'"
        ).fetchone()
    assert stored is None or stored["acceptance_command"] == ""


def test_bound_orchestrator_proof_may_waive(proof_db):
    from app.diff_budget import request_may_waive_diff_budget
    from app.mcp_proof import issue_mcp_proof

    proof = issue_mcp_proof("orch-session")
    assert request_may_waive_diff_budget(
        _req(session_id="orch-session", proof=proof),
    ) is True


def test_worker_proof_cannot_waive(proof_db):
    from app.diff_budget import request_may_waive_diff_budget
    from app.mcp_proof import issue_mcp_proof

    proof = issue_mcp_proof("worker-session")
    assert request_may_waive_diff_budget(
        _req(session_id="worker-session", proof=proof),
    ) is False
    assert request_may_waive_diff_budget(
        _req(session_id="orch-session", proof=proof),
    ) is False


@pytest.mark.asyncio
async def test_worker_and_spoofed_update_cannot_set_or_clear_acceptance(proof_db):
    import app.tm as tm
    from app.mcp_proof import issue_mcp_proof
    from app.routes.tm import TmTaskUpdate, tm_update_task

    with tm._conn() as conn:
        tm.create_task(conn, "proj", "protected", par_number=42, acceptance_command="true")

    for request in (
        _req(session_id="worker-session", proof=issue_mcp_proof("worker-session")),
        _req(session_id="orch-session"),
    ):
        result = await tm_update_task(
            "42", TmTaskUpdate(acceptance_command=""), request, project="proj",
        )
        assert result.status_code == 403

    with tm._conn() as conn:
        assert tm.get_task_by_par(conn, 42, "proj")["acceptance_command"] == "true"


@pytest.mark.asyncio
async def test_orchestrator_update_replaces_and_clears_acceptance(proof_db):
    import app.tm as tm
    from app.mcp_proof import issue_mcp_proof
    from app.routes.tm import TmTaskUpdate, tm_update_task

    with tm._conn() as conn:
        tm.create_task(conn, "proj", "editable", par_number=42, acceptance_command="true")
    request = _req(
        session_id="orch-session", proof=issue_mcp_proof("orch-session"),
    )

    result = await tm_update_task(
        "42", TmTaskUpdate(acceptance_command="false"), request, project="proj",
    )
    assert not hasattr(result, "status_code") or result.status_code == 200
    with tm._conn() as conn:
        assert tm.get_task_by_par(conn, 42, "proj")["acceptance_command"] == "false"

    result = await tm_update_task(
        "42", TmTaskUpdate(acceptance_command=""), request, project="proj",
    )
    assert not hasattr(result, "status_code") or result.status_code == 200
    with tm._conn() as conn:
        assert tm.get_task_by_par(conn, 42, "proj")["acceptance_command"] == ""


def test_dashboard_cookie_still_may_waive(proof_db, monkeypatch):
    from app.auth import create_session
    from app.diff_budget import request_may_waive_diff_budget

    monkeypatch.setenv("DASHBOARD_USER", "operator")
    monkeypatch.setenv("DASHBOARD_PASSWORD", "secret")
    assert request_may_waive_diff_budget(
        _req(cookie=create_session("operator")),
    ) is True


def test_reissue_invalidates_old_proof():
    from app.mcp_proof import check_mcp_proof, issue_mcp_proof

    first = issue_mcp_proof("sid-1")
    second = issue_mcp_proof("sid-1")
    assert first != second
    assert check_mcp_proof("sid-1", first) is False
    assert check_mcp_proof("sid-1", second) is True


@pytest.mark.asyncio
async def test_empty_acceptance_command_still_creates_without_proof(proof_db):
    import app.tm as tm
    from app.routes.tm import TmTaskCreate, tm_create_task

    result = await tm_create_task(
        TmTaskCreate(title="plain-task", project="proj", scope="/scope"),
        _req(session_id="worker-session"),
    )
    assert not hasattr(result, "status_code") or result.status_code == 200
    with tm._conn() as conn:
        stored = conn.execute(
            "SELECT acceptance_command FROM tm_tasks WHERE title='plain-task'"
        ).fetchone()
    assert stored is not None
    assert stored["acceptance_command"] == ""


def test_make_mcp_config_issues_proof_not_in_base_env():
    from app.manager import _make_mcp_config
    from app.mcp_proof import PROOF_ENV, check_mcp_proof
    from app.runtime_env import MCP_BASE_ENV

    assert PROOF_ENV not in MCP_BASE_ENV
    cfg = _make_mcp_config("w", "/s", "orchestrator", session_id="sid-cfg")
    proof = cfg["orchestra"]["env"].get(PROOF_ENV, "")
    assert proof
    assert check_mcp_proof("sid-cfg", proof) is True
