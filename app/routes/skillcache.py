"""One endpoint for the Orchestra MCP, local CLI and the authenticated Kesha bridge."""

import hashlib
import hmac
import json
import logging
import os
import re
import time

from fastapi import APIRouter, Request
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse

from app.deps import manager
from app.mcp_proof import check_mcp_proof
from app.session import AgentStatus
from app.skillcache import service
from app.tool_scoping import role_tool_names

router = APIRouter()
logger = logging.getLogger(__name__)
ENDPOINT = "/api/skillcache/capsule-run"


def _orchestra_authorizer(request):
    session_id = request.headers.get("x-orchestra-session-id", "")
    proof = request.headers.get("x-orchestra-mcp-proof", "")
    session = manager.sessions.get(session_id)
    if not session or not check_mcp_proof(session_id, proof):
        return None

    def authorize():
        if (manager.sessions.get(session_id) is not session or session.status != AgentStatus.RUNNING
                or "capsule_run" in session.disabled_tools
                or not role_tool_names({"capsule_run"}, session.role)
                or getattr(session, "_skillcache_exclusion", None)):
            return None
        return service.access(service.settings(), principal=f"orchestra:{session_id}", scope=session.scope,
                              invocation=getattr(session, "_skillcache_invocation_id", None), origin="orchestra")

    return authorize


def _kesha_authorizer(request, body):
    chat = request.headers.get("x-skillcache-chat", "")
    invocation = request.headers.get("x-skillcache-invocation", "")
    timestamp = request.headers.get("x-skillcache-at", "")
    proof = request.headers.get("x-skillcache-proof", "")
    secret = os.environ.get("ORCHESTRA_SKILLCACHE_KESHA_KEY", "")
    if (len(secret) < 32 or not re.fullmatch(r"-?[0-9]{1,20}", chat)
            or not re.fullmatch(r"[a-f0-9]{32}", invocation)
            or not re.fullmatch(r"[0-9]{1,12}", timestamp)
            or not re.fullmatch(r"[a-f0-9]{64}", proof)):
        return None
    signed = f"skillcache-v1:{chat}:{invocation}:{timestamp}:".encode() + body
    if not hmac.compare_digest(hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest(), proof):
        return None

    def authorize():
        if abs(time.time() - int(timestamp)) > 90:
            return None
        return service.access(service.settings(), principal=f"kesha:{chat}", invocation=invocation, origin="kesha")

    return authorize


@router.post(ENDPOINT)
async def capsule_run(request: Request):
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 524288:
            return JSONResponse({"status": "invalid_request"}, status_code=413)
    authorize = (_kesha_authorizer(request, body) if "x-skillcache-proof" in request.headers
                 else _orchestra_authorizer(request))
    if authorize is None:
        return JSONResponse({"status": "revoked"}, status_code=403)
    try:
        args = json.loads(body)
    except (ValueError, RecursionError):
        return JSONResponse({"status": "invalid_request"}, status_code=400)
    try:
        return await run_in_threadpool(service.execute, args, authorize)
    except Exception as error:
        logger.warning("SkillCache execution unavailable (%s)", type(error).__name__)
        return {"status": "unavailable"}

