#!/usr/bin/env python3
"""Which injection route survives a repo-local `.mcp.json` that declares the same name?

cwd is a worktree of this repo, which tracks a `.mcp.json` defining a server called
`orchestra`. Grok merges project scope over global scope by name, then folder-trust drops
the project entry — annihilating ours. Reads Grok's own debug log for the verdict.
"""
import asyncio, json, os, re, shutil, subprocess, sys, uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from app.backend_grok import GROK_BIN
from probe_routes import make_home, make_plugin, toml_block, acp_plan


def run(label: str, cwd: str, plugin: Path | None, send_plan: bool,
        config_server: bool) -> dict:
    home = make_home(toml_block() if config_server else "")
    log = f"/tmp/grok-collision-{label}-{uuid.uuid4().hex[:6]}.log"
    argv = [GROK_BIN, "agent", "--model", "grok-4.5", "--always-approve"]
    if plugin:
        argv += ["--plugin-dir", str(plugin)]
    argv += ["--debug", "--debug-file", log, "stdio"]

    params = {"cwd": cwd}
    if send_plan:
        params["mcpServers"] = acp_plan()
    stdin = "\n".join(json.dumps(m) for m in [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": 1, "clientCapabilities": {
                "fs": {"readTextFile": False, "writeTextFile": False}, "terminal": False}}},
        {"jsonrpc": "2.0", "id": 2, "method": "session/new", "params": params},
    ]) + "\n"

    env = dict(os.environ)
    for var in ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy", "ALL_PROXY", "all_proxy"):
        env.pop(var, None)
    env["GROK_HOME"] = str(home)
    try:
        subprocess.run(argv, input=stdin, text=True, env=env, cwd=cwd,
                       capture_output=True, timeout=90)
    except subprocess.TimeoutExpired:
        pass
    text = Path(log).read_text(errors="replace") if Path(log).exists() else ""
    created = re.search(r"created with (\d+) MCP servers", text)
    names = re.search(r"config_count=(\d+) config_names=(\[[^\]]*\])", text)
    shutil.rmtree(home, ignore_errors=True)
    return {
        "created": int(created.group(1)) if created else None,
        "init_count": int(names.group(1)) if names else None,
        "init_names": names.group(2) if names else None,
        "untrusted_skip": "folder untrusted" in text,
        "log": log,
    }


def main() -> None:
    cwd = str(ROOT)  # a worktree of this repo — tracks .mcp.json with an `orchestra` entry
    assert (Path(cwd) / ".mcp.json").exists(), "probe needs the colliding .mcp.json present"
    plugin = make_plugin(".claude-plugin")
    cases = [
        ("acp-plan", None, True, False),
        ("config-toml", None, False, True),
        ("plugin-dir", plugin, False, False),
        ("plugin+plan", plugin, True, False),
    ]
    results = {}
    for label, plug, send_plan, config_server in cases:
        results[label] = run(label, cwd, plug, send_plan, config_server)
        print(f"{label:14} {json.dumps(results[label])}", flush=True)
    Path("/tmp/grok-collision-results.json").write_text(json.dumps(results, indent=2))
    shutil.rmtree(plugin, ignore_errors=True)


if __name__ == "__main__":
    main()
