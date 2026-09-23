"""Каталог проектов: файл на каждый scope, а не один общий.

Решение владельца V-621, 23.09.2026, дословно: «эта хуйня в каждом оркестраторе свои
задачи должны быть и свои проекты не надо мешать блять и каждый оркестратор локально
в дот оркестра может проекты вписывать свои». До V-621 один файл
`.orchestra/projects.yaml` в репозитории Orchestra нёс теги ВСЕХ проектов на VPS — у
каждого оркестратора в интерфейсе висели чипы чужих проектов вперемешку со своими.

Теперь у каждого проекта, у которого есть `scope` (рабочий каталог на диске), СВОЙ
файл `<scope>/.orchestra/projects.yaml` — его читает и правит только оркестратор этого
scope. `own_catalog(scope)` открывает ровно этот файл и ничего больше: чужой тег в него
попасть не может, потому что чужой файл этот код никогда не открывает.

Проекты без scope (архив, «сироты» без живого рабочего каталога) жить своим файлом не
могут — их держит домашний файл той установки, которая физически всех обслуживает
(`.orchestra/projects.yaml` в репозитории Orchestra). Тот же домашний файл несёт
`include_scopes` — список путей, чьи собственные файлы стоит подмешать в СЛИТЫЙ вид.
Слитый вид (`catalog()`) — внутренняя бухгалтерия одной установки (проекция номеров при
старте, метка источника у чужого пространства), а не то, что видит или может выставить
один оркестратор; для этого — `own_catalog(scope)`.

Каталог владеет тегом, именем, scope и целевым пространством номеров. Он НЕ владеет
номерами задач: номер выдаёт и разрешает namespace (`tm_tasks.project_id`), потому что
`#N` уникален только внутри пространства — на 15.09.2026 внутри тегов этого каталога
424 конфликтующие ссылки на 857 задач из 1755 (см. .orchestra/kb, V-576).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import re
import threading

import yaml

from app.task_refs import project_key


CATALOG_PATH = Path(__file__).parent.parent / ".orchestra" / "projects.yaml"

# Та же форма, что у `app.task_refs.project_key`: namespace становится именем каталога
# в Git-хранилище задач, поэтому он обязан быть безопасным для пути.
_NAMESPACE = re.compile(r"[a-z0-9][a-z0-9._-]*")
_TAG = re.compile(r"[a-z0-9][a-z0-9-]*")
_ENTRY_FIELDS = {"tag", "name", "scope", "write_namespace", "namespaces", "archived"}


class CatalogError(RuntimeError):
    """Каталог не читается или противоречив. Чинится правкой файла, не кодом."""


@dataclass(frozen=True)
class Project:
    tag: str
    name: str
    scope: str
    write_namespace: str
    namespaces: dict[str, str]
    archived: bool
    source: str  # путь файла записи — только для диагностики конфликтов при слиянии

    def source_label(self, namespace: str) -> str:
        return self.namespaces.get(namespace, "")


@dataclass(frozen=True)
class Catalog:
    projects: tuple[Project, ...]
    _by_tag: dict[str, Project]
    _by_namespace: dict[str, Project]
    _by_scope: dict[str, Project]

    def by_tag(self, tag: str) -> Project | None:
        return self._by_tag.get(str(tag or "").strip())

    def by_namespace(self, namespace: str) -> Project | None:
        return self._by_namespace.get(str(namespace or "").strip())

    def by_scope(self, scope: str) -> Project | None:
        return self._by_scope.get(str(scope or "").rstrip("/"))

    def tag_of(self, namespace: str) -> str:
        project = self.by_namespace(namespace)
        return project.tag if project else ""

    def source_label(self, namespace: str) -> str:
        project = self.by_namespace(namespace)
        return project.source_label(namespace) if project else ""

    def namespaces_of(self, tag: str) -> tuple[str, ...]:
        project = self.by_tag(tag)
        return tuple(project.namespaces) if project else ()

    def scopes(self) -> dict[str, str]:
        """scope → tag для каждого проекта, принимающего задачи."""
        return {project.scope: project.tag for project in self.projects if project.scope}

    def open_tags(self) -> tuple[str, ...]:
        return tuple(p.tag for p in self.projects if not p.archived)


def _require(condition: object, message: str) -> None:
    if not condition:
        raise CatalogError(message)


def _parse_entries(entries: object, source: str) -> list[Project]:
    """Разобрать записи ОДНОГО файла в Project'ы. Конфликты тега/namespace/scope
    между разными файлами (и даже внутри одного) проверяет `_aggregate` — так один
    и тот же код ловит их что при чтении своего файла, что при слиянии нескольких."""
    _require(isinstance(entries, list), f"{source}: projects должен быть списком")
    assert isinstance(entries, list)

    projects: list[Project] = []
    for entry in entries:
        _require(isinstance(entry, dict), f"{source}: запись проекта должна быть отображением")
        assert isinstance(entry, dict)
        unknown = set(entry) - _ENTRY_FIELDS
        _require(not unknown, f"{source}: неизвестные поля проекта: {', '.join(sorted(unknown))}")

        tag = str(entry.get("tag") or "").strip()
        _require(_TAG.fullmatch(tag), f"{source}: тег '{tag}' должен быть вида [a-z0-9][a-z0-9-]*")

        name = str(entry.get("name") or "").strip()
        _require(name, f"{source}: у проекта '{tag}' пустое имя")

        raw_namespaces = entry.get("namespaces")
        _require(isinstance(raw_namespaces, dict) and raw_namespaces,
                 f"{source}: у проекта '{tag}' должен быть непустой namespaces")
        assert isinstance(raw_namespaces, dict)
        namespaces: dict[str, str] = {}
        for namespace, label in raw_namespaces.items():
            namespace = str(namespace)
            _require(_NAMESPACE.fullmatch(namespace),
                     f"{source}: namespace '{namespace}' не является безопасным для пути идентификатором")
            namespaces[namespace] = "" if label is None else str(label).strip()

        archived = bool(entry.get("archived", False))
        scope = str(entry.get("scope") or "").rstrip("/")
        write_namespace = str(entry.get("write_namespace") or "").strip()

        if scope:
            _require(scope.startswith("/"), f"{source}: scope проекта '{tag}' должен быть абсолютным путём")
            _require(not archived, f"{source}: архивный проект '{tag}' не может принимать задачи — убери scope")
            _require(write_namespace,
                     f"{source}: у проекта '{tag}' есть scope, но не задан write_namespace")
        if write_namespace:
            _require(write_namespace in namespaces,
                     f"{source}: write_namespace '{write_namespace}' проекта '{tag}' отсутствует в его namespaces")

        projects.append(Project(tag=tag, name=name, scope=scope, write_namespace=write_namespace,
                                namespaces=namespaces, archived=archived, source=source))
    return projects


def _parse_file(data: object, source: str) -> tuple[list[Project], tuple[str, ...]]:
    _require(isinstance(data, dict), f"{source}: каталог должен быть отображением")
    assert isinstance(data, dict)
    _require(data.get("version") == 1, f"{source}: поддерживается только version: 1")
    projects = _parse_entries(data.get("projects"), source)

    raw_includes = data.get("include_scopes") or []
    _require(isinstance(raw_includes, list), f"{source}: include_scopes должен быть списком")
    includes: list[str] = []
    for value in raw_includes:
        path = str(value).rstrip("/")
        _require(path.startswith("/"), f"{source}: include_scopes должен состоять из абсолютных путей: '{path}'")
        _require(path not in includes, f"{source}: include_scopes повторяет '{path}'")
        includes.append(path)
    return projects, tuple(includes)


def _aggregate(projects: list[Project]) -> Catalog:
    by_tag: dict[str, Project] = {}
    by_namespace: dict[str, Project] = {}
    by_scope: dict[str, Project] = {}
    for project in projects:
        owner = by_tag.get(project.tag)
        _require(owner is None,
                 f"{project.source}: тег '{project.tag}' уже объявлен в {owner.source if owner else ''}")
        for namespace in project.namespaces:
            ns_owner = by_namespace.get(namespace)
            _require(ns_owner is None,
                     f"{project.source}: namespace '{namespace}' заявлен и в "
                     f"'{ns_owner.tag if ns_owner else ''}' ({ns_owner.source if ns_owner else ''}), "
                     f"и в '{project.tag}'")
        if project.scope:
            scope_owner = by_scope.get(project.scope)
            _require(scope_owner is None,
                     f"{project.source}: scope '{project.scope}' заявлен и в "
                     f"'{scope_owner.tag if scope_owner else ''}' ({scope_owner.source if scope_owner else ''}), "
                     f"и в '{project.tag}'")
        by_tag[project.tag] = project
        for namespace in project.namespaces:
            by_namespace[namespace] = project
        if project.scope:
            by_scope[project.scope] = project
    return Catalog(projects=tuple(projects), _by_tag=by_tag,
                   _by_namespace=by_namespace, _by_scope=by_scope)


_LOCK = threading.Lock()
_FILE_CACHE: dict[str, tuple[tuple[int, int], tuple[list[Project], tuple[str, ...]]]] = {}


def _load_file(path: Path) -> tuple[list[Project], tuple[str, ...]]:
    """Разобранное содержимое одного файла; перечитывается, когда файл изменился —
    правка каталога действует без рестарта, а рестарт у нас инициирует только владелец."""
    try:
        stat = path.stat()
    except OSError as error:
        raise CatalogError(f"каталог проектов недоступен: {path} ({error.strerror})") from error
    key = (stat.st_mtime_ns, stat.st_size)
    cache_key = str(path)
    with _LOCK:
        cached = _FILE_CACHE.get(cache_key)
        if cached is not None and cached[0] == key:
            return cached[1]
    parsed = _parse_file(yaml.safe_load(path.read_text(encoding="utf-8")), str(path))
    with _LOCK:
        _FILE_CACHE[cache_key] = (key, parsed)
    return parsed


def reset_cache() -> None:
    with _LOCK:
        _FILE_CACHE.clear()


def catalog_path() -> Path:
    """Домашний файл этой установки — сироты без scope и точка входа в слитый вид."""
    override = os.environ.get("ORCHESTRA_PROJECT_CATALOG", "").strip()
    return Path(override) if override else CATALOG_PATH


def scope_root(scope: str) -> Path:
    """Физический каталог, отвечающий за `scope`. В проде это сам `scope`; тесты и
    миграция переопределяют корень через `ORCHESTRA_PROJECT_CATALOG_ROOT`, чтобы не
    трогать реальные пути чужих проектов вне явно выделенной песочницы."""
    scope = str(scope or "").rstrip("/")
    _require(scope, "scope is required to locate its own project catalog")
    root = os.environ.get("ORCHESTRA_PROJECT_CATALOG_ROOT", "").strip()
    if root:
        return Path(root) / project_key(scope)
    return Path(scope)


def own_catalog_path(scope: str) -> Path:
    return scope_root(scope) / ".orchestra" / "projects.yaml"


def own_catalog(scope: str) -> Catalog:
    """Каталог одного оркестратора: ровно его файл, ничего чужого.

    Это то, что оркестратор scope может увидеть в UI и передать в тулы — словарь
    тегов, закрытый ЭТИМ файлом. Чужой тег сюда попасть не может по построению.

    Отсутствующий файл — не авария, а обычное состояние scope, который ещё не завёл
    свой каталог (или никогда не будет — он просто ничего не тегирует): пустой
    каталог, а не громкий отказ. Громко падает только испорченный существующий файл."""
    path = own_catalog_path(scope)
    if not path.is_file():
        return _aggregate([])
    projects, _includes = _load_file(path)
    return _aggregate(projects)


def catalog() -> Catalog:
    """Слитый вид: домашний файл этой установки плюс каждый её include_scopes.

    Только для внутренней бухгалтерии платформы, которая физически обслуживает все
    scope разом (проекция номеров при старте, метка источника чужого пространства
    рядом с номером). Не источник того, что видит или может выставить один
    оркестратор — для этого `own_catalog(scope)`."""
    home_projects, includes = _load_file(catalog_path())
    combined = list(home_projects)
    for scope in includes:
        included, _nested = _load_file(own_catalog_path(scope))
        combined.extend(included)
    return _aggregate(combined)
