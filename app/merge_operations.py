"""Durable, idempotent merge operations above the pinned session merge entry point."""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import logging
import sqlite3
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.db import _conn, get_session, get_session_by_name
from app.errtext import err_text

logger = logging.getLogger("orchestra.merge_operations")

ACTIVE_STATES = ("PENDING", "RUNNING", "PARTIAL", "UNKNOWN")
TERMINAL_STATES = ("SUCCEEDED", "PARTIAL", "FAILED", "UNKNOWN")

# Стадии, чей провал НЕ разводит git и БД сессий: индекс поиска и подготовка следующей
# задачи. Когда коммит в target уже состоялся, а провалились только они, операция
# терминальна — иначе вторичный шаг навсегда блокирует мержи воркера.
# `TASK_LINK_PARTIAL` здесь нет намеренно: «номера не существует» до стадийных провалов
# не доходит вовсе (см. `_link_status`), а недоступная БД задач обязана оставаться
# провалом. Спорить про границу — здесь, в одном месте, а не в трёх ветках `if`.
SECONDARY_STAGES = ("RAG_NOT_READY", "RAG_STATUS_INVALID", "NEXT_TASK_FAILED")
_runner_tasks: dict[str, asyncio.Task[None]] = {}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash(value: Any) -> str:
    return hashlib.sha256(_json(value).encode()).hexdigest()


def _text(value: Any, fallback: str) -> str:
    text = str(value or "").strip()
    return text or fallback


def _error(
    code: str,
    message: Any,
    *,
    operation_id: str,
    status: int | None = None,
    retryable: bool = False,
    outcome_unknown: bool = False,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "code": code or "SERVER_ERROR",
        "message": _text(message, code or "merge operation failed"),
        "status": status,
        "retryable": bool(retryable) and not outcome_unknown,
        "request_id": operation_id or None,
        "retry_after_seconds": None,
        "outcome_unknown": outcome_unknown,
        "details": details or {},
    }


def _action(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": _text(message, code)}


# Инструкция без разрешённого действия не выполняется: чужой оркестратор смержил руками
# не по недисциплинированности, а потому что «do not merge manually» не называло выхода.
_RESOLVE_HINT = (
    "When the outcome is reconciled, close it with resolve_merge_operation("
    "operation_id='{operation_id}', reason=...) — that is the only way to unblock "
    "new merges for this worker."
)


def _blocking_action(code: str, message: str, operation_id: str) -> dict[str, str]:
    """next_action у блокирующего состояния обязан НАЗЫВАТЬ разрешённое действие."""
    return _action(code, f"{message} {_RESOLVE_HINT.format(operation_id=operation_id)}")


def _base_result(
    operation_id: str,
    state: str,
    *,
    target_branch: str = "",
    worker_branch: str = "",
    worker_head: str = "",
    commit_point: str = "NOT_REACHED",
    error: dict[str, Any] | None = None,
    next_action: dict[str, str] | None = None,
    retryable: bool = False,
) -> dict[str, Any]:
    active = state in {"PENDING", "RUNNING"}
    return {
        "schema_version": 1,
        "operation_id": operation_id,
        "operation_state": state,
        "retryable": bool(retryable),
        "commit_point": commit_point,
        "git": {
            "status": "NOT_STARTED" if active else "FAILED",
            "target_branch": target_branch,
            "target_before": None,
            "target_after": None,
            "worker_branch": worker_branch,
            "worker_head": worker_head or None,
            "conflicts": [],
        },
        "task_links": {"status": "NOT_RUN", "items": {}},
        "rag": {"status": "NOT_RUN"},
        "lifecycle": {"status": "NOT_RUN"},
        "next_task": {"status": "NOT_REQUESTED"},
        "error": error,
        "warnings": [],
        "next_action": next_action or _action(
            "CHECK_SAME_OPERATION",
            f"Check operation {operation_id}; do not merge manually.",
        ),
    }


def normalize_request(
    *,
    name: str,
    scope: str,
    target: str = "",
    next_task_id: str = "",
    waive_diff_budget: bool = False,
    waived_by: str = "",
    task_outcome: str = "",
    merge_schema_version: int | None = None,
) -> dict[str, Any]:
    request = {
        "name": name.strip(),
        "scope": scope.rstrip("/"),
        "target": target.strip(),
        "next_task_id": next_task_id.strip(),
        "squash": True,
        "waive_diff_budget": bool(waive_diff_budget),
        "waived_by": waived_by.strip() if waive_diff_budget else "",
    }
    if merge_schema_version is not None:
        request["merge_schema_version"] = int(merge_schema_version)
        request["task_outcome"] = task_outcome.strip().lower()
    return request


def request_hash(request: dict[str, Any]) -> str:
    return _hash(request)


def _operation_id(value: str) -> str:
    return str(uuid.UUID(value))


def _decode_record(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    record = dict(row)
    record["request"] = json.loads(record.pop("request_json"))
    record["result"] = json.loads(record.pop("result_json"))
    record["accepted_admission"] = json.loads(
        record.pop("accepted_admission_json", "{}") or "{}"
    )
    return record


def get_operation_record(operation_id: str) -> dict[str, Any] | None:
    with _conn() as connection:
        row = connection.execute(
            "SELECT * FROM merge_operations WHERE operation_id=?", (operation_id,),
        ).fetchone()
    if not row:
        return None
    record = _decode_record(row)
    from app.ia import merge_receipts

    result = record["result"]
    if (
        merge_receipts.merge_receipt_configured()
        and result.get("operation_state") == "SUCCEEDED"
    ):
        try:
            durable = merge_receipts.get_merge_receipt(operation_id)
            if durable is None or durable != result.get("receipt"):
                raise merge_receipts.MergeReceiptError(
                    "stored success is not bound to its durable receipt"
                )
        except merge_receipts.MergeReceiptError as exc:
            result = copy.deepcopy(result)
            result["operation_state"] = "PARTIAL"
            result["retryable"] = False
            result["error"] = _error(
                "MERGE_RECEIPT_INVALID",
                str(exc),
                operation_id=operation_id,
                details={"exception_type": type(exc).__name__},
            )
            result["next_action"] = _blocking_action(
                "RECONCILE_SAME_OPERATION",
                "The target may be committed, but its durable receipt is missing or invalid.",
                operation_id,
            )
            record["result"] = result
    return record


def get_operation_result(operation_id: str) -> dict[str, Any] | None:
    record = get_operation_record(operation_id)
    return record["result"] if record else None


def operation_not_found_result(operation_id: str) -> dict[str, Any]:
    error = _error(
        "OPERATION_NOT_FOUND",
        f"merge operation '{operation_id}' not found",
        operation_id=operation_id,
        status=404,
        retryable=True,
    )
    return _base_result(
        operation_id,
        "FAILED",
        error=error,
        next_action=_action(
            "RETRY_SAME_OPERATION",
            "Retry the merge with this same operation_id; do not merge manually.",
        ),
        retryable=True,
    )


def _idempotency_conflict(
    operation_id: str, existing: dict[str, Any], request_digest: str,
) -> dict[str, Any]:
    error = _error(
        "IDEMPOTENCY_CONFLICT",
        "operation_id is already bound to a different merge request",
        operation_id=operation_id,
        status=409,
        details={
            "existing_request_hash": existing["request_hash"],
            "received_request_hash": request_digest,
        },
    )
    result = _base_result(
        operation_id,
        "FAILED",
        target_branch=existing["result"]["git"].get("target_branch", ""),
        worker_branch=existing["accepted_worker_branch"],
        worker_head=existing["accepted_worker_head"],
        error=error,
        next_action=_action(
            "USE_ORIGINAL_REQUEST",
            "Reuse this operation_id only with its original payload.",
        ),
    )
    return result


def _terminal_snapshot_matches(
    row: sqlite3.Row | dict[str, Any], accepted: dict[str, Any],
) -> bool:
    return (
        row["terminal_worker_branch"] == accepted["worker_branch"]
        and row["terminal_worker_head"] == accepted["worker_head"]
        and row["terminal_base_branch"] == accepted["base_branch"]
        and row["terminal_task_id"] == accepted["task_id"]
        and bool(row["terminal_needs_switch"]) == accepted["needs_switch"]
    )


def _blocked_by_active(
    active: dict[str, Any], requested_operation_id: str,
) -> tuple[dict[str, Any], bool, int]:
    """Новый operation_id операции не создал: воркера держит незакрытая предыдущая.

    Возвращается её сохранённый результат, поэтому вызывающий обязан узнать из ПЕРВЫХ
    строк, что смотрит на чужую операцию, а не на свою (иначе он читает старую ветку
    как исход своего мержа). В хранилище ничего не пишется.
    """
    state = active["state"]
    result = active["result"]
    if state in {"PENDING", "RUNNING"}:
        return result, False, 202
    blocking_id = str(result.get("operation_id") or active["operation_id"])
    blocked = {
        **result,
        "next_action": _blocking_action(
            "RESOLVE_BLOCKING_OPERATION",
            f"Operation {requested_operation_id} was NOT created and nothing was merged "
            f"for it: unresolved {state} operation {blocking_id} still holds this worker, "
            f"and this response describes THAT operation.",
            blocking_id,
        ),
    }
    return blocked, False, 200


def resolve_operation(
    operation_id: str, *, reason: str, actor: str = "",
) -> tuple[dict[str, Any], int]:
    """Единственный писатель `resolved_at`: человек снял блокировку с разобранной операции.

    Состояние НЕ меняется — оно остаётся записью о том, что произошло. Закрывается только
    блокировка, ровно как это делалось руками через SQL. `UNKNOWN` закрывается лишь здесь
    и никогда автоматически: неизвестный git-исход, закрытый автоматом, — это потерянные
    данные без следа.
    """
    reason = _text(reason, "")
    if not reason:
        error = _error(
            "RESOLUTION_REASON_REQUIRED",
            "reason is required: it is the record of how the outcome was reconciled",
            operation_id=operation_id, status=400,
        )
        return _base_result(operation_id, "FAILED", error=error), 400
    with _conn() as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            "SELECT * FROM merge_operations WHERE operation_id=?", (operation_id,),
        ).fetchone()
        if not row:
            return operation_not_found_result(operation_id), 404
        record = _decode_record(row)
        result = record["result"]
        if record["resolved_at"]:
            return result, 200
        if record["state"] not in {"PARTIAL", "UNKNOWN"}:
            error = _error(
                "OPERATION_NOT_BLOCKING",
                f"operation is {record['state']}: only PARTIAL or UNKNOWN block new merges",
                operation_id=operation_id, status=409,
            )
            return {**result, "error": error}, 409
        now = _now()
        previous_error = result.get("error")
        resolved = {
            key: value for key, value in result.items() if key != "error"
        }
        resolution = {
            "resolved_at": now,
            "reason": reason,
            "actor": actor,
        }
        if previous_error is not None:
            resolution["previous_error"] = previous_error
        resolved.update({
            "resolution": resolution,
            "next_action": _action(
                "NONE",
                f"Operation {operation_id} is resolved; new merges for this worker are "
                f"unblocked. Its state stays {record['state']} as the record of what happened.",
            ),
        })
        connection.execute(
            "DELETE FROM tm_task_reservations WHERE operation_id=?",
            (operation_id,),
        )
        finalization = json.loads(record.get("finalization_json") or "{}")
        final_session_id = str(finalization.get("session_id") or "")
        final_task = finalization.get("task") or {}
        final_task_ref = str(final_task.get("par_number") or "")
        if final_session_id and final_task_ref:
            session = connection.execute(
                "SELECT task_id, status FROM sessions WHERE id=?",
                (final_session_id,),
            ).fetchone()
            if (
                session is None
                or session["status"] == "archived"
                or str(session["task_id"] or "") != final_task_ref
            ):
                from app import tm

                tm.release_session_task_binding(connection, final_session_id)
        connection.execute(
            """UPDATE merge_operations
               SET resolved_at=?, resolution_outcome=?, resolution_actor=?,
                   result_json=?, result_hash=?, updated_at=?
               WHERE operation_id=? AND resolved_at IS NULL""",
            (now, reason, actor, _json(resolved), _hash(resolved), now, operation_id),
        )
        return resolved, 200


def _admission_evidence(
    admission: dict[str, Any],
    *,
    oracle_status: str,
    mapped_files: list[str] | None = None,
    target_recheck: dict[str, Any] | None = None,
) -> dict[str, Any]:
    target = dict(admission.get("target") or {})
    oracle = dict(admission.get("oracle") or {})
    return {
        "target": {
            "branch": str(target.get("branch") or ""),
            "sha": str(target.get("sha") or ""),
        },
        "oracle": {
            "source": str(oracle.get("source") or "none"),
            "task_id": str(oracle.get("task_id") or ""),
            "revision": int(oracle.get("revision") or 0),
            "ref": str(oracle.get("ref") or target.get("sha") or ""),
            "hash": str(oracle.get("hash") or ""),
            "status": oracle_status,
        },
        "mapped_files": list(mapped_files or []),
        "target_recheck": target_recheck or {
            "expected": str(target.get("sha") or ""),
            "actual": None,
            "matched": None,
        },
    }


def accept_operation_snapshot(
    *,
    operation_id: str,
    request: dict[str, Any],
    accepted: dict[str, Any],
) -> tuple[dict[str, Any], bool, int]:
    """Atomically insert-or-read one operation using a pre-mutation snapshot."""
    digest = request_hash(request)
    fingerprint = _hash({
        "session_id": accepted["session_id"],
        "request": request,
        "worker_branch": accepted["worker_branch"],
        "worker_head": accepted["worker_head"],
        "admission": accepted.get("admission", {}),
    })
    now = _now()
    with _conn() as connection:
        connection.execute("BEGIN IMMEDIATE")
        existing_row = connection.execute(
            "SELECT * FROM merge_operations WHERE operation_id=?", (operation_id,),
        ).fetchone()
        if existing_row:
            existing = _decode_record(existing_row)
            if existing["request_hash"] != digest:
                return _idempotency_conflict(operation_id, existing, digest), False, 409
            state = existing["state"]
            return existing["result"], False, 202 if state in {"PENDING", "RUNNING"} else 200

        active_row = connection.execute(
            """SELECT * FROM merge_operations
               WHERE session_id=? AND resolved_at IS NULL
                 AND state IN ('PENDING','RUNNING','PARTIAL','UNKNOWN')
               ORDER BY created_at DESC LIMIT 1""",
            (accepted["session_id"],),
        ).fetchone()
        if active_row:
            return _blocked_by_active(_decode_record(active_row), operation_id)

        terminal_rows = connection.execute(
            """SELECT * FROM merge_operations
               WHERE session_id=? AND request_hash=?
                 AND state IN ('SUCCEEDED','PARTIAL','UNKNOWN')
                 AND commit_point IN ('REACHED','UNKNOWN')
               ORDER BY finished_at DESC, created_at DESC""",
            (accepted["session_id"], digest),
        ).fetchall()
        for terminal_row in terminal_rows:
            if _terminal_snapshot_matches(terminal_row, accepted):
                terminal = _decode_record(terminal_row)
                return terminal["result"], False, 200

        target = request["target"] or accepted.get("base_branch", "")
        result = _base_result(
            operation_id,
            "PENDING",
            target_branch=target,
            worker_branch=accepted["worker_branch"],
            worker_head=accepted["worker_head"],
            retryable=True,
        )
        admission = accepted.get("admission", {})
        if admission:
            result["admission"] = _admission_evidence(
                admission,
                oracle_status=(
                    "pending" if admission.get("oracle", {}).get("required")
                    else "not_required"
                ),
            )
        try:
            connection.execute(
                """INSERT INTO merge_operations (
                       operation_id, operation_type, session_id, scope, worker_name,
                       request_json, request_hash, dedupe_fingerprint,
                       accepted_worker_branch, accepted_worker_head,
                       accepted_base_branch, accepted_task_id, accepted_needs_switch,
                       accepted_admission_json,
                       state, commit_point, result_json, result_hash,
                       created_at, updated_at
                   ) VALUES (?, 'merge', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                             'PENDING', 'NOT_REACHED', ?, ?, ?, ?)""",
                (
                    operation_id,
                    accepted["session_id"],
                    request["scope"],
                    request["name"],
                    _json(request),
                    digest,
                    fingerprint,
                    accepted["worker_branch"],
                    accepted["worker_head"],
                    accepted["base_branch"],
                    accepted["task_id"],
                    int(accepted["needs_switch"]),
                    _json(admission),
                    _json(result),
                    _hash(result),
                    now,
                    now,
                ),
            )
        except sqlite3.IntegrityError:
            active_row = connection.execute(
                """SELECT * FROM merge_operations
                   WHERE session_id=? AND resolved_at IS NULL
                     AND state IN ('PENDING','RUNNING','PARTIAL','UNKNOWN')
                   ORDER BY created_at DESC LIMIT 1""",
                (accepted["session_id"],),
            ).fetchone()
            if not active_row:
                raise
            return _blocked_by_active(_decode_record(active_row), operation_id)
    return result, True, 202


def _reopen_for_finalization(operation_id: str) -> bool:
    """CAS a PARTIAL operation whose DB stage is still pending back into the runner."""
    with _conn() as connection:
        connection.execute("BEGIN IMMEDIATE")
        cursor = connection.execute(
            """UPDATE merge_operations SET state='PENDING', owner_token='', updated_at=?
               WHERE operation_id=? AND state='PARTIAL' AND resolved_at IS NULL
                 AND commit_point='REACHED' AND finalization_stage='PENDING'""",
            (_now(), operation_id),
        )
        return cursor.rowcount == 1


def claim_operation(operation_id: str, owner_token: str) -> bool:
    with _conn() as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            "SELECT result_json FROM merge_operations WHERE operation_id=? AND state='PENDING'",
            (operation_id,),
        ).fetchone()
        if not row:
            return False
        result = json.loads(row["result_json"])
        result["operation_state"] = "RUNNING"
        result["next_action"] = _action(
            "CHECK_SAME_OPERATION",
            f"Merge operation {operation_id} is running; do not merge manually.",
        )
        now = _now()
        cursor = connection.execute(
            """UPDATE merge_operations
               SET state='RUNNING', owner_token=?, result_json=?, result_hash=?,
                   started_at=COALESCE(started_at, ?), updated_at=?
               WHERE operation_id=? AND state='PENDING'""",
            (owner_token, _json(result), _hash(result), now, now, operation_id),
        )
        return cursor.rowcount == 1


def save_prepared_finalization(operation_id: str, payload: dict[str, Any]) -> None:
    """Write the pre-Git journal. Runs under the repo lock, before any ref moves."""
    with _conn() as connection:
        connection.execute(
            "UPDATE merge_operations SET finalization_stage='PREPARED', "
            "finalization_json=?, updated_at=? WHERE operation_id=?",
            (_json({**payload, "stage": "PREPARED"}), _now(), operation_id),
        )


def checkpoint_merge_commit(operation_id: str, payload: dict[str, Any]) -> None:
    """The FIRST SQLite mutation after Git. Nothing else may write before it.

    Task links, payment, session lifecycle and YouGile all depend on this row saying
    that the commit exists. Writing any of them first would leave the durable record
    claiming the merge never happened.
    """
    with _conn() as connection:
        cursor = connection.execute(
            "UPDATE merge_operations SET commit_point='REACHED', "
            "finalization_stage='PENDING', finalization_json=?, updated_at=? "
            "WHERE operation_id=?",
            (_json({**payload, "stage": "PENDING"}), _now(), operation_id),
        )
        if cursor.rowcount != 1:
            raise RuntimeError(
                f"merge operation '{operation_id}' vanished before its commit checkpoint"
            )


def mark_finalization_applied(operation_id: str, payload: dict[str, Any]) -> None:
    with _conn() as connection:
        connection.execute(
            "UPDATE merge_operations SET finalization_stage='APPLIED', "
            "finalization_json=?, updated_at=? WHERE operation_id=?",
            (_json({**payload, "stage": "APPLIED"}), _now(), operation_id),
        )


def _repo_for_scope(scope: str) -> str:
    return scope.rstrip("/")


def reconcile_prepared_commit(record: dict[str, Any]) -> dict[str, Any] | None:
    """Ask the repository whether the lost checkpoint's commit exists.

    Evidence, not inference: exactly one commit in the first-parent range, its parent is
    the recorded `target_before`, its tree is the tree computed before the merge, and it
    carries this operation's own trailer. Anything else stays UNKNOWN — an unexpected
    target is foreign history, not a checkpoint we may claim.
    """
    import subprocess

    payload = json.loads(record["finalization_json"] or "{}")
    if not payload:
        return None
    repo = _repo_for_scope(record["scope"])
    target_before = payload.get("target_before") or ""
    target_branch = payload.get("target_branch") or ""
    operation_id = record["operation_id"]
    if not repo or not target_before or not target_branch:
        return None

    def git(*args: str) -> tuple[int, str]:
        done = subprocess.run(
            ["git", *args], cwd=repo, capture_output=True, text=True,
        )
        return done.returncode, done.stdout.strip()

    code, head = git("rev-parse", target_branch)
    if code != 0:
        return None
    if head == target_before:
        return {"reached": False, "payload": payload}
    code, listing = git(
        "rev-list", "--first-parent", f"{target_before}..{target_branch}",
    )
    if code != 0:
        return None
    commits = [line for line in listing.splitlines() if line]
    if len(commits) != 1 or commits[0] != head:
        return None
    code, parent = git("rev-parse", f"{head}^")
    if code != 0 or parent != target_before:
        return None
    code, tree = git("rev-parse", f"{head}^{{tree}}")
    expected_tree = payload.get("expected_tree") or ""
    if code != 0 or (expected_tree and tree != expected_tree):
        return None
    code, body = git("log", "-1", "--format=%B", head)
    if code != 0:
        return None
    trailers = subprocess.run(
        ["git", "interpret-trailers", "--parse"], input=body,
        cwd=repo, capture_output=True, text=True,
    )
    if trailers.returncode != 0:
        return None
    marker = f"Orchestra-Operation: {operation_id}"
    if [line.strip() for line in trailers.stdout.splitlines()].count(marker) != 1:
        return None
    from app.workspace import _parse_merged_commits

    payload["target_after"] = head
    payload["commits"] = _parse_merged_commits(repo, target_before, head)
    payload["stage"] = "PENDING"
    return {"reached": True, "payload": payload, "target_after": head}


def _session_snapshot(session_id: str) -> dict[str, Any]:
    row = get_session(session_id)
    if not row or row.get("status") == "archived":
        raise RuntimeError(f"session '{session_id}' not found")
    from app.workspace import inspect_worktree_identity

    branch, head = inspect_worktree_identity(row.get("worktree_path") or "")
    return {
        "session_id": row["id"],
        "name": row["name"],
        "scope": (row.get("scope") or "").rstrip("/"),
        "base_branch": row.get("base_branch") or "",
        "worker_branch": branch,
        "worker_head": head,
        "task_id": str(row.get("task_id") or ""),
        "needs_switch": bool(row.get("needs_switch")),
        "worktree_path": row.get("worktree_path") or "",
    }


def _target_head(worktree_path: str, target_branch: str) -> str:
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--verify", f"{target_branch}^{{commit}}"],
            cwd=worktree_path, capture_output=True, text=True,
            timeout=15, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError(f"cannot resolve merge target {target_branch}: {exc}") from exc
    if proc.returncode != 0:
        detail = proc.stderr.strip() or proc.stdout.strip() or f"exit {proc.returncode}"
        raise ValueError(f"cannot resolve merge target {target_branch}: {detail}")
    return proc.stdout.strip()


def _prepare_admission_snapshot(
    accepted: dict[str, Any], request: dict[str, Any],
) -> dict[str, Any]:
    from app import acceptance
    from app.merge_test_gate import changed_paths

    target_branch = request.get("target") or accepted.get("base_branch") or "main"
    if not Path(accepted["worktree_path"]).is_dir():
        # Compatibility for callers whose worktree identity seam is explicitly mocked.
        # A real missing worktree cannot reach here: `_session_snapshot` inspects Git first.
        return {
            "target": {"branch": target_branch, "sha": ""},
            "oracle": {
                "source": "none", "task_id": str(accepted.get("task_id") or ""),
                "revision": 0, "ref": "", "hash": "", "command": "",
                "required": False, "manifest": [],
            },
        }
    target_sha = _target_head(accepted["worktree_path"], target_branch)
    changed = changed_paths(
        accepted["worktree_path"],
        target_ref=target_branch,
        target_sha=target_sha,
    )
    if changed is None:
        raise ValueError("cannot derive target-relative merge paths")
    nested_behavioral = target_branch not in {"main", "master"} and any(
        path.startswith("app/") or path.startswith("tests/")
        for path in changed
    )
    task_oracle = acceptance.task_oracle_for_session(accepted["session_id"])
    required = bool(task_oracle.get("required"))
    if nested_behavioral and not required:
        raise acceptance.AcceptanceCommandError(
            "oracle_missing",
            "nested behavioral merge requires an authoritative task oracle",
        )
    if required:
        oracle = acceptance.pin_task_oracle(
            task_id=str(task_oracle.get("task_id") or accepted.get("task_id") or ""),
            revision=int(task_oracle.get("revision") or 0),
            command=str(task_oracle.get("command") or ""),
            manifest_paths=list(task_oracle.get("manifest_paths") or []),
            updated_by=dict(task_oracle.get("updated_by") or {}),
            target_ref=target_branch,
            target_sha=target_sha,
            worktree_path=accepted["worktree_path"],
        )
        oracle["required"] = True
    elif task_oracle.get("command"):
        oracle = {
            "source": "legacy_task",
            "task_id": str(task_oracle.get("task_id") or accepted.get("task_id") or ""),
            "revision": 0,
            "ref": target_sha,
            "hash": _hash({
                "source": "legacy_task",
                "task_id": task_oracle.get("task_id"),
                "ref": target_sha,
                "command": task_oracle.get("command"),
            }),
            "command": str(task_oracle["command"]),
            "required": False,
            "manifest": [],
        }
    else:
        oracle = {
            "source": "none",
            "task_id": str(accepted.get("task_id") or ""),
            "revision": 0,
            "ref": target_sha,
            "hash": "",
            "command": "",
            "required": False,
            "manifest": [],
        }
    return {
        "target": {"branch": target_branch, "sha": target_sha},
        "oracle": oracle,
    }


def _verify_accepted_snapshot(record: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
    try:
        current = _session_snapshot(record["session_id"])
    except Exception as exc:
        return None, err_text(exc)
    expected = {
        "name": record["worker_name"],
        "scope": record["scope"],
        "worker_branch": record["accepted_worker_branch"],
        "worker_head": record["accepted_worker_head"],
        "base_branch": record["accepted_base_branch"],
        "task_id": record["accepted_task_id"],
        "needs_switch": bool(record["accepted_needs_switch"]),
    }
    mismatches = [
        key for key, value in expected.items() if current.get(key) != value
    ]
    if mismatches:
        return current, f"session identity changed before merge: {', '.join(mismatches)}"
    return current, ""


def _replay_drift(record: dict[str, Any]) -> dict[str, Any] | None:
    """Отказ, если повтор operation_id пришёл к УЕХАВШЕМУ воркеру; иначе None.

    Fail-closed в обе стороны: расхождение — отказ, и невозможность опросить воркер —
    тоже отказ. «Не смог проверить» не имеет права читаться как «всё хорошо».
    """
    operation_id = record["operation_id"]
    try:
        current = _session_snapshot(record["session_id"])
    except Exception as exc:
        detail = (
            f"Cannot verify that the worker is still where this operation was accepted: "
            f"{err_text(exc)}"
        )
        error = _error(
            "REPLAY_VERIFICATION_FAILED", detail, operation_id=operation_id,
            status=409, details={"exception_type": type(exc).__name__},
        )
        return _base_result(
            operation_id,
            "FAILED",
            target_branch=record["result"]["git"].get("target_branch", ""),
            worker_branch=record["accepted_worker_branch"],
            worker_head=record["accepted_worker_head"],
            error=error,
            next_action=_action(
                "VERIFY_WORKER_THEN_NEW_OPERATION",
                "Check the worker's actual branch and unmerged commits (worker_wip), "
                "then start a new operation with a fresh operation_id.",
            ),
        )

    accepted_branch = record["accepted_worker_branch"]
    accepted_head = record["accepted_worker_head"]
    if (
        current["worker_branch"] == accepted_branch
        and current["worker_head"] == accepted_head
    ):
        return None
    # Успешный мерж САМ двигает воркера (worktree сбрасывается на target). Сверять его
    # после этого с точкой ПРИЁМА — значит объявлять собственную работу дрейфом. Точка
    # сравнения для завершённой операции — состояние, в котором она его оставила.
    if record["finished_at"] and _terminal_snapshot_matches(record, current):
        return None

    detail = (
        f"This operation was accepted for branch {accepted_branch} at "
        f"{accepted_head or '(unknown)'}, but the worker is now on branch "
        f"{current['worker_branch']} at {current['worker_head']}. The stored result "
        f"describes the earlier branch and says nothing about the worker's current commits."
    )
    error = _error(
        "REPLAY_WORKER_MOVED", detail, operation_id=operation_id, status=409,
        details={
            "exception_type": "ReplayWorkerMoved",
            "accepted_worker_branch": accepted_branch,
            "accepted_worker_head": accepted_head,
            "actual_worker_branch": current["worker_branch"],
            "actual_worker_head": current["worker_head"],
        },
    )
    return _base_result(
        operation_id,
        "FAILED",
        target_branch=record["result"]["git"].get("target_branch", ""),
        worker_branch=current["worker_branch"],
        worker_head=current["worker_head"],
        error=error,
        next_action=_action(
            "VERIFY_WORKER_THEN_NEW_OPERATION",
            f"Check what is unmerged on {current['worker_branch']} (worker_wip), then "
            f"start a new operation with a fresh operation_id.",
        ),
    )


def _link_status(items: Any) -> tuple[str, dict[str, Any], list[str], list[str]]:
    """Разложить исходы привязки на провалы и предупреждения.

    «Номер не существует» — про ИСТОРИЮ: номер уже в коммите, чинить нечего, и провалом
    он делает ветку непригодной навсегда. «Номер есть, но привязка не удалась» — про
    СОСТОЯНИЕ (исключение, недоступная БД задач), там повтор может помочь, и это провал.
    Отличаются по маркеру `reason` из `tm.link_commits_to_task`; ответ без маркера
    (старый сервер) считается провалом — консервативно.
    """
    if not isinstance(items, dict) or not items:
        return "NOT_RUN", {}, [], []
    normalized: dict[str, Any] = {}
    successes = 0
    failures: list[str] = []
    warnings: list[str] = []
    for task_ref, info in items.items():
        normalized[str(task_ref)] = info
        ok = isinstance(info, dict) and bool(info.get("ok") or info.get("id"))
        if ok:
            successes += 1
            continue
        detail = info.get("error") if isinstance(info, dict) else "invalid link result"
        text = f"{task_ref}: {_text(detail, 'link failed without detail')}"
        if isinstance(info, dict) and info.get("reason") == "TASK_NOT_FOUND":
            warnings.append(text)
        else:
            failures.append(text)
    if failures:
        return ("PARTIAL" if successes else "FAILED"), normalized, failures, warnings
    if warnings:
        return "WARNED", normalized, [], warnings
    return "SUCCEEDED", normalized, [], []


def _classify_failure(raw: dict[str, Any], message: str) -> tuple[str, dict[str, Any], dict[str, str]]:
    lower = message.lower()
    details: dict[str, Any] = {
        "upstream_state": raw.get("state"),
        "normalization": "LEGACY_UPSTREAM_ERROR",
    }
    if raw.get("code") == "TARGET_HEAD_CHANGED":
        details["target_recheck"] = raw.get("target_recheck") or {}
        return "TARGET_HEAD_CHANGED", details, _action(
            "REFRESH_TARGET_THEN_NEW_OPERATION",
            "Target moved after admission; start a fresh merge operation.",
        )
    if raw.get("conflicts"):
        details["paths"] = list(raw["conflicts"])
        return "CONFLICT", details, _action(
            "RESOLVE_ON_WORKER_THEN_NEW_OPERATION",
            "Resolve and commit the conflict on the worker branch, then start a new operation; do not merge the target manually.",
        )
    if raw.get("code") == "NO_COMMITS_MERGED":
        if "target working tree is dirty" in lower:
            details["paths_text"] = message
            return "NO_COMMITS_MERGED", details, _action(
                "CLEAN_TARGET_THEN_NEW_OPERATION",
                "Clean the target worktree, then start a new merge operation.",
            )
        return "NO_COMMITS_MERGED", details, _action(
            "CHECK_WORKER_THEN_NEW_OPERATION",
            "No commits reached the target branch; verify the worker branch before retrying.",
        )
    if "target working tree is dirty" in lower:
        details["paths_text"] = message
        return "TARGET_DIRTY", details, _action(
            "CLEAN_TARGET_THEN_NEW_OPERATION",
            "Clean the target worktree, then start a new merge operation.",
        )
    if "worker working tree is dirty" in lower:
        details["paths_text"] = message
        return "WORKER_DIRTY", details, _action(
            "COMMIT_WORKER_THEN_NEW_OPERATION",
            "Commit or discard the listed worker changes, then start a new merge operation.",
        )
    if "worker is running" in lower:
        return "BUSY", details, _action(
            "WAIT_UNTIL_IDLE_THEN_NEW_OPERATION",
            "Wait for the worker to become idle, then start a new merge operation.",
        )
    if "worker is waiting" in lower:
        return "WAITING", details, _action(
            "FINISH_WAIT_THEN_NEW_OPERATION",
            "Finish the worker wait state, then start a new merge operation.",
        )
    if "rollback" in lower:
        return "ROLLBACK_FAILED", details, _action(
            "RECONCILE_SAME_OPERATION",
            "Keep the worker quarantined and reconcile this operation; do not merge manually.",
        )
    if "target branch" in lower and ("does not exist" in lower or "missing" in lower):
        return "TARGET_MISSING", details, _action(
            "FIX_TARGET_THEN_NEW_OPERATION",
            "Restore or select a valid target branch, then start a new operation.",
        )
    if "identity changed" in lower or "head changed" in lower or "branch changed" in lower:
        return "SESSION_IDENTITY_CHANGED", details, _action(
            "REFRESH_WORKER_THEN_NEW_OPERATION",
            "Refresh the worker snapshot, then start a new operation.",
        )
    return "LEGACY_UPSTREAM_ERROR", details, _action(
        "FIX_AND_START_NEW_OPERATION",
        "Fix the reported pre-merge failure, then start a new operation.",
    )


def normalize_merge_result(
    operation_id: str,
    raw: Any,
    request: dict[str, Any],
    *,
    rag_enabled: bool | None = None,
) -> dict[str, Any]:
    if not isinstance(raw, dict):
        error = _error(
            "UNKNOWN_OUTCOME",
            f"Invalid merge outcome: {type(raw).__name__}",
            operation_id=operation_id,
            outcome_unknown=True,
            details={"exception_type": "InvalidMergeOutcome"},
        )
        result = _base_result(
            operation_id, "UNKNOWN", error=error, commit_point="UNKNOWN",
            next_action=_action(
                "RECONCILE_SAME_OPERATION",
                "Check and reconcile this operation; do not merge manually.",
            ),
        )
        result["git"]["status"] = "UNKNOWN"
        return result

    # A successful response with an unchanged target and no transferred commits is
    # not a merge. Keep this invariant here as well as in the route: operation results
    # can come from an older server or a resumed runner, and neither may close a task.
    no_commits_merged = (
        raw.get("target_before")
        and raw.get("target_before") == raw.get("target_after")
        and int(raw.get("commits_merged") or 0) == 0
        and not raw.get("conflicts")
    )
    if no_commits_merged:
        raw = {
            **raw,
            "ok": False,
            "state": "failed",
            "commit_point": "not_reached",
            "code": "NO_COMMITS_MERGED",
            "error": raw.get("error") or "merge produced no new commits",
        }

    raw_state = str(raw.get("state") or ("merged" if raw.get("ok") else "failed"))
    raw_point = str(raw.get("commit_point") or "unknown")
    commit_point = {
        "target_committed": "REACHED",
        "not_reached": "NOT_REACHED",
        "rolled_back": "NOT_REACHED",
        "unknown": "UNKNOWN",
    }.get(raw_point, "UNKNOWN")
    message = _text(raw.get("error"), "merge failed without an error detail")
    conflicts = raw.get("conflicts") if isinstance(raw.get("conflicts"), list) else []
    if raw.get("ok"):
        git_status = "SUCCEEDED"
    elif raw_state == "conflict" or conflicts:
        git_status = "CONFLICT"
    elif raw.get("code") == "NO_COMMITS_MERGED":
        git_status = "FAILED"
    elif "working tree is dirty" in message.lower():
        git_status = "DIRTY"
    elif commit_point == "UNKNOWN":
        git_status = "UNKNOWN"
    elif commit_point == "REACHED":
        # Post-commit stages may set the aggregate outcome to false, but Git has
        # already committed at this point and must not be reported as failed.
        git_status = "SUCCEEDED"
    else:
        git_status = "FAILED"

    finalization = raw.get("finalization")
    linked_tasks = raw.get("linked_tasks")
    if (
        not linked_tasks
        and isinstance(finalization, dict)
        and finalization.get("links")
    ):
        linked_tasks = finalization["links"]
    link_status, link_items, link_failures, link_warnings = _link_status(linked_tasks)
    lifecycle = raw.get("lifecycle_status")
    lifecycle_status = (
        "SUCCEEDED" if isinstance(lifecycle, dict) and lifecycle.get("ok")
        else "FAILED" if isinstance(lifecycle, dict)
        else "NOT_RUN"
    )
    rag_raw = raw.get("rag_backfill_status")
    if rag_raw == "not_ready" and rag_enabled is False:
        rag_status = "DISABLED"
    else:
        rag_status = {
            "accepted": "ACCEPTED",
            "coalesced": "COALESCED",
            "not_ready": "NOT_READY",
        }.get(rag_raw, "NOT_RUN" if rag_raw is None else "FAILED")
    if not request.get("next_task_id"):
        next_status = "NOT_REQUESTED"
    else:
        switch = raw.get("switch")
        task_status = raw.get("task_status")
        next_status = (
            "SUCCEEDED"
            if isinstance(switch, dict) and switch.get("ok")
            and isinstance(task_status, dict) and task_status.get("ok")
            else "FAILED"
        )

    stage_failures: list[tuple[str, str]] = []
    if link_failures:
        stage_failures.append(("TASK_LINK_PARTIAL", "; ".join(link_failures)))
    if lifecycle_status == "FAILED":
        stage_failures.append((
            "LIFECYCLE_FAILED",
            _text(lifecycle.get("error") if isinstance(lifecycle, dict) else "", "lifecycle persistence failed"),
        ))
    if rag_status == "NOT_READY":
        stage_failures.append(("RAG_NOT_READY", "RAG backfill was not accepted"))
    elif rag_status == "FAILED":
        stage_failures.append(("RAG_STATUS_INVALID", f"unknown RAG status: {rag_raw!r}"))
    if next_status == "FAILED":
        switch = raw.get("switch") if isinstance(raw.get("switch"), dict) else {}
        task_status = raw.get("task_status") if isinstance(raw.get("task_status"), dict) else {}
        stage_failures.append((
            "NEXT_TASK_FAILED",
            _text(switch.get("error") or task_status.get("error"), "next-task transition failed"),
        ))

    warnings: list[dict[str, str]] = [
        {"code": "TASK_LINK_NOT_FOUND", "message": text} for text in link_warnings
    ]
    primary_failures = [item for item in stage_failures if item[0] not in SECONDARY_STAGES]
    warnings += [
        {"code": code, "message": detail}
        for code, detail in stage_failures if code in SECONDARY_STAGES
    ]

    error: dict[str, Any] | None = None
    next_action = _action("NONE", "Merge operation completed; no retry is required.")
    retryable = False
    if commit_point == "UNKNOWN" or raw_state == "partial" and raw_point == "unknown":
        state = "UNKNOWN"
        unknown_code = "ROLLBACK_FAILED" if "rollback" in message.lower() else "UNKNOWN_OUTCOME"
        error = _error(
            unknown_code, message, operation_id=operation_id,
            status=raw.get("_http_status"), outcome_unknown=True,
            details={"upstream_state": raw_state, "commit_point": raw_point},
        )
        next_action = _blocking_action(
            "RECONCILE_SAME_OPERATION",
            "Reconcile this operation before any retry; do not merge manually.",
            operation_id,
        )
    elif raw_state == "partial" or commit_point == "REACHED" and (not raw.get("ok") or primary_failures):
        state = "PARTIAL"
        code, detail = primary_failures[0] if primary_failures else ("POST_COMMIT_PARTIAL", message)
        error = _error(
            code, detail, operation_id=operation_id,
            status=raw.get("_http_status"),
            details={"failed_stages": [item[0] for item in stage_failures]},
        )
        next_action = _blocking_action(
            "FINALIZE_SAME_OPERATION",
            "Finalize this operation; do not manually apply the Git merge. "
            "Verifying the merged artifact is expected — check the target branch and "
            "worker_wip before reporting this task done.",
            operation_id,
        )
    elif raw.get("ok") and not primary_failures:
        state = "SUCCEEDED"
        if warnings:
            next_action = _action(
                "REVIEW_WARNINGS_OUTSIDE_MERGE",
                "Merge committed; no merge retry is required. Handle these outside the merge: "
                + "; ".join(warning["message"] for warning in warnings),
            )
    else:
        state = "FAILED"
        code, details, next_action = _classify_failure(raw, message)
        error = _error(
            code, message, operation_id=operation_id,
            status=raw.get("_http_status"), details=details,
        )

    if isinstance(finalization, dict) and finalization.get("stage") == "PENDING":
        # DB-стадия не доехала, но коммит есть и журнал его описывает: это чинится
        # повтором ТОГО ЖЕ operation_id и никогда вторым мержем.
        retryable = True

    result = {
        "schema_version": 1,
        "operation_id": operation_id,
        "operation_state": state,
        "retryable": retryable,
        "commit_point": commit_point,
        "git": {
            "status": git_status,
            "target_branch": str(raw.get("target_branch") or request.get("target") or ""),
            "target_before": raw.get("target_before") or None,
            "target_after": raw.get("target_after") or None,
            "worker_branch": str(raw.get("worker_branch") or raw.get("branch") or ""),
            "worker_head": raw.get("worker_head") or None,
            "conflicts": conflicts,
            "commits_merged": int(raw.get("commits_merged") or 0),
            # Класс дрейфа личности и запиннённый HEAD: поля ДОБАВЛЯЮТСЯ, старые не меняются,
            # поэтому старый читатель их просто не заметит.
            "head_drift": str(raw.get("head_drift") or "SAME"),
            "worker_head_pinned": raw.get("worker_head_pinned") or None,
        },
        "task_links": {"status": link_status, "items": link_items},
        "rag": {"status": rag_status},
        "lifecycle": {"status": lifecycle_status},
        "next_task": {"status": next_status},
        "error": error,
        # Поле ДОБАВЛЯЕТСЯ: то, что не меняет состояние операции, но исчезнуть молча не
        # имеет права. Старый читатель его не заметит.
        "warnings": warnings,
        "next_action": next_action,
    }
    for warning in raw.get("warnings") or []:
        if isinstance(warning, dict) and warning.get("code"):
            result["warnings"].append(warning)
    if isinstance(finalization, dict):
        result["finalization"] = finalization
    if isinstance(raw.get("receipt"), dict):
        result["receipt"] = copy.deepcopy(raw["receipt"])
    return result


def finish_operation(
    operation_id: str,
    owner_token: str,
    result: dict[str, Any],
    terminal: dict[str, Any] | None,
) -> bool:
    state = result["operation_state"]
    if state not in TERMINAL_STATES:
        raise ValueError(f"cannot finish operation in state {state}")
    terminal = terminal or {}
    finalization = result.get("finalization")
    now = _now()
    with _conn() as connection:
        cursor = connection.execute(
            """UPDATE merge_operations
               SET state=?, commit_point=?, result_json=?, result_hash=?,
                   terminal_worker_branch=?, terminal_worker_head=?,
                   terminal_base_branch=?, terminal_task_id=?, terminal_needs_switch=?,
                   finalization_stage=COALESCE(?, finalization_stage),
                   finalization_json=COALESCE(?, finalization_json),
                   finished_at=?, updated_at=?, owner_token=''
               WHERE operation_id=? AND state='RUNNING' AND owner_token=?""",
            (
                state,
                result["commit_point"],
                _json(result),
                _hash(result),
                terminal.get("worker_branch", ""),
                terminal.get("worker_head", ""),
                terminal.get("base_branch", ""),
                terminal.get("task_id", ""),
                int(bool(terminal.get("needs_switch"))),
                finalization.get("stage") if isinstance(finalization, dict) else None,
                _json(finalization) if isinstance(finalization, dict) else None,
                now,
                now,
                operation_id,
                owner_token,
            ),
        )
        return cursor.rowcount == 1


def _unknown_from_record(record: dict[str, Any], message: str, *, exception_type: str) -> dict[str, Any]:
    result = record["result"]
    result["operation_state"] = "UNKNOWN"
    result["commit_point"] = "UNKNOWN"
    result["retryable"] = False
    result["git"]["status"] = "UNKNOWN"
    result["error"] = _error(
        "UNKNOWN_OUTCOME", message, operation_id=record["operation_id"],
        outcome_unknown=True, details={"exception_type": exception_type},
    )
    result["next_action"] = _blocking_action(
        "RECONCILE_SAME_OPERATION",
        "Reconcile this operation before any retry; do not merge manually.",
        record["operation_id"],
    )
    return result


def _mark_terminal_snapshot_failure(
    result: dict[str, Any], operation_id: str, exc: BaseException,
) -> None:
    if result["commit_point"] != "REACHED":
        return
    detail = f"Cannot verify terminal worker state: {err_text(exc)}"
    if result["operation_state"] == "SUCCEEDED":
        result["operation_state"] = "PARTIAL"
        result["retryable"] = False
        result["error"] = _error(
            "TERMINAL_SNAPSHOT_FAILED",
            detail,
            operation_id=operation_id,
            details={
                "exception_type": type(exc).__name__,
                "failed_stages": ["TERMINAL_SNAPSHOT_FAILED"],
            },
        )
    elif result["operation_state"] == "PARTIAL":
        error = result.get("error")
        if isinstance(error, dict):
            details = error.setdefault("details", {})
            failures = details.setdefault("failed_stages", [])
            if "TERMINAL_SNAPSHOT_FAILED" not in failures:
                failures.append("TERMINAL_SNAPSHOT_FAILED")
            details["terminal_snapshot_error"] = detail
    result["next_action"] = _blocking_action(
        "FINALIZE_SAME_OPERATION",
        "Verify and finalize this operation; do not manually apply the Git merge. "
        "Verifying the merged artifact is expected — check the target branch and "
        "worker_wip before reporting this task done.",
        operation_id,
    )


def recover_orphan_operations() -> list[str]:
    """Reconcile orphaned Git commits before falling back to UNKNOWN."""
    now = _now()
    with _conn() as connection:
        running = list(connection.execute(
            "SELECT * FROM merge_operations WHERE state='RUNNING'"
        ).fetchall())

    pending: list[str] = []
    for row in running:
        record = _decode_record(row)
        operation_id = record["operation_id"]
        stage = str(record.get("finalization_stage") or "")
        point = str(record.get("commit_point") or "")

        if stage == "PENDING" and point == "REACHED":
            with _conn() as connection:
                cursor = connection.execute(
                    "UPDATE merge_operations SET state='PENDING', owner_token='', "
                    "finished_at=NULL, updated_at=? "
                    "WHERE operation_id=? AND state='RUNNING'",
                    (now, operation_id),
                )
            if cursor.rowcount == 1:
                pending.append(operation_id)
            continue

        reconciled = (
            reconcile_prepared_commit(record)
            if stage == "PREPARED" else None
        )
        if reconciled is not None and reconciled["reached"]:
            payload = reconciled["payload"]
            checkpoint_merge_commit(operation_id, payload)
            with _conn() as connection:
                cursor = connection.execute(
                    "UPDATE merge_operations SET state='PENDING', owner_token='', "
                    "finished_at=NULL, updated_at=? "
                    "WHERE operation_id=? AND state='RUNNING'",
                    (now, operation_id),
                )
            if cursor.rowcount == 1:
                pending.append(operation_id)
            continue

        if (
            reconciled is not None
            and not reconciled["reached"]
            and str(record["result"].get("operation_state") or "")
            in {"PENDING", "RUNNING"}
        ):
            payload = reconciled["payload"]
            from app import tm

            tm.release_merge_finalization(payload)
            result = dict(record["result"])
            result.update(
                operation_state="FAILED",
                retryable=False,
                commit_point="NOT_REACHED",
                error=_error(
                    "ORPHANED_BEFORE_GIT",
                    "Server restarted before the prepared merge reached Git.",
                    operation_id=operation_id,
                ),
                finalization={**payload, "stage": "NOT_REQUIRED"},
                next_action=_action(
                    "START_NEW_OPERATION",
                    "The prepared merge did not reach Git; start a new operation.",
                ),
            )
            with _conn() as connection:
                connection.execute(
                    "UPDATE merge_operations SET state='FAILED', "
                    "commit_point='NOT_REACHED', finalization_stage='NOT_REQUIRED', "
                    "finalization_json=?, result_json=?, result_hash=?, owner_token='', "
                    "finished_at=?, updated_at=? WHERE operation_id=? AND state='RUNNING'",
                    (
                        _json({**payload, "stage": "NOT_REQUIRED"}),
                        _json(result), _hash(result), now, now, operation_id,
                    ),
                )
            continue

        with _conn() as connection:
            connection.execute("BEGIN IMMEDIATE")
            current = connection.execute(
                "SELECT * FROM merge_operations WHERE operation_id=? AND state='RUNNING'",
                (operation_id,),
            ).fetchone()
            if current is None:
                continue
            record = _decode_record(current)
            result = _unknown_from_record(
                record,
                "Server restarted while the merge operation was running; Git outcome requires reconciliation.",
                exception_type="OrphanedMergeOperation",
            )
            connection.execute(
                """UPDATE merge_operations
                   SET state='UNKNOWN', commit_point='UNKNOWN', result_json=?, result_hash=?,
                       owner_token='', finished_at=?, updated_at=?
                   WHERE operation_id=? AND state='RUNNING'""",
                (_json(result), _hash(result), now, now, operation_id),
            )
    with _conn() as connection:
        queued = [
            row["operation_id"] for row in connection.execute(
                "SELECT operation_id FROM merge_operations WHERE state='PENDING'"
            ).fetchall()
        ]
    return list(dict.fromkeys([*pending, *queued]))


def _recover_lost_checkpoint(operation_id: str, raw: dict[str, Any]) -> dict[str, Any]:
    """Rebuild the lost first post-Git checkpoint from repository evidence."""
    record = get_operation_record(operation_id)
    reconciled = reconcile_prepared_commit(record) if record else None
    if reconciled is None:
        # Ни trailer, ни parent/tree не совпали, а target уехал — это чужая или
        # повреждённая история. `UNKNOWN` здесь честнее любого предположения.
        return raw
    if not reconciled["reached"]:
        payload = reconciled["payload"]
        from app import tm

        tm.release_merge_finalization(payload)
        return {
            **raw,
            "state": "failed",
            "commit_point": "not_reached",
            "finalization": {**payload, "stage": "NOT_REQUIRED"},
        }
    payload = reconciled["payload"]
    checkpoint_merge_commit(operation_id, payload)
    return {
        **raw,
        "state": "partial",
        "commit_point": "target_committed",
        "target_after": reconciled["target_after"],
        "error": raw.get("error") or "first post-commit checkpoint recovered from Git",
        "finalization": payload,
    }


async def _resume_finalization(record: dict[str, Any]) -> dict[str, Any]:
    """Finish the DB stage of an operation whose Git commit already exists."""
    from app.routes.sessions import apply_merge_finalization

    operation_id = record["operation_id"]
    payload = json.loads(record["finalization_json"] or "{}")
    result = dict(record["result"])
    try:
        applied = await apply_merge_finalization(payload)
    except Exception as exc:
        detail = f"merge finalization replay failed: {err_text(exc)}"
        logger.error("%s operation_id=%s", detail, operation_id)
        result["error"] = _error(
            "POST_COMMIT_PARTIAL", detail, operation_id=operation_id,
            retryable=True, details={"failed_stages": ["FINALIZATION_PENDING"]},
        )
        result["operation_state"] = "PARTIAL"
        result["retryable"] = True
        result["finalization"] = payload
        link_status, link_items, _failures, link_warnings = _link_status(
            payload.get("links"),
        )
        if link_items:
            result["task_links"] = {"status": link_status, "items": link_items}
            result["warnings"] = list(result.get("warnings") or []) + [
                {"code": "TASK_LINK_NOT_FOUND", "message": text}
                for text in link_warnings
            ]
        if result.get("commit_point") == "REACHED":
            result["git"]["status"] = "SUCCEEDED"
        return result
    payload["stage"] = "APPLIED"
    await asyncio.to_thread(mark_finalization_applied, operation_id, payload)
    link_status, link_items, _failures, link_warnings = _link_status(
        applied.get("linked_tasks"),
    )
    result.update(
        operation_state="SUCCEEDED",
        commit_point="REACHED",
        retryable=False,
        error=None,
        finalization=payload,
        next_action=_action(
            "NONE", "Merge operation completed; no retry is required.",
        ),
    )
    result["task_links"] = {"status": link_status, "items": link_items}
    result["warnings"] = list(result.get("warnings") or []) + [
        {"code": "TASK_LINK_NOT_FOUND", "message": text} for text in link_warnings
    ]
    return result


async def _run_operation(operation_id: str) -> None:
    owner_token = str(uuid.uuid4())
    claimed = await asyncio.to_thread(claim_operation, operation_id, owner_token)
    if not claimed:
        return
    record = await asyncio.to_thread(get_operation_record, operation_id)
    if not record:
        return
    if record["finalization_stage"] == "PENDING" and record["commit_point"] == "REACHED":
        # Git уже сделал свой единственный коммит: повтор доделывает ТОЛЬКО стадию БД.
        try:
            result = await _resume_finalization(record)
            terminal = None
            try:
                terminal = await asyncio.to_thread(
                    _session_snapshot, record["session_id"],
                )
            except Exception as exc:
                _mark_terminal_snapshot_failure(result, operation_id, exc)
            await asyncio.to_thread(
                finish_operation, operation_id, owner_token, result, terminal,
            )
        except BaseException as exc:
            logger.exception("merge finalization replay crashed operation_id=%s", operation_id)
            result = _unknown_from_record(
                record,
                f"Merge finalization replay crashed: {err_text(exc)}",
                exception_type=type(exc).__name__,
            )
            await asyncio.to_thread(
                finish_operation, operation_id, owner_token, result, None,
            )
            if isinstance(exc, asyncio.CancelledError):
                raise
        return
    try:
        current, mismatch = await asyncio.to_thread(_verify_accepted_snapshot, record)
        if mismatch:
            error = _error(
                "SESSION_IDENTITY_CHANGED", mismatch, operation_id=operation_id,
                status=409, details={"exception_type": "SessionIdentityChanged"},
            )
            result = _base_result(
                operation_id,
                "FAILED",
                target_branch=record["request"].get("target", ""),
                worker_branch=record["accepted_worker_branch"],
                worker_head=record["accepted_worker_head"],
                error=error,
                next_action=_action(
                    "REFRESH_WORKER_THEN_NEW_OPERATION",
                    "Refresh the worker identity, then start a new operation.",
                ),
            )
        else:
            from app import acceptance as acceptance_module
            from app.acceptance import FAILED, INCONCLUSIVE, PASSED, SKIPPED

            admission = dict(record.get("accepted_admission") or {})
            legacy_unpinned = not admission
            if legacy_unpinned:
                target = {
                    "branch": (
                        record["request"].get("target")
                        or record["accepted_base_branch"]
                    ),
                    "sha": "",
                }
                oracle = {
                    "source": "legacy_dynamic",
                    "task_id": record["accepted_task_id"],
                    "revision": 0,
                    "ref": "",
                    "hash": "",
                    "required": False,
                }
                admission = {"target": target, "oracle": oracle}
                acceptance = await asyncio.to_thread(
                    acceptance_module.evaluate_for_merge,
                    session_id=record["session_id"],
                    worktree_path=current["worktree_path"],
                )
                oracle_status = str(acceptance.get("status") or INCONCLUSIVE)
            else:
                target = dict(admission.get("target") or {})
                oracle = dict(admission.get("oracle") or {})
            source = str(oracle.get("source") or "none")
            if not legacy_unpinned and source == "task":
                acceptance = await asyncio.to_thread(
                    acceptance_module.evaluate_pinned_oracle,
                    oracle,
                    current["worktree_path"],
                )
                oracle_status = str(acceptance.get("status") or INCONCLUSIVE)
            elif not legacy_unpinned and source == "legacy_task":
                acceptance = await asyncio.to_thread(
                    acceptance_module.run_command,
                    str(oracle.get("command") or ""),
                    current["worktree_path"],
                )
                acceptance["command"] = str(oracle.get("command") or "")
                oracle_status = str(acceptance.get("status") or INCONCLUSIVE)
            elif not legacy_unpinned:
                acceptance = {
                    "status": PASSED,
                    "reason": "not_required",
                    "exit_code": 0,
                    "output": "",
                    "command": "",
                }
                oracle_status = "not_required"

            acceptance_blocks = (
                acceptance["status"] != PASSED
                if bool(oracle.get("required"))
                else acceptance["status"] in {FAILED, INCONCLUSIVE}
            )
            if acceptance_blocks:
                code = (
                    "ACCEPTANCE_FAILED"
                    if acceptance["status"] == FAILED
                    else "ACCEPTANCE_INCONCLUSIVE"
                )
                error = _error(
                    code,
                    (
                        f"Platform acceptance {acceptance['status']}"
                        f" ({acceptance.get('reason') or 'exit_nonzero'}): "
                        f"{(acceptance.get('output') or '')[-400:]}"
                    ),
                    operation_id=operation_id,
                    status=409,
                    retryable=acceptance["status"] == INCONCLUSIVE,
                )
                result = _base_result(
                    operation_id,
                    "FAILED",
                    target_branch=str(target.get("branch") or ""),
                    worker_branch=record["accepted_worker_branch"],
                    worker_head=record["accepted_worker_head"],
                    error=error,
                    next_action=_action(
                        "FIX_ACCEPTANCE_THEN_RETRY",
                        "Fix the registered acceptance command, then start a new merge.",
                    ),
                )
                result["acceptance"] = acceptance
                result["admission"] = _admission_evidence(
                    admission, oracle_status=oracle_status,
                )
            else:
                from app.merge_test_gate import describe_progress, evaluate_test_gate

                test_gate = await asyncio.to_thread(
                    evaluate_test_gate,
                    current["worktree_path"],
                    target_ref=str(target.get("branch") or ""),
                    target_sha=str(target.get("sha") or ""),
                )
                strict_mapped = bool(oracle.get("required"))
                gate_blocks = test_gate["status"] in {FAILED, INCONCLUSIVE} or (
                    strict_mapped and test_gate["status"] != PASSED
                )
                if gate_blocks:
                    code = (
                        "TEST_GATE_FAILED"
                        if test_gate["status"] == FAILED
                        else "TEST_GATE_INCONCLUSIVE"
                    )
                    # Учёт дописывается ПОСЛЕ хвоста выхода: получатель видит `[-400:]`,
                    # то есть конец строки, — сводка в начале до него не доехала бы.
                    progress = describe_progress(test_gate)
                    error = _error(
                        code,
                        (
                            f"Merge test gate {test_gate['status']}"
                            f" ({test_gate.get('reason') or 'exit_nonzero'}): "
                            f"{(test_gate.get('output') or '')[-400:]}"
                            + (f" — {progress}" if progress else "")
                        ),
                        operation_id=operation_id,
                        status=409,
                        retryable=test_gate["status"] in {INCONCLUSIVE, SKIPPED},
                    )
                    # Разные исходы требуют разных действий, и раньше оба получали
                    # «Fix the failing merge-gate tests» — для незавершённого прогона это
                    # прямая ложь (чинить нечего), из-за которой #329 смержили руками.
                    next_action = (
                        _action(
                            "FIX_TESTS_THEN_RETRY",
                            "Fix the failing merge-gate tests, then start a new merge.",
                        )
                        if test_gate["status"] == FAILED
                        else _action(
                            "TEST_GATE_UNFINISHED",
                            "No test was reported red — the gate ran out of its time "
                            "budget. Do NOT 'fix' tests. Retry the same operation; if it "
                            "keeps running out, the mapped subset costs more than the "
                            "gate budget and the merge needs an explicit decision.",
                        )
                    )
                    result = _base_result(
                        operation_id,
                        "FAILED",
                        target_branch=str(target.get("branch") or ""),
                        worker_branch=record["accepted_worker_branch"],
                        worker_head=record["accepted_worker_head"],
                        error=error,
                        next_action=next_action,
                    )
                    result["acceptance"] = acceptance
                    result["test_gate"] = test_gate
                    result["admission"] = _admission_evidence(
                        admission,
                        oracle_status=oracle_status,
                        mapped_files=list(test_gate.get("mapped_files") or []),
                    )
                else:
                    from app.routes.sessions import execute_merge_session

                    raw = await execute_merge_session(
                        session_id=record["session_id"],
                        expected_name=record["worker_name"],
                        expected_scope=record["scope"],
                        expected_branch=record["accepted_worker_branch"],
                        expected_head=record["accepted_worker_head"],
                        expected_target_head=str(target.get("sha") or ""),
                        req={
                            **record["request"],
                            "operation_id": operation_id,
                            "target": str(target.get("branch") or ""),
                        },
                    )
                    if isinstance(raw, dict) and raw.get("finalization_checkpoint_lost"):
                        raw = await asyncio.to_thread(
                            _recover_lost_checkpoint, operation_id, raw,
                        )
                    from app.ia import merge_receipts

                    if (
                        merge_receipts.merge_receipt_configured()
                        and isinstance(raw, dict)
                        and raw.get("ok")
                    ):
                        try:
                            durable_receipt = merge_receipts.get_merge_receipt(operation_id)
                            if (
                                durable_receipt is None
                                or durable_receipt != raw.get("receipt")
                            ):
                                raise merge_receipts.MergeReceiptError(
                                    "successful merge has no matching durable receipt"
                                )
                        except merge_receipts.MergeReceiptError as exc:
                            raw = {
                                **raw,
                                "ok": False,
                                "state": (
                                    "partial"
                                    if raw.get("commit_point") == "target_committed"
                                    else "failed"
                                ),
                                "error": f"verified merge receipt missing: {exc}",
                            }
                            raw.pop("receipt", None)
                    from app import rag_service

                    result = normalize_merge_result(
                        operation_id,
                        raw,
                        record["request"],
                        rag_enabled=rag_service.is_enabled(),
                    )
                    result["acceptance"] = acceptance
                    result["test_gate"] = test_gate
                    result["admission"] = _admission_evidence(
                        admission,
                        oracle_status=oracle_status,
                        mapped_files=list(test_gate.get("mapped_files") or []),
                        target_recheck=(
                            raw.get("target_recheck")
                            if isinstance(raw, dict) else None
                        ),
                    )
        if record.get("accepted_admission") and "admission" not in result:
            result["admission"] = _admission_evidence(
                record["accepted_admission"], oracle_status="not_run",
            )
        try:
            terminal = await asyncio.to_thread(_session_snapshot, record["session_id"])
        except Exception as exc:
            terminal = None
            _mark_terminal_snapshot_failure(result, operation_id, exc)
        stored = await asyncio.to_thread(
            finish_operation, operation_id, owner_token, result, terminal,
        )
        if not stored:
            logger.error("merge operation result CAS failed operation_id=%s", operation_id)
    except asyncio.CancelledError:
        logger.warning(
            "merge operation runner cancelled operation_id=%s; RUNNING remains for restart quarantine",
            operation_id,
        )
        raise
    except BaseException as exc:
        logger.exception("merge operation crashed operation_id=%s", operation_id)
        record = await asyncio.to_thread(get_operation_record, operation_id) or record
        result = _unknown_from_record(
            record,
            f"Merge operation crashed: {err_text(exc)}",
            exception_type=type(exc).__name__,
        )
        try:
            terminal = await asyncio.to_thread(_session_snapshot, record["session_id"])
        except Exception:
            terminal = None
        await asyncio.to_thread(
            finish_operation, operation_id, owner_token, result, terminal,
        )


def _observe_runner(task: asyncio.Task[None]) -> None:
    for operation_id, current in list(_runner_tasks.items()):
        if current is task:
            _runner_tasks.pop(operation_id, None)
            break
    if task.cancelled():
        return
    try:
        task.result()
    except Exception:
        logger.exception("unobserved merge operation runner failure")


def ensure_operation_runner(operation_id: str) -> None:
    current = _runner_tasks.get(operation_id)
    if current is not None and not current.done():
        return
    task = asyncio.create_task(
        _run_operation(operation_id), name=f"merge-operation:{operation_id}",
    )
    _runner_tasks[operation_id] = task
    task.add_done_callback(_observe_runner)


async def accept_merge_operation(
    *,
    operation_id: str,
    name: str,
    scope: str,
    target: str = "",
    next_task_id: str = "",
    waive_diff_budget: bool = False,
    waived_by: str = "",
    task_outcome: str = "",
    merge_schema_version: int | None = None,
) -> tuple[dict[str, Any], int]:
    request = normalize_request(
        name=name,
        scope=scope,
        target=target,
        next_task_id=next_task_id,
        waive_diff_budget=waive_diff_budget,
        waived_by=waived_by,
        task_outcome=task_outcome,
        merge_schema_version=merge_schema_version,
    )
    try:
        canonical_id = _operation_id(operation_id)
    except (ValueError, AttributeError):
        error = _error(
            "INVALID_OPERATION_ID", "operation_id must be a UUID",
            operation_id=operation_id, status=400,
            details={"exception_type": "ValueError"},
        )
        return _base_result(operation_id, "FAILED", error=error), 400

    existing = await asyncio.to_thread(get_operation_record, canonical_id)
    digest = request_hash(request)
    if existing:
        if existing["request_hash"] != digest:
            return _idempotency_conflict(canonical_id, existing, digest), 409
        if existing["state"] == "PENDING":
            ensure_operation_runner(canonical_id)
        if existing["state"] in {"PENDING", "RUNNING"}:
            return existing["result"], 202
        if (
            existing["state"] == "PARTIAL"
            and existing["finalization_stage"] == "PENDING"
            and existing["commit_point"] == "REACHED"
        ):
            # Отдельно от drift-проверки и ДО неё: воркер уже не там, где его приняли,
            # ровно потому, что этот мерж его подвинул. Замороженный payload описывает
            # смерженный коммит и от текущего состояния воркера не зависит.
            if await asyncio.to_thread(_reopen_for_finalization, canonical_id):
                ensure_operation_runner(canonical_id)
                refreshed = await asyncio.to_thread(get_operation_record, canonical_id)
                return (refreshed or existing)["result"], 202
        # Терминальную запись отдавать дословно можно только если воркер ВСЁ ЕЩЁ там,
        # где его приняли. request_hash состояние воркера не покрывает (в него входят
        # только name/scope/target/next_task_id), поэтому переезд на другую ветку хеш
        # не меняет — и агент, повторяющий с тем же operation_id по инструкции тула,
        # получает отчёт о чужой ветке как о своей (#166).
        drifted = await asyncio.to_thread(_replay_drift, existing)
        if drifted is not None:
            return drifted, 409
        return existing["result"], 200

    row = await asyncio.to_thread(get_session_by_name, request["name"], request["scope"])
    if not row:
        error = _error(
            "SESSION_NOT_FOUND",
            f"worker '{request['name']}' not found in scope '{request['scope']}'",
            operation_id=canonical_id, status=404,
        )
        return _base_result(canonical_id, "FAILED", error=error), 404
    try:
        accepted = await asyncio.to_thread(_session_snapshot, row["id"])
    except Exception as exc:
        error = _error(
            "SESSION_SNAPSHOT_FAILED",
            f"Cannot snapshot worker before merge: {err_text(exc)}",
            operation_id=canonical_id, status=409,
            details={"exception_type": type(exc).__name__},
        )
        return _base_result(
            canonical_id, "FAILED",
            target_branch=request["target"], worker_branch=row.get("branch") or "",
            error=error,
        ), 409
    try:
        accepted["admission"] = await asyncio.to_thread(
            _prepare_admission_snapshot, accepted, request,
        )
    except Exception as exc:
        reason = getattr(exc, "reason", "")
        code = "ORACLE_MISSING" if reason == "oracle_missing" else "ORACLE_METADATA_INVALID"
        error = _error(
            code,
            str(exc),
            operation_id=canonical_id,
            status=409,
            details={"exception_type": type(exc).__name__},
        )
        return _base_result(
            canonical_id,
            "FAILED",
            target_branch=request["target"] or accepted.get("base_branch", ""),
            worker_branch=accepted["worker_branch"],
            worker_head=accepted["worker_head"],
            error=error,
            next_action=_action(
                "FIX_ORACLE_THEN_NEW_OPERATION",
                "Repair the authoritative task oracle or target, then start a new operation.",
            ),
        ), 409
    result, _created, status = await asyncio.to_thread(
        accept_operation_snapshot,
        operation_id=canonical_id,
        request=request,
        accepted=accepted,
    )
    if result["operation_state"] == "PENDING":
        ensure_operation_runner(result["operation_id"])
    return result, status


async def restore_merge_operations() -> None:
    pending = await asyncio.to_thread(recover_orphan_operations)
    for operation_id in pending:
        ensure_operation_runner(operation_id)


async def shutdown_merge_operations() -> None:
    tasks = list(_runner_tasks.values())
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    _runner_tasks.clear()
