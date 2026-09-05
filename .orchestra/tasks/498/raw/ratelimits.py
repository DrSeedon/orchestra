#!/usr/bin/env python3
"""Raw uncached `account/rateLimits/read` via Codex app-server.

Mirrors app/routes/system.py:831 _fetch_codex_usage() but prints the RAW result
instead of the normalized view, so every key of rateLimitsByLimitId is visible.
"""
import json
import subprocess
import sys
import time

CODEX_BIN = "codex"

proc = subprocess.Popen(
    [CODEX_BIN, "app-server"],
    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
    text=True, bufsize=1,
)


def send(msg):
    proc.stdin.write(json.dumps(msg) + "\n")
    proc.stdin.flush()


send({"id": 1, "method": "initialize", "params": {
    "clientInfo": {"name": "orchestra-research-498", "title": "research", "version": "1"},
    "capabilities": None}})
init = json.loads(proc.stdout.readline())
assert init.get("id") == 1 and not init.get("error"), init
send({"method": "initialized"})
send({"id": 2, "method": "account/rateLimits/read", "params": None})

result = None
while line := proc.stdout.readline():
    resp = json.loads(line)
    if resp.get("id") == 2:
        result = resp.get("result")
        break

proc.stdin.close()
proc.terminate()

label = sys.argv[1] if len(sys.argv) > 1 else "snapshot"
out = {"label": label, "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "result": result}
print(json.dumps(out, indent=2, sort_keys=True))
