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
async def send_to_worker(name: str, message: str) -> str:
    """Send a message to worker's inbox."""
    sessions = await _api("GET", "/api/sessions", params={"scope": SCOPE} if SCOPE else None)
    if not isinstance(sessions, list):
        return f"Error: {sessions}"
    sid = next((s["id"] for s in sessions if s["name"] == name), None)
    if not sid:
        return f"Worker '{name}' not found"
    from app.db import add_inbox
    add_inbox(sid, ROLE, message)
    return f"Message queued in '{name}' inbox."


@mcp.tool()
async def list_workers() -> str:
    """List all worker sessions."""
    sessions = await _api("GET", "/api/sessions", params={"scope": SCOPE} if SCOPE else None)
    if not isinstance(sessions, list):
        return f"Error: {sessions}"
    workers = [s for s in sessions if not s.get("is_orchestrator") and s.get("is_orchestrator") != 1]
    if not workers:
        return "No workers"
    lines = []
    for w in workers:
        st = w.get("status", "?")
        lines.append(f"{'🟢' if st in ('running','idle') else '🪦'} **{w['name']}** | {st} | {w.get('model','?')} | ${w.get('cost_usd',0):.4f}")
    return "\n".join(lines)


@mcp.tool()
async def get_worker_logs(name: str, limit: int = 20) -> str:
    """Get recent logs from a worker."""
    logs = await _api("GET", f"/api/sessions/{name}/logs", params={"scope": SCOPE, "after_id": 0})
    if isinstance(logs, dict) and logs.get("error"):
        return f"Error: {logs['error']}"
    if not logs:
        return f"No logs for '{name}'"
    return "\n".join(f"[{l['type']}] {l['content'][:200]}" for l in logs[-limit:])


@mcp.tool()
async def kill_worker(name: str) -> str:
    """Stop and archive a worker."""
    result = await _api("DELETE", f"/api/sessions/{name}", params={"scope": SCOPE})
    if isinstance(result, dict) and result.get("error"):
        return f"Kill failed: {result['error']}"
    return f"Worker '{name}' killed."


@mcp.tool()
async def list_jobs() -> str:
    """List recent spawn/kill jobs."""
    jobs = await _api("GET", "/api/jobs", params={"scope": SCOPE} if SCOPE else None)
    if not isinstance(jobs, list):
        return f"Error: {jobs}"
    if not jobs:
        return "No jobs"
    return "\n".join(f"- {j['id']}: {j['type']} {j['name']} = {j['status']}" for j in jobs)


@mcp.tool()
async def send_message(to: str, message: str) -> str:
    """Send a message to any agent (worker→orchestrator)."""
    await _api("POST", f"/api/sessions/{to}/send", json={
        "message": f"[from:{WORKER_NAME}] {message}", "scope": SCOPE,
    })
    return f"Message sent to '{to}'"


@mcp.tool()
async def list_agents() -> str:
    """List all active agents."""
    sessions = await _api("GET", "/api/sessions", params={"scope": SCOPE} if SCOPE else None)
    if not isinstance(sessions, list):
        return f"Error: {sessions}"
    active = [s for s in sessions if s.get("status") in ("running", "idle")]
    if not active:
        return "No active agents"
    return "\n".join(f"- **{s['name']}** ({'orch' if s.get('is_orchestrator') else 'worker'}) | {s['status']}" for s in active)


if __name__ == "__main__":
    logger.info(f"Orchestra MCP stdio (url={ORCHESTRA_URL}, scope={SCOPE})")
    mcp.run(transport="stdio")
