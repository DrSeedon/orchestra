"""Sub-agent telemetry + transcript routes.

Telemetry (tokens/summary/output_file/status) comes from the DB `subagents`
table (populated from Task* SDK messages). Full transcripts are read lazily
from the SDK's JSONL store via list_subagents / get_subagent_messages — NOT
duplicated in our DB. For local_agent tasks the SDK task_id is the transcript
agent_id; local_bash tasks are background processes and have no transcript.
"""

import logging
import re
from datetime import datetime

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.db import get_subagent, get_subagents, get_session

logger = logging.getLogger("orchestra.subagent")

router = APIRouter(tags=["subagent"])

_SAFE_ID = re.compile(r"^[\w-]+$")  # agent_id goes into a filename — no path traversal


def _duration_ms(row: dict) -> int:
    """Return SDK duration or derive wall time for legacy/background rows."""
    duration = int(row.get("duration_ms") or 0)
    if duration or not row.get("started_at") or not row.get("ended_at"):
        return duration
    try:
        started = datetime.fromisoformat(row["started_at"])
        ended = datetime.fromisoformat(row["ended_at"])
    except (TypeError, ValueError):
        return 0
    return max(0, round((ended - started).total_seconds() * 1000))


def _transcript_ids(rows: list[dict], cwd: str) -> set[str]:
    """Find persisted local-agent transcripts across all SDK session rotations."""
    from claude_agent_sdk import list_subagents

    wanted_by_sdk: dict[str, set[str]] = {}
    for row in rows:
        if row.get("task_type") == "local_bash":
            continue
        sdk_id = row.get("sdk_session_id") or ""
        task_id = row.get("task_id") or ""
        if sdk_id and task_id:
            wanted_by_sdk.setdefault(sdk_id, set()).add(task_id)

    available: set[str] = set()
    for sdk_id, wanted in wanted_by_sdk.items():
        try:
            available.update(wanted.intersection(list_subagents(sdk_id, cwd or None)))
        except Exception as e:
            logger.warning("list_subagents failed for %s: %s", sdk_id, e)
    return available


@router.get("/api/subagents/{session_id}")
async def subagents_list(session_id: str):
    """Telemetry for real SDK agents and background tasks, explicitly typed."""
    rows = get_subagents(session_id)
    sess = get_session(session_id)
    available = _transcript_ids(rows, (sess or {}).get("cwd") or "") if sess else set()
    out = []
    for source in rows:
        row = dict(source)
        is_background = row.get("task_type") == "local_bash"
        row["kind"] = "background" if is_background else "agent"
        row["duration_ms"] = _duration_ms(row)
        row["transcript_id"] = (
            row.get("task_id") or ""
        ) if not is_background and row.get("task_id") in available else ""
        out.append(row)
    return {"subagents": out}


@router.get("/api/subagent-transcripts/{session_id}")
async def subagent_transcript_ids(session_id: str):
    """SDK agent_ids represented by telemetry, including older SDK sessions."""
    sess = get_session(session_id)
    if not sess:
        return JSONResponse({"error": "session not found"}, status_code=404)
    rows = get_subagents(session_id)
    if not rows and not (sess.get("session_id") or ""):
        return {"agent_ids": [], "note": "no sdk_session_id yet"}
    agent_ids = _transcript_ids(rows, sess.get("cwd") or "")
    current_sdk_id = sess.get("session_id") or ""
    if current_sdk_id:
        from claude_agent_sdk import list_subagents
        try:
            agent_ids.update(list_subagents(
                current_sdk_id,
                sess.get("cwd") or None,
            ))
        except Exception as e:
            logger.warning("list_subagents failed for %s: %s", current_sdk_id, e)
    return {"agent_ids": sorted(agent_ids), "sdk_session_id": current_sdk_id}


@router.get("/api/subagent-transcript/{session_id}/{agent_id}")
async def subagent_transcript(session_id: str, agent_id: str, limit: int = 200, offset: int = 0):
    """Full conversation of one sub-agent (lazy read from SDK JSONL store)."""
    if not _SAFE_ID.match(agent_id):
        return JSONResponse({"error": "invalid agent_id"}, status_code=400)
    sess = get_session(session_id)
    if not sess:
        return JSONResponse({"error": "session not found"}, status_code=404)
    telemetry = get_subagent(session_id, agent_id)
    if telemetry and telemetry.get("task_type") == "local_bash":
        return {
            "messages": [],
            "note": "background tasks do not have transcripts",
        }
    sdk_id = (
        (telemetry or {}).get("sdk_session_id")
        or sess.get("session_id")
        or ""
    )
    if not sdk_id:
        return {"messages": [], "note": "no sdk_session_id yet"}
    from claude_agent_sdk import get_subagent_messages
    try:
        msgs = get_subagent_messages(sdk_id, agent_id, sess.get("cwd") or None,
                                     limit=limit, offset=offset)
    except Exception as e:
        logger.warning(f"get_subagent_messages failed: {e}")
        return {"messages": [], "error": str(e)}
    out = []
    for m in msgs:
        content = m.message.get("content") if isinstance(m.message, dict) else m.message
        out.append({"type": m.type, "content": content,
                    "parent_tool_use_id": getattr(m, "parent_tool_use_id", None)})
    return {"messages": out, "count": len(out)}
