"""Authorized live Flash session check and read-only Seedon prompt replay.

Operator cookie stays in RAM. No production SQL writes, model switches, or tools.
"""
import asyncio
import collections
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")
from app.auth import create_session, create_csrf_token
from app.harness import tools as builtin, prompts
from app.harness.sessions import SessionStore
from app.harness.gemini_web import GeminiWebClient, format_prompt

USER = os.environ.get("DASHBOARD_USER", "")
HEADERS = {"Cookie": "session=" + create_session(USER),
           "X-CSRF-Token": create_csrf_token(USER), "Content-Type": "application/json"}
TASK = Path(__file__).resolve().parent


def api(path, data=None):
    request = urllib.request.Request("http://127.0.0.1:8888" + path, headers=HEADERS,
        data=json.dumps(data).encode() if data is not None else None)
    with urllib.request.urlopen(request, timeout=25) as response:
        return json.load(response)


def session_path(name, scope, endpoint=""):
    return "/api/sessions/" + name + endpoint + "?" + urllib.parse.urlencode({"scope": scope})


def snapshot():
    sessions = api("/api/sessions")
    pid = lambda unit: int(subprocess.check_output(["systemctl", "show", unit, "-p", "MainPID", "--value"]).strip())
    return {"orchestra_pid": pid("orchestra.service"), "telegram_bot_api_pid": pid("telegram-bot-api.service"),
            "status_counts": dict(collections.Counter(s["status"] for s in sessions)),
            "cut_names": [s["name"] for s in sessions if s["status"] == "running"],
            "interrupted_names": [s["name"] for s in sessions if s["status"] == "interrupted"],
            "targets": [{k: s.get(k) for k in ("name", "scope", "model", "status")}
                        for s in sessions if s["name"] in ("seedon-orchestrator", "gemini-web-check-1793881789")]}


def live_flash():
    name, scope = "gemini-web-check-1793881789", "/home/kesha/orchestra"
    current = api(session_path(name, scope))
    result = {"name": name, "model": current["model"], "before_status": current["status"]}
    if current["status"] != "idle" or current["model"] != "gemini-web/gemini-flash":
        return {**result, "success": False, "reason": "Session changed; did not disturb active work"}
    logs = api(session_path(name, scope, "/logs") + "&limit=10")
    after = max((r["id"] for r in logs), default=0)
    accepted = api("/api/sessions/" + name + "/send", {"scope": scope,
        "message": "Проверка исправленного Gemini Web. Ответь ровно GEMINI_WEB_OK. Не вызывай инструменты, не запускай воркеров и ничего не меняй."})
    result["accepted"] = bool(accepted.get("ok"))
    deadline = time.monotonic() + 210
    while time.monotonic() < deadline:
        time.sleep(2)
        rows = api(session_path(name, scope, "/logs") + "&after_id=" + str(after))
        current = api(session_path(name, scope))
        errors = [r for r in rows if r["type"] == "error"]
        text_rows = [r for r in rows if r["type"] in ("assistant", "text", "text_delta")]
        if current["status"] not in ("running", "thinking") and (errors or text_rows):
            result.update({"after_status": current["status"], "error_count": len(errors),
                           "text_chars": sum(len(r.get("content") or "") for r in text_rows),
                           "new_log_types": dict(collections.Counter(r["type"] for r in rows)),
                           "success": bool(text_rows and not errors)})
            break
    else:
        result.update({"success": False, "reason": "Live session check timed out"})
    return result


async def replay_seedon():
    # Read two selected rows only; no full DB backup or large state copies.
    with sqlite3.connect("file:" + str(ROOT / "data/orchestra.db") + "?mode=ro", uri=True, timeout=2) as db:
        db.row_factory = sqlite3.Row
        row = dict(db.execute("SELECT name,scope,model,status,system_prompt,session_id_history FROM sessions WHERE name=?",
                              ("seedon-orchestrator",)).fetchone())
    history = []
    for old in reversed(json.loads(row.get("session_id_history") or "[]")):
        if old.get("runtime") == "harness":
            sid = old.get("session_id") or ""
            if sid and "/" not in sid:
                history = SessionStore(str(ROOT / "data/harness-sessions"), session_id=sid).load()
            if history:
                break
    system = prompts.build_system_prompt(row["system_prompt"], cwd=row["scope"])
    messages = [{"role": "system", "content": system}]
    messages += [m for m in history if m.get("role") != "system"]
    messages += [{"role": "user", "content": "Диагностическая проверка Gemini Web: ответь ровно SEEDON_GEMINI_OK. Не вызывай инструменты и ничего не меняй."}]
    tools = builtin.tool_schemas()
    result = {"name": row["name"], "live_model_preserved": row["model"],
              "probe_mode": "read-only-context-replay", "model": "gemini-web/gemini-argon",
              "system_chars": len(system), "history_messages": len(history),
              "prompt_bytes": len(format_prompt(messages, tools).encode())}
    client = GeminiWebClient(result["model"])
    try:
        events = [e async for e in client.stream(messages, tools)]
        result["events"] = [e.kind for e in events]
        result["text_chars"] = sum(len(e.text or "") for e in events if e.kind == "text_delta")
        result["success"] = bool(result["text_chars"] and events[-1].kind == "final")
    except Exception as error:
        result.update({"success": False, "error_type": type(error).__name__})
    finally:
        await client.aclose()
    return result


def main():
    result = {}
    result["before"] = snapshot()
    (TASK / "gemini-web-pool-service-after.json").write_text(json.dumps(result["before"], ensure_ascii=False, indent=2) + "\n")
    result["flash_live"] = live_flash()
    print(json.dumps(result["flash_live"], ensure_ascii=False), flush=True)
    result["seedon_replay"] = asyncio.run(replay_seedon())
    print(json.dumps(result["seedon_replay"], ensure_ascii=False), flush=True)
    result["after"] = snapshot()
    result["success"] = result["flash_live"]["success"] and result["seedon_replay"]["success"]
    (TASK / "gemini-web-pool-session-result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    return 0 if result["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
