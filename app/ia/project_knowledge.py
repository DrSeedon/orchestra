"""Process-global filesystem owner for project-local knowledge records."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import subprocess
import threading
import uuid
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any


class KnowledgeOwnerError(RuntimeError):
    pass


_PROJECT_ID = re.compile(r"[a-z0-9][a-z0-9._-]*")
_HEAD = re.compile(r"[0-9a-f]{40}")
_ACTIVE_ROUTER: "ProjectKnowledgeRouter | None" = None
_ACTIVE_LOCK = threading.RLock()


def _bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8") + b"\n"


def _read_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_bytes())
    except (OSError, json.JSONDecodeError) as exc:
        raise KnowledgeOwnerError(f"cannot read project knowledge: {path}") from exc
    if not isinstance(value, dict):
        raise KnowledgeOwnerError(f"project knowledge is not an object: {path}")
    return value


def _write_state(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0),
            0o600,
        )
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(_bytes(value))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(
        path,
        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0),
    )
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


class ProjectKnowledgeRouter:
    """Persist one global owner while resolving records only inside the caller's project."""

    def __init__(
        self,
        *,
        project_roots: Mapping[str, Path],
        engine_state_path: Path,
        central_reader: Callable[[str, str], Mapping[str, Any]],
    ) -> None:
        roots: dict[str, Path] = {}
        for raw_project_id, raw_root in project_roots.items():
            project_id = str(raw_project_id)
            if _PROJECT_ID.fullmatch(project_id) is None or project_id in roots:
                raise KnowledgeOwnerError(f"invalid project map identity: {project_id!r}")
            root = Path(raw_root).expanduser().resolve()
            if not root.is_dir():
                raise KnowledgeOwnerError(f"project root is missing: {root}")
            roots[project_id] = root
        self.project_roots = dict(sorted(roots.items()))
        self.engine_state_path = Path(engine_state_path).expanduser().absolute()
        self.central_reader = central_reader
        self._lock = threading.RLock()
        if not self.engine_state_path.exists():
            _write_state(
                self.engine_state_path,
                {
                    "schema_version": 1,
                    "active_owner": "central",
                    "project_heads": {},
                },
            )
        self._state = self._load_state()

    def _load_state(self) -> dict[str, Any]:
        state = _read_object(self.engine_state_path)
        if state.get("schema_version") != 1:
            raise KnowledgeOwnerError("project owner state has unsupported schema")
        owner = state.get("active_owner")
        heads = state.get("project_heads")
        if owner not in {"central", "project-local"} or not isinstance(heads, dict):
            raise KnowledgeOwnerError("project owner state is invalid")
        if owner == "central" and heads:
            raise KnowledgeOwnerError("central project owner state contains project heads")
        if owner == "project-local":
            self._validate_map(heads, inspect_heads=False)
        return copy.deepcopy(state)

    @property
    def active_owner(self) -> str:
        return str(self._state["active_owner"])

    @property
    def project_heads(self) -> dict[str, str]:
        return copy.deepcopy(dict(self._state["project_heads"]))

    def _head(self, project_id: str) -> str:
        result = subprocess.run(
            ["git", "-C", str(self.project_roots[project_id]), "rev-parse", "HEAD"],
            check=False,
            capture_output=True,
            text=True,
            env={**os.environ, "GIT_OPTIONAL_LOCKS": "0", "GIT_TERMINAL_PROMPT": "0"},
        )
        if result.returncode != 0:
            raise KnowledgeOwnerError(f"project head is unavailable: {project_id}")
        return result.stdout.strip()

    def _validate_map(self, heads: Mapping[str, Any], *, inspect_heads: bool) -> None:
        observed_keys = {str(key) for key in heads}
        expected_keys = set(self.project_roots)
        if observed_keys != expected_keys:
            raise KnowledgeOwnerError(
                "project map mismatch: "
                f"missing={sorted(expected_keys - observed_keys)}, "
                f"extra={sorted(observed_keys - expected_keys)}"
            )
        for project_id in sorted(expected_keys):
            expected = str(heads[project_id])
            if _HEAD.fullmatch(expected) is None:
                raise KnowledgeOwnerError(f"project head is invalid: {project_id}")
            if inspect_heads and self._head(project_id) != expected:
                raise KnowledgeOwnerError(f"project head mismatch: {project_id}")

    def activate(self, project_heads: Mapping[str, str]) -> dict[str, Any]:
        if not isinstance(project_heads, Mapping):
            raise KnowledgeOwnerError("project map is not an object")
        with self._lock:
            if not self.project_roots:
                raise KnowledgeOwnerError("project map is empty")
            self._validate_map(project_heads, inspect_heads=True)
            normalized = {
                project_id: str(project_heads[project_id])
                for project_id in sorted(self.project_roots)
            }
            state = {
                "schema_version": 1,
                "active_owner": "project-local",
                "project_heads": normalized,
                "activation_id": hashlib.sha256(_bytes(normalized)).hexdigest(),
            }
            previous = copy.deepcopy(self._state)
            try:
                _write_state(self.engine_state_path, state)
            except Exception:
                try:
                    _write_state(self.engine_state_path, previous)
                except Exception:
                    pass
                self._state = previous
                raise
            self._state = state
            return copy.deepcopy(state)

    @staticmethod
    def _stable_id(value: Any) -> str:
        stable_id = str(value or "")
        try:
            if str(uuid.UUID(stable_id)) != stable_id:
                raise ValueError
        except ValueError as exc:
            raise KnowledgeOwnerError(f"invalid project knowledge stable_id: {stable_id!r}") from exc
        return stable_id

    def _record_paths(self, project_id: str, stable_id: str) -> list[Path]:
        root = self.project_roots[project_id] / ".orchestra/kb/records"
        return sorted(path for path in root.glob(f"*/{stable_id}.json") if path.is_file())

    def _checked_record(self, project_id: str, path: Path) -> dict[str, Any]:
        record = _read_object(path)
        if record.get("project_id") != project_id or record.get("stable_id") != path.stem:
            raise KnowledgeOwnerError(f"project knowledge identity mismatch: {path}")
        return record

    def read_record(self, project_id: str, stable_id: str) -> dict[str, Any]:
        project_id = str(project_id)
        if project_id not in self.project_roots:
            raise KnowledgeOwnerError(f"project is not registered: {project_id}")
        stable_id = str(stable_id or "")
        if self.active_owner == "central":
            return copy.deepcopy(dict(self.central_reader(project_id, stable_id)))
        try:
            stable_id = self._stable_id(stable_id)
        except KnowledgeOwnerError:
            return copy.deepcopy(dict(self.central_reader(project_id, stable_id)))
        matches = self._record_paths(project_id, stable_id)
        if len(matches) > 1:
            raise KnowledgeOwnerError(f"project knowledge stable_id is ambiguous: {stable_id}")
        if matches:
            return self._checked_record(project_id, matches[0])
        if any(
            self._record_paths(other_project_id, stable_id)
            for other_project_id in self.project_roots
            if other_project_id != project_id
        ):
            raise KnowledgeOwnerError("cross-project knowledge read is forbidden")
        return copy.deepcopy(dict(self.central_reader(project_id, stable_id)))

    def _record_path(self, project_id: str, record: Mapping[str, Any]) -> Path:
        record_type = str(record.get("record_type") or "")
        namespace = (
            "facts"
            if record_type == "knowledge.fact" or record_type.startswith("fact")
            else "evidence"
        )
        root = self.project_roots[project_id]
        relative = Path(".orchestra/kb/records") / namespace / f"{record['stable_id']}.json"
        current = root
        for part in relative.parts[:-1]:
            current /= part
            if current.is_symlink():
                raise KnowledgeOwnerError(f"project knowledge parent is a symlink: {current}")
        path = root / relative
        try:
            path.resolve(strict=False).relative_to(root)
        except ValueError as exc:
            raise KnowledgeOwnerError("project knowledge path escapes project root") from exc
        return path

    def write_record(self, project_id: str, record: Mapping[str, Any]) -> dict[str, Any]:
        project_id = str(project_id)
        if self.active_owner != "project-local":
            raise KnowledgeOwnerError("project-local knowledge owner is not active")
        if project_id not in self.project_roots or not isinstance(record, Mapping):
            raise KnowledgeOwnerError(f"project is not registered: {project_id}")
        value = copy.deepcopy(dict(record))
        stable_id = self._stable_id(value.get("stable_id"))
        if value.get("project_id") != project_id:
            raise KnowledgeOwnerError("cross-project knowledge write is forbidden")
        value["stable_id"] = stable_id
        path = self._record_path(project_id, value)
        payload = _bytes(value)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            descriptor = os.open(
                temporary,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0),
                0o600,
            )
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary, path)
            except FileExistsError:
                if path.read_bytes() != payload:
                    raise KnowledgeOwnerError(f"project knowledge record conflicts: {path}")
            else:
                _fsync_directory(path.parent)
        finally:
            temporary.unlink(missing_ok=True)
        return copy.deepcopy(value)

    def query_records(self, project_id: str, text: str, limit: int) -> list[dict[str, Any]]:
        project_id = str(project_id)
        if self.active_owner != "project-local":
            raise KnowledgeOwnerError("project-local knowledge owner is not active")
        if project_id not in self.project_roots:
            raise KnowledgeOwnerError(f"project is not registered: {project_id}")
        if int(limit) <= 0:
            return []
        words = re.findall(r"\w+", str(text or "").casefold(), flags=re.UNICODE)
        root = self.project_roots[project_id]
        matches: list[dict[str, Any]] = []
        for path in sorted((root / ".orchestra/kb/records").glob("*/*.json")):
            record = self._checked_record(project_id, path)
            source_path = str(record.get("source_path") or "")
            source = root / source_path
            source_text = ""
            try:
                source.resolve(strict=False).relative_to(root)
                if source.is_file():
                    source_text = source.read_text(encoding="utf-8", errors="replace")
            except (OSError, ValueError):
                source_text = ""
            haystack = (json.dumps(record, ensure_ascii=False) + "\n" + source_text).casefold()
            if all(word in haystack for word in words):
                value = copy.deepcopy(record)
                if source_text:
                    value["content"] = source_text
                matches.append(value)
                if len(matches) >= int(limit):
                    break
        return matches


def project_knowledge_configured() -> bool:
    return _ACTIVE_ROUTER is not None


def active_project_knowledge() -> ProjectKnowledgeRouter:
    if _ACTIVE_ROUTER is None:
        raise KnowledgeOwnerError("project knowledge router is not configured")
    return _ACTIVE_ROUTER


@contextmanager
def project_knowledge_mode(router: ProjectKnowledgeRouter) -> Iterator[ProjectKnowledgeRouter]:
    global _ACTIVE_ROUTER
    with _ACTIVE_LOCK:
        if _ACTIVE_ROUTER is not None:
            raise KnowledgeOwnerError("project knowledge router is already configured")
        _ACTIVE_ROUTER = router
    try:
        yield router
    finally:
        with _ACTIVE_LOCK:
            _ACTIVE_ROUTER = None
