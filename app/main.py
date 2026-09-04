"""Orchestra — AI Agent Orchestrator. App factory: lifespan, middleware, routers."""

import asyncio
import logging
import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from urllib.parse import parse_qs, quote

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.gzip import GZipMiddleware

from app.auth import is_auth_enabled, validate_session, requires_auth, check_internal_token
from app.db import init_db

from app import fdstore as _fdstore
_fdstore.seal_activation_fds()

from app.deps import manager
from app.initial_deliveries import recover_initial_deliveries
from app.message_deliveries import recover_message_deliveries
from app import restart_guard

logger = logging.getLogger("orchestra")
# Uvicorn настраивает только свои логгеры, рутовый остаётся без хендлера → всё, что Orchestra
# пишет на INFO, съедает lastResort (WARNING). Так пропадал весь жизненный цикл RAG-бэкфилла,
# из-за чего баг «память отдаёт устаревший файл» с 26.07 висел недоказуемым (#16).
if not logger.handlers:
    logger.addHandler(logging.StreamHandler())
    logger.setLevel(logging.INFO)
# И для пакета целиком. Модули пишут в ``logging.getLogger(__name__)`` — это "app.workspace",
# "app.session" и т.д., а они НЕ потомки "orchestra": настройка одного этого имени оставила
# весь пакет немым ниже WARNING. Именно поэтому удаление рабочих копий 03.08 не оставило в
# журнале ни строчки (#62). Настраиваем корень пакета, чтобы СЛЕДУЮЩИЙ модуль был слышен
# по умолчанию, а не попал в ту же ловушку.
_app_logger = logging.getLogger("app")
if not _app_logger.handlers:
    _app_logger.addHandler(logging.StreamHandler())
    _app_logger.setLevel(logging.INFO)


async def _start_bridge_background(manager) -> None:
    """Поднять TG-мост вне критического пути старта.

    Отказ обязан быть громким: мост, умерший молча, заметят через часы по отсутствию
    сообщений, а не по логу.
    """
    logger.info("TG bridge: starting in background (HTTP is already serving)")
    try:
        from app import tg_bridge
        await tg_bridge.start_bridge(manager)
        if tg_bridge.bot is not None:
            from app.tg_file_deliveries import start_file_delivery_service
            await start_file_delivery_service()
        logger.info("TG bridge: ready")
    except asyncio.CancelledError:
        raise
    except Exception as e:
        logger.error(f"TG bridge FAILED to start: {type(e).__name__}: {e}", exc_info=True)


# Кнопка рестарта — абсолютная команда, а не заявка (решение юзера 28.08.2026). Раньше здесь
# стояло 120 с ожидания мутаций, и рестарт ОТМЕНЯЛСЯ, если не дождался: нажатие не делало
# ничего. Ждать нельзя ни секунды — незавершённая мутация теряет свой ответ, и это принятая
# цена: агент переспросит, а юзер, нажавший кнопку, обязан получить рестарт.
MUTATING_DRAIN_BUDGET_S = 0.0
DRAIN_POLL_S = 0.05

#: Restart cannot count its own request, and an operator must retain the stop lever while
#: restart admission is closed. Neither endpoint joins the mutating census.
_CENSUS_EXEMPT_PATHS = frozenset({
    "/api/restart",
    "/api/sessions/{name}/stop",
})
#: Read-only by verb, but stated explicitly so a mutating GET can be added here instead of
#: being silently misclassified. Empty today; the list is the seam, not the emptiness.
_MUTATING_READ_METHODS: frozenset[str] = frozenset()

_READ_ONLY_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
_inflight_mutating = 0
_inflight_streams = 0
_mutating_admission_open = True
_restart_inbox_drain: "asyncio.Task | None" = None
_restart_failure = ""
_PROCESS_GENERATION = uuid.uuid4().hex
_PROCESS_STARTED_AT = datetime.now(timezone.utc).isoformat(timespec="seconds")


def clear_restart_failure() -> None:
    global _restart_failure
    _restart_failure = ""


def note_restart_failure(reason: str) -> None:
    global _restart_failure
    _restart_failure = str(reason)


def restart_failure_header() -> str:
    return quote(_restart_failure, safe="")


def _known_api_paths() -> set[str]:
    return {
        route.path for route in app.routes
        if getattr(route, "path", "").startswith("/api/")
    }


def _resolve_route_template(path: str) -> str | None:
    """Concrete request path -> its registered template, or None if nothing matches.

    The middleware sees `/api/sessions/foo/send`; the route table holds
    `/api/sessions/{name}/send`. Comparing them directly (which the first version of this
    classifier did) made EVERY parameterised route "unknown", hence mutating — so ordinary
    dashboard GETs would have held the drain and been refused during a restart. Found by the
    pre-mortem, not by the oracle, because the oracle passes templates in directly.
    """
    if path in _known_api_paths():
        return path
    for route in app.routes:
        regex = getattr(route, "path_regex", None)
        if regex is not None and regex.match(path):
            return route.path
    return None


def is_mutating_path(method: str, path: str) -> bool:
    """Classify a request against the app's OWN route table (#230 T6).

    Fail-closed: an unknown path counts as mutating, because "unknown" means "I do not know
    what this does", not "safe". The verb alone is never the criterion — `/api/restart` is a
    POST that must not be counted, and a mutating GET can be declared in
    `_MUTATING_READ_METHODS`.
    """
    if path in _CENSUS_EXEMPT_PATHS:
        return False
    method = method.upper()
    template = _resolve_route_template(path)
    if template is None:
        return True
    if template in _CENSUS_EXEMPT_PATHS:
        return False
    if template in _MUTATING_READ_METHODS:
        return True
    return method not in _READ_ONLY_METHODS


def inflight_mutating_count() -> int:
    return _inflight_mutating


def inflight_stream_count() -> int:
    return _inflight_streams


def close_mutating_admission() -> None:
    """Stop accepting NEW mutating calls; refused before its side effect, a call is retryable."""
    global _mutating_admission_open
    _mutating_admission_open = False


def open_mutating_admission() -> None:
    global _mutating_admission_open
    was_closed = not _mutating_admission_open
    _mutating_admission_open = True
    # The queue is owed to the gate, not to the process: a restart that never happened
    # (preflight refused, watchdog, failed restart path) reopens admission and keeps running,
    # and the message we promised to deliver would wait for the next real start (#269 B1).
    # Hooked on the transition, so the reopen-on-an-open-gate calls stay free.
    if was_closed:
        schedule_restart_inbox_drain()


def schedule_restart_inbox_drain() -> None:
    """Drain the restart queue in the background, at most one drain at a time."""
    global _restart_inbox_drain
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return  # no loop to schedule onto — nothing was queued in this process either
    if _restart_inbox_drain is not None and not _restart_inbox_drain.done():
        return
    from app import restart_inbox

    _restart_inbox_drain = asyncio.create_task(restart_inbox.deliver_pending(manager))
    _restart_inbox_drain.add_done_callback(_log_restart_inbox_drain)


def _log_restart_inbox_drain(task: "asyncio.Task") -> None:
    """A task nobody awaits swallows its exception until GC. Say it out loud instead."""
    if task.cancelled():
        return
    error = task.exception()
    if error is not None:
        logger.error("restart inbox drain failed: %s: %s", type(error).__name__, error)


def mutating_admission_open() -> bool:
    """Public reader for the gate. In-process senders (the TG bridge) never touch HTTP, so
    the middleware cannot protect them — they have to ask (#269)."""
    return _mutating_admission_open


def mutating_admission_verdict(method: str, path: str) -> dict:
    if not is_mutating_path(method, path) or _mutating_admission_open:
        return {"allowed": True, "retryable": False, "outcome_unknown": False}
    # It never started, so a retry is honest and the outcome is known: nothing happened.
    return {
        "allowed": False,
        "retryable": True,
        "outcome_unknown": False,
        "code": "restart_pending",
        # Human sentence, not a status line: this is what a person reads when a channel shows
        # the body verbatim (that is exactly how the raw JSON reached the user, #269). Machines
        # read `code`/`retryable` above; people need "nothing broke" and "what now".
        "message": "Orchestra перезапускается — сообщение не отправлено, ничего не сломалось. "
                   "Повтори через минуту, я вернусь сам.",
    }


class RequestCensusMiddleware:
    """Counts in-flight mutating requests and long-lived streams (#230 T6).

    Pure ASGI, not BaseHTTPMiddleware, because the count must survive until the response BODY
    is finished — that is the whole point for streams. A request is reclassified as a stream
    the moment its response declares `text/event-stream`: SSE never reaches zero, so it must
    never hold the drain.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        global _inflight_mutating, _inflight_streams
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method, path = scope.get("method", "GET"), scope.get("path", "")
        verdict = mutating_admission_verdict(method, path)
        if not verdict["allowed"]:
            from starlette.responses import JSONResponse
            # This branch answers WITHOUT reaching send_wrapper below, so it needs the header of
            # its own — a client that only saw the refusal would never learn the pause is over.
            response = JSONResponse(
                {"error": verdict}, status_code=503,
                headers={
                    "X-Orchestra-Restarting": "1",
                    "X-Orchestra-Restart-Error": restart_failure_header(),
                    "X-Orchestra-Generation": _PROCESS_GENERATION,
                    "X-Orchestra-Started-At": _PROCESS_STARTED_AT,
                },
            )
            await response(scope, receive, send)
            return

        counted_mutating = is_mutating_path(method, path)
        counted_stream = False
        if counted_mutating:
            _inflight_mutating += 1

        async def send_wrapper(message):
            nonlocal counted_mutating, counted_stream
            global _inflight_mutating, _inflight_streams
            if message["type"] == "http.response.start":
                # On EVERY response, both values: a header that only ever says "1" cannot tell a
                # client the pause ended, and a restart that never happens reopens admission
                # silently (`restart_preflight`). Reading one bool costs nothing on the hot path.
                message["headers"] = [
                    *(message.get("headers") or []),
                    (b"x-orchestra-restarting", b"0" if _mutating_admission_open else b"1"),
                    (b"x-orchestra-restart-error", restart_failure_header().encode("ascii")),
                    (b"x-orchestra-generation", _PROCESS_GENERATION.encode("ascii")),
                    (b"x-orchestra-started-at", _PROCESS_STARTED_AT.encode("ascii")),
                ]
                headers = {k.lower(): v for k, v in message.get("headers") or []}
                if headers.get(b"content-type", b"").startswith(b"text/event-stream"):
                    if counted_mutating:
                        _inflight_mutating -= 1
                        counted_mutating = False
                    _inflight_streams += 1
                    counted_stream = True
            elif message["type"] == "http.response.body" and not message.get("more_body"):
                if counted_mutating:
                    _inflight_mutating -= 1
                    counted_mutating = False
                if counted_stream:
                    _inflight_streams -= 1
                    counted_stream = False
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            if counted_mutating:
                _inflight_mutating -= 1
            if counted_stream:
                _inflight_streams -= 1


async def drain_mutating_requests(budget_s: float = MUTATING_DRAIN_BUDGET_S) -> bool:
    """Wait for accepted mutating calls. False = budget expired, so refuse the restart.

    Measured (.orchestra/tasks/230/plan.md, falsifier 2): a gracefully drained request keeps its
    response, while an instant restart commits the side effect and loses the answer — the agent
    then sees a tool call whose outcome is unknown. Streams are never waited for: they do not
    end. Budget default is above the slowest mutating call ever measured here (90.2s).
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + budget_s
    while loop.time() < deadline:
        if inflight_mutating_count() == 0:
            return True
        await asyncio.sleep(DRAIN_POLL_S)
    return inflight_mutating_count() == 0


async def _shutdown_runtime(
    restart_inbox_drain: "asyncio.Task | None",
    snapshot_task: asyncio.Task,
    bridge_task: asyncio.Task,
    projection_repair_task: "asyncio.Task | None",
    portfolio_watchdog_task: "asyncio.Task | None",
) -> None:
    startup_tasks = {
        task for task in (
            restart_inbox_drain,
            snapshot_task,
            projection_repair_task,
            portfolio_watchdog_task,
        )
        if task is not None and not task.done()
    }
    for task in startup_tasks:
        task.cancel()
    if startup_tasks:
        await asyncio.gather(*startup_tasks, return_exceptions=True)

    from app.merge_operations import shutdown_merge_operations
    restart_guard.note_shutdown_phase("merge_operations", "shutdown_merge_operations")
    await shutdown_merge_operations()

    from app import rag_service
    restart_guard.note_shutdown_phase("rag", "rag_service.shutdown")
    rag_service.shutdown()

    from app.tg_file_deliveries import shutdown_file_delivery_service
    restart_guard.note_shutdown_phase(
        "tg_file_deliveries", "shutdown_file_delivery_service"
    )
    await shutdown_file_delivery_service()

    bridge_task.cancel()
    restart_guard.note_shutdown_phase("bridge_task", "asyncio.Task[bridge]")
    try:
        await bridge_task
    except (asyncio.CancelledError, Exception):
        pass

    from app.tg_bridge import stop_bridge
    restart_guard.note_shutdown_phase("tg_bridge", "stop_bridge")
    await stop_bridge()

    from app.limits_card import shutdown_renderer
    restart_guard.note_shutdown_phase("limits_renderer", "limits_card.shutdown_renderer")
    await shutdown_renderer()

    from app.bg_jobs import bg_manager
    restart_guard.note_shutdown_phase("bg_jobs", "BgJobManager.shutdown")
    await bg_manager.shutdown()

    restart_guard.note_shutdown_phase("session_handoff", "SessionManager.shutdown_all")
    await manager.shutdown_all()
    restart_guard.note_shutdown_phase(
        "application_teardown_complete",
        "post_lifespan_runtime",
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    from dotenv import load_dotenv
    load_dotenv()
    from app.session import validate_auto_compact_window_config
    validate_auto_compact_window_config()
    init_db()
    from app.orchestra_layout import migrate_registered_project_layouts
    layout_migrations = migrate_registered_project_layouts()
    app.state.layout_migrations = layout_migrations
    for project_id, result in layout_migrations.items():
        if result.get("status") == "failed":
            logger.error(
                "project layout migration failed: project=%s code=%s error=%s",
                project_id,
                result.get("code", "ORCHESTRA_LAYOUT_GIT_ERROR"),
                result.get("error", "unknown migration error"),
            )
    from app.ia.runtime import knowledge_runtime_mode, production_runtime_config
    with knowledge_runtime_mode(production_runtime_config()) as knowledge_owner:
        app.state.knowledge_runtime = knowledge_owner
        from app.artifacts import cleanup_expired
        cleanup_expired()
        from app.models import refresh_models, is_proxy_connected
        await refresh_models()
        if is_auth_enabled() and not is_proxy_connected():
            async def _proxy_retry_loop():
                while not is_proxy_connected():
                    await asyncio.sleep(60)
                    await refresh_models()
                    if is_proxy_connected():
                        logger.info("Proxy reconnected, models loaded")
                        break
            asyncio.create_task(_proxy_retry_loop())
        await manager.auto_resume_all()
        from app.routes.tg import resume_dashboard_voice_transcriptions
        await resume_dashboard_voice_transcriptions()
        await recover_initial_deliveries()
        await recover_message_deliveries()
        from app.fan_barrier import recover_deadlines
        recover_deadlines()
        # #230 T7: descriptors that came back for sessions nobody owns any more.
        # Fail-closed inside: an EMPTY registry sweeps nothing.
        swept = await manager.sweep_orphan_fds()
        if swept:
            logger.warning('orphan sweep closed pipes of %d unknown session(s)', swept)
        from app.bootstrap import ensure_bootstrap
        await ensure_bootstrap()
        manager.start_background_tasks()
        # #269: messages accepted while the previous process was restarting. In the background —
        # a delivery runs the agent's turn, and startup must not wait for it.
        schedule_restart_inbox_drain()
        from app.bg_jobs import bg_manager
        bg_manager.set_session_manager(manager)
        await bg_manager.restore_from_db()
        # TG-мост поднимаем фоном. Замер (.orchestra/tasks/15/research.md): один только импорт
        # app.tg_bridge стоит 4.05 с, из них 3.72 с — aiogram, и всё это время uvicorn не
        # принимает запросы, а nginx отдаёт 502. Старт сервиса был 4.3-13.9 с; для приёма
        # HTTP мост не нужен. Плата: polling TG стартует на несколько секунд позже, и команда
        # из TG в это окно выполнится с задержкой (Telegram её не теряет).
        bridge_task = asyncio.create_task(_start_bridge_background(manager))
        from app.routes.system import _usage_snapshot_loop
        snapshot_task = asyncio.create_task(_usage_snapshot_loop())
        from app.portfolio_watchdog import ensure_task as ensure_portfolio_watchdog
        portfolio_watchdog_task = ensure_portfolio_watchdog(app)
        from app.runaway_guard import ensure_task as ensure_runaway_guard
        ensure_runaway_guard(app)
        from app import rag_service
        if rag_service.is_enabled():
            rag_service.initialize()
        from app.merge_operations import restore_merge_operations
        await restore_merge_operations()
        if _fdstore.notify_ready():
            logger.info("systemd readiness published after application startup gates")
        projection_repair_task = knowledge_owner.schedule_projection_repair()
        yield
    await _shutdown_runtime(
        _restart_inbox_drain,
        snapshot_task,
        bridge_task,
        projection_repair_task,
        portfolio_watchdog_task,
    )
    if getattr(app.state, "portfolio_watchdog_task", None) is portfolio_watchdog_task:
        app.state.portfolio_watchdog_task = None


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
from app.routes.sessions import router as sessions_router
from app.routes.system import router as system_router
from app.routes.tg import router as tg_router
from app.routes.subagent import router as subagent_router
from app.routes.memory import router as memory_router
from app.routes.knowledge import router as knowledge_router
from app.routes.merge_operations import router as merge_operations_router
from app.routes.artifacts import router as artifacts_router
from app.routes.portfolio import router as portfolio_router
app.include_router(tm_router)
app.include_router(bg_router)
app.include_router(sessions_router)
app.include_router(system_router)
app.include_router(tg_router)
app.include_router(subagent_router)
app.include_router(memory_router)
app.include_router(knowledge_router)
app.include_router(merge_operations_router)
app.include_router(artifacts_router)
app.include_router(portfolio_router)


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


app.add_middleware(RequestCensusMiddleware)
app.add_middleware(AuthMiddleware)
# Статика первой загрузки — 814 КБ против 68 КБ у всех API вместе (#197). Отдавалась
# несжатой: `curl --compressed` возвращал те же 434 627 байт для app.js. gzip даёт 3.7×
# (814 -> 221 КБ), а на канале с ~17% потерь вчетверо меньше байт — это ещё и вчетверо
# меньше шансов поймать обрыв посреди передачи.
# Добавлен ПОСЛЕДНИМ, а значит стоит САМЫМ ВНЕШНИМ (add_middleware делает insert(0)).
# Так и надо: gzip придерживает кадр `http.response.start` до первого куска тела, а
# RequestCensusMiddleware именно на этом кадре читает `content-type`, чтобы отличить
# поток от обычного ответа. Стой gzip внутри — счётчик дренажа узнавал бы о потоке с
# опозданием. Снаружи он сжимает уже посчитанный ответ и ничего не сдвигает.
# SSE не сжимается: DEFAULT_EXCLUDED_CONTENT_TYPES в Starlette 1.1.0 — ('text/event-stream',).
app.add_middleware(GZipMiddleware, minimum_size=1024)
