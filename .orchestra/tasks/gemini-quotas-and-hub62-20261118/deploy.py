"""Owner-approved idle-only deployment and one quota collection."""
import hashlib
import json
import os
from pathlib import Path
import re
import runpy
import sqlite3
import stat
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[3]
PROD = Path("/home/kesha/orchestra")
BASE = "e520add5081ea02b31b97d4911aa3ac0032e32a6"
HELPER = PROD / ".orchestra/tasks/sol62-rollout-20261118/live_control.py"
sys.argv = [str(HELPER), "client"]
operator = runpy.run_path(str(HELPER))
api = operator["api"]
snapshot = operator["snapshot"]


def command(*argv):
    return subprocess.check_output(argv, text=True, timeout=60).strip()


def fingerprint():
    result = {}
    for path in command("git", "-C", str(PROD), "diff", "--name-only", "HEAD").splitlines():
        result[path] = hashlib.sha256((PROD / path).read_bytes()).hexdigest()
    return result


def active_names():
    return [row["name"] for row in snapshot() if row["status"] == "running" or row.get("compaction")]


def cuts():
    uri = f"file:{PROD / 'data/orchestra.db'}?mode=ro"
    with sqlite3.connect(uri, uri=True) as db:
        return db.execute("SELECT COUNT(*) FROM restart_cut_turns").fetchone()[0]


def pid(unit):
    return command("systemctl", "show", unit, "-p", "MainPID", "--value")


def enable_gemini_lanes():
    path = PROD / ".env"
    original = path.read_bytes()
    pattern = rb"^(QUOTA_GATED_LANES=)([a-z_0-9,]+)$"
    match = re.search(pattern, original, re.M)
    assert match, "Unexpected existing quota policy format"
    current = match[2].split(b",")
    new_lanes = [lane for lane in (b"agy_gemini", b"agy_argon", b"agy_3p") if lane not in current]
    if not new_lanes:
        return
    updated = original[:match.start(2)] + b",".join(current + new_lanes) + original[match.end(2):]
    fd, temporary = tempfile.mkstemp(prefix=".quota-policy-", dir=PROD)
    try:
        with os.fdopen(fd, "wb") as buffer:
            os.fchmod(buffer.fileno(), stat.S_IMODE(path.stat().st_mode))
            buffer.write(updated)
            buffer.flush()
            os.fsync(buffer.fileno())
        assert path.read_bytes() == original, "Concurrent production quota config edit"
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


code = command("git", "-C", str(ROOT), "rev-parse", "HEAD")
assert command("git", "-C", str(PROD), "rev-parse", "HEAD") == BASE
other = fingerprint()
disabled_path = PROD / "data/disabled_providers.json"
disabled_before = hashlib.sha256(disabled_path.read_bytes()).hexdigest()
old_pid, tg = pid("orchestra.service"), pid("telegram-bot-api.service")
assert cuts() == 0
deadline = time.monotonic() + 1800
last = None
while True:
    busy = active_names()
    if busy != last:
        print(json.dumps({"busy": busy}), flush=True)
        last = busy
    if not busy:
        break
    if time.monotonic() >= deadline:
        raise RuntimeError("Idle deadline reached without merge or restart")
    time.sleep(2)
assert fingerprint() == other
command("git", "-C", str(PROD), "merge", "--ff-only", code)
assert not active_names(), "A new turn started during merge; restart deferred"
enable_gemini_lanes()
assert not active_names(), "A new turn started during preparation; restart deferred"
command("sudo", "-n", "systemctl", "restart", "orchestra.service")
assert command("systemctl", "is-active", "orchestra.service") == "active"
new_pid = pid("orchestra.service")
assert new_pid != old_pid and tg == pid("telegram-bot-api.service")
for attempt in range(30):
    try:
        snapshot()
        break
    except (OSError, RuntimeError):
        if attempt == 29:
            raise
        time.sleep(1)
assert cuts() == 0 and fingerprint() == other
assert hashlib.sha256(disabled_path.read_bytes()).hexdigest() == disabled_before
print(json.dumps({"code": code, "pid_before": old_pid, "pid_after": new_pid,
                  "restart_cut_turns": cuts(), "telegram_pid_preserved": True,
                  "foreign_dirty_preserved": True}), flush=True)
sample = api("POST", "/api/usage/antigravity/refresh", {}, timeout=40)
providers = sample["providers"]
print(json.dumps({"observed_at": sample["observed_at"], "windows": {
    pool: [w["id"] for w in payload["windows"]] for pool, payload in providers.items()
}}), flush=True)
windows = {w["id"] for provider in providers.values() for w in provider["windows"]}
assert windows == {"gemini-weekly", "gemini-5h", "gemini-argon-wtu-weekly", "3p-weekly", "3p-5h"}
graph = api("GET", "/api/usage/quota-map")
agy = [b for b in graph["buckets"] if b["bucket"].startswith("antigravity_")]
assert len(agy) == 5 and all(b["fresh"] and b["timeline"]["points"] for b in agy)
assert sum(l["gated"] for b in agy for l in b["lanes"]) == 3
catalog = api("GET", "/api/models/catalog")
ids = {item["id"] for item in catalog["catalog"]}
assert {"hub-gpt-6.2-sol", "hub-gpt-6.2-astra"} <= ids
assert ids.isdisjoint({"gpt-6.1-sol", "gpt-6-sol", "gpt-6-astra", "hub-gpt-6.1-sol", "hub-gpt-6-astra"})
print(json.dumps({"live_snapshot": True, "graph_windows": len(agy),
                  "history_observed": len(windows), "hub_62_catalog": True}), flush=True)
