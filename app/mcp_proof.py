"""Bind an HTTP callback to one MCP process.

Closes the EASY path: one curl with the shared INTERNAL_TOKEN and a spoofed
X-Orchestra-Session-Id. That hole bypassed both acceptance_command (#240)
and waive_diff_budget (#250).

Does NOT close an agent with bash: read ~/.orchestra/mcp-config,
CODEX_HOME/*/config.toml, /proc/<mcp>/environ, UPDATE data/orchestra.db,
or rewrite this file. Against an executor who bypasses on purpose there is
no defense — they have a shell as kesha with full sudo. bash/curl/SQL
stay out of the model. Same wording as `_acceptance_command_from_caller`.

The proof lives only in that MCP process env (issued in `_make_mcp_config`,
re-issued on spawn / load / refresh_identity / reconnect). It is not in the
systemd/shared env. A clean channel needs this secret; we do not pretend
X-Orchestra-Session-Id is one.
"""

from __future__ import annotations

import hmac
import secrets

from fastapi import Request

PROOF_ENV = "ORCHESTRA_MCP_PROOF"
PROOF_HEADER = "x-orchestra-mcp-proof"

_proofs: dict[str, str] = {}


def issue_mcp_proof(session_id: str) -> str:
    sid = (session_id or "").strip()
    if not sid:
        return ""
    token = secrets.token_hex(32)
    _proofs[sid] = token
    return token


def check_mcp_proof(session_id: str, presented: str) -> bool:
    expected = _proofs.get((session_id or "").strip(), "")
    got = (presented or "").strip()
    if not expected or not got or len(expected) != len(got):
        return False
    return hmac.compare_digest(expected, got)


def caller_may_use_orchestrator_privilege(request: Request) -> bool:
    from app.auth import validate_session
    from app.db import get_session
    from app.diff_budget import may_waive_diff_budget

    if validate_session(request.cookies.get("session", "")):
        return True
    session_id = request.headers.get("x-orchestra-session-id", "").strip()
    presented = request.headers.get(PROOF_HEADER, "").strip()
    if not check_mcp_proof(session_id, presented):
        return False
    row = get_session(session_id)
    if not row:
        return False
    return may_waive_diff_budget(
        caller_role=str(row.get("role") or ""),
        caller_is_orchestrator=bool(row.get("is_orchestrator")),
    )
