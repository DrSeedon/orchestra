"""Bind an HTTP callback to one MCP process.

Closes the EASY path: one curl with the shared INTERNAL_TOKEN and a spoofed
X-Orchestra-Session-Id. That hole bypassed both acceptance_command (#240)
and waive_diff_budget (#250).

Does NOT close an agent with bash: read ~/.orchestra/mcp-config,
CODEX_HOME/*/config.toml, /proc/<mcp>/environ, UPDATE data/orchestra.db,
or rewrite this file. Against an executor who bypasses on purpose there is
no defense — they have a shell as kesha with full sudo. bash/curl/SQL
stay out of the model. Same wording as `_acceptance_command_from_caller`.

The proof is derived from the server's existing INTERNAL_TOKEN and the session
id. Configuration may be rebuilt while that process is still serving a live
turn, and adopted processes keep working across server generations. The proof
is still passed only in the MCP process env; a clean channel needs this secret,
and we do not pretend X-Orchestra-Session-Id is one.
"""

from __future__ import annotations

import hashlib
import hmac
import os

from fastapi import Request

PROOF_ENV = "ORCHESTRA_MCP_PROOF"
PROOF_HEADER = "x-orchestra-mcp-proof"


def issue_mcp_proof(session_id: str) -> str:
    """Derive the session proof from the server secret, not process state."""
    sid = (session_id or "").strip()
    secret = os.environ.get("INTERNAL_TOKEN", "")
    if not sid or not secret:
        return ""
    return hmac.new(
        secret.encode(), f"mcp-proof:{sid}".encode(), hashlib.sha256,
    ).hexdigest()


def check_mcp_proof(session_id: str, presented: str) -> bool:
    expected = issue_mcp_proof(session_id)
    got = (presented or "").strip()
    if not expected or not got or len(expected) != len(got):
        return False
    return hmac.compare_digest(expected, got)


def orchestrator_principal(request: Request) -> str:
    """Authenticated accepting actor; never copied from a request-body claim."""
    from app.auth import validate_session
    from app.db import get_session
    from app.diff_budget import may_waive_diff_budget

    if validate_session(request.cookies.get("session", "")):
        return "owner"
    session_id = request.headers.get("x-orchestra-session-id", "").strip()
    presented = request.headers.get(PROOF_HEADER, "").strip()
    if not check_mcp_proof(session_id, presented):
        return ""
    row = get_session(session_id)
    if not row:
        return ""
    permitted = may_waive_diff_budget(
        caller_role=str(row.get("role") or ""),
        caller_is_orchestrator=bool(row.get("is_orchestrator")),
    )

    return session_id if permitted else ""


def caller_may_use_orchestrator_privilege(request: Request) -> bool:
    return bool(orchestrator_principal(request))


def work_acceptor_principal(request: Request, target: dict, target_branch: str) -> str:
    """A full-cycle parent may accept its own child into its own non-main branch."""
    principal = orchestrator_principal(request)
    if principal:
        return principal
    from app.db import get_session
    sid = request.headers.get("x-orchestra-session-id", "").strip()
    if not check_mcp_proof(sid, request.headers.get(PROOF_HEADER, "")):
        return ""
    parent = get_session(sid) or {}
    branch = str(parent.get("branch") or "")
    if (parent.get("role") == "full-cycle" and target.get("parent_id") == sid
            and target.get("id") != sid and parent.get("scope") == target.get("scope")
            and branch and branch not in {"main", "master", parent.get("base_branch")}
            and target_branch == branch):
        return sid
    return ""
