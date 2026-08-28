from __future__ import annotations

import sqlite3

import pytest

from app.ia.task_store import IdentityConflictError


@pytest.fixture
def canonical_tasks(tmp_path, monkeypatch):
    from app import db, tm

    database = tmp_path / "orchestra.db"
    monkeypatch.setattr(db, "DB_PATH", database)
    db.init_db()
    with tm._conn() as connection:
        tm.ensure_project(connection, "orchestra", scope=str(tmp_path / "repo"))

    with tm.ia_task_store_mode(
        mode="canonical",
        canonical_root=tmp_path / "canonical",
        projection_path=tmp_path / "task-current.db",
        cutoff="2026-08-26T00:00:00+00:00",
        source_head="sha256:legacy-snapshot",
    ) as store:
        assert store is not None
        yield tm, store, database


def test_canonical_create_uses_one_agreed_number_in_both_stores(canonical_tasks):
    tm, store, database = canonical_tasks

    result = tm.api_create_task("orchestra", "agreed allocation")

    assert result["par"] == "1"
    assert store.task_get("1", project="orchestra")["title"] == "agreed allocation"
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT par_number,title FROM tm_tasks"
        ).fetchall() == [(1, "agreed allocation")]


def test_canonical_create_rejects_counter_drift_without_writing(canonical_tasks):
    tm, store, database = canonical_tasks
    with tm._conn() as connection:
        connection.execute("BEGIN IMMEDIATE")
        tm.create_task(connection, "orchestra", "legacy occupied", par_number=1)
        connection.commit()
    canonical_head = store.canonical_head

    with pytest.raises(IdentityConflictError, match="counter mismatch.*canonical=1.*legacy=2"):
        tm.api_create_task("orchestra", "must not be created")

    assert store.canonical_head == canonical_head
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT par_number,title FROM tm_tasks ORDER BY par_number"
        ).fetchall() == [(1, "legacy occupied")]


def test_spawn_task_allocation_keeps_both_stores_in_step(canonical_tasks):
    """Спавн воркера обязан заводить задачу тем же путём, что и `task_create`.

    Раньше `create_task_for_scope` писала прямо в legacy и была ВТОРЫМ владельцем
    нумерации: она двигала legacy-счётчик, не трогая canonical, после чего гейт
    `task display counter mismatch` отказывал НАВСЕГДА. 28.08 веер из трёх детей развёл
    счётчики comfy-image-pipeline на 3, и проект не мог завести ни одной задачи.
    """
    tm, store, database = canonical_tasks
    scope = str(tm._conn().execute(
        "SELECT scope FROM tm_projects WHERE id='orchestra'"
    ).fetchone()[0])

    created = tm.create_task_for_scope(scope, "spawned by fan-out")

    # Потребитель строит имя ветки из par_number — форма ответа обязана сохраниться.
    assert created["par_number"] == 1

    # И, главное, обе стороны согласны: следующий task_create проходит, а не упирается в гейт.
    assert store.task_get("1", project="orchestra")["title"] == "spawned by fan-out"
    following = tm.api_create_task("orchestra", "next one still works")
    assert following["par"] == "2"


def test_low_level_create_refuses_to_allocate_a_number_itself(canonical_tasks):
    """Единственный владелец номера — `api_create_task`; обход обязан падать ГРОМКО.

    Это принуждение «одного пути» в коде, а не в договорённости: собственная выдача номера
    здесь двигает только legacy-счётчик, после чего гейт `task display counter mismatch`
    отказывает навсегда. Дефект 28.08 прожил именно потому, что обход был тихим.
    """
    tm, store, database = canonical_tasks
    canonical_head = store.canonical_head

    with tm._conn() as connection:
        with pytest.raises(RuntimeError, match="call api_create_task"):
            tm.create_task(connection, "orchestra", "second door")

    # Ни одна из сторон не сдвинулась: отказ пришёл ДО записи.
    assert store.canonical_head == canonical_head
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM tm_tasks").fetchone()[0] == 0

    # Легальный путь по-прежнему работает и остаётся единственным.
    assert tm.api_create_task("orchestra", "through the one owner")["par"] == "1"
