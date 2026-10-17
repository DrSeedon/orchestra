# Context for item-14

## Diff reviewed (-U20, capped at 1500 lines)

diff --git a/app/bootstrap.py b/app/bootstrap.py
new file mode 100644
index 000000000..9e0b45c59
--- /dev/null
+++ b/app/bootstrap.py
@@ -0,0 +1,97 @@
+"""Auto-bootstrap: ensure workspace + default orchestrator on first startup."""
+
+import logging
+import os
+import subprocess
+import uuid
+from datetime import datetime, timezone
+from pathlib import Path
+
+from app.db import get_all_sessions, save_session
+from app.models import DEFAULT_MODEL, resolve_model, backend_for_model
+
+logger = logging.getLogger(__name__)
+
+WORKSPACE_DIR = "/workspace/project"
+
+_DEFAULT_CLAUDE_MD = """\
+# Project
+
+This workspace was auto-created by Orchestra.
+"""
+
+_DEFAULT_SYSTEM_PROMPT = (
+    "You are an AI orchestrator. Manage workers, delegate tasks, report results."
+)
+
+
+async def ensure_bootstrap() -> None:
+    """Idempotent bootstrap: workspace dir + default orchestrator DB record."""
+    _ensure_workspace()
+    _ensure_orchestrator()
+
+
+def _ensure_workspace() -> None:
+    ws = Path(WORKSPACE_DIR)
+    if ws.is_dir():
+        return
+
+    try:
+        ws.mkdir(parents=True, exist_ok=True)
+    except OSError as e:
+        logger.warning("Bootstrap: cannot create workspace %s: %s", WORKSPACE_DIR, e)
+        return
+
+    subprocess.run(["git", "init"], cwd=str(ws), capture_output=True)
+    (ws / "CLAUDE.md").write_text(_DEFAULT_CLAUDE_MD)
+    subprocess.run(
+        ["git", "add", "CLAUDE.md"],
+        cwd=str(ws), capture_output=True,
+    )
+    subprocess.run(
+        ["git", "commit", "-m", "bootstrap: init workspace"],
+        cwd=str(ws), capture_output=True,
+    )
+    logger.info("Bootstrap: created workspace %s", WORKSPACE_DIR)
+
+
+def _ensure_orchestrator() -> None:
+    sessions = get_all_sessions()
+    has_orch = any(
+        bool(s.get("is_orchestrator")) or s.get("role") == "orchestrator"
+        for s in sessions
+    )
+    if has_orch:
+        logger.info("Bootstrap: skipping, orchestrator exists")
+        return
+
+    name = os.environ.get("BOOTSTRAP_ORCH_NAME", "orchestrator")
+    model = resolve_model(os.environ.get("DEFAULT_MODEL", DEFAULT_MODEL))
+    scope = WORKSPACE_DIR
+
+    prompt_file = Path(scope) / "prompts" / "orchestrator.md"
+    if prompt_file.is_file():
+        system_prompt = prompt_file.read_text().strip()
+    else:
+        system_prompt = _DEFAULT_SYSTEM_PROMPT
+
+    save_session({
+        "id": str(uuid.uuid4()),
+        "name": name,
+        "scope": scope,
+        "cwd": scope,
+        "model": model,
+        "system_prompt": system_prompt,
+        "status": "idle",
+        "session_id": None,
+        "cost_usd": 0,
+        "worktree_path": "",
+        "branch": "",
+        "is_orchestrator": 1,
+        "role": "orchestrator",
+        "color": "",
+        "created_at": datetime.now(timezone.utc).isoformat(),
+        "finished_at": None,
+        "backend_type": backend_for_model(model),
+    })
+    logger.info("Bootstrap: created default orchestrator '%s' (model=%s)", name, model)
diff --git a/app/main.py b/app/main.py
index b7de25ff4..4ec6a4952 100644
--- a/app/main.py
+++ b/app/main.py
@@ -11,40 +11,42 @@ from starlette.middleware.base import BaseHTTPMiddleware
 
 from app.auth import is_auth_enabled, validate_session, requires_auth, check_internal_token
 from app.db import init_db
 from app.deps import manager
 
 logger = logging.getLogger("orchestra")
 
 
 @asynccontextmanager
 async def lifespan(app: FastAPI):
     from dotenv import load_dotenv
     load_dotenv()
     init_db()
     from app.models import refresh_models
     await refresh_models()
     # YouGile sync fired from to_thread workers needs the app loop captured
     from app import tm as _tm_mod
     _tm_mod.set_main_loop(asyncio.get_running_loop())
     from app import tm_yougile  # noqa: F401 — registers tm sync hooks (on_task_synced, on_payment_changed)
     await manager.auto_resume_all()
+    from app.bootstrap import ensure_bootstrap
+    await ensure_bootstrap()
     manager.start_background_tasks()
     from app.bg_jobs import bg_manager
     bg_manager.set_session_manager(manager)
     await bg_manager.restore_from_db()
     from app.tg_bridge import start_bridge, stop_bridge
     await start_bridge(manager)
     from app.ssh_tunnel import start_tunnel, stop_tunnel
     await start_tunnel()
     from app.routes.system import _usage_snapshot_loop
     snapshot_task = asyncio.create_task(_usage_snapshot_loop())
     yield
     snapshot_task.cancel()
     await stop_tunnel()
     await stop_bridge()
     await bg_manager.shutdown()
     await manager.shutdown_all()
 
 
 app = FastAPI(title="Orchestra", lifespan=lifespan)
 app.mount("/static", StaticFiles(directory="app/static"), name="static")


## Later history of the touched files on main (after this commit)

74 later commits touch these paths; the first 40 (oldest first):
f1a5ba6e4 2026-06-13 remove proxy model fetching — enterprise-only feature, open source uses hardcoded MODELS dict
4fd783410 2026-06-13 Revert "#88: auto-bootstrap — ensure workspace + default orchestrator on startup"
a755646c6 2026-06-13 #91: client info page + proxy-only models + connection indicator
cbe4f00b0 2026-06-13 Revert "#91: client info page + proxy-only models + connection indicator"
79cc3fa0f 2026-06-13 #91: #91: client info page + proxy-only models + connection indicator
a1c89c427 2026-06-13 #88: restore auto-bootstrap (lost in revert)
e9f76b901 2026-06-13 #93: enterprise production hardening — skip tunnel/yougile, fix usage/proxy JS
f38cd69c7 2026-06-13 #94: auto-retry proxy + client modal improvements + refresh button
28fc89b2a 2026-06-14 #96: resolve ORCHESTRA_AGENT_UID name→uid + bootstrap as agent user
cb072944c 2026-06-14 fix: opencode.json gitignore + git config + file browser deny + user message dedup
ca56b761c 2026-06-14 #96: fix dubious ownership — git safe.directory for root + agent
12ae7a7ca 2026-06-14 #96: fix git init -b main + chmod a+rwX workspace for worktree ops
9a0a4fa47 2026-06-14 #96: runtime chmod worktrees/data — Docker volumes created as root, agent needs write
f21276a3d 2026-06-14 #96: mkdir worktree via gosu agent (root can't mkdir in agent-owned dirs)
ded9b9242 2026-06-14 fix: 6 UX issues — .claude gitignore, no reconnect for opencode, cost precision, dedup, tool truncate
dc3be906d 2026-06-30 fix: proxy persistence + hot-switch + lowercase env leak
ada728e9b 2026-07-01 fix(proxy): kill zombie ssh tunnels + dashboard status TTL
18d806139 2026-07-01 #4: #proxy-fix: force stable id='direct' for direct proxy
3ef921eac 2026-07-03 feat: full sub-agent telemetry — subagents table + transcript endpoints
2573942f9 2026-07-12 #rag-orchestra: RAG semantic memory (bge-m3 + sqlite-vec hybrid) ported from kesha
0c1804441 2026-07-17 refactor: make agent runtimes provider-agnostic
b6cabfdc5 2026-07-28 #adhoc-231036: gate orchestrator auto-compact by local window
0e15dcd31 2026-07-31 #108: #108: план правок по результатам аудита (фаза 2)
273e13db7 2026-08-03 #130: WIP: спасено оркестратором при исчерпании квоты Codex
2739e0b8d 2026-08-03 #9: версия в URL статики + правила кеширования
c6fe33c20 2026-08-03 #15 T3: TG-мост уходит с критического пути старта
1ade3ca25 2026-08-03 #16: #16: исследование RAG-узла — замер по живой БД, гипотеза о синхронном бэкфилле опровергнута
ef9c8057b 2026-08-04 #62: #62: фаза 1 — рабочие копии сносит pytest в главном чекауте, воспроизведено
a01a4b2aa 2026-08-13 #230: #230: план фазы 2 + красные оракулы T1-T5 (заглушки, 8 failed)
3b84786d9 2026-08-13 #269: state the restart pause on every response via X-Orchestra-Restarting
e55fb5bff 2026-08-13 #269: human refusal text and a durable inbox for messages that arrive during a restart
7c7c0de4b 2026-08-13 #269: drain the restart queue on every reopen, cap attempts, report undeliverable
b0b72d655 2026-08-16 #294: #294: plan secure artifact links
1e020d60e 2026-08-17 #311: #311: freeze durable delivery RED oracles
24d6308d4 2026-08-20 #197: #197: кеш последнего успешного ответа, джиттер ретраев, негативный кеш провайдера
b460149d4 2026-08-23 #379: #379: research socket restart failure
81a1c60f8 2026-08-24 #380: #380: research durable send acceptance
9f946a601 2026-08-24 #309: #309: freeze phase2 deletion oracles
4d58b176a 2026-08-24 refactor: remove OpenCode runtime
2fa666288 2026-08-24 #337: #337: add durable primary TG file receipts

## Patches of the first 8 later commits, restricted to the touched paths (each capped at 150 lines)

### f1a5ba6e4 remove proxy model fetching — enterprise-only feature, open source uses hardcoded MODELS dict

diff --git a/app/main.py b/app/main.py
index 4ec6a4952..71503bfe9 100644
--- a/app/main.py
+++ b/app/main.py
@@ -19,12 +19,10 @@ logger = logging.getLogger("orchestra")
 @asynccontextmanager
 async def lifespan(app: FastAPI):
     from dotenv import load_dotenv
     load_dotenv()
     init_db()
-    from app.models import refresh_models
-    await refresh_models()
     # YouGile sync fired from to_thread workers needs the app loop captured
     from app import tm as _tm_mod
     _tm_mod.set_main_loop(asyncio.get_running_loop())
     from app import tm_yougile  # noqa: F401 — registers tm sync hooks (on_task_synced, on_payment_changed)
     await manager.auto_resume_all()
### 4fd783410 Revert "#88: auto-bootstrap — ensure workspace + default orchestrator on startup"

diff --git a/app/bootstrap.py b/app/bootstrap.py
deleted file mode 100644
index 9e0b45c59..000000000
--- a/app/bootstrap.py
+++ /dev/null
@@ -1,97 +0,0 @@
-"""Auto-bootstrap: ensure workspace + default orchestrator on first startup."""
-
-import logging
-import os
-import subprocess
-import uuid
-from datetime import datetime, timezone
-from pathlib import Path
-
-from app.db import get_all_sessions, save_session
-from app.models import DEFAULT_MODEL, resolve_model, backend_for_model
-
-logger = logging.getLogger(__name__)
-
-WORKSPACE_DIR = "/workspace/project"
-
-_DEFAULT_CLAUDE_MD = """\
-# Project
-
-This workspace was auto-created by Orchestra.
-"""
-
-_DEFAULT_SYSTEM_PROMPT = (
-    "You are an AI orchestrator. Manage workers, delegate tasks, report results."
-)
-
-
-async def ensure_bootstrap() -> None:
-    """Idempotent bootstrap: workspace dir + default orchestrator DB record."""
-    _ensure_workspace()
-    _ensure_orchestrator()
-
-
-def _ensure_workspace() -> None:
-    ws = Path(WORKSPACE_DIR)
-    if ws.is_dir():
-        return
-
-    try:
-        ws.mkdir(parents=True, exist_ok=True)
-    except OSError as e:
-        logger.warning("Bootstrap: cannot create workspace %s: %s", WORKSPACE_DIR, e)
-        return
-
-    subprocess.run(["git", "init"], cwd=str(ws), capture_output=True)
-    (ws / "CLAUDE.md").write_text(_DEFAULT_CLAUDE_MD)
-    subprocess.run(
-        ["git", "add", "CLAUDE.md"],
-        cwd=str(ws), capture_output=True,
-    )
-    subprocess.run(
-        ["git", "commit", "-m", "bootstrap: init workspace"],
-        cwd=str(ws), capture_output=True,
-    )
-    logger.info("Bootstrap: created workspace %s", WORKSPACE_DIR)
-
-
-def _ensure_orchestrator() -> None:
-    sessions = get_all_sessions()
-    has_orch = any(
-        bool(s.get("is_orchestrator")) or s.get("role") == "orchestrator"
-        for s in sessions
-    )
-    if has_orch:
-        logger.info("Bootstrap: skipping, orchestrator exists")
-        return
-
-    name = os.environ.get("BOOTSTRAP_ORCH_NAME", "orchestrator")
-    model = resolve_model(os.environ.get("DEFAULT_MODEL", DEFAULT_MODEL))
-    scope = WORKSPACE_DIR
-
-    prompt_file = Path(scope) / "prompts" / "orchestrator.md"
-    if prompt_file.is_file():
-        system_prompt = prompt_file.read_text().strip()
-    else:
-        system_prompt = _DEFAULT_SYSTEM_PROMPT
-
-    save_session({
-        "id": str(uuid.uuid4()),
-        "name": name,
-        "scope": scope,
-        "cwd": scope,
-        "model": model,
-        "system_prompt": system_prompt,
-        "status": "idle",
-        "session_id": None,
-        "cost_usd": 0,
-        "worktree_path": "",
-        "branch": "",
-        "is_orchestrator": 1,
-        "role": "orchestrator",
-        "color": "",
-        "created_at": datetime.now(timezone.utc).isoformat(),
-        "finished_at": None,
-        "backend_type": backend_for_model(model),
-    })
-    logger.info("Bootstrap: created default orchestrator '%s' (model=%s)", name, model)
diff --git a/app/main.py b/app/main.py
index 71503bfe9..82ac11f61 100644
--- a/app/main.py
+++ b/app/main.py
@@ -24,12 +24,10 @@ async def lifespan(app: FastAPI):
     # YouGile sync fired from to_thread workers needs the app loop captured
     from app import tm as _tm_mod
     _tm_mod.set_main_loop(asyncio.get_running_loop())
     from app import tm_yougile  # noqa: F401 — registers tm sync hooks (on_task_synced, on_payment_changed)
     await manager.auto_resume_all()
-    from app.bootstrap import ensure_bootstrap
-    await ensure_bootstrap()
     manager.start_background_tasks()
     from app.bg_jobs import bg_manager
     bg_manager.set_session_manager(manager)
     await bg_manager.restore_from_db()
     from app.tg_bridge import start_bridge, stop_bridge
### a755646c6 #91: client info page + proxy-only models + connection indicator

diff --git a/app/main.py b/app/main.py
index 82ac11f61..b7de25ff4 100644
--- a/app/main.py
+++ b/app/main.py
@@ -19,10 +19,12 @@ logger = logging.getLogger("orchestra")
 @asynccontextmanager
 async def lifespan(app: FastAPI):
     from dotenv import load_dotenv
     load_dotenv()
     init_db()
+    from app.models import refresh_models
+    await refresh_models()
     # YouGile sync fired from to_thread workers needs the app loop captured
     from app import tm as _tm_mod
     _tm_mod.set_main_loop(asyncio.get_running_loop())
     from app import tm_yougile  # noqa: F401 — registers tm sync hooks (on_task_synced, on_payment_changed)
     await manager.auto_resume_all()
### cbe4f00b0 Revert "#91: client info page + proxy-only models + connection indicator"

diff --git a/app/main.py b/app/main.py
index b7de25ff4..82ac11f61 100644
--- a/app/main.py
+++ b/app/main.py
@@ -19,12 +19,10 @@ logger = logging.getLogger("orchestra")
 @asynccontextmanager
 async def lifespan(app: FastAPI):
     from dotenv import load_dotenv
     load_dotenv()
     init_db()
-    from app.models import refresh_models
-    await refresh_models()
     # YouGile sync fired from to_thread workers needs the app loop captured
     from app import tm as _tm_mod
     _tm_mod.set_main_loop(asyncio.get_running_loop())
     from app import tm_yougile  # noqa: F401 — registers tm sync hooks (on_task_synced, on_payment_changed)
     await manager.auto_resume_all()
### 79cc3fa0f #91: #91: client info page + proxy-only models + connection indicator

diff --git a/app/main.py b/app/main.py
index 82ac11f61..b7de25ff4 100644
--- a/app/main.py
+++ b/app/main.py
@@ -19,10 +19,12 @@ logger = logging.getLogger("orchestra")
 @asynccontextmanager
 async def lifespan(app: FastAPI):
     from dotenv import load_dotenv
     load_dotenv()
     init_db()
+    from app.models import refresh_models
+    await refresh_models()
     # YouGile sync fired from to_thread workers needs the app loop captured
     from app import tm as _tm_mod
     _tm_mod.set_main_loop(asyncio.get_running_loop())
     from app import tm_yougile  # noqa: F401 — registers tm sync hooks (on_task_synced, on_payment_changed)
     await manager.auto_resume_all()
### a1c89c427 #88: restore auto-bootstrap (lost in revert)

diff --git a/app/bootstrap.py b/app/bootstrap.py
new file mode 100644
index 000000000..9e0b45c59
--- /dev/null
+++ b/app/bootstrap.py
@@ -0,0 +1,97 @@
+"""Auto-bootstrap: ensure workspace + default orchestrator on first startup."""
+
+import logging
+import os
+import subprocess
+import uuid
+from datetime import datetime, timezone
+from pathlib import Path
+
+from app.db import get_all_sessions, save_session
+from app.models import DEFAULT_MODEL, resolve_model, backend_for_model
+
+logger = logging.getLogger(__name__)
+
+WORKSPACE_DIR = "/workspace/project"
+
+_DEFAULT_CLAUDE_MD = """\
+# Project
+
+This workspace was auto-created by Orchestra.
+"""
+
+_DEFAULT_SYSTEM_PROMPT = (
+    "You are an AI orchestrator. Manage workers, delegate tasks, report results."
+)
+
+
+async def ensure_bootstrap() -> None:
+    """Idempotent bootstrap: workspace dir + default orchestrator DB record."""
+    _ensure_workspace()
+    _ensure_orchestrator()
+
+
+def _ensure_workspace() -> None:
+    ws = Path(WORKSPACE_DIR)
+    if ws.is_dir():
+        return
+
+    try:
+        ws.mkdir(parents=True, exist_ok=True)
+    except OSError as e:
+        logger.warning("Bootstrap: cannot create workspace %s: %s", WORKSPACE_DIR, e)
+        return
+
+    subprocess.run(["git", "init"], cwd=str(ws), capture_output=True)
+    (ws / "CLAUDE.md").write_text(_DEFAULT_CLAUDE_MD)
+    subprocess.run(
+        ["git", "add", "CLAUDE.md"],
+        cwd=str(ws), capture_output=True,
+    )
+    subprocess.run(
+        ["git", "commit", "-m", "bootstrap: init workspace"],
+        cwd=str(ws), capture_output=True,
+    )
+    logger.info("Bootstrap: created workspace %s", WORKSPACE_DIR)
+
+
+def _ensure_orchestrator() -> None:
+    sessions = get_all_sessions()
+    has_orch = any(
+        bool(s.get("is_orchestrator")) or s.get("role") == "orchestrator"
+        for s in sessions
+    )
+    if has_orch:
+        logger.info("Bootstrap: skipping, orchestrator exists")
+        return
+
+    name = os.environ.get("BOOTSTRAP_ORCH_NAME", "orchestrator")
+    model = resolve_model(os.environ.get("DEFAULT_MODEL", DEFAULT_MODEL))
+    scope = WORKSPACE_DIR
+
+    prompt_file = Path(scope) / "prompts" / "orchestrator.md"
+    if prompt_file.is_file():
+        system_prompt = prompt_file.read_text().strip()
+    else:
+        system_prompt = _DEFAULT_SYSTEM_PROMPT
+
+    save_session({
+        "id": str(uuid.uuid4()),
+        "name": name,
+        "scope": scope,
+        "cwd": scope,
+        "model": model,
+        "system_prompt": system_prompt,
+        "status": "idle",
+        "session_id": None,
+        "cost_usd": 0,
+        "worktree_path": "",
+        "branch": "",
+        "is_orchestrator": 1,
+        "role": "orchestrator",
+        "color": "",
+        "created_at": datetime.now(timezone.utc).isoformat(),
+        "finished_at": None,
+        "backend_type": backend_for_model(model),
+    })
+    logger.info("Bootstrap: created default orchestrator '%s' (model=%s)", name, model)
diff --git a/app/main.py b/app/main.py
index b7de25ff4..4ec6a4952 100644
--- a/app/main.py
+++ b/app/main.py
@@ -26,10 +26,12 @@ async def lifespan(app: FastAPI):
     # YouGile sync fired from to_thread workers needs the app loop captured
     from app import tm as _tm_mod
     _tm_mod.set_main_loop(asyncio.get_running_loop())
     from app import tm_yougile  # noqa: F401 — registers tm sync hooks (on_task_synced, on_payment_changed)
     await manager.auto_resume_all()
+    from app.bootstrap import ensure_bootstrap
+    await ensure_bootstrap()
     manager.start_background_tasks()
     from app.bg_jobs import bg_manager
     bg_manager.set_session_manager(manager)
     await bg_manager.restore_from_db()
     from app.tg_bridge import start_bridge, stop_bridge
### e9f76b901 #93: enterprise production hardening — skip tunnel/yougile, fix usage/proxy JS

diff --git a/app/main.py b/app/main.py
index 4ec6a4952..25e0f2dd3 100644
--- a/app/main.py
+++ b/app/main.py
@@ -21,30 +21,34 @@ async def lifespan(app: FastAPI):
     from dotenv import load_dotenv
     load_dotenv()
     init_db()
     from app.models import refresh_models
     await refresh_models()
-    # YouGile sync fired from to_thread workers needs the app loop captured
     from app import tm as _tm_mod
     _tm_mod.set_main_loop(asyncio.get_running_loop())
-    from app import tm_yougile  # noqa: F401 — registers tm sync hooks (on_task_synced, on_payment_changed)
+    if not is_auth_enabled():
+        from app import tm_yougile  # noqa: F401 — registers tm sync hooks
     await manager.auto_resume_all()
     from app.bootstrap import ensure_bootstrap
     await ensure_bootstrap()
     manager.start_background_tasks()
     from app.bg_jobs import bg_manager
     bg_manager.set_session_manager(manager)
     await bg_manager.restore_from_db()
     from app.tg_bridge import start_bridge, stop_bridge
     await start_bridge(manager)
-    from app.ssh_tunnel import start_tunnel, stop_tunnel
-    await start_tunnel()
+    _tunnel_started = False
+    if not is_auth_enabled():
+        from app.ssh_tunnel import start_tunnel, stop_tunnel
+        await start_tunnel()
+        _tunnel_started = True
     from app.routes.system import _usage_snapshot_loop
     snapshot_task = asyncio.create_task(_usage_snapshot_loop())
     yield
     snapshot_task.cancel()
-    await stop_tunnel()
+    if _tunnel_started:
+        await stop_tunnel()
     await stop_bridge()
     await bg_manager.shutdown()
     await manager.shutdown_all()
 
 
### f38cd69c7 #94: auto-retry proxy + client modal improvements + refresh button

diff --git a/app/main.py b/app/main.py
index 25e0f2dd3..f218a9d81 100644
--- a/app/main.py
+++ b/app/main.py
@@ -19,12 +19,21 @@ logger = logging.getLogger("orchestra")
 @asynccontextmanager
 async def lifespan(app: FastAPI):
     from dotenv import load_dotenv
     load_dotenv()
     init_db()
-    from app.models import refresh_models
+    from app.models import refresh_models, is_proxy_connected
     await refresh_models()
+    if is_auth_enabled() and not is_proxy_connected():
+        async def _proxy_retry_loop():
+            while not is_proxy_connected():
+                await asyncio.sleep(60)
+                await refresh_models()
+                if is_proxy_connected():
+                    logger.info("Proxy reconnected, models loaded")
+                    break
+        asyncio.create_task(_proxy_retry_loop())
     from app import tm as _tm_mod
     _tm_mod.set_main_loop(asyncio.get_running_loop())
     if not is_auth_enabled():
         from app import tm_yougile  # noqa: F401 — registers tm sync hooks
     await manager.auto_resume_all()