"""Session routes: CRUD, send, stream, merge/switch, model/prompt/description management."""

import asyncio
import logging
import re
import sqlite3
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.responses import StreamingResponse
from pydantic import BaseModel, field_validator, model_validator

from app.db import get_logs, get_logs_before, get_all_sessions
from app.deps import manager
from app.models import resolve_model, MODELS
from app.session import AgentStatus

logger = logging.getLogger("orchestra.sessions")

router = APIRouter()


class CreateSessionRequest(BaseModel):
    name: str
    cwd: str
    model: str = "claude-sonnet-4-6"
    scope: Optional[str] = None
    system_prompt: str = ""
    use_worktree: bool = False
    repo_path: Optional[str] = None
    is_orchestrator: bool = False
    role: str = ""
    task_id: str = ""
    description: str = ""
    base_branch: str = ""
    parent_name: str = ""
    mcp_servers: dict = {}
    pipeline: str = ""
    profile: str = ""
    owned_dirs: list[str] = []
    tg_topic: bool = False

    @field_validator("name")
    @classmethod
    def validate_name(cls, v):
        if not re.match(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,49}$", v):
            raise ValueError("name must be alphanumeric with ._- allowed, 1-50 chars")
        return v

    @field_validator("model")
    @classmethod
    def validate_model(cls, v):
        resolved = resolve_model(v)
        if resolved not in MODELS:
            raise ValueError(f"unknown model '{v}'. Available: {', '.join(MODELS.keys())}")
        return resolved

    @field_validator("cwd")
    @classmethod
    def validate_cwd(cls, v):
        if not Path(v).is_dir():
            raise ValueError(f"cwd does not exist: {v}")
        return v

    @model_validator(mode="after")
    def validate_worktree(self):
        if self.use_worktree and not self.repo_path:
            raise ValueError("repo_path required when use_worktree=True")
        return self


class SendRequest(BaseModel):
    message: str
    scope: str
    sender: str | None = None


class ScopeRequest(BaseModel):
    scope: str


@router.get("/api/sessions")
async def list_sessions(scope: Optional[str] = None):
    return manager.list_sessions(scope)


@router.post("/api/sessions", status_code=201)
async def create_session(req: CreateSessionRequest):
    from app.routes.system import _is_safe_path
    if not _is_safe_path(req.cwd):
        return JSONResponse({"error": f"cwd not in allowed paths: {req.cwd}"}, status_code=403)
    from app.auth import is_auth_enabled
    if is_auth_enabled() and req.is_orchestrator:
        return JSONResponse({"error": "Orchestrator creation is disabled"}, status_code=403)
    scope = req.scope or req.cwd
    try:
        session = await manager.create_session(
            name=req.name,
            scope=scope,
            cwd=req.cwd,
            model=req.model,
            system_prompt=req.system_prompt,
            use_worktree=req.use_worktree,
            repo_path=req.repo_path,
            is_orchestrator=req.is_orchestrator,
            role=req.role,
            task_id=req.task_id,
            description=req.description,
            base_branch=req.base_branch,
            parent_name=req.parent_name,
            mcp_servers=req.mcp_servers,
            pipeline=req.pipeline,
            profile=req.profile,
            owned_dirs=req.owned_dirs,
            tg_topic=req.tg_topic,
        )
        d = session.to_dict()
        if session._spawn_warning:
            d["spawn_warning"] = session._spawn_warning
        return d
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=409)
    except sqlite3.IntegrityError:
        return JSONResponse({"error": f"session '{req.name}' already exists"}, status_code=409)
    except Exception as e:
        import traceback
        logger.error(f"spawn failed: {traceback.format_exc()}")
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/api/sessions/{name}")
async def get_session(name: str, scope: str):
    found = manager.get_by_name(name, scope)
    if not found:
        return JSONResponse({"error": "not found"}, status_code=404)
    # detached: raw DB row keeps legacy response shape (richer than to_dict)
    return found.to_dict() if found.loaded else found.db_row


@router.get("/api/sessions/{name}/prompt")
async def get_session_prompt(name: str, scope: str):
    from app.prompting import read_prompt as _read_prompt
    found = manager.get_by_name(name, scope)
    if not found:
        return JSONResponse({"error": "not found"}, status_code=404)
    sp = found.system_prompt or ""
    is_orch = found.is_orchestrator or False
    base = _read_prompt("base.md")
    base_len = len(base)
    role = ""
    custom = ""
    rest = sp[base_len:].lstrip("\n") if sp[:base_len] == base else sp
    if not is_orch:
        marker = "- Branch: "
        idx = rest.rfind(marker)
        if idx != -1:
            after_marker = rest.find("\n", idx)
            if after_marker != -1:
                role = rest[:after_marker + 1].strip()
                custom = rest[after_marker + 1:].strip()
            else:
                role = rest.strip()
        else:
            role = rest.strip()
    else:
        role = rest.strip()
    return {"system_prompt": sp, "base": base, "role": role, "custom": custom}


_BLOCK_TAG_MAP = {
    "platform": ("static", "Platform", "base.md"),
    "mcp-tools": ("static", "MCP Tools", "base.md"),
    "background-jobs": ("static", "Background Jobs", "module"),
    "rules": ("static", "Rules", "module"),
    "role": ("static", "Role", "role"),
    "git-workflow": ("static", "Git Workflow", "module"),
    "orchestration": ("static", "Orchestration", "module"),
    "decision-tree": ("static", "Decision Tree", "orchestration"),
    "tools": ("static", "Tools", "orchestration"),
    "task-workflow": ("static", "Task Workflow", "orchestration"),
    "worker-management": ("static", "Worker Management", "orchestration"),
    "workflow": ("static", "Workflow", "orchestration"),
    "pricing": ("dynamic", "Pricing", "manager.py"),
    "memory": ("static", "Memory", "module"),
    "task-management": ("static", "Task Management", "module"),
    "report-format": ("static", "Report Format", "module"),
    "codex-review": ("static", "Codex Review", "module"),
    "before-work": ("static", "Before Work", "module"),
    "before-done": ("static", "Before Done", "module"),
    "identity": ("dynamic", "Identity", "manager.py"),
}


def _parse_prompt_blocks(text: str) -> list[dict]:
    """Split system prompt into blocks by top-level XML tags."""
    import re
    blocks = []
    tag_re = re.compile(
        r'<([a-z][a-z0-9_-]*)(\s[^>]*)?>(.+?)</\1>',
        re.DOTALL,
    )
    pos = 0
    for m in tag_re.finditer(text):
        if m.start() > pos:
            gap = text[pos:m.start()].strip()
            if gap:
                block_type = "dynamic" if any(k in gap.lower() for k in
                    ["## available models", "## other orchestrators", "## your current workers"])  else "static"
                title = gap.split('\n')[0][:60].strip('#').strip() or "Text block"
                blocks.append({"type": block_type, "tag": "text", "title": title,
                               "source": "manager.py" if block_type == "dynamic" else "",
                               "size": len(gap), "content": gap})
        tag = m.group(1)
        attrs = (m.group(2) or "").strip()
        content = m.group(3).strip()
        info = _BLOCK_TAG_MAP.get(tag, ("static", tag.replace("-", " ").title(), ""))
        title = info[1]
        if attrs:
            title += f" ({attrs.strip('\"')})"
        blocks.append({
            "type": info[0], "tag": tag, "title": title,
            "source": info[2], "size": len(content), "content": content,
        })
        pos = m.end()
    if pos < len(text):
        tail = text[pos:].strip()
        if tail:
            sections = re.split(r'(?=^## )', tail, flags=re.MULTILINE)
            for sec in sections:
                sec = sec.strip()
                if not sec:
                    continue
                title = sec.split('\n')[0].strip('#').strip()[:60] or "Text"
                is_dyn = any(k in sec.lower() for k in
                    ["available models", "other orchestrators", "current workers",
                     "roles catalog", "identity"])
                blocks.append({
                    "type": "dynamic" if is_dyn else "static",
                    "tag": "section", "title": title,
                    "source": "manager.py" if is_dyn else "",
                    "size": len(sec), "content": sec,
                })
    return blocks


@router.get("/api/sessions/{name}/prompt-blocks")
async def get_prompt_blocks(name: str, scope: str):
    found = manager.get_by_name(name, scope)
    if not found:
        return JSONResponse({"error": "not found"}, status_code=404)
    sp = found.system_prompt or ""
    if not sp.strip():
        return []
    return _parse_prompt_blocks(sp)


@router.get("/api/sessions/{name}/context")
async def get_session_context(name: str, scope: str):
    found = manager.get_by_name(name, scope)
    if not found:
        return {"percentage": 0, "total_tokens": 0, "max_tokens": 0}
    if not found.loaded:
        return {"percentage": found._last_context.get("percentage", 0),
                "total_tokens": found._last_context.get("total_tokens", 0),
                "max_tokens": 200000}
    return await found.get_context()


@router.get("/api/sessions/{name}/stream")
async def stream_session_logs(name: str, scope: str, request: Request, after_id: int = 0, limit: int = 500):
    limit = min(limit, 1000)
    import json
    session_id = manager.get_session_id(name, scope)
    if not session_id:
        return JSONResponse({"error": "not found"}, status_code=404)
    async def event_generator():
        from app.db import _conn
        last_id = after_id
        initial = True
        idle_ticks = 0
        c = _conn()
        try:
            while True:
                if await request.is_disconnected():
                    return
                if initial and after_id == 0:
                    logs = get_logs_before(session_id, before_id=2**31 - 1, limit=limit)
                    initial = False
                else:
                    logs = get_logs(session_id, after_id=last_id, conn=c)
                    initial = False
                for log in logs:
                    yield f"data: {json.dumps(log)}\n\n"
                    last_id = log["id"]
                idle_ticks = 0 if logs else idle_ticks + 1
                # Back off to 3s after 2s of inactivity — reduces DB polling when idle
                await asyncio.sleep(0.5 if idle_ticks < 4 else 3.0)
        finally:
            c.close()
    return StreamingResponse(event_generator(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/api/sessions/{name}/logs")
async def get_session_logs(name: str, scope: str, after_id: int = 0, before_id: int = 0, limit: int = 500):
    limit = min(limit, 1000)
    session_id = manager.get_session_id(name, scope)
    if not session_id:
        return JSONResponse({"error": "not found"}, status_code=404)
    if before_id > 0:
        return get_logs_before(session_id, before_id, limit)
    return get_logs(session_id, after_id=after_id)


@router.post("/api/sessions/{name}/send")
async def send_message(name: str, req: SendRequest):
    try:
        session = await manager.ensure_loaded(name, req.scope)
        if not session:
            session = await manager.ensure_loaded_any(name)
        if not session:
            all_names = [s.name for s in manager.sessions.values()]
            for row in get_all_sessions():
                if row["name"] not in all_names:
                    all_names.append(row["name"])
            similar = [n for n in all_names if name.lower() in n.lower() or n.lower() in name.lower()]
            hint = f" Similar: {', '.join(similar[:5])}" if similar else f" Available: {', '.join(all_names[:10])}"
            return JSONResponse({"error": f"agent '{name}' not found.{hint}"}, status_code=404)
        if hasattr(session, 'needs_switch') and session.needs_switch:
            return JSONResponse({"error": "worker was merged — call switch_worker_branch first"}, status_code=400)
        msg = f"[from:{req.sender}] {req.message}" if req.sender else req.message
        if req.sender:
            msg += manager._context_warning(req.sender)
            if hasattr(session, 'last_task_sender'):
                session.last_task_sender = req.sender
        else:
            from datetime import datetime, timezone, timedelta
            local_tz = timezone(timedelta(hours=7))
            now = datetime.now(local_tz).strftime("%H:%M")
            msg = f"[{now}] {msg}"
        await manager.send(session.id, msg)
        pn = session.parent_name or ""
        return {"ok": True, "parent_name": pn}
    except (RuntimeError, KeyError) as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    except Exception as e:
        logger.error(f"send_message failed for {name}: {e}", exc_info=True)
        return JSONResponse({"error": f"Send failed: {e}"}, status_code=500)


@router.post("/api/sessions/{name}/compact")
async def compact_session(name: str, req: ScopeRequest):
    session = await manager.ensure_loaded(name, req.scope)
    if not session:
        return JSONResponse({"error": "not found"}, status_code=404)
    if session.status.value == "running":
        return JSONResponse({"error": "agent is running, wait for idle"}, status_code=400)
    result = await session.compact()
    return result


@router.post("/api/sessions/{name}/restart-cli")
async def restart_cli(name: str, req: ScopeRequest):
    session = await manager.ensure_loaded(name, req.scope)
    if not session:
        return JSONResponse({"error": "not found"}, status_code=404)
    await session._disconnect_backend()
    session.status = AgentStatus.IDLE
    session._persist()
    return {"ok": True}


@router.post("/api/sessions/{name}/interrupt")
async def interrupt_session(name: str, req: ScopeRequest):
    found = manager.get_by_name(name, req.scope)
    if not found or not found.loaded:
        return JSONResponse({"error": "agent not running"}, status_code=404)
    await manager.interrupt(found.id)
    return {"ok": True}


@router.post("/api/sessions/{name}/stop")
async def stop_session(name: str, req: ScopeRequest):
    found = manager.get_by_name(name, req.scope)
    if not found or not found.loaded:
        return JSONResponse({"error": "agent not running"}, status_code=404)
    await manager.stop_worker(found.id)
    return {"ok": True}


@router.post("/api/sessions/{name}/description")
async def update_description(name: str, req: dict):
    scope = req.get("scope", "")
    desc = req.get("description", "")
    if not manager.update_session_fields(name, scope, description=desc):
        return JSONResponse({"error": "not found"}, status_code=404)
    return {"ok": True}


@router.post("/api/sessions/{name}/tg_topic")
async def update_tg_topic(name: str, req: dict):
    scope = req.get("scope", "")
    enabled = bool(req.get("enabled", False))
    if not manager.update_session_fields(name, scope, tg_topic=enabled):
        return JSONResponse({"error": "not found"}, status_code=404)
    return {"ok": True, "tg_topic": enabled}


@router.post("/api/sessions/{name}/prompt")
async def update_prompt(name: str, req: dict):
    scope = req.get("scope", "")
    prompt = req.get("system_prompt", "")
    if not manager.update_session_fields(name, scope, system_prompt=prompt):
        return JSONResponse({"error": "not found"}, status_code=404)
    return {"ok": True}


@router.post("/api/sessions/{name}/change-model")
async def change_model(name: str, req: dict):
    scope = req.get("scope", "")
    new_model = req.get("model", "").strip()
    if not new_model:
        return JSONResponse({"error": "model required"}, status_code=400)
    new_model = resolve_model(new_model)
    if new_model not in MODELS:
        return JSONResponse({"error": f"unknown model: {new_model}"}, status_code=400)
    found = manager.get_by_name(name, scope)
    if not found or not found.loaded:
        return JSONResponse({"error": "session not loaded"}, status_code=404)
    result = await found.change_model(new_model)
    if not result.get("ok"):
        return JSONResponse(result, status_code=409)
    return result


@router.post("/api/sessions/{name}/rename")
async def rename_session(name: str, req: dict):
    scope = req.get("scope", "")
    new_name = req.get("new_name", "").strip()
    if not new_name:
        return JSONResponse({"error": "new_name required"}, status_code=400)
    if not re.match(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,49}$", new_name):
        return JSONResponse({"error": "invalid name: alphanumeric with ._- allowed, 1-50 chars"}, status_code=400)
    found = manager.get_by_name(name, scope)
    if not found:
        return JSONResponse({"error": "not found"}, status_code=404)
    sid = found.id
    session = manager.sessions.get(sid)
    old_branch = None
    new_branch = None
    from app.db import _conn
    with _conn() as c:
        row = c.execute("SELECT branch, system_prompt FROM sessions WHERE id=?", (sid,)).fetchone()
        updates = {"name": new_name}
        if row and row["system_prompt"]:
            updates["system_prompt"] = row["system_prompt"].replace(
                f"Worker name: {name}", f"Worker name: {new_name}"
            ).replace(
                f"Orchestrator: {name}", f"Orchestrator: {new_name}"
            )
        if row and row["branch"] and row["branch"].endswith(f"/{name}"):
            old_branch = row["branch"]
            new_branch = row["branch"][: -len(name)] + new_name
            updates["branch"] = new_branch
        sets = ", ".join(f"{k}=?" for k in updates)
        try:
            c.execute(f"UPDATE sessions SET {sets} WHERE id=?", (*updates.values(), sid))
        except sqlite3.IntegrityError:
            return JSONResponse({"error": "name already taken"}, status_code=409)
    if session:
        session.name = new_name
        if updates.get("system_prompt"):
            session.system_prompt = updates["system_prompt"]
        if new_branch:
            session.branch = new_branch
        session._persist()
    if old_branch and new_branch:
        wt_path = (session.worktree_path if session else None) or found.worktree_path
        if wt_path and Path(wt_path).is_dir():
            import subprocess
            subprocess.run(
                ["git", "branch", "-m", old_branch, new_branch],
                cwd=wt_path, capture_output=True,
            )
    is_orch = session.is_orchestrator if session else found.is_orchestrator
    if is_orch:
        try:
            from app.tg_bridge import rename_orch_topic
            await rename_orch_topic(name, new_name)
        except Exception as e:
            logger.warning(f"TG topic rename failed: {e}")

    return {"ok": True, "old_name": name, "new_name": new_name, "branch": new_branch}


@router.delete("/api/sessions/{name}")
async def delete_session(name: str, scope: str, force: bool = False):
    found = manager.get_by_name(name, scope)
    if not found:
        return JSONResponse({"error": "not found"}, status_code=404)
    sid = found.id
    if not force:
        if found.loaded and found.status.value == "running":
            return JSONResponse({"error": "worker is running — stop first (or force=true)"}, status_code=400)
        wt = found.worktree_path
        if wt and Path(wt).is_dir():
            status_proc = await asyncio.create_subprocess_exec(
                "git", "status", "--porcelain", cwd=wt,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(status_proc.communicate(), timeout=5)
            except asyncio.TimeoutError:
                status_proc.kill()
                return JSONResponse({"error": "git status timed out in worktree. Use force=true if certain"}, status_code=400)
            if status_proc.returncode != 0:
                return JSONResponse({"error": f"git status failed: {stderr.decode().strip()}. Use force=true if certain"}, status_code=400)
            dirty = stdout.decode().strip()
            if dirty:
                files = [l[3:] for l in dirty.splitlines()[:10]]
                return JSONResponse({"error": f"worker has uncommitted changes: {', '.join(files)}. Commit or discard first (or force=true)"}, status_code=400)
            ahead_proc = await asyncio.create_subprocess_exec(
                "git", "rev-list", "main..HEAD", "--count", cwd=wt,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(ahead_proc.communicate(), timeout=5)
            except asyncio.TimeoutError:
                ahead_proc.kill()
                return JSONResponse({"error": "git rev-list timed out. Use force=true if certain"}, status_code=400)
            ahead = stdout.decode().strip()
            if ahead_proc.returncode != 0 or not ahead.isdigit():
                return JSONResponse({"error": f"git rev-list failed: {stderr.decode().strip()}. Use force=true if certain"}, status_code=400)
            n = int(ahead)
            if n > 0:
                return JSONResponse({"error": f"worker has {n} unmerged commit(s). merge_worker first (or force=true)"}, status_code=400)
    await manager.remove(sid)
    return {"ok": True}


@router.post("/api/sessions/{name}/merge")
async def merge_session(name: str, req: dict):
    from app.workspace import merge_worktree_to_main
    from app import tm as _tm
    scope = req.get("scope", "")
    target = req.get("target", "main")
    next_task_id = req.get("next_task_id", "")
    found = manager.get_by_name(name, scope)
    if not found:
        return JSONResponse({"error": "not found"}, status_code=404)
    if found.loaded and found.status.value == "running":
        return JSONResponse({"error": "worker is running — wait for idle before merge"}, status_code=400)
    worktree_path = found.worktree_path
    scope = found.scope or scope
    session_id = found.id
    if not worktree_path:
        return JSONResponse({"error": "session has no worktree"}, status_code=400)
    if not scope:
        return JSONResponse({"error": "session has no scope"}, status_code=400)
    async with manager.get_session_lock(session_id):
        try:
            result = await asyncio.to_thread(merge_worktree_to_main, worktree_path, scope, target_branch=target)
            if result.get("ok"):
                link_results = {}
                with _tm._conn() as _lc:
                    _proj = _tm.get_project_by_scope(_lc, scope)
                _link_project_id = _proj["id"] if _proj else ""
                for task_ref, commits in result.pop("merged_commits", {}).items():
                    try:
                        link_results[task_ref] = _tm.link_commits_to_task(task_ref, commits, project_id=_link_project_id)
                    except Exception as link_err:
                        logger.error("Failed to link commits to %s: %s", task_ref, link_err)
                        link_results[task_ref] = {"ok": False, "error": str(link_err)}
                if link_results:
                    result["linked_tasks"] = link_results
                if found.loaded:
                    found.branch = target
                    found.task_id = ""
                    found.needs_switch = True
                    found._persist()
                if next_task_id and found.loaded:
                    from app.workspace import switch_worktree_branch, _normalize_task_id
                    par = _normalize_task_id(next_task_id)
                    new_branch = f"task-{par}/{name}"
                    switch_result = await asyncio.to_thread(
                        switch_worktree_branch, worktree_path, new_branch, f"refs/heads/{target}", force=True)
                    if switch_result.get("ok"):
                        found.branch = switch_result.get("branch", new_branch)
                        found.task_id = par
                        found.needs_switch = False
                        found._persist()
                        try:
                            _tm.api_update_task(par, status="in_progress")
                        except Exception as e:
                            logger.warning(f"task #{par} → in_progress failed after merge-switch: {e}")
                    result["switch"] = switch_result
            return result
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/api/sessions/{name}/switch-branch")
async def switch_branch(name: str, req: dict):
    from app.workspace import switch_worktree_branch, _normalize_task_id
    from app import tm as _tm
    scope = req.get("scope", "")
    task_id = req.get("task_id", "")
    if not task_id:
        return JSONResponse({"error": "task_id required"}, status_code=400)
    try:
        par = _normalize_task_id(task_id)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    found = manager.get_by_name(name, scope)
    if not found:
        return JSONResponse({"error": "not found"}, status_code=404)
    if found.loaded and found.status.value == "running":
        return JSONResponse({"error": "worker is running — wait for idle"}, status_code=400)
    worktree_path = found.worktree_path
    session_id = found.id
    if not worktree_path:
        return JSONResponse({"error": "session has no worktree"}, status_code=400)
    new_branch = f"task-{par}/{name}"
    from_ref = req.get("from_ref", "refs/heads/main")
    async with manager.get_session_lock(session_id):
        try:
            result = await asyncio.to_thread(switch_worktree_branch, worktree_path, new_branch, from_ref=from_ref)
            if found.loaded:
                if result.get("ok") or result.get("branch"):
                    found.branch = result.get("branch", new_branch)
                    found.task_id = par
                    found.needs_switch = False
                    found._persist()
            try:
                _tm.api_update_task(par, status="in_progress")
            except Exception as e:
                logger.warning(f"task #{par} → in_progress failed after switch-branch: {e}")
            return result
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/api/sessions/{name}/wip")
async def session_wip(name: str, scope: str = "", base_ref: str = "refs/heads/main"):
    from app.workspace import branch_wip_status
    found = manager.get_by_name(name, scope)
    if not found:
        return JSONResponse({"error": "not found"}, status_code=404)
    worktree_path = found.worktree_path
    if not worktree_path:
        return JSONResponse({"error": "session has no worktree"}, status_code=400)
    try:
        return branch_wip_status(worktree_path, base_ref=base_ref)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/api/sessions/check-conflict")
async def check_conflict_endpoint(req: dict):
    from app.workspace import simulate_conflict
    scope = req.get("scope", "")
    name_a = req.get("worker_a", "")
    name_b = req.get("worker_b", "")
    a = manager.get_by_name(name_a, scope)
    b = manager.get_by_name(name_b, scope)
    if not a or not b:
        missing = name_a if not a else name_b
        return JSONResponse({"error": f"worker '{missing}' not found"}, status_code=404)
    wt_a = a.worktree_path
    branch_a = a.branch
    branch_b = b.branch
    if not wt_a or not branch_a or not branch_b:
        return JSONResponse({"error": "both workers must have a worktree and branch"}, status_code=400)
    try:
        return simulate_conflict(wt_a, branch_a, branch_b)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/api/sessions/{name}/progress")
async def update_progress(name: str, req: dict):
    scope = req.get("scope", "")
    pct = max(0, min(100, int(req.get("percent", 0))))
    status_text = str(req.get("status", ""))
    session = manager.get_by_name(name, scope)
    if not session or not session.loaded:
        # progress is live-only: detached sessions 404 (write would flip legacy 404→200)
        session = next((s for s in manager.sessions.values() if s.name == name), None)
    if not session:
        return JSONResponse({"error": "not found"}, status_code=404)
    session.progress_pct = pct
    session.progress_status = status_text
    session._persist()
    return {"ok": True}


@router.get("/api/sessions/{name}/inbox")
async def get_session_inbox(name: str, scope: str):
    from app.db import get_inbox, ack_inbox
    session_id = manager.get_session_id(name, scope)
    if not session_id:
        return JSONResponse({"error": "not found"}, status_code=404)
    messages = get_inbox(session_id)
    for m in messages:
        ack_inbox(m["id"])
    return messages
