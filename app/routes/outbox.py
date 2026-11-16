from fastapi import APIRouter, Request
from pydantic import BaseModel
from app import outbox
from app.routes.always_on import address, validated

router = APIRouter(prefix="/api/outbox",tags=["outbox"])


class OutboxCreate(BaseModel):
    recipient: str
    scope: str
    channel: str
    target: str
    body: str
    urgent: bool = False
    min_interval_seconds: float | None = None
    quiet_start_hour: int | None = None
    quiet_end_hour: int | None = None
    timezone_name: str = "UTC"
    dedupe_key: str = ""
    dedupe_window_seconds: float = 86400
    max_attempts: int = 5


@router.post("")
def create(req: OutboxCreate,request: Request):
    address(request,req.recipient,req.scope)
    return validated(lambda: outbox.enqueue(**req.model_dump()))


@router.get("")
def listing(request: Request,recipient: str | None=None,scope: str | None=None,limit: int=100):
    recipient,scope = address(request,recipient,scope)
    return outbox.list_messages(recipient,scope,limit)
