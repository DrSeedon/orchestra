"""Outbox of a hub worker: the only way its agent can reach Orchestra (V-1008).

The hub link is outbound only: the hub agent has no Orchestra tools and no path back. It appends
JSON lines ``{"tool": ..., "args": {...}}`` to ``.orchestra-outbox.jsonl`` in its copy; when the
broker syncs the turn back it reads that file (it never reaches the worktree or git) and runs
the entries itself, as the worker's own identity, through the same local API a native worker's
MCP process uses. Three tools only; anything else is dropped and reported.

Authority stays with the broker: the recipient of ``send_message`` is the worker's own parent,
whatever the entry says; ``file_path`` and every other unknown argument are ignored.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from dataclasses import dataclass, field
from typing import Awaitable, Callable
from urllib.parse import quote

from app.message_deliveries import report_receipt_accepted

logger = logging.getLogger(__name__)

OUTBOX_NAME = ".orchestra-outbox.jsonl"
ALLOWED_TOOLS = ("send_message", "update_checklist", "update_progress")
MAX_OUTBOX_BYTES = 256 * 1024
MAX_ENTRIES = 50
MAX_MESSAGE_CHARS = 20_000
MAX_STATUS_CHARS = 300

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


@dataclass
class OutboxReport:
    done: list[str] = field(default_factory=list)
    dropped: list[str] = field(default_factory=list)

    def summary(self) -> str:
        if not self.done and not self.dropped:
            return ""
        text = f"[hub outbox] {len(self.done)} delivered"
        if self.done:
            text += " (" + ", ".join(self.done[:10]) + ")"
        if self.dropped:
            text += f", {len(self.dropped)} dropped: " + "; ".join(self.dropped[:10])
        return text


def parse_outbox(data: bytes) -> tuple[list[dict], list[str]]:
    """(valid entries, reasons for everything dropped). Never raises on hostile content."""
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
        if entry["tool"] not in ALLOWED_TOOLS:
            dropped.append(f"line {number}: tool '{entry['tool'][:40]}' is not available to hub workers")
            continue
        entries.append({"tool": entry["tool"], "args": args})
    return entries, dropped


def _request_for(tool: str, args: dict, who: Identity) -> tuple[str, str, dict] | str:
    """(method, path, body) for an allowed tool, or the reason it cannot run."""
    if tool == "send_message":
        if not who.parent_name:
            return "send_message: this worker has no parent orchestrator"
        message = args.get("message")
        if not isinstance(message, str) or not message.strip():
            return "send_message: message must be non-empty text"
        # `to` is never read: a hub worker may talk to its own parent only.
        return ("POST", f"/api/sessions/{quote(who.parent_name, safe='')}/send", {
            "message": message[:MAX_MESSAGE_CHARS], "sender": who.name, "scope": who.scope,
            "delivery_id": str(uuid.uuid4())})
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


async def execute(entries: list[dict], who: Identity, call: ApiCall) -> OutboxReport:
    report = OutboxReport()
    for entry in entries:
        tool = entry["tool"]
        planned = _request_for(tool, entry["args"], who)
        if isinstance(planned, str):
            report.dropped.append(planned)
            continue
        method, path, body = planned
        try:
            result = await call(method, path, body)
        except Exception as exc:   # noqa: BLE001 - one bad entry must not lose the turn's other entries
            report.dropped.append(f"{tool}: {type(exc).__name__}: {str(exc)[:120]}")
            continue
        error = result.get("error") if isinstance(result, dict) else None
        if tool == "send_message":
            if report_receipt_accepted(result):
                error = None  # WAITING_QUOTA's error metadata describes a retained receipt.
            else:
                error = error or "parent report was not accepted"
        if error:
            report.dropped.append(f"{tool}: {str(error)[:160]}")
        else:
            report.done.append(tool)
    for reason in report.dropped:
        logger.warning("hub outbox of %s: dropped %s", who.name, reason)
    return report


async def local_api_call(who: Identity, method: str, path: str, body: dict) -> object:
    """The worker's own authority against the local Orchestra API (what its MCP process would use)."""
    import httpx

    from app.mcp_proof import issue_mcp_proof

    headers = {"X-Orchestra-Session-Id": who.session_id,
               "X-Orchestra-Mcp-Proof": issue_mcp_proof(who.session_id)}
    token = os.environ.get("INTERNAL_TOKEN", "")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    base = os.environ.get("ORCHESTRA_URL", "http://127.0.0.1:8888")
    async with httpx.AsyncClient(base_url=base, timeout=30, headers=headers) as client:
        response = await client.request(method, path, json=body)
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    if response.status_code >= 400 and not (isinstance(payload, dict) and payload.get("error")):
        return {"error": f"HTTP {response.status_code}"}
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

    async def run(self, entries: list[dict]) -> OutboxReport:
        who = self._identity()

        async def call(method: str, path: str, body: dict) -> object:
            if self._call is not None:
                result = await self._call(method, path, body)
            else:
                result = await local_api_call(who, method, path, body)
            if (
                self._on_parent_report is not None
                and method == "POST"
                and path == f"/api/sessions/{quote(who.parent_name, safe='')}/send"
                and report_receipt_accepted(result)
            ):
                self._on_parent_report(who)
            return result
        return await execute(entries, who, call)
