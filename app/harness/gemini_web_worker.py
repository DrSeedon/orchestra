"""One isolated gemini-webapi==2.1.1 request. JSON in/out, no vendor diagnostics."""

from __future__ import annotations

import asyncio
import importlib
from importlib.metadata import version
import json
import os
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit, urlunsplit

SAFE_ERROR_TYPES = frozenset({
    "RuntimeError", "AuthError", "APIError", "TimeoutError", "ReadTimeout",
    "UsageLimitExceeded", "ModelInvalid", "TemporarilyBlockedError", "HTTPError",
    "UsageLimitExceededError", "ModelInvalidError", "GeminiError", "ImageGenerationError",
    "CurlError", "ConnectionError", "PermissionError", "ValueError", "UnknownError",
})
SAFE_ERROR_CODES = {
    "cookies_expired": "Gemini Web session cookies expired",
    "identity_mismatch": "Gemini Web account identity mismatch",
    "authorization_unconfirmed": "Gemini Web account authorization not confirmed",
    "model_unavailable": "Gemini Web requested model unavailable",
    "library_version": "Gemini Web requires gemini-webapi==2.1.1",
    "request_failed": "Gemini Web request failed (authentication, model or transport)",
}
CANNED_REFUSAL_PREFIXES = (
    "Sorry, something went wrong. Please try your request again.",
    "I'm having a hard time fulfilling your request.",
    "I seem to be encountering an error.",
    "Я просто языковая модель.",
    "Я всего лишь искусственный интеллект",
)


def is_canned_refusal(text: str) -> bool:
    return text.strip().startswith(CANNED_REFUSAL_PREFIXES)


def safe_error(error: Exception) -> dict:
    kind = type(error).__name__
    code = next((code for code, message in SAFE_ERROR_CODES.items()
                 if type(error) is RuntimeError and str(error) == message), "request_failed")
    return {"error_type": kind if kind in SAFE_ERROR_TYPES else "UnknownError",
            "error_code": code, "error": SAFE_ERROR_CODES[code]}


def account_url(url: str, index: int | None) -> str:
    """Pin init, catalog RPCs and streamed generation to the same Google user."""
    if index is None:
        return url
    parts = urlsplit(url)
    if parts.scheme == "https" and parts.netloc == "gemini.google.com":
        path = re.sub(r"^/u/\d+(?=/|$)", "", parts.path)
        return urlunsplit(parts._replace(path=f"/u/{index}{path}"))
    return url


def prevent_cookie_files(event, arguments):
    if event == "open" and arguments:
        path = arguments[0]
        if isinstance(path, (str, bytes)) and ".cached_cookies_" in str(path):
            raise PermissionError("Gemini Web credential cache disabled")


def disable_cookie_files(identity: dict, expected_email: str,
                         authuser_index: int | None = None,
                         allowed_emails: list[str] | None = None) -> None:
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
        if hasattr(module, "_get_cookie_cache_dir"):
            module._get_cookie_cache_dir = lambda *args, **kwargs: Path("/nonexistent")

    async def no_read_chat(*args, **kwargs):
        # 2.1.1 catches this after yielding streamed text, skipping its history poll.
        raise TimeoutError()

    vendor_client = getattr(client, "GeminiClient", None)
    if hasattr(vendor_client, "read_chat"):
        vendor_client.read_chat = no_read_chat

    async def rotate_in_memory(session, verbose=False):
        from gemini_webapi.constants import Endpoint, Headers
        response = await session.post(url=Endpoint.ROTATE_COOKIES,
                                      headers=Headers.ROTATE_COOKIES.value,
                                      data='[000,"-0000000000000000000"]')
        response.raise_for_status()
        return next((c.value for c in session.cookies.jar
                     if c.name == "__Secure-1PSIDTS"), None)

    cache.rotate_1psidts = rotate_in_memory
    client.rotate_1psidts = rotate_in_memory
    access.load_browser_cookies = no_op
    original = access._extract_payload

    def checked_payload(response):
        match = re.search(r'"oPEP7c"\s*:\s*("(?:\\.|[^"\\])*")', response.text)
        principal = json.loads(match.group(1)) if match else ""
        allowed = {email.lower() for email in (allowed_emails or [])} | {expected_email.lower()}
        identity["owner_match"] = isinstance(principal, str) and principal.lower() in allowed
        if not principal:
            raise RuntimeError("Gemini Web session cookies expired")
        if not identity["owner_match"]:
            raise RuntimeError("Gemini Web account identity mismatch")
        identity["account_email"] = principal.lower()
        return original(response)

    access._extract_payload = checked_payload
    session_factory = access.AsyncSession

    def account_session(*args, **kwargs):
        params = dict(kwargs.pop("params", {}) or {})
        params["authuser"] = authuser_index if authuser_index is not None else expected_email
        session = session_factory(*args, params=params, **kwargs)
        if authuser_index is not None:
            request = session.request

            async def pinned_request(method, url, **request_kwargs):
                return await request(method=method, url=account_url(url, authuser_index), **request_kwargs)

            session.request = pinned_request
        return session

    access.AsyncSession = account_session


def cookie_updates(client, cookies: dict) -> dict:
    return {c.name: c.value for c in getattr(getattr(client, "cookies", None), "jar", [])
            if c.name in (set(cookies) | {"__Secure-1PSIDTS"})
            and c.domain.lstrip(".") in {"google.com", "accounts.google.com", "gemini.google.com"}
            and c.value and c.value != cookies.get(c.name)}


async def generate(payload: dict, state: dict | None = None) -> dict:
    if version("gemini-webapi") != "2.1.1":
        raise RuntimeError("Gemini Web requires gemini-webapi==2.1.1")
    identity = {}
    disable_cookie_files(identity, payload["auth"]["expected_email"],
                         payload["auth"].get("authuser_index"), payload.get("allowed_emails"))
    from gemini_webapi import GeminiClient

    cookies = payload["auth"]["cookies"]
    client = GeminiClient(cookies["__Secure-1PSID"], cookies.get("__Secure-1PSIDTS"))
    if hasattr(client, "cookies"):
        for name, value in cookies.items():
            domain = "accounts.google.com" if name in {"LSID", "__Host-1PLSID", "__Host-3PLSID"} else ".google.com"
            client.cookies.set(name, value, domain=domain, secure=True)
    try:
        try:
            await asyncio.wait_for(client.init(
                timeout=30, auto_refresh=True, auto_close=False, verbose=False,
            ), 45)
        except RuntimeError as error:
            if str(error) != SAFE_ERROR_CODES["cookies_expired"]:
                raise
            # One server-side recovery attempt; the parent may refresh Opera once
            # when Google's session has already invalidated this entire jar.
            from curl_cffi.requests import AsyncSession
            from gemini_webapi.utils.rotate_1psidts import rotate_1psidts
            try:
                async with AsyncSession(impersonate="chrome", timeout=15) as session:
                    session.cookies.update(client.cookies)
                    await rotate_1psidts(session)
                    client.cookies.update(session.cookies)
            except Exception:
                raise RuntimeError(SAFE_ERROR_CODES["cookies_expired"]) from None
            await asyncio.wait_for(client.init(
                timeout=30, auto_refresh=True, auto_close=False, verbose=False,
            ), 45)
        if not identity.get("owner_match") or client.account_status.name != "AVAILABLE":
            raise RuntimeError("Gemini Web account authorization not confirmed")
        requested_name = payload["model"]
        available = [m for m in (client.list_models() or []) if m.is_available]
        model = next((m for m in available if m.model_name == requested_name), None)
        if model is None:
            raise RuntimeError("Gemini Web requested model unavailable")
        candidates = [model]
        if requested_name == "gemini-flash":
            candidates += [m for fb in ("gemini-flash-lite", "gemini-pro")
                           for m in available if m.model_name == fb]
        for index, cand in enumerate(candidates):
            if cand.model_name == "gemini-flash" and len(candidates) > 1:
                timeout = 25
            elif cand.model_name == "gemini-argon" and len(payload.get("prompt", "")) > 1000:
                timeout = 180
            else:
                timeout = 100
            try:
                output = await asyncio.wait_for(client.generate_content(
                    payload["prompt"], model=cand, temporary=True,
                ), timeout)
                if not output.text or not output.text.strip() or is_canned_refusal(output.text):
                    raise RuntimeError(SAFE_ERROR_CODES["request_failed"])
                break
            except Exception:
                if index == len(candidates) - 1:
                    raise
        return {"text": output.text, "selected_model": model.model_name,
                "selected_display_name": cand.display_name, "owner_match": True,
                "account_status": client.account_status.name,
                "account_email": identity["account_email"],
                "updated_cookies": cookie_updates(client, cookies)}
    finally:
        if state is not None and identity.get("owner_match"):
            state.update(owner_match=True, account_email=identity["account_email"],
                         updated_cookies=cookie_updates(client, cookies))
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
    state = {}
    try:
        payload = json.load(sys.stdin)
        result = asyncio.run(generate(payload, state))
    except Exception as error:
        # Even exception names/messages and traceback locals from vendor code are untrusted.
        print(json.dumps({**safe_error(error), **state}))
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
