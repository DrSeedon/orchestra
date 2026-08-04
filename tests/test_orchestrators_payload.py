"""#71 — `/api/orchestrators` не таскает системный промпт: 92.8% веса, читателей нет.

Проверяются ОБА пути сборки ответа: активная сессия (через `to_dict()`) и строка из БД.
Половинчатый фикс — ровно та ошибка, которую #65 нашёл в уже «починенном» месте.
"""
import gzip
import json
import uuid
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

# Не «xxx…»: повторяющийся текст gzip схлопывает почти в ноль, и замер по проводу
# получился бы бессмысленным. Собираем псевдотекст, который жмётся как настоящий промпт.
import random as _r
_r.seed(71)
BIG_PROMPT = " ".join(
    "".join(_r.choice("абвгдеёжзийклмнопрстуфхцчшщыэюя") for _ in range(_r.randint(3, 12)))
    for _ in range(1800)
)


@pytest.fixture
def env(tmp_path, monkeypatch):
    import app.db as dbmod

    monkeypatch.setattr(dbmod, "DB_PATH", tmp_path / "t.db")
    dbmod.init_db()
    wt_root = tmp_path / "worktrees"
    wt_root.mkdir()
    monkeypatch.setattr("app.workspace.WORKTREE_ROOT", wt_root)
    return dbmod


def _orch(dbmod, name, sid=None):
    sid = sid or str(uuid.uuid4())
    dbmod.save_session({
        "id": sid, "name": name, "scope": f"/p/{name}", "cwd": f"/p/{name}",
        "model": "claude-sonnet-5[1m]", "system_prompt": BIG_PROMPT, "status": "idle",
        "session_id": None, "cost_usd": 0.0, "worktree_path": "", "branch": "",
        "base_branch": "main", "is_orchestrator": True, "color": "", "role": "orchestrator",
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


def test_db_path_has_no_prompt(env, client):
    """Строка из БД: путь `get_all_sessions()`."""
    _orch(env, "db-orch")
    body = client.get("/api/orchestrators").json()
    assert body and all("system_prompt" not in o for o in body)
    # Бутстрап поднимает своего оркестратора — сверяем присутствие своего, а не равенство
    assert "db-orch" in {o["name"] for o in body}


@pytest.mark.asyncio
async def test_active_session_path_has_no_prompt(env, client):
    """Активная сессия: путь `to_dict()`. Половина записей — самая частая форма фикса."""
    from app.main import manager

    sid = _orch(env, "live-orch")
    session = await manager.ensure_loaded_any("live-orch")
    assert session is not None and session.id == sid
    assert session.system_prompt, "предпосылка: у живой сессии промпт есть"

    body = client.get("/api/orchestrators").json()
    names = {o["name"] for o in body}
    assert "live-orch" in names, "активная сессия обязана быть в ответе"
    assert all("system_prompt" not in o for o in body)


def test_other_fields_survive(env, client):
    """Резали одно поле, а не структуру ответа."""
    _orch(env, "db-orch")
    o = client.get("/api/orchestrators").json()[0]
    for field in ("id", "name", "scope", "status", "cost_usd", "any_running", "any_waiting"):
        assert field in o, f"поле {field} потеряно"


def test_wire_weight_drops_below_the_envelope(env, client):
    """Замер по проводу: gzip -6, как отдаёт nginx."""
    for i in range(5):
        _orch(env, f"orch-{i}")
    body = client.get("/api/orchestrators").json()
    wire = len(gzip.compress(json.dumps(body, ensure_ascii=False).encode(), 6))

    with_prompt = [{**o, "system_prompt": BIG_PROMPT} for o in body]
    wire_before = len(gzip.compress(json.dumps(with_prompt, ensure_ascii=False).encode(), 6))
    print(f"\nпо проводу: было бы {wire_before} б, стало {wire} б")
    assert wire < 15 * 1024, "ответ обязан помещаться в надёжный конверт"
    assert wire < wire_before


def test_full_prompt_still_available_by_its_own_door(env, client):
    """Промпт не исчез из системы — за ним ходят в отдельный эндпоинт."""
    _orch(env, "db-orch")
    r = client.get("/api/sessions/db-orch/prompt", params={"scope": "/p/db-orch"})
    assert r.status_code == 200
    assert BIG_PROMPT in r.json()["system_prompt"]
