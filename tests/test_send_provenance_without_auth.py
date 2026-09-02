"""Чат дашборда на контуре БЕЗ авторизации не должен отвечать 403.

`#433` завёл гейт происхождения: сообщение без `sender` требует авторизованного
оператора. Но `validate_session` возвращает False, когда `DASHBOARD_USER`/
`DASHBOARD_PASSWORD` пусты (`app/auth.py:58-61`) — а это наша штатная конфигурация.
Фронт шлёт в `/send` только `{message, scope}`, поэтому гейт отвергал КАЖДОЕ
сообщение из дашборда, а не иногда.

Правило самого #433 говорит, что делать вместо отказа: отсутствующее происхождение
рисуется как `unknown`, НИКОГДА как `user`. Отказ — это не «не соврать», это
«не доставить»; `unknown` выполняет требование, не ломая доставку.
"""

import pytest


def _request(path="/api/sessions/target/send", headers=None):
    from starlette.requests import Request

    return Request({
        "type": "http",
        "method": "POST",
        "path": path,
        "headers": headers or [],
        "query_string": b"",
        "server": ("test", 80),
        "client": ("test", 1),
        "scheme": "http",
    })


@pytest.fixture
def wired(tmp_path, monkeypatch):
    from app import db
    from app.routes import sessions as routes
    from tests.test_message_delivery_receipts_380 import _session_record

    # Ровно наш контур: авторизация дашборда выключена, куки нет.
    monkeypatch.delenv("DASHBOARD_USER", raising=False)
    monkeypatch.delenv("DASHBOARD_PASSWORD", raising=False)
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "send-provenance.db")
    db.init_db()

    target = type("Target", (), {
        "id": "target-noauth", "name": "target", "scope": "/scope",
        "parent_name": "", "last_task_sender": "",
    })()
    db.save_session(_session_record(
        session_id=target.id, name=target.name, scope=target.scope, task_id="7",
    ))

    captured = []

    class Manager:
        sessions = {target.id: target}
        async def ensure_loaded(self, name, scope): return target
        async def ensure_loaded_any(self, name): return None
        async def send(self, session_id, message, *, provenance):
            captured.append(provenance)
        def _context_warning(self, sender): return ""

    monkeypatch.setattr(routes, "manager", Manager())
    return routes, captured


@pytest.mark.asyncio
async def test_senderless_send_without_auth_is_delivered_as_unknown(wired):
    """Доставка обязана состояться, а происхождение — быть честным."""
    routes, captured = wired

    result = await routes.send_message(
        "target", routes.SendRequest(message="из дашборда", scope="/scope"),
        request=_request(),
    )

    status = getattr(result, "status_code", 200)
    assert status != 403, (
        "чат дашборда отвергнут гейтом происхождения: на контуре без "
        "DASHBOARD_USER оператор недоказуем В ПРИНЦИПЕ, значит 403 постоянный"
    )
    assert captured, "сообщение не доставлено получателю"
    assert captured[0].origin == "unknown", (
        "происхождение недоказуемо — оно обязано быть unknown, а не user"
    )
    assert captured[0].senders == ("unknown",)


@pytest.mark.asyncio
async def test_sender_still_wins_over_the_unknown_fallback(wired):
    """Запасной путь не должен затирать честно названного отправителя."""
    routes, captured = wired

    await routes.send_message(
        "target",
        routes.SendRequest(message="от агента", scope="/scope", sender="worker-1"),
        request=_request(),
    )

    assert captured[0].origin == "agent"
    assert captured[0].senders == ("worker-1",)


@pytest.mark.asyncio
async def test_authenticated_operator_is_still_user_not_unknown(tmp_path, monkeypatch):
    """Там, где оператор ДОКАЗАН кукой, происхождение остаётся `user`."""
    from app import db
    from app.auth import create_session
    from app.routes import sessions as routes
    from tests.test_message_delivery_receipts_380 import _session_record

    monkeypatch.setenv("DASHBOARD_USER", "operator-noauth")
    monkeypatch.setenv("DASHBOARD_PASSWORD", "secret-noauth")
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "send-provenance-auth.db")
    db.init_db()

    target = type("Target", (), {
        "id": "target-auth", "name": "target", "scope": "/scope",
        "parent_name": "", "last_task_sender": "",
    })()
    db.save_session(_session_record(
        session_id=target.id, name=target.name, scope=target.scope,
    ))
    captured = []

    class Manager:
        sessions = {target.id: target}
        async def ensure_loaded(self, name, scope): return target
        async def ensure_loaded_any(self, name): return None
        async def send(self, session_id, message, *, provenance):
            captured.append(provenance)
        def _context_warning(self, sender): return ""

    monkeypatch.setattr(routes, "manager", Manager())
    token = create_session("operator-noauth")
    await routes.send_message(
        "target", routes.SendRequest(message="из дашборда", scope="/scope"),
        request=_request(headers=[(b"cookie", f"session={token}".encode())]),
    )

    assert captured[0].origin == "user"
    assert captured[0].senders == ("user",)
