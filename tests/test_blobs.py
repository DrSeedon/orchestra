"""#78 — тело картинки уезжает в файл, журнал хранит ссылку.

Главный тест задачи стоит первым: рабочая копия воркера удалена, а картинка на месте.
Именно поэтому копируются БАЙТЫ из строки, а не файл по пути из соседней строки журнала.
"""
import base64
import hashlib
import json
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

PNG = base64.b64encode(bytes(range(256)) * 40).decode()  # 10 КБ «картинки»


def _row(payload=PNG, media="image/png"):
    """Форма из живой БД: python-repr, БЕЗ префикса `data:image`."""
    return ("{'type': 'image', 'source': {'type': 'base64', 'data': '"
            + payload + f"', 'media_type': '{media}'}}}}")


@pytest.fixture
def env(tmp_path, monkeypatch):
    import app.blobs as blobs
    import app.db as dbmod

    monkeypatch.setattr(dbmod, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(blobs, "BLOB_ROOT", tmp_path / "blobs")
    dbmod.init_db()
    return {"db": dbmod, "blobs": blobs, "root": tmp_path}


def test_image_survives_deletion_of_the_worktree(env):
    """ГЛАВНЫЙ сценарий: рабочей копии больше нет, а картинка открывается."""
    worktree = env["root"] / "worktrees" / "worker"
    worktree.mkdir(parents=True)
    source = worktree / "screenshot.png"
    source.write_bytes(base64.b64decode(PNG))

    stored = env["blobs"].store_images("s1", _row())
    shutil.rmtree(worktree)  # Orchestra штатно сносит рабочие копии после мержа

    sha = re.search(r"'blob': '([0-9a-f]{64})'", stored).group(1)
    path = env["blobs"].blob_path("s1", sha, "image/png")
    print(f"\nworktree удалён: {not source.exists()}; блоб на месте: {path.exists()}")
    assert not source.exists()
    assert path.read_bytes() == base64.b64decode(PNG), "байты обязаны совпадать до байта"


def test_row_becomes_small_and_keeps_the_shape(env):
    stored = env["blobs"].store_images("s1", _row())
    print(f"\nбыло {len(_row())} б, стало {len(stored)} б: {stored[:120]}")
    assert len(stored) < 1024 and len(_row()) > 10000
    assert "'type': 'blob'" in stored and "'media_type': 'image/png'" in stored
    assert "'bytes': 10240" in stored


def test_same_picture_twice_is_one_file(env):
    env["blobs"].store_images("s1", _row())
    env["blobs"].store_images("s1", _row())
    files = list((env["blobs"].BLOB_ROOT / "s1").glob("*"))
    assert len(files) == 1, f"дедупликация по содержимому не сработала: {files}"


def test_non_image_content_is_untouched(env):
    plain = "1\tobject = {'type': 'text'}\n2\tничего интересного"
    assert env["blobs"].store_images("s1", plain) == plain


def test_storage_failure_keeps_the_body_and_says_so(env, monkeypatch, caplog):
    """Картинка важнее экономии: не записался блоб — в журнал уходит исходное тело."""
    import logging

    monkeypatch.setattr(env["blobs"].Path, "mkdir",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("диск только на чтение")))
    with caplog.at_level(logging.WARNING):
        stored = env["blobs"].store_images("s1", _row())
    print("\nПРИ СБОЕ:", [r.getMessage()[:80] for r in caplog.records][:1])
    assert stored == _row(), "содержимое обязано остаться целым"
    assert any("blob store failed" in r.getMessage() for r in caplog.records)


def test_blobs_die_with_their_session(env):
    from app.db import delete_session, save_session

    sid = str(uuid.uuid4())
    save_session({
        "id": sid, "name": "worker", "scope": "/s", "cwd": "/s",
        "model": "claude-sonnet-5[1m]", "system_prompt": "", "status": "idle",
        "session_id": None, "cost_usd": 0.0, "worktree_path": "", "branch": "",
        "base_branch": "main", "is_orchestrator": False, "color": "",
        "created_at": datetime.now(timezone.utc).isoformat(), "finished_at": None,
        "task_id": "", "needs_switch": 0,
    })
    env["blobs"].store_images(sid, _row())
    assert env["blobs"].session_dir(sid).is_dir()

    delete_session(sid)
    assert not env["blobs"].session_dir(sid).exists(), "блоб не переживает свою строку"


def test_inventory_sees_both_sides(env):
    from app.db import add_log, save_session

    sid = str(uuid.uuid4())
    save_session({
        "id": sid, "name": "worker", "scope": "/s", "cwd": "/s",
        "model": "claude-sonnet-5[1m]", "system_prompt": "", "status": "idle",
        "session_id": None, "cost_usd": 0.0, "worktree_path": "", "branch": "",
        "base_branch": "main", "is_orchestrator": False, "color": "",
        "created_at": datetime.now(timezone.utc).isoformat(), "finished_at": None,
        "task_id": "", "needs_switch": 0,
    })
    # строка ссылается на блоб, которого нет — дыра в истории
    add_log(sid, datetime.now(timezone.utc), "tool_result",
            "{'type': 'blob', 'blob': '" + "a" * 64 + "', 'bytes': 10}")
    # блоб есть, строки нет — мусор
    env["blobs"].store_images(sid, _row())

    got = env["blobs"].inventory()
    print(f"\nинвентарь: {got['blobs']} блобов, мусора {len(got['orphan_blobs'])}, "
          f"дыр {len(got['missing_blobs'])}")
    assert len(got["orphan_blobs"]) == 1 and len(got["missing_blobs"]) == 1


@pytest.fixture
def client(env):
    from tests.conftest import make_backend_mock

    with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
        from app.main import app, manager

        manager.sessions.clear()
        with TestClient(app) as c:
            yield c


class TestBlobEndpoint:
    def test_serves_the_bytes(self, env, client):
        stored = env["blobs"].store_images("s1", _row())
        sha = re.search(r"'blob': '([0-9a-f]{64})'", stored).group(1)
        r = client.get(f"/api/blobs/s1/{sha}")
        assert r.status_code == 200
        assert r.content == base64.b64decode(PNG)
        assert "immutable" in r.headers.get("cache-control", "")

    def test_missing_blob_is_404(self, env, client):
        assert client.get(f"/api/blobs/s1/{'b' * 64}").status_code == 404

    @pytest.mark.parametrize("bad", ["../../etc/passwd", "не-хеш", "ab", "A" * 64])
    def test_path_traversal_and_junk_are_400(self, env, client, bad):
        r = client.get(f"/api/blobs/s1/{bad}")
        assert r.status_code in (400, 404), f"опасный адрес прошёл: {bad}"
        assert r.status_code != 200
