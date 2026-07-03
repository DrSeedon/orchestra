"""Sub-agent telemetry + transcript routes.

Telemetry (tokens/summary/output_file/status) comes from the DB `subagents`
table (populated from Task* SDK messages). Full transcripts are read lazily
from the SDK's JSONL store via list_subagents / get_subagent_messages — NOT
duplicated in our DB. agent_id (SDK file id) != task_id (Task message id), so
transcript listing is independent of the telemetry table.
"""

import logging
import re

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.db import get_subagents, get_session

logger = logging.getLogger("orchestra.subagent")

router = APIRouter(tags=["subagent"])

_SAFE_ID = re.compile(r"^[\w-]+$")  # agent_id goes into a filename — no path traversal


@router.get("/api/subagents/{session_id}")
async def subagents_list(session_id: str):
    """Telemetry rows for a session's sub-agents (from Task* messages)."""
    return {"subagents": get_subagents(session_id)}


@router.get("/api/subagent-transcripts/{session_id}")
async def subagent_transcript_ids(session_id: str):
    """SDK agent_ids of sub-agents whose transcripts exist for this session."""
    sess = get_session(session_id)
    if not sess:
        return JSONResponse({"error": "session not found"}, status_code=404)
    sdk_id = sess.get("session_id") or ""
    if not sdk_id:
        return {"agent_ids": [], "note": "no sdk_session_id yet"}
    from claude_agent_sdk import list_subagents
    try:
        agent_ids = list_subagents(sdk_id, sess.get("cwd") or None)
    except Exception as e:
        logger.warning(f"list_subagents failed: {e}")
        return {"agent_ids": [], "error": str(e)}
    return {"agent_ids": agent_ids, "sdk_session_id": sdk_id}


@router.get("/api/subagent-transcript/{session_id}/{agent_id}")
async def subagent_transcript(session_id: str, agent_id: str, limit: int = 200, offset: int = 0):
    """Full conversation of one sub-agent (lazy read from SDK JSONL store)."""
    if not _SAFE_ID.match(agent_id):
        return JSONResponse({"error": "invalid agent_id"}, status_code=400)
    sess = get_session(session_id)
    if not sess:
        return JSONResponse({"error": "session not found"}, status_code=404)
    sdk_id = sess.get("session_id") or ""
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
