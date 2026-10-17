# Candidate cand-11

## ORIGIN commit bc3a51e597 (2026-06-02): #47: refactor — prompting.py, BackendLike, extract-methods, main.py split
(diff of code only, excluding .orchestra/ and *.md; capped 1200 lines)

diff --git a/app/backend_protocol.py b/app/backend_protocol.py
new file mode 100644
index 000000000..a2296f6fb
--- /dev/null
+++ b/app/backend_protocol.py
@@ -0,0 +1,15 @@
+"""Backend protocol — structural typing contract for agent backends."""
+
+from typing import AsyncIterator, Optional, Protocol
+
+from app.events import AgentEvent
+
+
+class BackendLike(Protocol):
+    @property
+    def session_id(self) -> Optional[str]: ...
+    async def connect(self) -> None: ...
+    async def send(self, message: str) -> None: ...
+    async def events(self) -> AsyncIterator[AgentEvent]: ...
+    async def interrupt(self) -> None: ...
+    async def disconnect(self) -> None: ...
diff --git a/app/deps.py b/app/deps.py
new file mode 100644
index 000000000..c9e629102
--- /dev/null
+++ b/app/deps.py
@@ -0,0 +1,5 @@
+"""Shared dependencies for routers — avoids importing from main."""
+
+from app.manager import SessionManager
+
+manager = SessionManager()
diff --git a/app/main.py b/app/main.py
index f721aa3af..ff7b00a4c 100644
--- a/app/main.py
+++ b/app/main.py
@@ -17,21 +17,19 @@ from fastapi import FastAPI, Request, UploadFile, Form
 from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
 from starlette.responses import StreamingResponse
 from starlette.middleware.base import BaseHTTPMiddleware
 from fastapi.staticfiles import StaticFiles
 from fastapi.templating import Jinja2Templates
 from pydantic import BaseModel, field_validator, model_validator
 
 from app.db import init_db, get_logs, get_logs_before
-from app.manager import SessionManager
+from app.deps import manager
 from app.models import resolve_model, MODELS
 from app.session import AgentStatus
-
-manager = SessionManager()
 templates = Jinja2Templates(directory="app/templates")
 
 
 @asynccontextmanager
 async def lifespan(app: FastAPI):
     from dotenv import load_dotenv
     load_dotenv()
     init_db()
@@ -51,16 +49,23 @@ async def lifespan(app: FastAPI):
     await stop_bridge()
     await bg_manager.shutdown()
     await manager.shutdown_all()
 
 
 app = FastAPI(title="Orchestra", lifespan=lifespan)
 app.mount("/static", StaticFiles(directory="app/static"), name="static")
 
+from app.routes.tm import router as tm_router
+from app.routes.bg import router as bg_router
+from app.routes.proxy import router as proxy_router
+app.include_router(tm_router)
+app.include_router(bg_router)
+app.include_router(proxy_router)
+
 
 from app.auth import is_auth_enabled, validate_session, requires_auth, check_internal_token
 
 
 @app.exception_handler(Exception)
 async def global_exception_handler(request: Request, exc: Exception):
     import traceback
     tb = traceback.format_exc()
@@ -370,17 +375,17 @@ async def list_files(path: str):
             })
     except PermissionError:
         pass
     return items
 
 
 @app.get("/api/role-icons")
 async def role_icons():
-    from app.manager import get_role_icons
+    from app.prompting import get_role_icons
     return get_role_icons()
 
 
 @app.get("/api/sessions")
 async def list_sessions(scope: Optional[str] = None):
     return manager.list_sessions(scope)
 
 
@@ -429,17 +434,17 @@ async def get_session(name: str, scope: str):
         return JSONResponse({"error": "not found"}, status_code=404)
     if isinstance(found, dict):
         return found
     return found.to_dict()
 
 
 @app.get("/api/sessions/{name}/prompt")
 async def get_session_prompt(name: str, scope: str):
-    from app.manager import _read_prompt
+    from app.prompting import read_prompt as _read_prompt
     found = manager.get_by_name(name, scope)
     if not found:
         return JSONResponse({"error": "not found"}, status_code=404)
     sp = (found.get("system_prompt", "") if isinstance(found, dict) else found.system_prompt) or ""
     is_orch = (found.get("is_orchestrator") if isinstance(found, dict) else found.is_orchestrator) or False
     base = _read_prompt("base.md")
     base_len = len(base)
     role = ""
@@ -1091,17 +1096,17 @@ async def report_bug_endpoint(req: Request):
     except Exception as e:
         return JSONResponse({"error": str(e)}, status_code=500)
     return {"result": f"Bug reported: {title}"}
 
 
 @app.get("/api/orchestrators")
 async def list_orchestrators():
     from app.db import get_all_sessions
-    from app.session import is_orchestrator_role
+    from app.prompting import is_orchestrator_role
     active = [s.to_dict() for s in manager.sessions.values() if s.is_orchestrator]
     active_ids = {s["id"] for s in active}
     db_orchs = [s for s in get_all_sessions() if is_orchestrator_role(s.get("role", "worker")) and s["id"] not in active_ids]
     result = active + db_orchs
     running_scopes = {s.scope for s in manager.sessions.values() if s.status.value == "running"}
     waiting_scopes = {s.scope for s in manager.sessions.values() if s.status.value == "waiting"}
     for o in result:
         o["any_running"] = o.get("scope", "") in running_scopes
@@ -1275,230 +1280,19 @@ async def restart_server():
         ["sudo", "-n", "systemctl", "restart", "orchestra"],
         capture_output=True, text=True, timeout=10,
     )
     if result.returncode != 0:
         return JSONResponse({"error": result.stderr.strip()}, status_code=500)
     return {"ok": True}
 
 
-# --- Task Manager API ---
-
 from app import tm as _tm
 
 
-class TmTaskCreate(BaseModel):
-    title: str
-    project: str
-    price: int = 0
-    description: str = ""
-    assignee: str = ""
-    status: str = "new"
-    scope: str = ""
-    priority: int = 2
-
-
-class TmTaskUpdate(BaseModel):
-    title: str | None = None
-    description: str | None = None
-    price: int | None = None
-    status: str | None = None
-    assignee: str | None = None
-    priority: int | None = None
-
-
-class TmPaymentReceive(BaseModel):
-    amount: int
-    client: str = ""
-    scope: str = ""
-    date: str = ""
-    note: str = ""
-
-
-@app.post("/api/tm/tasks")
-async def tm_create_task(req: TmTaskCreate):
-    try:
-        return _tm.api_create_task(
-            req.project, req.title, req.price, req.description, req.assignee, req.status,
-            scope=req.scope, priority=req.priority,
-        )
-    except (ValueError, RuntimeError) as e:
-        return JSONResponse({"error": str(e)}, status_code=400)
-
-
-@app.get("/api/tm/tasks")
-async def tm_list_tasks(project: str = "", status: str = "", assignee: str = "",
-                        scope: str = ""):
-    proj = project
-    if not proj and scope:
-        with _tm._conn() as conn:
-            p = _tm.get_project_by_scope(conn, scope)
-            if p:
-                proj = p["id"]
-            else:
-                return {"tasks": [], "count": 0, "total_debt": "0"}
-    return _tm.api_list_tasks(proj, status, assignee)
-
-
-@app.get("/api/tm/tasks/{par}")
-async def tm_get_task(par: str, scope: str = ""):
-    try:
-        project = ""
-        if scope:
-            with _tm._conn() as conn:
-                p = _tm.get_project_by_scope(conn, scope)
-                if p:
-                    project = p["id"]
-        return _tm.api_get_task(par, project=project)
-    except ValueError as e:
-        return JSONResponse({"error": str(e)}, status_code=404)
-
-
-@app.put("/api/tm/tasks/{par}")
-async def tm_update_task(par: str, req: TmTaskUpdate, scope: str = ""):
-    try:
-        project = ""
-        if scope:
-            with _tm._conn() as conn:
-                p = _tm.get_project_by_scope(conn, scope)
-                if p:
-                    project = p["id"]
-        return _tm.api_update_task(
-            par, req.title, req.description, req.price, req.status, req.assignee,
-            project=project, priority=req.priority,
-        )
-    except (ValueError, RuntimeError) as e:
-        code = 404 if "not found" in str(e).lower() else 400
-        return JSONResponse({"error": str(e)}, status_code=code)
-
-
-def _resolve_client_id(client: str, scope: str) -> str:
-    if client:
-        return client
-    if scope:
-        with _tm._conn() as conn:
-            proj = _tm.get_project_by_scope(conn, scope)
-            if proj:
-                cl = _tm.get_client_for_project(conn, proj["id"])
-                if cl:
-                    return cl["id"]
-    raise ValueError("No client specified and no client found for project scope")
-
-
-@app.post("/api/tm/payments")
-async def tm_receive_payment(req: TmPaymentReceive):
-    try:
-        client_id = _resolve_client_id(req.client, req.scope)
-        return _tm.api_receive_payment(req.amount, client_id, req.date, req.note)
-    except (ValueError, RuntimeError) as e:
-        return JSONResponse({"error": str(e)}, status_code=400)
-
-
-@app.get("/api/tm/payments/status")
-async def tm_payment_status(client: str = "", scope: str = ""):
-    try:
-        client_id = _resolve_client_id(client, scope)
-        return _tm.api_payment_status(client_id)
-    except ValueError as e:
-        return JSONResponse({"error": str(e)}, status_code=404)
-
-
-@app.get("/api/tm/payments/history")
-async def tm_payment_history(client: str = "", scope: str = ""):
-    try:
-        client_id = _resolve_client_id(client, scope)
-    except ValueError as e:
-        return JSONResponse({"error": str(e)}, status_code=400)
-    with _tm._conn() as conn:
-        rows = conn.execute(
-            "SELECT * FROM tm_payments WHERE client_id = ? ORDER BY id DESC LIMIT 50",
-            (client_id,),
-        ).fetchall()
-    return {
-        "payments": [
-            {"id": r["id"], "amount_rub": r["amount_rub"], "date": r["date"],
-             "note": r["note"], "created_at": r["created_at"]}
-            for r in rows
-        ]
-    }
-
-
-@app.get("/api/tm/sync/log")
-async def tm_sync_log(limit: int = 50):
-    limit = min(limit, 200)
-    with _tm._conn() as conn:
-        rows = conn.execute(
-            "SELECT * FROM tm_sync_log ORDER BY id DESC LIMIT ?", (limit,)
-        ).fetchall()
-    return {"entries": [dict(r) for r in rows]}
-
-
-@app.post("/api/tm/sync/retry/{sync_id}")
-async def tm_sync_retry(sync_id: int):
-    with _tm._conn() as conn:
-        row = conn.execute("SELECT * FROM tm_sync_log WHERE id = ?", (sync_id,)).fetchone()
-        if not row:
-            return JSONResponse({"error": "sync entry not found"}, status_code=404)
-        entry = dict(row)
-        if entry["status"] not in ("error", "pending"):
-            return {"message": "nothing to retry", "status": entry["status"]}
-        task_id = entry["task_id"]
-
-    if task_id:
-        from app.tm_yougile import yougile_sync_task
-        result = await yougile_sync_task(task_id)
-        return {"retried": True, "task_id": task_id, "result": result}
-    return {"error": "no task_id on sync entry"}
-
-
-# ── Background Jobs API ──
-
-class BgJobCreateRequest(BaseModel):
-    type: str
-    config: dict = {}
-    message: str = ""
-    target_name: str = ""
-    target_scope: str = ""
-    timeout_seconds: int = 3600
-    created_by: str = ""
-
-@app.post("/api/bg/jobs")
-async def bg_job_create(req: BgJobCreateRequest):
-    from app.bg_jobs import bg_manager
-    scope = req.target_scope.rstrip("/")
-    name = req.target_name
-    if not scope or not name:
-        return JSONResponse({"error": "target_name and target_scope required"}, status_code=400)
-    session = manager.get_by_name(name, scope)
-    if not session:
-        return JSONResponse({"error": f"session '{name}' not found in scope"}, status_code=404)
-    session_id = session.id if hasattr(session, "id") else session.get("id")
-    result = await bg_manager.create(
-        job_type=req.type, config=req.config, message=req.message,
-        target_session_id=session_id, target_name=name, target_scope=scope,
-        created_by=req.created_by, timeout_seconds=req.timeout_seconds,
-    )
-    if result.get("error"):
-        return JSONResponse(result, status_code=400)
-    return result
-
-
-@app.get("/api/bg/jobs")
-async def bg_job_list(scope: str = "", session_id: str = ""):
-    from app.db import bg_get_jobs
-    return bg_get_jobs(scope=scope or None, session_id=session_id or None)
-
-
-@app.delete("/api/bg/jobs/{job_id}")
-async def bg_job_cancel(job_id: str):
-    from app.bg_jobs import bg_manager
-    result = await bg_manager.cancel(job_id)
-    if result.get("error"):
-        return JSONResponse(result, status_code=404)
-    return result
 
 
 # ── GitHub Webhook (CI failure routing) ──
 
 logger = logging.getLogger("orchestra.webhook")
 
 _FAILURE_CONCLUSIONS = {"failure", "timed_out", "startup_failure"}
 
@@ -1622,34 +1416,8 @@ async def github_webhook(request: Request):
         return {"ok": True, "routed_to": orch_name}
     except Exception as e:
         logger.error(f"Failed to send CI failure to {orch_name}: {e}")
         return JSONResponse({"error": str(e)}, status_code=500)
 
 
 # ── Proxy Manager ──
 
-from app.proxy_manager import proxy_manager
-
-@app.get("/api/proxy/list")
-async def proxy_list():
-    return await proxy_manager.list_proxies()
-
-@app.post("/api/proxy/check/{proxy_id}")
-async def proxy_check(proxy_id: str):
-    result = await proxy_manager.check_proxy(proxy_id)
-    if result.get("error"):
-        return JSONResponse(result, status_code=400)
-    return result
-
-@app.post("/api/proxy/select/{proxy_id}")
-async def proxy_select(proxy_id: str):
-    result = await proxy_manager.select_proxy(proxy_id)
-    if result.get("error"):
-        return JSONResponse(result, status_code=400)
-    return result
-
-
-from app.ssh_tunnel import tunnel_status
-
-@app.get("/api/tunnel/status")
-async def api_tunnel_status():
-    return tunnel_status()
diff --git a/app/manager.py b/app/manager.py
index fd929ce10..63bc1a712 100644
--- a/app/manager.py
+++ b/app/manager.py
@@ -6,17 +6,22 @@ import os
 import re
 import subprocess
 import sys
 import uuid
 from datetime import datetime, timezone
 from pathlib import Path
 from typing import Optional
 
-from app.session import AgentSession, AgentStatus, is_orchestrator_role
+from app.session import AgentSession, AgentStatus
+from app.prompting import (
+    is_orchestrator_role, safe_format_prompt, read_prompt,
+    role_prompt_file, role_can_spawn,
+    roles_catalog, skills_catalog, prompt_template_hash, inject_skills_to_worktree,
+)
 
 _TASK_BRANCH_RE = re.compile(r"^(?:task-|[A-Z]{2,5}-)(\d+)/")
 from app.workspace import create_worktree, remove_worktree, parse_owned_dirs, dirs_overlap
 from app.models import resolve_model, backend_for_model
 from app.db import (
     save_session, get_session_by_name, get_all_sessions,
     delete_session, archive_session, get_stats,
 )
@@ -31,29 +36,16 @@ for _k in ("HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY", "INTERNAL_TOKEN"):
     if os.environ.get(_k):
         MCP_BASE_ENV[_k] = os.environ[_k]
 
 COLOR_PALETTE = [
     "#818cf8", "#34d399", "#f97316", "#38bdf8", "#f472b6",
     "#a78bfa", "#fbbf24", "#2dd4bf", "#fb7185", "#4ade80",
 ]
 
-_PROMPTS_DIR = Path(__file__).parent / "prompts"
-
-_IDENTITY_PLACEHOLDERS = re.compile(r"\{(worker_name|orchestrator_name|scope|branch)\}")
-
-
-def _safe_format_prompt(template: str, **kwargs: str) -> str:
-    """Substitute only known identity placeholders, leaving other {braces} intact."""
-    return _IDENTITY_PLACEHOLDERS.sub(lambda m: kwargs.get(m.group(1), m.group(0)), template)
-
-
-def _read_prompt(name: str) -> str:
-    p = _PROMPTS_DIR / name
-    return p.read_text() if p.exists() else ""
 
 
 def _other_orchestrators_block(exclude_scope: str = "") -> str:
     try:
         orchs = [s for s in get_all_sessions()
                  if is_orchestrator_role(s.get("role", "worker")) and s.get("scope") != exclude_scope]
         if not orchs:
             return ""
@@ -88,159 +80,23 @@ def _workers_block(scope: str) -> str:
             desc = w.get("description", "")
             desc_part = f" | \"{desc}\"" if desc else ""
             lines.append(f"- **{name}** — {model} | {status} | ctx:{ctx}%{desc_part}")
         return "\n".join(lines)
     except Exception:
         return ""
 
 
-def _parse_role_frontmatter(text: str) -> tuple[dict, str]:
-    """Parse YAML frontmatter from role .md file. Returns (meta, body)."""
-    if not text.startswith("---"):
-        return {}, text
-    parts = text.split("---", 2)
-    if len(parts) < 3:
-        return {}, text
-    try:
-        import yaml
-        meta = yaml.safe_load(parts[1]) or {}
-    except Exception:
-        meta = {}
-    body = parts[2].strip()
-    return meta, body
-
-
-_MODULES_DIR = _PROMPTS_DIR / "modules"
-
-
-def _load_modules(module_names: list[str]) -> str:
-    parts = []
-    for name in module_names:
-        p = _MODULES_DIR / f"{name}.md"
-        if p.exists():
-            parts.append(p.read_text().strip())
-        else:
-            logger.warning(f"Module '{name}' not found at {p}")
-    return "\n\n".join(parts)
-
-
-def _role_prompt_file(role: str) -> str:
-    """Find the best prompt for a role. Parses frontmatter, returns body + modules.
-    Falls back to 'worker' role if role file not found."""
-    role_path = _PROMPTS_DIR / "roles" / f"{role}.md"
-    if role_path.exists():
-        meta, body = _parse_role_frontmatter(role_path.read_text())
-        if body:
-            modules = meta.get("modules", [])
-            if modules:
-                body = body + "\n\n" + _load_modules(modules)
-            return body
-    if role != "worker":
-        fallback = _PROMPTS_DIR / "roles" / ("orchestrator.md" if is_orchestrator_role(role) else "worker.md")
-        if fallback.exists():
-            meta, body = _parse_role_frontmatter(fallback.read_text())
-            if body:
-                modules = meta.get("modules", [])
-                if modules:
-                    body = body + "\n\n" + _load_modules(modules)
-                return body
-    return ""
-
-
-_SKILLS_DIR = _PROMPTS_DIR / "skills"
-
-
-
-def _role_can_spawn(role: str):
-    """Return the can_spawn whitelist for a role, or None if unrestricted.
-    None  = field absent OR malformed -> no restriction (spawn anything)
-    []    = empty list                -> terminal role (spawn nothing)
-    [...] = whitelist of allowed child roles
-    """
-    role_path = _PROMPTS_DIR / "roles" / f"{role}.md"
-    if not role_path.exists():
-        return None
-    meta, _ = _parse_role_frontmatter(role_path.read_text())
-    if "can_spawn" not in meta:
-        return None
-    val = meta["can_spawn"]
-    if not isinstance(val, list):
-        logger.warning(f"role '{role}' has non-list can_spawn ({val!r}); treating as unrestricted")
-        return None
-    return [str(x) for x in val]
-
-
-def _skills_catalog() -> str:
-    """Build catalog of available skills from skills/ directory for orchestrator."""
-    if not _SKILLS_DIR.is_dir():
-        return ""
-    entries = []
-    for f in sorted(_SKILLS_DIR.glob("*.md")):
-        meta, _ = _parse_role_frontmatter(f.read_text())
-        name = meta.get("name", f.stem)
-        desc = meta.get("description", "").strip().replace("\n", " ")
-        entries.append(f"- `{name}` — {desc}")
-    if not entries:
-        return ""
-    return "## Available skills (for roles)\nSkills are auto-injected into worker prompts via `skills:` in role frontmatter.\n" + "\n".join(entries)
-
-
-def get_role_icons() -> dict[str, str]:
-    roles_dir = _PROMPTS_DIR / "roles"
-    icons = {}
-    if roles_dir.is_dir():
-        for f in sorted(roles_dir.glob("*.md")):
-            meta, _ = _parse_role_frontmatter(f.read_text())
-            if meta:
-                name = meta.get("name", f.stem)
-                icon = meta.get("icon", "")
-                if icon:
-                    icons[name] = icon
-    return icons
-
-
-def _roles_catalog() -> str:
-    """Build a catalog of available worker roles from roles/ directory frontmatter.
-    Injected into orchestrator prompt so it knows what roles exist."""
-    roles_dir = _PROMPTS_DIR / "roles"
-    if not roles_dir.is_dir():
-        return ""
-    entries = []
-    for f in sorted(roles_dir.glob("*.md")):
-        meta, _ = _parse_role_frontmatter(f.read_text())
-        if not meta or meta.get("name") == "orchestrator":
-            continue
-        name = meta.get("name", f.stem)
-        label = meta.get("label", name)
-        model = meta.get("model", "any")
-        desc = meta.get("description", "").strip().replace("\n", " ")
-        when = meta.get("when", "").strip()
-        not_for = meta.get("not_for", "").strip()
-        skills_list = meta.get("skills", [])
-        entry = f"### `{name}` ({label}) — model: {model}\n{desc}"
-        if when:
-            entry += f"\n- ✅ **When**: {when}"
-        if not_for:
-            entry += f"\n- ❌ **Not for**: {not_for}"
-        if skills_list:
-            entry += f"\n- 🔧 **Skills**: {', '.join(skills_list)}"
-        entries.append(entry)
-    if not entries:
-        return ""
-    return "## Available worker roles\nSpawn with `role=\"<name>\"`. If no role specified, defaults to `worker`.\n\n" + "\n\n".join(entries)
-
-
 def ROLE_SYSTEM_PROMPT(role: str, scope: str = "") -> str:
-    base = f"{_read_prompt('base.md')}\n\n{_role_prompt_file(role)}"
+    base = f"{read_prompt('base.md')}\n\n{role_prompt_file(role)}"
     if is_orchestrator_role(role):
-        catalog = _roles_catalog()
+        catalog = roles_catalog()
         if catalog:
             base += f"\n\n{catalog}"
-        skills_cat = _skills_catalog()
+        skills_cat = skills_catalog()
         if skills_cat:
             base += f"\n\n{skills_cat}"
         others = _other_orchestrators_block(scope)
         if others:
             base += f"\n\n{others}"
         workers = _workers_block(scope)
         if workers:
             base += f"\n\n{workers}"
@@ -250,48 +106,16 @@ def ROLE_SYSTEM_PROMPT(role: str, scope: str = "") -> str:
 def ORCHESTRATOR_SYSTEM_PROMPT(scope: str = "") -> str:
     return ROLE_SYSTEM_PROMPT("orchestrator", scope)
 
 
 def WORKER_SYSTEM_PROMPT() -> str:
     return ROLE_SYSTEM_PROMPT("worker")
 
 
-def _prompt_template_hash(role_or_orch) -> str:
-    """Hash only the static template files (base.md + role.md + skills).
-    Accepts role string or legacy bool (is_orchestrator)."""
-    import hashlib
-    if isinstance(role_or_orch, bool):
-        role = "orchestrator" if role_or_orch else "worker"
-    else:
-        role = role_or_orch
-    content = _read_prompt("base.md") + _role_prompt_file(role)
-    return hashlib.md5(content.encode()).hexdigest()[:8]
-
-
-def _inject_skills_to_worktree(role: str, worktree_path: str) -> None:
-    """Copy role skills into worktree/.claude/skills/ as native Claude CLI skills."""
-    role_path = _PROMPTS_DIR / "roles" / f"{role}.md"
-    if not role_path.exists():
-        return
-    meta, _ = _parse_role_frontmatter(role_path.read_text())
-    skill_names = meta.get("skills", [])
-    if not skill_names or not _SKILLS_DIR.is_dir():
-        return
-    wt = Path(worktree_path)
-    for sname in skill_names:
-        skill_src = _SKILLS_DIR / f"{sname}.md"
-        if not skill_src.exists():
-            logger.warning(f"Skill '{sname}' not found in {_SKILLS_DIR}")
-            continue
-        skill_dir = wt / ".claude" / "skills" / sname
-        skill_dir.mkdir(parents=True, exist_ok=True)
-        import shutil
-        shutil.copy2(skill_src, skill_dir / "SKILL.md")
-    logger.info(f"Injected {len(skill_names)} skills into {worktree_path}/.claude/skills/")
 
 
 def _parse_custom_mcp(raw) -> dict:
     """Sanitize custom MCP servers (from DB JSON string or a dict).
     Returns a dict with the `orchestra` key stripped. Non-dict input -> {}."""
     if not raw:
         return {}
     if isinstance(raw, str):
@@ -461,17 +285,17 @@ class SessionManager:
         if not parent_id and parent_name:
             p_session = self.get_by_name(parent_name, scope)
             if p_session:
                 parent_id = p_session.id if isinstance(p_session, AgentSession) else p_session.get("id", "")
 
         if parent_name:
             parent_role = self._resolve_role(parent_name, scope)
             if parent_role:
-                whitelist = _role_can_spawn(parent_role)
+                whitelist = role_can_spawn(parent_role)
                 if whitelist is not None and role not in whitelist:
                     allowed = ", ".join(whitelist) if whitelist else "(none — terminal role)"
                     raise ValueError(
                         f"role '{parent_role}' is not allowed to spawn role '{role}'. "
                         f"Allowed: {allowed}"
                     )
 
         # Root orchestrators (no parent) always get a TG topic
@@ -486,17 +310,17 @@ class SessionManager:
             parent_id=parent_id, parent_name=parent_name,
             color="" if is_orch else self._pick_color(),
             mcp_servers=_make_mcp_config(name, scope, role, extra=custom_mcp),
             mcp_servers_custom=custom_mcp,
             backend_type=bt, task_id=task_id, description=description,
             owned_dirs=owned_dirs,
             tg_topic=tg_topic,
         )
-        session._template_hash = _prompt_template_hash(role)
+        session._template_hash = prompt_template_hash(role)
         session._spawn_warning = ownership_warning
         save_session(session._to_db_dict())
 
         if task_id and not is_orch:
             try:
                 from app.tm import api_update_task
                 api_update_task(task_id, status="in_progress")
             except Exception:
@@ -506,21 +330,21 @@ class SessionManager:
             if use_worktree and repo_path:
                 wip_note = await asyncio.to_thread(self._auto_commit_if_dirty, repo_path)
                 if wip_note:
                     session._spawn_warning = (session._spawn_warning + "; " + wip_note).strip("; ")
                 wt = await asyncio.to_thread(create_worktree, repo_path, name, scope, task_id, base_branch)
                 session.cwd = wt.path
                 session.worktree_path = wt.path
                 session.branch = wt.branch
-                await asyncio.to_thread(_inject_skills_to_worktree, role, wt.path)
+                await asyncio.to_thread(inject_skills_to_worktree, role, wt.path)
 
             if not is_orch:
                 orch_name = parent_name or self._find_orchestrator_name(scope)
-                session.system_prompt = _safe_format_prompt(
+                session.system_prompt = safe_format_prompt(
                     session.system_prompt,
                     worker_name=name, orchestrator_name=orch_name or "orchestrator",
                     scope=scope, branch=session.branch or "main",
                 )
                 session.on_idle = self._make_idle_callback(scope)
 
             save_session(session._to_db_dict())
             await session.start()
@@ -762,32 +586,32 @@ class SessionManager:
         pct = db_row.get("context_pct", 0) or 0
         tokens = db_row.get("context_tokens", 0) or 0
         if pct or tokens:
             from app.models import CONTEXT_LIMITS
             max_t = CONTEXT_LIMITS.get(db_row["model"], 200000)
             session._last_context = {"percentage": pct, "total_tokens": tokens, "max_tokens": max_t}
         orch_name = self._find_orchestrator_name(db_row["scope"]) if not is_orch else None
         if not is_orch:
-            current_prompt = _safe_format_prompt(
+            current_prompt = safe_format_prompt(
                 current_prompt,
                 worker_name=db_row["name"], orchestrator_name=orch_name or "orchestrator",
                 scope=db_row["scope"], branch=db_row.get("branch") or "main",
             )
         if old_prompt and old_prompt != current_prompt:
-            formatted_base = _safe_format_prompt(
+            formatted_base = safe_format_prompt(
                 ROLE_SYSTEM_PROMPT(role, db_row["scope"]) if is_orch else ROLE_SYSTEM_PROMPT(role),
                 worker_name=db_row["name"], orchestrator_name=orch_name or "orchestrator",
                 scope=db_row["scope"], branch=db_row.get("branch") or "main",
             )
             if old_prompt.startswith(formatted_base) and len(old_prompt) > len(formatted_base):
                 custom_part = old_prompt[len(formatted_base):]
                 current_prompt = current_prompt + custom_part
         session._current_prompt = current_prompt
-        session._template_hash = db_row.get("template_hash") or _prompt_template_hash(role)
+        session._template_hash = db_row.get("template_hash") or prompt_template_hash(role)
         if not is_orch:
             session.on_idle = self._make_idle_callback(db_row["scope"])
         await session.start()
         self.sessions[session.id] = session
         return session
 
     def _find_orchestrator_name(self, scope: str) -> str | None:
         for s in self.sessions.values():
diff --git a/app/prompting.py b/app/prompting.py
new file mode 100644
index 000000000..c5bba4c54
--- /dev/null
+++ b/app/prompting.py
@@ -0,0 +1,186 @@
+"""Prompt composition — pure file/template helpers for agent prompts."""
+
+import hashlib
+import logging
+import re
+import shutil
+from pathlib import Path
+
+logger = logging.getLogger(__name__)
+
+_PROMPTS_DIR = Path(__file__).parent / "prompts"
+_MODULES_DIR = _PROMPTS_DIR / "modules"
+_SKILLS_DIR = _PROMPTS_DIR / "skills"
+
+_ORCHESTRATOR_ROLES = frozenset({"orchestrator", "sub-orchestrator"})
+_IDENTITY_PLACEHOLDERS = re.compile(r"\{(worker_name|orchestrator_name|scope|branch)\}")
+
+
+def is_orchestrator_role(role: str) -> bool:
+    return role in _ORCHESTRATOR_ROLES
+
+
+def safe_format_prompt(template: str, **kwargs: str) -> str:
+    """Substitute only known identity placeholders, leaving other {braces} intact."""
+    return _IDENTITY_PLACEHOLDERS.sub(lambda m: kwargs.get(m.group(1), m.group(0)), template)
+
+
+def read_prompt(name: str) -> str:
+    p = _PROMPTS_DIR / name
+    return p.read_text() if p.exists() else ""
+
+
+def parse_role_frontmatter(text: str) -> tuple[dict, str]:
+    """Parse YAML frontmatter from role .md file. Returns (meta, body)."""
+    if not text.startswith("---"):
+        return {}, text
+    parts = text.split("---", 2)
+    if len(parts) < 3:
+        return {}, text
+    try:
+        import yaml
+        meta = yaml.safe_load(parts[1]) or {}
+    except Exception:
+        meta = {}
+    body = parts[2].strip()
+    return meta, body
+
+
+def _load_modules(module_names: list[str]) -> str:
+    parts = []
+    for name in module_names:
+        p = _MODULES_DIR / f"{name}.md"
+        if p.exists():
+            parts.append(p.read_text().strip())
+        else:
+            logger.warning(f"Module '{name}' not found at {p}")
+    return "\n\n".join(parts)
+
+
+def role_prompt_file(role: str) -> str:
+    """Find the best prompt for a role. Parses frontmatter, returns body + modules.
+    Falls back to 'worker' role if role file not found."""
+    role_path = _PROMPTS_DIR / "roles" / f"{role}.md"
+    if role_path.exists():
+        meta, body = parse_role_frontmatter(role_path.read_text())
+        if body:
+            modules = meta.get("modules", [])
+            if modules:
+                body = body + "\n\n" + _load_modules(modules)
+            return body
+    if role != "worker":
+        fallback = _PROMPTS_DIR / "roles" / ("orchestrator.md" if is_orchestrator_role(role) else "worker.md")
+        if fallback.exists():
+            meta, body = parse_role_frontmatter(fallback.read_text())
+            if body:
+                modules = meta.get("modules", [])
+                if modules:
+                    body = body + "\n\n" + _load_modules(modules)
+                return body
+    return ""
+
+
+def role_can_spawn(role: str):
+    """Return the can_spawn whitelist for a role, or None if unrestricted."""
+    role_path = _PROMPTS_DIR / "roles" / f"{role}.md"
+    if not role_path.exists():
+        return None
+    meta, _ = parse_role_frontmatter(role_path.read_text())
+    if "can_spawn" not in meta:
+        return None
+    val = meta["can_spawn"]
+    if not isinstance(val, list):
+        logger.warning(f"role '{role}' has non-list can_spawn ({val!r}); treating as unrestricted")
+        return None
+    return [str(x) for x in val]
+
+
+def skills_catalog() -> str:
+    """Build catalog of available skills from skills/ directory for orchestrator."""
+    if not _SKILLS_DIR.is_dir():
+        return ""
+    entries = []
+    for f in sorted(_SKILLS_DIR.glob("*.md")):
+        meta, _ = parse_role_frontmatter(f.read_text())
+        name = meta.get("name", f.stem)
+        desc = meta.get("description", "").strip().replace("\n", " ")
+        entries.append(f"- `{name}` — {desc}")
+    if not entries:
+        return ""
+    return "## Available skills (for roles)\nSkills are auto-injected into worker prompts via `skills:` in role frontmatter.\n" + "\n".join(entries)
+
+
+def get_role_icons() -> dict[str, str]:
+    roles_dir = _PROMPTS_DIR / "roles"
+    icons = {}
+    if roles_dir.is_dir():
+        for f in sorted(roles_dir.glob("*.md")):
+            meta, _ = parse_role_frontmatter(f.read_text())
+            if meta:
+                name = meta.get("name", f.stem)
+                icon = meta.get("icon", "")
+                if icon:
+                    icons[name] = icon
+    return icons
+
+
+def roles_catalog() -> str:
+    """Build a catalog of available worker roles from roles/ directory frontmatter."""
+    roles_dir = _PROMPTS_DIR / "roles"
+    if not roles_dir.is_dir():
+        return ""
+    entries = []
+    for f in sorted(roles_dir.glob("*.md")):
+        meta, _ = parse_role_frontmatter(f.read_text())
+        if not meta or meta.get("name") == "orchestrator":
+            continue
+        name = meta.get("name", f.stem)
+        label = meta.get("label", name)
+        model = meta.get("model", "any")
+        desc = meta.get("description", "").strip().replace("\n", " ")
+        when = meta.get("when", "").strip()
+        not_for = meta.get("not_for", "").strip()
+        skills_list = meta.get("skills", [])
+        entry = f"### `{name}` ({label}) — model: {model}\n{desc}"
+        if when:
+            entry += f"\n- ✅ **When**: {when}"
+        if not_for:
+            entry += f"\n- ❌ **Not for**: {not_for}"
+        if skills_list:
+            entry += f"\n- 🔧 **Skills**: {', '.join(skills_list)}"
+        entries.append(entry)
+    if not entries:
+        return ""
+    return "## Available worker roles\nSpawn with `role=\"<name>\"`. If no role specified, defaults to `worker`.\n\n" + "\n\n".join(entries)
+
+
+def prompt_template_hash(role_or_orch) -> str:
+    """Hash only the static template files (base.md + role.md + skills).
+    Accepts role string or legacy bool (is_orchestrator)."""
+    if isinstance(role_or_orch, bool):
+        role = "orchestrator" if role_or_orch else "worker"
+    else:
+        role = role_or_orch
+    content = read_prompt("base.md") + role_prompt_file(role)
+    return hashlib.md5(content.encode()).hexdigest()[:8]
+
+
+def inject_skills_to_worktree(role: str, worktree_path: str) -> None:
+    """Copy role skills into worktree/.claude/skills/ as native Claude CLI skills."""
+    role_path = _PROMPTS_DIR / "roles" / f"{role}.md"
+    if not role_path.exists():
+        return
+    meta, _ = parse_role_frontmatter(role_path.read_text())
+    skill_names = meta.get("skills", [])
+    if not skill_names or not _SKILLS_DIR.is_dir():
+        return
+    wt = Path(worktree_path)
+    for sname in skill_names:
+        skill_src = _SKILLS_DIR / f"{sname}.md"
+        if not skill_src.exists():
+            logger.warning(f"Skill '{sname}' not found in {_SKILLS_DIR}")
+            continue
+        skill_dir = wt / ".claude" / "skills" / sname
+        skill_dir.mkdir(parents=True, exist_ok=True)
+        shutil.copy2(skill_src, skill_dir / "SKILL.md")
+    logger.info(f"Injected {len(skill_names)} skills into {worktree_path}/.claude/skills/")
diff --git a/app/routes/__init__.py b/app/routes/__init__.py
new file mode 100644
index 000000000..e69de29bb
diff --git a/app/routes/bg.py b/app/routes/bg.py
new file mode 100644
index 000000000..725368513
--- /dev/null
+++ b/app/routes/bg.py
@@ -0,0 +1,55 @@
+"""Background Jobs API routes."""
+
+from fastapi import APIRouter
+from fastapi.responses import JSONResponse
+from pydantic import BaseModel
+
+from app.deps import manager
+
+router = APIRouter(prefix="/api/bg", tags=["bg-jobs"])
+
+
+class BgJobCreateRequest(BaseModel):
+    type: str
+    config: dict = {}
+    message: str = ""
+    target_name: str = ""
+    target_scope: str = ""
+    timeout_seconds: int = 3600
+    created_by: str = ""
+
+
+@router.post("/jobs")
+async def bg_job_create(req: BgJobCreateRequest):
+    from app.bg_jobs import bg_manager
+    scope = req.target_scope.rstrip("/")
+    name = req.target_name
+    if not scope or not name:
+        return JSONResponse({"error": "target_name and target_scope required"}, status_code=400)
+    session = manager.get_by_name(name, scope)
+    if not session:
+        return JSONResponse({"error": f"session '{name}' not found in scope"}, status_code=404)
+    session_id = session.id if hasattr(session, "id") else session.get("id")
+    result = await bg_manager.create(
+        job_type=req.type, config=req.config, message=req.message,
+        target_session_id=session_id, target_name=name, target_scope=scope,
+        created_by=req.created_by, timeout_seconds=req.timeout_seconds,
+    )
+    if result.get("error"):
+        return JSONResponse(result, status_code=400)
+    return result
+
+
+@router.get("/jobs")
+async def bg_job_list(scope: str = "", session_id: str = ""):
+    from app.db import bg_get_jobs
+    return bg_get_jobs(scope=scope or None, session_id=session_id or None)
+
+
+@router.delete("/jobs/{job_id}")
+async def bg_job_cancel(job_id: str):
+    from app.bg_jobs import bg_manager
+    result = await bg_manager.cancel(job_id)
+    if result.get("error"):
+        return JSONResponse(result, status_code=404)
+    return result
diff --git a/app/routes/proxy.py b/app/routes/proxy.py
new file mode 100644
index 000000000..8b4b79121
--- /dev/null
+++ b/app/routes/proxy.py
@@ -0,0 +1,35 @@
+"""Proxy & Tunnel API routes."""
+
+from fastapi import APIRouter
+from fastapi.responses import JSONResponse
+
+from app.proxy_manager import proxy_manager
+from app.ssh_tunnel import tunnel_status
+
+router = APIRouter(tags=["proxy"])
+
+
+@router.get("/api/proxy/list")
+async def proxy_list():
+    return await proxy_manager.list_proxies()
+
+
+@router.post("/api/proxy/check/{proxy_id}")
+async def proxy_check(proxy_id: str):
+    result = await proxy_manager.check_proxy(proxy_id)
+    if result.get("error"):
+        return JSONResponse(result, status_code=400)
+    return result
+
+
+@router.post("/api/proxy/select/{proxy_id}")
+async def proxy_select(proxy_id: str):
+    result = await proxy_manager.select_proxy(proxy_id)
+    if result.get("error"):
+        return JSONResponse(result, status_code=400)
+    return result
+
+
+@router.get("/api/tunnel/status")
+async def api_tunnel_status():
+    return tunnel_status()
diff --git a/app/routes/tm.py b/app/routes/tm.py
new file mode 100644
index 000000000..583d32a80
--- /dev/null
+++ b/app/routes/tm.py
@@ -0,0 +1,173 @@
+"""Task Manager API routes."""
+
+from fastapi import APIRouter
+from fastapi.responses import JSONResponse
+from pydantic import BaseModel
+
+from app import tm as _tm
+
+router = APIRouter(prefix="/api/tm", tags=["task-manager"])
+
+
+class TmTaskCreate(BaseModel):
+    title: str
+    project: str
+    price: int = 0
+    description: str = ""
+    assignee: str = ""
+    status: str = "new"
+    scope: str = ""
+    priority: int = 2
+
+
+class TmTaskUpdate(BaseModel):
+    title: str | None = None
+    description: str | None = None
+    price: int | None = None
+    status: str | None = None
+    assignee: str | None = None
+    priority: int | None = None
+
+
+class TmPaymentReceive(BaseModel):
+    amount: int
+    client: str = ""
+    scope: str = ""
+    date: str = ""
+    note: str = ""
+
+
+def _resolve_client_id(client: str, scope: str) -> str:
+    if client:
+        return client
+    if scope:
+        with _tm._conn() as conn:
+            proj = _tm.get_project_by_scope(conn, scope)
+            if proj:
+                cl = _tm.get_client_for_project(conn, proj["id"])
+                if cl:
+                    return cl["id"]
+    raise ValueError("No client specified and no client found for project scope")
+
+
+@router.post("/tasks")
+async def tm_create_task(req: TmTaskCreate):
+    try:
+        return _tm.api_create_task(
+            req.project, req.title, req.price, req.description, req.assignee, req.status,
+            scope=req.scope, priority=req.priority,
+        )
+    except (ValueError, RuntimeError) as e:
+        return JSONResponse({"error": str(e)}, status_code=400)
+
+
+@router.get("/tasks")
+async def tm_list_tasks(project: str = "", status: str = "", assignee: str = "",
+                        scope: str = ""):
+    proj = project
+    if not proj and scope:
+        with _tm._conn() as conn:
+            p = _tm.get_project_by_scope(conn, scope)
+            if p:
+                proj = p["id"]
+            else:
+                return {"tasks": [], "count": 0, "total_debt": "0"}
+    return _tm.api_list_tasks(proj, status, assignee)
+
+
+@router.get("/tasks/{par}")
+async def tm_get_task(par: str, scope: str = ""):
+    try:
+        project = ""
+        if scope:
+            with _tm._conn() as conn:
+                p = _tm.get_project_by_scope(conn, scope)
+                if p:
+                    project = p["id"]
+        return _tm.api_get_task(par, project=project)
+    except ValueError as e:
+        return JSONResponse({"error": str(e)}, status_code=404)
+
+
+@router.put("/tasks/{par}")
+async def tm_update_task(par: str, req: TmTaskUpdate, scope: str = ""):
+    try:
+        project = ""
+        if scope:
+            with _tm._conn() as conn:
+                p = _tm.get_project_by_scope(conn, scope)
+                if p:
+                    project = p["id"]
+        return _tm.api_update_task(
+            par, req.title, req.description, req.price, req.status, req.assignee,
+            project=project, priority=req.priority,
+        )
+    except (ValueError, RuntimeError) as e:
+        code = 404 if "not found" in str(e).lower() else 400
+        return JSONResponse({"error": str(e)}, status_code=code)
+
+
+@router.post("/payments")
+async def tm_receive_payment(req: TmPaymentReceive):
+    try:
+        client_id = _resolve_client_id(req.client, req.scope)
+        return _tm.api_receive_payment(req.amount, client_id, req.date, req.note)
+    except (ValueError, RuntimeError) as e:
+        return JSONResponse({"error": str(e)}, status_code=400)
+
+
+@router.get("/payments/status")
+async def tm_payment_status(client: str = "", scope: str = ""):
+    try:
+        client_id = _resolve_client_id(client, scope)
+        return _tm.api_payment_status(client_id)


## LATER FIX 18d8061390 (29.0 days later): #4: #proxy-fix: force stable id='direct' for direct proxy
lines of origin it changed/deleted: 8
(code only, capped 400 lines)

#4: #proxy-fix: force stable id='direct' for direct proxy

Squashed commits:
- #proxy-fix: force stable id='direct' for direct proxy
- #proxy-fix #4: backoff + health-gate против zombie-туннелей
- #proxy-fix: .env = единственный источник истины прокси (вырезать DB/hot-switch)
- #proxy-fix: CHANGELOG v2.24.0 + report
- take main check-proxies.sh (priority-aware retry)


diff --git a/app/main.py b/app/main.py
index 73346246f..f218a9d81 100644
--- a/app/main.py
+++ b/app/main.py
@@ -16,18 +16,16 @@ from app.deps import manager
 logger = logging.getLogger("orchestra")
 
 
 @asynccontextmanager
 async def lifespan(app: FastAPI):
     from dotenv import load_dotenv
     load_dotenv()
     init_db()
-    from app.proxy_manager import proxy_manager
-    proxy_manager.load_saved_proxy()
     from app.models import refresh_models, is_proxy_connected
     await refresh_models()
     if is_auth_enabled() and not is_proxy_connected():
         async def _proxy_retry_loop():
             while not is_proxy_connected():
                 await asyncio.sleep(60)
                 await refresh_models()
                 if is_proxy_connected():
@@ -49,20 +47,18 @@ async def lifespan(app: FastAPI):
     await start_bridge(manager)
     _tunnel_started = False
     if not is_auth_enabled():
         from app.ssh_tunnel import start_tunnel, stop_tunnel
         await start_tunnel()
         _tunnel_started = True
     from app.routes.system import _usage_snapshot_loop
     snapshot_task = asyncio.create_task(_usage_snapshot_loop())
-    proxy_refresh_task = asyncio.create_task(proxy_manager.refresh_loop())
     yield
     snapshot_task.cancel()
-    proxy_refresh_task.cancel()
     if _tunnel_started:
         await stop_tunnel()
     await stop_bridge()
     await bg_manager.shutdown()
     await manager.shutdown_all()
 
 
 app = FastAPI(title="Orchestra", lifespan=lifespan)
diff --git a/app/proxy_manager.py b/app/proxy_manager.py
index c6848f697..f4aad0e0f 100644
--- a/app/proxy_manager.py
+++ b/app/proxy_manager.py
@@ -1,24 +1,25 @@
-"""Proxy manager — switch HTTPS_PROXY for all agents."""
+"""Proxy list + on-demand health check — READ-ONLY.
+
+Source of truth for the active proxy is .env HTTPS_PROXY (systemd EnvironmentFile
+→ os.environ). This module NEVER mutates proxy env or persists anything: it only
+reads PROXY_LIST for the dashboard and probes liveness on demand. To switch proxy:
+edit .env + restart Orchestra.
+"""
 
 import asyncio
 import logging
 import os
-import time
 from dataclasses import dataclass
 
 import httpx
 
-from app.runtime_env import MCP_BASE_ENV
-
 logger = logging.getLogger(__name__)
 
-CACHE_TTL = 60  # seconds — stale check results are dropped so UI never shows a dead proxy as green
-
 COUNTRY_FLAGS = {
     "US": "🇺🇸", "GB": "🇬🇧", "DE": "🇩🇪", "NL": "🇳🇱", "FR": "🇫🇷",
     "FI": "🇫🇮", "SE": "🇸🇪", "NO": "🇳🇴", "CH": "🇨🇭", "AT": "🇦🇹",
     "RU": "🇷🇺", "UA": "🇺🇦", "KZ": "🇰🇿", "BY": "🇧🇾",
     "JP": "🇯🇵", "KR": "🇰🇷", "SG": "🇸🇬", "AU": "🇦🇺",
     "CA": "🇨🇦", "BR": "🇧🇷", "IN": "🇮🇳", "TR": "🇹🇷",
     "PL": "🇵🇱", "CZ": "🇨🇿", "RO": "🇷🇴", "BG": "🇧🇬",
     "HK": "🇭🇰", "TW": "🇹🇼", "IE": "🇮🇪", "ES": "🇪🇸",
@@ -52,66 +53,38 @@ def _parse_proxy_list() -> list[ProxyEntry]:
             parts = item.split("|", 2)
             pid = parts[0].strip().lower().replace(" ", "-")
             name = parts[0].strip()
             url = parts[1].strip()
         else:
             url = item
             pid = url.split(":")[-1] if ":" in url else "proxy"
             name = url
+        # Stable id for direct — name-derived id mangles cyrillic/parens
+        # ("Direct (VPN/Соту)" → "direct-(vpn/соту)")
+        if url == "direct":
+            pid = "direct"
         entries.append(ProxyEntry(id=pid, name=name, url=url))
     return entries
 
 
-class ProxyManager:
-    def __init__(self):
-        self._active_id: str | None = None
-        self._cache: dict[str, dict] = {}
+def _active_id(entries: list[ProxyEntry]) -> str:
+    """Which entry matches the current HTTPS_PROXY (from .env). Read-only."""
+    current = os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY") or ""
+    if not current:
+        direct = next((e for e in entries if e.url == "direct"), None)
+        return direct.id if direct else ""
+    match = next((e for e in entries if e.url == current), None)
+    return match.id if match else ""
+
 
+class ProxyManager:
     def _get_entries(self) -> list[ProxyEntry]:
         return _parse_proxy_list()
 
-    def load_saved_proxy(self) -> None:
-        """Load saved proxy from DB and apply to os.environ. Call at startup before auto_resume."""
-        try:
-            from app.db import kv_get
-            saved_id = kv_get("active_proxy")
-            if not saved_id:
-                return
-            entries = self._get_entries()
-            entry = next((e for e in entries if e.id == saved_id), None)
-            if not entry:
-                return
-            if entry.url == "direct":
-                for k in ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy"):
-                    os.environ.pop(k, None)
-            else:
-                for k in ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy"):
-                    os.environ[k] = entry.url
-            self._active_id = saved_id
-            logger.info(f"Restored proxy from DB: '{entry.name}' ({entry.url})")
-        except Exception as e:
-            logger.warning(f"Failed to load saved proxy: {e}")
-
-    def _get_active_id(self) -> str:
-        if self._active_id:
-            return self._active_id
-        entries = self._get_entries()
-        current_proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY") or ""
-        if not current_proxy:
-            direct = next((e for e in entries if e.url == "direct"), None)
-            if direct:
-                self._active_id = direct.id
-                return direct.id
-        for e in entries:
-            if e.url == current_proxy:
-                self._active_id = e.id
-                return e.id
-        return entries[0].id if entries else ""
-
     async def check_proxy(self, proxy_id: str) -> dict:
         entries = self._get_entries()
         entry = next((e for e in entries if e.id == proxy_id), None)
         if not entry:
             return {"error": f"proxy '{proxy_id}' not found"}
         return await self._do_check(entry)
 
     async def _do_check(self, entry: ProxyEntry) -> dict:
@@ -119,85 +92,37 @@ class ProxyManager:
             kwargs = {"timeout": IP_CHECK_TIMEOUT, "verify": False}
             if entry.url and entry.url != "direct":
                 kwargs["proxy"] = entry.url
             async with httpx.AsyncClient(**kwargs) as client:
                 resp = await client.get(IP_CHECK_URL)
                 if resp.status_code != 200:
                     return {"id": entry.id, "ok": False, "error": f"HTTP {resp.status_code}"}
                 data = resp.json()
-                ip = data.get("ip", "?")
                 country = data.get("country", "??")
-                city = data.get("city", "")
-                org = data.get("org", "")
-                flag = COUNTRY_FLAGS.get(country, "🏳️")
-                result = {
+                return {
                     "id": entry.id, "ok": True,
-                    "ip": ip, "country": country, "city": city,
-                    "org": org, "flag": flag,
+                    "ip": data.get("ip", "?"), "country": country,
+                    "city": data.get("city", ""), "org": data.get("org", ""),
+                    "flag": COUNTRY_FLAGS.get(country, "🏳️"),
                 }
-                self._cache[entry.id] = {**result, "_ts": time.monotonic()}
-                return result
         except Exception as e:
-            result = {"id": entry.id, "ok": False, "error": str(e)}
-            self._cache[entry.id] = {**result, "_ts": time.monotonic()}
-            return result
+            return {"id": entry.id, "ok": False, "error": str(e)}
 
     async def list_proxies(self) -> dict:
+        """List proxies from .env. `active` = current HTTPS_PROXY (read-only).
+
+        No liveness here — call check/{id} or check_all for that (on-demand).
+        """
         entries = self._get_entries()
-        active_id = self._get_active_id()
-        proxies = []
-        now = time.monotonic()
-        for e in entries:
-            cached = self._cache.get(e.id)
-            info = {
-                "id": e.id, "name": e.name, "url": e.url,
-                "active": e.id == active_id,
-            }
-            # Drop stale results — a proxy that died stays "green" forever otherwise
-            if cached and now - cached.get("_ts", 0) < CACHE_TTL:
-                info.update({k: cached[k] for k in ("ok", "ip", "country", "city", "flag", "error") if k in cached})
-            proxies.append(info)
+        active_id = _active_id(entries)
+        proxies = [
+            {"id": e.id, "name": e.name, "url": e.url, "active": e.id == active_id}
+            for e in entries
+        ]
         return {"proxies": proxies, "active": active_id}
 
     async def check_all(self) -> list[dict]:
         entries = self._get_entries()
-        tasks = [self._do_check(e) for e in entries]
-        return await asyncio.gather(*tasks)
-
-    async def refresh_loop(self):
-        """Periodically re-check all proxies so the dashboard self-heals.
-
-        WHY: without this a proxy that dies stays 🟢 until someone clicks Check.
-        Combined with CACHE_TTL, results older than one interval never render green.
-        """
-        while True:
-            try:
-                await self.check_all()
-            except Exception as e:
-                logger.warning(f"proxy refresh_loop error: {e}")
-            await asyncio.sleep(CACHE_TTL)
-
-    async def select_proxy(self, proxy_id: str) -> dict:
-        entries = self._get_entries()
-        entry = next((e for e in entries if e.id == proxy_id), None)
-        if not entry:
-            return {"error": f"proxy '{proxy_id}' not found"}
-        if entry.url == "direct":
-            for k in ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy"):
-                os.environ.pop(k, None)
-                MCP_BASE_ENV.pop(k, None)
-        else:
-            for k, v in [("HTTPS_PROXY", entry.url), ("HTTP_PROXY", entry.url),
-                         ("https_proxy", entry.url), ("http_proxy", entry.url)]:
-                os.environ[k] = v
-                MCP_BASE_ENV[k] = v
-        self._active_id = proxy_id
-        try:
-            from app.db import kv_set
-            kv_set("active_proxy", proxy_id)
-        except Exception as e:
-            logger.warning(f"Failed to persist proxy choice: {e}")
-        logger.info(f"Proxy switched to '{entry.name}' ({entry.url})")
-        return {"ok": True, "active": proxy_id, "url": entry.url}
+        return await asyncio.gather(*(self._do_check(e) for e in entries))
 
 
 proxy_manager = ProxyManager()
diff --git a/app/routes/proxy.py b/app/routes/proxy.py
index cd85c6426..30e95f78a 100644
--- a/app/routes/proxy.py
+++ b/app/routes/proxy.py
@@ -25,32 +25,12 @@ async def proxy_list():
 async def proxy_check(proxy_id: str):
     _block_if_enterprise()
     result = await proxy_manager.check_proxy(proxy_id)
     if result.get("error"):
         return JSONResponse(result, status_code=400)
     return result
 
 
-@router.post("/api/proxy/select/{proxy_id}")
-async def proxy_select(proxy_id: str):
-    _block_if_enterprise()
-    result = await proxy_manager.select_proxy(proxy_id)
-    if result.get("error"):
-        return JSONResponse(result, status_code=400)
-    from app.deps import manager
-    reconnected = 0
-    for s in list(manager.sessions.values()):
-        if s.status.value == "running" and s._backend:
-            try:
-                await s._backend.interrupt()
-                reconnected += 1
-            except Exception:
-                pass
-    if reconnected:
-        result["interrupted"] = reconnected
-    return result
-
-
 @router.get("/api/tunnel/status")
 async def api_tunnel_status():
     _block_if_enterprise()
     return tunnel_status()
diff --git a/app/ssh_tunnel.py b/app/ssh_tunnel.py
index 25e9aa166..cf85be99d 100644
--- a/app/ssh_tunnel.py
+++ b/app/ssh_tunnel.py
@@ -5,25 +5,48 @@ Config via SSH_TUNNELS env var (pipe-separated fields, comma-separated entries):
 
 Example:
   SSH_TUNNELS=ezhik|12340|194.87.250.243|18080|/path/to/key,timeweb|12341|147.45.101.84|3128|
 """
 
 import asyncio
 import logging
 import os
+import time
 from dataclasses import dataclass, field
 
 logger = logging.getLogger("ssh-tunnel")
 
 RECONNECT_DELAY = 5
+BACKOFF_MAX = 300  # cap exponential backoff — dead VPS retries every 5min, not 5s
+HEALTHY_UPTIME = 60  # ssh alive this long → connection was healthy, reset backoff
+HEALTH_TIMEOUT = 2  # TCP :22 probe timeout before spawning ssh
 KILL_GRACE = 3  # seconds to wait after terminate() before SIGKILL
 DEFAULT_KEY = os.path.expanduser("~/.ssh/id_ed25519")
 
 
+async def _port_open(host: str, port: int, timeout: float) -> bool:
+    """Quick TCP reachability probe — gate ssh spawn so dead VPS don't churn.
+
+    WHY: without this, a dead/DPI-blocked VPS (timeweb/ezhik) respawns ssh every
+    5s forever, spamming logs and racing with half-dead forwards → zombies.
+    """
+    try:
+        fut = asyncio.open_connection(host, port)
+        _, writer = await asyncio.wait_for(fut, timeout=timeout)
+        writer.close()
+        try:
+            await writer.wait_closed()
+        except Exception:
+            pass
+        return True
+    except Exception:
+        return False
+
+
 @dataclass
 class Tunnel:
     name: str
     local_port: int
     host: str
     remote_port: int
     key_path: str
     proc: asyncio.subprocess.Process | None = field(default=None, repr=False)
@@ -88,18 +111,27 @@ def _parse_legacy() -> list[Tunnel]:
     key = os.getenv("SSH_TUNNEL_KEY", DEFAULT_KEY)
     local = int(os.getenv("SSH_TUNNEL_LOCAL_PORT", "12338"))
     remote = int(os.getenv("SSH_TUNNEL_REMOTE_PORT", "18080"))
     return [Tunnel(name="legacy", local_port=local, host=host,
                    remote_port=remote, key_path=key)]
 
 
 async def _tunnel_loop(t: Tunnel):
+    backoff = RECONNECT_DELAY
     while True:
         try:
+            # Health-gate: don't spawn ssh at a VPS whose :22 is unreachable —
+            # that's what makes dead VPS churn processes every 5s.
+            if not await _port_open(t.host, 22, HEALTH_TIMEOUT):
+                logger.info(f"tunnel {t.name} :22 unreachable, retry in {backoff}s")
+                await asyncio.sleep(backoff)
+                backoff = min(backoff * 2, BACKOFF_MAX)
+                continue
+            started = time.monotonic()
             t.proc = await asyncio.create_subprocess_exec(
                 "ssh", "-N",
                 "-L", f"{t.local_port}:127.0.0.1:{t.remote_port}",
                 "-i", t.key_path,
                 "-o", "StrictHostKeyChecking=no",
                 "-o", "ServerAliveInterval=30",
                 "-o", "ServerAliveCountMax=3",
                 "-o", "ExitOnForwardFailure=yes",
@@ -110,30 +142,36 @@ async def _tunnel_loop(t: Tunnel):
             t.running = True
             logger.info(f"tunnel {t.name} started pid={t.proc.pid} "
                         f"(:{t.local_port} → {t.host}:{t.remote_port})")
             _, stderr = await t.proc.communicate()
             t.running = False
             msg = stderr.decode().strip() if stderr else ""
             logger.warning(f"tunnel {t.name} died pid={t.proc.pid}"
                            f"{': ' + msg if msg else ''}")
+            # Reset backoff only if the tunnel stayed up long enough to be healthy