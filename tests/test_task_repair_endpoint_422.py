from types import SimpleNamespace

import pytest


class _Request:
    def __init__(self, *, token: str | None, payload: object, store=None):
        headers = [] if token is None else [("authorization", f"Bearer {token}")]
        self.headers = dict(headers)
        self.app = SimpleNamespace(
            state=SimpleNamespace(
                knowledge_runtime=SimpleNamespace(task_store=store),
            ),
        )
        self._payload = payload

    async def json(self):
        return self._payload


@pytest.mark.asyncio
@pytest.mark.parametrize("token", [None, "wrong-token"])
async def test_repair_endpoint_requires_internal_token(monkeypatch, token):
    from app.routes import tm as routes

    monkeypatch.setenv("INTERNAL_TOKEN", "repair-token")
    called = False

    def unexpected_repair(*_args, **_kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(routes._tm, "repair_shadow_task_drift", unexpected_repair)
    response = await routes.tm_repair_shadow_drift(
        _Request(token=token, payload={"expected_refs": []}),
    )

    assert response.status_code == 403
    assert response.body == b'{"error":"internal token required"}'
    assert called is False


@pytest.mark.asyncio
async def test_repair_endpoint_uses_live_runtime_task_store(monkeypatch):
    from app.routes import tm as routes

    monkeypatch.setenv("INTERNAL_TOKEN", "repair-token")
    store = object()
    expected_refs = [{"project_id": "project", "par_number": 412}]
    captured = {}

    def repair(store_arg, *, expected_refs):
        captured["store"] = store_arg
        captured["expected_refs"] = expected_refs
        return {"ok": True, "changed": 0, "idempotent": True, "items": [], "errors": []}

    monkeypatch.setattr(routes._tm, "repair_shadow_task_drift", repair)
    response = await routes.tm_repair_shadow_drift(
        _Request(token="repair-token", payload={"expected_refs": expected_refs}, store=store),
    )

    assert response == {
        "ok": True,
        "changed": 0,
        "idempotent": True,
        "items": [],
        "errors": [],
    }
    assert captured == {"store": store, "expected_refs": expected_refs}


def test_repair_uses_process_task_binding_lock(monkeypatch):
    from app import tm

    class RecordingLock:
        entered = False

        def __enter__(self):
            self.entered = True

        def __exit__(self, *_args):
            return False

    lock = RecordingLock()
    monkeypatch.setattr(tm, "_TASK_BINDING_LOCK", lock)
    monkeypatch.setattr(
        tm,
        "_repair_shadow_task_drift_unlocked",
        lambda *_args, **_kwargs: {"ok": True},
    )

    result = tm.repair_shadow_task_drift(
        object(), expected_refs=[{"project_id": "p", "par_number": 1}]
    )
    assert result == {"ok": True}
    assert lock.entered is True
