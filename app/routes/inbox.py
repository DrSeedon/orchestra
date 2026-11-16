from fastapi import APIRouter, Request
from pydantic import BaseModel
from app import mailbox
from app.deps import manager
from app.events import MessageProvenance
from app.routes.always_on import actor

router = APIRouter(prefix="/api/inbox",tags=["event-inbox"])


class EventCreate(BaseModel):
    recipient: str
    scope: str
    sender: str = "external"
    body: str
    idempotency_key: str | None = None


@router.post("/events")
async def enqueue_event(req: EventCreate,request: Request):
    who = actor(request)
    if who:
        # Agent identity is server-owned; self-inbox is allowed, spoofing is not.
        from fastapi import HTTPException
        if (req.recipient,req.scope) != (who["name"],who["scope"]):
            raise HTTPException(403,"inbox belongs to another session")
    sender = who["name"] if who else req.sender
    result = mailbox.enqueue_event(req.recipient,req.scope,sender,req.body,
        provenance=MessageProvenance("agent" if who else "platform",(sender,),"inbox_event"),
        idempotency_key=req.idempotency_key)
    await mailbox.wake_recipient(req.recipient,req.scope,manager=manager)
    return result
