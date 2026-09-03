#!/usr/bin/env python3
"""Does session/new's `mcpServers` add to, replace, or get ignored against config.toml?

Runs the same ACP handshake three ways against a GROK_HOME whose config.toml already
declares the orchestra server (proved healthy by `grok mcp doctor`).
"""
import asyncio, json, shutil, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from probe_routes import make_home, toml_block, probe, acp_plan

ROOT = Path(__file__).resolve().parents[3]


async def main() -> None:
    cwd = str(ROOT)
    cases = {
        # (send_plan flag understood by probe(), plus an omit-key override below)
        "config+no-key": "omit",
        "config+empty-list": "empty",
        "config+acp-plan": "plan",
    }
    results = {}
    for label, mode in cases.items():
        home = make_home(toml_block())
        try:
            seen = await probe_mode(label, home, cwd, mode)
        except Exception as exc:
            seen = {"error": f"{type(exc).__name__}: {exc}"}
        results[label] = seen
        print(f"{label:20} {json.dumps(seen)}", flush=True)
        shutil.rmtree(home, ignore_errors=True)
    Path("/tmp/grok-session-new-results.json").write_text(json.dumps(results, indent=2))


async def probe_mode(label: str, home: Path, cwd: str, mode: str) -> dict:
    """probe() always sends the key; patch the params for the omit case."""
    import probe_routes
    original = probe_routes.acp_plan
    if mode == "omit":
        # Monkeypatch a sentinel the patched probe understands.
        return await _probe_omit(label, home, cwd)
    probe_routes.acp_plan = (lambda: acp_plan()) if mode == "plan" else (lambda: [])
    try:
        return await probe(label, home, None, True, cwd)
    finally:
        probe_routes.acp_plan = original


async def _probe_omit(label: str, home: Path, cwd: str) -> dict:
    """session/new without the mcpServers key at all."""
    import os, uuid
    from app.backend_grok import GROK_BIN
    env = dict(os.environ)
    for var in ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy", "ALL_PROXY", "all_proxy"):
        env.pop(var, None)
    env["GROK_HOME"] = str(home)
    proc = await asyncio.create_subprocess_exec(
        GROK_BIN, "agent", "--model", "grok-4.5", "--reasoning-effort", "high",
        "--always-approve", "stdio",
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE, env=env, cwd=cwd, limit=16 * 1024 * 1024)
    dump = open(f"/tmp/grok-omit-{label}-{uuid.uuid4().hex[:6]}.jsonl", "w")
    pending: dict[int, asyncio.Future] = {}
    seen = {"servers": [], "tool_count": None, "status": []}

    async def reader() -> None:
        while True:
            line = await proc.stdout.readline()
            if not line:
                return
            dump.write(line.decode(errors="replace")); dump.flush()
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            if "id" in msg and ("result" in msg or "error" in msg):
                fut = pending.pop(msg["id"], None)
                if fut and not fut.done():
                    fut.set_result(msg)
                continue
            method, params = msg.get("method"), msg.get("params") or {}
            if method == "_x.ai/mcp/servers_updated":
                seen["servers"] = [s.get("name") for s in (params.get("mcpServers") or [])]
            elif method == "_x.ai/mcp/server_status":
                seen["status"].append((params.get("name"), params.get("status")))
            elif method == "_x.ai/mcp_initialized":
                seen["tool_count"] = params.get("mcpToolCount")
            elif method and "id" in msg:
                proc.stdin.write((json.dumps({"jsonrpc": "2.0", "id": msg["id"],
                                              "result": {}}) + "\n").encode())

    async def errdrain() -> None:
        while True:
            line = await proc.stderr.readline()
            if not line:
                return
            dump.write("STDERR: " + line.decode(errors="replace")); dump.flush()

    tasks = [asyncio.create_task(reader()), asyncio.create_task(errdrain())]
    counter = 0

    async def request(method: str, params: dict) -> dict:
        nonlocal counter
        counter += 1
        fut = asyncio.get_running_loop().create_future()
        pending[counter] = fut
        proc.stdin.write((json.dumps({"jsonrpc": "2.0", "id": counter, "method": method,
                                      "params": params}) + "\n").encode())
        await proc.stdin.drain()
        return await asyncio.wait_for(fut, timeout=60)

    try:
        await request("initialize", {"protocolVersion": 1, "clientCapabilities": {
            "fs": {"readTextFile": False, "writeTextFile": False}, "terminal": False}})
        await request("session/new", {"cwd": cwd})  # no mcpServers key
        await asyncio.sleep(25)
    finally:
        proc.kill()
        await proc.wait()
        for t in tasks:
            t.cancel()
        dump.close()
    return seen


asyncio.run(main())
