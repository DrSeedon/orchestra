"""Orchestra MCP tools — injected into orchestrator sessions."""

import asyncio
import logging
import uuid

from claude_agent_sdk import tool, create_sdk_mcp_server

logger = logging.getLogger(__name__)

_manager = None


def set_manager(mgr):
    global _manager
    _manager = mgr


def _caller_scope() -> str | None:
    if not _manager:
        return None
    for s in _manager.sessions.values():
        if s.is_orchestrator:
            return s.scope
    return None


def _caller_name() -> str:
    if not _manager:
        return "orchestrator"
    for s in _manager.sessions.values():
        if s.is_orchestrator:
            return s.name
    return "orchestrator"


@tool("spawn_worker", "Spawn a new worker agent in a git worktree.", {
    "name": str,
    "task": str,
    "repo_path": str,
    "model": {"type": "string", "description": "Model ID: claude-sonnet-4-6, claude-opus-4-6[1m], claude-haiku-4-5"},
    "system_prompt": {"type": "string", "description": "Optional system prompt"},
})
async def spawn_worker(args):
    if not _manager:
        return {"content": [{"type": "text", "text": "Orchestra not initialized"}], "is_error": True}
    from app.db import add_job
    job_id = str(uuid.uuid4())[:8]
    add_job(job_id, "spawn", args["name"], args["repo_path"])
    await _manager.enqueue_worker_spawn(
        job_id=job_id,
        name=args["name"],
        task=args["task"],
        repo_path=args["repo_path"],
        model=args.get("model", "claude-sonnet-4-6"),
        system_prompt=args.get("system_prompt", ""),
    )
    return {"content": [{"type": "text", "text": f"Worker '{args['name']}' spawn queued (job {job_id}).\nCheck: list_jobs or list_workers."}]}


@tool("send_to_worker", "Send a message to worker's inbox. Worker reads inbox via API.", {
    "name": str,
    "message": str,
})
async def send_to_worker(args):
    if not _manager:
        return {"content": [{"type": "text", "text": "Orchestra not initialized"}], "is_error": True}
    from app.db import add_inbox
    name = args["name"]
    scope = _caller_scope()
    session_id = _manager.find_session_id_by_name(name, scope)
    if not session_id:
        return {"content": [{"type": "text", "text": f"Worker '{name}' not found"}], "is_error": True}
    sender = _caller_name()
    inbox_id = add_inbox(session_id, sender, args["message"])
    return {"content": [{"type": "text", "text": f"Message #{inbox_id} queued in '{name}' inbox from '{sender}'. Worker polls inbox automatically."}]}


@tool("list_workers", "List all worker sessions (active + archived).", {})
async def list_workers(args):
    if not _manager:
        return {"content": [{"type": "text", "text": "Orchestra not initialized"}], "is_error": True}
    active = [s for s in _manager.sessions.values() if not s.is_orchestrator]
    archived = [a for a in _manager.archived.values() if not a.get("is_orchestrator")]
    if not active and not archived:
        return {"content": [{"type": "text", "text": "No workers"}]}
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


@tool("get_worker_logs", "Get recent logs from a worker.", {
    "name": str,
    "limit": {"type": "integer", "description": "Max logs (default 20)"},
})
async def get_worker_logs(args):
    if not _manager:
        return {"content": [{"type": "text", "text": "Orchestra not initialized"}], "is_error": True}
    from app.db import get_logs
    name = args["name"]
    scope = _caller_scope()
    session_id = _manager.find_session_id_by_name(name, scope)
    if not session_id:
        return {"content": [{"type": "text", "text": f"Worker '{name}' not found"}], "is_error": True}
    logs = get_logs(session_id, limit=args.get("limit", 20))
    if not logs:
        return {"content": [{"type": "text", "text": f"No logs for '{name}'"}]}
    lines = [f"[{l['type']}] {l['content'][:200]}" for l in logs]
    return {"content": [{"type": "text", "text": "\n".join(lines)}]}


@tool("kill_worker", "Stop and archive a worker.", {
    "name": str,
})
async def kill_worker(args):
    if not _manager:
        return {"content": [{"type": "text", "text": "Orchestra not initialized"}], "is_error": True}
    from app.db import add_job, update_job
    name = args["name"]
    scope = _caller_scope()
    session = _manager.find_worker(name, scope)
    if session:
        job_id = str(uuid.uuid4())[:8]
        add_job(job_id, "kill", name, session.scope)
        async def _do_kill():
            try:
                await _manager.remove(session.id)
                update_job(job_id, "succeeded")
            except Exception as e:
                update_job(job_id, "failed", str(e))
        asyncio.create_task(_do_kill())
        return {"content": [{"type": "text", "text": f"Worker '{name}' kill queued (job {job_id})."}]}
    session_id = _manager.find_session_id_by_name(name, scope)
    if session_id:
        archived_name = f"{name}-{session_id[:6]}"
        _manager.archive_by_id(session_id, archived_name)
        return {"content": [{"type": "text", "text": f"Worker '{name}' archived as '{archived_name}'."}]}
    return {"content": [{"type": "text", "text": f"Worker '{name}' not found"}], "is_error": True}


@tool("stop_worker", "Interrupt a worker and set it to idle. Worktree and session are preserved — can be resumed with send_message.", {
    "name": str,
})
async def stop_worker(args):
    if not _manager:
        return {"content": [{"type": "text", "text": "Orchestra not initialized"}], "is_error": True}
    name = args["name"]
    scope = _caller_scope()
    session = _manager.find_worker(name, scope)
    if not session:
        return {"content": [{"type": "text", "text": f"Worker '{name}' not found or not running"}], "is_error": True}
    await _manager.stop_worker(session.id)
    return {"content": [{"type": "text", "text": f"Worker '{name}' interrupted and set to idle."}]}


@tool("list_jobs", "List recent spawn/kill jobs and their status.", {})
async def list_jobs(args):
    if not _manager:
        return {"content": [{"type": "text", "text": "Orchestra not initialized"}], "is_error": True}
    from app.db import get_jobs
    jobs = get_jobs(scope=_caller_scope())
    if not jobs:
        return {"content": [{"type": "text", "text": "No jobs"}]}
    lines = [f"- **{j['id']}** | {j['type']} {j['name']} | {j['status']}" +
             (f" | error: {j['error'][:100]}" if j.get('error') else "") for j in jobs]
    return {"content": [{"type": "text", "text": "\n".join(lines)}]}


@tool("set_agent_color", "Set color for an agent. Hex format like #34d399.", {
    "name": str,
    "color": str,
})
async def set_agent_color(args):
    if not _manager:
        return {"content": [{"type": "text", "text": "Orchestra not initialized"}], "is_error": True}
    for s in _manager.sessions.values():
        if s.name == args["name"]:
            s.color = args["color"]
            s._persist()
            return {"content": [{"type": "text", "text": f"Color set to {args['color']}"}]}
    return {"content": [{"type": "text", "text": f"Agent '{args['name']}' not found"}], "is_error": True}


@tool("send_message", "Send a message to any agent by name (worker→orchestrator via inbox).", {
    "to": str,
    "message": str,
})
async def send_message(args):
    if not _manager:
        return {"content": [{"type": "text", "text": "Orchestra not initialized"}], "is_error": True}
    from app.db import add_inbox
    name = args["to"]
    session_id = _manager.find_session_id_by_name(name)
    if not session_id:
        return {"content": [{"type": "text", "text": f"Agent '{name}' not found"}], "is_error": True}
    sender = None
    for s in _manager.sessions.values():
        if hasattr(s, '_client') and s._client and s.name != name:
            sender = s.name
            break
    add_inbox(session_id, sender or "unknown", args["message"])
    return {"content": [{"type": "text", "text": f"Message queued in '{name}' inbox"}]}


@tool("list_agents", "List all agents (orchestrators and workers).", {})
async def list_agents(args):
    if not _manager:
        return {"content": [{"type": "text", "text": "Orchestra not initialized"}], "is_error": True}
    if not _manager.sessions:
        return {"content": [{"type": "text", "text": "No active agents"}]}
    lines = [f"- **{s.name}** ({'orchestrator' if s.is_orchestrator else 'worker'}) | {s.status.value} | {s.model}"
             for s in _manager.sessions.values()]
    return {"content": [{"type": "text", "text": "\n".join(lines)}]}


orchestra_server = create_sdk_mcp_server(
    name="orchestra",
    tools=[spawn_worker, send_to_worker, list_workers, get_worker_logs, kill_worker, stop_worker, list_jobs, set_agent_color],
)

worker_server = create_sdk_mcp_server(
    name="orchestra",
    tools=[send_message, list_agents],
)
