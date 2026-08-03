"""Session routes: CRUD, send, stream, merge/switch, model/prompt/description management."""

import asyncio
import logging
import re
import sqlite3
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.responses import StreamingResponse
from pydantic import BaseModel, field_validator, model_validator

from app.db import get_logs, get_logs_before, get_logs_sync, get_all_sessions
from app.deps import manager
from app.models import resolve_model, MODELS
from app.session import AgentStatus

logger = logging.getLogger("orchestra.sessions")

router = APIRouter()

async def _wait_for_merge_idle(session) -> bool:
    """Wait for the current turn's explicit terminal signal; only IDLE is ready."""
    if session.status.value == "idle":
        return True
    if not session.loaded or session.status.value != "running":
        return False
    return await session.wait_for_turn_completion()


def _session_base_branch(session, requested: str = "") -> str:
    """Resolve an explicit or persisted lifecycle base against the actual repository."""
    from app.workspace import resolve_base_branch

    worktree_path = session.worktree_path
    if not worktree_path:
        raise ValueError("session has no worktree")
    return resolve_base_branch(worktree_path, requested or getattr(session, "base_branch", ""))


class CreateSessionRequest(BaseModel):
    name: str
    cwd: str
    model: str = "claude-sonnet-5[1m]"
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
        if req.use_worktree:
            d["repo_path"] = session._spawn_repo_path
            d["git_common_dir"] = session._spawn_git_common_dir
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


_SOURCE_BLOCKS = [
    ("file",   "base",   "Platform Base",       "prompts/base.md",              "<platform>",       "</communication-style>", 1),
    ("file",   "role",   "Role",                "prompts/roles/*.md",           "<role>",           "</role>",           1),
    ("module", "module", "Git Workflow",         "prompts/modules/git-workflow.md",  "<git-workflow>",   "</git-workflow>",   1),
    ("module", "module", "Orchestration",        "prompts/modules/orchestration.md", "<orchestration>",  "</orchestration>",  1),
    ("module", "module", "Background Jobs",      "prompts/modules/background-jobs.md","<background-jobs>","</background-jobs>",2),
    ("module", "module", "Task Management",      "prompts/modules/task-management.md","<task-management>","</task-management>",1),
    ("module", "module", "Report Format",        "prompts/modules/report-format.md", "<report-format>",  "</report-format>",  1),
    ("module", "module", "Codex Review",         "prompts/modules/codex-review.md",  "<codex-review>",   "</codex-review>",   1),
    ("module", "module", "Before Work",          "prompts/modules/before-work.md",   "<before-work>",    "</before-work>",    1),
    ("module", "module", "Before Done",          "prompts/modules/before-done.md",   "<before-done>",    "</before-done>",    1),
    ("dynamic","dynamic","Identity",             "manager.py",                   "<identity>",       "</identity>",       1),
]


def _parse_prompt_blocks(text: str) -> list[dict]:
    """Split system prompt into blocks by SOURCE (files/modules/dynamic), not XML tags."""
    import re
    blocks = []
    consumed = set()

    for btype, tag, title, source, open_tag, close_tag, nth in _SOURCE_BLOCKS:
        start = -1
        pos = 0
        for _ in range(nth):
            idx = text.find(open_tag, pos)
            if idx == -1:
                break
            start = idx
            pos = idx + len(open_tag)
        if start == -1:
            continue
        end = text.find(close_tag, start + len(open_tag))
        if end == -1:
            continue
        end += len(close_tag)
        content = text[start:end].strip()
        if title == "Role":
            role_match = re.search(r'## Role:\s*(.+)', content)
            if role_match:
                title = f"Role: {role_match.group(1).strip()}"
        blocks.append({
            "type": btype, "tag": tag, "title": title,
            "source": source, "size": len(content), "content": content,
            "_start": start, "_end": end,
        })
        consumed.update(range(start, end))

    tail = []
    pos = 0
    for b in sorted(blocks, key=lambda x: x["_start"]):
        gap = text[pos:b["_start"]].strip()
        if gap:
            tail.append(gap)
        pos = b["_end"]
    remaining = text[pos:].strip()
    if remaining:
        tail.append(remaining)
    tail_text = "\n\n".join(tail)

    if tail_text:
        sections = re.split(r'(?=^## )', tail_text, flags=re.MULTILINE)
        for sec in sections:
            sec = sec.strip()
            if not sec:
                continue
            heading = sec.split('\n')[0].strip('#').strip()[:80] or "Text"
            blocks.append({
                "type": "dynamic", "tag": "dynamic", "title": heading,
                "source": "manager.py", "size": len(sec), "content": sec,
                "_start": 999999,
            })

    blocks.sort(key=lambda x: x.get("_start", 999999))
    for b in blocks:
        b.pop("_start", None)
        b.pop("_end", None)
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
        from app.live_broker import STREAM_CLOSE, broker
        last_id = after_id
        c = _conn()
        q = broker.subscribe(session_id)  # session_id == manager.get_session_id == session.id
        try:
            # Первым делом называем сессию, которую мы разрешили из name+scope. Клиент
            # держит историю по session_id и до этого события знает её лишь по своей карте,
            # которая могла устареть (агента убили и подняли под тем же именем). Правду
            # знает только сервер, и он обязан сказать её ДО первой строки истории.
            yield f"data: {json.dumps({'type': '__session', 'session_id': session_id})}\n\n"
            # initial history first (one-shot) — preserves load-more behavior
            if after_id == 0:
                for log in get_logs_before(session_id, before_id=2**31 - 1, limit=limit):
                    yield f"data: {json.dumps(log)}\n\n"
                    last_id = log["id"]
            while True:
                if await request.is_disconnected():
                    return
                # 1) drain live partials FIRST (ephemeral, no id) — they always
                #    precede their final 'text' row, so emit before polling DB.
                drained = 0
                while drained < 500:  # cap per tick — don't starve disconnect check
                    try:
                        payload = q.get_nowait()
                    except asyncio.QueueEmpty:
                        break
                    if payload is STREAM_CLOSE:
                        return
                    yield f"data: {json.dumps(payload)}\n\n"
                    drained += 1
                # 2) DB-persisted logs (finals + all other log types)
                logs = get_logs(session_id, after_id=last_id, conn=c)
                for log in logs:
                    yield f"data: {json.dumps(log)}\n\n"
                    last_id = log["id"]
                # 3) short poll while active (partials follow quickly), back off when idle
                await asyncio.sleep(0.1 if (logs or drained) else 0.5)
        finally:
            broker.unsubscribe(session_id, q)
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


@router.get("/api/logs/sync")
async def logs_sync(after_id: int = 0, tail: int = 20, cap: int = 16384):
    """Зеркало журнала для браузера: все сессии всех проектов одним ответом.

    Scope не принимает намеренно — пользователь один, а смысл именно в том, чтобы
    переключение в чужой проект было мгновенным. Замер: tail=20 по всем сессиям —
    ~100 КБ gzip, инкремент — единицы КБ.
    """
    return get_logs_sync(after_id=max(after_id, 0),
                         tail=max(1, min(tail, 200)),
                         cap=max(256, min(cap, 1 << 20)))


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


@router.get("/api/sessions/{name}/session-history")
async def session_history(name: str, scope: str = ""):
    session = await manager.ensure_loaded(name, scope)
    if not session:
        return JSONResponse({"error": "not found"}, status_code=404)
    return {
        "current_session_id": session.session_id,
        "history": session.session_id_history,
    }


@router.post("/api/sessions/{name}/rollback-session")
async def rollback_session(name: str, req: ScopeRequest, index: int = -1):
    session = await manager.ensure_loaded(name, req.scope)
    if not session:
        return JSONResponse({"error": "not found"}, status_code=404)
    if session.status.value == "running":
        return JSONResponse({"error": "agent is running"}, status_code=400)
    if not session.session_id_history:
        return JSONResponse({"error": "no session history"}, status_code=400)
    try:
        entry = session.session_id_history[index]
    except IndexError:
        return JSONResponse({"error": f"invalid index {index}"}, status_code=400)
    old_sid = session.session_id
    await session._disconnect_backend()
    session.session_id = entry["session_id"]
    if entry.get("runtime") and entry.get("model"):
        session.backend_type = entry["runtime"]
        session.model = entry["model"]
        session.runtime_handoff = ""
    session._persist()
    return {
        "ok": True,
        "rolled_back_to": entry["session_id"],
        "previous": old_sid,
        "runtime": session.backend_type,
        "model": session.model,
        "compacted_at": entry.get("compacted_at"),
    }


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
        # Orphan-guard: killing a parent with live children leaves them dangling
        # (no kill-cascade). Mirror the change_scope guard — block, force to override.
        children = manager._live_children(name, found.scope or scope)
        if children:
            return JSONResponse({"error": f"worker has {len(children)} live child worker(s): {', '.join(children)}. Kill or merge them first (or force=true)"}, status_code=400)
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
            try:
                base_branch = _session_base_branch(found)
            except ValueError as e:
                return JSONResponse({"error": str(e)}, status_code=400)
            from app.workspace import branch_content_status
            content_status = await asyncio.to_thread(
                branch_content_status,
                wt,
                base_branch,
            )
            if content_status.get("error"):
                return JSONResponse(
                    {
                        "error": (
                            f"worker content check failed: {content_status['error']}. "
                            "Use force=true if certain"
                        )
                    },
                    status_code=400,
                )
            if not content_status["content_merged"]:
                n = content_status["commits_ahead"]
                reason = content_status["reason"]
                return JSONResponse(
                    {
                        "error": (
                            f"worker has {n} commit(s) whose content is not verified in "
                            f"{base_branch} ({reason}). merge_worker first (or force=true)"
                        )
                    },
                    status_code=400,
                )
    try:
        await manager.remove(sid)
    except Exception as e:
        logger.error(f"session remove failed for {name}: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)
    return {"ok": True}


def _merge_not_reached(
    error: str,
    *,
    target_branch: str = "",
    worker_branch: str = "",
    worker_head: str = "",
    http_status: int = 400,
) -> dict:
    return {
        "ok": False,
        "state": "failed",
        "commit_point": "not_reached",
        "error": error or "merge rejected without an error detail",
        "target_branch": target_branch,
        "target_before": "",
        "target_after": "",
        "worker_branch": worker_branch,
        "worker_head": worker_head,
        "conflicts": [],
        "_http_status": http_status,
    }


async def _persist_lifecycle_quarantine(
    session,
    *,
    branch: str,
    base_branch: str,
) -> dict:
    """Persist a fail-closed lifecycle snapshot, retrying one transient failure."""
    errors: list[str] = []
    for _attempt in range(2):
        session.branch = branch
        session.base_branch = base_branch
        session.task_id = ""
        session.needs_switch = True
        try:
            await manager.persist_lifecycle(
                session,
                branch=branch,
                base_branch=base_branch,
                task_id="",
                needs_switch=True,
            )
        except Exception as error:
            errors.append(str(error) or type(error).__name__)
            continue
        status = {"ok": True}
        if errors:
            status.update(recovered=True, warning="; ".join(errors))
        return status
    return {
        "ok": False,
        "error": "; ".join(errors) or "lifecycle quarantine persistence failed",
    }


async def execute_merge_session(
    *,
    session_id: str,
    expected_name: str,
    expected_scope: str,
    expected_branch: str,
    expected_head: str,
    req: dict,
) -> dict:
    """Execute a merge for one pinned session identity and own its lock sequence."""
    from app import tm as _tm
    from app.db import get_session
    from app.workspace import (
        classify_head_drift,
        inspect_worktree_identity,
        merge_worktree_to_main,
        switch_worktree_branch,
    )

    requested_target = req.get("target", "")
    next_task_id = req.get("next_task_id", "")
    expected_scope = expected_scope.rstrip("/")

    async with manager.get_session_lock(session_id):
        row = await asyncio.to_thread(get_session, session_id)
        if not row or row.get("status") == "archived":
            return _merge_not_reached(
                f"session '{session_id}' not found",
                worker_branch=expected_branch,
                worker_head=expected_head,
                http_status=404,
            )
        row_scope = (row.get("scope") or "").rstrip("/")
        row_branch = row.get("branch") or ""
        if row.get("name") != expected_name or row_scope != expected_scope:
            return _merge_not_reached(
                "session identity changed before merge",
                worker_branch=row_branch,
                worker_head=expected_head,
                http_status=409,
            )
        if expected_branch and row_branch != expected_branch:
            return _merge_not_reached(
                f"session branch changed before merge: expected {expected_branch}, found {row_branch}",
                worker_branch=row_branch,
                worker_head=expected_head,
                http_status=409,
            )

        live = manager.get(session_id)
        if live is not None and (
            live.name != row["name"]
            or live.scope.rstrip("/") != row_scope
            or (live.branch or "") != row_branch
        ):
            return _merge_not_reached(
                "loaded session disagrees with its durable identity",
                worker_branch=live.branch or "",
                worker_head=expected_head,
                http_status=409,
            )
        found = live or manager._hydrate_row(row)
        worktree_path = row.get("worktree_path") or ""
        if not worktree_path:
            return _merge_not_reached(
                "session has no worktree", worker_branch=row_branch, http_status=400,
            )
        if not row_scope:
            return _merge_not_reached(
                "session has no scope", worker_branch=row_branch, http_status=400,
            )

        task_identity = None
        project_id = ""
        if next_task_id:
            try:
                task_identity = await asyncio.to_thread(
                    _tm.resolve_scoped_task_identity, row_scope, next_task_id,
                )
            except ValueError as e:
                return _merge_not_reached(
                    str(e), worker_branch=row_branch, worker_head=expected_head,
                    http_status=400,
                )
            project_id = task_identity["project_id"]
        else:
            def _project_for_scope() -> str:
                with _tm._conn() as conn:
                    project = _tm.get_project_by_scope(conn, row_scope)
                return project["id"] if project else ""

            project_id = await asyncio.to_thread(_project_for_scope)

        pinned_head = expected_head
        pinned_branch = expected_branch or row_branch
        if not pinned_head:
            try:
                actual_branch, pinned_head = await asyncio.to_thread(
                    inspect_worktree_identity, worktree_path,
                )
            except RuntimeError as e:
                return _merge_not_reached(
                    str(e), worker_branch=row_branch, http_status=400,
                )
            if pinned_branch and actual_branch != pinned_branch:
                return _merge_not_reached(
                    f"worker branch changed before merge: expected {pinned_branch}, found {actual_branch}",
                    worker_branch=actual_branch,
                    worker_head=pinned_head,
                    http_status=409,
                )
            pinned_branch = actual_branch

        try:
            target = await asyncio.to_thread(
                _session_base_branch, found, requested_target,
            )
        except ValueError as e:
            return _merge_not_reached(
                str(e), target_branch=requested_target,
                worker_branch=pinned_branch, worker_head=pinned_head,
                http_status=400,
            )

        if not await _wait_for_merge_idle(found):
            status = found.status.value
            return _merge_not_reached(
                f"worker is {status} — wait for idle before merge",
                target_branch=target, worker_branch=pinned_branch,
                worker_head=pinned_head, http_status=400,
            )

        current_row = await asyncio.to_thread(get_session, session_id)
        if (
            not current_row
            or current_row.get("status") == "archived"
            or current_row.get("name") != expected_name
            or (current_row.get("scope") or "").rstrip("/") != row_scope
            or (current_row.get("branch") or "") != row_branch
        ):
            return _merge_not_reached(
                "session identity changed while waiting to merge",
                target_branch=target, worker_branch=pinned_branch,
                worker_head=pinned_head, http_status=409,
            )

        async with AsyncExitStack() as stack:
            if found.loaded:
                await stack.enter_async_context(found._lifecycle_lock)
                if found.status.value != "idle":
                    return _merge_not_reached(
                        f"worker is {found.status.value} — wait for idle before merge",
                        target_branch=target, worker_branch=pinned_branch,
                        worker_head=pinned_head, http_status=400,
                    )
            # Личность перечитывается ЗДЕСЬ — после ожидания хода и под lifecycle-локом,
            # то есть в последний момент, когда воркер уже не может ничего дописать.
            # Пин не забывается: он уезжает в результат вместе с фактическим HEAD и классом.
            drift = await asyncio.to_thread(
                classify_head_drift, worktree_path, pinned_branch, pinned_head,
            )
            if drift["class"] == "FATAL":
                return _merge_not_reached(
                    f"worker identity drifted before merge: {drift['reason']}",
                    target_branch=target,
                    worker_branch=drift["actual_branch"] or pinned_branch,
                    worker_head=drift["actual_head"] or pinned_head,
                    http_status=409,
                )
            merge_head = drift["actual_head"] or pinned_head
            try:
                result = await asyncio.to_thread(
                    merge_worktree_to_main,
                    worktree_path,
                    row_scope,
                    target_branch=target,
                    expected_worker_branch=pinned_branch,
                    expected_worker_head=merge_head,
                )
            except Exception as e:
                return {
                    **_merge_not_reached(
                        f"merge execution failed: {type(e).__name__}: {e}",
                        target_branch=target,
                        worker_branch=pinned_branch,
                        worker_head=pinned_head,
                        http_status=500,
                    ),
                    "state": "partial",
                    "commit_point": "unknown",
                }

            if isinstance(result, dict):
                result["head_drift"] = drift["class"]
                result["worker_head_pinned"] = pinned_head
            if not result.get("ok"):
                return result

            link_results = {}
            for task_ref, commits in result.pop("merged_commits", {}).items():
                if not project_id:
                    link_results[task_ref] = {
                        "ok": False,
                        "added": 0,
                        "error": f"scope '{row_scope}' has no task project",
                    }
                    continue
                try:
                    link_results[task_ref] = await asyncio.to_thread(
                        _tm.link_commits_to_task,
                        task_ref,
                        commits,
                        project_id,
                    )
                except Exception as link_err:
                    logger.error("Failed to link commits to %s: %s", task_ref, link_err)
                    detail = str(link_err) or type(link_err).__name__
                    link_results[task_ref] = {
                        "ok": False,
                        "added": 0,
                        "error": detail,
                    }
            if link_results:
                result["linked_tasks"] = link_results

            merged_branch = (
                result.get("branch") or getattr(found, "branch", "") or ""
            )
            lifecycle_status = await _persist_lifecycle_quarantine(
                found,
                branch=merged_branch,
                base_branch=target,
            )
            result["lifecycle_status"] = lifecycle_status
            if not lifecycle_status["ok"]:
                detail = lifecycle_status["error"]
                if task_identity:
                    result["switch"] = {
                        "ok": False,
                        "error": f"switch skipped: post-merge quarantine persistence failed: {detail}",
                    }
                    result["task_status"] = {
                        "ok": False,
                        "error": "task not updated because switch was skipped",
                    }
                return result

            from app import rag_service
            result["rag_backfill_status"] = rag_service.schedule_backfill(row_scope)

            if task_identity:
                par = str(task_identity["par_number"])
                new_branch = f"task-{par}/{expected_name}"
                try:
                    switch_result = await asyncio.to_thread(
                        switch_worktree_branch,
                        worktree_path,
                        new_branch,
                        target,
                        force=True,
                    )
                except Exception as switch_error:
                    detail = str(switch_error) or type(switch_error).__name__
                    switch_result = {
                        "ok": False,
                        "state": "failed",
                        "error": f"branch switch failed: {detail}",
                    }
                if switch_result.get("ok"):
                    switched_branch = switch_result.get("branch", new_branch)
                    try:
                        await manager.persist_lifecycle(
                            found,
                            branch=switched_branch,
                            base_branch=target,
                            task_id=par,
                            needs_switch=False,
                        )
                    except Exception as persist_error:
                        detail = str(persist_error) or type(persist_error).__name__
                        switch_result = {
                            **switch_result,
                            "ok": False,
                            "state": "persistence_failed",
                            "error": (
                                f"branch switched to {switched_branch}, but lifecycle "
                                f"persistence failed: {detail}"
                            ),
                        }
                        quarantine_status = await _persist_lifecycle_quarantine(
                            found,
                            branch=switched_branch,
                            base_branch=target,
                        )
                        result["lifecycle_status"] = quarantine_status
                        if not quarantine_status["ok"]:
                            switch_result["persistence_error"] = (
                                quarantine_status["error"]
                            )
                        result["task_status"] = {
                            "ok": False,
                            "error": "task not updated because switched lifecycle was not persisted",
                        }
                        result["switch"] = switch_result
                        return result
                    try:
                        task_status = await asyncio.to_thread(
                            _tm.api_update_task_if_current,
                            task_identity,
                            status="in_progress",
                        )
                    except Exception as task_error:
                        detail = str(task_error) or type(task_error).__name__
                        task_status = {"ok": False, "error": detail}
                    if not task_status.get("ok"):
                        quarantine_status = await _persist_lifecycle_quarantine(
                            found,
                            branch=switched_branch,
                            base_branch=target,
                        )
                        result["lifecycle_status"] = quarantine_status
                        task_status["quarantined"] = quarantine_status["ok"]
                        if not quarantine_status["ok"]:
                            task_status["quarantine_error"] = (
                                quarantine_status["error"]
                            )
                    result["task_status"] = task_status
                else:
                    result["task_status"] = {
                        "ok": False,
                        "error": "task not updated because branch switch failed",
                    }
                    if switch_result.get("state") == "rollback_failed":
                        quarantine_status = await _persist_lifecycle_quarantine(
                            found,
                            branch=(
                                switch_result.get("actual_branch")
                                or getattr(found, "branch", "")
                                or ""
                            ),
                            base_branch=target,
                        )
                        result["lifecycle_status"] = quarantine_status
                        if not quarantine_status["ok"]:
                            switch_result["persistence_error"] = (
                                quarantine_status["error"]
                            )
                result["switch"] = switch_result
            return result


@router.post("/api/sessions/{name}/merge")
async def merge_session(name: str, req: dict):
    scope = req.get("scope", "")
    found = manager.get_by_name(name, scope)
    if not found:
        return JSONResponse({"error": "not found"}, status_code=404)
    result = await execute_merge_session(
        session_id=found.id,
        expected_name=found.name,
        expected_scope=found.scope or scope,
        expected_branch=getattr(found, "branch", "") or "",
        expected_head="",
        req=req,
    )
    status_code = result.pop("_http_status", None)
    if status_code:
        return JSONResponse(result, status_code=status_code)
    return result


@router.post("/api/sessions/{name}/switch-branch")
async def switch_branch(name: str, req: dict):
    from app.workspace import switch_worktree_branch
    from app import tm as _tm
    scope = req.get("scope", "")
    task_id = req.get("task_id", "")
    force = req.get("force", False)
    if not task_id:
        return JSONResponse({"error": "task_id required"}, status_code=400)
    if not isinstance(force, bool):
        return JSONResponse({"error": "force must be a boolean"}, status_code=400)
    found = manager.get_by_name(name, scope)
    if not found:
        return JSONResponse({"error": "not found"}, status_code=404)
    scope = (getattr(found, "scope", "") or scope).rstrip("/")
    try:
        task_identity = await asyncio.to_thread(
            _tm.resolve_scoped_task_identity, scope, task_id,
        )
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    par = str(task_identity["par_number"])
    worktree_path = found.worktree_path
    session_id = found.id
    if not worktree_path:
        return JSONResponse({"error": "session has no worktree"}, status_code=400)
    new_branch = f"task-{par}/{name}"
    try:
        from_ref = _session_base_branch(found, req.get("from_ref", ""))
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    async with manager.get_session_lock(session_id):
        if not await _wait_for_merge_idle(found):
            return JSONResponse(
                {"error": f"worker is {found.status.value} — wait for idle before switch"},
                status_code=400,
            )
        async with AsyncExitStack() as stack:
            if found.loaded:
                await stack.enter_async_context(found._lifecycle_lock)
                if found.status.value != "idle":
                    return JSONResponse(
                        {
                            "error": (
                                f"worker is {found.status.value} — "
                                "wait for idle before switch"
                            )
                        },
                        status_code=400,
                    )
            try:
                old_lifecycle = {
                    "branch": getattr(found, "branch", "") or "",
                    "base_branch": getattr(found, "base_branch", "") or "",
                    "task_id": getattr(found, "task_id", "") or "",
                    "needs_switch": bool(getattr(found, "needs_switch", False)),
                }
                await manager.persist_lifecycle(
                    found,
                    branch=old_lifecycle["branch"],
                    base_branch=old_lifecycle["base_branch"],
                    task_id="",
                    needs_switch=True,
                )
                result = await asyncio.to_thread(
                    switch_worktree_branch,
                    worktree_path,
                    new_branch,
                    from_ref=from_ref,
                    force=force,
                )
                if result.get("ok"):
                    switched_branch = result.get("branch", new_branch)
                    try:
                        await manager.persist_lifecycle(
                            found,
                            branch=switched_branch,
                            base_branch=from_ref,
                            task_id=par,
                            needs_switch=False,
                        )
                    except Exception as persist_error:
                        detail = str(persist_error) or type(persist_error).__name__
                        result = {
                            **result,
                            "ok": False,
                            "state": "persistence_failed",
                            "error": (
                                f"branch switched to {switched_branch}, but lifecycle "
                                f"persistence failed: {detail}"
                            ),
                        }
                        quarantine_status = await _persist_lifecycle_quarantine(
                            found,
                            branch=switched_branch,
                            base_branch=from_ref,
                        )
                        if not quarantine_status["ok"]:
                            result["persistence_error"] = quarantine_status["error"]
                        result["task_status"] = {
                            "ok": False,
                            "error": "task not updated because switched lifecycle was not persisted",
                        }
                        return result
                    try:
                        result["task_status"] = await asyncio.to_thread(
                            _tm.api_update_task_if_current,
                            task_identity,
                            status="in_progress",
                        )
                    except Exception as task_error:
                        detail = str(task_error) or type(task_error).__name__
                        result["task_status"] = {"ok": False, "error": detail}
                    if not result["task_status"].get("ok"):
                        quarantine_status = await _persist_lifecycle_quarantine(
                            found,
                            branch=switched_branch,
                            base_branch=from_ref,
                        )
                        result["task_status"]["quarantined"] = (
                            quarantine_status["ok"]
                        )
                        if not quarantine_status["ok"]:
                            result["task_status"]["quarantine_error"] = (
                                quarantine_status["error"]
                            )
                        result.update(
                            ok=False,
                            state="task_assignment_failed",
                            error=(
                                "branch switched, but task assignment failed: "
                                f"{result['task_status']['error']}"
                            ),
                        )
                elif result.get("state") == "rollback_failed":
                    quarantine_status = await _persist_lifecycle_quarantine(
                        found,
                        branch=result.get("actual_branch") or old_lifecycle["branch"],
                        base_branch=from_ref,
                    )
                    if not quarantine_status["ok"]:
                        result["persistence_error"] = quarantine_status["error"]
                else:
                    try:
                        await manager.persist_lifecycle(found, **old_lifecycle)
                    except Exception as persist_error:
                        found.task_id = ""
                        found.needs_switch = True
                        result["persistence_error"] = str(persist_error)
                return result
            except Exception as e:
                return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/api/sessions/{name}/wip")
async def session_wip(name: str, scope: str = "", base_ref: str = ""):
    from app.workspace import branch_wip_status
    found = manager.get_by_name(name, scope)
    if not found:
        return JSONResponse({"error": "not found"}, status_code=404)
    worktree_path = found.worktree_path
    if not worktree_path:
        return JSONResponse({"error": "session has no worktree"}, status_code=400)
    try:
        base_ref = _session_base_branch(found, base_ref)
        result = branch_wip_status(worktree_path, base_ref=base_ref)
        d = found.to_dict()
        result["context_pct"] = d.get("context_pct", 0)
        result["status"] = d.get("status", "unknown")
        return result
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


@router.patch("/api/sessions/{name}/tg-topic")
async def toggle_tg_topic(name: str, scope: str, enabled: bool):
    from app.db import save_session
    found = manager.get_by_name(name, scope)
    if not found:
        return JSONResponse({"error": "not found"}, status_code=404)
    found.tg_topic = enabled
    save_session(found.to_dict())
    return {"ok": True, "name": name, "tg_topic": enabled}
