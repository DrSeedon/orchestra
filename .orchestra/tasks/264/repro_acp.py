#!/usr/bin/env python3
"""Minimal ACP handshake against `grok agent stdio`, dumping every notification.

Reproduces the launch plan Orchestra sends (one stdio server named `orchestra`) against a
SCRATCH GROK_HOME so live workers' config is never touched.
"""
import asyncio, json, os, sys, uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from app.backend_grok import _GROK_SANDBOX_CONFIG, GROK_BIN, GROK_USER_HOME
from app.runtime_env import MCP_STDIO_CMD, MCP_BASE_ENV

SCRATCH = Path(os.environ.get("SCRATCH_HOME", "/tmp/grok-repro-home-%s" % uuid.uuid4().hex[:6]))


def scratch_home() -> Path:
    SCRATCH.mkdir(parents=True, exist_ok=True)
    (SCRATCH / "config.toml").write_text(_GROK_SANDBOX_CONFIG, encoding="utf-8")
    link = SCRATCH / "auth.json"
    if not link.is_symlink():
        link.symlink_to(GROK_USER_HOME / "auth.json")
    return SCRATCH


def server_configs(cwd: str) -> list[dict]:
    env = {**MCP_BASE_ENV, "ORCHESTRA_URL": "http://127.0.0.1:8888",
           "ORCHESTRA_SCOPE": "/home/kesha/orchestra", "ORCHESTRA_ROLE": "worker",
           "ORCHESTRA_ACCESS_MODE": "full", "WORKER_NAME": "grok-repro",
           "PARENT_NAME": "", "ORCHESTRA_SESSION_ID": ""}
    return [{
        "name": "orchestra", "type": "stdio",
        "command": MCP_STDIO_CMD[0], "args": [str(a) for a in MCP_STDIO_CMD[1:]],
        "env": [{"name": k, "value": str(v)} for k, v in env.items()],
    }]


async def main() -> None:
    cwd = str(Path(__file__).resolve().parents[2])
    home = scratch_home()
    env = dict(os.environ)
    for var in ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy", "ALL_PROXY", "all_proxy"):
        env.pop(var, None)
    env["GROK_HOME"] = str(home)

    argv = [GROK_BIN, "agent", "--model", "grok-4.5", "--reasoning-effort", "high",
            "--always-approve"]
    plugin_dir = os.environ.get("PLUGIN_DIR")
    if plugin_dir:
        argv += ["--plugin-dir", plugin_dir]
    argv += ["stdio"]
    proc = await asyncio.create_subprocess_exec(
        *argv,
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE, env=env, cwd=cwd, limit=16 * 1024 * 1024,
    )
    out = open(os.environ.get("DUMP", "/tmp/grok-repro.jsonl"), "w")
    pending: dict[int, asyncio.Future] = {}

    async def reader() -> None:
        while True:
            line = await proc.stdout.readline()
            if not line:
                break
            out.write(line.decode(errors="replace"))
            out.flush()
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            if "id" in msg and ("result" in msg or "error" in msg):
                fut = pending.pop(msg["id"], None)
                if fut and not fut.done():
                    fut.set_result(msg)
            elif msg.get("method") and "id" in msg:
                # agent->client request; approve everything
                proc.stdin.write((json.dumps({"jsonrpc": "2.0", "id": msg["id"],
                                              "result": {}}) + "\n").encode())

    async def stderr_drain() -> None:
        while True:
            line = await proc.stderr.readline()
            if not line:
                break
            out.write("STDERR: " + line.decode(errors="replace"))
            out.flush()

    asyncio.create_task(reader())
    asyncio.create_task(stderr_drain())
    counter = 0

    async def request(method: str, params: dict) -> dict:
        nonlocal counter
        counter += 1
        fut = asyncio.get_running_loop().create_future()
        pending[counter] = fut
        proc.stdin.write((json.dumps({"jsonrpc": "2.0", "id": counter,
                                      "method": method, "params": params}) + "\n").encode())
        await proc.stdin.drain()
        return await asyncio.wait_for(fut, timeout=60)

    await request("initialize", {"protocolVersion": 1,
                                 "clientCapabilities": {"fs": {"readTextFile": False,
                                                               "writeTextFile": False},
                                                        "terminal": False}})
    plan = [] if os.environ.get("PLUGIN_DIR") and os.environ.get("NO_PLAN") else server_configs(cwd)
    res = await request("session/new", {"cwd": cwd, "mcpServers": plan})
    print("session/new ->", json.dumps(res)[:400])
    await asyncio.sleep(25)  # let MCP init notifications land
    proc.kill()
    out.close()
    print("dump:", os.environ.get("DUMP", "/tmp/grok-repro.jsonl"))
    print("scratch home:", home)


asyncio.run(main())
