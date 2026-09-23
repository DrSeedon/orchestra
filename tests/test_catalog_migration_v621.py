"""V-621: миграция общего `.orchestra/projects.yaml` в файл на каждый scope.

По образцу `test_startup_migration_v576.py` — проверяется механика, а не формулировки.
Все репозитории — временные каталоги внутри `tmp_path`; ни один реальный проект здесь
не создаётся и не трогается (граница задачи V-621).

Второй заход (23.09.2026, решение владельца): непригодный чужой scope (грязный,
отсутствует, отказ записи) деградирует — миграция его пропускает и служба СТАРТУЕТ,
а не роняет старт всей платформы из-за одного чужого репозитория. Падать на старте
можно только если нечитаем сам домашний файл каталога.
"""
from pathlib import Path
import subprocess

import pytest
import yaml

from app.catalog_migration_v621 import CatalogMigrationError, migrate_v621
from app.project_catalog import own_catalog, own_catalog_path


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=True)
    return result.stdout


def _init_repo(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init", "--initial-branch=main")
    _git(root, "config", "user.name", "Migration Test")
    _git(root, "config", "user.email", "test@example.invalid")
    (root / "README.md").write_text("seed\n", encoding="utf-8")


def _commit_all(root: Path, message: str) -> None:
    _git(root, "add", "-A")
    _git(root, "commit", "-m", message)


@pytest.fixture(autouse=True)
def _no_catalog_root_override(monkeypatch):
    """Миграция обязана писать по буквальным путям `scope` — тестовая песочница
    `_isolate_project_catalog` (autouse) иначе увела бы её в чужой каталог."""
    monkeypatch.delenv("ORCHESTRA_PROJECT_CATALOG_ROOT", raising=False)


def _seed_home(tmp_path: Path, *, external: dict[str, str] | None = None) -> tuple[Path, Path]:
    """Домашний git-репозиторий со старым плоским каталогом. Возвращает (repo_root, home_path)."""
    home_root = tmp_path / "home"
    _init_repo(home_root)
    (home_root / ".orchestra").mkdir()
    home_path = home_root / ".orchestra" / "projects.yaml"
    entries = [
        {"tag": "home", "name": "Home", "scope": str(home_root), "write_namespace": "home-ns",
         "namespaces": {"home-ns": ""}},
        {"tag": "orphan", "name": "Orphan", "namespaces": {"orphan-ns": "ноутбук"}},
    ]
    for scope, tag in (external or {}).items():
        entries.append({
            "tag": tag, "name": tag.title(), "scope": scope, "write_namespace": f"{tag}-ns",
            "namespaces": {f"{tag}-ns": ""},
        })
    home_path.write_text(yaml.safe_dump({"version": 1, "projects": entries}, sort_keys=False),
                         encoding="utf-8")
    _commit_all(home_root, "seed: old flat catalog")
    return home_root, home_path


# --- состояния, не требующие записи ------------------------------------------


def test_fresh_install_has_nothing_to_migrate(tmp_path):
    assert migrate_v621(tmp_path / "missing" / "projects.yaml") == {"state": "fresh"}


def test_already_migrated_catalog_is_a_noop(tmp_path):
    home_root, home_path = _seed_home(tmp_path)
    home_path.write_text(
        yaml.safe_dump({"version": 1, "include_scopes": [], "projects": []}), encoding="utf-8",
    )
    _commit_all(home_root, "already on V-621 shape")
    before = home_path.read_text(encoding="utf-8")
    assert migrate_v621(home_path) == {"state": "already"}
    assert home_path.read_text(encoding="utf-8") == before


# --- единственный настоящий отказ: домашний файл нечитаем --------------------


def test_refuses_to_start_when_the_home_file_has_unexpected_shape(tmp_path):
    home_root, home_path = _seed_home(tmp_path)
    home_path.write_text("version: 2\nprojects: []\n", encoding="utf-8")
    with pytest.raises(CatalogMigrationError, match="читать нечего"):
        migrate_v621(home_path)


def test_refuses_to_start_when_the_home_file_is_not_valid_yaml(tmp_path):
    home_root, home_path = _seed_home(tmp_path)
    home_path.write_text("version: 1\nprojects: [\n  - this is not: [valid, yaml", encoding="utf-8")
    with pytest.raises(CatalogMigrationError, match="не парсится"):
        migrate_v621(home_path)


# --- непригодный ЧУЖОЙ scope деградирует, а не роняет старт ------------------


def test_a_missing_scope_directory_is_skipped_others_split_service_starts(tmp_path):
    ghost = tmp_path / "ghost"
    ext = tmp_path / "ext"
    _init_repo(ext)
    _commit_all(ext, "seed ext")
    home_root, home_path = _seed_home(
        tmp_path, external={str(ghost): "ghost", str(ext): "ext"},
    )

    result = migrate_v621(home_path)  # не бросает — служба стартует
    assert result["state"] == "migrated"
    assert result["external"] == [str(ext)]
    assert str(ghost) in result["skipped"]
    assert not ghost.exists()  # миграция ничего не создаёт для непригодного scope

    # Пропущенный тег по-прежнему резолвится — просто через домашний файл, не свой.
    from app import project_catalog
    import os
    os.environ["ORCHESTRA_PROJECT_CATALOG"] = str(home_path)
    project_catalog.reset_cache()
    try:
        merged = project_catalog.catalog()
    finally:
        del os.environ["ORCHESTRA_PROJECT_CATALOG"]
        project_catalog.reset_cache()
    assert merged.by_tag("ghost") is not None
    assert merged.by_tag("ext") is not None
    assert own_catalog(str(ext)).by_tag("ext") is not None
    assert own_catalog(str(ghost)).by_tag("ghost") is None  # у него всё ещё нет своего файла


def test_a_dirty_external_scope_is_skipped_others_split_service_starts(tmp_path):
    ext1, ext2 = tmp_path / "ext1", tmp_path / "ext2"
    _init_repo(ext1)
    _commit_all(ext1, "seed ext1")
    (ext1 / "dirty.txt").write_text("uncommitted", encoding="utf-8")
    _init_repo(ext2)
    _commit_all(ext2, "seed ext2")
    home_root, home_path = _seed_home(
        tmp_path, external={str(ext1): "ext1", str(ext2): "ext2"},
    )

    result = migrate_v621(home_path)  # не бросает
    assert result["state"] == "migrated"
    assert result["external"] == [str(ext2)]
    assert str(ext1) in result["skipped"]
    assert "uncommitted changes" in result["skipped"][str(ext1)]
    assert not own_catalog_path(str(ext1)).exists()

    home_data = yaml.safe_load(home_path.read_text(encoding="utf-8"))
    assert {p["tag"] for p in home_data["projects"]} == {"home", "orphan", "ext1"}
    assert home_data["include_scopes"] == [str(ext2)]


def test_a_skipped_scope_is_picked_up_on_the_next_start_once_clean(tmp_path):
    """Идемпотентность: то, что пропустили сейчас, доезжает само на следующем рестарте."""
    ext1, ext2 = tmp_path / "ext1", tmp_path / "ext2"
    _init_repo(ext1)
    _commit_all(ext1, "seed ext1")
    (ext1 / "dirty.txt").write_text("uncommitted", encoding="utf-8")
    _init_repo(ext2)
    _commit_all(ext2, "seed ext2")
    home_root, home_path = _seed_home(
        tmp_path, external={str(ext1): "ext1", str(ext2): "ext2"},
    )

    first = migrate_v621(home_path)
    assert first["state"] == "migrated"
    assert str(ext1) in first["skipped"]
    assert own_catalog(str(ext1)).by_tag("ext1") is None

    # Владелец коммитит рассинхрон — scope становится чистым.
    _commit_all(ext1, "clean up")

    second = migrate_v621(home_path)  # маркер include_scopes уже есть → перезапуск разбора
    assert second["state"] == "migrated"
    assert second["external"] == [str(ext1)]
    assert own_catalog(str(ext1)).by_tag("ext1") is not None
    home_data = yaml.safe_load(home_path.read_text(encoding="utf-8"))
    assert {p["tag"] for p in home_data["projects"]} == {"home", "orphan"}
    assert home_data["include_scopes"] == sorted([str(ext1), str(ext2)])


def test_a_scope_with_a_pre_existing_own_catalog_is_adopted_not_overwritten(tmp_path):
    ext = tmp_path / "ext"
    ext.mkdir()
    own_catalog_path(str(ext)).parent.mkdir(parents=True)
    own_catalog_path(str(ext)).write_text(
        "version: 1\nprojects:\n  - tag: ext\n    name: Ext\n    namespaces: {ext-ns: ''}\n",
        encoding="utf-8",
    )
    before = own_catalog_path(str(ext)).read_text(encoding="utf-8")
    home_root, home_path = _seed_home(tmp_path, external={str(ext): "ext"})

    result = migrate_v621(home_path)
    assert result["state"] == "migrated"
    assert result["already"] == [str(ext)]
    assert result["external"] == []
    assert own_catalog_path(str(ext)).read_text(encoding="utf-8") == before  # не тронут
    home_data = yaml.safe_load(home_path.read_text(encoding="utf-8"))
    assert home_data["include_scopes"] == [str(ext)]
    assert {p["tag"] for p in home_data["projects"]} == {"home", "orphan"}


def test_a_dirty_home_repository_still_writes_and_commits_only_its_own_files(tmp_path):
    """Коммит домашнего файла — точечный (`git add -- <файлы>`), поэтому чужое
    незакоммиченное `wip.txt` в том же репозитории ему не мешает и в коммит не
    попадает: падать здесь нечему, читать домашний файл было можно."""
    ext = tmp_path / "ext"
    _init_repo(ext)
    _commit_all(ext, "seed ext")
    home_root, home_path = _seed_home(tmp_path, external={str(ext): "ext"})
    (home_root / "wip.txt").write_text("someone's uncommitted work", encoding="utf-8")

    result = migrate_v621(home_path)  # не бросает
    assert result["state"] == "migrated"
    assert result["external"] == [str(ext)]
    assert result["home_committed"] is True

    home_data = yaml.safe_load(home_path.read_text(encoding="utf-8"))
    assert home_data["include_scopes"] == [str(ext)]
    assert own_catalog(str(ext)).by_tag("ext") is not None
    # Чужой wip.txt остался нетронутым и незакоммиченным.
    status = _git(home_root, "status", "--porcelain")
    assert "wip.txt" in status
    assert "projects.yaml" not in status


# --- миграция: файлы, бэкап, коммит последним --------------------------------


def test_migrates_flat_catalog_into_per_scope_files_and_commits(tmp_path):
    ext1, ext2 = tmp_path / "ext1", tmp_path / "ext2"
    _init_repo(ext1)
    _commit_all(ext1, "seed ext1")
    ext2.mkdir()  # не git-репозиторий вовсе — тоже законный scope
    home_root, home_path = _seed_home(
        tmp_path, external={str(ext1): "ext1", str(ext2): "ext2"},
    )

    result = migrate_v621(home_path)
    assert result["state"] == "migrated"
    assert set(result["external"]) == {str(ext1), str(ext2)}
    assert result["home_committed"] is True

    home_data = yaml.safe_load(home_path.read_text(encoding="utf-8"))
    assert home_data["include_scopes"] == sorted([str(ext1), str(ext2)])
    assert {p["tag"] for p in home_data["projects"]} == {"home", "orphan"}

    ext1_data = yaml.safe_load(own_catalog_path(str(ext1)).read_text(encoding="utf-8"))
    assert [p["tag"] for p in ext1_data["projects"]] == ["ext1"]
    ext2_data = yaml.safe_load(own_catalog_path(str(ext2)).read_text(encoding="utf-8"))
    assert [p["tag"] for p in ext2_data["projects"]] == ["ext2"]

    # Бэкап несёт СТАРОЕ содержимое (все теги в одном месте).
    backups = list((home_root / ".orchestra").glob("projects-pre-v621-*.yaml"))
    assert len(backups) == 1
    backup_data = yaml.safe_load(backups[0].read_text(encoding="utf-8"))
    assert {p["tag"] for p in backup_data["projects"]} == {"home", "orphan", "ext1", "ext2"}

    # Коммит — последний шаг: рабочее дерево home-репозитория снова чистое.
    assert _git(home_root, "status", "--porcelain").strip() == ""
    assert "V-621" in _git(home_root, "log", "-1", "--format=%s")
    assert _git(ext1, "status", "--porcelain").strip() == ""
    assert "V-621" in _git(ext1, "log", "-1", "--format=%s")
    # ext2 не git — файл есть, коммитить было нечем.
    assert not (ext2 / ".git").exists()


def test_migration_is_idempotent_on_rerun(tmp_path):
    ext = tmp_path / "ext"
    _init_repo(ext)
    _commit_all(ext, "seed ext")
    home_root, home_path = _seed_home(tmp_path, external={str(ext): "ext"})

    first = migrate_v621(home_path)
    assert first["state"] == "migrated"
    second = migrate_v621(home_path)
    assert second == {"state": "already"}


def test_existing_tags_all_remain_resolvable_after_the_split(tmp_path):
    """Приёмка V-621: существующие теги (и их задачи) остаются валидными после
    разбиения — просто через `include_scopes` вместо одного файла."""
    from app import project_catalog

    ext = tmp_path / "ext"
    _init_repo(ext)
    _commit_all(ext, "seed ext")
    home_root, home_path = _seed_home(tmp_path, external={str(ext): "ext"})

    before = {p.tag for p in project_catalog._parse_file(
        yaml.safe_load(home_path.read_text(encoding="utf-8")), str(home_path),
    )[0]}
    migrate_v621(home_path)

    import os
    os.environ["ORCHESTRA_PROJECT_CATALOG"] = str(home_path)
    project_catalog.reset_cache()
    try:
        after = {p.tag for p in project_catalog.catalog().projects}
    finally:
        del os.environ["ORCHESTRA_PROJECT_CATALOG"]
        project_catalog.reset_cache()
    assert after == before == {"home", "orphan", "ext"}
