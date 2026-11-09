#!/usr/bin/env python3
"""One authorized Gemini Web canary; credentials stay in this process's RAM.

Reads only Opera's two Gemini authentication cookies, using the owner's
already-unlocked KWallet Chromium Safe Storage item. Never exports the browser DB,
prints credentials, or writes a cookie cache. See gemini-web-pilot.md.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib
import json
import os
from pathlib import Path
import re
import resource
import signal
import socket
import sqlite3
import subprocess
import sys
import time
from urllib.parse import quote


HOME_DIR = Path.home()
ROOT = HOME_DIR / ".local/share/orchestra-gemini-web-pilot"
COOKIE_DB = HOME_DIR / ".config/opera/Default/Cookies"
COOKIE_NAMES = ("__Secure-1PSID", "__Secure-1PSIDTS")
RESULT: dict[str, object] = {"phase": "prepare", "credential_files_written": 0}


def report(**values: object) -> None:
    RESULT.update(values)
    print(json.dumps(values, ensure_ascii=False), flush=True)


def stop(process: subprocess.Popen | None) -> None:
    if process is not None and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def load_session_in_memory() -> dict[str, str]:
    from Cryptodome.Cipher import AES
    from Cryptodome.Protocol.KDF import PBKDF2
    from Cryptodome.Util.Padding import unpad

    service = "org.kde.kwalletd6"
    wallet_path = "/modules/kwalletd6"
    app_id = "orchestra-gemini-web-pilot"

    def wallet_call(method, *values):
        process = subprocess.run(
            ["qdbus6", service, wallet_path, "org.kde.KWallet." + method, *map(str, values)],
            capture_output=True, text=True, timeout=12,
        )
        if process.returncode:
            raise RuntimeError("wallet-call-failed")
        return process.stdout.rstrip("\n")

    handle = None
    try:
        wallet = wallet_call("networkWallet")
        if wallet_call("isOpen", wallet) != "true":
            raise RuntimeError("wallet-locked")
        handle = int(wallet_call("open", wallet, 0, app_id))
        if handle < 0:
            raise RuntimeError("wallet-access-declined")
        secret = wallet_call(
            "readPassword", handle, "Chromium Keys", "Chromium Safe Storage", app_id,
        ).encode()
        if not secret:
            raise RuntimeError("storage-secret-unavailable")
    finally:
        if handle is not None and handle >= 0:
            wallet_call("close", handle, "false", app_id)
    key = PBKDF2(secret, b"saltysalt", dkLen=16, count=1)
    del secret
    with sqlite3.connect("file:" + quote(str(COOKIE_DB)) + "?mode=ro", uri=True) as db:
        version = int(db.execute("SELECT value FROM meta WHERE key='version'").fetchone()[0])
        rows = db.execute(
            "SELECT host_key,name,value,encrypted_value FROM cookies "
            "WHERE host_key='.google.com' AND name IN (?,?)", COOKIE_NAMES,
        ).fetchall()
    result = {}
    for host, name, plain, encrypted in rows:
        if plain:
            result[name] = plain
            continue
        if not encrypted.startswith(b"v11"):
            raise RuntimeError("unsupported-cookie-encryption")
        decoded = unpad(AES.new(key, AES.MODE_CBC, iv=b" " * 16).decrypt(encrypted[3:]), 16)
        if version >= 24:
            if decoded[:32] != hashlib.sha256(host.encode()).digest():
                raise RuntimeError("cookie-domain-verification-failed")
            decoded = decoded[32:]
        result[name] = decoded.decode()
    if any(not result.get(name) for name in COOKIE_NAMES):
        raise RuntimeError("essential-cookie-missing")
    return result


def disable_cookie_files(identity: dict[str, object], expected_email: str) -> None:
    from loguru import logger

    logger.remove()
    cache = importlib.import_module("gemini_webapi.utils.rotate_1psidts")
    access = importlib.import_module("gemini_webapi.utils.get_access_token")
    client = importlib.import_module("gemini_webapi.client")
    no_op = lambda *args, **kwargs: None
    for module in (cache, access):
        module._get_cookies_cache_path = no_op
    cache.save_cookies = no_op
    cache.clear_cookies_cache = no_op
    client.save_cookies = no_op
    client.clear_cookies_cache = no_op
    original = access._extract_payload

    def capture_principal(response):
        match = re.search(r'"oPEP7c"\s*:\s*("(?:\\.|[^"\\])*")', response.text)
        principal = json.loads(match.group(1)) if match else ""
        identity["principal_field_present"] = bool(match)
        identity["owner_match"] = principal.lower() == expected_email.lower()
        identity["principal_is_email"] = bool(re.fullmatch(r"[^\s@]+@[^\s@]+\.[A-Za-z]{2,}", principal))
        if identity["principal_is_email"]:
            local, domain = principal.rsplit("@", 1)
            identity["principal_hint"] = local[:3] + "…" + local[-3:] + "@" + domain
        return original(response)

    access._extract_payload = capture_principal
    # Select the user-approved Google account on init and every later request.
    # curl_cffi merges session params with per-request RPC params.
    session_factory = access.AsyncSession

    def account_session(*args, **kwargs):
        params = dict(kwargs.pop("params", {}) or {})
        params["authuser"] = expected_email
        return session_factory(*args, params=params, **kwargs)

    access.AsyncSession = account_session

    def prevent_cache_files(event, arguments):
        if event == "open" and arguments:
            path = arguments[0]
            if isinstance(path, (str, bytes)) and ".cached_cookies_" in str(path):
                raise PermissionError("credential-cache-disabled-for-pilot")

    sys.addaudithook(prevent_cache_files)


async def check_web(cookies: dict[str, str], proxy: str, expected_email: str, generate: bool) -> None:
    identity: dict[str, object] = {}
    disable_cookie_files(identity, expected_email)
    from gemini_webapi import GeminiClient

    client = GeminiClient(cookies[COOKIE_NAMES[0]], cookies[COOKIE_NAMES[1]], proxy=proxy)
    try:
        report(phase="web-init")
        await asyncio.wait_for(
            client.init(timeout=25, auto_refresh=False, auto_close=False, verbose=False), 45,
        )
        report(
            phase="catalog", account_status=client.account_status.name,
            principal_field_present=identity.get("principal_field_present", False),
            owner_match=identity.get("owner_match", False),
            principal_is_email=identity.get("principal_is_email", False),
            principal_hint=identity.get("principal_hint"),
        )
        models = client.list_models() or []
        public_models = [
            {"name": model.model_name, "display_name": model.display_name,
             "available": model.is_available}
            for model in models
        ]
        report(models=public_models)
        if client.account_status.name != "AVAILABLE" or not identity.get("owner_match"):
            report(result="authorization-not-confirmed")
            return
        argon = next((
            model for model in models if model.is_available
            and "argon" in (model.model_name + " " + model.display_name).lower()
        ), None)
        if argon is None:
            report(result="argon-not-listed")
            return
        report(selected_model=argon.model_name, selected_display_name=argon.display_name)
        if not generate:
            report(result="argon-listed-no-generation")
            return
        report(phase="canary")
        started = time.monotonic()
        output = await asyncio.wait_for(
            client.generate_content("Reply with exactly OK.", model=argon, temporary=True), 60,
        )
        report(
            result="reply-received", response_is_ok=output.text.strip() == "OK",
            response_length=len(output.text), duration_seconds=round(time.monotonic() - started, 3),
            actual_model_attribution="not-exposed-by-client-output",
        )
    finally:
        await client.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-email", required=True)
    parser.add_argument("--generate", action="store_true")
    args = parser.parse_args()
    def interrupted(number, _frame):
        raise SystemExit(128 + number)
    for number in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(number, interrupted)
    os.nice(15)
    resource.setrlimit(resource.RLIMIT_AS, (2 * 1024**3, 2 * 1024**3))
    try:
        Path("/proc/self/oom_score_adj").write_text("1000")
    except OSError:
        pass
    tunnel = None
    try:
        report(phase="read-session-in-memory")
        cookies = load_session_in_memory()
        report(essential_cookies_available=True)
        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            port = reservation.getsockname()[1]
        tunnel = subprocess.Popen(
            ["ssh", "-N", "-T", "-D", f"127.0.0.1:{port}",
             "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
             "-o", "ExitOnForwardFailure=yes", "-o", "ConnectTimeout=8",
             "-o", "ServerAliveInterval=20", "-o", "ServerAliveCountMax=2",
             "kesha@158.220.127.161"],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, start_new_session=True,
        )
        deadline = time.monotonic() + 12
        while True:
            if tunnel.poll() is not None:
                raise RuntimeError("ssh-tunnel-failed")
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.3):
                    break
            except OSError:
                if time.monotonic() >= deadline:
                    raise RuntimeError("ssh-tunnel-timeout")
                time.sleep(0.1)
        report(tunnel_ready=True)
        asyncio.run(check_web(cookies, f"socks5h://127.0.0.1:{port}", args.expected_email, args.generate))
        return 0
    except Exception as error:
        # Exception messages can contain request/session data; expose the type only.
        report(result="failed", error_type=type(error).__name__, failed_phase=RESULT.get("phase"))
        return 1
    finally:
        stop(tunnel)
        report(tunnel_stopped=tunnel is None or tunnel.poll() is not None)
        ROOT.mkdir(parents=True, exist_ok=True)
        (ROOT / "pilot-result.json").write_text(json.dumps(RESULT, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    sys.exit(main())
