"""Idle-only ACP timeout rollout. No provider prompt."""
import hashlib
import json
from pathlib import Path
import runpy
import sqlite3
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
PROD = Path("/home/kesha/orchestra")
EVIDENCE = ROOT / ".orchestra/tasks/acp-timeout-and-human-cadence-20261119"
BASE = "66b78b3b8"
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

