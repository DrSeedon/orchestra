# Context for item-28

## Diff reviewed (-U20, capped at 1500 lines)

diff --git a/app/ia/merge_receipts.py b/app/ia/merge_receipts.py
new file mode 100644
index 000000000..400bd2587
--- /dev/null
+++ b/app/ia/merge_receipts.py
@@ -0,0 +1,428 @@
+"""Content-bound, durable receipts for task-aware merge operations."""
+
+from __future__ import annotations
+
+import copy
+import json
+import re
+import uuid
+from collections.abc import Callable, Iterator, Mapping
+from contextlib import contextmanager
+from contextvars import ContextVar
+from dataclasses import dataclass
+from datetime import datetime, timezone
+from pathlib import Path
+from typing import Any
+
+
+class MergeReceiptError(RuntimeError):
+    """Raised when a merge receipt is absent, forged, or cannot be made durable."""
+
+
+_SHA40 = re.compile(r"[0-9a-f]{40}")
+_SHA256 = re.compile(r"sha256:[0-9a-f]{64}")
+_HEX256 = re.compile(r"[0-9a-f]{64}")
+_EVIDENCE_URI = re.compile(
+    r"orch://project/(?P<project>[a-z0-9][a-z0-9._-]*)/tasks/"
+    r"(?P<task>[0-9a-f-]{36})/evidence/(?P<evidence>[0-9a-f-]{36})"
+)
+
+
+@dataclass(frozen=True)
+class _ReceiptContext:
+    canonical_root: Path
+    task_resolver: Callable[[Mapping[str, Any]], Mapping[str, Any]]
+    evidence_resolver: Callable[[Mapping[str, Any]], Mapping[str, Any]]
+    head_resolver: Callable[[], Mapping[str, Any]]
+    receipt_writer: Callable[[Path, Mapping[str, Any]], Any] | None
+
+
+_ACTIVE_RECEIPTS: ContextVar[_ReceiptContext | None] = ContextVar(
+    "ia_merge_receipts", default=None,
+)
+
+
+def _canonical_bytes(value: Any) -> bytes:
+    try:
+        return json.dumps(
+            value,
+            ensure_ascii=False,
+            separators=(",", ":"),
+            sort_keys=True,
+            allow_nan=False,
+        ).encode("utf-8")
+    except (TypeError, ValueError) as exc:
+        raise MergeReceiptError("merge receipt is not canonical JSON") from exc
+
+
+def _detached(value: Any) -> Any:
+    return json.loads(_canonical_bytes(value))
+
+
+def _read_json(path: Path) -> dict[str, Any]:
+    try:
+        value = json.loads(path.read_text(encoding="utf-8"))
+    except (OSError, json.JSONDecodeError) as exc:
+        raise MergeReceiptError(f"cannot read durable merge receipt: {path}") from exc
+    if not isinstance(value, dict):
+        raise MergeReceiptError("durable merge receipt is not an object")
+    return value
+
+
+def _write_json(path: Path, value: Mapping[str, Any]) -> None:
+    path.parent.mkdir(parents=True, exist_ok=True)
+    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
+    try:
+        temporary.write_bytes(_canonical_bytes(value) + b"\n")
+        temporary.replace(path)
+    finally:
+        temporary.unlink(missing_ok=True)
+
+
+def _context() -> _ReceiptContext:
+    context = _ACTIVE_RECEIPTS.get()
+    if context is None:
+        raise MergeReceiptError("merge receipt owner is not configured")
+    return context
+
+
+@contextmanager
+def merge_receipt_mode(
+    *,
+    canonical_root: Path,
+    task_resolver: Callable[[Mapping[str, Any]], Mapping[str, Any]],
+    evidence_resolver: Callable[[Mapping[str, Any]], Mapping[str, Any]],
+    head_resolver: Callable[[], Mapping[str, Any]],
+    receipt_writer: Callable[[Path, Mapping[str, Any]], Any] | None = None,
+) -> Iterator[None]:
+    """Temporarily configure the canonical receipt owner and its resolvers."""
+
+    context = _ReceiptContext(
+        canonical_root=Path(canonical_root),
+        task_resolver=task_resolver,
+        evidence_resolver=evidence_resolver,
+        head_resolver=head_resolver,
+        receipt_writer=receipt_writer,
+    )
+    token = _ACTIVE_RECEIPTS.set(context)
+    try:
+        yield
+    finally:
+        _ACTIVE_RECEIPTS.reset(token)
+
+
+def merge_receipt_configured() -> bool:
+    """Return whether this execution context requires durable merge receipts."""
+
+    return _ACTIVE_RECEIPTS.get() is not None
+
+
+def _receipt_paths(operation_id: str) -> list[Path]:
+    context = _ACTIVE_RECEIPTS.get()
+    if context is None:
+        return []
+    return sorted(context.canonical_root.rglob(f"merge-receipts/{operation_id}.json"))
+
+
+def get_merge_receipt(operation_id: str) -> dict[str, Any] | None:
+    """Load the one durable receipt for an operation, if it exists."""
+
+    paths = _receipt_paths(str(operation_id))
+    if not paths:
+        return None
+    if len(paths) != 1:
+        raise MergeReceiptError(
+            f"operation '{operation_id}' has {len(paths)} durable merge receipts"
+        )
+    return verify_merge_receipt(_read_json(paths[0]), operation_id=str(operation_id))
+
+
+def _mapping(value: Any, name: str) -> dict[str, Any]:
+    if not isinstance(value, Mapping):
+        raise MergeReceiptError(f"receipt {name} must be an object")
+    return _detached(dict(value))
+
+
+def _equal(actual: Any, expected: Any, name: str) -> None:
+    if expected is not None and actual != expected:
+        raise MergeReceiptError(f"receipt {name} does not match its pinned source")
+
+
+def verify_merge_receipt(
+    receipt: Mapping[str, Any],
+    *,
+    operation_id: str = "",
+    target: Mapping[str, Any] | None = None,
+    worker: Mapping[str, Any] | None = None,
+    task: Mapping[str, Any] | None = None,
+    evidence: Mapping[str, Any] | None = None,
+    heads: Mapping[str, Any] | None = None,
+    acceptance: Mapping[str, Any] | None = None,
+) -> dict[str, Any]:
+    """Validate a receipt and optional independently pinned bindings."""
+
+    value = _mapping(receipt, "root")
+    required = {
+        "schema_version", "receipt_id", "receipt_status", "operation_id",
+        "target", "worker", "task", "evidence", "heads", "acceptance",
+        "created_at",
+    }
+    missing = sorted(required - value.keys())
+    if missing:
+        raise MergeReceiptError(f"merge receipt is incomplete: {', '.join(missing)}")
+    if value["schema_version"] != 1 or value["receipt_status"] != "verified":
+        raise MergeReceiptError("merge receipt is not a verified schema-v1 receipt")
+    try:
+        canonical_operation = str(uuid.UUID(str(value["operation_id"])))
+        canonical_receipt = str(uuid.UUID(str(value["receipt_id"])))
+    except (ValueError, AttributeError) as exc:
+        raise MergeReceiptError("merge receipt identities must be canonical UUIDs") from exc
+    if canonical_operation != value["operation_id"] or canonical_receipt != value["receipt_id"]:
+        raise MergeReceiptError("merge receipt identities must be canonical UUIDs")
+    if operation_id and canonical_operation != str(operation_id):
+        raise MergeReceiptError("merge receipt belongs to another operation")
+
+    target_value = _mapping(value["target"], "target")
+    worker_value = _mapping(value["worker"], "worker")
+    task_value = _mapping(value["task"], "task")
+    evidence_value = _mapping(value["evidence"], "evidence")
+    heads_value = _mapping(value["heads"], "heads")
+    acceptance_value = _mapping(value["acceptance"], "acceptance")
+    for name in ("before", "commit"):
+        if _SHA40.fullmatch(str(target_value.get(name) or "")) is None:
+            raise MergeReceiptError(f"receipt target.{name} is not a commit")
+    if target_value["before"] == target_value["commit"]:
+        raise MergeReceiptError("merge receipt does not describe a target commit")
+    if _SHA40.fullmatch(str(worker_value.get("head") or "")) is None:
+        raise MergeReceiptError("receipt worker.head is not a commit")
+
+    try:
+        stable_id = str(uuid.UUID(str(task_value["stable_id"])))
+        display_number = int(task_value["display_number"])
+        task_id = int(task_value["task_id"])
+    except (KeyError, TypeError, ValueError, AttributeError) as exc:
+        raise MergeReceiptError("receipt task identity is invalid") from exc
+    if (
+        stable_id != task_value["stable_id"]
+        or task_value.get("display_ref") != f"#{display_number}"
+    ):
+        raise MergeReceiptError("receipt task stable/display identity is inconsistent")
+    if task_id < 1 or display_number < 1 or not str(task_value.get("project_id") or ""):
+        raise MergeReceiptError("receipt task identity is incomplete")
+
+    uri = str(evidence_value.get("manifest_uri") or "")
+    uri_match = _EVIDENCE_URI.fullmatch(uri)
+    if (
+        uri_match is None
+        or uri_match.group("project") != task_value["project_id"]
+        or uri_match.group("task") != stable_id
+    ):
+        raise MergeReceiptError("receipt evidence URI is not bound to the task")
+    for name in ("manifest_head", "manifest_sha256"):
+        if _SHA256.fullmatch(str(evidence_value.get(name) or "")) is None:
+            raise MergeReceiptError(f"receipt evidence.{name} is invalid")
+    if int(evidence_value.get("count") or 0) < 1:
+        raise MergeReceiptError("receipt evidence manifest is empty")
+
+    for name in ("canonical_head", "projection_head", "indexed_head"):
+        if _SHA256.fullmatch(str(heads_value.get(name) or "")) is None:
+            raise MergeReceiptError(f"receipt heads.{name} is invalid")
+    if heads_value["projection_head"] != heads_value["canonical_head"]:
+        raise MergeReceiptError("current projection is not bound to the canonical head")
+
+    try:
+        revision = int(acceptance_value["revision"])
+        manifest_count = int(acceptance_value["manifest_count"])
+    except (KeyError, TypeError, ValueError) as exc:
+        raise MergeReceiptError("receipt acceptance identity is invalid") from exc
+    if revision < 1 or manifest_count < 1:
+        raise MergeReceiptError("receipt acceptance manifest is empty")
+    if _HEX256.fullmatch(str(acceptance_value.get("oracle_hash") or "")) is None:
+        raise MergeReceiptError("receipt acceptance oracle hash is invalid")
+    if manifest_count != int(evidence_value["count"]):
+        raise MergeReceiptError("receipt acceptance/evidence counts disagree")
+
+    _equal(target_value, _detached(target) if target is not None else None, "target")
+    _equal(worker_value, _detached(worker) if worker is not None else None, "worker")
+    _equal(task_value, _detached(task) if task is not None else None, "task")
+    _equal(evidence_value, _detached(evidence) if evidence is not None else None, "evidence")
+    _equal(heads_value, _detached(heads) if heads is not None else None, "heads")
+    _equal(
+        acceptance_value,
+        _detached(acceptance) if acceptance is not None else None,
+        "acceptance",
+    )
+    return copy.deepcopy(value)
+
+
+def _task_binding(finalization: Mapping[str, Any]) -> dict[str, Any]:
+    task = _mapping(finalization.get("task"), "finalization task")
+    try:
+        return {
+            "project_id": str(finalization.get("project_id") or task["project_id"]),
+            "stable_id": str(task["stable_id"]),
+            "task_id": int(task["task_id"]),
+            "display_number": int(task["par_number"]),
+            "display_ref": f"#{int(task['par_number'])}",
+        }
+    except (KeyError, TypeError, ValueError) as exc:
+        raise MergeReceiptError("merge finalization lacks a stable task binding") from exc
+
+
+def _canonical_evidence(evidence: Mapping[str, Any]) -> None:
+    context = _context()
+    expected = _detached(evidence)
+    matches: list[dict[str, Any]] = []
+    for path in sorted(context.canonical_root.rglob("*.json")):
+        if "merge-receipts" in path.parts:
+            continue
+        try:
+            candidate = json.loads(path.read_text(encoding="utf-8"))
+        except (OSError, json.JSONDecodeError):
+            continue
+        if (
+            isinstance(candidate, dict)
+            and candidate.get("manifest_uri") == expected["manifest_uri"]
+        ):
+            matches.append(candidate)
+    if len(matches) != 1:
+        raise MergeReceiptError(
+            f"evidence manifest URI resolves to {len(matches)} canonical records"
+        )
+    for name, expected_value in expected.items():
+        if matches[0].get(name) != expected_value:
+            raise MergeReceiptError(f"canonical evidence {name} does not match resolver")
+
+
+def _bindings(
+    operation_id: str,
+    merge_result: Mapping[str, Any],
+    finalization: Mapping[str, Any],
+) -> dict[str, dict[str, Any]]:
+    from app.merge_operations import get_operation_record
+
+    record = get_operation_record(operation_id)
+    if record is None:
+        raise MergeReceiptError(f"merge operation '{operation_id}' is not durable")
+    admission = _mapping(record.get("accepted_admission"), "accepted admission")
+    admitted_target = _mapping(admission.get("target"), "admitted target")
+    oracle = _mapping(admission.get("oracle"), "accepted oracle")
+    if str(oracle.get("source") or "") != "task" or not oracle.get("required"):
+        raise MergeReceiptError("verified receipts require an authoritative task oracle")
+
+    task = _mapping(_context().task_resolver(finalization), "resolved task")
+    expected_task = _task_binding(finalization)
+    if task != expected_task:
+        raise MergeReceiptError("resolved task does not match prepared merge finalization")
+    if str(oracle.get("task_id") or "") != str(task["display_number"]):
+        raise MergeReceiptError("accepted oracle is bound to another task")
+    evidence = _mapping(_context().evidence_resolver(task), "resolved evidence")
+    heads = _mapping(_context().head_resolver(), "resolved heads")
+    _canonical_evidence(evidence)
+
+    target_recheck = _mapping(merge_result.get("target_recheck"), "target recheck")
+    target = {
+        "branch": str(merge_result.get("target_branch") or ""),
+        "before": str(merge_result.get("target_before") or ""),
+        "commit": str(merge_result.get("target_after") or ""),
+    }
+    worker = {
+        "branch": str(record.get("accepted_worker_branch") or ""),
+        "head": str(record.get("accepted_worker_head") or ""),
+    }
+    acceptance = {
+        "revision": int(oracle.get("revision") or 0),
+        "oracle_hash": str(oracle.get("hash") or ""),
+        "manifest_count": len(oracle.get("manifest") or []),
+    }
+    if not merge_result.get("ok") or merge_result.get("commit_point") != "target_committed":
+        raise MergeReceiptError("target commit is not proven successful")
+    if (
+        target["branch"] != admitted_target.get("branch")
+        or target["before"] != admitted_target.get("sha")
+    ):
+        raise MergeReceiptError("merge target differs from accepted target")
+    if (
+        target_recheck.get("matched") is not True
+        or target_recheck.get("expected") != admitted_target.get("sha")
+        or target_recheck.get("actual") != admitted_target.get("sha")
+    ):
+        raise MergeReceiptError("target admission was not reverified under the repository lock")
+    if (
+        str(merge_result.get("worker_branch") or "") != worker["branch"]
+        or str(merge_result.get("worker_head") or "") != worker["head"]
+        or str(finalization.get("worker_head") or "") != worker["head"]
+    ):
+        raise MergeReceiptError("merged worker head differs from the accepted head")
+    if str(merge_result.get("head_drift") or "SAME") != "SAME":
+        raise MergeReceiptError("accepted worker head drifted before the merge boundary")
+    return {
+        "target": target,
+        "worker": worker,
+        "task": task,
+        "evidence": evidence,
+        "heads": heads,
+        "acceptance": acceptance,
+    }
+
+
+def record_merge_receipt(
+    operation_id: str,
+    merge_result: Mapping[str, Any],
+    finalization: Mapping[str, Any],
+) -> dict[str, Any]:
+    """Create-or-read the verified receipt before any finalization or cleanup."""
+
+    context = _context()
+    bindings = _bindings(operation_id, merge_result, finalization)
+    task = bindings["task"]
+    path = (
+        context.canonical_root
+        / "projects" / task["project_id"]
+        / "tasks" / task["stable_id"]
+        / "merge-receipts" / f"{operation_id}.json"
+    )
+    if path.exists():
+        return verify_merge_receipt(
+            _read_json(path), operation_id=operation_id, **bindings,
+        )
+    receipt = {
+        "schema_version": 1,
+        "receipt_id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"orch:merge-receipt:{operation_id}")),
+        "receipt_status": "verified",
+        "operation_id": operation_id,
+        **bindings,
+        "created_at": datetime.now(timezone.utc).isoformat(),
+    }
+    verified = verify_merge_receipt(receipt, operation_id=operation_id, **bindings)
+    try:
+        if context.receipt_writer is None:
+            _write_json(path, verified)
+        else:
+            path.parent.mkdir(parents=True, exist_ok=True)
+            context.receipt_writer(path, copy.deepcopy(verified))
+    except Exception as exc:
+        raise MergeReceiptError(
+            f"cannot persist merge receipt: {type(exc).__name__}: {exc}"
+        ) from exc
+    if not path.is_file():
+        raise MergeReceiptError("receipt writer returned without a durable receipt")
+    return verify_merge_receipt(
+        _read_json(path), operation_id=operation_id, **bindings,
+    )
+
+
+def require_merge_receipt(
+    operation_id: str,
+    *,
+    finalization: Mapping[str, Any] | None = None,
+) -> dict[str, Any]:
+    """Require the durable receipt before replaying task or lifecycle finalization."""
+
+    receipt = get_merge_receipt(operation_id)
+    if receipt is None:
+        raise MergeReceiptError(f"merge operation '{operation_id}' has no durable receipt")
+    if finalization is not None:
+        expected_task = _task_binding(finalization)
+        verify_merge_receipt(receipt, operation_id=operation_id, task=expected_task)
+    return receipt
diff --git a/app/merge_operations.py b/app/merge_operations.py
index e42efa14b..37c8a882e 100644
--- a/app/merge_operations.py
+++ b/app/merge_operations.py
@@ -1,25 +1,26 @@
 """Durable, idempotent merge operations above the pinned session merge entry point."""
 
 from __future__ import annotations
 
 import asyncio
+import copy
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
@@ -161,41 +162,73 @@ def request_hash(request: dict[str, Any]) -> str:
 
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
-    return _decode_record(row) if row else None
+    if not row:
+        return None
+    record = _decode_record(row)
+    from app.ia import merge_receipts
+
+    result = record["result"]
+    if (
+        merge_receipts.merge_receipt_configured()
+        and result.get("operation_state") == "SUCCEEDED"
+    ):
+        try:
+            durable = merge_receipts.get_merge_receipt(operation_id)
+            if durable is None or durable != result.get("receipt"):
+                raise merge_receipts.MergeReceiptError(
+                    "stored success is not bound to its durable receipt"
+                )
+        except merge_receipts.MergeReceiptError as exc:
+            result = copy.deepcopy(result)
+            result["operation_state"] = "PARTIAL"
+            result["retryable"] = False
+            result["error"] = _error(
+                "MERGE_RECEIPT_INVALID",
+                str(exc),
+                operation_id=operation_id,
+                details={"exception_type": type(exc).__name__},
+            )
+            result["next_action"] = _blocking_action(
+                "RECONCILE_SAME_OPERATION",
+                "The target may be committed, but its durable receipt is missing or invalid.",
+                operation_id,
+            )
+            record["result"] = result
+    return record
 
 
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
@@ -1128,40 +1161,42 @@ def normalize_merge_result(
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
+    if isinstance(raw.get("receipt"), dict):
+        result["receipt"] = copy.deepcopy(raw["receipt"])
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
@@ -1651,40 +1686,68 @@ async def _run_operation(operation_id: str) -> None:
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
+                    from app.ia import merge_receipts
+
+                    if (
+                        merge_receipts.merge_receipt_configured()
+                        and isinstance(raw, dict)
+                        and raw.get("ok")
+                    ):
+                        try:
+                            durable_receipt = merge_receipts.get_merge_receipt(operation_id)
+                            if (
+                                durable_receipt is None
+                                or durable_receipt != raw.get("receipt")
+                            ):
+                                raise merge_receipts.MergeReceiptError(
+                                    "successful merge has no matching durable receipt"
+                                )
+                        except merge_receipts.MergeReceiptError as exc:
+                            raw = {
+                                **raw,
+                                "ok": False,
+                                "state": (
+                                    "partial"
+                                    if raw.get("commit_point") == "target_committed"
+                                    else "failed"
+                                ),
+                                "error": f"verified merge receipt missing: {exc}",
+                            }
+                            raw.pop("receipt", None)
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
diff --git a/app/routes/sessions.py b/app/routes/sessions.py
index c926b2c7d..cf7987b17 100644
--- a/app/routes/sessions.py
+++ b/app/routes/sessions.py
@@ -1557,43 +1557,49 @@ async def _persist_lifecycle_quarantine(
             continue
         status = {"ok": True}
         if errors:
             status.update(recovered=True, warning="; ".join(errors))
         return status
     return {
         "ok": False,
         "error": "; ".join(errors) or "lifecycle quarantine persistence failed",
     }
 
 
 async def apply_merge_finalization(finalization: dict) -> dict:
     """Everything the platform owns AFTER the merge commit point.
 
     One owner for two callers: the merge that produced the commit, and a same-id replay
     that resumes a DB stage which never landed. Both must be able to run it, and running
     it twice must change nothing the second time.
     """
     from app import tm as _tm
     from app.db import get_session
+    from app.ia import merge_receipts
     from app.workspace import switch_worktree_branch
 
     session_id = finalization["session_id"]
+    operation_id = str(finalization.get("operation_id") or "")
+    if operation_id and merge_receipts.merge_receipt_configured():
+        merge_receipts.require_merge_receipt(
+            operation_id, finalization=finalization,
+        )
     applied = await asyncio.to_thread(_tm.finalize_merge_outcome, finalization)
     out: dict = {"linked_tasks": applied["links"]}
 
     row = await asyncio.to_thread(get_session, session_id)
     session = manager.get(session_id) or (manager._hydrate_row(row) if row else None)
     if session is None:
         out["lifecycle_status"] = {
             "ok": False, "error": f"session '{session_id}' disappeared before finalization",
         }
         return out
 
     terminal = finalization["terminal_session"]
     target = finalization["target_branch"]
     branch = getattr(session, "branch", "") or ""
     if terminal["task_id"]:
         new_branch = f"task-{terminal['task_id']}/{session.name}"
         try:
             switch = await asyncio.to_thread(
                 switch_worktree_branch,
                 session.worktree_path, new_branch, target, force=True,
@@ -1623,67 +1629,89 @@ async def apply_merge_finalization(finalization: dict) -> dict:
         session,
         branch=branch,
         base_branch=target,
         task_id=terminal["task_id"],
         needs_switch=bool(terminal["needs_switch"]),
     )
     return out
 
 
 async def _finalize_committed_merge(
     *,
     result: dict,
     finalization: dict,
     found,
     operation_id: str,
     row_scope: str,
     merged_commits: dict,
 ) -> dict:
     """Run the durable checkpoint and the DB stage of a merge that already committed."""
     from app import merge_operations as _ops
+    from app.ia import merge_receipts
     from app import rag_service
 
     finalization["commits"] = merged_commits
     finalization["target_after"] = result.get("target_after") or ""
     finalization["stage"] = "PENDING"
     if operation_id:
         try:
             await asyncio.to_thread(
                 _ops.checkpoint_merge_commit, operation_id, finalization,
             )
         except Exception as error:
             # Первая запись после Git И ЕСТЬ журнал. Потеряли её — состояние БД неизвестно,
             # и восстанавливать его надо из репозитория (trailer + parent + tree), а не
             # повторной попыткой: повтор не отличить от второго мержа.
             detail = err_text(error)
             logger.error(
                 "merge checkpoint lost operation_id=%s: %s", operation_id, detail,
             )
             result.update(
                 ok=False,
                 state="partial",
                 commit_point="unknown",
                 error=f"first post-commit checkpoint lost: {detail}",
                 finalization=finalization,
                 finalization_checkpoint_lost=detail,
             )
             return result
+    if operation_id and merge_receipts.merge_receipt_configured():
+        try:
+            result["receipt"] = await asyncio.to_thread(
+                merge_receipts.record_merge_receipt,
+                operation_id,
+                result,
+                finalization,
+            )
+        except Exception as error:
+            detail = err_text(error)
+            logger.error(
+                "merge receipt failed operation_id=%s: %s", operation_id, detail,
+            )
+            result.update(
+                ok=False,
+                state="partial",
+                commit_point="target_committed",
+                error=f"verified merge receipt failed: {detail}",
+                finalization=finalization,
+            )
+            return result
     try:
         applied = await apply_merge_finalization(finalization)
     except Exception as error:
         detail = err_text(error)
         logger.error("merge finalization failed operation_id=%s: %s", operation_id, detail)
         result.update(
             ok=False,
             state="partial",
             commit_point="target_committed",
             error=f"merge finalization failed: {detail}",
             finalization=finalization,
         )
         return result
     finalization["stage"] = "APPLIED"
     if operation_id:
         await asyncio.to_thread(
             _ops.mark_finalization_applied, operation_id, finalization,
         )
     result.update(applied)
     result["finalization"] = finalization
@@ -1755,40 +1783,45 @@ async def execute_merge_session(
                 worker_head=expected_head,
                 http_status=409,
             )
         found = live or manager._hydrate_row(row)
         prior_task_id = str(getattr(found, "task_id", "") or row.get("task_id") or "")
         worktree_path = row.get("worktree_path") or ""
         if not worktree_path:
             return _merge_not_reached(
                 "session has no worktree", worker_branch=row_branch, http_status=400,
             )
         if not row_scope:
             return _merge_not_reached(
                 "session has no scope", worker_branch=row_branch, http_status=400,
             )
 
         task_identity = None
         primary_task_identity = None
         primary_task_ref = ""
         project_id = ""
         strict_task_merge = str(req.get("merge_schema_version") or "") == "2"
+        from app.ia import merge_receipts
+
+        receipt_required = (
+            strict_task_merge and merge_receipts.merge_receipt_configured()
+        )
         task_outcome = str(req.get("task_outcome") or "").strip().lower()
         if strict_task_merge:
             if task_outcome not in {"continue", "complete"}:
                 return _merge_not_reached(
                     "task_outcome must be 'continue' or 'complete' for merge schema 2",
                     worker_branch=row_branch,
                     worker_head=expected_head,
                     http_status=400,
                 )
             if task_outcome == "continue" and next_task_id:
                 # Смена задачи — это ЗАКРЫТИЕ текущей и назначение следующей одной
                 # транзакцией. `continue` с next_task_id оставил бы текущую открытой
                 # и без воркера, то есть ровно ту забывчивость, которую #248 убирает.
                 return _merge_not_reached(
                     "next_task_id requires task_outcome='complete'",
                     worker_branch=row_branch,
                     worker_head=expected_head,
                     http_status=400,
                 )
             primary_task_ref = str(row.get("task_id") or "").strip()
@@ -1837,50 +1870,55 @@ async def execute_merge_session(
         pinned_head = expected_head
         pinned_branch = expected_branch or row_branch
         if not pinned_head:
             try:
                 actual_branch, pinned_head = await asyncio.to_thread(
                     inspect_worktree_identity, worktree_path,
                 )
             except RuntimeError as e:
                 return _merge_not_reached(
                     str(e), worker_branch=row_branch, http_status=400,
                 )
             if pinned_branch and actual_branch != pinned_branch:
                 return _merge_not_reached(
                     f"worker branch changed before merge: expected {pinned_branch}, found {actual_branch}",
                     worker_branch=actual_branch,
                     worker_head=pinned_head,
                     http_status=409,
                 )
             pinned_branch = actual_branch
 
-        try:
-            target = await asyncio.to_thread(
-                _session_base_branch, found, requested_target,
-            )
-        except ValueError as e:
-            return _merge_not_reached(
-                str(e), target_branch=requested_target,
-                worker_branch=pinned_branch, worker_head=pinned_head,
-                http_status=400,
-            )
+        if expected_target_head:
+            # Target-aware operations already resolved and persisted this branch/ref at
+            # admission. The repository lock rechecks the same pair before mutation.
+            target = requested_target or getattr(found, "base_branch", "")
+        else:
+            try:
+                target = await asyncio.to_thread(
+                    _session_base_branch, found, requested_target,
+                )
+            except ValueError as e:
+                return _merge_not_reached(
+                    str(e), target_branch=requested_target,
+                    worker_branch=pinned_branch, worker_head=pinned_head,
+                    http_status=400,
+                )
 
         if not await _wait_for_merge_idle(found):
             status = found.status.value
             return _merge_not_reached(
                 f"worker is {status} — wait for idle before merge",
                 target_branch=target, worker_branch=pinned_branch,
                 worker_head=pinned_head, http_status=400,
             )
 
         current_row = await asyncio.to_thread(get_session, session_id)
         if (
             not current_row
             or current_row.get("status") == "archived"
             or current_row.get("name") != expected_name
             or (current_row.get("scope") or "").rstrip("/") != row_scope
             or (current_row.get("branch") or "") != row_branch
         ):
             return _merge_not_reached(
                 "session identity changed while waiting to merge",
                 target_branch=target, worker_branch=pinned_branch,
@@ -1893,102 +1931,110 @@ async def execute_merge_session(
                 if found.status.value != "idle":
                     return _merge_not_reached(
                         f"worker is {found.status.value} — wait for idle before merge",
                         target_branch=target, worker_branch=pinned_branch,
                         worker_head=pinned_head, http_status=400,
                     )
             # Личность перечитывается ЗДЕСЬ — после ожидания хода и под lifecycle-локом,
             # то есть в последний момент, когда воркер уже не может ничего дописать.
             # Пин не забывается: он уезжает в результат вместе с фактическим HEAD и классом.
             drift = await asyncio.to_thread(
                 classify_head_drift, worktree_path, pinned_branch, pinned_head,
             )
             if drift["class"] == "FATAL":
                 return _merge_not_reached(
                     f"worker identity drifted before merge: {drift['reason']}",
                     target_branch=target,
                     worker_branch=drift["actual_branch"] or pinned_branch,
                     worker_head=drift["actual_head"] or pinned_head,
                     http_status=409,
                 )
-            merge_head = drift["actual_head"] or pinned_head
+            merge_head = pinned_head if receipt_required else drift["actual_head"] or pinned_head
 
             finalization: dict | None = None
             if strict_task_merge:
                 try:
                     finalization = await asyncio.to_thread(
                         _tm.prepare_merge_finalization,
                         scope=row_scope,
                         session_id=session_id,
                         project_id=project_id,
                         outcome=task_outcome,
                         task=primary_task_identity,
                         next_task=task_identity,
                         operation_id=operation_id,
                     )
                 except ValueError as e:
                     return _merge_not_reached(
                         str(e),
                         target_branch=target,
                         worker_branch=pinned_branch,
                         worker_head=merge_head,
                         http_status=409,
                     )
                 finalization["target_branch"] = target
                 finalization["worker_head"] = merge_head
 
+            commit_receipt = None
+            if finalization is not None and receipt_required:
+                def commit_receipt(merge_result: dict) -> dict:
+                    return merge_receipts.record_merge_receipt(
+                        operation_id, merge_result, finalization,
+                    )
+
             def _resolve_candidate_refs(actual_refs: list[str]) -> list[str]:
                 """Turn the refs found on the pinned HEAD into canonical scoped ones.
 
                 Runs under the repository lock, on the same inspection that guards the
                 emitted subject — a ref this refuses never reaches a commit.
                 """
                 canonical = _tm.resolve_scoped_task_identities(
                     row_scope, actual_refs,
                 )["canonical_refs"]
                 finalization["candidate_refs"] = canonical
                 return canonical
 
             def _prepare_finalization(target_before: str, expected_tree: str) -> None:
                 """Freeze the pre-Git journal under the repo lock, before any mutation."""
                 finalization["target_before"] = target_before
                 finalization["expected_tree"] = expected_tree
                 if operation_id:
                     _ops.save_prepared_finalization(operation_id, finalization)
 
             try:
                 result = await asyncio.to_thread(
                     merge_worktree_to_main,
                     worktree_path,
                     row_scope,
                     target_branch=target,
                     expected_worker_branch=pinned_branch,
                     expected_worker_head=merge_head,
                     expected_target_head=expected_target_head,
                     waive_diff_budget=bool(req.get("waive_diff_budget")),
                     waived_by=str(req.get("waived_by") or ""),
                     primary_task_ref=primary_task_ref,
                     operation_id=operation_id if finalization is not None else "",
                     prepare=_prepare_finalization if finalization is not None else None,
                     resolve_refs=(
                         _resolve_candidate_refs if finalization is not None else None
                     ),
+                    commit_receipt=commit_receipt,
                 )
             except Exception as e:
                 # Реmержа не было видно ни одной стороной: исход Git неизвестен, поэтому
                 # резервация НЕ снимается — иначе задачу заберёт другой воркер, пока
                 # никто не знает, коммитнулась она или нет.
                 return {
                     **_merge_not_reached(
                         f"merge execution failed: {type(e).__name__}: {e}",
                         target_branch=target,
                         worker_branch=pinned_branch,
                         worker_head=pinned_head,
                         http_status=500,
                     ),
                     "state": "partial",
                     "commit_point": "unknown",
                 }
 
             if isinstance(result, dict):
                 result["head_drift"] = drift["class"]
                 result["worker_head_pinned"] = pinned_head
diff --git a/app/workspace.py b/app/workspace.py
index 1a0a9993a..d59de0b65 100644
--- a/app/workspace.py
+++ b/app/workspace.py
@@ -1225,56 +1225,58 @@ def inspect_worktree_identity(worktree_path: str) -> tuple[str, str]:
         raise RuntimeError(f"cannot inspect worker HEAD: {detail}")
     return branch.stdout.strip(), head.stdout.strip()
 
 
 def merge_worktree_to_main(
     worktree_path: str,
     repo_path: str,
     target_branch: str = "",
     *,
     expected_worker_branch: str = "",
     expected_worker_head: str = "",
     expected_target_head: str = "",
     waive_diff_budget: bool = False,
     waived_by: str = "",
     expected_candidate_refs: list[str] | None = None,
     validated_task_refs: list[str] | None = None,
     primary_task_ref: str = "",
     operation_id: str = "",
     prepare: Callable[[str, str], None] | None = None,
     resolve_refs: Callable[[list[str]], list[str]] | None = None,
+    commit_receipt: Callable[[dict], dict] | None = None,
 ) -> MergeOutcome:
     wt = Path(worktree_path).resolve()
     repo = _resolve_repo(str(wt), repo_path)
 
     original_branch = None
     result = None
     worker_head = ""
     target_before = ""
     diff_insertions = None
     target_after = ""
     worker_branch = ""
     mutation_started = False
     target_commit_succeeded = False
     merge_cwd = ""
     target_recheck = None
     prepared_squash_message = ""
+    reset_worker_pending = False
 
     with repo_mutation_lock(repo):
         target_branch = resolve_base_branch(str(repo), target_branch)
         try:
             worker_head_result = _git_cmd(
                 ["git", "rev-parse", "HEAD"],
                 cwd=str(wt), capture_output=True, text=True,
             )
             if worker_head_result.returncode == 0:
                 worker_head = worker_head_result.stdout.strip()
                 if expected_worker_head and worker_head != expected_worker_head:
                     result = {
                         "ok": False,
                         "error": (
                             "worker HEAD changed before merge: "
                             f"expected {expected_worker_head}, found {worker_head}"
                         ),
                     }
             else:
                 detail = (
@@ -1644,43 +1646,41 @@ def merge_worktree_to_main(
                                                                     merge_cwd, old_head,
                                                                 )
                                                                 if old_head else {}
                                                             )
                                                             result = {
                                                                 "ok": True,
                                                                 "commits_merged": commits_merged,
                                                                 "branch": branch,
                                                                 "merged_commits": merged_commits,
                                                             }
                                                     else:
                                                         result = {
                                                             "ok": True,
                                                             "commits_merged": 0,
                                                             "branch": branch,
                                                             "merged_commits": {},
                                                         }
 
                                             if result and result.get("ok"):
                                                 target_commit_succeeded = True
-                                                _reset_worktree_to_ref(
-                                                    str(wt), target_branch, str(repo),
-                                                )
+                                                reset_worker_pending = True
         finally:
             if original_branch and original_branch != target_branch:
                 restore = _git_cmd(
                     ["git", "checkout", original_branch],
                     cwd=str(repo), capture_output=True, text=True,
                 )
                 if restore.returncode != 0:
                     logger.error(f"restore branch failed: {restore.stderr.strip()}")
                     result = {"ok": False, "state": "restore_failed",
                               "error": f"cannot restore branch '{original_branch}': {restore.stderr.strip()}"}
         target_after_result = _git_cmd(
             ["git", "show-ref", "--verify", f"refs/heads/{target_branch}"],
             cwd=str(repo), capture_output=True, text=True,
         )
         if target_after_result.returncode == 0:
             target_after = target_after_result.stdout.split()[0]
         target_snapshot_known = target_after_result.returncode in (0, 1)
 
         if result is None:
             result = {"ok": False, "error": "merge produced no result"}
@@ -1729,40 +1729,63 @@ def merge_worktree_to_main(
         result.update(
             state=state,
             commit_point=commit_point,
             target_branch=target_branch,
             target_before=target_before,
             target_after=target_after,
             worker_branch=worker_branch,
             worker_head=worker_head,
             conflicts=result.get("conflicts", []),
             diff_insertions=diff_insertions,
             diff_budget_limit=MAX_DIFF_INSERTIONS,
             diff_budget_waived=bool(waive_diff_budget),
             diff_budget_waived_by=waived_by if waive_diff_budget else "",
         )
         if expected_target_head:
             result["target_recheck"] = target_recheck or {
                 "expected": expected_target_head,
                 "actual": target_before,
                 "matched": target_before == expected_target_head,
             }
+        if (
+            result.get("ok")
+            and commit_point == "target_committed"
+            and commit_receipt is not None
+        ):
+            try:
+                result["receipt"] = commit_receipt(dict(result))
+            except Exception as error:
+                result.update(
+                    ok=False,
+                    state="partial",
+                    error=(
+                        "verified merge receipt could not be persisted before "
+                        f"worktree reset: {type(error).__name__}: {error}"
+                    ),
+                    receipt_error=f"{type(error).__name__}: {error}",
+                )
+        if reset_worker_pending and (
+            commit_point != "target_committed"
+            or commit_receipt is None
+            or isinstance(result.get("receipt"), dict)
+        ):
+            _reset_worktree_to_ref(str(wt), target_branch, str(repo))
         return result
 
 
 def _parse_merged_commits(
     repo: str, old_head: str, head_ref: str = "HEAD",
 ) -> dict[str, list[dict]]:
     log = _git_cmd(
         ["git", "log", f"{old_head}..{head_ref}", "--format=%H%x00%s%x00%ad", "--date=short"],
         cwd=repo, capture_output=True, text=True,
     )
     if log.returncode != 0 or not log.stdout.strip():
         return {}
 
     by_par: dict[str, list[dict]] = {}
     for line in log.stdout.strip().splitlines():
         parts = line.split("\x00", 2)
         if len(parts) < 3:
             continue
         full_hash, message, date = parts
         short_hash = full_hash[:7]


## Later history of the touched files on main (after this commit)

84 later commits touch these paths; the first 40 (oldest first):
41d7182d8 2026-08-25 #398: preserve post-commit merge fields
0349fc14c 2026-08-26 Repair Orchestra startup and dashboard resilience
589528d1a 2026-08-26 Improve Orchestra runtime stability and live status
e15a5f443 2026-08-26 #400: freeze merge loss regression oracles
507b63d81 2026-08-26 #401: expose quota delivery refusals
8e2b564cd 2026-08-26 #407: freeze durable fan interception oracle
f1e4aeb14 2026-08-28 время в каждом входящем сообщении, включая агентские
735cf14e5 2026-08-28 чат берётся из сети, зеркало логов в IndexedDB удалено
43a96ed31 2026-08-28 #413: freeze merge delivery visibility oracle
8239760c7 2026-08-29 #416: research misleading zero-commit merge failure
cc15369de 2026-08-31 #423: report merge conflict paths
feff52e3b 2026-08-31 #423: freeze resolved-operation success oracle
0aa2d5953 2026-08-31 #424: freeze live merge progress oracle
9093641f3 2026-09-01 v2.41.0: аудит кодовой базы — 27 дефектов закрыто (3 P0 в tm.py), 2 фикса откачены как регрессии
4e5940ef6 2026-09-02 #433: research message provenance
cb96eb6fc 2026-09-02 v2.41.1: чат дашборда чинён — гейт происхождения #433 отвергал каждое сообщение на контуре без авторизации
12ed3d3d6 2026-09-03 #445: classify senderless dashboard sends by auth state
f8e00522e 2026-09-03 #430: research .orchestra path migration
71240bd4f 2026-09-03 #446: suppress raw telemetry from user channels
afdf03ea0 2026-09-03 #450: hide user timestamps in human-facing channels
1a86f403b 2026-09-03 #462: backtest review coverage gate
2a048e616 2026-09-03 #465: research taskless adhoc merge deadlock
975476622 2026-09-04 #466: research and freeze run receipt acceptance
e47719104 2026-09-04 #473: миграция раскладки чинит владение воркеров в обоих владельцах
cb052ede7 2026-09-04 #474: пер-тестовый потолок в merge-гейте и снятие хеша цели с идентичности ревью
480ca55c2 2026-09-04 refactor: extract privacy and error helpers, trim duplicated validation
bb2f98bb8 2026-09-05 #493: author signs the review outcome, verdict comes from the artifact, post-review delta needs a machine-checked attestation
e3d29ad1f 2026-09-05 #499: surface and repair derived lifecycle quarantine
36326164d 2026-09-05 #502: WIP #502: map merge subjects before emergency slice
e2e83139f 2026-09-05 fix: complete scoped recovery and continuation lifecycle safeguards
2847a2c5f 2026-09-05 refactor: use tracked AGENTS as the shared project instruction source
42882844a 2026-09-05 #509: plan for explicit review subject and requester/subject split
979c46315 2026-09-06 мерж: чужой номер задачи в сообщении коммита — предупреждение, а не отказ всей операции
067679f36 2026-09-07 #515, #432, #523, #520, #526: CI шардируется на 6 процессов — полный сьют в один процесс убивает OOM
5f8894ec9 2026-09-07 #532: enforce role and persistent worker tool exclusions at MCP dispatch
25a7e6ed7 2026-09-07 Introduce advisory review and one pinned acceptance for new task assignments
bb115dcac 2026-09-07 Merge branch 'main' into codex/simplify-review
fe507ac6e 2026-09-08 Namespace VPS tasks and simplify runtime chat transfer and worker notes
4f87cecca 2026-09-08 #536: WIP #536: preserve writer conflict detection and regression coverage
715f0fc9f 2026-09-08 Merge remote-tracking branch 'origin/main' into codex/local-workflow

## Patches of the first 8 later commits, restricted to the touched paths (each capped at 150 lines)

### 41d7182d8 #398: preserve post-commit merge fields

diff --git a/app/merge_operations.py b/app/merge_operations.py
index 37c8a882e..ac94b3ded 100644
--- a/app/merge_operations.py
+++ b/app/merge_operations.py
@@ -1028,14 +1028,26 @@ def normalize_merge_result(
         git_status = "CONFLICT"
     elif "working tree is dirty" in message.lower():
         git_status = "DIRTY"
     elif commit_point == "UNKNOWN":
         git_status = "UNKNOWN"
+    elif commit_point == "REACHED":
+        # Post-commit stages may set the aggregate outcome to false, but Git has
+        # already committed at this point and must not be reported as failed.
+        git_status = "SUCCEEDED"
     else:
         git_status = "FAILED"
 
-    link_status, link_items, link_failures, link_warnings = _link_status(raw.get("linked_tasks"))
+    finalization = raw.get("finalization")
+    linked_tasks = raw.get("linked_tasks")
+    if (
+        not linked_tasks
+        and isinstance(finalization, dict)
+        and finalization.get("links")
+    ):
+        linked_tasks = finalization["links"]
+    link_status, link_items, link_failures, link_warnings = _link_status(linked_tasks)
     lifecycle = raw.get("lifecycle_status")
     lifecycle_status = (
         "SUCCEEDED" if isinstance(lifecycle, dict) and lifecycle.get("ok")
         else "FAILED" if isinstance(lifecycle, dict)
         else "NOT_RUN"
@@ -1135,11 +1147,10 @@ def normalize_merge_result(
         error = _error(
             code, message, operation_id=operation_id,
             status=raw.get("_http_status"), details=details,
         )
 
-    finalization = raw.get("finalization")
     if isinstance(finalization, dict) and finalization.get("stage") == "PENDING":
         # DB-стадия не доехала, но коммит есть и журнал его описывает: это чинится
         # повтором ТОГО ЖЕ operation_id и никогда вторым мержем.
         retryable = True
 
@@ -1441,10 +1452,21 @@ async def _resume_finalization(record: dict[str, Any]) -> dict[str, Any]:
             retryable=True, details={"failed_stages": ["FINALIZATION_PENDING"]},
         )
         result["operation_state"] = "PARTIAL"
         result["retryable"] = True
         result["finalization"] = payload
+        link_status, link_items, _failures, link_warnings = _link_status(
+            payload.get("links"),
+        )
+        if link_items:
+            result["task_links"] = {"status": link_status, "items": link_items}
+            result["warnings"] = list(result.get("warnings") or []) + [
+                {"code": "TASK_LINK_NOT_FOUND", "message": text}
+                for text in link_warnings
+            ]
+        if result.get("commit_point") == "REACHED":
+            result["git"]["status"] = "SUCCEEDED"
         return result
     payload["stage"] = "APPLIED"
     await asyncio.to_thread(mark_finalization_applied, operation_id, payload)
     link_status, link_items, _failures, link_warnings = _link_status(
         applied.get("linked_tasks"),
### 0349fc14c Repair Orchestra startup and dashboard resilience

diff --git a/app/routes/sessions.py b/app/routes/sessions.py
index cf7987b17..4e52aac1c 100644
--- a/app/routes/sessions.py
+++ b/app/routes/sessions.py
@@ -241,11 +241,15 @@ def _conditional(request: Request, payload) -> Response:
     return JSONResponse(payload, headers=headers)
 
 
 @router.get("/api/sessions")
 async def list_sessions(request: Request, scope: Optional[str] = None):
-    return _conditional(request, manager.list_sessions(scope))
+    # Snapshotting 80+ live/persisted sessions performs two SQLite reads and JSON-ready
+    # projection. Keep that work off the event loop so one cold disk/swap page cannot freeze
+    # SSE and make every browser retry the same request at once.
+    payload = await asyncio.to_thread(manager.list_sessions, scope)
+    return _conditional(request, payload)
 
 
 @router.post("/api/sessions", status_code=201)
 async def create_session(req: CreateSessionRequest):
     from app.routes.system import _is_safe_path
### 589528d1a Improve Orchestra runtime stability and live status

diff --git a/app/routes/sessions.py b/app/routes/sessions.py
index 4e52aac1c..d779a142e 100644
--- a/app/routes/sessions.py
+++ b/app/routes/sessions.py
@@ -506,10 +506,21 @@ async def stream_session_logs(name: str, scope: str, request: Request, after_id:
     limit = min(limit, 1000)
     import json
     session_id = manager.get_session_id(name, scope)
     if not session_id:
         return JSONResponse({"error": "not found"}, status_code=404)
+    live_session = manager.get(session_id)
+    stored = get_session_row(session_id) if live_session is None else None
+
+    def with_status(payload: dict) -> dict:
+        status = (
+            live_session.status.value
+            if live_session is not None
+            else str((stored or {}).get("status") or "idle")
+        )
+        return {**payload, "agent_status": status}
+
     async def event_generator():
         from app.db import _conn
         from app.live_broker import STREAM_CLOSE, broker
         last_id = after_id
         c = _conn()
@@ -517,15 +528,15 @@ async def stream_session_logs(name: str, scope: str, request: Request, after_id:
         try:
             # Первым делом называем сессию, которую мы разрешили из name+scope. Клиент
             # держит историю по session_id и до этого события знает её лишь по своей карте,
             # которая могла устареть (агента убили и подняли под тем же именем). Правду
             # знает только сервер, и он обязан сказать её ДО первой строки истории.
-            yield f"data: {json.dumps({'type': '__session', 'session_id': session_id})}\n\n"
+            yield f"data: {json.dumps(with_status({'type': '__session', 'session_id': session_id}))}\n\n"
             # initial history first (one-shot) — preserves load-more behavior
             if after_id == 0:
                 for log in get_logs_before(session_id, before_id=2**31 - 1, limit=limit):
-                    yield f"data: {json.dumps(log)}\n\n"
+                    yield f"data: {json.dumps(with_status(log))}\n\n"
                     last_id = log["id"]
             while True:
                 if await request.is_disconnected():
                     return
                 # 1) drain live partials FIRST (ephemeral, no id) — they always
@@ -536,16 +547,16 @@ async def stream_session_logs(name: str, scope: str, request: Request, after_id:
                         payload = q.get_nowait()
                     except asyncio.QueueEmpty:
                         break
                     if payload is STREAM_CLOSE:
                         return
-                    yield f"data: {json.dumps(payload)}\n\n"
+                    yield f"data: {json.dumps(with_status(payload))}\n\n"
                     drained += 1
                 # 2) DB-persisted logs (finals + all other log types)
                 logs = get_logs(session_id, after_id=last_id, conn=c)
                 for log in logs:
-                    yield f"data: {json.dumps(log)}\n\n"
+                    yield f"data: {json.dumps(with_status(log))}\n\n"
                     last_id = log["id"]
                 # 3) short poll while active (partials follow quickly), back off when idle
                 await asyncio.sleep(0.1 if (logs or drained) else 0.5)
         finally:
             broker.unsubscribe(session_id, q)
### e15a5f443 #400: freeze merge loss regression oracles

diff --git a/app/merge_operations.py b/app/merge_operations.py
index ac94b3ded..5881a718f 100644
--- a/app/merge_operations.py
+++ b/app/merge_operations.py
@@ -936,10 +936,15 @@ def _classify_failure(raw: dict[str, Any], message: str) -> tuple[str, dict[str,
         details["target_recheck"] = raw.get("target_recheck") or {}
         return "TARGET_HEAD_CHANGED", details, _action(
             "REFRESH_TARGET_THEN_NEW_OPERATION",
             "Target moved after admission; start a fresh merge operation.",
         )
+    if raw.get("code") == "NO_COMMITS_MERGED":
+        return "NO_COMMITS_MERGED", details, _action(
+            "CHECK_WORKER_THEN_NEW_OPERATION",
+            "No commits reached the target branch; verify the worker branch before retrying.",
+        )
     if raw.get("conflicts"):
         details["paths"] = list(raw["conflicts"])
         return "CONFLICT", details, _action(
             "RESOLVE_ON_WORKER_THEN_NEW_OPERATION",
             "Resolve and commit the conflict on the worker branch, then start a new operation; do not merge the target manually.",
diff --git a/app/routes/sessions.py b/app/routes/sessions.py
index d779a142e..19c24fa0e 100644
--- a/app/routes/sessions.py
+++ b/app/routes/sessions.py
@@ -103,11 +103,12 @@ def _existing_branch_verdict(worktree_path: str, branch: str, scope: str,
         "ok": False,
         "state": "branch_has_work_after_merge",
         "error": (
             f"branch '{branch}' has commits made after it was merged (head {head}, "
             f"merged {', '.join(proof['heads'])}, operation {proof['operation_id']}) — "
-            f"recreating it from base would destroy them; pass force=true to discard"
+            f"recreating this target branch from base would discard its commits; "
+            "the worker's current branch is unaffected; pass force=true to discard"
         ),
     }
 
 
 def _session_base_branch(session, requested: str = "") -> str:
@@ -1916,10 +1917,18 @@ async def execute_merge_session(
                     str(e), target_branch=requested_target,
                     worker_branch=pinned_branch, worker_head=pinned_head,
                     http_status=400,
                 )
 
+        if target == pinned_branch:
+            return _merge_not_reached(
+                f"target branch '{target}' is the worker branch; refusing to merge it into itself",
+                target_branch=target,
+                worker_branch=pinned_branch,
+                worker_head=pinned_head,
+            )
+
         if not await _wait_for_merge_idle(found):
             status = found.status.value
             return _merge_not_reached(
                 f"worker is {status} — wait for idle before merge",
                 target_branch=target, worker_branch=pinned_branch,
@@ -2048,10 +2057,25 @@ async def execute_merge_session(
                     ),
                     "state": "partial",
                     "commit_point": "unknown",
                 }
 
+            if (
+                isinstance(result, dict)
+                and result.get("ok")
+                and result.get("target_before")
+                and result.get("target_before") == result.get("target_after")
+                and int(result.get("commits_merged") or 0) == 0
+            ):
+                result.update(
+                    ok=False,
+                    state="failed",
+                    commit_point="not_reached",
+                    code="NO_COMMITS_MERGED",
+                    error="merge produced no new commits",
+                )
+
             if isinstance(result, dict):
                 result["head_drift"] = drift["class"]
                 result["worker_head_pinned"] = pinned_head
                 if strict_task_merge:
                     result["task_outcome"] = task_outcome
@@ -2280,10 +2304,15 @@ async def switch_branch(name: str, req: dict):
             )
         except ValueError as e:
             return JSONResponse({"error": str(e)}, status_code=409)
     worktree_path = found.worktree_path
     session_id = found.id
+    previous_branch = getattr(found, "branch", "") or ""
+    previous_base_branch = getattr(found, "base_branch", "") or ""
+    previous_task_id = str(getattr(found, "task_id", "") or "")
+    previous_needs_switch = bool(getattr(found, "needs_switch", False))
+    previous_owned_dirs = list(getattr(found, "owned_dirs", []) or [])
     if not worktree_path:
         return JSONResponse({"error": "session has no worktree"}, status_code=400)
     new_branch = f"task-{par}/{name}"
     try:
         from_ref = _session_base_branch(found, req.get("from_ref", ""))
@@ -2369,20 +2398,66 @@ async def switch_branch(name: str, req: dict):
                             result["task_status"] = {
                                 "ok": False,
                                 "error": "task not updated because switched lifecycle was not persisted",
                             }
                             return result
+                        task_assignment_raised = False
                         try:
                             result["task_status"] = await asyncio.to_thread(
                                 _tm.api_update_task_if_current,
                                 task_identity,
                                 status="in_progress",
                             )
                         except Exception as task_error:
+                            task_assignment_raised = True
                             detail = err_text(task_error)
                             result["task_status"] = {"ok": False, "error": detail}
                         if not result["task_status"].get("ok"):
+                            if task_assignment_raised and previous_branch:
+                                try:
+                                    rollback = await asyncio.to_thread(
+                                        switch_worktree_branch,
+                                        worktree_path,
+                                        previous_branch,
+                                        from_ref=previous_branch,
+                                        force=True,
+                                    )
+                                except Exception as rollback_error:
+                                    rollback = {
+                                        "ok": False,
+                                        "error": f"branch rollback failed: {err_text(rollback_error)}",
+                                    }
+                                if rollback.get("ok"):
+                                    try:
+                                        await manager.transition_lifecycle(
+                                            found,
+                                            branch=previous_branch,
+                                            base_branch=previous_base_branch,
+                                            task_id=previous_task_id,
+                                            needs_switch=previous_needs_switch,
+                                            owned_dirs=previous_owned_dirs,
+                                        )
+                                    except Exception as restore_error:
+                                        rollback = {
+                                            **rollback,
+                                            "ok": False,
+                                            "error": (
+                                                "branch rolled back but lifecycle restore failed: "
+                                                f"{err_text(restore_error)}"
### 507b63d81 #401: expose quota delivery refusals

diff --git a/app/routes/sessions.py b/app/routes/sessions.py
index 19c24fa0e..ff08e81e9 100644
--- a/app/routes/sessions.py
+++ b/app/routes/sessions.py
@@ -729,10 +729,12 @@ async def send_message(name: str, req: SendRequest, request: Request = None):
                         status_code=403,
                     )
                 if name != existing["target_name"]:
                     conflict, conflict_status = message_deliveries._conflict(delivery_id)
                     return JSONResponse(conflict, status_code=conflict_status)
+                if existing["state"] == "FAILED_BEFORE_SUBMIT":
+                    await manager.preflight_message_delivery(existing["target_session_id"])
                 resource, status_code = await message_deliveries.accept_message_delivery(
                     delivery_id=delivery_id,
                     source_session_id=source_id or None,
                     source_principal=source_principal,
                     source_name=source_name,
@@ -815,10 +817,11 @@ async def send_message(name: str, req: SendRequest, request: Request = None):
                             "outcome_unknown": False,
                         }
                     },
                     status_code=404,
                 )
+            await manager.preflight_message_delivery(target.id)
             target_generation = (
                 f"session={target.id}|task={getattr(target, 'task_id', '')}|"
                 f"branch={getattr(target, 'branch', '')}|"
                 f"needs_switch={int(bool(getattr(target, 'needs_switch', False)))}"
             )
### 8e2b564cd #407: freeze durable fan interception oracle

diff --git a/app/routes/sessions.py b/app/routes/sessions.py
index ff08e81e9..ef5096231 100644
--- a/app/routes/sessions.py
+++ b/app/routes/sessions.py
@@ -222,10 +222,17 @@ class OpenFanRequest(BaseModel):
         if v < 0 or v > 86400:
             raise ValueError("deadline_seconds must be within [0, 86400]")
         return v
 
 
+class FanMemberTerminalRequest(BaseModel):
+    fan_id: str
+    child: str
+    state: str
+    summary: str = ""
+
+
 def _conditional(request: Request, payload) -> Response:
     """Отдать payload с ETag, а при совпадении If-None-Match — пустой 304.
 
     Дашборд опрашивает `/api/sessions` каждые 3 секунды, и ответ весит 48.8 КБ даже когда
     ничего не изменилось (замер 21.08) — почти мегабайт в минуту и один из ШЕСТИ браузерных
@@ -627,13 +634,36 @@ async def open_fan(req: OpenFanRequest):
         scope=req.scope,
         children=req.children,
         deadline_seconds=deadline,
         reducer=req.reducer or "",
     )
+    fan_barrier.schedule_deadline(req.fan_id)
     return {"ok": True, "fan_id": req.fan_id, "children": len(req.children)}
 
 
+@router.post("/api/fan/member/terminal")
+async def mark_fan_member_terminal(req: FanMemberTerminalRequest):
+    from app import fan_barrier
+
+    released = fan_barrier.record_terminal(
+        req.child,
+        req.state,
+        summary=req.summary,
+        fan_id=req.fan_id,
+    )
+    if released:
+        target = fan_barrier.parent_of(req.fan_id)
+        if target:
+            recipient = fan_barrier.reducer_of(req.fan_id) or target[0]
+            destination = await manager.ensure_loaded(recipient, target[1])
+            if destination is not None:
+                await manager.send(
+                    destination.id, fan_barrier.manifest_text(req.fan_id)
+                )
+    return {"ok": True, "fan_id": req.fan_id, "released": released}
+
+
 @router.post("/api/sessions/{name}/send")
 async def send_message(name: str, req: SendRequest, request: Request = None):
     try:
         if req.delivery_id.strip():
             if not req.wake or req.message_kind is not None:
### f1e4aeb14 время в каждом входящем сообщении, включая агентские

diff --git a/app/routes/sessions.py b/app/routes/sessions.py
index ef5096231..9efcc459a 100644
--- a/app/routes/sessions.py
+++ b/app/routes/sessions.py
@@ -1053,15 +1053,17 @@ async def send_message(name: str, req: SendRequest, request: Request = None):
         msg = f"[from:{req.sender}] {req.message}" if req.sender else req.message
         if req.sender:
             msg += manager._context_warning(req.sender)
             if hasattr(session, 'last_task_sender'):
                 session.last_task_sender = req.sender
-        else:
-            from datetime import datetime, timezone, timedelta
-            local_tz = timezone(timedelta(hours=7))
-            now = datetime.now(local_tz).strftime("%H:%M")
-            msg = f"[{now}] {msg}"
+        # Время ставится КАЖДОМУ входящему, включая агентские: юзер требует видеть,
+        # когда сообщение написано, а не только от кого (28.08). Раньше метку получал
+        # только он сам, и в ленте нельзя было отличить свежий отчёт от вчерашнего.
+        from datetime import datetime, timezone, timedelta
+        local_tz = timezone(timedelta(hours=7))
+        now = datetime.now(local_tz).strftime("%H:%M")
+        msg = f"[{now}] {msg}"
         await manager.send(session.id, msg)
         pn = session.parent_name or ""
         result = {"ok": True, "parent_name": pn}
         if task_state:
             result["task"] = task_state
### 735cf14e5 чат берётся из сети, зеркало логов в IndexedDB удалено

diff --git a/app/routes/sessions.py b/app/routes/sessions.py
index 9efcc459a..f45129336 100644
--- a/app/routes/sessions.py
+++ b/app/routes/sessions.py
@@ -572,12 +572,17 @@ async def stream_session_logs(name: str, scope: str, request: Request, after_id:
     return StreamingResponse(event_generator(), media_type="text/event-stream",
                              headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
 
 
 @router.get("/api/sessions/{name}/logs")
-async def get_session_logs(name: str, scope: str, after_id: int = 0, before_id: int = 0,
+async def get_session_logs(name: str, response: Response, scope: str,
+                           after_id: int = 0, before_id: int = 0,
                            limit: int = 500, max_bytes: int = 0, cap: int = 0):
+    # Live chat snapshots are authoritative state, not an asset. A browser/intermediary
+    # replaying an older 200 here recreates the exact "old messages, then SSE catches up"
+    # staircase that the network-first client is designed to eliminate.
+    response.headers["Cache-Control"] = "no-store"
     limit = min(limit, 1000)
     session_id = manager.get_session_id(name, scope)
     if not session_id:
         return JSONResponse({"error": "not found"}, status_code=404)
     if before_id > 0: