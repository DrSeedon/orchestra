"""Byte-preserving, project-scoped knowledge distribution.

The module owns preparation and local Git commits only. It never pushes, fetches, pulls,
rewrites history, or deletes the central source.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Any, Mapping, Sequence


class DistributionError(RuntimeError):
    """Raised before accepting an ambiguous or lossy distribution."""


class PartialDistributionError(DistributionError):
    """Raised after at least one destination changed but the full pass did not finish."""

    def __init__(self, message: str, *, partial_result: Mapping[str, Any]) -> None:
        self.partial_result = copy.deepcopy(dict(partial_result))
        super().__init__(message)


_FORBIDDEN_GIT = {"push", "pull", "fetch", "remote", "reset", "rebase"}
_PROJECT_ID = re.compile(r"[a-z0-9][a-z0-9._-]*")
_ATTRIBUTES = (
    b"*.json -text -filter -working-tree-encoding\n"
    b"records/**/*.json -text -filter -working-tree-encoding\n"
)


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    ).encode("utf-8")


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DistributionError(f"cannot read JSON: {path}") from exc
    if not isinstance(value, dict):
        raise DistributionError(f"JSON owner is not an object: {path}")
    return value


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_bytes(_canonical_bytes(value) + b"\n")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _write_new_or_equal(path: Path, payload: bytes) -> None:
    """Create without clobbering; a concurrent identical writer is an idempotent success."""

    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags, 0o600)
    except FileExistsError:
        if path.is_symlink() or not path.is_file() or path.read_bytes() != payload:
            raise DistributionError(f"concurrent destination conflict: {path}")
        return
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    except Exception:
        path.unlink(missing_ok=True)
        raise


def _subcommand(args: Sequence[str]) -> str:
    index = 0
    while index < len(args) and str(args[index]).startswith("-"):
        index += 2 if args[index] in {"-C", "-c", "--git-dir", "--work-tree"} else 1
    return str(args[index]) if index < len(args) else ""


def _git(
    root: Path,
    *args: str,
    binary: bool = False,
    check: bool = True,
    commands: list[str] | None = None,
    timeout: float = 30.0,
    extra_env: Mapping[str, str] | None = None,
):
    command = _subcommand(args)
    if command in _FORBIDDEN_GIT:
        raise DistributionError(f"forbidden Git subcommand: {command}")
    if commands is not None and command:
        commands.append(command)
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_OPTIONAL_LOCKS"] = "0"
    env.setdefault("GIT_ASKPASS", "/bin/false")
    ssh_command = env.get("GIT_SSH_COMMAND", "ssh")
    env["GIT_SSH_COMMAND"] = (
        f"{ssh_command} -oBatchMode=yes -oStrictHostKeyChecking=yes -oConnectTimeout=10"
    )
    if extra_env:
        env.update({str(key): str(value) for key, value in extra_env.items()})
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *args],
            check=False,
            capture_output=True,
            text=not binary,
            timeout=timeout,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        raise DistributionError(f"git {command or args!r} timed out in {root}") from exc
    if check and result.returncode != 0:
        stderr = result.stderr if binary else result.stderr.strip()
        stdout = result.stdout if binary else result.stdout.strip()
        detail = stderr or stdout or f"exit {result.returncode}"
        if isinstance(detail, bytes):
            detail = detail.decode("utf-8", errors="replace")
        raise DistributionError(f"git {command or args!r} failed in {root}: {detail}")
    return result.stdout


def _exact_repo(root: Path, *, commands: list[str]) -> Path:
    resolved = root.expanduser().resolve()
    if not resolved.is_dir():
        raise DistributionError(f"repository is missing: {resolved}")
    top = Path(str(_git(resolved, "rev-parse", "--show-toplevel", commands=commands)).strip())
    if top.resolve() != resolved:
        raise DistributionError(f"repository root is not exact: {resolved} -> {top}")
    return resolved


def _status(root: Path, *, commands: list[str]) -> str:
    return str(_git(root, "status", "--porcelain", commands=commands)).strip()


def _status_bytes(
    root: Path, pathspec: Sequence[str], *, commands: list[str]
) -> bytes:
    return _git(
        root,
        "status",
        "--porcelain=v1",
        "-z",
        "--untracked-files=all",
        "--",
        *pathspec,
        binary=True,
        commands=commands,
    )


def _dirty_paths(status: bytes) -> list[str]:
    tokens = [item for item in status.split(b"\0") if item]
    result = []
    position = 0
    while position < len(tokens):
        item = tokens[position]
        code = item[:2]
        result.append(os.fsdecode(item[3:]))
        position += 1
        if b"R" in code or b"C" in code:
            result.append(os.fsdecode(tokens[position]))
            position += 1
    return result


def _foreign_snapshot(
    root: Path, allowed_prefixes: Sequence[str], *, commands: list[str]
) -> dict[str, Any]:
    pathspec = [".", *(f":(exclude){prefix}**" for prefix in allowed_prefixes)]
    status = _status_bytes(root, pathspec, commands=commands)
    index = _git(
        root,
        "ls-files",
        "--stage",
        "-z",
        "--",
        *pathspec,
        binary=True,
        commands=commands,
    )
    paths = sorted(set(_dirty_paths(status)))
    content = hashlib.sha256()
    for relative in paths:
        path = root / relative
        content.update(os.fsencode(relative))
        content.update(b"\0")
        if path.is_symlink():
            content.update(b"symlink\0" + os.fsencode(os.readlink(path)))
        elif path.is_file():
            content.update(b"file\0" + hashlib.sha256(path.read_bytes()).digest())
        elif path.exists():
            content.update(b"other\0")
        else:
            content.update(b"missing\0")
        content.update(b"\0")
    return {
        "dirty_count": len(paths),
        "status_sha256": hashlib.sha256(status).hexdigest(),
        "index_sha256": hashlib.sha256(index).hexdigest(),
        "dirty_content_sha256": content.hexdigest(),
    }


def _is_ignored(root: Path, relative: str, *, commands: list[str]) -> bool:
    commands.append("check-ignore")
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_OPTIONAL_LOCKS"] = "0"
    result = subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "check-ignore",
            "-q",
            "--no-index",
            "--",
            relative,
        ],
        check=False,
        capture_output=True,
        timeout=30.0,
        env=env,
    )
    if result.returncode not in {0, 1}:
        raise DistributionError(f"git check-ignore failed in {root}: exit {result.returncode}")
    return result.returncode == 0


def _head(root: Path, *, commands: list[str]) -> str:
    return str(_git(root, "rev-parse", "HEAD", commands=commands)).strip()


def _refs(root: Path, *, commands: list[str]) -> dict[str, str]:
    raw = str(_git(root, "show-ref", "--head", check=False, commands=commands))
    result = {}
    for line in raw.splitlines():
        oid, separator, name = line.partition(" ")
        if separator and name != "HEAD":
            result[name] = oid
    return dict(sorted(result.items()))


def _config_sha(root: Path, *, commands: list[str]) -> str:
    raw = _git(root, "config", "--local", "--list", "-z", binary=True, commands=commands)
    return hashlib.sha256(raw).hexdigest()


def _index_sha(root: Path, *, commands: list[str]) -> str:
    path = Path(
        str(
            _git(
                root,
                "rev-parse",
                "--path-format=absolute",
                "--git-path",
                "index",
                commands=commands,
            )
        ).strip()
    )
    return hashlib.sha256(path.read_bytes() if path.is_file() else b"").hexdigest()


def _remote_refs(root: Path, *, commands: list[str]) -> dict[str, list[str]]:
    configured = str(
        _git(
            root,
            "config",
            "--local",
            "--get-regexp",
            r"^remote\..*\.url$",
            check=False,
            commands=commands,
        )
    ).splitlines()
    names = {
        line.split(maxsplit=1)[0].removeprefix("remote.").removesuffix(".url")
        for line in configured
        if line.strip()
    }
    result = {}
    for name in sorted(item for item in names if item):
        # ls-remote is read-only. It does not change refs, config, the index, or the worktree.
        raw = str(
            _git(
                root,
                "ls-remote",
                "--refs",
                name,
                commands=commands,
                timeout=30.0,
            )
        )
        result[name] = sorted(line for line in raw.splitlines() if line)
    return result


def _records_sha(records: Sequence[Mapping[str, Any]]) -> str:
    digest = hashlib.sha256()
    for item in sorted(records, key=lambda value: str(value["stable_id"])):
        digest.update(str(item["stable_id"]).encode())
        digest.update(b"\0")
        digest.update(bytes(item["payload"]))
        digest.update(b"\0")
    return "sha256:" + digest.hexdigest()


def _source_records(
    canonical_root: Path,
    source_head: str,
    *,
    commands: list[str],
) -> dict[str, list[dict[str, Any]]]:
    raw = _git(
        canonical_root,
        "ls-tree",
        "-r",
        "-z",
        "--name-only",
        source_head,
        "--",
        "evidence",
        binary=True,
        commands=commands,
    )
    by_project: dict[str, list[dict[str, Any]]] = {}
    for encoded in raw.split(b"\0"):
        if not encoded:
            continue
        path = encoded.decode("utf-8")
        parts = Path(path).parts
        if len(parts) != 3 or parts[0] != "evidence" or Path(path).suffix != ".json":
            raise DistributionError(f"unexpected central evidence path: {path}")
        project_id, stable_id = parts[1], Path(parts[2]).stem
        if _PROJECT_ID.fullmatch(project_id) is None:
            raise DistributionError(f"invalid project id in evidence path: {path}")
        try:
            if str(uuid.UUID(stable_id)) != stable_id:
                raise ValueError
        except ValueError as exc:
            raise DistributionError(f"invalid stable_id filename: {path}") from exc
        payload = _git(
            canonical_root,
            "show",
            f"{source_head}:{path}",
            binary=True,
            commands=commands,
        )
        try:
            record = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise DistributionError(f"central evidence is not JSON: {path}") from exc
        if not isinstance(record, dict):
            raise DistributionError(f"central evidence is not an object: {path}")
        if record.get("project_id") != project_id or record.get("stable_id") != stable_id:
            raise DistributionError(f"central evidence identity mismatch: {path}")
        by_project.setdefault(project_id, []).append(
            {
                "project_id": project_id,
                "stable_id": stable_id,
                "source_relative_path": path,
                "payload": payload,
                "size": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        )
    for values in by_project.values():
        values.sort(key=lambda item: item["stable_id"])
    return by_project


def _registry(path: Path) -> tuple[dict[str, Path], bytes]:
    raw = path.read_bytes()
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise DistributionError(f"scope registry is not JSON: {path}") from exc
    entries = value.get("entries") if isinstance(value, dict) else None
    if not isinstance(entries, list):
        raise DistributionError("scope registry entries are missing")
    result = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise DistributionError("scope registry entry is not an object")
        project_id = str(entry.get("canonical_project_id") or "")
        repository = str(entry.get("repository_root") or "")
        if not project_id or not repository or project_id in result:
            raise DistributionError(f"invalid scope registry identity: {project_id!r}")
        result[project_id] = Path(repository)
    return result, raw


def _owner(
    project_id: str,
    registry: Mapping[str, Path],
    quarantine_root: Path,
    *,
    commands: list[str],
) -> dict[str, Any]:
    if project_id in registry:
        git_root = _exact_repo(Path(registry[project_id]), commands=commands)
        return {
            "project_root": git_root,
            "git_root": git_root,
            "manifest_relative_path": "docs/kb/manifest.json",
            "quarantined": False,
        }
    git_root = _exact_repo(quarantine_root, commands=commands)
    project_root = git_root / project_id
    if project_root.is_symlink():
        raise DistributionError(f"quarantine project root is a symlink: {project_root}")
    try:
        project_root.resolve(strict=False).relative_to(git_root.resolve())
    except ValueError as exc:
        raise DistributionError(f"quarantine project root escapes: {project_root}") from exc
    return {
        "project_root": project_root,
        "git_root": git_root,
        "manifest_relative_path": f"{project_id}/docs/kb/manifest.json",
        "quarantined": True,
        "quarantine_reason": "project_unmapped",
    }


def _safe_path(root: Path, relative: str, *, label: str) -> Path:
    candidate = root / relative
    current = root
    for part in Path(relative).parts[:-1]:
        current = current / part
        if current.is_symlink():
            raise DistributionError(f"{label} parent is a symlink: {current}")
    try:
        candidate.resolve(strict=False).relative_to(root.resolve())
    except ValueError as exc:
        raise DistributionError(f"{label} escapes project root: {candidate}") from exc
    return candidate


def _destination_row(owner: Mapping[str, Any], record: Mapping[str, Any]) -> dict[str, Any]:
    relative = f"docs/kb/records/evidence/{record['stable_id']}.json"
    project_root = Path(owner["project_root"])
    _safe_path(project_root, relative, label="record destination")
    return {
        "stable_id": record["stable_id"],
        "source_relative_path": record["source_relative_path"],
        "destination_relative_path": relative,
        "size": record["size"],
        "sha256": record["sha256"],
    }


def _project_plan(
    project_id: str,
    records: Sequence[Mapping[str, Any]],
    owner: Mapping[str, Any],
    source_head: str,
    *,
    commands: list[str],
    probe_remotes: bool,
    allow_materialized_target: bool,
) -> dict[str, Any]:
    git_root = Path(owner["git_root"])
    before_head = _head(git_root, commands=commands)
    rows = [_destination_row(owner, record) for record in records]
    manifest = {
        "schema_version": 1,
        "project_id": project_id,
        "source_head": source_head,
        "record_count": len(rows),
        "records_sha256": _records_sha(records),
        "records": rows,
    }
    existing = Path(owner["project_root"]) / "docs/kb/records/evidence"
    if existing.exists():
        present = {path.stem for path in existing.glob("*.json")}
        wanted = {str(row["stable_id"]) for row in rows}
        if present - wanted:
            raise DistributionError(f"destination has unowned evidence records: {project_id}")
    for source, row in zip(records, rows, strict=True):
        destination = Path(owner["project_root"]) / row["destination_relative_path"]
        if destination.exists() and destination.read_bytes() != source["payload"]:
            raise DistributionError(f"destination record conflicts: {destination}")
    manifest_path = _safe_path(
        git_root,
        str(owner["manifest_relative_path"]),
        label="manifest destination",
    )
    encoded_manifest = _canonical_bytes(manifest) + b"\n"
    if manifest_path.exists() and manifest_path.read_bytes() != encoded_manifest:
        raise DistributionError(f"destination manifest conflicts: {manifest_path}")
    attributes_relative = str(Path(owner["manifest_relative_path"]).parent / ".gitattributes")
    allowed_prefix = Path(owner["manifest_relative_path"]).parent.as_posix() + "/"
    attributes_path = _safe_path(
        git_root,
        attributes_relative,
        label="attributes destination",
    )
    if attributes_path.exists() and attributes_path.read_bytes() != _ATTRIBUTES:
        raise DistributionError(f"destination attributes conflict: {attributes_path}")
    target_status = _status_bytes(git_root, [allowed_prefix], commands=commands)
    if target_status:
        expected_paths = {attributes_relative, str(owner["manifest_relative_path"])}
        for row in rows:
            expected_paths.add(
                (
                    Path(owner["project_root"]) / row["destination_relative_path"]
                ).resolve().relative_to(git_root.resolve()).as_posix()
            )
        unexpected = sorted(set(_dirty_paths(target_status)) - expected_paths)
        if not allow_materialized_target or unexpected:
            suffix = f": {', '.join(unexpected[:3])}" if unexpected else ""
            raise DistributionError(
                f"destination docs/kb has non-materialized dirty paths: {git_root}{suffix}"
            )
    foreign_snapshot = _foreign_snapshot(
        git_root, [allowed_prefix], commands=commands
    )
    target_ref = str(_git(git_root, "symbolic-ref", "-q", "HEAD", commands=commands)).strip()
    return {
        "project_id": project_id,
        "repository_root": str(Path(owner["project_root"]).resolve()),
        "git_root": str(git_root),
        "manifest_relative_path": owner["manifest_relative_path"],
        "record_count": len(rows),
        "records_sha256": manifest["records_sha256"],
        "manifest": manifest,
        "attributes_relative_path": attributes_relative,
        "allowed_prefix": allowed_prefix,
        "target_status_sha256_before": hashlib.sha256(target_status).hexdigest(),
        "records": [copy.deepcopy(dict(record)) for record in records],
        "before_head": before_head,
        "target_ref": target_ref,
        "local_refs_before": _refs(git_root, commands=commands),
        "remote_refs_before": (
            _remote_refs(git_root, commands=commands) if probe_remotes else {}
        ),
        "local_config_sha256_before": _config_sha(git_root, commands=commands),
        "index_sha256_before": _index_sha(git_root, commands=commands),
        "foreign_snapshot_before": foreign_snapshot,
        "force_add": _is_ignored(
            git_root,
            str(owner["manifest_relative_path"]),
            commands=commands,
        ),
        "quarantined": bool(owner.get("quarantined")),
        "quarantine_reason": owner.get("quarantine_reason"),
    }


def _materialize_group(
    plans: Sequence[dict[str, Any]], *, commit: bool, commands: list[str]
) -> None:
    from app.workspace import repo_mutation_lock

    if not plans:
        return
    git_root = Path(plans[0]["git_root"])
    if any(Path(plan["git_root"]) != git_root for plan in plans):
        raise DistributionError("materialize group spans multiple Git roots")
    before_heads = {plan["before_head"] for plan in plans}
    target_refs = {plan["target_ref"] for plan in plans}
    if len(before_heads) != 1 or len(target_refs) != 1:
        raise DistributionError(f"shared Git root has inconsistent snapshots: {git_root}")
    before_head = next(iter(before_heads))
    target_ref = next(iter(target_refs))
    with repo_mutation_lock(git_root):
        current_ref = str(
            _git(git_root, "symbolic-ref", "-q", "HEAD", commands=commands)
        ).strip()
        if current_ref != target_ref:
            raise DistributionError(f"destination ref drift: {git_root}")
        if _head(git_root, commands=commands) != before_head:
            raise DistributionError(f"destination HEAD drift: {git_root}")
        allowed_prefixes = sorted({str(plan["allowed_prefix"]) for plan in plans})
        target_status = _status_bytes(git_root, allowed_prefixes, commands=commands)
        if hashlib.sha256(target_status).hexdigest() != plans[0][
            "target_status_sha256_before"
        ]:
            raise DistributionError(
                f"concurrent destination docs/kb change after planning: {git_root}"
            )
        if _foreign_snapshot(
            git_root, allowed_prefixes, commands=commands
        ) != plans[0]["foreign_snapshot_before"]:
            raise DistributionError(f"foreign worktree/index changed after planning: {git_root}")
        written_paths: list[Path] = []
        for plan in plans:
            project_root = Path(plan["repository_root"])
            attributes_path = _safe_path(
                git_root,
                plan["attributes_relative_path"],
                label="attributes destination",
            )
            _write_new_or_equal(attributes_path, _ATTRIBUTES)
            written_paths.append(attributes_path)
            for record, row in zip(
                plan["records"], plan["manifest"]["records"], strict=True
            ):
                destination = _safe_path(
                    project_root,
                    row["destination_relative_path"],
                    label="record destination",
                )
                _write_new_or_equal(destination, bytes(record["payload"]))
                written_paths.append(destination)
            manifest_path = _safe_path(
                git_root,
                plan["manifest_relative_path"],
                label="manifest destination",
            )
            _write_new_or_equal(
                manifest_path,
                _canonical_bytes(plan["manifest"]) + b"\n",
            )
            written_paths.append(manifest_path)
        if not commit:
            return
        descriptor, temporary_name = tempfile.mkstemp(prefix="orchestra-412-index-")
        os.close(descriptor)
        os.unlink(temporary_name)
        index_env = {"GIT_INDEX_FILE": temporary_name}
        staged: list[tuple[str, str]] = []
        try:
            _git(
                git_root,
                "read-tree",
                before_head,
                commands=commands,
                extra_env=index_env,
            )
            add_args = ["add", "-N"]
            if any(bool(plan["force_add"]) for plan in plans):
                add_args.append("-f")
            _git(
                git_root,
                *add_args,
                "--",
                *allowed_prefixes,
                commands=commands,
                extra_env=index_env,
            )
            for path in written_paths:
                relative = path.resolve().relative_to(git_root.resolve()).as_posix()
                oid = str(
                    _git(
                        git_root,
                        "hash-object",
                        "-w",
                        "--no-filters",
                        "--",
                        relative,
                        commands=commands,
                    )
                ).strip()
                _git(
                    git_root,
                    "update-index",
                    "--add",
                    "--cacheinfo",
                    f"100644,{oid},{relative}",
                    commands=commands,
                    extra_env=index_env,
                )
                staged.append((relative, oid))
            raw_changed = _git(
                git_root,
                "diff",
                "--cached",
                "--name-only",
                "-z",
                "--",
                *allowed_prefixes,
                binary=True,
                commands=commands,
                extra_env=index_env,
            )
            changed = [item.decode("utf-8") for item in raw_changed.split(b"\0") if item]
            if changed:
                if any(
                    not any(path.startswith(prefix) for prefix in allowed_prefixes)
                    for path in changed
                ):
                    raise DistributionError(f"staged path escapes docs/kb: {git_root}")
                _git(
                    git_root,
                    "-c",
                    "core.hooksPath=/dev/null",
                    "commit",
                    "-qm",
                    "#412: distribute project knowledge evidence",
                    commands=commands,
                    extra_env=index_env,
                )
        finally:
            Path(temporary_name).unlink(missing_ok=True)
        # Bring only our target entries into the real index. Pre-existing staged foreign
        # entries were never loaded into the temporary index and remain byte-identical.
        for relative, oid in staged:
            _git(
                git_root,
                "update-index",
                "--add",
                "--cacheinfo",
                f"100644,{oid},{relative}",
                commands=commands,
            )
        committed_head = _head(git_root, commands=commands)
        for plan in plans:
            project_root = Path(plan["repository_root"])
            for record, row in zip(
                plan["records"], plan["manifest"]["records"], strict=True
            ):
                relative = (
                    project_root / row["destination_relative_path"]
                ).resolve().relative_to(git_root.resolve()).as_posix()
                observed = _git(
                    git_root,
                    "show",
                    f"{committed_head}:{relative}",
                    binary=True,
                    commands=commands,
                )
                if observed != record["payload"]:
                    raise DistributionError(f"committed byte parity failed: {relative}")
            manifest_relative = str(plan["manifest_relative_path"])
            observed_manifest = _git(
                git_root,
                "show",
                f"{committed_head}:{manifest_relative}",
                binary=True,
                commands=commands,
            )
            if observed_manifest != _canonical_bytes(plan["manifest"]) + b"\n":
                raise DistributionError(
                    f"committed manifest byte parity failed: {manifest_relative}"
                )
        if any(
            _status_bytes(git_root, [prefix], commands=commands)
            for prefix in allowed_prefixes
        ):
            raise DistributionError(f"destination docs/kb is dirty after commit: {git_root}")
        if _foreign_snapshot(
            git_root, allowed_prefixes, commands=commands
        ) != plans[0]["foreign_snapshot_before"]:
            raise DistributionError(f"foreign worktree/index changed during commit: {git_root}")


def _materialize(plan: dict[str, Any], *, commit: bool, commands: list[str]) -> None:
    _materialize_group([plan], commit=commit, commands=commands)


def _verify_materialized_project(project: Mapping[str, Any]) -> None:
    project_root = Path(str(project["repository_root"]))
    for record, row in zip(
        project["records"], project["manifest"]["records"], strict=True
    ):
        destination = project_root / str(row["destination_relative_path"])
        if not destination.is_file() or destination.read_bytes() != record["payload"]:
            raise DistributionError(
                f"external owner commit changed distributed bytes: {destination}"
            )
    manifest = project_root / str(project["manifest_relative_path"])
    if (
        not manifest.is_file()
        or manifest.read_bytes() != _canonical_bytes(project["manifest"]) + b"\n"
    ):
        raise DistributionError(
            f"external owner commit changed distributed manifest: {manifest}"
        )


def _public_project(
    project: Mapping[str, Any], *, commands: list[str], probe_remotes: bool
) -> dict[str, Any]:
    git_root = Path(str(project["git_root"]))
    target_commit = _head(git_root, commands=commands)
    target_prefixes = [str(value) for value in project.get(
        "group_allowed_prefixes", [project["allowed_prefix"]]
    )]
    target_status = _status_bytes(git_root, target_prefixes, commands=commands)
    external_owner_commit = bool(
        target_commit != project["before_head"]
        and not project.get("commit_requested", False)
    )
    if external_owner_commit:
        _verify_materialized_project(project)
    result = {
        key: copy.deepcopy(value)
        for key, value in project.items()
        if key not in {"manifest", "records", "git_root"}
    }
    result.update(
        target_commit=target_commit,
        local_refs_after=_refs(git_root, commands=commands),
        remote_refs_after=(
            _remote_refs(git_root, commands=commands) if probe_remotes else {}
        ),
        local_config_sha256_after=_config_sha(git_root, commands=commands),
        index_sha256_after=_index_sha(git_root, commands=commands),
        foreign_snapshot_after=_foreign_snapshot(
            git_root,
            target_prefixes,
            commands=commands,
        ),
        target_status_sha256_after=hashlib.sha256(target_status).hexdigest(),
        target_dirty_paths_after=sorted(set(_dirty_paths(target_status))),
        external_owner_commit=external_owner_commit,
        git_subcommands=sorted(set(commands)),
    )
    before_refs = dict(project["local_refs_before"])
    after_refs = dict(result["local_refs_after"])
    changed_refs = {
        name for name in set(before_refs) | set(after_refs)
        if before_refs.get(name) != after_refs.get(name)
    }
    if target_commit == project["before_head"]:
        if changed_refs:
            raise DistributionError(f"unexpected local refs changed: {git_root}")
    else:
        if changed_refs != {project["target_ref"]}:
            raise DistributionError(f"unexpected local refs changed: {git_root}")
        if (
            before_refs.get(project["target_ref"]) != project["before_head"]
            or after_refs.get(project["target_ref"]) != target_commit
        ):
            raise DistributionError(f"target ref transition mismatch: {git_root}")
    if result["local_config_sha256_after"] != project["local_config_sha256_before"]:
        raise DistributionError(f"local config changed during distribution: {git_root}")
    if (
        target_commit == project["before_head"]
        and result["index_sha256_after"] != project["index_sha256_before"]
    ):
        raise DistributionError(f"Git index changed during uncommitted distribution: {git_root}")
    if result["foreign_snapshot_after"] != project["foreign_snapshot_before"]:
        raise DistributionError(f"foreign worktree/index changed during distribution: {git_root}")
    if (
        probe_remotes
        and result["remote_refs_after"] != project["remote_refs_before"]
        and not external_owner_commit
    ):
        raise DistributionError(f"remote refs changed during distribution: {git_root}")
    return result


def distribute_project_knowledge(
    *,
    canonical_root: Path,
    scope_registry_path: Path,
    quarantine_root: Path,
    expected_source_head: str,
    apply: bool,
    commit: bool,
    probe_remotes: bool = False,
    allow_materialized_target: bool = False,
    expected_scope_registry_sha256: str = "",
) -> dict[str, Any]:
    """Prepare or apply one frozen distribution without touching central bytes."""

    commands: list[str] = []
    canonical_root = _exact_repo(Path(canonical_root), commands=commands)
    source_head = _head(canonical_root, commands=commands)
    if source_head != expected_source_head:
        raise DistributionError(
            f"central HEAD drift: expected {expected_source_head}, found {source_head}"
        )
    if _status(canonical_root, commands=commands):
        raise DistributionError("central repository is dirty")
    registry_path = Path(scope_registry_path)
    registry, registry_bytes = _registry(registry_path)
    registry_sha256 = hashlib.sha256(registry_bytes).hexdigest()
    if (
        expected_scope_registry_sha256
        and registry_sha256 != expected_scope_registry_sha256
    ):
        raise DistributionError(
            "scope registry drift: "
            f"expected {expected_scope_registry_sha256}, found {registry_sha256}"
        )
    source = _source_records(canonical_root, source_head, commands=commands)
    project_ids = sorted(set(registry) | set(source))
    plans = []
    for project_id in project_ids:
        owner = _owner(
            project_id,
            registry,
            Path(quarantine_root),
            commands=commands,
        )
        plans.append(
            _project_plan(
                project_id,
                source.get(project_id, []),
                owner,
                source_head,
                commands=commands,
                probe_remotes=probe_remotes,
                allow_materialized_target=bool(apply or allow_materialized_target),
            )
        )
    groups: dict[str, list[dict[str, Any]]] = {}
    for plan in plans:
        groups.setdefault(str(plan["git_root"]), []).append(plan)
    for group in groups.values():
        prefixes = sorted({str(plan["allowed_prefix"]) for plan in group})
        target_status_sha256 = hashlib.sha256(
            _status_bytes(
                Path(group[0]["git_root"]), prefixes, commands=commands
            )
        ).hexdigest()
        snapshot = _foreign_snapshot(
            Path(group[0]["git_root"]), prefixes, commands=commands
        )
        for plan in group:
            plan["group_allowed_prefixes"] = prefixes
            plan["commit_requested"] = bool(apply and commit)
            plan["target_status_sha256_before"] = target_status_sha256
            plan["foreign_snapshot_before"] = snapshot

    committed_projects: list[str] = []
    if apply:
        if registry_path.read_bytes() != registry_bytes:
            raise DistributionError("scope registry drift before first write")
        if _head(canonical_root, commands=commands) != source_head or _status(
            canonical_root, commands=commands
        ):
            raise DistributionError("central repository drift before first write")
        for group in groups.values():
            try:
                _materialize_group(group, commit=commit, commands=commands)
                if commit and _head(
                    Path(group[0]["git_root"]), commands=commands
                ) != group[0]["before_head"]:
                    committed_projects.extend(plan["project_id"] for plan in group)
            except Exception as exc:
                partial = {
                    "schema_version": 1,
                    "status": "partial",
                    "source_head": source_head,
                    "committed_projects": committed_projects,
                    "failed_project": ",".join(plan["project_id"] for plan in group),
                    "error": f"{type(exc).__name__}: {exc}",
                }
                raise PartialDistributionError(
                    f"distribution stopped after {len(committed_projects)} committed project(s): "
                    f"{type(exc).__name__}: {exc}",
                    partial_result=partial,
                ) from exc
    try:
        projects = [
            _public_project(plan, commands=commands, probe_remotes=probe_remotes)
            for plan in plans
        ]
    except Exception as exc:
        if not apply:
            raise
        partial = {
            "schema_version": 1,
            "status": "partial",
            "source_head": source_head,
            "committed_projects": committed_projects,
            "failed_project": "post-apply-snapshot",
            "error": f"{type(exc).__name__}: {exc}",
        }
        raise PartialDistributionError(
            f"post-apply snapshot failed after {len(committed_projects)} committed project(s): "
            f"{type(exc).__name__}: {exc}",
            partial_result=partial,
        ) from exc
    records = []
    for plan in plans:
        for source_record, row in zip(plan["records"], plan["manifest"]["records"], strict=True):
            records.append(
                {
                    **copy.deepcopy(row),
                    "project_id": plan["project_id"],
                    "destination_repo": plan["repository_root"],
                    "payload": source_record["payload"],
                }
            )
    return {
        "schema_version": 1,
        "mode": "apply" if apply else "dry-run",
        "status": "prepared" if apply else "planned",
        "source_state_root": str(canonical_root.parent),
        "source_head": source_head,
        "scope_registry_sha256": registry_sha256,
        "total_record_count": len(records),
        "quarantine_count": sum(
            project["record_count"] for project in projects if project["quarantined"]
        ),
        "projects": projects,
        "records": records,
        "git_subcommands": sorted(set(commands)),
    }


def verify_project_knowledge_distribution(
    *,
    canonical_root: Path,
    scope_registry_path: Path,
    quarantine_root: Path,
    expected_source_head: str,
    probe_remotes: bool = False,
    expected_scope_registry_sha256: str = "",
) -> dict[str, Any]:
    """Re-read source and destinations; never repair or create anything."""

    result = distribute_project_knowledge(
        canonical_root=canonical_root,
        scope_registry_path=scope_registry_path,
        quarantine_root=quarantine_root,
        expected_source_head=expected_source_head,
        apply=False,
        commit=False,
        probe_remotes=probe_remotes,
        allow_materialized_target=True,
        expected_scope_registry_sha256=expected_scope_registry_sha256,
    )
    for record in result["records"]:
        destination = (
            Path(str(record["destination_repo"]))
            / str(record["destination_relative_path"])
        )
        if not destination.is_file():
            raise DistributionError(f"destination record is missing: {destination}")
        payload = destination.read_bytes()
        if len(payload) != record["size"] or hashlib.sha256(payload).hexdigest() != record["sha256"]:
            raise DistributionError(f"destination record parity failed: {destination}")
    for project in result["projects"]:
        manifest_path = (
            Path(str(project["repository_root"])) / "docs/kb/manifest.json"
        )
        if not manifest_path.is_file():
            raise DistributionError(f"destination manifest is missing: {manifest_path}")
        observed = _read_json(manifest_path)
        if (
            observed.get("record_count") != project["record_count"]
            or observed.get("records_sha256") != project["records_sha256"]
        ):
            raise DistributionError(f"destination manifest parity failed: {manifest_path}")
    result["mode"] = "verify"
    result["status"] = "verified"
    return result


def global_receipt(result: Mapping[str, Any], *, run_id: str = "") -> dict[str, Any]:
    """Drop record-level detail before persisting the engine migration receipt."""

    return {
        key: copy.deepcopy(value)
        for key, value in result.items()
        if key not in {"records"}
    } | {"run_id": run_id or str(uuid.uuid4())}
