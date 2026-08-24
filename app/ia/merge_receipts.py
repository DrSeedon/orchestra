"""Content-bound, durable receipts for task-aware merge operations."""

from __future__ import annotations

import copy
import json
import re
import uuid
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class MergeReceiptError(RuntimeError):
    """Raised when a merge receipt is absent, forged, or cannot be made durable."""


_SHA40 = re.compile(r"[0-9a-f]{40}")
_SHA256 = re.compile(r"sha256:[0-9a-f]{64}")
_HEX256 = re.compile(r"[0-9a-f]{64}")
_EVIDENCE_URI = re.compile(
    r"orch://project/(?P<project>[a-z0-9][a-z0-9._-]*)/tasks/"
    r"(?P<task>[0-9a-f-]{36})/evidence/(?P<evidence>[0-9a-f-]{36})"
)


@dataclass(frozen=True)
class _ReceiptContext:
    canonical_root: Path
    task_resolver: Callable[[Mapping[str, Any]], Mapping[str, Any]]
    evidence_resolver: Callable[[Mapping[str, Any]], Mapping[str, Any]]
    head_resolver: Callable[[], Mapping[str, Any]]
    receipt_writer: Callable[[Path, Mapping[str, Any]], Any] | None


_ACTIVE_RECEIPTS: ContextVar[_ReceiptContext | None] = ContextVar(
    "ia_merge_receipts", default=None,
)


def _canonical_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise MergeReceiptError("merge receipt is not canonical JSON") from exc


def _detached(value: Any) -> Any:
    return json.loads(_canonical_bytes(value))


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MergeReceiptError(f"cannot read durable merge receipt: {path}") from exc
    if not isinstance(value, dict):
        raise MergeReceiptError("durable merge receipt is not an object")
    return value


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_bytes(_canonical_bytes(value) + b"\n")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _context() -> _ReceiptContext:
    context = _ACTIVE_RECEIPTS.get()
    if context is None:
        raise MergeReceiptError("merge receipt owner is not configured")
    return context


@contextmanager
def merge_receipt_mode(
    *,
    canonical_root: Path,
    task_resolver: Callable[[Mapping[str, Any]], Mapping[str, Any]],
    evidence_resolver: Callable[[Mapping[str, Any]], Mapping[str, Any]],
    head_resolver: Callable[[], Mapping[str, Any]],
    receipt_writer: Callable[[Path, Mapping[str, Any]], Any] | None = None,
) -> Iterator[None]:
    """Temporarily configure the canonical receipt owner and its resolvers."""

    context = _ReceiptContext(
        canonical_root=Path(canonical_root),
        task_resolver=task_resolver,
        evidence_resolver=evidence_resolver,
        head_resolver=head_resolver,
        receipt_writer=receipt_writer,
    )
    token = _ACTIVE_RECEIPTS.set(context)
    try:
        yield
    finally:
        _ACTIVE_RECEIPTS.reset(token)


def merge_receipt_configured() -> bool:
    """Return whether this execution context requires durable merge receipts."""

    return _ACTIVE_RECEIPTS.get() is not None


def _receipt_paths(operation_id: str) -> list[Path]:
    context = _ACTIVE_RECEIPTS.get()
    if context is None:
        return []
    return sorted(context.canonical_root.rglob(f"merge-receipts/{operation_id}.json"))


def get_merge_receipt(operation_id: str) -> dict[str, Any] | None:
    """Load the one durable receipt for an operation, if it exists."""

    paths = _receipt_paths(str(operation_id))
    if not paths:
        return None
    if len(paths) != 1:
        raise MergeReceiptError(
            f"operation '{operation_id}' has {len(paths)} durable merge receipts"
        )
    return verify_merge_receipt(_read_json(paths[0]), operation_id=str(operation_id))


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise MergeReceiptError(f"receipt {name} must be an object")
    return _detached(dict(value))


def _equal(actual: Any, expected: Any, name: str) -> None:
    if expected is not None and actual != expected:
        raise MergeReceiptError(f"receipt {name} does not match its pinned source")


def verify_merge_receipt(
    receipt: Mapping[str, Any],
    *,
    operation_id: str = "",
    target: Mapping[str, Any] | None = None,
    worker: Mapping[str, Any] | None = None,
    task: Mapping[str, Any] | None = None,
    evidence: Mapping[str, Any] | None = None,
    heads: Mapping[str, Any] | None = None,
    acceptance: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate a receipt and optional independently pinned bindings."""

    value = _mapping(receipt, "root")
    required = {
        "schema_version", "receipt_id", "receipt_status", "operation_id",
        "target", "worker", "task", "evidence", "heads", "acceptance",
        "created_at",
    }
    missing = sorted(required - value.keys())
    if missing:
        raise MergeReceiptError(f"merge receipt is incomplete: {', '.join(missing)}")
    if value["schema_version"] != 1 or value["receipt_status"] != "verified":
        raise MergeReceiptError("merge receipt is not a verified schema-v1 receipt")
    try:
        canonical_operation = str(uuid.UUID(str(value["operation_id"])))
        canonical_receipt = str(uuid.UUID(str(value["receipt_id"])))
    except (ValueError, AttributeError) as exc:
        raise MergeReceiptError("merge receipt identities must be canonical UUIDs") from exc
    if canonical_operation != value["operation_id"] or canonical_receipt != value["receipt_id"]:
        raise MergeReceiptError("merge receipt identities must be canonical UUIDs")
    if operation_id and canonical_operation != str(operation_id):
        raise MergeReceiptError("merge receipt belongs to another operation")

    target_value = _mapping(value["target"], "target")
    worker_value = _mapping(value["worker"], "worker")
    task_value = _mapping(value["task"], "task")
    evidence_value = _mapping(value["evidence"], "evidence")
    heads_value = _mapping(value["heads"], "heads")
    acceptance_value = _mapping(value["acceptance"], "acceptance")
    for name in ("before", "commit"):
        if _SHA40.fullmatch(str(target_value.get(name) or "")) is None:
            raise MergeReceiptError(f"receipt target.{name} is not a commit")
    if target_value["before"] == target_value["commit"]:
        raise MergeReceiptError("merge receipt does not describe a target commit")
    if _SHA40.fullmatch(str(worker_value.get("head") or "")) is None:
        raise MergeReceiptError("receipt worker.head is not a commit")

    try:
        stable_id = str(uuid.UUID(str(task_value["stable_id"])))
        display_number = int(task_value["display_number"])
        task_id = int(task_value["task_id"])
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise MergeReceiptError("receipt task identity is invalid") from exc
    if (
        stable_id != task_value["stable_id"]
        or task_value.get("display_ref") != f"#{display_number}"
    ):
        raise MergeReceiptError("receipt task stable/display identity is inconsistent")
    if task_id < 1 or display_number < 1 or not str(task_value.get("project_id") or ""):
        raise MergeReceiptError("receipt task identity is incomplete")

    uri = str(evidence_value.get("manifest_uri") or "")
    uri_match = _EVIDENCE_URI.fullmatch(uri)
    if (
        uri_match is None
        or uri_match.group("project") != task_value["project_id"]
        or uri_match.group("task") != stable_id
    ):
        raise MergeReceiptError("receipt evidence URI is not bound to the task")
    for name in ("manifest_head", "manifest_sha256"):
        if _SHA256.fullmatch(str(evidence_value.get(name) or "")) is None:
            raise MergeReceiptError(f"receipt evidence.{name} is invalid")
    if int(evidence_value.get("count") or 0) < 1:
        raise MergeReceiptError("receipt evidence manifest is empty")

    for name in ("canonical_head", "projection_head", "indexed_head"):
        if _SHA256.fullmatch(str(heads_value.get(name) or "")) is None:
            raise MergeReceiptError(f"receipt heads.{name} is invalid")
    if heads_value["projection_head"] != heads_value["canonical_head"]:
        raise MergeReceiptError("current projection is not bound to the canonical head")

    try:
        revision = int(acceptance_value["revision"])
        manifest_count = int(acceptance_value["manifest_count"])
    except (KeyError, TypeError, ValueError) as exc:
        raise MergeReceiptError("receipt acceptance identity is invalid") from exc
    if revision < 1 or manifest_count < 1:
        raise MergeReceiptError("receipt acceptance manifest is empty")
    if _HEX256.fullmatch(str(acceptance_value.get("oracle_hash") or "")) is None:
        raise MergeReceiptError("receipt acceptance oracle hash is invalid")
    if manifest_count != int(evidence_value["count"]):
        raise MergeReceiptError("receipt acceptance/evidence counts disagree")

    _equal(target_value, _detached(target) if target is not None else None, "target")
    _equal(worker_value, _detached(worker) if worker is not None else None, "worker")
    _equal(task_value, _detached(task) if task is not None else None, "task")
    _equal(evidence_value, _detached(evidence) if evidence is not None else None, "evidence")
    _equal(heads_value, _detached(heads) if heads is not None else None, "heads")
    _equal(
        acceptance_value,
        _detached(acceptance) if acceptance is not None else None,
        "acceptance",
    )
    return copy.deepcopy(value)


def _task_binding(finalization: Mapping[str, Any]) -> dict[str, Any]:
    task = _mapping(finalization.get("task"), "finalization task")
    try:
        return {
            "project_id": str(finalization.get("project_id") or task["project_id"]),
            "stable_id": str(task["stable_id"]),
            "task_id": int(task["task_id"]),
            "display_number": int(task["par_number"]),
            "display_ref": f"#{int(task['par_number'])}",
        }
    except (KeyError, TypeError, ValueError) as exc:
        raise MergeReceiptError("merge finalization lacks a stable task binding") from exc


def _canonical_evidence(evidence: Mapping[str, Any]) -> None:
    context = _context()
    expected = _detached(evidence)
    matches: list[dict[str, Any]] = []
    for path in sorted(context.canonical_root.rglob("*.json")):
        if "merge-receipts" in path.parts:
            continue
        try:
            candidate = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if (
            isinstance(candidate, dict)
            and candidate.get("manifest_uri") == expected["manifest_uri"]
        ):
            matches.append(candidate)
    if len(matches) != 1:
        raise MergeReceiptError(
            f"evidence manifest URI resolves to {len(matches)} canonical records"
        )
    for name, expected_value in expected.items():
        if matches[0].get(name) != expected_value:
            raise MergeReceiptError(f"canonical evidence {name} does not match resolver")


def _bindings(
    operation_id: str,
    merge_result: Mapping[str, Any],
    finalization: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    from app.merge_operations import get_operation_record

    record = get_operation_record(operation_id)
    if record is None:
        raise MergeReceiptError(f"merge operation '{operation_id}' is not durable")
    admission = _mapping(record.get("accepted_admission"), "accepted admission")
    admitted_target = _mapping(admission.get("target"), "admitted target")
    oracle = _mapping(admission.get("oracle"), "accepted oracle")
    if str(oracle.get("source") or "") != "task" or not oracle.get("required"):
        raise MergeReceiptError("verified receipts require an authoritative task oracle")

    task = _mapping(_context().task_resolver(finalization), "resolved task")
    expected_task = _task_binding(finalization)
    if task != expected_task:
        raise MergeReceiptError("resolved task does not match prepared merge finalization")
    if str(oracle.get("task_id") or "") != str(task["display_number"]):
        raise MergeReceiptError("accepted oracle is bound to another task")
    evidence = _mapping(_context().evidence_resolver(task), "resolved evidence")
    heads = _mapping(_context().head_resolver(), "resolved heads")
    _canonical_evidence(evidence)

    target_recheck = _mapping(merge_result.get("target_recheck"), "target recheck")
    target = {
        "branch": str(merge_result.get("target_branch") or ""),
        "before": str(merge_result.get("target_before") or ""),
        "commit": str(merge_result.get("target_after") or ""),
    }
    worker = {
        "branch": str(record.get("accepted_worker_branch") or ""),
        "head": str(record.get("accepted_worker_head") or ""),
    }
    acceptance = {
        "revision": int(oracle.get("revision") or 0),
        "oracle_hash": str(oracle.get("hash") or ""),
        "manifest_count": len(oracle.get("manifest") or []),
    }
    if not merge_result.get("ok") or merge_result.get("commit_point") != "target_committed":
        raise MergeReceiptError("target commit is not proven successful")
    if (
        target["branch"] != admitted_target.get("branch")
        or target["before"] != admitted_target.get("sha")
    ):
        raise MergeReceiptError("merge target differs from accepted target")
    if (
        target_recheck.get("matched") is not True
        or target_recheck.get("expected") != admitted_target.get("sha")
        or target_recheck.get("actual") != admitted_target.get("sha")
    ):
        raise MergeReceiptError("target admission was not reverified under the repository lock")
    if (
        str(merge_result.get("worker_branch") or "") != worker["branch"]
        or str(merge_result.get("worker_head") or "") != worker["head"]
        or str(finalization.get("worker_head") or "") != worker["head"]
    ):
        raise MergeReceiptError("merged worker head differs from the accepted head")
    if str(merge_result.get("head_drift") or "SAME") != "SAME":
        raise MergeReceiptError("accepted worker head drifted before the merge boundary")
    return {
        "target": target,
        "worker": worker,
        "task": task,
        "evidence": evidence,
        "heads": heads,
        "acceptance": acceptance,
    }


def record_merge_receipt(
    operation_id: str,
    merge_result: Mapping[str, Any],
    finalization: Mapping[str, Any],
) -> dict[str, Any]:
    """Create-or-read the verified receipt before any finalization or cleanup."""

    context = _context()
    bindings = _bindings(operation_id, merge_result, finalization)
    task = bindings["task"]
    path = (
        context.canonical_root
        / "projects" / task["project_id"]
        / "tasks" / task["stable_id"]
        / "merge-receipts" / f"{operation_id}.json"
    )
    if path.exists():
        return verify_merge_receipt(
            _read_json(path), operation_id=operation_id, **bindings,
        )
    receipt = {
        "schema_version": 1,
        "receipt_id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"orch:merge-receipt:{operation_id}")),
        "receipt_status": "verified",
        "operation_id": operation_id,
        **bindings,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    verified = verify_merge_receipt(receipt, operation_id=operation_id, **bindings)
    try:
        if context.receipt_writer is None:
            _write_json(path, verified)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            context.receipt_writer(path, copy.deepcopy(verified))
    except Exception as exc:
        raise MergeReceiptError(
            f"cannot persist merge receipt: {type(exc).__name__}: {exc}"
        ) from exc
    if not path.is_file():
        raise MergeReceiptError("receipt writer returned without a durable receipt")
    return verify_merge_receipt(
        _read_json(path), operation_id=operation_id, **bindings,
    )


def require_merge_receipt(
    operation_id: str,
    *,
    finalization: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Require the durable receipt before replaying task or lifecycle finalization."""

    receipt = get_merge_receipt(operation_id)
    if receipt is None:
        raise MergeReceiptError(f"merge operation '{operation_id}' has no durable receipt")
    if finalization is not None:
        expected_task = _task_binding(finalization)
        verify_merge_receipt(receipt, operation_id=operation_id, task=expected_task)
    return receipt
