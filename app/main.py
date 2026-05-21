"""Orchestra — AI Agent Orchestrator API."""

import asyncio
import hashlib
import hmac
import json
import logging
import os
import re
import sqlite3
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request, UploadFile, Form
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.responses import StreamingResponse
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, field_validator, model_validator

from app.db import init_db, get_logs, get_logs_before
from app.manager import SessionManager
from app.models import resolve_model, MODELS

manager = SessionManager()
templates = Jinja2Templates(directory="app/templates")


@asynccontextmanager
async def lifespan(app: FastAPI):
    from dotenv import load_dotenv
    load_dotenv()
    init_db()
    await manager.auto_resume_orchestrators()
    manager.start_background_tasks()
    from app.bg_jobs import bg_manager
    bg_manager.set_session_manager(manager)
    await bg_manager.restore_from_db()
    from app.tg_bridge import start_bridge, stop_bridge
    await start_bridge(manager)
    yield
    await stop_bridge()
    await bg_manager.shutdown()
    await manager.shutdown_all()


app = FastAPI(title="Orchestra", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="app/static"), name="static")


from app.auth import is_auth_enabled, validate_session, requires_auth, check_internal_token


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        method = request.method
        if check_internal_token(request.headers.get("authorization", "")):
            return await call_next(request)
        if not is_auth_enabled():
            return await call_next(request)
        if not requires_auth(path, method):
            return await call_next(request)
        token = request.cookies.get("session")
        if token and validate_session(token):
            return await call_next(request)
        if path.startswith("/api/"):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        return RedirectResponse("/login", status_code=302)


app.add_middleware(AuthMiddleware)


class CreateSessionRequest(BaseModel):
    name: str
    cwd: str
    model: str = "claude-sonnet-4-6"
    scope: Optional[str] = None
    system_prompt: str = ""
    use_worktree: bool = False
    repo_path: Optional[str] = None
    is_orchestrator: bool = False
    task_id: str = ""
    description: str = ""

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


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    if not is_auth_enabled():
        return RedirectResponse("/", status_code=302)
    return templates.TemplateResponse(request, "login.html", {"error": ""})


@app.post("/login")
async def login_submit(request: Request, username: str = Form(""), password: str = Form("")):
    from app.auth import check_credentials, create_session
    if not is_auth_enabled():
        return RedirectResponse("/", status_code=302)
    if check_credentials(username, password):
        token = create_session(username)
        response = RedirectResponse("/", status_code=302)
        secure = request.url.scheme == "https" or os.environ.get("COOKIE_SECURE") == "1"
        response.set_cookie("session", token, httponly=True, samesite="lax", max_age=86400, secure=secure)
        return response
    return templates.TemplateResponse(request, "login.html", {"error": "Invalid credentials"})


@app.post("/logout")
async def logout(request: Request):
    response = RedirectResponse("/login", status_code=302)
    response.delete_cookie("session")
    return response



@app.get("/api/jobs")
async def list_api_jobs(scope: str | None = None):
    from app.db import get_jobs
    return get_jobs(scope=scope)


def _encode_path(path: str) -> str:
    return "".join("-" if (c == "/" or c == " " or ord(c) > 127) else c for c in path)


def _build_path_map() -> dict[str, str]:
    scan_roots = [
        "/mnt/data/Projects/Python",
        "/mnt/data/Projects/Unity",
        "/mnt/data/Projects",
        str(Path.home()),
    ]
    mapping = {}
    for root in scan_roots:
        if not Path(root).is_dir():
            continue
        mapping[_encode_path(root)] = root
        for entry in Path(root).iterdir():
            if entry.is_dir() and not entry.name.startswith("."):
                mapping[_encode_path(str(entry))] = str(entry)
    return mapping


@app.get("/api/projects")
async def list_projects():
    projects_dir = Path.home() / ".claude" / "projects"
    if not projects_dir.is_dir():
        return []
    path_map = _build_path_map()
    results = []
    for entry in sorted(projects_dir.iterdir()):
        if not entry.is_dir():
            continue
        real_path = path_map.get(entry.name)
        if not real_path or not Path(real_path).is_dir():
            continue
        if real_path == str(Path.home()):
            continue
        folder = real_path.rstrip("/").split("/")[-1]
        results.append({"path": real_path, "name": folder})
    return results


_ALLOWED_ROOTS: list[str] = []


def _get_allowed_roots() -> list[str]:
    if _ALLOWED_ROOTS:
        return _ALLOWED_ROOTS
    extra = os.environ.get("ALLOWED_ROOTS", "")
    if extra:
        for p in extra.split(":"):
            if p and Path(p).is_dir():
                _ALLOWED_ROOTS.append(p)
    for root in ["/mnt/data/Projects", "/opt", str(Path.home())]:
        if Path(root).is_dir():
            _ALLOWED_ROOTS.append(root)
    uploads = str(Path(__file__).parent.parent / "data" / "uploads")
    _ALLOWED_ROOTS.append(uploads)
    return _ALLOWED_ROOTS


_DENIED_PARTS = {".env", ".claude", ".ssh", ".git", ".credentials", ".config", ".gnupg", ".aws"}
_DENIED_EXTENSIONS = {".db", ".db-shm", ".db-wal", ".db-journal", ".sqlite", ".sqlite3", ".key", ".pem", ".p12", ".pfx"}


def _is_safe_path(path: str) -> bool:
    try:
        p = Path(path).resolve()
        resolved = str(p)
    except (ValueError, OSError):
        return False
    if not any(resolved.startswith(root) for root in _get_allowed_roots()):
        return False
    for part in p.parts:
        if part in _DENIED_PARTS or part.startswith(".env"):
            return False
    if p.suffix in _DENIED_EXTENSIONS:
        return False
    return True


BINARY_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.gif', '.ico', '.bmp', '.webp',
                     '.zip', '.tar', '.gz', '.bz2', '.xz', '.rar', '.7z',
                     '.exe', '.bin', '.so', '.whl', '.dll', '.dylib', '.pyc',
                     '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.mp3', '.mp4',
                     '.wav', '.avi', '.mov', '.ttf', '.otf', '.woff', '.woff2'}

@app.get("/api/files/raw")
async def get_file_raw(path: str):
    if not _is_safe_path(path):
        return JSONResponse({"error": "access denied"}, status_code=403)
    from starlette.responses import FileResponse
    target = Path(path)
    if not target.is_file():
        return JSONResponse({"error": "not found"}, status_code=404)
    return FileResponse(str(target))


@app.get("/api/files/content")
async def get_file_content(path: str):
    if not _is_safe_path(path):
        return JSONResponse({"error": "access denied"}, status_code=403)
    target = Path(path)
    if not target.exists():
        return JSONResponse({"error": "not found"}, status_code=404)
    if not target.is_file():
        return JSONResponse({"error": "not a file"}, status_code=400)
    size = target.stat().st_size
    if target.suffix.lower() in BINARY_EXTENSIONS:
        return JSONResponse({"error": "binary file", "size": size})
    if size > 500 * 1024:
        return JSONResponse({"error": "too large", "size": size})
    content = target.read_text(encoding="utf-8", errors="replace")
    return {"content": content, "size": size, "name": str(target)}


@app.post("/api/open-folder")
async def open_folder(req: dict):
    if not os.environ.get("ALLOW_OPEN_FOLDER"):
        return JSONResponse({"error": "disabled on this server"}, status_code=403)
    import subprocess
    path = req.get("path", "")
    if not Path(path).is_dir():
        return JSONResponse({"error": "not a directory"}, status_code=400)
    env = {**os.environ, "DISPLAY": ":0", "WAYLAND_DISPLAY": "wayland-0", "XDG_RUNTIME_DIR": f"/run/user/{os.getuid()}"}
    subprocess.Popen(["xdg-open", path], env=env)
    return {"ok": True}


@app.get("/api/files")
async def list_files(path: str):
    if not _is_safe_path(path):
        return JSONResponse({"error": "access denied"}, status_code=403)
    target = Path(path)
    if not target.is_dir():
        return JSONResponse({"error": "not a directory"}, status_code=400)
    items = []
    try:
        for entry in sorted(target.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower())):
            items.append({
                "name": entry.name,
                "path": str(entry),
                "is_dir": entry.is_dir(),
                "size": entry.stat().st_size if entry.is_file() else None,
            })
    except PermissionError:
        pass
    return items


@app.get("/api/sessions")
async def list_sessions(scope: Optional[str] = None):
    return manager.list_sessions(scope)


@app.post("/api/sessions", status_code=201)
async def create_session(req: CreateSessionRequest):
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
            task_id=req.task_id,
            description=req.description,
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


@app.get("/api/sessions/{name}/prompt")
async def get_session_prompt(name: str, scope: str):
    from app.manager import _read_prompt
    found = manager.get_by_name(name, scope)
    if not found:
        return JSONResponse({"error": "not found"}, status_code=404)
    sp = (found.get("system_prompt", "") if isinstance(found, dict) else found.system_prompt) or ""
    is_orch = (found.get("is_orchestrator") if isinstance(found, dict) else found.is_orchestrator) or False
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


@app.get("/api/sessions/{name}/context")
async def get_session_context(name: str, scope: str):
    found = manager.get_by_name(name, scope)
    if not found:
        return {"percentage": 0, "total_tokens": 0, "max_tokens": 0}
    if isinstance(found, dict):
        pct = found.get("context_pct", 0) or 0
        tokens = found.get("context_tokens", 0) or 0
        return {"percentage": pct, "total_tokens": tokens, "max_tokens": 200000}
    return await found.get_context()


@app.get("/api/sessions/{name}/stream")
async def stream_session_logs(name: str, scope: str, request: Request, after_id: int = 0, limit: int = 500):
    limit = min(limit, 1000)
    import json
    session_id = manager.get_session_id(name, scope)
    if not session_id:
        return JSONResponse({"error": "not found"}, status_code=404)
    async def event_generator():
        last_id = after_id
        initial = True
        while True:
            if await request.is_disconnected():
                return
            if initial and after_id == 0:
                logs = get_logs_before(session_id, before_id=2**31 - 1, limit=limit)
                initial = False
            else:
                logs = get_logs(session_id, after_id=last_id)
                initial = False
            for log in logs:
                yield f"data: {json.dumps(log)}\n\n"
                last_id = log["id"]
            await asyncio.sleep(0.5)
    return StreamingResponse(event_generator(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/sessions/{name}/logs")
async def get_session_logs(name: str, scope: str, after_id: int = 0, before_id: int = 0, limit: int = 500):
    limit = min(limit, 1000)
    session_id = manager.get_session_id(name, scope)
    if not session_id:
        return JSONResponse({"error": "not found"}, status_code=404)
    if before_id > 0:
        return get_logs_before(session_id, before_id, limit)
    return get_logs(session_id, after_id=after_id)


@app.post("/api/sessions/{name}/send")
async def send_message(name: str, req: SendRequest):
    session = await manager.ensure_loaded(name, req.scope)
    if not session:
        session = await manager.ensure_loaded_any(name)
    if not session:
        return JSONResponse({"error": "not found"}, status_code=404)
    try:
        msg = f"[from:{req.sender}] {req.message}" if req.sender else req.message
        if req.sender:
            msg += manager._context_warning(req.sender)
        else:
            from datetime import datetime, timezone, timedelta
            local_tz = timezone(timedelta(hours=7))
            now = datetime.now(local_tz).strftime("%H:%M")
            msg = f"[{now}] {msg}"
        await manager.send(session.id, msg)
        return {"ok": True}
    except RuntimeError as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@app.post("/api/sessions/{name}/compact")
async def compact_session(name: str, req: ScopeRequest):
    session = await manager.ensure_loaded(name, req.scope)
    if not session:
        session = await manager.ensure_loaded_any(name)
    if not session:
        return JSONResponse({"error": "not found"}, status_code=404)
    if session.status.value == "running":
        return JSONResponse({"error": "agent is running, wait for idle"}, status_code=400)
    result = await session.compact()
    return result


@app.post("/api/sessions/{name}/restart-cli")
async def restart_cli(name: str, req: ScopeRequest):
    session = await manager.ensure_loaded(name, req.scope)
    if not session:
        session = await manager.ensure_loaded_any(name)
    if not session:
        return JSONResponse({"error": "not found"}, status_code=404)
    await session._disconnect_client()
    session.status = session.status.__class__("idle")
    session._persist()
    return {"ok": True}


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
        return JSONResponse({"error": "agent not running"}, status_code=404)
    await manager.stop_worker(found.id)
    return {"ok": True}


@app.post("/api/sessions/{name}/description")
async def update_description(name: str, req: dict):
    scope = req.get("scope", "")
    desc = req.get("description", "")
    found = manager.get_by_name(name, scope)
    if not found:
        return JSONResponse({"error": "not found"}, status_code=404)
    sid = found["id"] if isinstance(found, dict) else found.id
    session = manager.sessions.get(sid)
    if session:
        session.description = desc
        session._persist()
    else:
        from app.db import _conn
        with _conn() as c:
            c.execute("UPDATE sessions SET description=? WHERE id=?", (desc, sid))
    return {"ok": True}


@app.post("/api/sessions/{name}/prompt")
async def update_prompt(name: str, req: dict):
    scope = req.get("scope", "")
    prompt = req.get("system_prompt", "")
    found = manager.get_by_name(name, scope)
    if not found:
        return JSONResponse({"error": "not found"}, status_code=404)
    sid = found["id"] if isinstance(found, dict) else found.id
    session = manager.sessions.get(sid)
    if session:
        session.system_prompt = prompt
        session._persist()
    else:
        from app.db import _conn
        with _conn() as c:
            c.execute("UPDATE sessions SET system_prompt=? WHERE id=?", (prompt, sid))
    return {"ok": True}


@app.post("/api/sessions/{name}/change-model")
async def change_model(name: str, req: dict):
    scope = req.get("scope", "")
    new_model = req.get("model", "").strip()
    if not new_model:
        return JSONResponse({"error": "model required"}, status_code=400)
    new_model = resolve_model(new_model)
    if new_model not in MODELS:
        return JSONResponse({"error": f"unknown model: {new_model}"}, status_code=400)
    found = manager.get_by_name(name, scope)
    if not found or isinstance(found, dict):
        return JSONResponse({"error": "session not loaded"}, status_code=404)
    result = await found.change_model(new_model)
    if not result.get("ok"):
        return JSONResponse(result, status_code=409)
    return result


@app.post("/api/sessions/{name}/rename")
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
    sid = found["id"] if isinstance(found, dict) else found.id
    session = manager.sessions.get(sid)
    old_branch = None
    new_branch = None
    if session:
        session.name = new_name
        if session.system_prompt:
            session.system_prompt = session.system_prompt.replace(
                f"Worker name: {name}", f"Worker name: {new_name}"
            ).replace(
                f"Orchestrator: {name}", f"Orchestrator: {new_name}"
            )
        if session.branch and session.branch.endswith(f"/{name}"):
            old_branch = session.branch
            new_branch = session.branch[: -len(name)] + new_name
            session.branch = new_branch
        session._persist()
    else:
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
            c.execute(f"UPDATE sessions SET {sets} WHERE id=?", (*updates.values(), sid))
    if old_branch and new_branch:
        wt_path = (session.worktree_path if session else None) or (
            found.get("worktree_path") if isinstance(found, dict) else getattr(found, "worktree_path", None)
        )
        if wt_path and Path(wt_path).is_dir():
            import subprocess
            subprocess.run(
                ["git", "branch", "-m", old_branch, new_branch],
                cwd=wt_path, capture_output=True,
            )
    return {"ok": True, "old_name": name, "new_name": new_name, "branch": new_branch}


@app.delete("/api/sessions/{name}")
async def delete_session(name: str, scope: str):
    found = manager.get_by_name(name, scope)
    if not found:
        return JSONResponse({"error": "not found"}, status_code=404)
    sid = found["id"] if isinstance(found, dict) else found.id
    await manager.remove(sid)
    return {"ok": True}


@app.post("/api/sessions/{name}/merge")
async def merge_session(name: str, req: ScopeRequest):
    from app.workspace import merge_worktree_to_main
    found = manager.get_by_name(name, req.scope)
    if not found:
        return JSONResponse({"error": "not found"}, status_code=404)
    if not isinstance(found, dict):
        if found.status.value == "running":
            return JSONResponse({"error": "worker is running — wait for idle before merge"}, status_code=400)
    worktree_path = found.get("worktree_path") if isinstance(found, dict) else found.worktree_path
    scope = found.get("scope") if isinstance(found, dict) else found.scope
    session_id = found.get("id") if isinstance(found, dict) else found.id
    if not worktree_path:
        return JSONResponse({"error": "session has no worktree"}, status_code=400)
    if not scope:
        return JSONResponse({"error": "session has no scope"}, status_code=400)
    async with manager.get_session_lock(session_id):
        try:
            result = merge_worktree_to_main(worktree_path, scope)
            if result.get("ok"):
                link_results = {}
                for task_ref, commits in result.pop("merged_commits", {}).items():
                    try:
                        link_results[task_ref] = _tm.link_commits_to_task(task_ref, commits)
                    except Exception as link_err:
                        import logging
                        logging.getLogger(__name__).error("Failed to link commits to %s: %s", task_ref, link_err)
                        link_results[task_ref] = {"ok": False, "error": str(link_err)}
                if link_results:
                    result["linked_tasks"] = link_results
            return result
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/api/sessions/{name}/switch-branch")
async def switch_branch(name: str, req: dict):
    from app.workspace import switch_worktree_branch, _normalize_task_id
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
    if not isinstance(found, dict):
        if found.status.value == "running":
            return JSONResponse({"error": "worker is running — wait for idle"}, status_code=400)
    worktree_path = found.get("worktree_path") if isinstance(found, dict) else found.worktree_path
    session_id = found.get("id") if isinstance(found, dict) else found.id
    if not worktree_path:
        return JSONResponse({"error": "session has no worktree"}, status_code=400)
    new_branch = f"task-{par}/{name}"
    async with manager.get_session_lock(session_id):
        try:
            result = switch_worktree_branch(worktree_path, new_branch)
            if not isinstance(found, dict):
                if result.get("ok") or result.get("branch"):
                    found.branch = result.get("branch", new_branch)
                    found.task_id = par
                    found._persist()
            try:
                _tm.api_update_task(par, status="in_progress")
            except Exception:
                pass
            return result
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/api/sessions/{name}/progress")
async def update_progress(name: str, req: dict):
    scope = req.get("scope", "")
    pct = max(0, min(100, int(req.get("percent", 0))))
    status_text = str(req.get("status", ""))
    session = manager.get_by_name(name, scope)
    if not session or isinstance(session, dict):
        session = next((s for s in manager.sessions.values() if s.name == name), None)
    if not session or isinstance(session, dict):
        return JSONResponse({"error": "not found"}, status_code=404)
    session.progress_pct = pct
    session.progress_status = status_text
    session._persist()
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


_USAGE_CACHE_FILE = Path(__file__).parent.parent / "data" / "usage_cache.json"
_usage_cache: dict = {"data": None, "ts": 0.0, "token": None}
_USAGE_CACHE_TTL = 300
_CREDENTIALS_PATH = Path.home() / ".claude" / ".credentials.json"


def _load_usage_cache():
    if _USAGE_CACHE_FILE.exists():
        try:
            import json
            cached = json.loads(_USAGE_CACHE_FILE.read_text())
            _usage_cache["data"] = cached.get("data")
            _usage_cache["ts"] = cached.get("ts", 0.0)
        except Exception:
            pass


def _save_usage_cache():
    try:
        import json
        _USAGE_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _USAGE_CACHE_FILE.write_text(json.dumps({"data": _usage_cache["data"], "ts": _usage_cache["ts"]}))
    except Exception:
        pass


_load_usage_cache()


def _read_oauth_credentials() -> tuple[str | None, str | None, str | None]:
    """Read accessToken, refreshToken, and rateLimitTier from credentials file."""
    try:
        creds = json.loads(_CREDENTIALS_PATH.read_text())
        oauth = creds.get("claudeAiOauth", {})
        return oauth.get("accessToken"), oauth.get("refreshToken"), oauth.get("rateLimitTier")
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        return None, None, None


async def _fetch_anthropic_usage(token: str) -> dict:
    """Call Anthropic OAuth usage API. Raises PermissionError on 401, RuntimeError on 429."""
    import httpx
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            "https://api.anthropic.com/api/oauth/usage",
            headers={
                "Authorization": f"Bearer {token}",
                "anthropic-beta": "oauth-2025-04-20",
                "Accept": "application/json",
            },
        )
        if resp.status_code == 401:
            raise PermissionError("token_expired")
        if resp.status_code == 429:
            raise RuntimeError("rate_limited")
        resp.raise_for_status()
        return resp.json()


async def _refresh_oauth_token(refresh_token: str) -> str | None:
    """Refresh expired OAuth token. Returns new access token or None."""
    import httpx
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                "https://platform.claude.com/v1/oauth/token",
                json={"grant_type": "refresh_token", "refresh_token": refresh_token},
                headers={"Content-Type": "application/json", "Accept": "application/json"},
            )
            if resp.status_code == 200:
                return resp.json().get("access_token")
    except Exception:
        pass
    return None


def _get_agents_cost() -> dict:
    """Get per-agent cost breakdown from DB."""
    from app.db import _conn
    with _conn() as c:
        rows = c.execute(
            "SELECT name, model, cost_usd FROM sessions ORDER BY cost_usd DESC"
        ).fetchall()
        total = sum(r["cost_usd"] for r in rows)
        agents = [
            {"name": r["name"], "cost_usd": round(r["cost_usd"], 4), "model": r["model"]}
            for r in rows if r["cost_usd"] > 0
        ]
        return {
            "total_cost_usd": round(total, 4),
            "agents_count": len(agents),
            "agents": agents,
        }


@app.get("/api/usage")
async def get_usage():
    now = time.time()

    if _usage_cache["data"] and (now - _usage_cache["ts"]) < _USAGE_CACHE_TTL:
        anthropic_data = _usage_cache["data"]
    else:
        token, refresh_token, _tier = _read_oauth_credentials()
        if not token:
            return JSONResponse({"error": "no OAuth credentials found"}, status_code=500)

        try:
            anthropic_data = await _fetch_anthropic_usage(token)
        except PermissionError:
            if refresh_token:
                new_token = await _refresh_oauth_token(refresh_token)
                if new_token:
                    try:
                        anthropic_data = await _fetch_anthropic_usage(new_token)
                        _usage_cache["token"] = new_token
                    except Exception as e:
                        return JSONResponse({"error": f"refresh succeeded but usage fetch failed: {e}"}, status_code=500)
                else:
                    return JSONResponse({"error": "token expired, refresh failed"}, status_code=500)
            else:
                return JSONResponse({"error": "token expired, no refresh token"}, status_code=500)
        except RuntimeError:
            if _usage_cache["data"]:
                anthropic_data = _usage_cache["data"]
            else:
                return JSONResponse({"error": "rate limited by Anthropic, no cached data"}, status_code=429)
        except Exception as e:
            if _usage_cache["data"]:
                anthropic_data = _usage_cache["data"]
            else:
                return JSONResponse({"error": str(e)}, status_code=500)

        _usage_cache["data"] = anthropic_data
        _usage_cache["ts"] = now
        _save_usage_cache()

    return {
        "anthropic": anthropic_data,
        "orchestra": _get_agents_cost(),
    }


@app.get("/api/orchestrators")
async def list_orchestrators():
    from app.db import get_all_sessions
    active = [s.to_dict() for s in manager.sessions.values() if s.is_orchestrator]
    active_ids = {s["id"] for s in active}
    db_orchs = [s for s in get_all_sessions() if s.get("is_orchestrator") and s["id"] not in active_ids]
    result = active + db_orchs
    running_scopes = {s.scope for s in manager.sessions.values() if s.status.value == "running"}
    for o in result:
        o["any_running"] = o.get("scope", "") in running_scopes
    return result


@app.delete("/api/orchestrators/{name}")
async def delete_orchestrator(name: str, scope: str):
    await manager.remove_scope(scope)
    return {"ok": True}


@app.get("/api/models")
async def list_models():
    return [{"id": k, "name": v} for k, v in MODELS.items()]


UPLOADS_DIR = Path(__file__).parent.parent / "data" / "uploads"
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)


_BLOCKED_UPLOAD_EXTS = {".exe", ".sh", ".bat", ".cmd", ".ps1", ".py", ".js", ".php", ".rb", ".pl"}

@app.post("/api/upload")
async def upload_file(file: UploadFile):
    import hashlib
    ext = Path(file.filename or "image.png").suffix or ".png"
    if ext.lower() in _BLOCKED_UPLOAD_EXTS:
        return JSONResponse({"error": f"file type {ext} not allowed"}, status_code=400)
    content = await file.read()
    if len(content) > 10 * 1024 * 1024:
        return JSONResponse({"error": "file too large (max 10MB)"}, status_code=400)
    h = hashlib.md5(content).hexdigest()[:12]
    name = f"{h}{ext}"
    path = UPLOADS_DIR / name
    if not path.exists():
        path.write_bytes(content)
    return {"path": str(path), "url": f"/uploads/{name}"}


app.mount("/uploads", StaticFiles(directory=str(UPLOADS_DIR)), name="uploads")


_git_status_cache: dict = {}  # scope -> {ts, data}
_GIT_STATUS_TTL = 10


async def _run_git(cmd: list[str], cwd: str) -> str:
    proc = await asyncio.create_subprocess_exec(
        *cmd, cwd=cwd,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
        return stdout.decode().strip()
    except asyncio.TimeoutError:
        proc.kill()
        return ""


@app.get("/api/git-status")
async def get_git_status(scope: str):
    now = time.time()
    cached = _git_status_cache.get(scope)
    if cached and (now - cached["ts"]) < _GIT_STATUS_TTL:
        return cached["data"]

    sessions = manager.list_sessions(scope)
    result = []
    for s in sessions:
        wt = s.get("worktree_path") if isinstance(s, dict) else getattr(s, "worktree_path", None)
        if not wt or not Path(wt).is_dir():
            continue
        name = s.get("name") if isinstance(s, dict) else s.name
        branch = s.get("branch") if isinstance(s, dict) else getattr(s, "branch", None)

        ahead_str, dirty_str, last_commit = await asyncio.gather(
            _run_git(["git", "rev-list", "main..HEAD", "--count"], wt),
            _run_git(["git", "status", "--porcelain"], wt),
            _run_git(["git", "log", "-1", "--format=%s"], wt),
        )

        commits_ahead = int(ahead_str) if ahead_str.isdigit() else 0
        dirty_files = len([l for l in dirty_str.splitlines() if l.strip()])
        last_commit = last_commit[:50] if last_commit else ""

        result.append({
            "name": name,
            "branch": branch or "",
            "commits_ahead": commits_ahead,
            "dirty_files": dirty_files,
            "last_commit": last_commit,
        })

    _git_status_cache[scope] = {"ts": now, "data": result}
    return result


@app.post("/api/tg/send_file")
async def tg_send_file(req: dict):
    path = req.get("path", "")
    caption = req.get("caption", "")
    scope = req.get("scope", "")
    sender = req.get("sender", "")
    as_document = req.get("as_document", False)
    if not path:
        return JSONResponse({"error": "path required"}, status_code=400)
    if not _is_safe_path(path):
        return JSONResponse({"error": "access denied"}, status_code=403)
    from app.tg_bridge import send_file_to_tg
    result = await send_file_to_tg(path, caption, scope, sender, as_document=as_document)
    if result.get("error"):
        return JSONResponse(result, status_code=500)
    return result


@app.post("/api/restart")
async def restart_server():
    import subprocess
    result = subprocess.run(
        ["sudo", "-n", "systemctl", "restart", "orchestra"],
        capture_output=True, text=True, timeout=10,
    )
    if result.returncode != 0:
        return JSONResponse({"error": result.stderr.strip()}, status_code=500)
    return {"ok": True}


# --- Task Manager API ---

from app import tm as _tm


class TmTaskCreate(BaseModel):
    title: str
    project: str
    price: int = 0
    description: str = ""
    assignee: str = ""
    status: str = "new"
    scope: str = ""
    priority: int = 2


class TmTaskUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    price: int | None = None
    status: str | None = None
    assignee: str | None = None
    priority: int | None = None


class TmPaymentReceive(BaseModel):
    amount: int
    client: str = "aleksandr-kislinskiy"
    date: str = ""
    note: str = ""


@app.post("/api/tm/tasks")
async def tm_create_task(req: TmTaskCreate):
    try:
        return _tm.api_create_task(
            req.project, req.title, req.price, req.description, req.assignee, req.status,
            scope=req.scope, priority=req.priority,
        )
    except (ValueError, RuntimeError) as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@app.get("/api/tm/tasks")
async def tm_list_tasks(project: str = "", status: str = "", assignee: str = "",
                        scope: str = ""):
    proj = project
    if not proj and scope:
        with _tm._conn() as conn:
            p = _tm.get_project_by_scope(conn, scope)
            if p:
                proj = p["id"]
            else:
                return {"tasks": [], "count": 0, "total_debt": "0"}
    return _tm.api_list_tasks(proj, status, assignee)


@app.get("/api/tm/tasks/{par}")
async def tm_get_task(par: str, scope: str = ""):
    try:
        project = ""
        if scope:
            with _tm._conn() as conn:
                p = _tm.get_project_by_scope(conn, scope)
                if p:
                    project = p["id"]
        return _tm.api_get_task(par, project=project)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=404)


@app.put("/api/tm/tasks/{par}")
async def tm_update_task(par: str, req: TmTaskUpdate, scope: str = ""):
    try:
        project = ""
        if scope:
            with _tm._conn() as conn:
                p = _tm.get_project_by_scope(conn, scope)
                if p:
                    project = p["id"]
        return _tm.api_update_task(
            par, req.title, req.description, req.price, req.status, req.assignee,
            project=project, priority=req.priority,
        )
    except (ValueError, RuntimeError) as e:
        code = 404 if "not found" in str(e).lower() else 400
        return JSONResponse({"error": str(e)}, status_code=code)


@app.post("/api/tm/payments")
async def tm_receive_payment(req: TmPaymentReceive):
    try:
        return _tm.api_receive_payment(req.amount, req.client, req.date, req.note)
    except (ValueError, RuntimeError) as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@app.get("/api/tm/payments/status")
async def tm_payment_status(client: str = "aleksandr-kislinskiy"):
    try:
        return _tm.api_payment_status(client)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=404)


@app.get("/api/tm/payments/history")
async def tm_payment_history(client: str = "aleksandr-kislinskiy"):
    with _tm._conn() as conn:
        rows = conn.execute(
            "SELECT * FROM tm_payments WHERE client_id = ? ORDER BY id DESC LIMIT 50",
            (client,),
        ).fetchall()
    return {
        "payments": [
            {"id": r["id"], "amount_rub": r["amount_rub"], "date": r["date"],
             "note": r["note"], "created_at": r["created_at"]}
            for r in rows
        ]
    }


@app.get("/api/tm/sync/log")
async def tm_sync_log(limit: int = 50):
    limit = min(limit, 200)
    with _tm._conn() as conn:
        rows = conn.execute(
            "SELECT * FROM tm_sync_log ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return {"entries": [dict(r) for r in rows]}


@app.post("/api/tm/sync/retry/{sync_id}")
async def tm_sync_retry(sync_id: int):
    with _tm._conn() as conn:
        row = conn.execute("SELECT * FROM tm_sync_log WHERE id = ?", (sync_id,)).fetchone()
        if not row:
            return JSONResponse({"error": "sync entry not found"}, status_code=404)
        entry = dict(row)
        if entry["status"] not in ("error", "pending"):
            return {"message": "nothing to retry", "status": entry["status"]}
        task_id = entry["task_id"]

    if task_id:
        from app.tm_yougile import yougile_sync_task
        result = await yougile_sync_task(task_id)
        return {"retried": True, "task_id": task_id, "result": result}
    return {"error": "no task_id on sync entry"}


# ── Background Jobs API ──

class BgJobCreateRequest(BaseModel):
    type: str
    config: dict = {}
    message: str = ""
    target_name: str = ""
    target_scope: str = ""
    timeout_seconds: int = 3600
    created_by: str = ""

@app.post("/api/bg/jobs")
async def bg_job_create(req: BgJobCreateRequest):
    from app.bg_jobs import bg_manager
    scope = req.target_scope.rstrip("/")
    name = req.target_name
    if not scope or not name:
        return JSONResponse({"error": "target_name and target_scope required"}, status_code=400)
    session = manager.get_by_name(name, scope)
    if not session:
        return JSONResponse({"error": f"session '{name}' not found in scope"}, status_code=404)
    session_id = session.id if hasattr(session, "id") else session.get("id")
    result = await bg_manager.create(
        job_type=req.type, config=req.config, message=req.message,
        target_session_id=session_id, target_name=name, target_scope=scope,
        created_by=req.created_by, timeout_seconds=req.timeout_seconds,
    )
    if result.get("error"):
        return JSONResponse(result, status_code=400)
    return result


@app.get("/api/bg/jobs")
async def bg_job_list(scope: str = "", session_id: str = ""):
    from app.db import bg_get_jobs
    return bg_get_jobs(scope=scope or None, session_id=session_id or None)


@app.delete("/api/bg/jobs/{job_id}")
async def bg_job_cancel(job_id: str):
    from app.bg_jobs import bg_manager
    result = await bg_manager.cancel(job_id)
    if result.get("error"):
        return JSONResponse(result, status_code=404)
    return result


# ── GitHub Webhook (CI failure routing) ──

logger = logging.getLogger("orchestra.webhook")

_FAILURE_CONCLUSIONS = {"failure", "timed_out", "startup_failure"}

REPO_TO_SCOPE = {
    "DrSeedon/parsing-hub": "/mnt/data/Projects/Python/Parsing",
    "DrSeedon/seo-platform": "/mnt/data/Projects/Python/Parsing",
    "DrSeedon/ai-assistants": "/mnt/data/Projects/Python/Parsing",
    "DrSeedon/zahoron-mobile": "/mnt/data/Projects/Python/Parsing",
    "DrSeedon/family-tree": "/mnt/data/Projects/Python/Parsing",
}


def _verify_github_signature(payload: bytes, signature: str, secret: str) -> bool:
    expected = "sha256=" + hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


async def _fetch_failed_log(owner: str, repo: str, run_id: int, token: str) -> str:
    import httpx
    headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github+json"}
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            f"https://api.github.com/repos/{owner}/{repo}/actions/runs/{run_id}/jobs",
            headers=headers,
        )
        if resp.status_code != 200:
            return f"(failed to fetch jobs: HTTP {resp.status_code})"
        jobs = resp.json().get("jobs", [])
        failed_job = next((j for j in jobs if j.get("conclusion") in _FAILURE_CONCLUSIONS), None)
        if not failed_job:
            return "(no failed job found)"
        job_id = failed_job["id"]
        log_resp = await client.get(
            f"https://api.github.com/repos/{owner}/{repo}/actions/jobs/{job_id}/logs",
            headers=headers,
            follow_redirects=True,
        )
        if log_resp.status_code != 200:
            return f"(failed to fetch log: HTTP {log_resp.status_code})"
        lines = log_resp.text.splitlines()
        return "\n".join(lines[-50:])


@app.post("/api/webhook/github")
async def github_webhook(request: Request):
    secret = os.getenv("GITHUB_WEBHOOK_SECRET", "")
    if not secret:
        return JSONResponse({"error": "webhook not configured"}, status_code=500)

    body = await request.body()
    signature = request.headers.get("X-Hub-Signature-256", "")
    if not signature or not _verify_github_signature(body, signature, secret):
        return JSONResponse({"error": "invalid signature"}, status_code=403)

    event = request.headers.get("X-GitHub-Event", "")
    if event != "workflow_run":
        return {"ok": True, "skipped": event}

    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return JSONResponse({"error": "invalid JSON"}, status_code=400)

    action = payload.get("action")
    workflow_run = payload.get("workflow_run") or {}
    conclusion = workflow_run.get("conclusion")

    if action != "completed" or conclusion not in _FAILURE_CONCLUSIONS:
        return {"ok": True, "skipped": f"{action}/{conclusion}"}

    repository = payload.get("repository") or {}
    repo_full = repository.get("full_name", "")
    scope = REPO_TO_SCOPE.get(repo_full)
    if not scope:
        logger.warning(f"No scope mapping for repo: {repo_full}")
        return {"ok": True, "skipped": f"unmapped repo {repo_full}"}

    workflow_name = workflow_run.get("name", "unknown")
    run_id = workflow_run.get("id")
    run_url = workflow_run.get("html_url", "")
    head_commit = workflow_run.get("head_commit") or {}
    commit_sha = str(head_commit.get("id", ""))[:7]
    commit_msg = str(head_commit.get("message", "")).split("\n")[0]

    token = os.getenv("GITHUB_TOKEN", "")
    error_log = ""
    if token and run_id:
        owner, repo = repo_full.split("/", 1)
        try:
            error_log = await _fetch_failed_log(owner, repo, run_id, token)
        except Exception as e:
            error_log = f"(log fetch error: {e})"

    message = (
        f"🔴 CI FAIL: {repo_full}\n"
        f"Workflow: {workflow_name}, Run #{run_id}\n"
        f"Commit: {commit_sha} \"{commit_msg}\"\n"
    )
    if error_log:
        message += f"Error:\n{error_log}\n"
    message += f"URL: {run_url}"

    orch_name = manager._find_orchestrator_name(scope)
    if not orch_name:
        logger.warning(f"No orchestrator for scope: {scope}")
        return JSONResponse({"error": f"no orchestrator for scope {scope}"}, status_code=404)

    session = await manager.ensure_loaded(orch_name, scope)
    if not session:
        return JSONResponse({"error": f"orchestrator {orch_name} not loadable"}, status_code=404)

    try:
        await manager.send(session.id, message)
        logger.info(f"CI failure routed to {orch_name}: {repo_full} run #{run_id}")
        return {"ok": True, "routed_to": orch_name}
    except Exception as e:
        logger.error(f"Failed to send CI failure to {orch_name}: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)
