"""V-614: shadow verdict — was there a passing check after the last code edit before DONE.

Idea from Canny (see `.orchestra/tasks/V-613/research.md` §2.1): our own `logs` table
already carries every fact needed, so this uses no external hook and no Jev call.
Currently SHADOW ONLY: `record_verdict` only writes a `logs` row (type
``done_gate_verdict``) for later analysis; it never blocks, delays or changes the text
of `send_message`, and it is never shown to the worker. Any failure inside this module
is swallowed — a broken gate must never break a DONE report.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, replace
from datetime import datetime, timezone

from app import db
from app.events import MessageProvenance

logger = logging.getLogger("done_gate")

# Скан ограничен последними N tool-строк сессии: полный DONE-отчёт наступает намного
# раньше этого предела, а лимит защищает от полного скана многотысячной истории.
_SCAN_LIMIT = 4000

_DEFAULT_CODE_EXT = (
    r"\.(py|js|mjs|cjs|ts|tsx|jsx|css|html|sh|go|rs|sql|java|kt|swift|c|cc|cpp|h|rb|php|vue|svelte)$"
)
_DEFAULT_EDIT_TOOLS = (
    "Edit", "Write", "MultiEdit", "NotebookEdit", "FileChange",
    "apply_patch", "edit", "write_file", "file",
)
_DEFAULT_CHECK_PATTERN = (
    r"\b(pytest|unittest|npm (run )?test|pnpm (run )?test|yarn test|vitest|jest|tsc\b|"
    r"ruff|eslint|mypy|pyright|go test|cargo (test|check|build)|node --test|"
    r"playwright test|make (test|check)|py_compile|check_instruction_contract|"
    r"npm run (build|lint|check)|node --check)"
)
# Как у Canny: `| tail`, `|| true`, `; echo` не признаются проверкой — они могут
# скрыть ненулевой код возврата.
_DEFAULT_NON_STRICT_PATTERN = r"\|\s*(tail|head|grep)\b|\|\|\s*true|;\s*echo\b"
_DEFAULT_IGNORED_PREFIXES = (".orchestra/", "docs/")
_SHELL_TOOLS = ("Bash", "bash", "run_terminal_command", "shell")


@dataclass(frozen=True)
class DoneGateConfig:
    code_ext: str = _DEFAULT_CODE_EXT
    edit_tools: tuple[str, ...] = _DEFAULT_EDIT_TOOLS
    check_pattern: str = _DEFAULT_CHECK_PATTERN
    non_strict_pattern: str = _DEFAULT_NON_STRICT_PATTERN
    ignored_prefixes: tuple[str, ...] = _DEFAULT_IGNORED_PREFIXES


DEFAULT_CONFIG = DoneGateConfig()


def _kv_key(scope: str) -> str:
    return f"done_gate_config:{scope}"


def load_config(scope: str) -> DoneGateConfig:
    """Per-scope override stored in `kv` (no schema change); falls back to defaults."""
    raw = db.kv_get(_kv_key(scope), "")
    if not raw:
        return DEFAULT_CONFIG
    try:
        override = json.loads(raw)
    except (TypeError, ValueError):
        logger.warning("done_gate config for scope=%r is not valid JSON, using defaults", scope)
        return DEFAULT_CONFIG
    if not isinstance(override, dict):
        return DEFAULT_CONFIG
    fields: dict[str, object] = {}
    for name in ("code_ext", "check_pattern", "non_strict_pattern"):
        value = override.get(name)
        if isinstance(value, str) and value:
            fields[name] = value
    for name in ("edit_tools", "ignored_prefixes"):
        value = override.get(name)
        if isinstance(value, list) and value and all(isinstance(v, str) for v in value):
            fields[name] = tuple(value)
    if not fields:
        return DEFAULT_CONFIG
    return replace(DEFAULT_CONFIG, **fields)


def set_config_override(scope: str, override: dict) -> None:
    """Test/ops helper: store a per-scope override. Empty dict clears it."""
    if override:
        db.kv_set(_kv_key(scope), json.dumps(override, ensure_ascii=False))
    else:
        db.kv_delete(_kv_key(scope))


def _tool_name(row) -> str:
    name = row["tool_name"]
    if name:
        return name
    content = row["content"] or ""
    i = content.find(":")
    return content[:i] if 0 < i < 60 else ""


def _paths_from_content(name: str, content: str) -> list[str]:
    body = content.split(":", 1)[1] if ":" in content else content
    if name == "file":
        return [body.strip().split(" ", 1)[-1]]
    try:
        data = json.loads(body)
    except (TypeError, ValueError):
        return re.findall(r'"(?:file_path|path|notebook_path)":\s*"([^"]+)"', body)
    if isinstance(data, dict):
        changes = data.get("changes")
        if isinstance(changes, list):
            return [c.get("path", "") for c in changes if isinstance(c, dict)]
        for key in ("file_path", "path", "notebook_path"):
            if key in data:
                return [data[key]]
    return []


def _command_from_content(content: str) -> str:
    body = content.split(":", 1)[1] if ":" in content else content
    try:
        data = json.loads(body)
    except (TypeError, ValueError):
        return body
    return data.get("command", "") if isinstance(data, dict) else str(data)


def _is_ignored(path: str, prefixes: tuple[str, ...]) -> bool:
    probe = "/" + path
    return any(("/" + prefix) in probe or path.startswith(prefix) for prefix in prefixes)


def evaluate(session_id: str, scope: str) -> dict:
    """Replays one session's tool log to find: last code edit, and whether a passing,
    strict check ran after it. Pure read — never mutates state."""
    config = load_config(scope)
    code_re = re.compile(config.code_ext)
    check_re = re.compile(config.check_pattern)
    non_strict_re = re.compile(config.non_strict_pattern)

    with db._conn() as connection:
        raw_rows = connection.execute(
            "SELECT id, ts, type, content, tool_use_id, tool_name, tool_is_error "
            "FROM logs WHERE session_id=? AND type IN ('tool','tool_result') "
            "ORDER BY id DESC LIMIT ?",
            (session_id, _SCAN_LIMIT),
        ).fetchall()
    rows = [dict(r) for r in reversed(raw_rows)]
    results_by_use_id = {
        r["tool_use_id"]: r for r in rows
        if r["type"] == "tool_result" and r["tool_use_id"]
    }

    last_edit: dict | None = None
    last_edit_paths: list[str] = []
    checked_after = False
    check_command = ""

    for idx, row in enumerate(rows):
        if row["type"] != "tool":
            continue
        name = _tool_name(row)
        if name in config.edit_tools:
            candidates = [
                p for p in _paths_from_content(name, row["content"] or "")
                if p and code_re.search(p)
            ]
            code_paths = [p for p in candidates if not _is_ignored(p, config.ignored_prefixes)]
            if code_paths:
                last_edit = row
                last_edit_paths = code_paths
                checked_after = False
                check_command = ""
        elif name in _SHELL_TOOLS and last_edit is not None:
            command = _command_from_content(row["content"] or "")
            if check_re.search(command) and not non_strict_re.search(command):
                result = results_by_use_id.get(row["tool_use_id"])
                if result is None and idx + 1 < len(rows) and rows[idx + 1]["type"] == "tool_result":
                    result = rows[idx + 1]
                ok = result is not None and not result["tool_is_error"]
                if ok:
                    checked_after = True
                    check_command = command

    return {
        "has_code_edit": last_edit is not None,
        "last_edit_file": last_edit_paths[0] if last_edit_paths else "",
        "last_edit_ts": last_edit["ts"] if last_edit else "",
        "checked": checked_after,
        "check_command": check_command if checked_after else "",
        "flag": last_edit is not None and not checked_after,
    }


def record_verdict(
    *, session_id: str, scope: str, task_id: str, worker_name: str, message: str,
) -> dict | None:
    """Evaluate and persist a shadow verdict. Never raises — a gate failure must not
    touch `send_message`. Returns the payload written, or None if nothing was recorded."""
    try:
        verdict = evaluate(session_id, scope)
    except Exception:
        logger.exception("done_gate evaluate failed for session=%s", session_id)
        return None
    payload = {
        "session_id": session_id,
        "scope": scope,
        "task_id": task_id,
        "worker_name": worker_name,
        "message_prefix": message[:80],
        **verdict,
    }
    try:
        db.add_log(
            session_id,
            datetime.now(timezone.utc),
            "done_gate_verdict",
            json.dumps(payload, ensure_ascii=False),
            provenance=MessageProvenance(
                origin="platform", senders=("done_gate",), subtype="verdict",
            ),
        )
    except Exception:
        logger.exception("done_gate record failed for session=%s", session_id)
        return None
    return payload


def maybe_record(
    *, source_session_id: str | None, source_scope: str, source_task_id: str,
    source_name: str, message: str,
) -> dict | None:
    """Gate entry point for a worker `send_message`: only DONE reports, only non-orchestrators."""
    if not source_session_id:
        return None
    if not isinstance(message, str) or not message.lstrip().startswith("DONE"):
        return None
    try:
        source = db.get_session(source_session_id)
    except Exception:
        logger.exception("done_gate could not load source session=%s", source_session_id)
        return None
    if not source:
        return None
    if source.get("is_orchestrator") or source.get("role") in ("orchestrator", "sub-orchestrator"):
        return None
    return record_verdict(
        session_id=source_session_id,
        scope=source_scope,
        task_id=source_task_id,
        worker_name=source_name or str(source.get("name") or ""),
        message=message,
    )
