#!/usr/bin/env python3
"""#130 probe: a stdio MCP server that records the RAW request line before parsing it."""
import json
import sys

RAW = "/tmp/probe_raw.jsonl"


def send(obj):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


TOOL = {
    "name": "probe_id",
    "description": "Echo back the id it received. Pass n exactly as instructed.",
    "inputSchema": {"type": "object", "properties": {"n": {}}, "required": ["n"]},
}

for line in sys.stdin:
    line = line.rstrip("\n")
    if not line:
        continue
    with open(RAW, "a", encoding="utf-8") as f:
        f.write(line + "\n")
    try:
        req = json.loads(line)
    except Exception:
        continue
    method, rid = req.get("method"), req.get("id")
    if method == "initialize":
        send({"jsonrpc": "2.0", "id": rid, "result": {
            "protocolVersion": req.get("params", {}).get("protocolVersion", "2024-11-05"),
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "probe", "version": "0.1.0"},
        }})
    elif method == "tools/list":
        send({"jsonrpc": "2.0", "id": rid, "result": {"tools": [TOOL]}})
    elif method == "tools/call":
        n = req.get("params", {}).get("arguments", {}).get("n")
        text = f"received type={type(n).__name__} value={n!r}"
        send({"jsonrpc": "2.0", "id": rid, "result": {
            "content": [{"type": "text", "text": text}], "isError": False}})
    elif rid is not None:
        send({"jsonrpc": "2.0", "id": rid, "result": {}})
