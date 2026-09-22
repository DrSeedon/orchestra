"""Миграция V-576 выполняется самим сервисом при старте.

От владельца требуется ровно один рестарт и ни одной команды на остановленной
системе: агент, который запускал бы скрипт, живёт внутри Orchestra и при её
остановке останавливается сам.

Порядок шагов выбран по тому, ЧТО МОЖЕТ УПАСТЬ, а не по удобству отката:
1. отказы-предусловия — до единой записи;
2. SQLite копируется через ``Connection.backup()`` — откат базы это возврат копии;
3. в SQLite появляется колонка-проекция ``tm_tasks.tags`` и ``user_version`` 2 → 3;
4. записи задач получают ``tags`` и ``schema_version: 2`` одним git-коммитом.

Необратимый шаг (git-коммит) идёт ПОСЛЕДНИМ. Авария 22.09.2026 произошла ровно от
обратного порядка: миграцию запустили на РАБОТАЮЩЕЙ системе, коммит в хранилище
прошёл, а шаг базы упал на занятой базе — живой процесс перестал читать хранилище
(«task repository is not initialized»), и у проекта отказали merge_worker и task_get.

Отсюда три предусловия, каждое из которых в одиночку закрыло бы ту аварию:
* хранилище обязано лежать внутри каталога данных своей базы — одна установка;
* база не должна быть занята другим процессом: миграция на живом сервисе
  невозможна по коду, а не по дисциплине вызывающего;
* рабочее дерево хранилища обязано быть чистым.

Любой отказ поднимается наружу: сервис не стартует, причина уходит в журнал,
данные остаются в исходном виде. Тихо стартовать на полумигрированных данных
хуже, чем не стартовать вовсе.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import json
import logging
import sqlite3
import subprocess

from app.project_catalog import catalog
from app.task_store import SCHEMA_VERSION as STORE_VERSION, _bytes, _validate


logger = logging.getLogger(__name__)

DB_VERSION_BEFORE = 2
DB_VERSION_AFTER = 3


class MigrationError(RuntimeError):
    """Миграция не прошла. Сервис не стартует; данные остались прежними."""


def _database_needs_migration(connection: sqlite3.Connection) -> bool:
    tables = {
        str(row[0]) for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    if "tm_tasks" not in tables:
        return False  # свежая установка: схема создаётся сразу нужной версии
    columns = {
        str(row[1]) for row in connection.execute("PRAGMA table_info(tm_tasks)").fetchall()
    }
    return "tags" not in columns


def _backup(database: Path) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = database.with_name(f"{database.stem}-pre-v576-{stamp}.db")
    source = sqlite3.connect(str(database))
    try:
        destination = sqlite3.connect(str(target))
        try:
            # Копия живой SQLite делается backup(), а не cp: cp рвёт WAL.
            source.backup(destination)
        finally:
            destination.close()
    finally:
        source.close()
    return target


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(root), *args],
                            capture_output=True, text=True, timeout=300)
    if result.returncode:
        raise MigrationError(result.stderr.strip() or result.stdout.strip() or "git failed")
    return result.stdout


def _require_clean_task_store(root: Path) -> None:
    """Чужие незакоммиченные правки не должны попасть в коммит миграции."""
    if not (root / "task-store.json").is_file():
        return
    if _git(root, "status", "--porcelain", "--untracked-files=all", "--", "projects").strip():
        raise MigrationError("task store has uncommitted changes; migration refuses to mix them in")


def _migrate_task_store(root: Path) -> dict:
    marker = root / "task-store.json"
    if not marker.is_file():
        return {"state": "absent"}
    version = json.loads(marker.read_text())
    if version == {"schema_version": STORE_VERSION}:
        return {"state": "already"}
    if version != {"schema_version": 1}:
        raise MigrationError(f"unsupported task store version {version}")
    known = catalog()
    written: dict[Path, bytes] = {}
    tagged = untagged = 0
    for path in sorted((root / "projects").glob("*/tasks/*.json")):
        record = json.loads(path.read_text())
        tag = known.tag_of(str(record.get("project_id") or ""))
        record["schema_version"] = STORE_VERSION
        record["tags"] = [tag] if tag else []
        _validate(record)
        written[path] = _bytes(record)
        tagged, untagged = (tagged + 1, untagged) if tag else (tagged, untagged + 1)
    written[marker] = _bytes({"schema_version": STORE_VERSION})
    for path, content in written.items():
        path.write_bytes(content)
    relative = [str(path.relative_to(root)) for path in written]
    _git(root, "add", "--", *relative)
    _git(root, "commit", "--only", "-m",
         "V-576: task records carry project tags (schema_version 2)", "--", *relative)
    return {"state": "migrated", "files": len(written) - 1,
            "tagged": tagged, "untagged": untagged, "head": _git(root, "rev-parse", "HEAD").strip()}


def _migrate_database(database: Path) -> dict:
    connection = sqlite3.connect(str(database))
    try:
        version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        if not _database_needs_migration(connection):
            if version == DB_VERSION_AFTER:
                return {"state": "already", "schema_version": version}
            connection.execute(f"PRAGMA user_version={DB_VERSION_AFTER}")
            connection.commit()
            return {"state": "version_only", "schema_version": DB_VERSION_AFTER}
        if version != DB_VERSION_BEFORE:
            raise MigrationError(
                f"unsupported schema version {version}; expected {DB_VERSION_BEFORE} before V-576"
            )
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("ALTER TABLE tm_tasks ADD COLUMN tags TEXT NOT NULL DEFAULT '[]'")
        connection.execute(f"PRAGMA user_version={DB_VERSION_AFTER}")
        connection.commit()
        return {"state": "migrated", "schema_version": DB_VERSION_AFTER}
    except MigrationError:
        connection.rollback()
        raise
    except Exception as error:
        connection.rollback()
        raise MigrationError(f"database migration failed: {error}") from error
    finally:
        connection.close()


def _require_one_installation(database: Path, task_repository: Path) -> None:
    """Хранилище задач обязано лежать в каталоге данных своей базы.

    Проекция и её источник принадлежат одной установке. В аварии 22.09.2026 база
    была чужая, а хранилище боевое — одна эта проверка закрыла бы инцидент.
    """
    data_directory = database.resolve().parent
    if not task_repository.resolve().is_relative_to(data_directory):
        raise MigrationError(
            f"task repository {task_repository} is outside the data directory of "
            f"{database}; migration refuses to pair stores of different installations"
        )


def _require_exclusive_database(database: Path) -> None:
    """Отказаться, если базу держит другой процесс: миграция на живом сервисе запрещена."""
    connection = sqlite3.connect(str(database), timeout=0.0)
    try:
        connection.execute("BEGIN IMMEDIATE")
        connection.rollback()
    except sqlite3.OperationalError as error:
        raise MigrationError(
            f"database {database} is busy ({error}); stop Orchestra before migrating"
        ) from error
    finally:
        connection.close()


def migrate_v576(database: Path, task_repository: Path) -> dict:
    """Идемпотентно привести оба хранилища к V-576. Повторный старт ничего не делает."""
    database = Path(database)
    task_repository = Path(task_repository)
    if not database.is_file():
        return {"state": "fresh"}
    with sqlite3.connect(str(database)) as probe:
        pending_database = _database_needs_migration(probe)
    marker = task_repository / "task-store.json"
    pending_store = marker.is_file() and json.loads(marker.read_text()) != {
        "schema_version": STORE_VERSION
    }
    if not pending_database and not pending_store:
        return {"state": "already"}

    # Всё, что способно отказать, отказывает ДО первой записи.
    _require_one_installation(database, task_repository)
    _require_exclusive_database(database)
    _require_clean_task_store(task_repository)

    backup = _backup(database) if pending_database else None
    if backup:
        logger.warning("V-576 migration: SQLite backup at %s", backup)
    result = _migrate_database(database)
    # Необратимый шаг последний: git-коммит уже некуда откатить автоматически.
    store = _migrate_task_store(task_repository)
    logger.warning("V-576 migration complete: store=%s database=%s backup=%s",
                   store, result, backup)
    return {"state": "migrated", "store": store, "database": result,
            "backup": str(backup) if backup else ""}
