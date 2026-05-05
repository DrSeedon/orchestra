"""Orchestra — AI Agent Orchestrator API."""

import asyncio
import re
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from starlette.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, field_validator, model_validator

from app.db import init_db, get_logs
from app.manager import SessionManager
from app.models import resolve_model, MODELS

manager = SessionManager()
templates = Jinja2Templates(directory="app/templates")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    await manager.auto_resume_orchestrators()
    manager.start_background_tasks()
    yield
    await manager.shutdown_all()


app = FastAPI(title="Orchestra", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="app/static"), name="static")


class CreateSessionRequest(BaseModel):
    name: str
    cwd: str
    model: str = "claude-sonnet-4-6"
    scope: Optional[str] = None
    system_prompt: str = ""
    use_worktree: bool = False
    repo_path: Optional[str] = None
    is_orchestrator: bool = False

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


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    return templates.TemplateResponse(request, "dashboard.html")


@app.get("/api/jobs")
async def list_api_jobs(scope: str | None = None):
    from app.db import get_jobs
    return get_jobs(scope=scope)


@app.get("/api/sessions")
async def list_sessions(scope: Optional[str] = None):
    return manager.list_sessions(scope)


@app.post("/api/sessions", status_code=201)
async def create_session(req: CreateSessionRequest):
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
        )
        return session.to_dict()
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=409)
    except sqlite3.IntegrityError:
        return JSONResponse({"error": f"session '{req.name}' already exists"}, status_code=409)


@app.get("/api/sessions/{name}")
async def get_session(name: str, scope: str):
    found = manager.get_by_name(name, scope)
    if not found:
        return JSONResponse({"error": "not found"}, status_code=404)
    if isinstance(found, dict):
        return found
    return found.to_dict()


@app.get("/api/sessions/{name}/context")
async def get_session_context(name: str, scope: str):
    found = manager.get_by_name(name, scope)
    if not found or isinstance(found, dict):
        return {"percentage": 0, "total_tokens": 0, "max_tokens": 0}
    return await found.get_context()


@app.get("/api/sessions/{name}/stream")
async def stream_session_logs(name: str, scope: str, after_id: int = 0):
    import json
    session_id = manager.get_session_id(name, scope)
    if not session_id:
        return JSONResponse({"error": "not found"}, status_code=404)
    async def event_generator():
        last_id = after_id
        while True:
            logs = get_logs(session_id, after_id=last_id)
            for log in logs:
                yield f"data: {json.dumps(log)}\n\n"
                last_id = log["id"]
            await asyncio.sleep(0.5)
    return StreamingResponse(event_generator(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/sessions/{name}/logs")
async def get_session_logs(name: str, scope: str, after_id: int = 0):
    session_id = manager.get_session_id(name, scope)
    if not session_id:
        return JSONResponse({"error": "not found"}, status_code=404)
    return get_logs(session_id, after_id=after_id)


@app.post("/api/sessions/{name}/send")
async def send_message(name: str, req: SendRequest):
    session = await manager.ensure_loaded(name, req.scope)
    if not session:
        return JSONResponse({"error": "not found"}, status_code=404)
    try:
        msg = f"[from:{req.sender}] {req.message}" if req.sender else req.message
        await manager.send(session.id, msg)
        return {"ok": True}
    except RuntimeError as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@app.post("/api/sessions/{name}/interrupt")
async def interrupt_session(name: str, req: ScopeRequest):
    found = manager.get_by_name(name, req.scope)
    if not found or isinstance(found, dict):
        return JSONResponse({"error": "agent not running"}, status_code=404)
    await manager.interrupt(found.id)
    return {"ok": True}


@app.post("/api/sessions/{name}/stop")
async def stop_session(name: str, req: ScopeRequest):
    found = manager.get_by_name(name, req.scope)
    if not found or isinstance(found, dict):
        return JSONResponse({"error": "not found or already stopped"}, status_code=404)
    await manager.stop(found.id)
    return {"ok": True}


@app.delete("/api/sessions/{name}")
async def delete_session(name: str, scope: str):
    found = manager.get_by_name(name, scope)
    if not found:
        return JSONResponse({"error": "not found"}, status_code=404)
    sid = found["id"] if isinstance(found, dict) else found.id
    await manager.remove(sid)
    return {"ok": True}


@app.get("/api/sessions/{name}/inbox")
async def get_session_inbox(name: str, scope: str):
    from app.db import get_inbox, ack_inbox
    session_id = manager.get_session_id(name, scope)
    if not session_id:
        return JSONResponse({"error": "not found"}, status_code=404)
    messages = get_inbox(session_id)
    for m in messages:
        ack_inbox(m["id"])
    return messages


@app.get("/api/stats")
async def stats(scope: Optional[str] = None):
    return manager.stats(scope)


@app.get("/api/orchestrators")
async def list_orchestrators():
    return [s.to_dict() for s in manager.sessions.values() if s.is_orchestrator]


@app.get("/api/projects")
async def list_projects():
    import os
    projects_dir = Path.home() / ".claude" / "projects"
    if not projects_dir.is_dir():
        return []
    results = []
    for name in sorted(projects_dir.iterdir()):
        parts = name.name.split("-")
        candidate = "/" + "/".join(parts[1:])
        if Path(candidate).is_dir() and candidate != "/":
            folder = candidate.rstrip("/").split("/")[-1]
            results.append({"path": candidate, "name": folder})
    return results


@app.get("/api/models")
async def list_models():
    return [{"id": k, "name": v} for k, v in MODELS.items()]
