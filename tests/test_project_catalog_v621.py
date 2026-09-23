"""V-621: каталог проектов — файл на scope, а не один общий.

Решение владельца 23.09.2026: у каждого оркестратора свои задачи и свои проекты,
не подмешивая чужие. Эти тесты проверяют ровно механику: `own_catalog(scope)`
видит только свой файл, `catalog()` (слитый вид) собирает его из `include_scopes`,
правка применяется без рестарта, а чужой тег не резолвится и не проходит валидацию
в чужом scope. Старые тесты `test_project_catalog_v576.py` и `test_tm.py` покрывают
то, что не изменилось (валидация формы одного файла, задачи без тегов/с тегами).
"""
import subprocess
from pathlib import Path

import pytest

from app import db, project_catalog, tm
from app.project_catalog import CatalogError, catalog, own_catalog, own_catalog_path
from app.task_runtime import TaskRuntime, task_runtime_mode
from app.task_store import TaskStore


@pytest.fixture
def catalog_runtime(tmp_path, monkeypatch, _isolate_project_catalog):
    """Минимальный рабочий стенд tm.api_*: своя БД и своё Git-хранилище задач —
    как в test_project_catalog_v576.py, только каталог правится по ходу теста."""
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "catalog.db")
    db.init_db()
    root = tmp_path / "tasks"
    subprocess.run(["git", "init", "--initial-branch=main", str(root)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(root), "config", "user.name", "Catalog Test"], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.email", "test@example.invalid"], check=True)
    store = TaskStore(root, origin="")
    store.initialize()
    with task_runtime_mode(TaskRuntime(store, db.DB_PATH)) as runtime:
        yield runtime


def _write_own(scope: str, text: str) -> Path:
    path = own_catalog_path(scope)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    project_catalog.reset_cache()
    return path


_ALPHA = """
version: 1
projects:
  - tag: alpha
    name: Alpha
    scope: /alpha
    write_namespace: alpha-vps
    namespaces:
      alpha-vps: ""
"""

_BETA = """
version: 1
projects:
  - tag: beta
    name: Beta
    scope: /beta
    write_namespace: beta-vps
    namespaces:
      beta-vps: ""
"""


# --- own_catalog: видит только свой файл ------------------------------------


def test_own_catalog_does_not_see_a_foreign_scope_file():
    _write_own("/alpha", _ALPHA)
    _write_own("/beta", _BETA)

    assert own_catalog("/alpha").by_tag("alpha") is not None
    assert own_catalog("/alpha").by_tag("beta") is None
    assert own_catalog("/beta").by_tag("beta") is not None
    assert own_catalog("/beta").by_tag("alpha") is None


def test_own_catalog_of_a_scope_without_a_file_is_empty_not_an_error():
    """Отсутствующий файл — обычное состояние ещё не заведённого scope, не авария."""
    assert own_catalog("/never-registered").projects == ()
    assert own_catalog("/never-registered").by_tag("anything") is None


def test_own_catalog_reloads_after_an_edit_without_restart():
    path = _write_own("/alpha", _ALPHA)
    assert own_catalog("/alpha").by_tag("gamma") is None
    path.write_text(_ALPHA + "  - tag: gamma\n    name: Gamma\n    namespaces: {gamma-ns: ''}\n",
                    encoding="utf-8")
    assert own_catalog("/alpha").by_tag("gamma").name == "Gamma"


def test_own_catalog_rejects_a_contradictory_file_loudly():
    _write_own("/alpha", "version: 1\nprojects:\n  - tag: A\n    name: A\n    namespaces: {x: ''}\n")
    with pytest.raises(CatalogError, match="должен быть вида"):
        own_catalog("/alpha")


# --- catalog(): слитый вид из include_scopes ---------------------------------


def test_merged_catalog_pulls_in_every_included_scope(_isolate_project_catalog):
    _write_own("/alpha", _ALPHA)
    _write_own("/beta", _BETA)
    _isolate_project_catalog.write_text(
        "version: 1\ninclude_scopes: [/alpha, /beta]\nprojects: []\n", encoding="utf-8",
    )
    project_catalog.reset_cache()

    merged = catalog()
    assert {p.tag for p in merged.projects} == {"alpha", "beta"}
    # А собственный вид каждого scope по-прежнему видит только себя.
    assert own_catalog("/alpha").by_tag("beta") is None


def test_merged_catalog_without_include_scopes_behaves_like_the_old_single_file(
    _isolate_project_catalog,
):
    """Домашний файл без `include_scopes` (домиграционная форма) — тот же результат,
    что и раньше: слитый вид равен его собственным записям."""
    _isolate_project_catalog.write_text(_ALPHA, encoding="utf-8")
    project_catalog.reset_cache()
    assert {p.tag for p in catalog().projects} == {"alpha"}


def test_merged_catalog_rejects_a_tag_declared_in_two_included_files(_isolate_project_catalog):
    _write_own("/alpha", _ALPHA)
    _write_own("/beta", _ALPHA.replace("/alpha", "/gamma"))  # тот же тег 'alpha', другой scope
    _isolate_project_catalog.write_text(
        "version: 1\ninclude_scopes: [/alpha, /beta]\nprojects: []\n", encoding="utf-8",
    )
    project_catalog.reset_cache()
    with pytest.raises(CatalogError, match="тег 'alpha' уже объявлен"):
        catalog()


# --- задача с несколькими тегами и без тегов остаётся валидной ---------------


def test_task_tags_validate_against_the_callers_own_scope_only():
    _write_own("/alpha", _ALPHA)
    _write_own("/beta", _BETA)

    # Свой тег проходит.
    assert tm.normalize_tags(["alpha"], catalog_scope="/alpha") == ["alpha"]
    # Чужой тег ('beta' существует, но не в файле /alpha) отклоняется по имени.
    with pytest.raises(ValueError, match="unknown project tag 'beta'"):
        tm.normalize_tags(["beta"], catalog_scope="/alpha")


def test_task_without_tags_and_task_with_several_tags_both_stay_valid():
    """И то, и другое — законные состояния (V-576, не тронуто V-621): проверяем,
    что разбиение каталога на файлы этого не изменило."""
    _write_own("/alpha", _ALPHA)
    assert tm.normalize_tags([], catalog_scope="/alpha") == []
    assert tm.normalize_tags(["alpha", "alpha"], catalog_scope="/alpha") == ["alpha"]


def test_api_list_tasks_rejects_a_foreign_scopes_tag(catalog_runtime, _isolate_project_catalog):
    _write_own("/alpha", _ALPHA)
    _write_own("/beta", _BETA)
    _isolate_project_catalog.write_text(
        "version: 1\ninclude_scopes: [/alpha, /beta]\nprojects: []\n", encoding="utf-8",
    )
    project_catalog.reset_cache()

    # 'beta' существует на платформе (виден в слитом виде), но не в каталоге /alpha.
    assert catalog().by_tag("beta") is not None
    with pytest.raises(ValueError, match="unknown project tag 'beta'"):
        tm.api_list_tasks(tags=["beta"], catalog_scope="/alpha")


def test_api_create_task_rejects_a_foreign_scopes_tag(catalog_runtime, _isolate_project_catalog):
    _write_own("/alpha", _ALPHA)
    _write_own("/beta", _BETA)
    _isolate_project_catalog.write_text(
        "version: 1\ninclude_scopes: [/alpha, /beta]\nprojects: []\n", encoding="utf-8",
    )
    project_catalog.reset_cache()
    with db._conn() as connection:
        tm.sync_catalog(connection)

    # Свой scope создаёт задачу нормально.
    created = tm.api_create_task("", "own", scope="/alpha", request_key="own-request-00000001")
    assert created["par"]

    # А явный чужой тег ('beta' существует, но в каталоге ДРУГОГО scope) отклоняется —
    # не подставляется молча в проект вызывающего scope.
    with pytest.raises(ValueError, match="not registered in this scope's own catalog"):
        tm.api_create_task("beta", "foreign", scope="/alpha", request_key="foreign-req-0000001")


# --- HTTP-слой: чипы и /api/tm/tasks видят только свой scope -----------------


@pytest.mark.asyncio
async def test_projects_endpoint_scoped_to_caller_hides_foreign_tags():
    from app.routes.tm import tm_projects

    _write_own("/alpha", _ALPHA)
    _write_own("/beta", _BETA)

    own = await tm_projects(scope="/alpha")
    assert [p["tag"] for p in own["projects"]] == ["alpha"]

    other = await tm_projects(scope="/beta")
    assert [p["tag"] for p in other["projects"]] == ["beta"]
