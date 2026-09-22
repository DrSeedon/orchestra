"""V-576: каталог проектов файлом и теги задач.

Проверяется механика, которая ломается молча: куда уходит номер новой задачи,
переживает ли тег пересборку проекции из Git и продолжает ли разрешаться `#N`
при мерже. Формулировки каталога не проверяются — их правит владелец.
"""
import subprocess

import pytest

from app import db, project_catalog, tm
from app.project_catalog import CatalogError, catalog
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
  - tag: beta
    name: Beta
    scope: /beta
    write_namespace: beta-vps
    namespaces:
      beta-vps: ""
  - tag: gamma
    name: Gamma
    archived: true
    namespaces:
      gamma-laptop: ноутбук
"""


def _write_catalog(path, text=_CATALOG):
    path.write_text(text, encoding="utf-8")
    project_catalog.reset_cache()
    return path


@pytest.fixture
def catalog_runtime(tmp_path, monkeypatch, _isolate_project_catalog):
    _write_catalog(_isolate_project_catalog)
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "catalog.db")
    db.init_db()
    root = tmp_path / "tasks"
    subprocess.run(["git", "init", "--initial-branch=main", str(root)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(root), "config", "user.name", "Catalog Test"], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.email", "test@example.invalid"], check=True)
    store = TaskStore(root, origin="")
    store.initialize()
    with task_runtime_mode(TaskRuntime(store, db.DB_PATH)) as runtime:
        with db._conn() as connection:
            tm.sync_catalog(connection)
        yield runtime


def _seed(runtime, namespace, title, *, request_key=None):
    return runtime.create({"canonical_id": namespace}, title,
                          request_key=request_key or f"seed-{namespace}-{title}")


# --- каталог как источник истины о scope -------------------------------------


def test_each_catalog_scope_creates_tasks_in_its_write_namespace(catalog_runtime):
    """Приёмка: номер новой задачи уходит ровно в то пространство, что в каталоге."""
    for scope, tag in catalog().scopes().items():
        created = tm.api_create_task("", f"task for {tag}", scope=scope,
                                     request_key=f"create-{tag}-0000001")
        namespace = catalog().by_tag(tag).write_namespace
        assert catalog_runtime.store.get(namespace, created["par"])["title"] == f"task for {tag}"


def test_unknown_scope_no_longer_invents_a_project(catalog_runtime):
    with db._conn() as connection:
        before = connection.execute("SELECT COUNT(*) FROM tm_projects").fetchone()[0]

    with pytest.raises(ValueError, match="is not registered"):
        tm.api_create_task("", "ghost", scope="/not-in-catalog",
                           request_key="ghost-request-000001")

    with db._conn() as connection:
        assert connection.execute("SELECT COUNT(*) FROM tm_projects").fetchone()[0] == before
        assert connection.execute(
            "SELECT COUNT(*) FROM tm_projects WHERE id LIKE 'scope:%'"
        ).fetchone()[0] == 0


def test_sync_catalog_is_idempotent_and_keeps_existing_binding(catalog_runtime):
    with db._conn() as connection:
        first = tm.sync_catalog(connection)
        rows = connection.execute("SELECT id,scope,canonical_id FROM tm_projects ORDER BY id").fetchall()
        second = tm.sync_catalog(connection)
        again = connection.execute("SELECT id,scope,canonical_id FROM tm_projects ORDER BY id").fetchall()
    assert first == second
    assert [tuple(r) for r in rows] == [tuple(r) for r in again]
    assert set(first["scopes"]) == {"/alpha", "/beta"}


def test_sync_catalog_refuses_when_scope_belongs_to_another_binding(catalog_runtime):
    with db._conn() as connection:
        # scope уникален, поэтому захват возможен только после освобождения:
        # ровно так это и выглядит, если в каталоге сменили write_namespace.
        connection.execute("UPDATE tm_projects SET scope=NULL WHERE canonical_id='beta-vps'")
        connection.execute(
            "INSERT INTO tm_projects(id,name,prefix,scope,created_at,canonical_id) "
            "VALUES('squatter','Squatter','SQT','/beta','now','squatter')"
        )
        with pytest.raises(CatalogError, match="squatter"):
            tm.sync_catalog(connection)


def test_merge_ref_resolution_follows_the_catalog_scope(catalog_runtime):
    """§10 п.4: номера из сообщений коммитов разрешаются через scope сессии."""
    tm.api_create_task("", "mergeable", scope="/alpha", request_key="merge-alpha-000001")
    resolved = tm.resolve_scoped_task_identities("/alpha", ["1"])
    assert resolved["canonical_refs"] == ["1"]
    assert resolved["tasks"][0]["par_number"] == 1
    with pytest.raises(ValueError, match="has no task project"):
        tm.resolve_scoped_task_identities("/not-in-catalog", ["1"])


# --- теги --------------------------------------------------------------------


def test_task_without_tags_is_valid(catalog_runtime):
    """Тег не обязателен: задача может не числиться ни за одним проектом."""
    _seed(catalog_runtime, "alpha-vps", "untagged")
    with db._conn() as connection:
        task = connection.execute("SELECT * FROM tm_tasks").fetchone()
        assert tm.task_tags(task) == []
    assert tm.api_list_tasks(tags=["alpha"])["count"] == 0
    assert tm.api_list_tasks()["count"] == 1


def test_tag_is_written_into_the_task_file(catalog_runtime):
    created = tm.api_create_task("", "tagged work", scope="/alpha",
                                 request_key="alpha-tagwrite-00001")
    tm.api_update_task(created["par"], project="alpha", tags=["alpha", "beta"])
    record = catalog_runtime.store.get("alpha-vps", created["par"])
    assert record["tags"] == ["alpha", "beta"]


def test_tag_survives_a_full_projection_rebuild(catalog_runtime):
    created = tm.api_create_task("", "tagged work", scope="/alpha",
                                 request_key="alpha-rebuild-000001")
    tm.api_update_task(created["par"], project="alpha", tags=["beta"])

    with db._conn() as connection:
        # Проекция пересобирается из файлов целиком; источник истины — они.
        connection.execute("DELETE FROM tm_tasks")
        connection.execute("DELETE FROM task_projection_meta")
        connection.commit()
    catalog_runtime.refresh()

    with db._conn() as connection:
        rebuilt = connection.execute("SELECT * FROM tm_tasks").fetchone()
        assert tm.task_tags(rebuilt) == ["beta"]
    assert [t["title"] for t in tm.api_list_tasks(tags=["beta"])["tasks"]] == ["tagged work"]


def test_tag_filter_spans_namespaces_and_ignores_the_task_own_namespace(catalog_runtime):
    first = tm.api_create_task("", "from alpha", scope="/alpha",
                               request_key="span-alpha-00000001")
    second = tm.api_create_task("", "from beta", scope="/beta",
                                request_key="span-beta-000000001")
    tm.api_update_task(first["par"], project="alpha", tags=["gamma"])
    tm.api_update_task(second["par"], project="beta", tags=["gamma"])

    listed = tm.api_list_tasks(tags=["gamma"])
    assert {t["title"] for t in listed["tasks"]} == {"from alpha", "from beta"}
    assert {t["project"] for t in listed["tasks"]} != {""}


def test_colliding_numbers_stay_apart_by_source_label(catalog_runtime):
    _seed(catalog_runtime, "alpha-vps", "vps one")
    _seed(catalog_runtime, "alpha-laptop", "laptop one")

    listed = tm.api_list_tasks()["tasks"]
    assert sorted(t["par"] for t in listed) == ["1", "1"]
    assert {(t["title"], t["source"]) for t in listed} == {
        ("vps one", ""), ("laptop one", "ноутбук"),
    }


def test_tag_outside_the_catalog_is_rejected(catalog_runtime):
    created = tm.api_create_task("", "work", scope="/beta",
                                 request_key="beta-unknown-000001")
    with pytest.raises(ValueError, match="unknown project tag 'delta'"):
        tm.api_update_task(created["par"], project="beta", tags=["delta"])
    assert catalog_runtime.store.get("beta-vps", created["par"])["tags"] == []
    with pytest.raises(ValueError, match="unknown project tag 'delta'"):
        tm.api_list_tasks(tags=["delta"])


def test_archived_project_tag_is_usable_but_takes_no_new_tasks(catalog_runtime):
    created = tm.api_create_task("", "work", scope="/beta",
                                 request_key="beta-archived-00001")
    tm.api_update_task(created["par"], project="beta", tags=["gamma"])
    assert tm.api_list_tasks(tags=["gamma"])["count"] == 1
    with pytest.raises(ValueError, match="is not registered"):
        tm.api_create_task("gamma", "new", request_key="gamma-request-0000001")


def test_store_refuses_a_record_of_the_previous_shape(catalog_runtime):
    """Старая форма записи отвергается громко, а не читается молча без тегов."""
    from app.task_store import _validate

    record = catalog_runtime.store.get("beta-vps", tm.api_create_task(
        "", "work", scope="/beta", request_key="beta-shape-00000001")["par"])
    legacy = {k: v for k, v in record.items()
              if k not in {"ref", "display_ref", "revision", "tags"}}
    legacy["schema_version"] = 1
    with pytest.raises(ValueError, match="invalid task record shape/version"):
        _validate(legacy)


# --- валидация самого каталога ----------------------------------------------


@pytest.mark.parametrize("text,message", [
    ("version: 2\nprojects: []\n", "version: 1"),
    ("version: 1\nprojects:\n  - tag: a\n    name: A\n    namespaces: {}\n", "непустой namespaces"),
    ("version: 1\nprojects:\n  - tag: A\n    name: A\n    namespaces: {x: ''}\n", "должен быть вида"),
    ("version: 1\nprojects:\n  - tag: a\n    name: A\n    namespaces: {x: ''}\n"
     "  - tag: b\n    name: B\n    namespaces: {x: ''}\n", "заявлен и в"),
    ("version: 1\nprojects:\n  - tag: a\n    name: A\n    scope: /a\n    namespaces: {x: ''}\n",
     "не задан write_namespace"),
    ("version: 1\nprojects:\n  - tag: a\n    name: A\n    scope: /a\n"
     "    write_namespace: y\n    namespaces: {x: ''}\n", "отсутствует в его namespaces"),
    ("version: 1\nprojects:\n  - tag: a\n    name: A\n    archived: true\n    scope: /a\n"
     "    write_namespace: x\n    namespaces: {x: ''}\n", "не может принимать задачи"),
    ("version: 1\nprojects:\n  - tag: a\n    name: A\n    colour: red\n    namespaces: {x: ''}\n",
     "неизвестные поля"),
])
def test_catalog_refuses_a_contradictory_file(_isolate_project_catalog, text, message):
    _write_catalog(_isolate_project_catalog, text)
    with pytest.raises(CatalogError, match=message):
        catalog()


def test_catalog_reloads_after_an_edit_without_restart(_isolate_project_catalog):
    _write_catalog(_isolate_project_catalog)
    assert catalog().by_tag("delta") is None
    _write_catalog(_isolate_project_catalog,
                   _CATALOG + "  - tag: delta\n    name: Delta\n    namespaces: {delta-ns: ''}\n")
    assert catalog().by_tag("delta").name == "Delta"
