"""RAG memory API — semantic search over project .md files + agent logs.

Called by the MCP `search_memory` tool (worker-side) and the dashboard. The MCP tool sends
its OWN `ORCHESTRA_SCOPE` as `scope` — a worker cannot request another project's data unless
it explicitly opts into `cross_project` (see mcp_stdio.search_memory).
"""

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app import rag, rag_service

router = APIRouter(prefix="/api/memory", tags=["memory"])


class MemorySearchRequest(BaseModel):
    scope: str
    query: str
    limit: int = 5
    cross_project: bool = False
    kinds: list[str] | None = None  # filter logs by kind: agent_msg | user_msg | text


class MemoryReindexRequest(BaseModel):
    scope: str
    session_name: str | None = None  # if set → index ONLY this session's logs


@router.post("/search")
async def memory_search(req: MemorySearchRequest):
    if not rag_service.is_enabled():
        return JSONResponse({"error": "RAG disabled (set RAG_ENABLED=true)"}, status_code=503)
    scope = req.scope.rstrip("/")
    if not scope:
        return JSONResponse({"error": "scope required"}, status_code=400)
    kinds = tuple(req.kinds) if req.kinds else None
    try:
        results = await rag_service.search(
            scope, req.query, limit=req.limit, cross_project=req.cross_project, kinds=kinds)
    # ВАЖНО: оба класса — наследники RuntimeError, поэтому ловятся ДО общей ветки ниже,
    # иначе схлопнутся в безликое http_5xx и MCP не сможет назвать агенту причину.
    # Код отдаём словарём — _response_error в mcp_stdio читает error["code"] как есть.
    except rag_service.SearchBusy as e:
        return JSONResponse({"error": {"code": "search_busy", "message": str(e)}}, status_code=503)
    except rag.StaleRequest as e:
        return JSONResponse({"error": {"code": "search_stale", "message": str(e)}}, status_code=503)
    except RuntimeError as e:
        return JSONResponse({"error": str(e)}, status_code=503)
    # `index` аддитивен: старый MCP его просто не читает. Показывает долг индекса по последнему
    # прогону — без него агент не отличает «в памяти этого нет» от «до этого ещё не дошли».
    return {"results": results, "index": rag_service.index_status(scope)}


@router.post("/reindex")
async def memory_reindex(req: MemoryReindexRequest):
    """Ставит индексацию в очередь и возвращает управление СРАЗУ.

    Раньше эндпоинт держал запрос до конца прогона: один лог стоит 1.3–2.9 с, поэтому сессия
    на 500 логов висела дольше 6.5 минут и обрывалась по таймауту клиента, а докстринг при
    этом обещал «fast per-agent reindex». Ждать тут нечего: прогресс виден в journald
    (`RAG scheduled backfill …`) и в `index_status` — его же отдаёт `/api/memory/search`.
    """
    if not rag_service.is_enabled():
        return JSONResponse({"error": "RAG disabled (set RAG_ENABLED=true)"}, status_code=503)
    scope = req.scope.rstrip("/")
    if not scope:
        return JSONResponse({"error": "scope required"}, status_code=400)
    status = rag_service.schedule_backfill(scope, session_name=req.session_name or "")
    if status == "not_ready":
        return JSONResponse({"error": "RAG not initialized"}, status_code=503)
    return {"ok": True, "status": status, "index": rag_service.index_status(scope)}
