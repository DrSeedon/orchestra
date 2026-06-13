"""Orchestra — AI Agent Orchestrator. App factory: lifespan, middleware, routers."""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from app.auth import is_auth_enabled, validate_session, requires_auth, check_internal_token
from app.db import init_db
from app.deps import manager

logger = logging.getLogger("orchestra")


@asynccontextmanager
async def lifespan(app: FastAPI):
    from dotenv import load_dotenv
    load_dotenv()
    init_db()
    # YouGile sync fired from to_thread workers needs the app loop captured
    from app import tm as _tm_mod
    _tm_mod.set_main_loop(asyncio.get_running_loop())
    from app import tm_yougile  # noqa: F401 — registers tm sync hooks (on_task_synced, on_payment_changed)
    await manager.auto_resume_all()
    from app.bootstrap import ensure_bootstrap
    await ensure_bootstrap()
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

from app.routes.tm import router as tm_router
from app.routes.bg import router as bg_router
from app.routes.proxy import router as proxy_router
from app.routes.sessions import router as sessions_router
from app.routes.system import router as system_router
from app.routes.tg import router as tg_router
app.include_router(tm_router)
app.include_router(bg_router)
app.include_router(proxy_router)
app.include_router(sessions_router)
app.include_router(system_router)
app.include_router(tg_router)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    import traceback
    tb = traceback.format_exc()
    logger.error(f"Unhandled exception on {request.method} {request.url.path}: {exc}\n{tb}")
    return JSONResponse({"error": f"Internal: {exc}"}, status_code=500)


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        method = request.method
        # Internal token bypasses cookie auth — allows MCP subprocess and workers
        # to call the API without a browser session
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
