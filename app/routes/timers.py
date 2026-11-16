from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from app import timers
from app.routes.always_on import address, owned, validated

router = APIRouter(prefix="/api/timers",tags=["timers"])


class TimerCreate(BaseModel):
    recipient: str
    scope: str
    body: str
    kind: str = "follow_up"
    delay_seconds: float | None = None
    due_at: float | str | None = None
    interval_seconds: float | None = None
    cron_expr: str = ""
    timezone_name: str = "UTC"
    max_fires: int | None = None
    cancel_on_sender: str = ""
    cancel_on_scope: str = ""
    idempotency_key: str | None = None


@router.post("")
def create(req: TimerCreate,request: Request):
    address(request,req.recipient,req.scope)
    return validated(lambda: timers.set_timer(**req.model_dump()))


@router.get("")
def listing(request: Request,recipient: str | None=None,scope: str | None=None):
    recipient,scope = address(request,recipient,scope)
    return timers.list_timers(recipient,scope)


@router.post("/{timer_id}/cancel")
def cancel(timer_id: str,request: Request):
    owned(request,"timers",timer_id)
    return {"cancelled":timers.cancel_timer(timer_id)}
