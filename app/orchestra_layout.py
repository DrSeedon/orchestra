"""Forced, recoverable migration of project-local Orchestra state to .orchestra/."""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
import uuid
from collections.abc import Mapping
from contextlib import nullcontext
from pathlib import Path
from typing import Any

from app.workspace import repo_mutation_lock


# LEGACY_PATH_FIXTURE: old roots are one-way migration sources, never read fallbacks.
OLD_TO_NEW = {
    "kb": (Path("docs/kb"), Path(".orchestra/kb")),
    "tasks": (Path("docs/tasks"), Path(".orchestra/tasks")),
    "workers": (Path("docs/workers"), Path(".orchestra/workers")),
    "archive": (Path("docs/archive"), Path(".orchestra/archive")),
}
LAYOUT_FILE = Path(".orchestra/layout.json")
JOURNAL_FILE = Path(".orchestra/.layout-migration.json")


def _run(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        text=True,
        capture_output=True,
        check=False,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
    )
    if check and result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}"
        raise RuntimeError(f"git {' '.join(args)} failed: {detail}")
    return result


def _run_bytes(
    repo: Path, *args: str, check: bool = True, input_bytes: bytes | None = None
) -> subprocess.CompletedProcess[bytes]:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        input=input_bytes,
        capture_output=True,
        check=False,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
    )
    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout).decode("utf-8", "replace").strip()
        raise RuntimeError(f"git {' '.join(args)} failed: {detail or f'exit {result.returncode}'}")
    return result


def _canonical_json(value: Mapping[str, Any]) -> str:
    return json.dumps(
        dict(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ) + "\n"


def _repair_command(repository: Path) -> str:
    script = Path(__file__).resolve().parents[1] / "scripts" / "migrate_orchestra_layout.py"
    return " ".join(
        shlex.quote(value)
        for value in (sys.executable, str(script), "--repair", str(repository.resolve()))
    )


class LayoutMigrationError(RuntimeError):
    def __init__(self, code: str, repository: Path, detail: str) -> None:
        self.code = code
        self.repository = repository.resolve()
        self.repair_command = _repair_command(self.repository)
        super().__init__(
            f"{code}: {detail}; repository={self.repository}; repair: {self.repair_command}"
        )


def _raise(code: str, repository: Path, detail: str) -> None:
    raise LayoutMigrationError(code, repository, detail)


def _git_root(repository: Path) -> Path:
    repository = Path(repository).expanduser().resolve()
    result = _run(repository, "rev-parse", "--show-toplevel", check=False)
    if result.returncode != 0:
        _raise("ORCHESTRA_LAYOUT_GIT_ERROR", repository, "repository is not a Git checkout")
    observed = Path(result.stdout.strip()).resolve()
    if observed != repository:
        _raise(
            "ORCHESTRA_LAYOUT_GIT_ERROR",
            repository,
            f"repository must be its Git top-level ({observed})",
        )
    return repository


def _layout_state(
    repository: Path, *, ignore_journal: bool = False
) -> tuple[str, list[str]]:
    old = {name for name, (source, _) in OLD_TO_NEW.items() if (repository / source).exists()}
    new = {name for name, (_, target) in OLD_TO_NEW.items() if (repository / target).exists()}
    layout_file = repository / LAYOUT_FILE
    journal = repository / JOURNAL_FILE
    if layout_file.is_file() and not old and (ignore_journal or not journal.exists()):
        try:
            value = json.loads(layout_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return "partial", sorted(new)
        managed = value.get("managed_paths") if isinstance(value, dict) else None
        if (
            value.get("schema_version") == 1
            and value.get("layout") == ".orchestra"
            and isinstance(managed, list)
            and all(isinstance(item, str) for item in managed)
            and set(managed) <= set(OLD_TO_NEW)
            and set(managed) <= new
        ):
            return "current", sorted(set(managed))
        return "partial", sorted(new)
    if (journal.exists() and not ignore_journal) or (old and new) or (
        new and not layout_file.is_file()
    ):
        return "partial", sorted(old | new)
    if old:
        return "old", sorted(old)
    return "missing", []


def _status(repository: Path) -> tuple[str, list[str]]:
    raw = _run(repository, "status", "--porcelain=v1", "-z").stdout
    entries = [item for item in raw.split("\0") if item]
    paths: list[str] = []
    skip_source = False
    for entry in entries:
        if skip_source:
            paths.append(entry)
            skip_source = False
            continue
        paths.append(entry[3:] if len(entry) >= 4 else entry)
        if entry[:2].strip() in {"R", "C"}:
            skip_source = True
    return raw, paths


def _status_records(repository: Path) -> list[dict[str, str]]:
    raw = _run(
        repository, "status", "--porcelain=v1", "-z", "--untracked-files=all"
    ).stdout
    tokens = raw.split("\0")
    records: list[dict[str, str]] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        index += 1
        if not token:
            continue
        record = {"xy": token[:2], "path": token[3:]}
        if token[:2].strip() in {"R", "C"}:
            record["original"] = tokens[index]
            index += 1
        records.append(record)
    return records


def _map_legacy_path(path: str) -> str:
    for source, target in OLD_TO_NEW.values():
        old = source.as_posix()
        if path == old or path.startswith(old + "/"):
            return target.as_posix() + path[len(old):]
    return path


def _mapped_status_records(records: list[dict[str, str]]) -> list[dict[str, str]]:
    mapped = []
    for record in records:
        item = {**record, "path": _map_legacy_path(record["path"])}
        if "original" in item:
            item["original"] = _map_legacy_path(item["original"])
        mapped.append(item)
    return sorted(mapped, key=lambda item: (item["path"], item["xy"], item.get("original", "")))


def _preserve_journal_path(repository: Path) -> Path:
    raw = _run(repository, "rev-parse", "--git-path", "orchestra-layout-preserve.json").stdout
    path = Path(raw.strip())
    return path.resolve() if path.is_absolute() else (repository / path).resolve()


def _write_preserve_journal(path: Path, value: Mapping[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(_canonical_json(value), encoding="utf-8")
    temporary.replace(path)


def _tree_entry(repository: Path, tree: str, path: str) -> tuple[str, str, str] | None:
    raw = _run_bytes(repository, "ls-tree", "-z", tree, "--", path).stdout
    if not raw:
        return None
    metadata, observed = raw.rstrip(b"\0").split(b"\t", 1)
    if observed.decode("utf-8") != path:
        raise RuntimeError(f"git tree returned an unexpected path for {path}")
    mode, object_type, blob = metadata.decode("ascii").split()
    return mode, object_type, blob


def _diff_paths(repository: Path, before: str, after: str) -> list[str]:
    raw = _run_bytes(
        repository, "diff", "--name-only", "-z", "--no-renames", before, after
    ).stdout
    return [item.decode("utf-8") for item in raw.split(b"\0") if item]


def _set_index_entry(
    repository: Path, path: str, entry: tuple[str, str, str] | None
) -> None:
    if entry is None:
        _run(repository, "update-index", "--force-remove", "--", path)
        return
    mode, object_type, blob = entry
    if object_type not in {"blob", "commit"}:
        raise RuntimeError(f"unsupported index object type for {path}: {object_type}")
    _run(repository, "update-index", "--add", "--cacheinfo", mode, blob, path)


def _write_worktree_entry(
    repository: Path, path: str, entry: tuple[str, str, str] | None
) -> None:
    destination = repository / path
    if entry is None:
        if destination.is_symlink() or destination.is_file():
            destination.unlink()
        return
    mode, object_type, blob = entry
    if object_type != "blob":
        raise RuntimeError(f"cannot restore worktree object type for {path}: {object_type}")
    content = _run_bytes(repository, "cat-file", "blob", blob).stdout
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_symlink() or destination.exists():
        if destination.is_dir():
            raise RuntimeError(f"cannot replace directory with preserved file: {path}")
        destination.unlink()
    if mode == "120000":
        destination.symlink_to(content.decode("utf-8"))
    else:
        destination.write_bytes(content)
        destination.chmod(0o755 if mode == "100755" else 0o644)


def _stash_ref(repository: Path, stash_oid: str) -> str | None:
    for line in _run(repository, "stash", "list", "--format=%H%x09%gd").stdout.splitlines():
        oid, ref = line.split("\t", 1)
        if oid == stash_oid:
            return ref
    return None


def _stash_oid_for_message(repository: Path, message: str) -> str | None:
    matches = []
    for line in _run(repository, "stash", "list", "--format=%H%x09%gs").stdout.splitlines():
        oid, subject = line.split("\t", 1)
        if subject.endswith(message):
            matches.append(oid)
    return matches[0] if len(matches) == 1 else None


def _untracked_stash_paths(repository: Path, stash_oid: str) -> list[str]:
    tree = f"{stash_oid}^3"
    if _run(repository, "cat-file", "-e", tree, check=False).returncode != 0:
        return []
    raw = _run_bytes(repository, "ls-tree", "-r", "-z", "--name-only", tree).stdout
    return [item.decode("utf-8") for item in raw.split(b"\0") if item]


def _expand_untracked_records(
    records: list[dict[str, str]], untracked_paths: list[str]
) -> list[dict[str, str]]:
    expanded = []
    for record in records:
        path = record["path"]
        if record["xy"] == "??" and path.endswith("/"):
            matches = [item for item in untracked_paths if item.startswith(path)]
            expanded.extend({"xy": "??", "path": item} for item in matches)
        else:
            expanded.append(record)
    return expanded


def _managed_from_stash(repository: Path, stash_oid: str) -> list[str]:
    trees = [
        tree
        for tree in (f"{stash_oid}^3", stash_oid, f"{stash_oid}^2")
        if _run(repository, "cat-file", "-e", tree, check=False).returncode == 0
    ]
    managed = []
    for name, (source, target) in OLD_TO_NEW.items():
        if (repository / source).exists() or (repository / target).exists():
            managed.append(name)
            continue
        if any(_tree_entry(repository, tree, source.as_posix()) for tree in trees):
            managed.append(name)
            continue
        if any(
            _run_bytes(repository, "ls-tree", "-r", "-z", tree, "--", source.as_posix()).stdout
            for tree in trees
        ):
            managed.append(name)
    return sorted(managed)


def _ensure_managed_placeholders(repository: Path, managed: list[str]) -> None:
    for name in managed:
        source, target = OLD_TO_NEW[name]
        if not (repository / source).exists() and not (repository / target).exists():
            (repository / source).mkdir(parents=True)


def _restore_preserved_stash(
    repository: Path, source_head: str, stash_oid: str
) -> None:
    index_tree = f"{stash_oid}^2"
    dirty_paths = set(_diff_paths(repository, source_head, index_tree))
    dirty_paths.update(_diff_paths(repository, index_tree, stash_oid))
    for path in sorted(dirty_paths):
        target = _map_legacy_path(path)
        _set_index_entry(repository, target, _tree_entry(repository, index_tree, path))
        _write_worktree_entry(repository, target, _tree_entry(repository, stash_oid, path))

    untracked_tree = f"{stash_oid}^3"
    if _run(repository, "cat-file", "-e", untracked_tree, check=False).returncode == 0:
        raw = _run_bytes(
            repository, "ls-tree", "-r", "-z", "--name-only", untracked_tree
        ).stdout
        for item in raw.split(b"\0"):
            if not item:
                continue
            path = item.decode("utf-8")
            _write_worktree_entry(
                repository,
                _map_legacy_path(path),
                _tree_entry(repository, untracked_tree, path),
            )


def _recover_preserved_dirty(
    repository: Path, preserve_journal: Path, journal: Mapping[str, Any]
) -> dict[str, Any] | None:
    source_head = str(journal.get("source_head") or "")
    stash_oid = str(journal.get("stash_oid") or "") or (
        _stash_oid_for_message(repository, str(journal.get("stash_message") or "")) or ""
    )
    before_records = list(journal.get("status_records") or [])
    if not stash_oid:
        head = _run(repository, "rev-parse", "HEAD").stdout.strip()
        observed_records = sorted(
            _status_records(repository),
            key=lambda item: (item["path"], item["xy"], item.get("original", "")),
        )
        if (
            head == source_head
            and observed_records
            == sorted(
                before_records,
                key=lambda item: (item["path"], item["xy"], item.get("original", "")),
            )
        ):
            preserve_journal.unlink()
            return None
        state, managed = _layout_state(repository)
        expected_records = _mapped_status_records(before_records)
        if state == "current" and observed_records == expected_records:
            preserve_journal.unlink()
            return {
                "status": "recovered",
                "repository": str(repository),
                "managed_paths": managed,
                "commit": head,
                "repair_command": _repair_command(repository),
                "dirty_preserved": True,
                "dirty_status_before": list(journal.get("status_short") or []),
                "dirty_status_after": _run(
                    repository, "status", "--short"
                ).stdout.splitlines(),
            }
        _raise(
            "ORCHESTRA_LAYOUT_GIT_ERROR",
            repository,
            "dirty-worktree recovery journal has no recoverable stash",
        )

    before_records = _expand_untracked_records(
        before_records, _untracked_stash_paths(repository, stash_oid)
    )
    managed = list(journal.get("managed_paths") or _managed_from_stash(repository, stash_oid))
    _ensure_managed_placeholders(repository, managed)
    phase = str(journal.get("phase") or "")
    state, _ = _layout_state(repository)
    head = _run(repository, "rev-parse", "HEAD").stdout.strip()
    if phase != "migrated":
        if head == source_head:
            residual = _status_records(repository)
            unexpected = [record for record in residual if record not in before_records]
            if unexpected:
                _raise(
                    "ORCHESTRA_LAYOUT_GIT_ERROR",
                    repository,
                    "worktree changed after the preserve snapshot; "
                    f"stash={stash_oid} unexpected={unexpected[:5]}",
                )
            result = migrate_project_layout(
                repository,
                repair=state == "partial",
                _lock=False,
                _allow_dirty=True,
            )
            managed = list(result.get("managed_paths") or [])
            head = _run(repository, "rev-parse", "HEAD").stdout.strip()
        elif state != "current":
            _raise(
                "ORCHESTRA_LAYOUT_GIT_ERROR",
                repository,
                f"cannot locate the migration commit while recovering stash={stash_oid}",
            )

    _restore_preserved_stash(repository, source_head, stash_oid)
    expected_records = _mapped_status_records(before_records)
    observed_records = sorted(
        _status_records(repository),
        key=lambda item: (item["path"], item["xy"], item.get("original", "")),
    )
    status_after = _run(repository, "status", "--short").stdout.splitlines()
    if observed_records != expected_records:
        _raise(
            "ORCHESTRA_LAYOUT_GIT_ERROR",
            repository,
            "dirty status changed during recovery; "
            f"stash={stash_oid} expected={expected_records[:5]} "
            f"observed={observed_records[:5]}",
        )
    stash_ref = _stash_ref(repository, stash_oid)
    if stash_ref is not None:
        _run(repository, "stash", "drop", "-q", stash_ref)
    preserve_journal.unlink()
    return {
        "status": "recovered",
        "repository": str(repository),
        "managed_paths": managed,
        "commit": head,
        "repair_command": _repair_command(repository),
        "dirty_preserved": True,
        "dirty_status_before": list(journal.get("status_short") or []),
        "dirty_status_after": status_after,
    }


def _repair_dirty_is_allowed(paths: list[str]) -> bool:
    allowed = ("docs/kb", "docs/tasks", "docs/workers", "docs/archive", ".orchestra")
    return all(path == ".gitignore" or path.startswith(allowed) for path in paths)


def _layout_file_is_staged_new(repository: Path) -> bool:
    staged = _run(
        repository,
        "diff",
        "--cached",
        "--name-status",
        "--",
        LAYOUT_FILE.as_posix(),
    ).stdout
    return any(line == f"A\t{LAYOUT_FILE.as_posix()}" for line in staged.splitlines())


def _journal_is_only_change(repository: Path, dirty_paths: list[str]) -> bool:
    return (repository / JOURNAL_FILE).is_file() and all(
        path == JOURNAL_FILE.as_posix() for path in dirty_paths
    )


def _ensure_not_ignored(repository: Path, managed: list[str]) -> None:
    gitignore = repository / ".gitignore"
    text = gitignore.read_text(encoding="utf-8") if gitignore.exists() else ""
    block = "# Orchestra project state is canonical Git data.\n!.orchestra/\n!.orchestra/**\n"
    if block not in text:
        if text and not text.endswith("\n"):
            text += "\n"
        gitignore.write_text(text + block, encoding="utf-8")
    for name in managed:
        _, target = OLD_TO_NEW[name]
        candidate = repository / target
        files = [path for path in candidate.rglob("*") if path.is_file()]
        probe = files[0] if files else candidate
        ignored = _run(repository, "check-ignore", str(probe.relative_to(repository)), check=False)
        if ignored.returncode == 0:
            _raise(
                "ORCHESTRA_LAYOUT_GIT_ERROR",
                repository,
                f"new project state is ignored: {probe.relative_to(repository)}",
            )
        if ignored.returncode not in {1, 128}:
            _raise(
                "ORCHESTRA_LAYOUT_GIT_ERROR",
                repository,
                ignored.stderr.strip() or "cannot verify Git ignore state",
            )


def require_project_layout(repository: Path) -> Path:
    repository = _git_root(Path(repository))
    state, managed = _layout_state(repository)
    if state == "current":
        return repository / ".orchestra"
    detail = f"layout state={state}; managed={managed or 'none'}"
    code = {
        "missing": "ORCHESTRA_LAYOUT_MISSING",
        "partial": "ORCHESTRA_LAYOUT_PARTIAL",
        "old": "ORCHESTRA_LAYOUT_MISSING",
    }[state]
    _raise(code, repository, detail)


def migrate_project_layout(
    repository: Path,
    *,
    repair: bool = False,
    _lock: bool = True,
    _allow_dirty: bool = False,
) -> dict[str, Any]:
    repository = _git_root(Path(repository))
    lock = repo_mutation_lock(repository) if _lock else nullcontext()
    with lock:
        state, managed = _layout_state(repository)
        if state == "current":
            raw_status, dirty_paths = _status(repository)
            if not raw_status or _allow_dirty:
                return {
                    "status": "already_current",
                    "repository": str(repository),
                    "managed_paths": managed,
                    "repair_command": _repair_command(repository),
                }
            if not _layout_file_is_staged_new(repository):
                _raise(
                    "ORCHESTRA_LAYOUT_DIRTY",
                    repository,
                    f"current layout working tree is dirty: {dirty_paths[:5]}",
                )
            if not repair:
                _raise(
                    "ORCHESTRA_LAYOUT_PARTIAL",
                    repository,
                    "layout files are staged but the migration commit is missing",
                )
        if state == "missing":
            _raise("ORCHESTRA_LAYOUT_MISSING", repository, "no old or new project state exists")
        if state == "partial" and not repair:
            _raise(
                "ORCHESTRA_LAYOUT_PARTIAL",
                repository,
                f"old/new project state is mixed; managed={managed or 'none'}",
            )

        raw_status, dirty_paths = _status(repository)
        state_without_journal, managed_without_journal = _layout_state(
            repository, ignore_journal=True
        )
        if (
            repair
            and state == "partial"
            and state_without_journal == "current"
            and _journal_is_only_change(repository, dirty_paths)
        ):
            (repository / JOURNAL_FILE).unlink()
            return {
                "status": "repaired",
                "repository": str(repository),
                "managed_paths": managed_without_journal,
                "commit": _run(repository, "rev-parse", "HEAD").stdout.strip(),
                "repair_command": _repair_command(repository),
            }
        if raw_status and not _allow_dirty and (
            not repair or not _repair_dirty_is_allowed(dirty_paths)
        ):
            _raise(
                "ORCHESTRA_LAYOUT_DIRTY",
                repository,
                f"working tree is dirty: {dirty_paths[:5]}",
            )

        managed = sorted(
            name
            for name, (source, target) in OLD_TO_NEW.items()
            if (repository / source).exists() or (repository / target).exists()
        )
        if not managed:
            _raise("ORCHESTRA_LAYOUT_MISSING", repository, "no managed project paths exist")

        duplicate = [
            name
            for name in managed
            if (repository / OLD_TO_NEW[name][0]).exists()
            and (repository / OLD_TO_NEW[name][1]).exists()
        ]
        if duplicate:
            _raise(
                "ORCHESTRA_LAYOUT_PARTIAL",
                repository,
                f"both old and new paths exist: {duplicate}",
            )

        try:
            orchestra_root = repository / ".orchestra"
            orchestra_root.mkdir(parents=True, exist_ok=True)
            journal = {
                "schema_version": 1,
                "source_head": _run(repository, "rev-parse", "HEAD").stdout.strip(),
                "moves": {
                    OLD_TO_NEW[name][0].as_posix(): OLD_TO_NEW[name][1].as_posix()
                    for name in managed
                },
            }
            (repository / JOURNAL_FILE).write_text(_canonical_json(journal), encoding="utf-8")

            for name in managed:
                source, target = OLD_TO_NEW[name]
                source_path = repository / source
                target_path = repository / target
                if target_path.exists():
                    continue
                target_path.parent.mkdir(parents=True, exist_ok=True)
                tracked = _run(repository, "ls-files", "-z", "--", source.as_posix()).stdout
                if tracked:
                    _run(repository, "mv", source.as_posix(), target.as_posix())
                else:
                    shutil.move(str(source_path), str(target_path))

            _ensure_not_ignored(repository, managed)
            layout = {
                "schema_version": 1,
                "layout": ".orchestra",
                "managed_paths": managed,
            }
            (repository / LAYOUT_FILE).write_text(_canonical_json(layout), encoding="utf-8")
            migration_candidates = [
                ".gitignore",
                LAYOUT_FILE.as_posix(),
                *(
                    path.as_posix()
                    for name in managed
                    for path in OLD_TO_NEW[name]
                ),
            ]
            migration_paths = [
                path
                for path in migration_candidates
                if (repository / path).exists()
                or bool(_run(repository, "ls-files", "--", path).stdout)
            ]
            _run(repository, "add", "-A", "--", *migration_paths)
            _run(repository, "reset", "-q", "--", JOURNAL_FILE.as_posix())

            observed, observed_managed = _layout_state(repository, ignore_journal=True)
            if observed != "current" or observed_managed != managed:
                _raise(
                    "ORCHESTRA_LAYOUT_GIT_ERROR",
                    repository,
                    f"post-move layout is {observed}: {observed_managed}",
                )
            _run(
                repository,
                "-c", "user.name=Orchestra",
                "-c", "user.email=orchestra@localhost",
                "commit", "-qm", "Orchestra: migrate project state to .orchestra",
            )
            (repository / JOURNAL_FILE).unlink(missing_ok=True)
            if _status(repository)[0] and not _allow_dirty:
                _raise("ORCHESTRA_LAYOUT_GIT_ERROR", repository, "migration commit is not clean")
            commit = _run(repository, "rev-parse", "HEAD").stdout.strip()
            return {
                "status": "repaired" if repair else "migrated",
                "repository": str(repository),
                "managed_paths": managed,
                "commit": commit,
                "repair_command": _repair_command(repository),
            }
        except LayoutMigrationError:
            raise
        except Exception as exc:
            _raise("ORCHESTRA_LAYOUT_GIT_ERROR", repository, str(exc))


def migrate_project_layout_preserving_dirty(repository: Path) -> dict[str, Any]:
    """Migrate one checkout while restoring its staged, unstaged and untracked work."""
    repository = _git_root(Path(repository))
    with repo_mutation_lock(repository):
        preserve_journal = _preserve_journal_path(repository)
        if preserve_journal.exists():
            value = json.loads(preserve_journal.read_text(encoding="utf-8"))
            recovered = _recover_preserved_dirty(repository, preserve_journal, value)
            if recovered is not None:
                return recovered

        before_records = _status_records(repository)
        if not before_records:
            return migrate_project_layout(repository, repair=False, _lock=False)
        _, managed_before = _layout_state(repository)
        unmerged = _run(
            repository, "diff", "--name-only", "--diff-filter=U", check=False
        ).stdout.splitlines()
        if unmerged:
            _raise(
                "ORCHESTRA_LAYOUT_DIRTY",
                repository,
                f"unmerged paths cannot be preserved automatically: {unmerged[:5]}",
            )

        source_head = _run(repository, "rev-parse", "HEAD").stdout.strip()
        status_before = _run(repository, "status", "--short").stdout.splitlines()
        transaction_id = uuid.uuid4().hex
        stash_message = f"orchestra-layout-preserve:{transaction_id}"
        journal: dict[str, Any] = {
            "schema_version": 1,
            "phase": "before_stash",
            "source_head": source_head,
            "stash_message": stash_message,
            "stash_oid": "",
            "managed_paths": managed_before,
            "status_records": before_records,
            "status_short": status_before,
        }
        _write_preserve_journal(preserve_journal, journal)
        _run(repository, "stash", "push", "--include-untracked", "-m", stash_message)
        stash_oid = _stash_oid_for_message(repository, stash_message) or ""
        journal.update({"phase": "stashed", "stash_oid": stash_oid})
        _write_preserve_journal(preserve_journal, journal)
        residual = _status_records(repository)
        unexpected = [record for record in residual if record not in before_records]
        if unexpected:
            _raise(
                "ORCHESTRA_LAYOUT_GIT_ERROR",
                repository,
                "stash left changes outside the preserve snapshot; "
                f"stash={stash_oid} unexpected={unexpected[:5]}",
            )

        _ensure_managed_placeholders(repository, managed_before)
        state, _ = _layout_state(repository)
        result = migrate_project_layout(
            repository,
            repair=state == "partial",
            _lock=False,
            _allow_dirty=True,
        )
        journal.update({"phase": "migrated", "migration_commit": result.get("commit", "")})
        _write_preserve_journal(preserve_journal, journal)

        if stash_oid:
            _restore_preserved_stash(repository, source_head, stash_oid)
        expected_records = _mapped_status_records(before_records)
        observed_records = sorted(
            _status_records(repository),
            key=lambda item: (item["path"], item["xy"], item.get("original", "")),
        )
        status_after = _run(repository, "status", "--short").stdout.splitlines()
        if observed_records != expected_records:
            _raise(
                "ORCHESTRA_LAYOUT_GIT_ERROR",
                repository,
                "dirty status changed while restoring preserved work; "
                f"stash={stash_oid} expected={expected_records[:5]} "
                f"observed={observed_records[:5]}",
            )
        if stash_oid:
            stash_ref = _stash_ref(repository, stash_oid)
            if stash_ref is None:
                _raise(
                    "ORCHESTRA_LAYOUT_GIT_ERROR",
                    repository,
                    f"preserved stash disappeared before verification: {stash_oid}",
                )
            _run(repository, "stash", "drop", "-q", stash_ref)
        preserve_journal.unlink()
        return {
            **result,
            "dirty_preserved": True,
            "dirty_status_before": status_before,
            "dirty_status_after": status_after,
        }


def migrate_registered_projects(
    project_roots: Mapping[str, Path],
    *,
    preserve_dirty: bool = False,
) -> dict[str, dict[str, Any]]:
    results: dict[str, dict[str, Any]] = {}
    for project_id, repository in sorted(project_roots.items()):
        try:
            if preserve_dirty:
                result = migrate_project_layout_preserving_dirty(Path(repository))
            else:
                result = migrate_project_layout(Path(repository), repair=False)
            results[str(project_id)] = result
        except LayoutMigrationError as exc:
            results[str(project_id)] = {
                "status": "failed",
                "code": exc.code,
                "repository": str(exc.repository),
                "error": str(exc),
                "repair_command": exc.repair_command,
            }
    return results


def migrate_registered_project_layouts() -> dict[str, dict[str, Any]]:
    """Force-migrate every canonical tm_projects.scope; failures stay per-project."""
    from app.db import _conn

    with _conn() as connection:
        rows = connection.execute(
            "SELECT id,scope FROM tm_projects WHERE scope IS NOT NULL AND trim(scope)!='' "
            "ORDER BY id"
        ).fetchall()
    roots = {str(row["id"]): Path(str(row["scope"])) for row in rows}
    return migrate_registered_projects(roots, preserve_dirty=True)
