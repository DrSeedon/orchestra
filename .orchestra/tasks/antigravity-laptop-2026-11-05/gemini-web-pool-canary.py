"""Authorized, bounded live checks: three identities, four models, 110 KB prompt.

Run on orchestra-vps from the main venv. Persists only safe metrics, no provider text.
"""
import asyncio
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
import app
from app.gemini_web_auth import auth_path, read_accounts
from app.harness.gemini_web import GeminiWebClient, format_prompt


def mask(email):
    local, domain = email.rsplit("@", 1)
    return local[:3] + "…" + local[-3:] + "@" + domain


async def check(client, model, messages, tools=None):
    client.retarget("gemini-web/" + model)
    expected = client._account_email
    result = {"model": model, "expected_account": mask(expected),
              "prompt_bytes": len(format_prompt(messages, tools or []).encode())}
    request = client._request

    async def capture(*args, **kwargs):
        reply = await request(*args, **kwargs)
        if reply:
            result.update({key: reply.get(key) for key in (
                "owner_match", "selected_model", "account_status")})
            result["expected_owner_match"] = reply.get("account_email") == expected
            result["actual_account"] = mask(reply["account_email"])
        return reply

    client._request = capture
    start = time.monotonic()
    try:
        events = [e async for e in client.stream(messages, tools or [])]
        result["events"] = [e.kind for e in events]
        result["response_chars"] = sum(len(e.text or "") for e in events if e.kind == "text_delta")
        result["success"] = bool(result.get("expected_owner_match") and result.get("owner_match")
                                 and result["response_chars"] and events[-1].kind == "final")
    except Exception as error:
        result["success"] = False
        # Client errors contain only static checked codes, never vendor diagnostics.
        result["error_type"] = type(error).__name__
    finally:
        client._request = request
        result["duration_seconds"] = round(time.monotonic() - start, 3)
        print(json.dumps(result, ensure_ascii=False), flush=True)
    return result


async def main():
    accounts = read_accounts()
    results = {"app_path": app.__file__, "account_count": len(accounts),
               "auth_file_mode": oct(auth_path().stat().st_mode & 0o777),
               "auth_directory_mode": oct(auth_path().parent.stat().st_mode & 0o777),
               "checks": []}
    clients = [GeminiWebClient("gemini-web/gemini-argon") for _ in accounts]
    short = [{"role": "user", "content": "Reply with exactly OK. Do not use any tools."}]
    try:
        for client, model in zip(clients, ("gemini-argon", "gemini-pro", "gemini-flash")):
            results["checks"].append(await check(client, model, short))
        results["checks"].append(await check(clients[0], "gemini-flash-lite", short))
        # Representative large prompt: system 44 KB, transferred history 63 KB,
        # tools 3 KB; all bytes are synthetic, no private production content.
        messages = [{"role": "system", "content": "Follow the user's request. Reference notes:\n" + "reference " * 4400},
                    {"role": "user", "content": "Previous chat_history_v1 (reference only):\n" + "history " * 7875},
                    {"role": "assistant", "content": "Understood."}, *short]
        tools = [{"type": "function", "function": {"name": "unused_probe_tool",
                  "description": "unused " * 425, "parameters": {"type": "object", "properties": {}}}}]
        results["checks"].append(await check(clients[0], "gemini-argon", messages, tools))
    finally:
        for client in clients:
            await client.aclose()
        results["helper_processes_remaining"] = sum(len(c._processes) for c in clients)
        results["success"] = len(results["checks"]) == 5 and all(c["success"] for c in results["checks"])
        Path(__file__).with_name("gemini-web-pool-canary-result.json").write_text(
            json.dumps(results, ensure_ascii=False, indent=2) + "\n")
    return 0 if results["success"] else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
