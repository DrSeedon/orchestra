"""Idle-only rollout, production admission, and one operator ACP turn."""
import hashlib
import json
from pathlib import Path
import runpy
import sqlite3
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlencode
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[3]
PROD = Path("/home/kesha/orchestra")
EVIDENCE = ROOT / ".orchestra/tasks/gemini-neon-20261119"
BASE = "759b32c41"
helper = str(PROD / ".orchestra/tasks/sol62-rollout-20261118/live_control.py")
sys.argv = [helper, "client"]
operator = runpy.run_path(helper)
api, snapshot = operator["api"], operator["snapshot"]
report = {}


def save(**values):
    report.update(values)
    (EVIDENCE / "live.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(values, ensure_ascii=False), flush=True)


def cmd(*args):
    return subprocess.check_output(args, text=True, timeout=70).strip()


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fingerprints():
    return {path: sha(PROD / path)
            for path in cmd("git", "-C", str(PROD), "diff", "--name-only", "HEAD").splitlines()}


def pid(unit):
    return cmd("systemctl", "show", unit, "-p", "MainPID", "--value")


def active():
    return sorted(row["name"] for row in snapshot() if row["status"] == "running" or row.get("compaction"))


def query(sql, params=()):
    with sqlite3.connect(f"file:{PROD / 'data/orchestra.db'}?mode=ro", uri=True) as conn:
        return conn.execute(sql, params).fetchall()


code = cmd("git", "-C", str(ROOT), "rev-parse", "HEAD")
assert cmd("git", "-C", str(PROD), "rev-parse", "--short=9", "HEAD") == BASE
dirty = fingerprints()
disabled_file = PROD / "data/disabled_providers.json"
disabled = sha(disabled_file)
assert query("SELECT COUNT(*) FROM restart_cut_turns") == [(0,)]
old, telegram = pid("orchestra.service"), pid("telegram-bot-api.service")
stop = time.monotonic() + 1200
previous = None
while True:
    busy = active()
    if busy != previous:
        print(json.dumps({"active": busy}), flush=True)
        previous = busy
    if not busy:
        break
    if time.monotonic() >= stop:
        raise RuntimeError("Idle deadline reached before merge/restart")
    time.sleep(3)
assert dirty == fingerprints()
cmd("git", "-C", str(PROD), "merge", "--ff-only", code)
assert not active(), "New active turn appeared after fast-forward. Restart deferred."
cmd("sudo", "-n", "systemctl", "restart", "orchestra.service")
for attempt in range(30):
    try:
        snapshot()
        break
    except (OSError, RuntimeError):
        if attempt == 29:
            raise
        time.sleep(1)
assert query("SELECT COUNT(*) FROM restart_cut_turns") == [(0,)]
assert old != pid("orchestra.service") and telegram == pid("telegram-bot-api.service")
assert dirty == fingerprints() and disabled == sha(disabled_file)
assert cmd("systemctl", "is-active", "orchestra.service", "telegram-bot-api.service").splitlines() == ["active", "active"]
save(code=code, deployed=True, restart_cut_turns=0, orchestra_pid=pid("orchestra.service"),
     telegram_pid_preserved=True, dirty_files_preserved=len(dirty))

sys.path.insert(0, str(PROD))
from app import models

allowed = models.ANTIGRAVITY_G1_AGENT_MODELS
assert len(allowed) == 22
catalog = {entry["id"]: entry for entry in api("GET", "/api/models/catalog")["catalog"]}
for model in sorted(allowed):
    assert catalog[model]["flags"]["agents"] and not catalog[model]["provider_disabled"], model
    models.ensure_spawn_allowed(model, scope=str(PROD), role="worker", pipeline="default")
save(admitted=len(allowed), gemini=len(models.ANTIGRAVITY_G1_GEMINI_AGENT_MODELS),
     claude=len(models.ANTIGRAVITY_G1_CLAUDE_AGENT_MODELS),
     neon_aliases={key: models.resolve_model(key) for key in models.ALIASES if key.startswith("agy-neon")})

# The temporary worker uses the live server's canonical profile, so it shares
# the already-guarded ACP owner. No alternate HOME, token or vendor process.
name = "neon-smoke-" + uuid4().hex[:8]
with tempfile.TemporaryDirectory(prefix="orchestra-neon-smoke-") as cwd:
    session = api("POST", "/api/sessions", {"name": name, "scope": cwd, "cwd": cwd,
                  "model": "antigravity/gemini-4-neon-high", "role": "worker", "pipeline": "default",
                  "tg_topic": False})
    sid = session["id"]
    base = f"/api/sessions/{name}"
    started = time.monotonic()
    try:
        result = api("POST", base + "/send", {"scope": cwd, "channel": "dashboard",
                     "message": "Reply with the exact text NEON_SMOKE_OK. Do not use any tools.",
                     "delivery_id": str(uuid4())}, timeout=45)
        end = started + 95
        while time.monotonic() < end:
            logs = query("SELECT type, content FROM logs WHERE session_id=? ORDER BY id", (sid,))
            status, native_id = query("SELECT status, session_id FROM sessions WHERE id=?", (sid,))[0]
            if any(kind == "error" for kind, _ in logs):
                save(smoke="failed", error_events=sum(kind == "error" for kind, _ in logs),
                     error_categories=sorted({label for label in ("quota", "auth", "model", "protocol", "egress", "permission")
                                              if any(kind == "error" and label in line.lower() for kind, line in logs)}))
                raise RuntimeError("Smoke produced an error; no replay")
            end_turn = any(kind == "status" and line.startswith("turn ended (end_turn,")
                           for kind, line in logs)
            if native_id and end_turn and status in {"idle", "waiting"} and any(
                kind == "text" and content.strip() == "NEON_SMOKE_OK" for kind, content in logs
            ):
                save(smoke="passed", model=session["model"], exact_response=True,
                     wall_seconds=round(time.monotonic() - started, 2),
                     tool_calls=sum(kind == "tool" for kind, _ in logs))
                break
            time.sleep(1)
        else:
            save(smoke="timeout", last_status=status)
            raise RuntimeError("Smoke deadline; no replay")
    finally:
        rows = query("SELECT status FROM sessions WHERE id=?", (sid,))
        if rows and rows[0][0] == "running":
            api("POST", base + "/interrupt", {"scope": cwd})
            for _ in range(12):
                if query("SELECT status FROM sessions WHERE id=?", (sid,)) != [("running",)]:
                    break
                time.sleep(1)
        api("DELETE", base + "?" + urlencode({"scope": cwd}))
        remaining = query("SELECT status FROM sessions WHERE id=?", (sid,))
        assert not remaining or remaining == [("archived",)]
        save(smoke_worker_removed_from_active=True)
