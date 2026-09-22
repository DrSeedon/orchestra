"""V-576: миграция выполняется самим сервисом при старте.

От владельца требуется один рестарт и ни одной команды на остановленной системе,
поэтому проверяется именно то, что ломается молча: старт на немигрированных данных
доводит оба хранилища до рабочего состояния, а повторный старт не делает ничего.
"""
import json
import pathlib
import sqlite3
import subprocess
import uuid

import pytest

from app import db, project_catalog, tm
from app.startup_migration import MigrationError, migrate_v576
from app.task_runtime import TaskRuntime, task_runtime_mode
from app.task_store import TaskStore


_CATALOG = """
version: 1
projects:
  - tag: alpha
    name: Alpha
    scope: /alpha
    write_namespace: alpha-vps
    namespaces:
      alpha-vps: ""
      alpha-laptop: ноутбук
"""


def _legacy_record(namespace: str, number: int, title: str) -> dict:
    now = "2026-09-01T00:00:00+00:00"
    return {
        "schema_version": 1, "id": str(uuid.uuid4()), "project_id": namespace,
        "origin": "", "number": number, "title": title, "description": "",
        "status": "new", "priority": 2, "assignee": "", "price_rub": 0,
        "acceptance": {"command": "", "manifest_paths": [], "required": False},
        "git_commits": [], "evidence_refs": [], "completed_at": None,
        "created_at": now, "updated_at": now,
        "creation_key": f"legacy-{namespace}-{number}",
        "creation_fingerprint": "0" * 64,
    }


@pytest.fixture
def legacy_install(tmp_path, monkeypatch, _isolate_project_catalog):
    _isolate_project_catalog.write_text(_CATALOG, encoding="utf-8")
    project_catalog.reset_cache()

    database = tmp_path / "orchestra.db"
    monkeypatch.setattr(db, "DB_PATH", database)
    db.init_db()
    # Точное состояние ДО V-576: колонки проекции нет, версия схемы прежняя.
    with sqlite3.connect(database) as connection:
        connection.execute("ALTER TABLE tm_tasks DROP COLUMN tags")
        connection.execute("PRAGMA user_version=2")

    root = tmp_path / "tasks"
    (root / "projects" / "alpha-vps" / "tasks").mkdir(parents=True)
    (root / "projects" / "alpha-laptop" / "tasks").mkdir(parents=True)
    (root / "projects" / "unknown-ns" / "tasks").mkdir(parents=True)
    (root / "task-store.json").write_text(json.dumps({"schema_version": 1}) + "\n")
    records = [
        _legacy_record("alpha-vps", 1, "current work"),
        _legacy_record("alpha-laptop", 1, "laptop work"),
        _legacy_record("unknown-ns", 1, "outside the catalog"),
    ]
    for record in records:
        path = root / "projects" / record["project_id"] / "tasks" / f"{record['id']}.json"
        path.write_text(json.dumps(record, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    subprocess.run(["git", "init", "--initial-branch=main", str(root)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(root), "config", "user.name", "Legacy"], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.email", "legacy@example.invalid"], check=True)
    subprocess.run(["git", "-C", str(root), "add", "."], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(root), "commit", "-m", "legacy store"], check=True, capture_output=True)
    return database, root, records


def _head(root):
    return subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
                          capture_output=True, text=True, check=True).stdout.strip()


def test_startup_migrates_legacy_data_and_the_service_works(legacy_install, monkeypatch):
    database, root, records = legacy_install

    result = migrate_v576(database, root)

    assert result["state"] == "migrated"
    assert result["store"] == {**result["store"], "tagged": 2, "untagged": 1, "files": 3}
    backup = database.with_name(result["backup"].rsplit("/", 1)[-1])
    assert backup.is_file() and backup != database

    assert json.loads((root / "task-store.json").read_text()) == {"schema_version": 2}
    with sqlite3.connect(database) as connection:
        assert int(connection.execute("PRAGMA user_version").fetchone()[0]) == 3
        columns = {r[1] for r in connection.execute("PRAGMA table_info(tm_tasks)")}
    assert "tags" in columns

    # Хранилище читается, проецируется и фильтруется по тегу — то есть работает.
    monkeypatch.setattr(db, "DB_PATH", database)
    store = TaskStore(root, origin="")
    with task_runtime_mode(TaskRuntime(store, database)):
        with db._conn() as connection:
            tm.sync_catalog(connection)
        tagged = {t["title"] for t in tm.api_list_tasks(tags=["alpha"])["tasks"]}
        assert tagged == {"current work", "laptop work"}
        assert {r["tags"][0] for r in store.list() if r["tags"]} == {"alpha"}
        assert [r["title"] for r in store.list() if not r["tags"]] == ["outside the catalog"]


def test_second_start_changes_nothing(legacy_install):
    database, root, _records = legacy_install

    first = migrate_v576(database, root)
    head_after_first = _head(root)
    backups_after_first = sorted(p.name for p in database.parent.glob("*pre-v576*"))

    second = migrate_v576(database, root)

    assert first["state"] == "migrated"
    assert second == {"state": "already"}
    assert _head(root) == head_after_first
    assert sorted(p.name for p in database.parent.glob("*pre-v576*")) == backups_after_first


def test_a_dirty_task_store_refuses_instead_of_mixing_changes_in(legacy_install):
    database, root, records = legacy_install
    stray = root / "projects" / "alpha-vps" / "tasks" / "stray.json"
    stray.write_text("{}\n")

    with pytest.raises(MigrationError, match="uncommitted"):
        migrate_v576(database, root)

    assert json.loads((root / "task-store.json").read_text()) == {"schema_version": 1}


def test_a_store_of_another_installation_refuses(legacy_install, tmp_path_factory):
    """Авария 22.09.2026: база была тестовая, а хранилище — боевое, из другого дерева."""
    database, root, _records = legacy_install
    foreign = tmp_path_factory.mktemp("foreign-installation") / "tasks"
    foreign.mkdir()
    subprocess.run(["git", "init", "--initial-branch=main", str(foreign)], check=True, capture_output=True)
    for name in ("user.name", "user.email"):
        subprocess.run(["git", "-C", str(foreign), "config", name, "x"], check=True)
    (foreign / "task-store.json").write_text(json.dumps({"schema_version": 1}) + "\n")
    subprocess.run(["git", "-C", str(foreign), "add", "."], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(foreign), "commit", "-m", "seed"], check=True, capture_output=True)
    before = subprocess.run(["git", "-C", str(foreign), "rev-parse", "HEAD"],
                            capture_output=True, text=True, check=True).stdout

    with pytest.raises(MigrationError, match="outside the data directory"):
        migrate_v576(database, foreign)

    assert json.loads((foreign / "task-store.json").read_text()) == {"schema_version": 1}
    assert subprocess.run(["git", "-C", str(foreign), "rev-parse", "HEAD"],
                          capture_output=True, text=True, check=True).stdout == before


def test_a_busy_database_refuses_before_touching_the_store(legacy_install):
    """Миграция на работающем сервисе запрещена кодом, а не дисциплиной вызывающего."""
    database, root, _records = legacy_install
    holder = sqlite3.connect(str(database))
    holder.execute("BEGIN IMMEDIATE")
    try:
        with pytest.raises(MigrationError, match="is busy"):
            migrate_v576(database, root)
    finally:
        holder.rollback()
        holder.close()

    assert json.loads((root / "task-store.json").read_text()) == {"schema_version": 1}
    assert not list(database.parent.glob("*pre-v576*"))


def test_an_unexpected_schema_version_refuses(legacy_install):
    database, root, _records = legacy_install
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA user_version=99")

    with pytest.raises(MigrationError, match="unsupported schema version 99"):
        migrate_v576(database, root)


def test_conftest_clears_production_paths_at_import(tmp_path):
    """`.env` чекаута несёт боевые пути; пофикстурная изоляция опаздывает.

    Проверяется именно момент импорта: приложение поднимается и из module/session-фикстур,
    и на сборе тестов, куда function-scoped фикстуры ещё не дотянулись.
    """
    import os
    import sys

    probe = tmp_path / "probe.py"
    probe.write_text(
        "import os\n"
        "import tests.conftest  # noqa: F401\n"
        "print(repr(os.environ.get('ORCHESTRA_TASK_REPOSITORY')))\n"
        "print(repr(os.environ.get('ORCHESTRA_DB_PATH')))\n"
    )
    leaked = dict(os.environ)
    leaked["ORCHESTRA_TASK_REPOSITORY"] = "/sentinel/live/tasks"
    leaked["ORCHESTRA_DB_PATH"] = "/sentinel/live/orchestra.db"
    leaked["PYTHONPATH"] = str(pathlib.Path(__file__).resolve().parent.parent)

    result = subprocess.run([sys.executable, str(probe)], capture_output=True,
                            text=True, env=leaked, check=True)
    assert result.stdout.split() == ["None", "None"], result.stdout


def test_lifespan_never_loads_dotenv_under_pytest(monkeypatch):
    """Каждый TestClient(app) входит в lifespan — `.env` туда попадать не должен."""
    import dotenv
    from fastapi.testclient import TestClient

    calls = []
    monkeypatch.setattr(dotenv, "load_dotenv", lambda *a, **k: calls.append(1))
    import app.main as main

    with TestClient(main.app):
        pass
    assert calls == []
