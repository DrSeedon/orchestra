"""RAG memory API — semantic search over project .md files + agent logs.

Called by the MCP `search_memory` tool (worker-side) and the dashboard. The MCP tool sends
its OWN `ORCHESTRA_SCOPE` as `scope` — a worker cannot request another project's data unless
it explicitly opts into `cross_project` (see mcp_stdio.search_memory).
"""

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app import rag, rag_service
from app.ia import projections

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
    from app.ia import runtime as knowledge_runtime

    live_runtime = (
        knowledge_runtime.active_runtime()
        if knowledge_runtime.runtime_configured()
        else None
    )
    if live_runtime is not None and live_runtime.state.get("active_owner") == "canonical":
        try:
            current = live_runtime.query_for_scope(
                req.scope.rstrip("/"), req.query, limit=req.limit,
            )
        except RuntimeError as error:
            return JSONResponse({"error": str(error)}, status_code=503)
        results = []
        for raw in current["items"]:
            item = dict(raw)
            if item["record_type"] == "resource":
                item.update(source="file", path=item["source_path"])
            else:
                item.update(
                    source="log",
                    log_id=(item.get("source_log_ids") or [None])[0],
                )
            results.append(item)
        return {
            "results": results,
            "index": {"pending_files": 0},
            "canonical_head": current["canonical_head"],
            "projection_head": current["projection_head"],
            "indexed_head": current["indexed_head"],
            "debt": current["debt"],
        }
    # Generation 2 keeps RAG authoritative even while the typed projection is configured.
    projection_active = projections._projection_configured() and live_runtime is None
    if not projection_active and not rag_service.is_enabled():
        return JSONResponse({"error": "RAG disabled (set RAG_ENABLED=true)"}, status_code=503)
    scope = req.scope.rstrip("/")
    if not scope:
        return JSONResponse({"error": "scope required"}, status_code=400)
    kinds = tuple(req.kinds) if req.kinds else None
    if projection_active:
        try:
            current = projections.query_current({
                "project_id": scope,
                "text": req.query,
                "record_types": ["knowledge.evidence-ref", "session.history"],
                "limit": req.limit,
                "cross_project": req.cross_project,
            })
        except RuntimeError as e:
            return JSONResponse({"error": str(e)}, status_code=503)
        results = []
        for raw in current["items"]:
            item = dict(raw)
            if item["record_type"] == "knowledge.evidence-ref":
                item.update(
                    source="file",
                    path=item["source_path"],
                    content=item["content"],
                )
            else:
                item.update(
                    source="log",
                    log_id=item["source_log_ids"][0],
                    content=item["content"],
                )
            results.append(item)
        return {
            "results": results,
            "index": {"pending_files": 0},
            "canonical_head": current["canonical_head"],
            "projection_head": current["projection_head"],
            "indexed_head": current["indexed_head"],
            "debt": current["debt"],
        }
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
    from app.ia import runtime as knowledge_runtime

    runtime_active = knowledge_runtime.runtime_configured()
    if (not projections._projection_configured() or runtime_active) and not rag_service.is_enabled():
        return JSONResponse({"error": "RAG disabled (set RAG_ENABLED=true)"}, status_code=503)
    scope = req.scope.rstrip("/")
    if not scope:
        return JSONResponse({"error": "scope required"}, status_code=400)
    try:
        if runtime_active:
            status = rag_service.schedule_backfill(scope, session_name=req.session_name or "")
            if status == "not_ready":
                raise projections.ProjectionDebtError("RAG not initialized")
            return {"ok": True, "status": status, "index": rag_service.index_status(scope)}
        return projections.rebuild_legacy(scope=scope, session_name=req.session_name)
    except projections.ProjectionDebtError as exc:
        return JSONResponse({"error": str(exc)}, status_code=503)
