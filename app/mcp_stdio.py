"""External stdio MCP server for Orchestra.

Runs as a separate process, communicates with Orchestra via HTTP API.
Avoids the in-process SDK control_request deadlock (issue #425/#701).

Usage: python -m app.mcp_stdio
"""

import json
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
    t = kwargs.pop("timeout", 30)
    async with httpx.AsyncClient(base_url=ORCHESTRA_URL, timeout=t) as client:
        if method == "GET":
            r = await client.get(path, params=kwargs.get("params"))
        elif method == "POST":
            r = await client.post(path, json=kwargs.get("json"))
        elif method == "PUT":
            r = await client.put(path, json=kwargs.get("json"))
        elif method == "DELETE":
            r = await client.delete(path, params=kwargs.get("params"))
        else:
            return None
        if r.status_code >= 400:
            return {"error": r.text}
        return r.json()


@mcp.tool()
async def spawn_worker(name: str, task: str, repo_path: str,
                       model: str = "",
                       system_prompt: str = "",
                       task_id: str = "") -> str:
    """Spawn a new worker agent in a git worktree. Model is REQUIRED — choose explicitly: claude-opus-4-6[1m] for research/planning/long-lived, claude-sonnet-4-6 for implementation from spec, gpt-5.5 for Codex."""
    if not model:
        return "Error: model is required. Choose: claude-opus-4-6[1m] (think), claude-sonnet-4-6 (type), gpt-5.5 (codex)"
    scope = SCOPE or repo_path
    body = {
        "name": name, "scope": scope, "cwd": repo_path,
        "model": model, "system_prompt": system_prompt,
        "use_worktree": True, "repo_path": repo_path,
    }
    if task_id:
        body["task_id"] = task_id
    result = await _api("POST", "/api/sessions", json=body)
    if isinstance(result, dict) and result.get("error"):
        return f"Spawn failed: {result['error']}"
    await _api("POST", f"/api/sessions/{name}/send", json={
        "message": task, "scope": scope,
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
    """List all agents in your project (orchestrators and workers)."""
    sessions = await _api("GET", "/api/sessions", params={"scope": SCOPE} if SCOPE else None)
    if not isinstance(sessions, list):
        return f"Error: {sessions}"
    if not sessions:
        return "No agents"
    lines = []
    for s in sessions:
        role = "🎯" if s.get("is_orchestrator") else "⚙️"
        st = "🟢" if s.get("status") in ("running", "idle") else "⚪"
        ctx = s.get('context_pct', 0)
        ctx_str = f" | ctx:{ctx}%" if ctx else ""
        lines.append(f"{st} {role} **{s['name']}** | {s.get('status','?')} | {s.get('model','?')} | ${s.get('cost_usd',0):.4f}{ctx_str}")
    return "\n".join(lines)


@mcp.tool()
async def list_orchestrators() -> str:
    """List ALL orchestrators across all projects. Use to find agents you can talk to from other projects."""
    orchs = await _api("GET", "/api/orchestrators")
    if not isinstance(orchs, list):
        return f"Error: {orchs}"
    if not orchs:
        return "No orchestrators"
    lines = []
    for o in orchs:
        scope_short = o.get("scope", "").rstrip("/").split("/")[-1]
        ctx = o.get('context_pct', 0)
        ctx_str = f" | ctx:{ctx}%" if ctx else ""
        lines.append(f"🎯 **{o['name']}** | {o.get('status','?')} | {scope_short} | ${o.get('cost_usd',0):.4f}{ctx_str}")
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
async def compact_worker(name: str) -> str:
    """Compact a worker's context — summarize, reset session, continue fresh. Use when worker context >80%. Returns summary. Takes ~30-60s."""
    result = await _api("POST", f"/api/sessions/{name}/compact", json={"scope": SCOPE}, timeout=120)
    if isinstance(result, dict) and result.get("error"):
        return f"Compact failed: {result['error']}"
    if isinstance(result, dict) and result.get("ok"):
        return f"Compact done: {result.get('before_pct', '?')}% → {result.get('after_pct', '?')}%. Summary ({result.get('summary_chars', 0)} chars): {result.get('summary', '')}"
    return f"Compact result: {result}"


@mcp.tool()
async def kill_worker(name: str) -> str:
    """Stop and archive a worker."""
    result = await _api("DELETE", f"/api/sessions/{name}", params={"scope": SCOPE})
    if isinstance(result, dict) and result.get("error"):
        return f"Kill failed: {result['error']}"
    return f"Worker '{name}' stopped and archived."


@mcp.tool()
async def stop_worker(name: str) -> str:
    """Interrupt a worker and set it to idle. Worktree and session are preserved — can be resumed later with send_message."""
    result = await _api("POST", f"/api/sessions/{name}/stop", json={"scope": SCOPE})
    if isinstance(result, dict) and result.get("error"):
        return f"Stop failed: {result['error']}"
    return f"Worker '{name}' interrupted and set to idle."


@mcp.tool()
async def rename_worker(old_name: str, new_name: str) -> str:
    """Rename a worker agent."""
    result = await _api("POST", f"/api/sessions/{old_name}/rename", json={"new_name": new_name, "scope": SCOPE})
    if isinstance(result, dict) and result.get("error"):
        return f"Rename failed: {result['error']}"
    return f"Worker '{old_name}' renamed to '{new_name}'."


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
async def send_file(path: str, caption: str = "", as_document: bool = False) -> str:
    """Send a file to the user via Telegram. Path must be absolute. Images are sent as inline photos by default; set as_document=True to force file attachment."""
    result = await _api("POST", "/api/tg/send_file", json={
        "path": path, "caption": caption, "scope": SCOPE, "sender": WORKER_NAME or ROLE,
        "as_document": as_document,
    })
    if isinstance(result, dict) and result.get("error"):
        return f"Send failed: {result['error']}"
    return f"File sent to TG: {path}"


@mcp.tool()
async def update_progress(percent: int, status: str) -> str:
    """Update task progress. percent: 0-100, status: short description of current step."""
    result = await _api("POST", f"/api/sessions/{WORKER_NAME}/progress", json={
        "percent": percent, "status": status, "scope": SCOPE,
    })
    if isinstance(result, dict) and result.get("error"):
        return f"Progress update failed: {result['error']}"
    return f"Progress: {percent}% — {status}"


@mcp.tool()
async def change_worker_model(name: str, model: str) -> str:
    """Change a worker's model (e.g. sonnet→opus) without losing context. Worker must be idle."""
    result = await _api("POST", f"/api/sessions/{name}/change-model", json={"scope": SCOPE, "model": model})
    if isinstance(result, dict) and result.get("error"):
        return f"Model change failed: {result['error']}"
    if isinstance(result, dict) and result.get("changed"):
        return f"Model changed: {result.get('old_model')} → {result.get('model')}"
    return f"Model already {result.get('model', model)}"


@mcp.tool()
async def merge_worker(name: str) -> str:
    """Merge a worker's branch into main. Returns commit count or conflict file list."""
    result = await _api("POST", f"/api/sessions/{name}/merge", json={"scope": SCOPE})
    if isinstance(result, dict) and result.get("error"):
        return f"Merge failed: {result['error']}"
    if isinstance(result, dict) and result.get("ok"):
        n = result.get("commits_merged", 0)
        branch = result.get("branch", "?")
        parts = [f"Merged {n} commit{'s' if n != 1 else ''} from branch {branch}"]
        linked = result.get("linked_tasks", {})
        if linked:
            for par, info in linked.items():
                added = info.get("added", 0) if isinstance(info, dict) else 0
                parts.append(f"  → {par}: {added} commits linked")
        new_branch = result.get("new_branch")
        if new_branch:
            parts.append(f"New branch: {new_branch}")
        return "\n".join(parts)
    if isinstance(result, dict) and not result.get("ok"):
        conflicts = result.get("conflicts", [])
        if conflicts:
            return f"Conflicts in: {', '.join(conflicts)}"
        return f"Merge failed: {result.get('error', 'unknown error')}"
    return f"Merge result: {result}"


@mcp.tool()
async def report_bug(title: str, description: str) -> str:
    """Report a bug or issue with the Orchestra platform. Saves to bugs.md for the developer."""
    from datetime import datetime, timezone
    bugs_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "BUGS.md")
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    entry = f"\n## [{ts}] {title}\n- **Reporter:** {WORKER_NAME}\n- **Scope:** {SCOPE}\n{description}\n"
    with open(bugs_path, "a") as f:
        f.write(entry)
    return f"Bug reported: {title}"





@mcp.tool()
async def task_create(title: str, project: str, price: int = 0,
                      description: str = "", assignee: str = "",
                      status: str = "new") -> str:
    """Create a new task. Returns PAR number and task details.
    price is in thousands (e.g. 20 = 20,000₽). 0 is valid (no price)."""
    result = await _api("POST", "/api/tm/tasks", json={
        "title": title, "project": project, "price": price,
        "description": description, "assignee": assignee, "status": status,
    })
    if isinstance(result, dict) and result.get("error"):
        return f"Error: {result['error']}"
    return json.dumps(result, ensure_ascii=False)


@mcp.tool()
async def task_update(par: str, title: str = "", description: str = "",
                      price: int = -1, status: str = "",
                      assignee: str = "") -> str:
    """Update an existing task. Only provided fields are changed.
    par: 'PAR-42' or '42'. price in thousands (-1 = don't change, 0 = set to zero).
    Empty string = don't change for text fields."""
    body: dict = {}
    if title:
        body["title"] = title
    if description:
        body["description"] = description
    if price >= 0:
        body["price"] = price
    if status:
        body["status"] = status
    if assignee:
        body["assignee"] = assignee
    if not body:
        return "Nothing to update"
    result = await _api("PUT", f"/api/tm/tasks/{par}", json=body)
    if isinstance(result, dict) and result.get("error"):
        return f"Error: {result['error']}"
    return json.dumps(result, ensure_ascii=False)


@mcp.tool()
async def task_list(project: str = "", status: str = "",
                    assignee: str = "") -> str:
    """List tasks with optional filters. Returns summary per task."""
    params = {}
    if project:
        params["project"] = project
    if status:
        params["status"] = status
    if assignee:
        params["assignee"] = assignee
    result = await _api("GET", "/api/tm/tasks", params=params)
    if isinstance(result, dict) and result.get("error"):
        return f"Error: {result['error']}"
    return json.dumps(result, ensure_ascii=False)


@mcp.tool()
async def task_get(par: str) -> str:
    """Get full task details including payment history and linked commits."""
    result = await _api("GET", f"/api/tm/tasks/{par}")
    if isinstance(result, dict) and result.get("error"):
        return f"Error: {result['error']}"
    return json.dumps(result, ensure_ascii=False)


@mcp.tool()
async def payment_receive(amount: int, client: str = "aleksandr-kislinskiy",
                          date: str = "", note: str = "") -> str:
    """Record incoming payment. Auto-distributes to done tasks (smallest debt first).
    amount in thousands (e.g. 30 = 30,000₽)."""
    result = await _api("POST", "/api/tm/payments", json={
        "amount": amount, "client": client, "date": date, "note": note,
    })
    if isinstance(result, dict) and result.get("error"):
        return f"Error: {result['error']}"
    return json.dumps(result, ensure_ascii=False)


@mcp.tool()
async def payment_status(client: str = "aleksandr-kislinskiy") -> str:
    """Get payment overview: balance, total debt, recent payments."""
    result = await _api("GET", "/api/tm/payments/status", params={"client": client})
    if isinstance(result, dict) and result.get("error"):
        return f"Error: {result['error']}"
    return json.dumps(result, ensure_ascii=False)


@mcp.tool()
async def bg_create(type: str, message: str = "", target: str = "",
                    delay_seconds: int = 0, path: str = "", pattern: str = "",
                    command: str = "", host: str = "",
                    interval_seconds: int = 60,
                    timeout_seconds: int = 3600) -> str:
    """Create a background job that wakes an agent when triggered. Survives hibernate.
    Types:
    - timer: fires after delay_seconds
    - file: watches file at path for pattern (regex)
    - command: runs command every interval_seconds, matches pattern in output
    - ssh: streams ssh command output, matches pattern
    - run: executes command, wakes agent when done with exit code + output
    target: agent name (default: you). timeout_seconds: max lifetime (default 1h, max 24h)."""
    config = {}
    if type == "timer":
        config = {"delay_seconds": delay_seconds}
    elif type == "file":
        config = {"path": path, "pattern": pattern}
    elif type == "command":
        config = {"command": command, "pattern": pattern, "interval_seconds": interval_seconds}
    elif type == "ssh":
        config = {"command": command, "host": host, "pattern": pattern}
    elif type == "run":
        config = {"command": command, "host": host} if host else {"command": command}
    target_name = target or WORKER_NAME
    result = await _api("POST", "/api/bg/jobs", json={
        "type": type, "config": config, "message": message,
        "target_name": target_name, "target_scope": SCOPE,
        "timeout_seconds": timeout_seconds, "created_by": WORKER_NAME,
    })
    if isinstance(result, dict) and result.get("error"):
        return f"Error: {result['error']}"
    return f"Background job created: {result.get('id', '?')} (type={type}, target={target_name})"


@mcp.tool()
async def bg_list() -> str:
    """List active background jobs in your project."""
    jobs = await _api("GET", "/api/bg/jobs", params={"scope": SCOPE})
    if not isinstance(jobs, list):
        return f"Error: {jobs}"
    if not jobs:
        return "No background jobs"
    icons = {"timer": "⏰", "file": "📄", "command": "🖥️", "ssh": "🔗", "run": "🚀"}
    lines = []
    for j in jobs:
        icon = icons.get(j["type"], "❓")
        status = j["status"]
        target = j.get("target_name", "?")
        msg = j.get("message", "")[:60]
        lines.append(f"{icon} **{j['id']}** | {status} | → {target} | {msg}")
    return "\n".join(lines)


@mcp.tool()
async def bg_cancel(job_id: str) -> str:
    """Cancel an active background job."""
    result = await _api("DELETE", f"/api/bg/jobs/{job_id}")
    if isinstance(result, dict) and result.get("error"):
        return f"Cancel failed: {result['error']}"
    return f"Job {job_id} cancelled."


if __name__ == "__main__":
    logger.info(f"Orchestra MCP stdio (url={ORCHESTRA_URL}, scope={SCOPE})")
    mcp.run(transport="stdio")
