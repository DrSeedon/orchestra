"""Orchestra MCP tools — injected into orchestrator sessions."""

import logging

from claude_agent_sdk import tool, create_sdk_mcp_server

logger = logging.getLogger(__name__)

_manager = None


def set_manager(mgr):
    global _manager
    _manager = mgr


@tool("spawn_worker", "Spawn a new worker agent in a git worktree. Worker gets its own branch and isolated copy of the repo.", {
    "name": str,
    "task": str,
    "repo_path": str,
    "model": {"type": "string", "description": "Model ID. Must be one of: claude-sonnet-4-6 (default), claude-opus-4-6[1m], claude-haiku-4-5. Always use full ID, not aliases."},
    "system_prompt": {"type": "string", "description": "Optional system prompt for the worker"},
})
async def spawn_worker(args):
    if not _manager:
        return {"content": [{"type": "text", "text": "Orchestra not initialized"}], "is_error": True}
    name = args["name"]
    task = args["task"]
    repo_path = args["repo_path"]
    model = args.get("model", "claude-sonnet-4-6")
    system_prompt = args.get("system_prompt", "")
    scope = repo_path
    try:
        session = await _manager.create_session(
            name=name,
            scope=scope,
            cwd=repo_path,
            model=model,
            system_prompt=system_prompt,
            use_worktree=True,
            repo_path=repo_path,
        )
        await session.send(task)
        return {"content": [{"type": "text", "text": f"Worker '{name}' spawned on {repo_path}\nBranch: {session.branch}\nModel: {model}\nTask sent."}]}
    except Exception as e:
        return {"content": [{"type": "text", "text": f"Spawn failed: {e}"}], "is_error": True}


@tool("send_to_worker", "Send a message to an existing worker.", {
    "name": str,
    "message": str,
})
async def send_to_worker(args):
    if not _manager:
        return {"content": [{"type": "text", "text": "Orchestra not initialized"}], "is_error": True}
    name = args["name"]
    message = args["message"]
    session = None
    for s in _manager.sessions.values():
        if s.name == name and not s.is_orchestrator:
            session = s
            break
    if not session:
        return {"content": [{"type": "text", "text": f"Worker '{name}' not found"}], "is_error": True}
    try:
        await session.send(message)
        return {"content": [{"type": "text", "text": f"Message sent to '{name}'"}]}
    except Exception as e:
        return {"content": [{"type": "text", "text": f"Send failed: {e}"}], "is_error": True}


@tool("list_workers", "List all worker sessions (active + archived) with their status.", {})
async def list_workers(args):
    if not _manager:
        return {"content": [{"type": "text", "text": "Orchestra not initialized"}], "is_error": True}
    active = [s for s in _manager.sessions.values() if not s.is_orchestrator]
    active_ids = {s.id for s in active}
    from app.db import get_all_sessions
    archived = [s for s in get_all_sessions()
                if not s.get("is_orchestrator") and s["status"] in ("stopped", "error")
                and s["id"] not in active_ids]
    if not active and not archived:
        return {"content": [{"type": "text", "text": "No workers (active or archived)"}]}
    lines = []
    if active:
        lines.append("**Active:**")
        for w in active:
            lines.append(f"- **{w.name}** | {w.status.value} | {w.model} | ${w.cost_usd:.4f}")
    if archived:
        lines.append("\n**Archived:**")
        for s in archived:
            lines.append(f"- **{s['name']}** | {s['status']} | {s['model']} | ${s.get('cost_usd', 0):.4f}")
    return {"content": [{"type": "text", "text": "\n".join(lines)}]}


@tool("get_worker_logs", "Get recent logs from a worker (active or archived).", {
    "name": str,
    "limit": {"type": "integer", "description": "Max logs to return (default 20)"},
})
async def get_worker_logs(args):
    if not _manager:
        return {"content": [{"type": "text", "text": "Orchestra not initialized"}], "is_error": True}
    from app.db import get_logs, get_all_sessions
    name = args["name"]
    limit = args.get("limit", 20)
    session_id = None
    for s in _manager.sessions.values():
        if s.name == name:
            session_id = s.id
            break
    if not session_id:
        for s in get_all_sessions():
            if s["name"] == name:
                session_id = s["id"]
                break
    if not session_id:
        return {"content": [{"type": "text", "text": f"Worker '{name}' not found (active or archived)"}], "is_error": True}
    logs = get_logs(session_id, limit=limit)
    if not logs:
        return {"content": [{"type": "text", "text": f"No logs for '{name}'"}]}
    lines = [f"[{l['type']}] {l['content'][:200]}" for l in logs]
    return {"content": [{"type": "text", "text": "\n".join(lines)}]}


@tool("kill_worker", "Stop and remove a worker.", {
    "name": str,
})
async def kill_worker(args):
    if not _manager:
        return {"content": [{"type": "text", "text": "Orchestra not initialized"}], "is_error": True}
    name = args["name"]
    session = None
    for s in _manager.sessions.values():
        if s.name == name and not s.is_orchestrator:
            session = s
            break
    if session:
        try:
            await _manager.stop(session.id)
            archived_name = session.name
            del _manager.sessions[session.id]
            return {"content": [{"type": "text", "text": f"Worker '{name}' killed. Archived as '{archived_name}' — read logs with get_worker_logs(name='{archived_name}')."}]}
        except Exception as e:
            return {"content": [{"type": "text", "text": f"Kill failed: {e}"}], "is_error": True}
    from app.db import get_all_sessions
    for s in get_all_sessions():
        if s["name"] == name:
            return {"content": [{"type": "text", "text": f"Worker '{name}' already archived in DB (status: {s['status']})"}]}
    return {"content": [{"type": "text", "text": f"Worker '{name}' not found"}], "is_error": True}


@tool("restart_worker", "Kill and respawn a worker with the same config but a new task.", {
    "name": str,
    "task": str,
})
async def restart_worker(args):
    if not _manager:
        return {"content": [{"type": "text", "text": "Orchestra not initialized"}], "is_error": True}
    name = args["name"]
    task = args["task"]
    session = None
    for s in _manager.sessions.values():
        if s.name == name and not s.is_orchestrator:
            session = s
            break
    if not session:
        return {"content": [{"type": "text", "text": f"Worker '{name}' not found"}], "is_error": True}
    repo_path = session.scope
    model = session.model
    try:
        await _manager.remove(session.id)
        new_session = await _manager.create_session(
            name=name, scope=repo_path, cwd=repo_path, model=model,
            use_worktree=True, repo_path=repo_path,
        )
        await new_session.send(task)
        return {"content": [{"type": "text", "text": f"Worker '{name}' restarted with new task.\nBranch: {new_session.branch}"}]}
    except Exception as e:
        return {"content": [{"type": "text", "text": f"Restart failed: {e}"}], "is_error": True}


orchestra_server = create_sdk_mcp_server(
    name="orchestra",
    tools=[spawn_worker, send_to_worker, list_workers, get_worker_logs, kill_worker, restart_worker],
)


@tool("send_message", "Send a message to any agent (orchestrator or worker) by name.", {
    "to": str,
    "message": str,
})
async def send_message(args):
    if not _manager:
        return {"content": [{"type": "text", "text": "Orchestra not initialized"}], "is_error": True}
    name = args["to"]
    message = args["message"]
    session = None
    for s in _manager.sessions.values():
        if s.name == name:
            session = s
            break
    if not session:
        return {"content": [{"type": "text", "text": f"Agent '{name}' not found"}], "is_error": True}
    try:
        await session.send(message)
        return {"content": [{"type": "text", "text": f"Message sent to '{name}'"}]}
    except Exception as e:
        return {"content": [{"type": "text", "text": f"Send failed: {e}"}], "is_error": True}


@tool("list_agents", "List all agents (orchestrators and workers) with their status.", {})
async def list_agents(args):
    if not _manager:
        return {"content": [{"type": "text", "text": "Orchestra not initialized"}], "is_error": True}
    if not _manager.sessions:
        return {"content": [{"type": "text", "text": "No active agents"}]}
    lines = []
    for s in _manager.sessions.values():
        role = "orchestrator" if s.is_orchestrator else "worker"
        lines.append(f"- **{s.name}** ({role}) | {s.status.value} | {s.model} | ${s.cost_usd:.4f}")
    return {"content": [{"type": "text", "text": "\n".join(lines)}]}


worker_server = create_sdk_mcp_server(
    name="orchestra",
    tools=[send_message, list_agents],
)
