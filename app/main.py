"""Orchestra — AI Agent Orchestrator. App factory: lifespan, middleware, routers."""

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from urllib.parse import parse_qs

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from app.auth import is_auth_enabled, validate_session, requires_auth, check_internal_token
from app.db import init_db
from app.deps import manager

logger = logging.getLogger("orchestra")
# Uvicorn настраивает только свои логгеры, рутовый остаётся без хендлера → всё, что Orchestra
# пишет на INFO, съедает lastResort (WARNING). Так пропадал весь жизненный цикл RAG-бэкфилла,
# из-за чего баг «память отдаёт устаревший файл» с 26.07 висел недоказуемым (#16).
if not logger.handlers:
    logger.addHandler(logging.StreamHandler())
    logger.setLevel(logging.INFO)


async def _start_bridge_background(manager) -> None:
    """Поднять TG-мост вне критического пути старта.

    Отказ обязан быть громким: мост, умерший молча, заметят через часы по отсутствию
    сообщений, а не по логу.
    """
    logger.info("TG bridge: starting in background (HTTP is already serving)")
    try:
        from app.tg_bridge import start_bridge
        await start_bridge(manager)
        logger.info("TG bridge: ready")
    except asyncio.CancelledError:
        raise
    except Exception as e:
        logger.error(f"TG bridge FAILED to start: {type(e).__name__}: {e}", exc_info=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    from dotenv import load_dotenv
    load_dotenv()
    from app.session import validate_auto_compact_window_config
    validate_auto_compact_window_config()
    init_db()
    _tunnel_started = False
    if not is_auth_enabled():
        # Model discovery may itself use a local SSH-forward from .env. Start those
        # routes before the first proxy request instead of waiting 60s for recovery.
        from app.ssh_tunnel import start_tunnel, stop_tunnel
        await start_tunnel()
        _tunnel_started = True
    from app.models import refresh_models, is_proxy_connected
    custom_model_endpoint = bool(
        os.environ.get("ANTHROPIC_BASE_URL") or os.environ.get("UPSTREAM_API")
    )
    attempts = 5 if _tunnel_started and custom_model_endpoint else 1
    for attempt in range(attempts):
        await refresh_models()
        if is_proxy_connected() or attempt == attempts - 1:
            break
        await asyncio.sleep(1)
    if is_auth_enabled() and not is_proxy_connected():
        async def _proxy_retry_loop():
            while not is_proxy_connected():
                await asyncio.sleep(60)
                await refresh_models()
                if is_proxy_connected():
                    logger.info("Proxy reconnected, models loaded")
                    break
        asyncio.create_task(_proxy_retry_loop())
    from app import tm as _tm_mod
    _tm_mod.set_main_loop(asyncio.get_running_loop())
    if not is_auth_enabled():
        from app import tm_yougile  # noqa: F401 — registers tm sync hooks
    await manager.auto_resume_all()
    from app.bootstrap import ensure_bootstrap
    await ensure_bootstrap()
    manager.start_background_tasks()
    from app.bg_jobs import bg_manager
    bg_manager.set_session_manager(manager)
    await bg_manager.restore_from_db()
    # TG-мост поднимаем фоном. Замер (docs/tasks/15/research.md): один только импорт
    # app.tg_bridge стоит 4.05 с, из них 3.72 с — aiogram, и всё это время uvicorn не
    # принимает запросы, а nginx отдаёт 502. Старт сервиса был 4.3-13.9 с; для приёма
    # HTTP мост не нужен. Плата: polling TG стартует на несколько секунд позже, и команда
    # из TG в это окно выполнится с задержкой (Telegram её не теряет).
    bridge_task = asyncio.create_task(_start_bridge_background(manager))
    from app.routes.system import _usage_snapshot_loop
    snapshot_task = asyncio.create_task(_usage_snapshot_loop())
    from app import rag_service
    if rag_service.is_enabled():
        rag_service.initialize()
    from app.merge_operations import restore_merge_operations
    await restore_merge_operations()
    yield
    snapshot_task.cancel()
    from app import rag_service as _rs
    from app.merge_operations import shutdown_merge_operations
    await shutdown_merge_operations()
    _rs.shutdown()
    if _tunnel_started:
        await stop_tunnel()
    # Мост мог ещё не подняться — гасим задачу и только потом просим его остановиться
    bridge_task.cancel()
    try:
        await bridge_task
    except (asyncio.CancelledError, Exception):
        pass
    from app.tg_bridge import stop_bridge
    await stop_bridge()
    await bg_manager.shutdown()
    await manager.shutdown_all()


class VersionedStatic(StaticFiles):
    """Есть ?v= в URL → кешируем навсегда, нет → обязательная ревалидация.

    Версию проставляет static_url() из app/deps.py. Ошибиться здесь можно только
    в безопасную сторону: забыли версию — юзер платит лишним 304, а не сидит
    неделю со старым кодом, как было без Cache-Control вовсе (задача #9).
    """

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        # Только 200: закешировать навечно 404 по версионному URL — значит спрятать
        # файл от юзера до конца жизни профиля браузера
        versioned = b"v" in parse_qs(scope.get("query_string", b""))
        response.headers["Cache-Control"] = (
            "public, max-age=31536000, immutable"
            if versioned and response.status_code == 200
            else "no-cache"
        )
        return response


app = FastAPI(title="Orchestra", lifespan=lifespan)
app.mount("/static", VersionedStatic(directory="app/static"), name="static")

from app.routes.tm import router as tm_router
from app.routes.bg import router as bg_router
from app.routes.proxy import router as proxy_router
from app.routes.sessions import router as sessions_router
from app.routes.system import router as system_router
from app.routes.tg import router as tg_router
from app.routes.subagent import router as subagent_router
from app.routes.memory import router as memory_router
from app.routes.merge_operations import router as merge_operations_router
app.include_router(tm_router)
app.include_router(bg_router)
app.include_router(proxy_router)
app.include_router(sessions_router)
app.include_router(system_router)
app.include_router(tg_router)
app.include_router(subagent_router)
app.include_router(memory_router)
app.include_router(merge_operations_router)


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
        parts = path.split("/")
        if (
            method == "POST"
            and len(parts) == 5
            and parts[1:3] == ["api", "sessions"]
            and parts[3]
            and parts[4] == "merge"
        ):
            error = {
                "code": "MERGE_OPERATION_REQUIRED",
                "message": (
                    "Legacy merge endpoint is disabled; use merge operation-v1. "
                    "No Git mutation was started."
                ),
                "status": 426,
                "retryable": False,
                "request_id": request.headers.get("X-Request-ID") or None,
                "retry_after_seconds": None,
                "outcome_unknown": False,
                "details": {"capability": "operation-v1"},
            }
            return JSONResponse({"result": None, "error": error}, status_code=426)
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
