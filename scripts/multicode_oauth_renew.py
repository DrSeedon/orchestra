#!/usr/bin/env python3
"""Renew the MultiCode Hub MCP OAuth session without browser interaction."""

from __future__ import annotations

import argparse
import base64
import hashlib
import http.server
import json
import os
import secrets
import shlex
import socketserver
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

HUB_KEY = "/home/kesha/.ssh/multicode_hub_vps"
HUB = "<hub-user>@<hub-host>"
HUB_BASE_DIR = "/home/<hub-user>/.t3"
BASE = "http://127.0.0.1:14606"
CALLBACK_PORT = 18765
TOKEN_PATH = Path("/home/kesha/orchestra/data/secrets/multicode-oauth.token")
SCOPES = ("orchestration:read", "orchestration:operate", "settings:write", "source-control:write")
CLIENT_NAME = "Orchestra VPS"
PROTOCOL_VERSION = "2025-06-18"
DAY_MS = 24 * 60 * 60 * 1000


def pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def build_authorization_request(client_id: str, redirect_uri: str, challenge: str,
                                state: str, resource: str) -> dict[str, str]:
    return {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": state,
        "resource": resource,
    }


def build_decision_payload(authorization: dict[str, str], pairing_code: str) -> dict[str, Any]:
    return {"authorization": authorization,
            "decision": {"_tag": "pairing-code", "access": "full-access", "code": pairing_code}}


def build_token_request(code: str, redirect_uri: str, client_id: str,
                        verifier: str, resource: str) -> dict[str, str]:
    return {"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri,
            "client_id": client_id, "code_verifier": verifier, "resource": resource}


def token_claims(token: str) -> dict[str, Any]:
    parts = token.split(".")
    if len(parts) != 2:
        raise RuntimeError("Existing MultiCode token has an unsupported format")
    try:
        payload = base64.urlsafe_b64decode(parts[0] + "=" * (-len(parts[0]) % 4))
        claims = json.loads(payload)
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
        raise RuntimeError("Existing MultiCode token claims could not be read") from None
    if not isinstance(claims, dict) or claims.get("sub") != "mcp-client" or not claims.get("sid"):
        raise RuntimeError("Existing token is not an MCP client session")
    return claims


def renewal_decision(expires_at_ms: int, threshold_days: int,
                     *, now_ms: int | None = None) -> tuple[bool, float]:
    if threshold_days < 0:
        raise ValueError("expiration threshold cannot be negative")
    if now_ms is None:
        now_ms = int(time.time() * 1000)
    days_left = (expires_at_ms - now_ms) / DAY_MS
    return days_left > threshold_days, days_left


def atomic_write_token(path: Path, token: str) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as target:
            target.write(token.encode("ascii"))
            target.flush()
            os.fsync(target.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def request_json(url: str, *, body: dict[str, Any] | None = None,
                 form: bool = False, headers: dict[str, str] | None = None,
                 bearer: str | None = None, session_id: str | None = None,
                 redact: tuple[str, ...] = (),
                 timeout: float = 20) -> tuple[int, Any, dict[str, str]]:
    request_headers = dict(headers or {})
    if bearer:
        request_headers["Authorization"] = f"Bearer {bearer}"
    if session_id:
        request_headers["Mcp-Session-Id"] = session_id
    data = None
    if body is not None:
        if form:
            data = urllib.parse.urlencode(body).encode()
            request_headers["Content-Type"] = "application/x-www-form-urlencoded"
        else:
            data = json.dumps(body).encode()
            request_headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=request_headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw = response.read()
            response_headers = dict(response.headers.items())
            content_type = next((value for key, value in response_headers.items()
                                 if key.lower() == "content-type"), "")
            if raw and "text/event-stream" in content_type:
                events = [line[5:].strip() for line in raw.decode().splitlines()
                          if line.startswith("data:") and line[5:].strip() != "[DONE]"]
                parsed = json.loads(events[-1]) if events else {}
            else:
                parsed = json.loads(raw) if raw else {}
            return response.status, parsed, response_headers
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")[:500]
        for secret in (bearer, *redact):
            if secret:
                detail = detail.replace(secret, "[redacted]")
        raise RuntimeError(f"Hub returned HTTP {error.code} at {urllib.parse.urlsplit(url).path}: {detail}") from None
    except (urllib.error.URLError, TimeoutError) as error:
        raise RuntimeError(f"Hub request failed at {urllib.parse.urlsplit(url).path}: {type(error).__name__}") from None


class CallbackHandler(http.server.BaseHTTPRequestHandler):
    callback: dict[str, str] = {}

    def do_GET(self) -> None:
        parsed = urllib.parse.urlsplit(self.path)
        if parsed.path != "/auth/callback":
            self.send_error(404)
            return
        CallbackHandler.callback.clear()
        CallbackHandler.callback.update(
            {key: values[0] for key, values in urllib.parse.parse_qs(parsed.query).items()})
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"OAuth callback received. You may close this window.")

    def log_message(self, *_: object) -> None:
        pass


class CallbackServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class McpSession:
    def __init__(self, token: str):
        self.token = token
        self.session_id: str | None = None
        self.request_id = 1

    def post(self, message: dict[str, Any]) -> dict[str, Any] | None:
        headers = {"Accept": "application/json, text/event-stream"}
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        try:
            status, result, response_headers = request_json(
                f"{BASE}/mcp", body=message, headers=headers, bearer=self.token, timeout=90)
        except RuntimeError as error:
            stage = message.get("method", "tools/call")
            if stage == "tools/call":
                stage = message.get("params", {}).get("name", stage)
            raise RuntimeError(f"MCP {stage} failed: {error}") from None
        self.session_id = next((value for key, value in response_headers.items()
                                if key.lower() == "mcp-session-id"), self.session_id)
        if not result:
            return None
        if not isinstance(result, dict):
            raise RuntimeError("Hub returned an invalid MCP response")
        if result.get("error"):
            error = result["error"]
            raise RuntimeError(f"Hub MCP error {error.get('code', 'unknown')}")
        return result

    def initialize(self) -> None:
        response = self.post({"jsonrpc": "2.0", "id": self.request_id, "method": "initialize",
                              "params": {"protocolVersion": PROTOCOL_VERSION, "capabilities": {},
                                          "clientInfo": {"name": "orchestra-oauth-renew", "version": "1"}}})
        self.request_id += 1
        if not response or not isinstance(response.get("result"), dict):
            raise RuntimeError("New token failed MCP initialization")
        self.post({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def call(self, name: str, args: dict[str, Any]) -> Any:
        response = self.post({"jsonrpc": "2.0", "id": self.request_id, "method": "tools/call",
                              "params": {"name": name, "arguments": args}})
        self.request_id += 1
        result = response.get("result") if response else None
        if not isinstance(result, dict) or result.get("isError"):
            raise RuntimeError(f"Hub tool call failed: {name}")
        if "structuredContent" in result:
            return result["structuredContent"]
        texts = [item.get("text") for item in result.get("content", [])
                 if isinstance(item, dict) and item.get("type") == "text"]
        if len(texts) == 1 and isinstance(texts[0], str):
            try:
                return json.loads(texts[0])
            except json.JSONDecodeError:
                return texts[0]
        return texts


def run_full_access_probe(token: str) -> tuple[str, dict[str, Any]]:
    mcp = McpSession(token)
    mcp.initialize()
    launch = mcp.call("t3_thread_launch", {
        "title": "Orchestra OAuth renewal check", "scratch": True, "runtimeMode": "full-access",
        "modelSelection": {"instanceId": "claudeAgent", "model": "claude-haiku-5-5"},
        "message": "Run exactly this one shell command and nothing else: "
                   "echo orchestra-oauth-renew-ok > /tmp/orchestra_oauth_renew.txt && "
                   "cat /tmp/orchestra_oauth_renew.txt . Then reply with the exact file contents.",
    })
    thread_id = launch.get("threadId") if isinstance(launch, dict) else None
    if not isinstance(thread_id, str) or not thread_id:
        raise RuntimeError("Hub launch returned no thread id")
    archived = False
    try:
        for _ in range(12):
            waited = mcp.call("t3_thread_wait", {"threadId": thread_id, "timeoutMs": 20_000})
            if not isinstance(waited, dict) or not waited.get("timedOut"):
                break
        else:
            raise RuntimeError("Full-access verification thread timed out")
        read = mcp.call("t3_thread_read", {"threadId": thread_id, "view": "messages", "limit": 40})
        thread = read.get("thread") if isinstance(read, dict) else None
        items = read.get("items", []) if isinstance(read, dict) else []
        assistant_text = "\n".join(item.get("text", "") for item in items
                                     if isinstance(item, dict) and item.get("createdBy") != "user"
                                     and isinstance(item.get("text"), str))
        pending = thread.get("pendingRequestCount") if isinstance(thread, dict) else None
        if pending != 0 or "orchestra-oauth-renew-ok" not in assistant_text:
            raise RuntimeError("Full-access verification failed (pending request or command output mismatch)")
        mcp.call("t3_thread_organize", {"threadId": thread_id, "action": "archive"})
        archived = True
        return thread_id, thread
    finally:
        if not archived:
            try:
                mcp.call("t3_thread_organize", {"threadId": thread_id, "action": "archive"})
            except Exception:
                pass


def ssh_run(*arguments: str, json_output: bool = False) -> Any:
    command = ["ssh", "-i", HUB_KEY, "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes",
               HUB, shlex.join(arguments)]
    result = subprocess.run(command, capture_output=True, text=True, timeout=30)
    if result.returncode:
        raise RuntimeError(f"Hub command failed (exit {result.returncode})")
    if json_output:
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError:
            raise RuntimeError("Hub command returned invalid JSON") from None
    return result.stdout


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--if-expiring-within-days", type=int)
    try:
        options = parser.parse_args(argv)
    except SystemExit as error:
        if error.code == 0:
            raise
        raise RuntimeError("invalid command-line arguments") from None

    old_token = TOKEN_PATH.read_text(encoding="ascii").strip()
    old_claims = token_claims(old_token)
    if options.if_expiring_within_days is not None:
        skip, days_left = renewal_decision(old_claims.get("exp", 0),
                                          options.if_expiring_within_days)
        if skip:
            print(f"RENEW_SKIPPED {days_left:.2f}")
            return 0
    old_session_id = old_claims["sid"]
    if old_claims.get("rtc") != "full-access" or not set(SCOPES).issubset(old_claims.get("scopes", [])):
        raise RuntimeError("Existing session does not have the expected full-access scope ceiling")
    if os.stat(TOKEN_PATH).st_mode & 0o777 != 0o600:
        raise RuntimeError("Existing token file must be mode 0600")

    sessions = ssh_run("t3", "auth", "session", "list", "--json", "--base-dir", HUB_BASE_DIR,
                       json_output=True)
    if not any(session.get("sessionId") == old_session_id for session in sessions):
        raise RuntimeError("Existing token session is not active on the Hub; refusing to renew")

    tunnel = subprocess.Popen(["ssh", "-i", HUB_KEY, "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes",
                               "-o", "ExitOnForwardFailure=yes", "-o", "ServerAliveInterval=15", "-N",
                               "-L", "14606:127.0.0.1:14606", HUB],
                              stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    pairing_id: str | None = None
    new_session_id: str | None = None
    token_installed = False
    callback_server: CallbackServer | None = None
    try:
        for _ in range(30):
            if tunnel.poll() is not None:
                raise RuntimeError("Hub SSH tunnel exited before connecting")
            try:
                request_json(f"{BASE}/.well-known/oauth-authorization-server", timeout=2)
                break
            except RuntimeError:
                time.sleep(1)
        else:
            raise RuntimeError("Hub OAuth endpoint did not become available through the SSH tunnel")

        pairing = ssh_run("t3", "auth", "pairing", "create", "--base-dir", HUB_BASE_DIR,
                          "--ttl", "15m", "--label", "Orchestra OAuth renewal",
                          "--scope", SCOPES[0], "--scope", SCOPES[1], "--scope", SCOPES[2], "--scope", SCOPES[3],
                          "--json", json_output=True)
        pairing_id = pairing.get("id")
        pairing_code = pairing.get("credential")
        if not isinstance(pairing_id, str) or not isinstance(pairing_code, str):
            raise RuntimeError("Hub did not issue a usable pairing code")

        client_name = CLIENT_NAME
        redirect_uri = f"http://127.0.0.1:{CALLBACK_PORT}/auth/callback"
        status, registration, _ = request_json(f"{BASE}/oauth/mcp/register", body={
            "client_name": client_name, "redirect_uris": [redirect_uri],
            "grant_types": ["authorization_code"], "response_types": ["code"],
            "token_endpoint_auth_method": "none", "scope": " ".join(SCOPES),
        })
        client_id = registration.get("client_id") if isinstance(registration, dict) else None
        if status >= 300 or not isinstance(client_id, str):
            raise RuntimeError("Hub OAuth client registration failed")

        verifier = secrets.token_urlsafe(64)
        state = secrets.token_urlsafe(24)
        resource = f"{BASE}/mcp"
        authorization = build_authorization_request(client_id, redirect_uri,
                                                    pkce_challenge(verifier), state, resource)
        callback_server = CallbackServer(("127.0.0.1", CALLBACK_PORT), CallbackHandler)
        CallbackHandler.callback = {}
        _, approval, _ = request_json(f"{BASE}/oauth/mcp/approval", body=authorization)
        if not isinstance(approval, dict) or "redirectTo" in approval:
            raise RuntimeError("Hub did not return OAuth approval details")
        _, decision, _ = request_json(f"{BASE}/oauth/mcp/decision",
                                      body=build_decision_payload(authorization, pairing_code),
                                      redact=(pairing_code,))
        redirect_to = decision.get("redirectTo") if isinstance(decision, dict) else None
        if not isinstance(redirect_to, str):
            raise RuntimeError("Hub did not return an OAuth callback redirect")
        parsed_redirect = urllib.parse.urlsplit(redirect_to)
        if (parsed_redirect.scheme, parsed_redirect.netloc, parsed_redirect.path) != (
                "http", f"127.0.0.1:{CALLBACK_PORT}", "/auth/callback"):
            raise RuntimeError("Hub OAuth redirect did not match the registered loopback callback")
        callback_thread = threading.Thread(target=callback_server.handle_request, daemon=True)
        callback_thread.start()
        try:
            with urllib.request.urlopen(redirect_to, timeout=10) as callback_response:
                callback_response.read()
        except Exception:
            raise RuntimeError("Loopback OAuth callback delivery failed") from None
        callback_thread.join(timeout=12)
        callback = CallbackHandler.callback
        if callback.get("state") != state or not callback.get("code"):
            raise RuntimeError("OAuth callback state validation failed")
        if callback.get("error"):
            raise RuntimeError("Hub denied the OAuth renewal")

        _, token_response, _ = request_json(f"{BASE}/oauth/mcp/token",
                                            body=build_token_request(callback["code"], redirect_uri,
                                                                     client_id, verifier, resource), form=True,
                                            redact=(callback["code"], verifier))
        new_token = token_response.get("access_token") if isinstance(token_response, dict) else None
        if not isinstance(new_token, str) or not new_token:
            raise RuntimeError("Hub token exchange failed")
        new_claims = token_claims(new_token)
        new_session_id = new_claims.get("sid")
        if (new_claims.get("sub") != "mcp-client" or new_claims.get("rtc") != "full-access"
                or not set(SCOPES).issubset(new_claims.get("scopes", []))):
            raise RuntimeError("New token does not have the expected full-access claims")
        expires_ms = int(new_claims.get("exp", 0))
        remaining_ms = expires_ms - int(time.time() * 1000)
        if not 29 * 24 * 60 * 60 * 1000 <= remaining_ms <= 31 * 24 * 60 * 60 * 1000:
            raise RuntimeError("New Hub session does not have the expected approximately 30-day lifetime")

        thread_id, thread = run_full_access_probe(new_token)
        fresh_sessions = ssh_run("t3", "auth", "session", "list", "--json", "--base-dir", HUB_BASE_DIR,
                                 json_output=True)
        session = next((item for item in fresh_sessions if item.get("sessionId") == new_session_id), None)
        if not session or session.get("expiresAt") is None:
            raise RuntimeError("New session is absent from Hub session list")

        atomic_write_token(TOKEN_PATH, new_token)
        token_installed = True
        ssh_run("t3", "auth", "session", "revoke", "--base-dir", HUB_BASE_DIR, old_session_id)
        final_sessions = ssh_run("t3", "auth", "session", "list", "--json", "--base-dir", HUB_BASE_DIR,
                                 json_output=True)
        if any(item.get("sessionId") == old_session_id for item in final_sessions):
            raise RuntimeError("Old session remains active after revocation")
        final_session = next((item for item in final_sessions if item.get("sessionId") == new_session_id), None)
        if final_session is None:
            raise RuntimeError("New session is missing after old session revocation")
        print(json.dumps({"renewed": True, "old_session_revoked": True,
                          "new_session": {key: final_session.get(key) for key in
                                          ("sessionId", "scopes", "issuedAt", "expiresAt")},
                          "probe": {"threadId": thread_id, "status": thread.get("status"),
                                    "pendingRequestCount": thread.get("pendingRequestCount"),
                                    "output": "orchestra-oauth-renew-ok"}}, indent=2))
        print(f"RENEWED {final_session['expiresAt']}")
        return 0
    finally:
        if callback_server:
            callback_server.server_close()
        if new_session_id and not token_installed:
            try:
                ssh_run("t3", "auth", "session", "revoke", "--base-dir", HUB_BASE_DIR,
                        str(new_session_id))
            except Exception:
                pass
        if pairing_id:
            try:
                ssh_run("t3", "auth", "pairing", "revoke", "--base-dir", HUB_BASE_DIR, pairing_id)
            except Exception:
                pass
        tunnel.terminate()
        try:
            tunnel.wait(timeout=5)
        except subprocess.TimeoutExpired:
            tunnel.kill()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        reason = " ".join(str(error).splitlines())
        print(f"RENEW_FAILED {reason}", file=sys.stderr)
        raise SystemExit(1)
