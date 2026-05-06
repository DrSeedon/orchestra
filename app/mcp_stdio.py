"""External stdio MCP server for Orchestra.

Runs as a separate process, communicates with Orchestra via HTTP API.
Avoids the in-process SDK control_request deadlock (issue #425/#701).

Usage: python -m app.mcp_stdio
"""

import logging
import os
import sys

import httpx
from mcp.server.fastmcp import FastMCP

logging.basicConfig(level=logging.INFO, stream=sys.stderr)
logger = logging.getLogger("orchestra-mcp")

ORCHESTRA_URL = os.environ.get("ORCHESTRA_URL", "http://127.0.0.1:8888")
SCOPE = os.environ.get("ORCHESTRA_SCOPE", "")
ROLE = os.environ.get("ORCHESTRA_ROLE", "orchestrator")
WORKER_NAME = os.environ.get("WORKER_NAME", "worker")

mcp = FastMCP("orchestra")


async def _api(method: str, path: str, **kwargs) -> dict | list | None:
    async with httpx.AsyncClient(base_url=ORCHESTRA_URL, timeout=30) as client:
        if method == "GET":
            r = await client.get(path, params=kwargs.get("params"))
        elif method == "POST":
            r = await client.post(path, json=kwargs.get("json"))
        elif method == "DELETE":
            r = await client.delete(path, params=kwargs.get("params"))
        else:
            return None
        if r.status_code >= 400:
            return {"error": r.text}
        return r.json()


@mcp.tool()
async def spawn_worker(name: str, task: str, repo_path: str,
                       model: str = "claude-sonnet-4-6",
                       system_prompt: str = "") -> str:
    """Spawn a new worker agent in a git worktree."""
    result = await _api("POST", "/api/sessions", json={
        "name": name, "scope": repo_path, "cwd": repo_path,
        "model": model, "system_prompt": system_prompt,
        "use_worktree": True, "repo_path": repo_path,
    })
    if isinstance(result, dict) and result.get("error"):
        return f"Spawn failed: {result['error']}"
    await _api("POST", f"/api/sessions/{name}/send", json={
        "message": task, "scope": repo_path,
    })
    return f"Worker '{name}' spawned. Model: {model}. Task sent."


@mcp.tool()
async def send_message(to: str, message: str) -> str:
    """Send a message to any agent by name. Triggers a new turn."""
    result = await _api("POST", f"/api/sessions/{to}/send", json={
        "message": message, "sender": WORKER_NAME or ROLE, "scope": SCOPE,
    })
    if isinstance(result, dict) and result.get("error"):
        return f"Send failed: {result['error']}"
    return f"Message sent to '{to}'"


@mcp.tool()
async def list_agents() -> str:
    """List all agents (orchestrators and workers)."""
    sessions = await _api("GET", "/api/sessions", params={"scope": SCOPE} if SCOPE else None)
    if not isinstance(sessions, list):
        return f"Error: {sessions}"
    if not sessions:
        return "No agents"
    lines = []
    for s in sessions:
        role = "🎯" if s.get("is_orchestrator") else "⚙️"
        st = "🟢" if s.get("status") in ("running", "idle") else "⚪"
        lines.append(f"{st} {role} **{s['name']}** | {s.get('status','?')} | {s.get('model','?')} | ${s.get('cost_usd',0):.4f}")
    return "\n".join(lines)


@mcp.tool()
async def get_worker_logs(name: str, limit: int = 20) -> str:
    """Get recent logs from a worker."""
    logs = await _api("GET", f"/api/sessions/{name}/logs", params={"scope": SCOPE, "after_id": 0})
    if isinstance(logs, dict) and logs.get("error"):
        return f"Error: {logs['error']}"
    if not logs:
        return f"No logs for '{name}'"
    lines = []
    for l in logs[-limit:]:
        t, c = l['type'], l['content'][:200]
        if t == 'text':
            lines.append(f"💬 {c}")
        elif t == 'user_message':
            lines.append(f"👤 {c}")
        elif t == 'tool':
            lines.append(f"🔧 {c}")
        elif t == 'error':
            lines.append(f"❌ {c}")
    return "\n".join(lines) if lines else f"No meaningful logs for '{name}'"


@mcp.tool()
async def kill_worker(name: str) -> str:
    """Stop and archive a worker."""
    result = await _api("POST", f"/api/sessions/{name}/stop", json={"scope": SCOPE})
    if isinstance(result, dict) and result.get("error"):
        return f"Kill failed: {result['error']}"
    return f"Worker '{name}' stopped and archived."


@mcp.tool()
async def list_jobs() -> str:
    """List recent spawn/kill jobs."""
    jobs = await _api("GET", "/api/jobs", params={"scope": SCOPE} if SCOPE else None)
    if not isinstance(jobs, list):
        return f"Error: {jobs}"
    if not jobs:
        return "No jobs"
    return "\n".join(f"- {j['id']}: {j['type']} {j['name']} = {j['status']}" for j in jobs)


KESHA_INBOX_URL = os.environ.get("KESHA_INBOX_URL", "http://127.0.0.1:18081")


@mcp.tool()
async def notify_kesha(message: str, sender: str = "") -> str:
    """Send a message to Kesha (Telegram bot). He will see it in TG and can respond."""
    who = sender or WORKER_NAME or ROLE
    async with httpx.AsyncClient(base_url=KESHA_INBOX_URL, timeout=10) as client:
        try:
            r = await client.post("/inbox", json={"message": message, "sender": who})
            if r.status_code >= 400:
                return f"Failed: {r.text}"
            return f"Kesha notified by {who}"
        except Exception as e:
            return f"Failed to reach Kesha: {e}"



if __name__ == "__main__":
    logger.info(f"Orchestra MCP stdio (url={ORCHESTRA_URL}, scope={SCOPE})")
    mcp.run(transport="stdio")
