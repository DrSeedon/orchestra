"""Shared authorization and error mapping for always-on REST resources."""
from fastapi import HTTPException, Request
from app import db
from app.auth import is_auth_enabled, require_operator_csrf, require_operator_session
from app.mcp_proof import check_mcp_proof


def actor(request: Request):
    session_id = request.headers.get("x-orchestra-session-id","").strip()
    if session_id:
        if not check_mcp_proof(session_id,request.headers.get("x-orchestra-mcp-proof","")):
            raise HTTPException(403,"valid MCP identity required")
        result = db.get_session(session_id)
        if result is None:
            raise HTTPException(403,"unknown session")
        return result
    # A missing session header must not turn an internal agent token into an operator.
    if is_auth_enabled():
        if request.method in {"GET", "HEAD"}:
            require_operator_session(request)
        else:
            require_operator_csrf(request)
    return None


def address(request,recipient=None,scope=None):
    who = actor(request)
    if who:
        if (recipient is not None and recipient != who["name"]) or (scope is not None and scope != who["scope"]):
            raise HTTPException(403,"resource belongs to another session")
        return who["name"],who["scope"]
    return recipient,scope


def owned(request,table,resource_id):
    # Table names are fixed by router code, never taken from request input.
    who = actor(request)
    with db._conn() as c:
        row = c.execute(f"SELECT * FROM {table} WHERE id=?",(resource_id,)).fetchone()
    if row is None:
        raise HTTPException(404,"resource not found")
    if who and (row["recipient"],row["scope"]) != (who["name"],who["scope"]):
        raise HTTPException(403,"resource belongs to another session")
    return dict(row)


def operator(request):
    if request.headers.get("x-orchestra-session-id"):
        raise HTTPException(403,"operator decision required")
    if is_auth_enabled():
        require_operator_csrf(request)


def validated(call):
    try:
        return call()
    except (ValueError,KeyError,TypeError) as error:
        raise HTTPException(422,str(error)) from error
