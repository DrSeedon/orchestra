"""Authenticated publication and narrowly exempted private artifact-link routes."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import re
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from pydantic import BaseModel

from app import artifacts
from app.auth import check_internal_token, require_operator_session
from app.db import get_session
from app.mcp_proof import check_mcp_proof

router = APIRouter()


class PublishRequest(BaseModel):
    path: str
    caption: str = ""
    ttl_seconds: int | None = None


def _not_found() -> Response:
    return JSONResponse({"error": "not found"}, status_code=404)


def _private_headers() -> dict[str, str]:
    return {
        "Cache-Control": "no-store, private, max-age=0",
        "Referrer-Policy": "no-referrer",
        "X-Content-Type-Options": "nosniff",
    }


def _wrapper_csp(script: str) -> str:
    digest = base64.b64encode(hashlib.sha256(script.encode()).digest()).decode()
    return (
        "default-src 'none'; "
        f"script-src 'sha256-{digest}'; "
        "connect-src 'self'; frame-src 'self'; base-uri 'none'; "
        "form-action 'none'; frame-ancestors 'none'"
    )


_BOOTSTRAP_SCRIPT = """(() => {
const capability = location.hash.slice(1);
history.replaceState(null, "", location.pathname);
if (!/^[A-Za-z0-9_-]{43}$/.test(capability)) return;
let attempts = 0;
const redeem = () => fetch(location.pathname + "/redeem", {
  method: "POST", credentials: "same-origin",
  headers: {"Content-Type": "application/json"},
  body: JSON.stringify({capability})
}).then((response) => {
  if (response.ok) location.reload();
  else if (response.status === 404 && attempts++ < 20) setTimeout(redeem, 250);
});
redeem();
})();"""

_WRAPPER_SCRIPT = """(() => {
const frame = document.getElementById("artifact");
frame.src = location.pathname + "/content";
})();"""


def _bootstrap() -> HTMLResponse:
    body = (
        "<!doctype html><meta charset=\"utf-8\"><title>Artifact</title>"
        f"<script>{_BOOTSTRAP_SCRIPT}</script>"
    )
    return HTMLResponse(body, headers={**_private_headers(), "Content-Security-Policy": _wrapper_csp(_BOOTSTRAP_SCRIPT)})


def _wrapper() -> HTMLResponse:
    body = (
        "<!doctype html><meta charset=\"utf-8\"><title>Artifact</title>"
        '<iframe id="artifact" sandbox="allow-scripts" referrerpolicy="no-referrer"></iframe>'
        f"<script>{_WRAPPER_SCRIPT}</script>"
    )
    return HTMLResponse(body, headers={**_private_headers(), "Content-Security-Policy": _wrapper_csp(_WRAPPER_SCRIPT)})


def _publisher(request: Request) -> dict[str, Any] | None:
    if not check_internal_token(request.headers.get("authorization", "")):
        return None
    session_id = request.headers.get("x-orchestra-session-id", "").strip()
    proof = request.headers.get("x-orchestra-mcp-proof", "").strip()
    if not session_id or not check_mcp_proof(session_id, proof):
        return None
    return get_session(session_id)


def _allowed_roots(session: dict[str, Any]) -> tuple[str, ...]:
    roots = []
    for key in ("cwd", "worktree_path"):
        value = str(session.get(key) or "")
        if value and value not in roots:
            roots.append(value)
    return tuple(roots)


async def send_text_to_tg(text: str, *, scope: str, sender: str, disable_link_preview: bool = False) -> dict:
    from app.tg_bridge import send_text_to_tg as sender_fn
    return await sender_fn(text, scope=scope, sender=sender, disable_link_preview=disable_link_preview)


async def send_file_to_tg(*args, **kwargs):
    from app.tg_bridge import send_file_to_tg as sender_fn
    return await sender_fn(*args, **kwargs)


@router.post("/api/artifacts/publish")
async def publish_artifact(request: Request, req: PublishRequest):
    session = _publisher(request)
    if not session:
        return JSONResponse({"error": "artifact publisher proof required"}, status_code=403)
    cfg = artifacts.load_artifact_config()
    ttl = cfg.default_ttl if req.ttl_seconds is None else req.ttl_seconds
    try:
        published = artifacts.publish_snapshot(
            source_path=req.path,
            allowed_roots=_allowed_roots(session),
            publisher_session_id=str(session["id"]),
            publisher_name=str(session.get("name") or "publisher"),
            scope=str(session.get("scope") or ""),
            ttl_seconds=ttl,
        )
    except Exception:
        return JSONResponse({"error": "artifact publication failed; use send_file(path, as_document=True)"}, status_code=400)

    locator = published["id"]
    capability = published["capability"]
    url = artifacts.public_url(locator, capability)
    try:
        try:
            activated = artifacts.activate_artifact(locator)
        except Exception:
            activated = False
        if not activated:
            # Keep the activation-failure contract observable as a dead link, while never
            # exposing a redeemable capability.  The normal path below is active before send.
            try:
                await send_text_to_tg(
                    url,
                    scope=str(session.get("scope") or ""),
                    sender=str(session.get("name") or "publisher"),
                    disable_link_preview=True,
                )
            finally:
                artifacts.discard_pending_artifact(locator)
            return JSONResponse(
                {"error": "artifact link activation failed; use send_file(path, as_document=True)"},
                status_code=502,
            )
        delivered = await send_text_to_tg(
            url,
            scope=str(session.get("scope") or ""),
            sender=str(session.get("name") or "publisher"),
            disable_link_preview=True,
        )
        if not isinstance(delivered, dict) or delivered.get("ok") is not True:
            artifacts.discard_artifact(locator)
            return JSONResponse(
                {"error": "artifact link delivery failed; use send_file(path, as_document=True)"},
                status_code=502,
            )
        return {
            "ok": True,
            "artifact_id": locator,
            "expires_at": published["expires_at"],
            "message_id": delivered.get("message_id"),
        }
    except asyncio.CancelledError:
        artifacts.discard_artifact(locator)
        raise
    except Exception:
        artifacts.discard_artifact(locator)
        return JSONResponse(
            {"error": "artifact link delivery failed; use send_file(path, as_document=True)"},
            status_code=502,
        )


@router.post("/api/artifacts/{locator}/revoke")
async def revoke_artifact(locator: str, request: Request):
    if not re.fullmatch(r"[A-Za-z0-9_-]{22}", locator):
        return _not_found()
    operator = False
    try:
        require_operator_session(request)
        operator = True
    except Exception:
        operator = False
    if not operator:
        session = _publisher(request)
        if not session:
            return JSONResponse({"error": "artifact revoke requires publisher proof"}, status_code=403)
        row = artifacts._artifact_row(locator)
        if not row or row["publisher_session_id"] != session["id"]:
            return JSONResponse({"error": "artifact revoke forbidden"}, status_code=403)
    artifacts.revoke_artifact(locator)
    return {"ok": True}


@router.api_route("/api/artifacts/open/{locator}", methods=["GET", "HEAD"])
async def open_artifact(locator: str, request: Request):
    if not re.fullmatch(r"[A-Za-z0-9_-]{22}", locator):
        return _not_found()
    value = request.cookies.get("orchestra_artifact_grant", "")
    if artifacts.verify_grant(locator, value):
        return _wrapper()
    return _bootstrap()


@router.post("/api/artifacts/open/{locator}/redeem")
async def redeem_artifact(locator: str, request: Request):
    if not re.fullmatch(r"[A-Za-z0-9_-]{22}", locator):
        return _not_found()
    try:
        payload = await request.json()
    except Exception:
        return _not_found()
    capability = payload.get("capability") if isinstance(payload, dict) else None
    if not isinstance(capability, str) or not re.fullmatch(r"[A-Za-z0-9_-]{43}", capability):
        return _not_found()
    cfg = artifacts.load_artifact_config()
    row = artifacts._artifact_row(locator)
    if not cfg.enabled or not row or row["state"] != "active":
        return _not_found()
    expected = artifacts._capability_verifier(capability, cfg.secret)
    if not __import__("hmac").compare_digest(bytes(row["capability_verifier"]), expected):
        return _not_found()
    import time
    now = int(time.time())
    if int(row["expires_at"]) <= now:
        return _not_found()
    grant = artifacts.grant_value(locator, int(row["expires_at"]), cfg.secret)
    response = Response(status_code=204)
    response.set_cookie(
        "orchestra_artifact_grant", grant,
        max_age=max(1, int(row["expires_at"]) - now),
        path=f"/api/artifacts/open/{locator}", secure=True, httponly=True, samesite="strict",
    )
    return response


@router.get("/api/artifacts/open/{locator}/content")
async def artifact_content(locator: str, request: Request):
    if not re.fullmatch(r"[A-Za-z0-9_-]{22}", locator):
        return _not_found()
    if request.headers.get("sec-fetch-dest", "") != "iframe":
        return _not_found()
    if not artifacts.verify_grant(locator, request.cookies.get("orchestra_artifact_grant", "")):
        return _not_found()
    if "range" in request.headers:
        return Response(status_code=416, headers=_private_headers())
    try:
        body = artifacts.open_artifact_buffer(locator)
    except Exception:
        return _not_found()
    headers = {
        **_private_headers(),
        "Content-Security-Policy": (
            "sandbox allow-scripts; default-src 'none'; script-src 'unsafe-inline'; "
            "style-src 'unsafe-inline'; img-src data: blob:; font-src data:; "
            "media-src data: blob:; connect-src 'none'; object-src 'none'; "
            "base-uri 'none'; form-action 'none'; frame-src 'none'; frame-ancestors 'self'"
        ),
    }
    return Response(body, media_type="text/html", headers=headers)
