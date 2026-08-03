"""Durable, idempotent merge operations above the pinned session merge entry point."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any

from app.db import _conn, get_session, get_session_by_name

logger = logging.getLogger("orchestra.merge_operations")

ACTIVE_STATES = ("PENDING", "RUNNING", "PARTIAL", "UNKNOWN")
TERMINAL_STATES = ("SUCCEEDED", "PARTIAL", "FAILED", "UNKNOWN")
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
        "next_action": next_action or _action(
            "CHECK_SAME_OPERATION",
            f"Check operation {operation_id}; do not merge manually.",
        ),
    }


def normalize_request(
    *, name: str, scope: str, target: str = "", next_task_id: str = "",
) -> dict[str, Any]:
    return {
        "name": name.strip(),
        "scope": scope.rstrip("/"),
        "target": target.strip(),
        "next_task_id": next_task_id.strip(),
        "squash": True,
    }


def request_hash(request: dict[str, Any]) -> str:
    return _hash(request)


def _operation_id(value: str) -> str:
    return str(uuid.UUID(value))


def _decode_record(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    record = dict(row)
    record["request"] = json.loads(record.pop("request_json"))
    record["result"] = json.loads(record.pop("result_json"))
    return record


def get_operation_record(operation_id: str) -> dict[str, Any] | None:
    with _conn() as connection:
        row = connection.execute(
            "SELECT * FROM merge_operations WHERE operation_id=?", (operation_id,),
        ).fetchone()
    return _decode_record(row) if row else None


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
    row: sqlite3.Row, accepted: dict[str, Any],
) -> bool:
    return (
        row["terminal_worker_branch"] == accepted["worker_branch"]
        and row["terminal_worker_head"] == accepted["worker_head"]
        and row["terminal_base_branch"] == accepted["base_branch"]
        and row["terminal_task_id"] == accepted["task_id"]
        and bool(row["terminal_needs_switch"]) == accepted["needs_switch"]
    )


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
            active = _decode_record(active_row)
            state = active["state"]
            return active["result"], False, 202 if state in {"PENDING", "RUNNING"} else 200

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
        try:
            connection.execute(
                """INSERT INTO merge_operations (
                       operation_id, operation_type, session_id, scope, worker_name,
                       request_json, request_hash, dedupe_fingerprint,
                       accepted_worker_branch, accepted_worker_head,
                       accepted_base_branch, accepted_task_id, accepted_needs_switch,
                       state, commit_point, result_json, result_hash,
                       created_at, updated_at
                   ) VALUES (?, 'merge', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
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
            active = _decode_record(active_row)
            state = active["state"]
            return active["result"], False, 202 if state in {"PENDING", "RUNNING"} else 200
    return result, True, 202


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


def _verify_accepted_snapshot(record: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
    try:
        current = _session_snapshot(record["session_id"])
    except Exception as exc:
        return None, _text(exc, type(exc).__name__)
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


def _link_status(items: Any) -> tuple[str, dict[str, Any], list[str]]:
    if not isinstance(items, dict) or not items:
        return "NOT_RUN", {}, []
    normalized: dict[str, Any] = {}
    successes = 0
    failures: list[str] = []
    for task_ref, info in items.items():
        normalized[str(task_ref)] = info
        ok = isinstance(info, dict) and bool(info.get("ok") or info.get("id"))
        if ok:
            successes += 1
        else:
            detail = info.get("error") if isinstance(info, dict) else "invalid link result"
            failures.append(f"{task_ref}: {_text(detail, 'link failed without detail')}")
    if not failures:
        return "SUCCEEDED", normalized, []
    return ("PARTIAL" if successes else "FAILED"), normalized, failures


def _classify_failure(raw: dict[str, Any], message: str) -> tuple[str, dict[str, Any], dict[str, str]]:
    lower = message.lower()
    details: dict[str, Any] = {
        "upstream_state": raw.get("state"),
        "normalization": "LEGACY_UPSTREAM_ERROR",
    }
    if raw.get("conflicts"):
        details["paths"] = list(raw["conflicts"])
        return "CONFLICT", details, _action(
            "RESOLVE_ON_WORKER_THEN_NEW_OPERATION",
            "Resolve and commit the conflict on the worker branch, then start a new operation; do not merge the target manually.",
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
    elif "working tree is dirty" in message.lower():
        git_status = "DIRTY"
    elif commit_point == "UNKNOWN":
        git_status = "UNKNOWN"
    else:
        git_status = "FAILED"

    link_status, link_items, link_failures = _link_status(raw.get("linked_tasks"))
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
        next_action = _action(
            "RECONCILE_SAME_OPERATION",
            "Reconcile this operation before any retry; do not merge manually.",
        )
    elif raw_state == "partial" or commit_point == "REACHED" and (not raw.get("ok") or stage_failures):
        state = "PARTIAL"
        code, detail = stage_failures[0] if stage_failures else ("POST_COMMIT_PARTIAL", message)
        retryable = code == "RAG_NOT_READY"
        error = _error(
            code, detail, operation_id=operation_id,
            status=raw.get("_http_status"), retryable=retryable,
            details={"failed_stages": [item[0] for item in stage_failures]},
        )
        next_action = _action(
            "FINALIZE_SAME_OPERATION",
            "Finalize this operation; do not repeat or manually apply the Git merge.",
        )
    elif raw.get("ok") and not stage_failures:
        state = "SUCCEEDED"
    else:
        state = "FAILED"
        code, details, next_action = _classify_failure(raw, message)
        error = _error(
            code, message, operation_id=operation_id,
            status=raw.get("_http_status"), details=details,
        )

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
        "next_action": next_action,
    }
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
    now = _now()
    with _conn() as connection:
        cursor = connection.execute(
            """UPDATE merge_operations
               SET state=?, commit_point=?, result_json=?, result_hash=?,
                   terminal_worker_branch=?, terminal_worker_head=?,
                   terminal_base_branch=?, terminal_task_id=?, terminal_needs_switch=?,
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
    result["next_action"] = _action(
        "RECONCILE_SAME_OPERATION",
        "Reconcile this operation before any retry; do not merge manually.",
    )
    return result


def _mark_terminal_snapshot_failure(
    result: dict[str, Any], operation_id: str, exc: BaseException,
) -> None:
    if result["commit_point"] != "REACHED":
        return
    detail = f"Cannot verify terminal worker state: {type(exc).__name__}: {_text(exc, type(exc).__name__)}"
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
    result["next_action"] = _action(
        "FINALIZE_SAME_OPERATION",
        "Verify and finalize this operation; do not repeat or manually apply the Git merge.",
    )


def recover_orphan_operations() -> list[str]:
    """Mark orphan RUNNING rows unknown and return restartable PENDING ids."""
    pending: list[str] = []
    now = _now()
    with _conn() as connection:
        connection.execute("BEGIN IMMEDIATE")
        running = connection.execute(
            "SELECT * FROM merge_operations WHERE state='RUNNING'"
        ).fetchall()
        for row in running:
            record = _decode_record(row)
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
                (_json(result), _hash(result), now, now, record["operation_id"]),
            )
        pending = [
            row["operation_id"] for row in connection.execute(
                "SELECT operation_id FROM merge_operations WHERE state='PENDING'"
            ).fetchall()
        ]
    return pending


async def _run_operation(operation_id: str) -> None:
    owner_token = str(uuid.uuid4())
    claimed = await asyncio.to_thread(claim_operation, operation_id, owner_token)
    if not claimed:
        return
    record = await asyncio.to_thread(get_operation_record, operation_id)
    if not record:
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
            from app.routes.sessions import execute_merge_session

            raw = await execute_merge_session(
                session_id=record["session_id"],
                expected_name=record["worker_name"],
                expected_scope=record["scope"],
                expected_branch=record["accepted_worker_branch"],
                expected_head=record["accepted_worker_head"],
                req={
                    **record["request"],
                    "target": (
                        record["request"].get("target")
                        or record["accepted_base_branch"]
                    ),
                },
            )
            from app import rag_service

            result = normalize_merge_result(
                operation_id,
                raw,
                record["request"],
                rag_enabled=rag_service.is_enabled(),
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
            f"Merge operation crashed: {type(exc).__name__}: {_text(exc, type(exc).__name__)}",
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
) -> tuple[dict[str, Any], int]:
    request = normalize_request(
        name=name, scope=scope, target=target, next_task_id=next_task_id,
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
        return existing["result"], 202 if existing["state"] in {"PENDING", "RUNNING"} else 200

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
            f"Cannot snapshot worker before merge: {type(exc).__name__}: {_text(exc, type(exc).__name__)}",
            operation_id=canonical_id, status=409,
            details={"exception_type": type(exc).__name__},
        )
        return _base_result(
            canonical_id, "FAILED",
            target_branch=request["target"], worker_branch=row.get("branch") or "",
            error=error,
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
