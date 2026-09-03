#!/usr/bin/env python3
"""Probe which MCP injection route Grok 1.0.3 actually honours over ACP.

Each variant gets a fresh scratch GROK_HOME so live workers are never touched. Prints the
observed roster and tool count per route — the two signals `_verify_mcp_isolation` reads.
"""
import asyncio, json, os, shutil, sys, uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from app.backend_grok import _GROK_SANDBOX_CONFIG, GROK_BIN, GROK_USER_HOME
from app.runtime_env import MCP_STDIO_CMD, MCP_BASE_ENV

SERVER_ENV = {
    **MCP_BASE_ENV, "ORCHESTRA_URL": "http://127.0.0.1:8888",
    "ORCHESTRA_SCOPE": "/home/kesha/orchestra", "ORCHESTRA_ROLE": "worker",
    "ORCHESTRA_ACCESS_MODE": "full", "WORKER_NAME": "grok-probe",
    "PARENT_NAME": "", "ORCHESTRA_SESSION_ID": "",
}


def acp_plan() -> list[dict]:
    return [{
        "name": "orchestra", "type": "stdio",
        "command": MCP_STDIO_CMD[0], "args": [str(a) for a in MCP_STDIO_CMD[1:]],
        "env": [{"name": k, "value": str(v)} for k, v in SERVER_ENV.items()],
    }]


def toml_block() -> str:
    args = ", ".join(json.dumps(str(a)) for a in MCP_STDIO_CMD[1:])
    env = ", ".join(f"{k} = {json.dumps(str(v))}" for k, v in SERVER_ENV.items())
    return (f'\n[mcp_servers.orchestra]\ncommand = {json.dumps(MCP_STDIO_CMD[0])}\n'
            f'args = [{args}]\nenv = {{ {env} }}\nenabled = true\n')


def make_home(config_extra: str = "", base: str | None = None) -> Path:
    home = Path(f"/tmp/grok-probe-home-{uuid.uuid4().hex[:8]}")
    home.mkdir(parents=True)
    (home / "config.toml").write_text((base or _GROK_SANDBOX_CONFIG) + config_extra, encoding="utf-8")
    (home / "auth.json").symlink_to(GROK_USER_HOME / "auth.json")
    return home


def make_plugin(manifest_dir: str) -> Path:
    d = Path(f"/tmp/grok-probe-plugin-{uuid.uuid4().hex[:8]}")
    (d / manifest_dir).mkdir(parents=True)
    (d / manifest_dir / "plugin.json").write_text(json.dumps(
        {"name": "orchestra", "description": "Orchestra managed MCP", "version": "1.0.0"}))
    (d / ".mcp.json").write_text(json.dumps({"mcpServers": {"orchestra": {
        "type": "stdio", "command": MCP_STDIO_CMD[0],
        "args": [str(a) for a in MCP_STDIO_CMD[1:]], "env": SERVER_ENV}}}, indent=2))
    return d


async def probe(label: str, home: Path, plugin_dir: Path | None, send_plan: bool,
                cwd: str, settle: float = 25.0) -> dict:
    env = dict(os.environ)
    for var in ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy", "ALL_PROXY", "all_proxy"):
        env.pop(var, None)
    env["GROK_HOME"] = str(home)
    argv = [GROK_BIN, "agent", "--model", "grok-4.5", "--reasoning-effort", "high",
            "--always-approve"]
    if plugin_dir:
        argv += ["--plugin-dir", str(plugin_dir)]
    argv += ["stdio"]

    proc = await asyncio.create_subprocess_exec(
        *argv, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE, env=env, cwd=cwd, limit=16 * 1024 * 1024)
    dump = open(f"/tmp/grok-probe-{label}-{uuid.uuid4().hex[:6]}.jsonl", "w")
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
        await request("session/new", {"cwd": cwd,
                                      "mcpServers": acp_plan() if send_plan else []})
        await asyncio.sleep(settle)
    finally:
        proc.kill()
        await proc.wait()
        for t in tasks:
            t.cancel()
        dump.close()
    return seen


async def main() -> None:
    cwd = str(ROOT)
    results = {}

    variants = [
        ("acp-plan-only", make_home(), None, True),
        ("plugin-claude-manifest", make_home(), make_plugin(".claude-plugin"), False),
        ("plugin-grok-manifest", make_home(), make_plugin(".grok-plugin"), False),
        ("plugin-compat-on", make_home(base=_GROK_SANDBOX_CONFIG.replace(
            "[compat.claude]\nmcps = false", "[compat.claude]\nmcps = true")),
         make_plugin(".claude-plugin"), False),
        ("home-config-toml", make_home(toml_block()), None, False),
    ]
    for label, home, plugin, send_plan in variants:
        try:
            seen = await probe(label, home, plugin, send_plan, cwd)
        except Exception as exc:
            seen = {"error": f"{type(exc).__name__}: {exc}"}
        results[label] = seen
        print(f"{label:26} {json.dumps(seen)}", flush=True)
        shutil.rmtree(home, ignore_errors=True)
        if plugin:
            shutil.rmtree(plugin, ignore_errors=True)

    Path("/tmp/grok-probe-results.json").write_text(json.dumps(results, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
