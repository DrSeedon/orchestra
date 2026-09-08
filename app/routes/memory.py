"""Search the project's Markdown and original SQLite logs directly."""
import asyncio
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from app.memory_search import search

router = APIRouter(prefix='/api/memory', tags=['memory'])


class MemorySearchRequest(BaseModel):
    scope: str
    query: str
    limit: int = Field(default=5, ge=1, le=50)
    cross_project: bool = False
    kinds: list[str] | None = None


@router.post('/search')
async def memory_search(req: MemorySearchRequest):
    try:
        results = await asyncio.to_thread(search, req.scope, req.query, limit=req.limit,
            cross_project=req.cross_project, kinds=req.kinds)
    except (ValueError, KeyError) as error:
        return JSONResponse({'error': str(error)}, status_code=400)
    return {'results': results}
