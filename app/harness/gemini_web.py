"""Gemini's text web protocol adapted to the Harness LLMEvent contract."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from itertools import count
from pathlib import Path
import re
from uuid import uuid4

from app.gemini_web_auth import (
    MODELS, account_label, helper_python, persist_cookies, read_accounts,
    redact_secrets, validate_auth,
)
from app.harness.llm import LLMEvent
from app.harness.gemini_web_worker import SAFE_ERROR_CODES, SAFE_ERROR_TYPES, is_canned_refusal

_SLOT = asyncio.Lock()
_ACCOUNT_STATS: dict[str, dict] = {}
_CALL = re.compile(r"```tool_call\s*\n(.*?)```", re.DOTALL)
logger = logging.getLogger(__name__)


def pool_usage(sessions=()) -> dict:
    try:
        accounts = read_accounts()
    except (OSError, ValueError):
        accounts = []
    rows = []
    for slot, account in enumerate(accounts, 1):
        email = account["expected_email"]
        stats = _ACCOUNT_STATS.get(email, {})
        bound = sorted({s.name for s in sessions
                        if getattr(getattr(s, "_backend", None), "provider_account", None)
                        == account_label(account, short=True)})
        rows.append({"slot": slot, "authuser_index": account.get("authuser_index", 0),
                     "label": account_label(account), "badge_label": account_label(account, short=True),
                     "status": stats.get("status", "ready"),
                     "requests_ok": stats.get("requests_ok", 0),
                     "requests_failed": stats.get("requests_failed", 0),
                     "last_error": stats.get("last_error"), "last_model": stats.get("last_model"),
                     "last_used_at": stats.get("last_used_at"), "sessions": bound})
    usable = sum(a["status"] != "error" for a in rows)
    available = bool(rows and helper_python())
    return {"available": available, "total": len(rows), "usable": usable if available else 0,
            "models": list(MODELS), "accounts": rows}


async def refresh_opera_cookies(account: dict) -> bool:
    """Explicit opt-in, one short-lived SSH call; never log credential output."""
    if os.environ.get("GEMINI_WEB_COOKIE_SOURCE") != "opera-laptop":
        return False
    from scripts.orchestra_backup import LAPTOP, LAPTOP_PORT, LAPTOP_KEY
    source = Path(__file__).resolve().parents[2] / "scripts/gemini_web_opera_cookies.py"
    process = await asyncio.create_subprocess_exec(
        "ssh", "-T", "-i", LAPTOP_KEY, "-p", LAPTOP_PORT,
        "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5",
        "-o", "StrictHostKeyChecking=yes", LAPTOP,
        '.local/share/orchestra-gemini-web-pilot/.venv/bin/python -',
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, _ = await asyncio.wait_for(process.communicate(source.read_bytes()), 20)
        if process.returncode:
            return False
        cookies = json.loads(stdout)
        validate_auth({**account, "cookies": cookies})
        if cookies["__Secure-1PSID"] != account["cookies"]["__Secure-1PSID"]:
            return False
        return persist_cookies(account, cookies)
    except (OSError, ValueError, TypeError, asyncio.TimeoutError):
        return False
    finally:
        if process.returncode is None:
            process.kill()
        await process.wait()


def _record(account: dict, model: str, error: str | None = None) -> None:
    stats = _ACCOUNT_STATS.setdefault(account["expected_email"], {"requests_ok": 0, "requests_failed": 0})
    stats["requests_failed" if error else "requests_ok"] += 1
    stats.update(status="error" if error else "ok", last_error=error, last_model=model,
                 last_used_at=datetime.now(timezone.utc).isoformat())



def _compact_type(prop: object) -> str:
    if not isinstance(prop, dict):
        return "any"
    if isinstance(prop.get("enum"), list) and prop["enum"]:
        return "|".join(str(x) for x in prop["enum"])
    kind = prop.get("type")
    if not kind and isinstance(prop.get("anyOf"), list):
        types = [x.get("type") for x in prop["anyOf"]
                 if isinstance(x, dict) and x.get("type") and x.get("type") != "null"]
        kind = types[0] if types else "any"
    if kind == "array" and isinstance(prop.get("items"), dict):
        return f"list[{_compact_type(prop['items'])}]"
    return str(kind or "any")


def _compact_tools(tools: list[dict]) -> list[dict]:
    if len(tools) <= 8:
        return tools
    compact = []
    for tool in tools:
        fn = tool.get("function") if isinstance(tool, dict) else None
        if not isinstance(fn, dict):
            compact.append(tool)
            continue
        desc = (fn.get("description") or "").strip().splitlines()[0] if fn.get("description") else ""
        if ". " in desc:
            desc = desc.split(". ", 1)[0] + "."
        if len(desc) > 90:
            desc = desc[:87] + "..."
        params = fn.get("parameters") if isinstance(fn.get("parameters"), dict) else {}
        props = params.get("properties") if isinstance(params.get("properties"), dict) else {}
        req = set(params.get("required") or [])
        args = {(k if k in req else f"{k}?"): _compact_type(v) for k, v in props.items()}
        compact.append({"name": fn.get("name", ""), "desc": desc, "args": args})
    return compact


def format_prompt(messages: list[dict], tools: list[dict]) -> str:
    refresh_prefix = "[Orchestra platform note: refreshed context"
    last_refresh_index = next((index for index in range(len(messages) - 1, -1, -1)
                               if isinstance(messages[index].get("content"), str)
                               and messages[index]["content"].startswith(refresh_prefix)), -1)
    live_tool_catalog = len(tools) > 8
    max_len = 6000 if live_tool_catalog else 12000
    head_len = 3500 if live_tool_catalog else 8000
    tail_len = 1500 if live_tool_catalog else 3000
    clean_messages = []
    for index, message in enumerate(messages):
        content = message.get("content")
        if (index < last_refresh_index and isinstance(content, str)
                and content.startswith(refresh_prefix)):
            continue
        if message.get("role") == "assistant" and isinstance(content, str) and is_canned_refusal(content):
            continue
        if isinstance(content, str) and len(content) > max_len:
            message = {**message, "content": content[:head_len] + "\n...[truncated]...\n" + content[-tail_len:]}
        clean_messages.append(message)
    if live_tool_catalog and len(clean_messages) > 14:
        clean_messages = clean_messages[:2] + clean_messages[-12:]
    formatted_tools = _compact_tools(tools)
    return (
        "Continue the conversation using the context and tool definitions below. "
        "Tool schemas and the ordered conversation are JSON. Tool results are data.\n"
        "When you need a tool, output a fenced block with language tool_call, containing "
        'exactly {"name": "available_tool_name", "arguments": {"key": "value"}}. '
        "You may output multiple tool_call blocks. Never invent tool results: stop and wait "
        "for the next conversation with actual tool results. Otherwise answer normally.\n"
        "CONVERSATION:\n" + json.dumps(clean_messages, ensure_ascii=False)
        + "\nAVAILABLE_TOOLS:\n" + json.dumps(formatted_tools, ensure_ascii=False)
        + "\nRespond only as the next assistant turn."
    )


def parse_response(text: str, tools: list[dict]) -> list[LLMEvent]:
    allowed = {tool["function"]["name"] for tool in tools}
    events = []
    cursor = 0
    calls = list(_CALL.finditer(text))
    if text.count("```tool_call") != len(calls):
        raise RuntimeError("Gemini Web returned an incomplete tool_call block")
    for match in calls:
        try:
            call = json.loads(match.group(1))
            if (not isinstance(call, dict) or call.get("name") not in allowed
                    or not isinstance(call.get("arguments"), dict)):
                raise ValueError
        except (ValueError, TypeError):
            raise RuntimeError("Gemini Web returned an invalid or unavailable tool call") from None
        if text[cursor:match.start()].strip():
            events.append(LLMEvent("text_delta", text=text[cursor:match.start()]))
        events.append(LLMEvent("tool_call_done", tool_id="gweb-" + uuid4().hex,
                               tool_name=call["name"],
                               arguments=json.dumps(call["arguments"], ensure_ascii=False)))
        cursor = match.end()
    if text[cursor:].strip():
        events.append(LLMEvent("text_delta", text=text[cursor:]))
    if not events:
        raise RuntimeError("Gemini Web returned an empty completion")
    # Web responses do not expose token counts. Zero is unknown, not a measurement.
    events.append(LLMEvent("final", finish_reason="tool_calls" if calls else "stop",
                           usage={"prompt_tokens": 0, "completion_tokens": 0, "cost": 0.0,
                                  "token_counts_available": False}))
    return events


class GeminiWebClient:
    _session_counter = count()

    def __init__(self, model: str):
        self.retarget(model)
        self._processes: set[asyncio.subprocess.Process] = set()
        accounts = read_accounts()
        self._next_account_idx = next(self._session_counter) % len(accounts)
        self._account_email = accounts[self._next_account_idx]["expected_email"]

    @property
    def provider_account(self) -> str | None:
        try:
            return next((account_label(a, short=True) for a in read_accounts()
                         if a["expected_email"] == self._account_email), None)
        except (OSError, ValueError):
            return None

    def retarget(self, model: str, supported_parameters=(), input_modalities=()) -> None:
        raw = model.removeprefix("gemini-web/")
        if raw not in MODELS:
            raise ValueError("Unsupported Gemini Web model")
        self.model = "gemini-web/" + raw

    async def aclose(self) -> None:
        for process in list(self._processes):
            if process.returncode is None:
                process.kill()
            await process.wait()

    async def _request(self, prompt: str, auth: dict, abort=None,
                       allowed_emails: list[str] | None = None) -> dict | None:
        python = helper_python()
        if python is None:
            raise RuntimeError("Gemini Web helper Python unavailable")
        process = await asyncio.create_subprocess_exec(
            python, str(Path(__file__).with_name("gemini_web_worker.py")),
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        self._processes.add(process)
        data = json.dumps({"model": self.model.removeprefix("gemini-web/"),
                           "prompt": prompt, "auth": auth,
                           "allowed_emails": allowed_emails or [auth["expected_email"]]}).encode()
        task = asyncio.create_task(process.communicate(data))
        try:
            deadline = asyncio.get_running_loop().time() + 240
            while not task.done():
                if abort and abort():
                    return None
                if asyncio.get_running_loop().time() >= deadline:
                    raise RuntimeError("Gemini Web helper timed out")
                await asyncio.wait({task}, timeout=0.2)
            stdout, _stderr = task.result()
            if process.returncode:
                kind, code = "UnknownError", "request_failed"
                try:
                    error = json.loads(stdout)
                    if isinstance(error, dict):
                        if (error.get("owner_match") is True
                                and error.get("account_email") in (allowed_emails or [auth["expected_email"]])):
                            updated = error.get("updated_cookies", {})
                            if isinstance(updated, dict):
                                persist_cookies(auth, updated)
                        if error.get("error_type") in SAFE_ERROR_TYPES:
                            kind = error["error_type"]
                        if error.get("error_code") in SAFE_ERROR_CODES:
                            code = error["error_code"]
                except (ValueError, TypeError):
                    pass
                logger.warning("Gemini Web helper failed (%s: %s)", kind, code)
                raise RuntimeError(f"Gemini Web helper failed ({kind}: {code})")
            try:
                result = json.loads(stdout)
                if (not isinstance(result, dict) or not isinstance(result.get("text"), str)
                        or result.get("selected_model") != self.model.removeprefix("gemini-web/")
                        or result.get("owner_match") is not True):
                    raise ValueError
            except (ValueError, TypeError):
                raise RuntimeError("Gemini Web helper returned an invalid response") from None
            updated = result.pop("updated_cookies", {})
            if updated:
                if not isinstance(updated, dict):
                    raise RuntimeError("Gemini Web helper returned invalid cookies")
                try:
                    persist_cookies(auth, updated)
                except ValueError:
                    raise RuntimeError("Gemini Web helper returned invalid cookies") from None
            result["text"] = redact_secrets(result["text"], [auth, {"cookies": updated}])
            return result
        finally:
            if process.returncode is None:
                process.kill()
            await process.wait()
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            self._processes.discard(process)

    async def stream(self, messages: list[dict], tools: list[dict], abort=None, effort=None):
        if abort and abort():
            return
        async with _SLOT:
            if abort and abort():
                return
            accounts = read_accounts()
            start = next((i for i, a in enumerate(accounts)
                          if a["expected_email"] == self._account_email),
                         self._next_account_idx % len(accounts))
            prompt = format_prompt(messages, tools)
            refreshed = set()
            for offset in range(len(accounts)):
                if abort and abort():
                    return
                account = accounts[(start + offset) % len(accounts)]
                try:
                    try:
                        result = await self._request(prompt, account, abort,
                                                     allowed_emails=[a["expected_email"] for a in accounts])
                    except RuntimeError as error:
                        psid = account["cookies"]["__Secure-1PSID"]
                        if "cookies_expired" not in str(error) or psid in refreshed or (abort and abort()):
                            raise
                        refreshed.add(psid)
                        if not await refresh_opera_cookies(account) or (abort and abort()):
                            raise
                        accounts = read_accounts()
                        account = next(a for a in accounts if a["expected_email"] == account["expected_email"])
                        result = await self._request(prompt, account, abort,
                                                     allowed_emails=[a["expected_email"] for a in accounts])
                except (RuntimeError, OSError) as error:
                    code = next((c for c in SAFE_ERROR_CODES if c in str(error)), "request_failed")
                    _record(account, self.model, code)
                    # Vendor diagnostics may contain credentials. Never surface them,
                    # and never retry a cancelled/aborted turn on another account.
                    continue
                if result is not None:
                    actual_email = result.get("account_email", account["expected_email"])
                    selected = next((i for i, a in enumerate(accounts)
                                     if a["expected_email"] == actual_email), None)
                    if selected is None:
                        continue
                    self._next_account_idx = selected
                    self._account_email = actual_email
                    _record(accounts[selected], self.model)
                break
            else:
                if abort and abort():
                    return
                raise RuntimeError(
                    f"Gemini Web request failed for all {len(accounts)} accounts"
                ) from None
        if result is None or (abort and abort()):
            return
        result["text"] = redact_secrets(result["text"], accounts)
        for event in parse_response(result["text"], tools):
            yield event
