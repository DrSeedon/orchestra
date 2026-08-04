"""#56 — баг-репорт агента доходит до оркестратора его scope, а не только в стор.

Сценарий сквозной: настоящий HTTP-роут, настоящий стор (во временном каталоге), настоящий
`SessionManager`. Подменён только CLI-бэкенд — как и во всех тестах доставки.
"""
import json
import logging
import uuid
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

SCOPE = "/home/kesha/projects/чужой"


@pytest.fixture
def env(tmp_path, monkeypatch):
    import app.db as dbmod
    import app.routes.system as sysmod

    monkeypatch.setattr(dbmod, "DB_PATH", tmp_path / "t.db")
    dbmod.init_db()
    # приватный стор — во временный каталог, живой не трогаем
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setattr(sysmod, "_BUG_STATE_ROOT_CACHE", None, raising=False)
    return tmp_path


def _save(dbmod, name, *, orch: bool, scope=SCOPE, sid=None):
    sid = sid or str(uuid.uuid4())
    dbmod.save_session({
        "id": sid, "name": name, "scope": scope, "cwd": scope,
        "model": "claude-sonnet-5[1m]", "system_prompt": "", "status": "idle",
        "session_id": None, "cost_usd": 0.0, "worktree_path": "", "branch": "",
        "base_branch": "main", "is_orchestrator": orch, "color": "",
        "created_at": datetime.now(timezone.utc).isoformat(), "finished_at": None,
        "task_id": "", "needs_switch": 0,
    })
    return sid


@pytest.fixture
def client(env):
    from tests.conftest import make_backend_mock

    with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
        from app.main import app, manager

        manager.sessions.clear()
        with TestClient(app) as c:
            yield c


def _post(client, *, reporter, title="Тестовый репорт", scope=SCOPE):
    r = client.post("/api/report_bug", json={
        "title": title, "description": "- Location: x\n- Error: y",
        "reporter": reporter, "scope": scope,
    })
    assert r.status_code == 200, r.text
    return r.json()


def test_scope_orchestrator_is_notified(env, client, monkeypatch):
    import app.db as dbmod
    from app.main import manager

    orch_id = _save(dbmod, "чужой-orchestrator", orch=True)
    sent = []

    async def capture(sid, text):
        sent.append((sid, text))

    monkeypatch.setattr(manager, "send", capture)
    body = _post(client, reporter="worker-7", title="Стор растёт без ограничения")

    print("\nУВЕДОМЛЕНИЕ:", sent[0][1] if sent else "НЕТ")
    assert body["notified"].startswith("сообщено оркестратору")
    assert sent and sent[0][0] == orch_id
    assert "Стор растёт без ограничения" in sent[0][1]
    assert "worker-7" in sent[0][1] and body["record_id"] in sent[0][1]


def test_author_of_the_report_is_not_notified(env, client, monkeypatch):
    import app.db as dbmod
    from app.main import manager

    _save(dbmod, "чужой-orchestrator", orch=True)
    sent = []

    async def capture(sid, text):
        sent.append(sid)

    monkeypatch.setattr(manager, "send", capture)
    body = _post(client, reporter="чужой-orchestrator")
    print("\nАВТОР=АДРЕСАТ:", body["notified"])
    assert sent == [], "автору собственного репорта слать нечего"
    assert "автор репорта и адресат" in body["notified"]


def test_no_orchestrator_is_said_out_loud_and_nobody_is_invented(env, client, monkeypatch, caplog):
    from app.main import manager

    sent = []

    async def capture(sid, text):
        sent.append(sid)

    monkeypatch.setattr(manager, "send", capture)
    with caplog.at_level(logging.WARNING):
        body = _post(client, reporter="worker-7")
    print("\nБЕЗ ОРКЕСТРАТОРА:", body["notified"])
    assert sent == []
    assert "некому сообщить" in body["notified"]
    assert any("некому сообщить" in r.getMessage() for r in caplog.records)


def test_report_survives_a_failed_notification(env, client, monkeypatch):
    """Стор — первичен: репорт зарегистрирован, даже если уведомление отказало."""
    import app.db as dbmod
    from app.db import get_logs
    from app.main import manager

    orch_id = _save(dbmod, "чужой-orchestrator", orch=True)

    async def boom(sid, text):
        raise RuntimeError("auto-switch failed: branch already exists")

    monkeypatch.setattr(manager, "send", boom)
    body = _post(client, reporter="worker-7", title="Репорт при сломанной доставке")

    print("\nОТКАЗ ДОСТАВКИ:", body["notified"])
    assert body["record_id"] and "уведомить" in body["notified"]
    assert "RuntimeError" in body["notified"]
    # сам репорт лежит в сторе
    stored = client.get("/api/report_bug").text
    assert "Репорт при сломанной доставке" in stored
    # и остался след в истории адресата — канал сломан, а факт нет
    rows = [r for r in get_logs(orch_id, limit=20) if "[доставка]" in (r["content"] or "")]
    assert rows and "GET /api/report_bug" in rows[0]["content"]


def test_notification_is_sent_once_per_record(env, client, monkeypatch):
    import app.db as dbmod
    from app.main import manager

    _save(dbmod, "чужой-orchestrator", orch=True)
    sent = []

    async def capture(sid, text):
        sent.append(text)

    monkeypatch.setattr(manager, "send", capture)
    first = _post(client, reporter="worker-7", title="Первый")
    second = _post(client, reporter="worker-7", title="Второй")

    assert len(sent) == 2, "два репорта — два уведомления, это не дубль"
    assert first["record_id"] != second["record_id"]
    assert sum(1 for t in sent if first["record_id"] in t) == 1, "повторов на запись нет"


def test_cross_project_scope_reaches_its_own_orchestrator(env, client, monkeypatch):
    """Репорт из чужого проекта не должен уезжать к оркестратору Orchestra."""
    import app.db as dbmod
    from app.main import manager

    _save(dbmod, "Orchestra-orchestrator", orch=True, scope="/home/kesha/orchestra")
    theirs = _save(dbmod, "seedon-orchestrator", orch=True, scope="/home/kesha/projects/seedon")
    sent = []

    async def capture(sid, text):
        sent.append(sid)

    monkeypatch.setattr(manager, "send", capture)
    body = _post(client, reporter="seo-cro", scope="/home/kesha/projects/seedon")
    assert sent == [theirs], f"уведомление ушло не туда: {body['notified']}"
