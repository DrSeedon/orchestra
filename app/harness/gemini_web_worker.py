"""One isolated gemini-webapi==2.1.1 request. JSON in/out, no vendor diagnostics."""

from __future__ import annotations

import asyncio
import importlib
from importlib.metadata import version
import json
import os
import re
import sys


def prevent_cookie_files(event, arguments):
    if event == "open" and arguments:
        path = arguments[0]
        if isinstance(path, (str, bytes)) and ".cached_cookies_" in str(path):
            raise PermissionError("Gemini Web credential cache disabled")


def disable_cookie_files(identity: dict, expected_email: str) -> None:
    """Only called inside the disposable helper, never in the service process."""
    sys.addaudithook(prevent_cookie_files)
    from loguru import logger
    logger.remove()
    cache = importlib.import_module("gemini_webapi.utils.rotate_1psidts")
    access = importlib.import_module("gemini_webapi.utils.get_access_token")
    client = importlib.import_module("gemini_webapi.client")
    no_op = lambda *args, **kwargs: None
    for module in (cache, access, client):
        for name in ("save_cookies", "clear_cookies_cache", "_get_cookies_cache_path"):
            if hasattr(module, name):
                setattr(module, name, no_op)
    access.load_browser_cookies = no_op
    original = access._extract_payload

    def checked_payload(response):
        match = re.search(r'"oPEP7c"\s*:\s*("(?:\\.|[^"\\])*")', response.text)
        principal = json.loads(match.group(1)) if match else ""
        identity["owner_match"] = isinstance(principal, str) and principal.lower() == expected_email.lower()
        if not identity["owner_match"]:
            raise RuntimeError("Gemini Web account identity mismatch")
        return original(response)

    access._extract_payload = checked_payload
    session_factory = access.AsyncSession

    def account_session(*args, **kwargs):
        params = dict(kwargs.pop("params", {}) or {})
        params["authuser"] = expected_email
        return session_factory(*args, params=params, **kwargs)

    access.AsyncSession = account_session


async def generate(payload: dict) -> dict:
    if version("gemini-webapi") != "2.1.1":
        raise RuntimeError("Gemini Web requires gemini-webapi==2.1.1")
    identity = {}
    disable_cookie_files(identity, payload["auth"]["expected_email"])
    from gemini_webapi import GeminiClient

    cookies = payload["auth"]["cookies"]
    client = GeminiClient(cookies["__Secure-1PSID"], cookies["__Secure-1PSIDTS"])
    try:
        await asyncio.wait_for(client.init(
            timeout=30, auto_refresh=False, auto_close=False, verbose=False,
        ), 45)
        if not identity.get("owner_match") or client.account_status.name != "AVAILABLE":
            raise RuntimeError("Gemini Web account authorization not confirmed")
        model = next((m for m in (client.list_models() or [])
                      if m.model_name == payload["model"] and m.is_available), None)
        if model is None:
            raise RuntimeError("Gemini Web requested model unavailable")
        output = await asyncio.wait_for(client.generate_content(
            payload["prompt"], model=model, temporary=True,
        ), 100)
        return {"text": output.text, "selected_model": model.model_name,
                "selected_display_name": model.display_name, "owner_match": True}
    finally:
        await client.close()


def main() -> int:
    # No core dumps containing the credential pipe, low priority, no detached jobs.
    import resource
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    os.nice(10)
    try:
        with open("/proc/self/oom_score_adj", "w") as stream:
            stream.write("1000")
    except OSError:
        pass
    try:
        payload = json.load(sys.stdin)
        result = asyncio.run(generate(payload))
    except Exception:
        # Even exception names/messages and traceback locals from vendor code are untrusted.
        print(json.dumps({"error": "Gemini Web request failed (authentication, model or transport)"}))
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
