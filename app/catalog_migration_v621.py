"""V-621: разбить общий `.orchestra/projects.yaml` на файл по каждому scope.

Выполняется самим сервисом при старте, по образцу `app/startup_migration.py` (V-576):
от владельца требуется один рестарт и ни одной команды на остановленной системе.

Идемпотентность держится на ключе `include_scopes` в домашнем файле, но это не разовый
маркер «было — стало»: пропущенный scope остаётся внутри `projects:` домашнего файла со
своим `scope:`, и каждый следующий запуск заново ищет там записи с чужим `scope` и
пробует их доразобрать. Полностью законченная миграция — это `include_scopes` есть И
внутри `projects:` не осталось ни одной записи с чужим `scope`; только тогда старт
ничего не делает.

**Деградация, а не отказ старта (решение владельца 23.09.2026, второй заход).** Первая
версия требовала, чтобы КАЖДЫЙ затронутый scope был чистым git-репозиторием, и роняла
СТАРТ службы, если хоть один из восьми чужих репозиториев в момент рестарта оказался
грязным — а починить это изнутри некому, агенты вместе с Orchestra лежат. Непригодный
scope (грязный, не существует на диске, нет прав на запись, любая иная ошибка при
записи/коммите) теперь просто пропускается с громкой записью в журнал: его запись
остаётся в домашнем файле как была — тег продолжает резолвиться через слитый вид
`catalog()`, просто ещё не через собственный `own_catalog(scope)`. Миграция идемпотентна,
поэтому пропущенный scope доедет сам — при следующем рестарте или когда владелец руками
почистит/создаст его каталог. Падать на старте можно только если ЧИТАТЬ НЕЧЕГО — домашний
файл каталога испорчен (не парсится или не той формы); эта ошибка не про чужой scope,
её некому починить снаружи, значит служба честно не поднимается, как и раньше.

Порядок шагов:
1. разбор домашнего файла — единственное, что ещё может уронить старт;
2. бэкап старого домашнего файла — рядом, с меткой времени, всегда;
3. по каждому scope из старого файла — попытка завести его собственный файл
   (создать каталог, записать, закоммитить, если это git); любая ошибка здесь дом
   scope просто пропускает — он остаётся как есть в домашнем файле;
4. новый домашний файл: `include_scopes` — объединение прежних с тем, что удалось
   сейчас; `projects:` — то, что ещё не разобрано (включая пропущенное);
5. коммит домашнего файла — точечный, только по своим путям (`git commit -- <файлы>`),
   поэтому чужие незакоммиченные изменения в том же репозитории ему не мешают и в
   коммит не попадают; не заводится только если это вообще не git или git отказал.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import logging
import subprocess

import yaml

from app.project_catalog import own_catalog_path, reset_cache, scope_root


logger = logging.getLogger(__name__)


class CatalogMigrationError(RuntimeError):
    """Домашний каталог нечитаем — единственное, что валит старт службы."""


class _ScopeSkipped(RuntimeError):
    """Один конкретный scope непригоден для миграции сейчас. Не про домашний файл."""


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(root), *args],
                            capture_output=True, text=True, timeout=60)
    if result.returncode:
        raise _ScopeSkipped(
            f"git {' '.join(args)} in {root} failed: "
            f"{result.stderr.strip() or result.stdout.strip()}"
        )
    return result.stdout


def _is_git_repo(root: Path) -> bool:
    return (root / ".git").exists()


def _require_clean(root: Path, *, label: str) -> None:
    if not _is_git_repo(root):
        return
    status = subprocess.run(["git", "-C", str(root), "status", "--porcelain"],
                            capture_output=True, text=True, timeout=60)
    if status.returncode:
        raise _ScopeSkipped(f"git status in {root} ({label}) failed: {status.stderr.strip()}")
    if status.stdout.strip():
        raise _ScopeSkipped(
            f"{label} ({root}) has uncommitted changes; skipped until it is clean"
        )


def _dump(data: dict) -> str:
    return yaml.safe_dump(data, allow_unicode=True, sort_keys=False)


def _migrate_one_scope(scope: str, entries: list[dict]) -> None:
    """Завести собственный файл каталога для одного scope. Бросает `_ScopeSkipped`
    на любую причину — отсутствующий каталог, грязный git, отказ прав на запись."""
    root = scope_root(scope)
    if not root.is_dir():
        raise _ScopeSkipped(f"scope без каталога на диске: {root}")
    _require_clean(root, label=f"project catalog target '{scope}'")
    path = own_catalog_path(scope)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_dump({"version": 1, "projects": entries}), encoding="utf-8")
    except OSError as error:
        raise _ScopeSkipped(f"не удалось записать {path}: {error}") from error
    if _is_git_repo(root):
        rel = path.relative_to(root)
        _git(root, "add", "--", str(rel))
        _git(root, "commit", "-m", "V-621: собственный каталог проекта (выделен из Orchestra)")


def migrate_v621(home_path: Path) -> dict:
    """Идемпотентно перевести домашний каталог в форму V-621. Повторный старт ничего не делает.

    Отказывается стартовать только если домашний файл нечитаем; любая проблема с
    конкретным ЧУЖИМ scope (грязный git, отсутствующий каталог, отказ записи) даёт этому
    scope деградировать — он остаётся в домашнем файле как был, остальное едет дальше.
    """
    home_path = Path(home_path)
    if not home_path.is_file():
        return {"state": "fresh"}
    try:
        raw = yaml.safe_load(home_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as error:
        raise CatalogMigrationError(f"{home_path}: домашний файл каталога не парсится: {error}") from error
    if raw.get("version") != 1 or not isinstance(raw.get("projects"), list):
        raise CatalogMigrationError(f"{home_path}: неожиданная форма — читать нечего")
    already_migrated = isinstance(raw.get("include_scopes"), list)
    if "include_scopes" in raw and not already_migrated:
        raise CatalogMigrationError(f"{home_path}: неожиданная форма — читать нечего")

    home_scope = str(home_path.parent.parent.resolve())
    home_entries: list[dict] = []
    external: dict[str, list[dict]] = {}
    for entry in raw["projects"]:
        entry_scope = str((entry or {}).get("scope") or "").rstrip("/")
        if not entry_scope or entry_scope == home_scope:
            home_entries.append(entry)
        else:
            external.setdefault(entry_scope, []).append(entry)

    if already_migrated and not external:
        # Полностью разобрано в прошлый раз: ни одной чужой записи внутри projects:
        # не осталось, повторять нечего.
        return {"state": "already"}
    previous_includes = list(raw.get("include_scopes") or [])

    written: list[str] = []
    already: list[str] = []
    skipped: dict[str, str] = {}
    for scope, entries in external.items():
        if own_catalog_path(scope).exists():
            # Уже есть свой файл — прошлый (возможно частичный) прогон уже завёл его,
            # или владелец создал руками. Не перезаписываем, просто подхватываем.
            already.append(scope)
            continue
        try:
            _migrate_one_scope(scope, entries)
            written.append(scope)
        except _ScopeSkipped as error:
            # Каталог общий для машин: scope другой машины на этом диске отсутствует штатно
            # (ноутбук держит девять путей VPS), это не повод для предупреждения на каждом старте.
            level = logging.WARNING if scope_root(scope).is_dir() else logging.INFO
            logger.log(level, "V-621: scope '%s' пропущен, остаётся в домашнем файле: %s", scope, error)
            skipped[scope] = str(error)
            home_entries.extend(entries)

    if already_migrated and not written and not already:
        # Ни один scope не сдвинулся: домашний файл вышел бы байт-в-байт прежним, а
        # бэкап и коммит — новыми на каждом старте (V-634: ноутбук держит в каталоге
        # девять путей VPS, которых на его диске нет, — пять одинаковых коммитов за сутки).
        return {"state": "pending", "skipped": skipped}

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = home_path.with_name(f"{home_path.stem}-pre-v621-{stamp}{home_path.suffix}")
    backup.write_text(home_path.read_text(encoding="utf-8"), encoding="utf-8")

    new_home = {
        "version": 1,
        "include_scopes": sorted(set(previous_includes) | set(written) | set(already)),
        "projects": home_entries,
    }
    home_path.write_text(_dump(new_home), encoding="utf-8")
    reset_cache()

    home_root = home_path.parent.parent
    home_committed = False
    try:
        if _is_git_repo(home_root):
            rel_home = home_path.relative_to(home_root)
            rel_backup = backup.relative_to(home_root)
            _git(home_root, "add", "--", str(rel_home), str(rel_backup))
            _git(home_root, "commit", "-m",
                 "V-621: разбить общий каталог проектов на файлы по scope")
            home_committed = True
    except _ScopeSkipped as error:
        logger.warning(
            "V-621: домашний файл записан, но не закоммичен (%s) — почини руками", error,
        )

    logger.warning(
        "V-621 catalog split: home=%s written=%s already=%s skipped=%s home_committed=%s backup=%s",
        home_path, written, already, sorted(skipped), home_committed, backup,
    )
    return {
        "state": "migrated", "home": str(home_path), "external": written,
        "already": already, "skipped": skipped, "home_committed": home_committed,
        "backup": str(backup),
    }
