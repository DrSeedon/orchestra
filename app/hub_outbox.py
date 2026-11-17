"""Outbox of a hub agent: the only way a Hub session can reach Orchestra (V-1008).

The hub link is outbound only: the hub agent has no Orchestra tools and no path back. It appends
JSON lines ``{"tool": ..., "args": {...}}`` to ``.orchestra-outbox.jsonl`` in its copy; when the
broker syncs the turn back it reads that file (it never reaches the worktree or git) and runs
the entries itself, as the session's own identity, through the same local API a native session's
MCP process uses.

Ordinary workers have three tools only (``send_message``, ``update_checklist``, ``update_progress``),
and the recipient of ``send_message`` is always the worker's own parent.
Sessions with ``role == "orchestrator"`` (or ``is_orchestrator=True``) instead receive the
orchestrator outbox contract (``spawn_worker``, ``send_to_worker``, ``merge_worker``,
``close_worker``, ``update_checklist``, ``update_progress``), scoped strictly to ``who.scope``
and direct children owned by ``who``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
import re
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from typing import Awaitable, Callable
from urllib.parse import quote, urlencode

from app.message_deliveries import report_receipt_accepted

logger = logging.getLogger(__name__)

OUTBOX_NAME = ".orchestra-outbox.jsonl"
ALLOWED_TOOLS = ("send_message", "update_checklist", "update_progress")
ORCHESTRATOR_TOOLS = (
    "spawn_worker",
    "send_to_worker",
    "merge_worker",
    "close_worker",
    "update_checklist",
    "update_progress",
)
MAX_OUTBOX_BYTES = 256 * 1024
MAX_ENTRIES = 50
MAX_MESSAGE_CHARS = 20_000
MAX_STATUS_CHARS = 300
MERGE_POLL_BUDGET_S = 25.0
MERGE_POLL_INTERVAL_S = 0.25

ApiCall = Callable[[str, str, dict], Awaitable[object]]


@dataclass
class Identity:
    session_id: str
    name: str
    scope: str
    parent_name: str = ""
    role: str = "worker"
    branch: str = ""
    pipeline: str = ""
    turn_gen: int = 0
    base_branch: str = ""  # live source binding; older/direct callers may omit it
    is_orchestrator: bool = False


def is_orchestrator_identity(who: Identity | object | None) -> bool:
    if who is None:
        return False
    return bool(getattr(who, "role", "") == "orchestrator" or getattr(who, "is_orchestrator", False))


@dataclass
class OutboxReport:
    done: list[str] = field(default_factory=list)
    dropped: list[str] = field(default_factory=list)
    # A subset of dropped: only positively identified, terminal validation refusals.
    # Everything else remains pending in the sync journal.
    rejected: list[str] = field(default_factory=list)

    def summary(self) -> str:
        if not self.done and not self.dropped:
            return ""
        text = f"[hub outbox] {len(self.done)} delivered"
        if self.done:
            text += " (" + ", ".join(self.done[:10]) + ")"
        if self.dropped:
            text += f", {len(self.dropped)} dropped: " + "; ".join(self.dropped[:10])
        return text


class BookkeepingValidationError(ValueError):
    """The local checklist owner explicitly rejected the request before writing it."""


def _reject(report: OutboxReport, entry: dict, reason: str) -> None:
    # Keep the original action, broker delivery identity and full owner error in
    # the existing dropped journal/report path; never repair model arguments.
    diagnostic = f"{reason}; terminal validation rejection; action=" + json.dumps(entry, ensure_ascii=False)
    report.dropped.append(diagnostic)
    report.rejected.append(diagnostic)


def parse_outbox(
    data: bytes,
    *,
    role: str = "worker",
    is_orchestrator: bool = False,
) -> tuple[list[dict], list[str]]:
    """(valid entries, reasons for everything dropped). Never raises on hostile content."""
    orch_mode = bool(role == "orchestrator" or is_orchestrator)
    allowed = ORCHESTRATOR_TOOLS if orch_mode else ALLOWED_TOOLS
    dropped: list[str] = []
    if len(data) > MAX_OUTBOX_BYTES:
        dropped.append(f"outbox larger than {MAX_OUTBOX_BYTES // 1024} KiB; the tail was ignored")
        data = data[:MAX_OUTBOX_BYTES]
    entries: list[dict] = []
    for number, raw in enumerate(data.decode("utf-8", "replace").splitlines(), 1):
        if not raw.strip():
            continue
        if len(entries) >= MAX_ENTRIES:
            dropped.append(f"line {number}: more than {MAX_ENTRIES} entries in one turn")
            break
        try:
            entry = json.loads(raw)
        except ValueError:
            dropped.append(f"line {number}: not JSON")
            continue
        if not isinstance(entry, dict) or not isinstance(entry.get("tool"), str):
            dropped.append(f"line {number}: no tool name")
            continue
        args = entry.get("args", {})
        if not isinstance(args, dict):
            dropped.append(f"line {number}: args must be an object")
            continue
        if entry["tool"] not in allowed:
            actor = "hub orchestrators" if orch_mode else "hub workers"
            dropped.append(f"line {number}: tool '{entry['tool'][:40]}' is not available to {actor}")
            continue
        entries.append({"tool": entry["tool"], "args": args})
    return entries, dropped


def _lookup_direct_child(
    who: Identity,
    worker_name: str,
    *,
    include_archived: bool = False,
) -> tuple[dict | None, str]:
    """Verify worker_name is a direct non-orchestrator child of `who` inside `who.scope`."""
    from app import db

    scope = (who.scope or "").rstrip("/")
    if not scope:
        return None, "orchestrator scope is empty"
    name = worker_name.strip() if isinstance(worker_name, str) else ""
    if not name or not re.fullmatch(r"[A-Za-z0-9._-]+", name):
        return None, "worker name must be a non-empty slug"
    if name == who.name:
        return None, f"worker '{name}' cannot target the orchestrator itself"
    row = db.get_session_by_name(name, scope)
    if row is None and include_archived:
        with db._conn() as conn:
            found = conn.execute(
                "SELECT * FROM sessions WHERE name = ? AND scope = ? ORDER BY created_at DESC, rowid DESC LIMIT 1",
                (name, scope),
            ).fetchone()
            row = dict(found) if found else None
    if row is None:
        return None, f"worker '{name}' not found in scope '{scope}'"
    if row.get("id") == who.session_id or bool(row.get("is_orchestrator")) or row.get("role") == "orchestrator":
        return None, f"worker '{name}' is not a child worker"
    if row.get("parent_name") != who.name and row.get("parent_id") != who.session_id:
        return None, f"worker '{name}' is not a direct child of '{who.name}'"
    return row, ""


def _worktree_head_sha(worktree_path: str) -> str:
    if not worktree_path or not Path(worktree_path).is_dir():
        return ""
    try:
        out = subprocess.run(
            ["git", "-C", worktree_path, "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    sha = out.stdout.strip() if out.returncode == 0 else ""
    return sha if re.fullmatch(r"[0-9a-fA-F]{40}", sha) else ""


def _request_for(tool: str, args: dict, who: Identity, *, delivery_id: str = "") -> tuple[str, str, dict] | str:
    """(method, path, body) for a single-request worker/bookkeeping tool, or the reason it cannot run."""
    if tool == "send_message":
        if is_orchestrator_identity(who):
            return "send_message: orchestrators must use send_to_worker"
        if not who.parent_name:
            return "send_message: this worker has no parent orchestrator"
        message = args.get("message")
        if not isinstance(message, str) or not message.strip():
            return "send_message: message must be non-empty text"
        # `to` is never read: a hub worker may talk to its own parent only.
        return ("POST", f"/api/sessions/{quote(who.parent_name, safe='')}/send", {
            "message": message[:MAX_MESSAGE_CHARS], "sender": who.name, "scope": who.scope,
            "delivery_id": delivery_id or str(uuid.uuid4())})
    if tool == "update_progress":
        percent = args.get("percent")
        if isinstance(percent, bool) or not isinstance(percent, (int, float)):
            return "update_progress: percent must be a number"
        return ("POST", f"/api/sessions/{quote(who.name, safe='')}/progress", {
            "percent": int(percent), "status": str(args.get("status", ""))[:MAX_STATUS_CHARS],
            "scope": who.scope})
    items, completed = args.get("items"), args.get("completed")
    if not (isinstance(items, list) and all(isinstance(i, str) for i in items)):
        return "update_checklist: items must be a list of strings"
    if not (isinstance(completed, list) and all(isinstance(i, int) and not isinstance(i, bool) for i in completed)):
        return "update_checklist: completed must be a list of step numbers"
    return ("POST", f"/api/sessions/{quote(who.name, safe='')}/checklist", {
        "items": items, "completed": completed, "current": args.get("current"),
        "estimates_minutes": args.get("estimates_minutes")})


def _is_client_rejection(result: object) -> bool:
    if not isinstance(result, dict):
        return False
    status = result.get("http_status")
    return isinstance(status, int) and 400 <= status < 500 and status not in {408, 429}


async def _execute_orchestrator_tool(
    entry: dict,
    who: Identity,
    call: ApiCall,
    report: OutboxReport,
) -> None:
    tool = entry["tool"]
    args = entry["args"]
    delivery_id = entry.get("_delivery_id") or str(uuid.uuid4())
    scope = (who.scope or "").rstrip("/")
    if not scope:
        _reject(report, entry, f"{tool}: orchestrator has no project scope")
        return

    if tool == "spawn_worker":
        from app.models import (
            ensure_project_model_allowed,
            resolve_model,
            validate_model_reason,
        )
        from app.prompting import is_orchestrator_role

        raw_name = args.get("name")
        name = raw_name.strip() if isinstance(raw_name, str) else ""
        if not name or not re.fullmatch(r"[A-Za-z0-9._-]+", name) or name == who.name:
            _reject(report, entry, "spawn_worker: name must be a valid distinct worker slug")
            return
        task = args.get("task")
        if not isinstance(task, str) or not task.strip():
            _reject(report, entry, "spawn_worker: task must be non-empty text")
            return
        raw_model = args.get("model", "hub-gpt-6-luna")
        if not isinstance(raw_model, str) or not raw_model.strip():
            _reject(report, entry, "spawn_worker: model must be a non-empty string")
            return
        child_role = args.get("role", "worker")
        if not isinstance(child_role, str) or not child_role.strip() or is_orchestrator_role(child_role.strip()):
            _reject(report, entry, "spawn_worker: role must be a non-orchestrator worker role")
            return
        child_role = child_role.strip()
        base_branch = str(args.get("base_branch") or "").strip()
        description = str(args.get("description") or "").strip()[:MAX_STATUS_CHARS]
        raw_reason = str(args.get("model_reason") or "").strip()
        task_id = str(args.get("task_id") or "").strip()
        try:
            model = resolve_model(raw_model.strip())
            ensure_project_model_allowed(model, scope)
            model_reason = validate_model_reason(
                model, raw_reason, role=child_role, pipeline=who.pipeline or "default",
                scope=scope, task_id=task_id,
            )

        except ValueError as exc:
            _reject(report, entry, f"spawn_worker: {exc}")
            return

        create_body: dict = {
            "name": name,
            "scope": scope,
            "cwd": scope,
            "model": model,
            "system_prompt": "",
            "use_worktree": True,
            "repo_path": scope,
            "base_branch": base_branch,
            "role": child_role,
            "parent_name": who.name,
            "planned_initial_turn": True,
            "initial_task_title": task[:MAX_MESSAGE_CHARS],
            "initial_delivery_id": delivery_id,
            "disabled_tools": [],
        }
        if model_reason:
            create_body["model_reason"] = model_reason
        if description:
            create_body["description"] = description
        if task_id:
            create_body["task_id"] = task_id

        # Idempotent retry support: if the child was already created by an earlier
        # attempt with the same name & parent, skip duplicate creation and reconcile initial delivery.
        existing_child, _ = _lookup_direct_child(who, name)
        if existing_child is None:
            created = await call("POST", "/api/sessions", create_body)
            err = created.get("error") if isinstance(created, dict) else "invalid create response"
            if err:
                existing_child, _ = _lookup_direct_child(who, name)
                if existing_child is None:
                    if _is_client_rejection(created):
                        _reject(report, entry, f"spawn_worker: {str(err)[:160]}")
                    else:
                        report.dropped.append(f"spawn_worker: {str(err)[:160]}")
                    return

        deliv = await call(
            "POST",
            f"/api/sessions/{quote(name, safe='')}/initial-deliveries",
            {
                "delivery_id": delivery_id,
                "message": task[:MAX_MESSAGE_CHARS],
                "scope": scope,
                "sender": who.name,
            },
        )
        err = deliv.get("error") if isinstance(deliv, dict) else "initial delivery not acknowledged"
        if err and not report_receipt_accepted(deliv):
            if _is_client_rejection(deliv):
                _reject(report, entry, f"spawn_worker: {str(err)[:160]}")
            else:
                report.dropped.append(f"spawn_worker: {str(err)[:160]}")
            return
        report.done.append(tool)
        return

    if tool == "send_to_worker":
        worker = args.get("worker")
        message = args.get("message")
        if not isinstance(message, str) or not message.strip():
            _reject(report, entry, "send_to_worker: message must be non-empty text")
            return
        child, err_reason = _lookup_direct_child(who, worker if isinstance(worker, str) else "")
        if child is None:
            _reject(report, entry, f"send_to_worker: {err_reason}")
            return
        res = await call(
            "POST",
            f"/api/sessions/{quote(child['name'], safe='')}/send",
            {
                "message": message[:MAX_MESSAGE_CHARS],
                "sender": who.name,
                "scope": scope,
                "wake": True,
                "delivery_id": delivery_id,
            },
        )
        if report_receipt_accepted(res) or (isinstance(res, dict) and res.get("ok") is True):
            report.done.append(tool)
            return
        err = res.get("error") if isinstance(res, dict) else "worker message was not accepted"
        if _is_client_rejection(res):
            _reject(report, entry, f"send_to_worker: {str(err)[:160]}")
        else:
            report.dropped.append(f"send_to_worker: {str(err)[:160]}")
        return

    if tool == "merge_worker":
        worker = args.get("worker")
        child, err_reason = _lookup_direct_child(who, worker if isinstance(worker, str) else "")
        if child is None:
            _reject(report, entry, f"merge_worker: {err_reason}")
            return
        target_branch = str(args.get("target_branch") or args.get("target") or child.get("base_branch") or "main").strip()
        expected_head = str(args.get("expected_head") or "").strip()
        if not expected_head:
            expected_head = await asyncio.to_thread(
                _worktree_head_sha, str(child.get("worktree_path") or ""),
            )
        if not re.fullmatch(r"[0-9a-fA-F]{40}", expected_head):
            _reject(report, entry, f"merge_worker: could not resolve 40-char HEAD SHA for worker '{child['name']}'")
            return
        acceptance_note = str(args.get("acceptance_note") or "").strip()
        if len(acceptance_note) < 15:
            acceptance_note = f"Accepted worker {child['name']} into {target_branch} by orchestrator {who.name}"
        waive = bool(args.get("waive_diff_budget", False))
        merge_body: dict = {
            "operation_id": str(uuid.UUID(delivery_id)) if _is_uuid(delivery_id) else str(uuid.uuid4()),
            "name": child["name"],
            "scope": scope,
            "target": target_branch,
            "expected_head": expected_head,
            "acceptance_note": acceptance_note,
            "waive_diff_budget": waive,
            "waived_by": who.name if waive else "",
            "completion_session_id": who.session_id,
        }
        task_id = str(args.get("task_id") or "").strip()
        if task_id:
            merge_body["task_id"] = task_id
            merge_body["task_outcome"] = str(args.get("task_outcome") or "complete").strip().lower()
            merge_body["merge_schema_version"] = 2

        op_id = merge_body["operation_id"]
        res = await call("POST", "/api/merge-operations", merge_body)
        payload = res.get("result") if isinstance(res, dict) and isinstance(res.get("result"), dict) else res
        state = payload.get("operation_state") if isinstance(payload, dict) else None
        deadline = time.monotonic() + MERGE_POLL_BUDGET_S
        while state in {"PENDING", "RUNNING"} and time.monotonic() < deadline:
            await asyncio.sleep(MERGE_POLL_INTERVAL_S)
            polled = await call("GET", f"/api/merge-operations/{quote(op_id, safe='')}", {})
            p_inner = polled.get("result") if isinstance(polled, dict) and isinstance(polled.get("result"), dict) else polled
            if isinstance(p_inner, dict) and p_inner.get("operation_state"):
                payload = p_inner
                state = p_inner.get("operation_state")
        err = (
            (payload.get("error") if isinstance(payload, dict) else None)
            or (res.get("error") if isinstance(res, dict) else None)
        )
        if state in {"SUCCEEDED", "PENDING", "RUNNING"} and not err:
            report.done.append(tool)
            return
        msg = err.get("message") if isinstance(err, dict) else str(err or f"merge ended in state {state}")
        if state == "FAILED" or _is_client_rejection(res):
            _reject(report, entry, f"merge_worker: {str(msg)[:160]}")
        else:
            report.dropped.append(f"merge_worker: {str(msg)[:160]}")
        return

    if tool == "close_worker":
        worker = args.get("worker")
        child, err_reason = _lookup_direct_child(
            who, worker if isinstance(worker, str) else "", include_archived=True,
        )
        if child is None:
            _reject(report, entry, f"close_worker: {err_reason}")
            return
        if child.get("status") == "archived":
            report.done.append(tool)
            return
        force = "true" if bool(args.get("force", False)) else "false"
        query = urlencode({"scope": scope, "force": force})
        res = await call("DELETE", f"/api/sessions/{quote(child['name'], safe='')}?{query}", {})
        err = res.get("error") if isinstance(res, dict) else None
        if not err:
            report.done.append(tool)
            return
        if _is_client_rejection(res):
            _reject(report, entry, f"close_worker: {str(err)[:160]}")
        else:
            report.dropped.append(f"close_worker: {str(err)[:160]}")
        return


def _is_uuid(value: str) -> bool:
    try:
        uuid.UUID(str(value))
        return True
    except (ValueError, TypeError, AttributeError):
        return False


async def execute(entries: list[dict], who: Identity, call: ApiCall) -> OutboxReport:
    report = OutboxReport()
    for entry in entries:
        tool = entry["tool"]
        if tool in {"spawn_worker", "send_to_worker", "merge_worker", "close_worker"}:
            if not is_orchestrator_identity(who):
                _reject(report, entry, f"{tool}: tool is restricted to role='orchestrator'")
                continue
            try:
                await _execute_orchestrator_tool(entry, who, call, report)
            except Exception as exc:  # noqa: BLE001 - one bad entry must not lose the turn's other entries
                report.dropped.append(f"{tool}: {type(exc).__name__}: {str(exc)[:120]}")
            continue
        # Only the broker can attach this field: parse_outbox strips unknown keys.
        planned = _request_for(tool, entry["args"], who, delivery_id=entry.get("_delivery_id", ""))
        if isinstance(planned, str):
            if tool in {"update_checklist", "update_progress"} or is_orchestrator_identity(who):
                _reject(report, entry, planned)
            else:
                report.dropped.append(planned)
            continue
        method, path, body = planned
        try:
            result = await call(method, path, body)
        except BookkeepingValidationError as exc:
            if tool == "update_checklist":
                _reject(report, entry, f"{tool}: {exc}")
            else:
                report.dropped.append(f"{tool}: {exc}")
            continue
        except Exception as exc:   # noqa: BLE001 - one bad entry must not lose the turn's other entries
            report.dropped.append(f"{tool}: {type(exc).__name__}: {str(exc)[:120]}")
            continue
        error = result.get("error") if isinstance(result, dict) else None
        if tool == "send_message":
            if report_receipt_accepted(result):
                error = None  # WAITING_QUOTA's error metadata describes a retained receipt.
            else:
                error = error or "parent report was not accepted"
        elif not (isinstance(result, dict) and result.get("ok") is True):
            error = error or "bookkeeping update was not acknowledged"
        if error:
            report.dropped.append(f"{tool}: {str(error)[:160]}")
        else:
            report.done.append(tool)
    for reason in report.dropped:
        logger.warning("hub outbox of %s: dropped %s", who.name, reason)
    return report


async def local_api_call(who: Identity, method: str, path: str, body: dict) -> object:
    """The session's own authority against the local Orchestra API (what its MCP process would use)."""
    import httpx

    from app.mcp_proof import issue_mcp_proof

    headers = {"X-Orchestra-Session-Id": who.session_id,
               "X-Orchestra-Mcp-Proof": issue_mcp_proof(who.session_id)}
    token = os.environ.get("INTERNAL_TOKEN", "")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    base = os.environ.get("ORCHESTRA_URL", "http://127.0.0.1:8888")
    req_json = None if method.upper() in {"GET", "DELETE"} and not body else body
    async with httpx.AsyncClient(base_url=base, timeout=30, headers=headers) as client:
        response = await client.request(method, path, json=req_json)
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    if not 200 <= response.status_code < 300:
        error = payload.get("error") if isinstance(payload, dict) else None
        # Only this owned endpoint's explicit 422/error response is known to be
        # a permanent validation refusal. HTTP/auth/ownership failures, malformed
        # replies and send_message outcomes must retain their ambiguity barrier.
        if (response.status_code == 422 and method == "POST"
                and path == f"/api/sessions/{quote(who.name, safe='')}/checklist"
                and isinstance(payload, dict)
                and payload.get("ok") is not True):
            if isinstance(error, str) and error:
                raise BookkeepingValidationError(error)
            detail = payload.get("detail")
            # FastAPI/Pydantic rejects malformed body fields before the handler.
            # An arbitrary 422/detail string or unknown error object is not proof.
            if error is None and isinstance(detail, list) and detail and all(
                isinstance(item, dict) and isinstance(item.get("loc"), list)
                and item["loc"] and item["loc"][0] == "body"
                and isinstance(item.get("msg"), str) and isinstance(item.get("type"), str)
                for item in detail
            ):
                raise BookkeepingValidationError(json.dumps(detail, ensure_ascii=False))
        out = {"error": error or f"HTTP {response.status_code}", "http_status": response.status_code}
        if isinstance(payload, dict) and "result" in payload:
            out["result"] = payload["result"]
        return out
    return payload


class HubBridge:
    """What the session gives its hub backend: who the worker is and how its outbox is run."""

    def __init__(self, identity: Callable[[], Identity], call: ApiCall | None = None,
                 *, on_parent_report: Callable[[Identity], None] | None = None):
        self._identity = identity
        self._call = call
        self._on_parent_report = on_parent_report

    def identity(self) -> Identity:
        return self._identity()

    async def run(self, entries: list[dict], *, mark_reported: bool = True) -> OutboxReport:
        who = self._identity()

        async def call(method: str, path: str, body: dict) -> object:
            if self._call is not None:
                result = await self._call(method, path, body)
            else:
                result = await local_api_call(who, method, path, body)
            if (
                self._on_parent_report is not None
                and mark_reported
                and method == "POST"
                and who.parent_name
                and path == f"/api/sessions/{quote(who.parent_name, safe='')}/send"
                and report_receipt_accepted(result)
            ):
                self._on_parent_report(who)
            return result
        return await execute(entries, who, call)
