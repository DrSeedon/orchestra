"""Единственный роут, переживший портфельный слой: durable-тег пользователя."""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app import attention

router = APIRouter(prefix="/api", tags=["attention"])


class AttentionCreate(BaseModel):
    reason: str
    kind: str = "legacy"


@router.post("/attention")
def create_attention(req: AttentionCreate, request: Request):
    session_id = request.headers.get("x-orchestra-session-id", "").strip()
    try:
        if not session_id:
            raise attention.AttentionError(403, "x-orchestra-session-id is required")
        result = attention.create_attention(session_id, req.reason, kind=req.kind)
    except attention.AttentionError as exc:
        return JSONResponse({"error": exc.detail}, status_code=exc.status_code)
    return JSONResponse(result, status_code=201)
