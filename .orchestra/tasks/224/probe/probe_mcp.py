#!/usr/bin/env python3
"""Minimal stdio MCP server used only as a probe (#224).

On startup it dumps the env keys it received to $PROBE_OUT, so a run proves both
"the CLI accepted this config form" and "the child got these env vars".
"""
import json, os, sys

out = os.environ.get("PROBE_OUT", "/tmp/probe_mcp_env.json")
with open(out, "w") as f:
    json.dump({k: v for k, v in os.environ.items()
               if k.startswith("PROBE_") or k.startswith("ORCHESTRA_")}, f)

def send(obj):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()

for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    try:
        msg = json.loads(line)
    except Exception:
        continue
    mid, method = msg.get("id"), msg.get("method")
    if method == "initialize":
        send({"jsonrpc": "2.0", "id": mid, "result": {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "probe", "version": "0.1"}}})
    elif method == "tools/list":
        send({"jsonrpc": "2.0", "id": mid, "result": {"tools": [
            {"name": "probe_ping", "description": "probe",
             "inputSchema": {"type": "object", "properties": {}}}]}})
    elif method == "tools/call":
        send({"jsonrpc": "2.0", "id": mid,
              "result": {"content": [{"type": "text", "text": "pong"}]}})
    elif mid is not None:
        send({"jsonrpc": "2.0", "id": mid, "result": {}})
