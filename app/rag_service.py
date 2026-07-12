"""RAG service — singleton wrapper around app.rag for the main FastAPI process.

Owns the embedder (946MB, ONE per Orchestra — NEVER in the MCP subprocess: 946MB × N workers
= OOM) and the write/read ThreadPoolExecutors. All access goes through async methods that
route to the right executor (search → read, index/backfill → write).

Feature-flagged by RAG_ENABLED — when off, `is_enabled()` is False and nothing is loaded,
so Orchestra runs without the optional `[rag]` deps (fastembed/sqlite-vec/onnxruntime).
"""

import asyncio
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


def is_enabled() -> bool:
    return _RAG_ENABLED


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
    _write_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="rag-w")
    _read_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="rag-r")
    rag.set_executor(_write_executor, _read_executor, db_path=_DB_PATH)
    _initialized = True
    logger.info(f"RAG service initialized (db={_DB_PATH})")
    return True


def shutdown() -> None:
    global _write_executor, _read_executor, _initialized
    if _write_executor:
        _write_executor.shutdown(wait=False)
    if _read_executor:
        _read_executor.shutdown(wait=False)
    _write_executor = _read_executor = None
    _initialized = False


async def search(project: str, query: str, limit: int = 5, cross_project: bool = False,
                 kinds: tuple | None = None) -> list[dict]:
    """Semantic search in the read-executor (RO conn, concurrent with backfill)."""
    if not _initialized:
        raise RuntimeError("RAG not initialized")
    from app import rag
    loop = asyncio.get_running_loop()
    return await rag.run(loop, "search", project, query, limit, cross_project, kinds)


async def backfill_scope(project: str, root: Path | None = None) -> dict:
    """Index all .md + agent logs of a project (write-executor). Fire-and-forget safe:
    caller wraps in try. batch=16 (RAM), incremental (sha256 + logs_indexed dedup)."""
    if not _initialized:
        raise RuntimeError("RAG not initialized")
    from app import rag
    loop = asyncio.get_running_loop()
    root = root or Path(project)
    files = await rag.run(loop, "backfill_files", project, root)
    logs = await rag.run(loop, "backfill_logs", project, _ORCHESTRA_DB)
    logger.info(f"RAG backfill_scope[{project}]: {files} files, {logs} logs")
    return {"files": files, "logs": logs}
