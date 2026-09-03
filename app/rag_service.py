"""RAG service — singleton wrapper around app.rag for the main FastAPI process.

Owns the embedder (946MB, ONE per Orchestra — NEVER in the MCP subprocess: 946MB × N workers
= OOM) and the write/read ThreadPoolExecutors. All access goes through async methods that
route to the right executor (search → read, index/backfill → write).

Feature-flagged by RAG_ENABLED — when off, `is_enabled()` is False and nothing is loaded,
so Orchestra runs without the optional `[rag]` deps (fastembed/sqlite-vec/onnxruntime).
"""

import asyncio
import time
import logging
import os
from pathlib import Path

logger = logging.getLogger("orchestra.rag_service")

_RAG_ENABLED = os.environ.get("RAG_ENABLED", "false").lower() == "true"
_DB_PATH = Path(os.environ.get("RAG_DB_PATH", "data/vec.db"))
# orchestra.db — source of agent logs to index. Same DB Orchestra uses for sessions/logs.
_ORCHESTRA_DB = Path(os.environ.get("ORCHESTRA_DB_PATH", "data/orchestra.db"))

_write_executor = None
_read_executor = None
_initialized = False
_backfill_tasks: dict[str, asyncio.Task[None]] = {}
_backfill_dirty: set[str] = set()
_last_pending: dict[str, int] = {}  # scope → файлов в долге по последнему прогону ЭТОГО scope

# Размеры срезов: работа обязана переживать рестарт, а не влезать в него целиком.
# Прогресс фиксируется на КАЖДОМ файле/логе (коммит внутри index_*), поэтому срез задаёт не
# цену обрыва, а частоту чередования слоёв и проверки бюджета. Замер на боевом корпусе:
# крупный .orchestra/tasks/*.md стоит десятки секунд, отсюда 5, а не 25.
_FILE_SLICE = 5
_LOG_SLICE = 100
_PASS_BUDGET_SECONDS = 300.0


def is_enabled() -> bool:
    return _RAG_ENABLED


def is_ready() -> bool:
    return _RAG_ENABLED and _initialized


def initialize() -> bool:
    """Create embedder-owning executors + wire app.rag. Idempotent. No-op if RAG disabled.
    Called from main.py lifespan. Model loads lazily on first embed (not here) — keeps startup fast."""
    global _write_executor, _read_executor, _initialized
    if not _RAG_ENABLED or _initialized:
        return _initialized
    try:
        from concurrent.futures import ThreadPoolExecutor

        from app import rag
    except Exception as e:  # optional deps missing but RAG_ENABLED=true → fail loud, don't crash app
        logger.error(f"RAG_ENABLED but deps unavailable: {e}. Install `orchestra[rag]`. RAG disabled.")
        return False
    # HF offline: model is pre-cached in data/models/ (Contabo proxy blocks HuggingFace).
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    models_dir = Path("data/models")
    if models_dir.is_dir():
        os.environ.setdefault("FASTEMBED_CACHE_PATH", str(models_dir.resolve()))
    # nice the write-executor (backfill/index) so heavy reindex stays background-quiet.
    # read-executor (search, user-facing) keeps normal priority.
    def _nice_init():
        if rag.RAG_NICE > 0:
            try:
                os.nice(rag.RAG_NICE)
            except OSError:
                pass  # nice may be restricted in some sandboxes — thread-cap still applies
    _write_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="rag-w",
                                         initializer=_nice_init)
    _read_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="rag-r")
    rag.set_executor(_write_executor, _read_executor, db_path=_DB_PATH)
    _initialized = True
    logger.info(f"RAG service initialized (db={_DB_PATH})")
    return True


def shutdown() -> None:
    global _write_executor, _read_executor, _initialized
    _last_pending.clear()
    scheduled = tuple(_backfill_tasks.values())
    for task in scheduled:
        if not task.done():
            task.cancel()
    _backfill_tasks.clear()
    _backfill_dirty.clear()
    if scheduled:
        logger.info(
            "RAG scheduler cancelled %d wrapper task(s); executor work already running may continue",
            len(scheduled),
        )
    if _write_executor:
        _write_executor.shutdown(wait=False)
    if _read_executor:
        _read_executor.shutdown(wait=False)
    _write_executor = _read_executor = None
    _initialized = False


class SearchBusy(RuntimeError):
    """Очередь поиска забита: новую заявку не принимаем, она всё равно опоздает."""


# Дедлайн серверной стороны. Считается от ПРИХОДА запроса, а не от чего-либо присланного
# клиентом: клиентское значение — это чужой ввод, и синхронизировать их лишним полем в API
# нельзя (окно рассинхрона MCP↔роут, MCP обновляется мгновенно, роуты — до рестарта).
SEARCH_DEADLINE_S = 5.0
# Потолок очереди = пропускная способность × дедлайн: 6.5 запросов/с × 5 с ≈ 32. Заявка
# номер 33 физически не успеет — принимать её значит гарантированно потратить единственный
# поток впустую. Обе цифры из замера 03.08.2026:
# .orchestra/tasks/18/measurements/search-latency-p{1,2,4,8}.log (потолок 6.5 запр/с не растёт с
# числом клиентов — сериализация на max_workers=1). Меняется железо или размер индекса —
# ПЕРЕМЕРЯЙ, а не подкручивай на глаз.
SEARCH_QUEUE_MAX = 32
_search_queued = 0


async def search(project: str, query: str, limit: int = 5, cross_project: bool = False,
                 kinds: tuple | None = None) -> list[dict]:
    """Semantic search in the read-executor (RO conn, concurrent with backfill)."""
    global _search_queued
    if not _initialized:
        raise RuntimeError("RAG not initialized")
    from app import rag
    if _search_queued >= SEARCH_QUEUE_MAX:
        raise SearchBusy(f"search queue full ({_search_queued}/{SEARCH_QUEUE_MAX})")
    loop = asyncio.get_running_loop()
    deadline = time.monotonic() + SEARCH_DEADLINE_S
    _search_queued += 1
    try:
        return await rag.run(loop, "search", project, query, limit, cross_project, kinds,
                             deadline=deadline)
    finally:
        # именно finally: счётчик, не убывающий при исключении, залипает НАВСЕГДА —
        # система начнёт отвечать busy на всё после первой же ошибки поиска
        _search_queued -= 1


async def backfill_scope(project: str, root: Path | None = None,
                         session_name: str | None = None) -> dict:
    """Index all .md + agent logs of a project (write-executor). Fire-and-forget safe:
    caller wraps in try. Incremental (sha256 + logs_indexed dedup).
    session_name задан → индексим ТОЛЬКО логи этой сессии (файлы .md пропускаем — они
    не привязаны к сессии); иначе — весь scope (.md + все логи).

    Работа нарезана на срезы и чередует слои. Прогон, оборванный рестартом, продолжается с
    места обрыва: файлы дедуплицируются по sha256, логи — по `logs_indexed`. Один запланированный
    прогон не занимает write-executor дольше `_PASS_BUDGET_SECONDS`; недоделанное догонит
    следующий триггер. Догнать корпус за один прогон и не пытаемся: медиана жизни процесса —
    25 минут, полный догон — десятки минут, и схема «всё за раз» не сходится by design.

    Бюджет обязан обрывать слой ВНУТРИ, а не между срезами. Пока дедлайн проверялся только
    здесь, один срез логов длиной 27 минут съедал прогон целиком: до второй итерации дело не
    доходило, и за прогон индексировалось ровно `_FILE_SLICE` файлов — при долге в 481 файл
    это «не догонит никогда» (#44). Половина остатка каждому слою: иначе слой, который идёт
    первым, забирает весь бюджет, и второй голодает."""
    if not _initialized:
        raise RuntimeError("RAG not initialized")
    from app import rag
    loop = asyncio.get_running_loop()
    root = root or Path(project)
    files = logs = 0
    deadline = time.monotonic() + _PASS_BUDGET_SECONDS
    while True:
        now = time.monotonic()
        # Половина остатка файловому слою, остальное логам: слой, идущий первым, иначе
        # забирает весь бюджет, и второй голодает.
        f = 0 if session_name else await rag.run(
            loop, "backfill_files", project, root, _FILE_SLICE, now + (deadline - now) / 2)
        l = await rag.run(loop, "backfill_logs", project, _ORCHESTRA_DB, _LOG_SLICE,
                          session_name, deadline)
        files += f
        logs += l
        if (f == 0 and l == 0) or time.monotonic() >= deadline:
            break
    if session_name:
        logger.info(f"RAG backfill_scope[{project}] session={session_name}: {logs} logs")
        return {"files": 0, "logs": logs}
    pending = await rag.run(loop, "pending_files", project, root)
    _last_pending[_normalize_scope(project)] = pending
    logger.info(f"RAG backfill_scope[{project}]: {files} files, {logs} logs, {pending} still pending")
    return {"files": files, "logs": logs, "pending_files": pending}


def index_status(scope: str) -> dict:
    """Сколько .md ЭТОГО scope ещё не догнано по последнему прогону. Долг считается по scope:
    общий счётчик показывал бы чужой проект. Прогонов не было — пусто: врать нулём
    («индекс догнан») хуже, чем честно молчать."""
    key = _normalize_scope(scope)
    if key not in _last_pending:
        return {}
    running = any(k == key or k.startswith(f"{key}::") for k in _backfill_tasks)
    return {"pending_files": _last_pending[key], "indexing": running}


def _normalize_scope(scope: str) -> str:
    return scope.rstrip("/")


def _observe_backfill_task(task: asyncio.Task[None]) -> None:
    try:
        task.result()
    except asyncio.CancelledError:
        pass
    except Exception:
        logger.exception("RAG scheduler wrapper failed unexpectedly")


async def _run_scheduled_backfill(key: str, scope: str, session_name: str) -> None:
    task = asyncio.current_task()
    loop = asyncio.get_running_loop()
    started = loop.time()
    scans = 0
    try:
        while True:
            _backfill_dirty.discard(key)
            scans += 1
            scan_started = loop.time()
            logger.info("RAG scheduled backfill start scope=%s scan=%d", key, scans)
            try:
                result = await backfill_scope(scope, session_name=session_name or None)
            except asyncio.CancelledError:
                logger.info(
                    "RAG scheduled backfill wrapper cancelled scope=%s; "
                    "executor work already running may continue",
                    key,
                )
                raise
            except Exception as exc:
                logger.exception(
                    "RAG scheduled backfill failed scope=%s scan=%d duration=%.3fs: %s: %s",
                    key,
                    scans,
                    loop.time() - scan_started,
                    type(exc).__name__,
                    exc,
                )
                if key not in _backfill_dirty:
                    return
                logger.info("RAG scheduled backfill rerun after failure scope=%s", key)
                continue
            logger.info(
                "RAG scheduled backfill end scope=%s scan=%d duration=%.3fs result=%s",
                key,
                scans,
                loop.time() - scan_started,
                result,
            )
            if key not in _backfill_dirty:
                logger.info(
                    "RAG scheduled backfill complete scope=%s scans=%d duration=%.3fs",
                    key,
                    scans,
                    loop.time() - started,
                )
                return
            logger.info("RAG scheduled backfill rerun scope=%s", key)
    finally:
        if _backfill_tasks.get(key) is task:
            _backfill_tasks.pop(key, None)
        _backfill_dirty.discard(key)


def schedule_backfill(scope: str, session_name: str = "") -> str:
    """Accept a live backfill, or coalesce one follow-up scan for the same key.

    Единственный способ запустить индексацию: и триггер после мержа, и ручной reindex ходят
    сюда. Работа уходит в фон, вызывающий получает управление сразу — синхронно ждать нельзя,
    один лог стоит 1.3–2.9 с, и сессия на 500 логов держала HTTP-запрос дольше 6.5 минут."""
    if not scope or not scope.strip() or not is_ready():
        logger.warning("RAG scheduled backfill not ready scope=%r", scope)
        return "not_ready"
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.warning("RAG scheduled backfill not ready scope=%r: no running event loop", scope)
        return "not_ready"

    normalized = _normalize_scope(scope)
    # Ключ отделяет пересессионный прогон от общего: они не должны коалесцировать друг с
    # другом, иначе явный ручной reindex тихо схлопнется в фоновый скан всего scope.
    key = f"{normalized}::{session_name}" if session_name else normalized
    current = _backfill_tasks.get(key)
    if current is not None and not current.done():
        _backfill_dirty.add(key)
        logger.info("RAG scheduled backfill coalesced scope=%s", key)
        return "coalesced"

    task = loop.create_task(
        _run_scheduled_backfill(key, normalized, session_name),
        name=f"rag-backfill:{key}",
    )
    _backfill_tasks[key] = task
    task.add_done_callback(_observe_backfill_task)
    logger.info("RAG scheduled backfill accepted scope=%s", key)
    return "accepted"
