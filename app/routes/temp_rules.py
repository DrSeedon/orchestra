"""Backend of the temp_rule_* MCP tools: temporary prompt rules set by orchestrators."""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app import temp_rules
from app.db import get_session
from app.mcp_proof import check_mcp_proof

router = APIRouter(prefix="/api/temp-rules", tags=["temp-rules"])


class RuleCreate(BaseModel):
    text: str
    reason: str = ""
    targets: list[str]
    mode: str = ""
    expires_at: str = ""
    project: str = ""


class RuleUpdate(BaseModel):
    expires_at: str = ""
    keep: bool = False
    text: str | None = None
    reason: str | None = None
    targets: list[str] | None = None
    mode: str | None = None


def _actor(request: Request) -> dict | None:
    session_id = request.headers.get("x-orchestra-session-id", "").strip()
    if not check_mcp_proof(session_id, request.headers.get("x-orchestra-mcp-proof", "")):
        return None
    return get_session(session_id)


def _run(call):
    try:
        return JSONResponse(call())
    except temp_rules.RuleError as error:
        return JSONResponse({"error": error.detail}, status_code=error.status_code)


@router.post("")
def create_rule(req: RuleCreate, request: Request):
    return _run(lambda: temp_rules.add_rule(
        _actor(request), req.text, req.reason, req.targets, req.mode, req.expires_at,
        project=req.project))


@router.get("")
def list_rules(request: Request, include_inactive: bool = False):
    return _run(lambda: temp_rules.list_rules(_actor(request), include_inactive=include_inactive))


@router.put("/{rule_id}")
def update_rule(rule_id: str, req: RuleUpdate, request: Request):
    return _run(lambda: temp_rules.update_rule(
        _actor(request), rule_id, **req.model_dump()))


@router.delete("/{rule_id}")
def remove_rule(rule_id: str, request: Request):
    return _run(lambda: temp_rules.remove_rule(_actor(request), rule_id))
