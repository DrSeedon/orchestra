"""Каталог проектов: один файл вместо двух таблиц.

Источник истины о том, что человек называет проектом, — ``.orchestra/projects.yaml``.
Файл правится руками и живёт в git, поэтому перечитывается по mtime: правка каталога
действует без рестарта, а рестарт у нас инициирует только владелец.

Каталог владеет тегом, именем, scope и целевым пространством номеров. Он НЕ владеет
номерами задач: номер выдаёт и разрешает namespace (`tm_tasks.project_id`), потому что
`#N` уникален только внутри пространства — на 15.09.2026 внутри тегов этого каталога
424 конфликтующие ссылки на 857 задач из 1755.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import re
import threading

import yaml


CATALOG_PATH = Path(__file__).parent.parent / ".orchestra" / "projects.yaml"

# Та же форма, что у `app.task_refs.project_key`: namespace становится именем каталога
# в Git-хранилище задач, поэтому он обязан быть безопасным для пути.
_NAMESPACE = re.compile(r"[a-z0-9][a-z0-9._-]*")
_TAG = re.compile(r"[a-z0-9][a-z0-9-]*")


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


def _parse(data: object, source: str) -> Catalog:
    _require(isinstance(data, dict), f"{source}: каталог должен быть отображением")
    assert isinstance(data, dict)
    _require(data.get("version") == 1, f"{source}: поддерживается только version: 1")
    entries = data.get("projects")
    # Пустой список законен: у свежей установки проектов ещё нет.
    _require(isinstance(entries, list), f"{source}: projects должен быть списком")
    assert isinstance(entries, list)

    projects: list[Project] = []
    by_tag: dict[str, Project] = {}
    by_namespace: dict[str, Project] = {}
    by_scope: dict[str, Project] = {}

    for entry in entries:
        _require(isinstance(entry, dict), f"{source}: запись проекта должна быть отображением")
        assert isinstance(entry, dict)
        unknown = set(entry) - {"tag", "name", "scope", "write_namespace", "namespaces", "archived"}
        _require(not unknown, f"{source}: неизвестные поля проекта: {', '.join(sorted(unknown))}")

        tag = str(entry.get("tag") or "").strip()
        _require(_TAG.fullmatch(tag), f"{source}: тег '{tag}' должен быть вида [a-z0-9][a-z0-9-]*")
        _require(tag not in by_tag, f"{source}: тег '{tag}' объявлен дважды")

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
            owner = by_namespace.get(namespace)
            _require(owner is None,
                     f"{source}: namespace '{namespace}' заявлен и в '{owner.tag if owner else ''}', и в '{tag}'")
            namespaces[namespace] = "" if label is None else str(label).strip()

        archived = bool(entry.get("archived", False))
        scope = str(entry.get("scope") or "").rstrip("/")
        write_namespace = str(entry.get("write_namespace") or "").strip()

        if scope:
            _require(scope.startswith("/"), f"{source}: scope проекта '{tag}' должен быть абсолютным путём")
            _require(not archived, f"{source}: архивный проект '{tag}' не может принимать задачи — убери scope")
            _require(write_namespace,
                     f"{source}: у проекта '{tag}' есть scope, но не задан write_namespace")
            other = by_scope.get(scope)
            _require(other is None,
                     f"{source}: scope '{scope}' заявлен и в '{other.tag if other else ''}', и в '{tag}'")
        if write_namespace:
            _require(write_namespace in namespaces,
                     f"{source}: write_namespace '{write_namespace}' проекта '{tag}' отсутствует в его namespaces")

        project = Project(tag=tag, name=name, scope=scope, write_namespace=write_namespace,
                          namespaces=namespaces, archived=archived)
        projects.append(project)
        by_tag[tag] = project
        for namespace in namespaces:
            by_namespace[namespace] = project
        if scope:
            by_scope[scope] = project

    return Catalog(projects=tuple(projects), _by_tag=by_tag,
                   _by_namespace=by_namespace, _by_scope=by_scope)


_LOCK = threading.Lock()
_CACHE: tuple[tuple[str, int, int], Catalog] | None = None


def catalog_path() -> Path:
    override = os.environ.get("ORCHESTRA_PROJECT_CATALOG", "").strip()
    return Path(override) if override else CATALOG_PATH


def catalog() -> Catalog:
    """Разобранный каталог; перечитывается, когда файл изменился."""
    global _CACHE
    path = catalog_path()
    try:
        stat = path.stat()
    except OSError as error:
        raise CatalogError(f"каталог проектов недоступен: {path} ({error.strerror})") from error
    key = (str(path), stat.st_mtime_ns, stat.st_size)
    with _LOCK:
        if _CACHE is not None and _CACHE[0] == key:
            return _CACHE[1]
    parsed = _parse(yaml.safe_load(path.read_text(encoding="utf-8")), str(path))
    with _LOCK:
        _CACHE = (key, parsed)
    return parsed


def reset_cache() -> None:
    global _CACHE
    with _LOCK:
        _CACHE = None
