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


def _save(dbmod, name, *, orch: bool, scope=SCOPE, sid=None, role="orchestrator"):
    sid = sid or str(uuid.uuid4())
    dbmod.save_session({
        "id": sid, "name": name, "scope": scope, "cwd": scope,
        "model": "claude-sonnet-5[1m]", "system_prompt": "", "status": "idle",
        "session_id": None, "cost_usd": 0.0, "worktree_path": "", "branch": "",
        "base_branch": "main", "is_orchestrator": orch, "color": "", "role": role,
        "created_at": datetime.now(timezone.utc).isoformat(), "finished_at": None,
        "task_id": "", "needs_switch": 0,
    })
    return sid


def _save_owner(dbmod, name="Orchestra-orchestrator", **kw):
    """Оркестратор самой платформы — единственный адресат баг-репортов (#362)."""
    from app.notify import platform_scope

    return _save(dbmod, name, orch=True, scope=platform_scope(), **kw)


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


def test_platform_owner_is_notified(env, client, monkeypatch):
    import app.db as dbmod
    from app.main import manager

    owner_id = _save_owner(dbmod)
    sent = []

    async def capture(sid, text, *, provenance):
        assert provenance.origin == "platform"
        sent.append((sid, text))

    monkeypatch.setattr(manager, "send", capture)
    body = _post(client, reporter="worker-7", title="Стор растёт без ограничения")

    print("\nУВЕДОМЛЕНИЕ:", sent[0][1] if sent else "НЕТ")
    assert body["notified"].startswith("сообщено оркестратору")
    assert sent and sent[0][0] == owner_id
    assert "Стор растёт без ограничения" in sent[0][1]
    assert "worker-7" in sent[0][1] and body["record_id"] in sent[0][1]
    assert SCOPE in sent[0][1], "владельцу нужен scope, откуда репорт"


def test_author_of_the_report_is_not_notified(env, client, monkeypatch):
    import app.db as dbmod
    from app.main import manager

    _save_owner(dbmod, name="Orchestra-orchestrator")
    sent = []

    async def capture(sid, text, *, provenance):
        assert provenance.origin == "platform"
        sent.append(sid)

    monkeypatch.setattr(manager, "send", capture)
    body = _post(client, reporter="Orchestra-orchestrator")
    print("\nАВТОР=АДРЕСАТ:", body["notified"])
    assert sent == [], "автору собственного репорта слать нечего"
    assert "автор репорта и адресат" in body["notified"]


def test_root_orchestrator_wins_over_sub_orchestrator(env, client, monkeypatch):
    """#362: саб-оркестратор перехватывал репорты только потому, что шёл раньше в списке."""
    import app.db as dbmod
    from app.main import manager
    from app.notify import platform_scope

    sub_id = _save(dbmod, "dev-lead", orch=True, scope=platform_scope(),
                   role="sub-orchestrator")
    owner_id = _save_owner(dbmod)
    assert sub_id != owner_id
    sent = []

    async def capture(sid, text, *, provenance):
        assert provenance.origin == "platform"
        sent.append(sid)

    monkeypatch.setattr(manager, "send", capture)
    body = _post(client, reporter="worker-7")
    assert sent == [owner_id], f"уведомление ушло саб-оркестратору: {body['notified']}"


def test_no_orchestrator_is_said_out_loud_and_nobody_is_invented(env, client, monkeypatch, caplog):
    from app.main import manager

    sent = []

    async def capture(sid, text, *, provenance):
        assert provenance.origin == "platform"
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

    orch_id = _save_owner(dbmod)

    async def boom(sid, text, *, provenance):
        assert provenance.origin == "platform"
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

    _save_owner(dbmod)
    sent = []

    async def capture(sid, text, *, provenance):
        assert provenance.origin == "platform"
        sent.append(text)

    monkeypatch.setattr(manager, "send", capture)
    first = _post(client, reporter="worker-7", title="Первый")
    second = _post(client, reporter="worker-7", title="Второй")

    assert len(sent) == 2, "два репорта — два уведомления, это не дубль"
    assert first["record_id"] != second["record_id"]
    assert sum(1 for t in sent if first["record_id"] in t) == 1, "повторов на запись нет"


def test_cross_project_report_goes_to_the_platform_owner(env, client, monkeypatch):
    """Репорт чужого проекта — про ПЛАТФОРМУ; чинит владелец Orchestra, не свой оркестратор.

    Прежнее поведение было обратным (адресат по scope репортёра) и отменено решением
    юзера 20.08: `report_bug` принимает только сбои платформы.
    """
    import app.db as dbmod
    from app.main import manager

    owner_id = _save_owner(dbmod)
    theirs = _save(dbmod, "seedon-orchestrator", orch=True,
                   scope="/home/kesha/projects/seedon")
    sent = []

    async def capture(sid, text, *, provenance):
        assert provenance.origin == "platform"
        sent.append(sid)

    monkeypatch.setattr(manager, "send", capture)
    body = _post(client, reporter="seo-cro", scope="/home/kesha/projects/seedon")
    assert sent == [owner_id], f"уведомление ушло не туда: {body['notified']}"
    assert theirs not in sent, "оркестратор чужого проекта платформенный баг не чинит"
