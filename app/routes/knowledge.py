"""Single agent-facing HTTP boundary for canonical structured knowledge."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.ia import knowledge
from app.ia.evidence import EvidenceResolutionError
from app.ia.events import EventConflictError
from app.ia.schema import PrivacyViolationError


router = APIRouter(tags=["knowledge"])


def _error(code: str, message: str, status: int) -> JSONResponse:
    return JSONResponse(
        {"error": {"code": code, "message": message}},
        status_code=status,
    )


@router.post("/api/knowledge")
async def knowledge_request(request: Request):
    try:
        payload = await request.json()
    except ValueError:
        return _error("invalid_request", "knowledge request must be JSON", 400)
    try:
        return knowledge.knowledge_api(payload)
    except knowledge.UnsupportedKnowledgeOperationError as exc:
        return _error("unsupported_operation", str(exc), 400)
    except knowledge.CanonicalKnowledgeUnavailableError as exc:
        return _error("canonical_unavailable", str(exc), 503)
    except knowledge.KnowledgeNotConfiguredError as exc:
        return _error("knowledge_not_configured", str(exc), 503)
    except (knowledge.PromotionConflictError, EventConflictError) as exc:
        return _error("knowledge_conflict", str(exc), 409)
    except (
        knowledge.PromotionValidationError,
        knowledge.TopicResolutionError,
        EvidenceResolutionError,
        PrivacyViolationError,
        TypeError,
    ) as exc:
        return _error("invalid_request", str(exc), 400)
