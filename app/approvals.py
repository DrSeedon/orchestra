"""Deferred approval cards: durable decisions, no held CLI or model process."""
import json
import time
from uuid import uuid4

from app import db, mailbox
from app.always_on import seconds
from app.events import MessageProvenance


def _resource(row):
    result = dict(row)
    result["payload"] = json.loads(result["payload"])
    return result


def request_approval(recipient, scope, action, summary, payload=None, *, risk_level="medium",
                     context_note="", expires_in_seconds=86400, idempotency_key=""):
    if not action.strip() or not summary.strip():
        raise ValueError("action and summary are required")
    if risk_level not in {"low","medium","high","critical"}:
        raise ValueError("invalid risk_level")
    if payload is not None and not isinstance(payload,dict):
        raise ValueError("payload must be an object")
    ttl = seconds(expires_in_seconds,minimum=1)
    encoded = json.dumps(payload or {},ensure_ascii=False,allow_nan=False)
    now = time.time()
    with db._conn() as c:
        c.execute("BEGIN IMMEDIATE")
        if idempotency_key:
            row = c.execute("SELECT * FROM deferred_approvals WHERE recipient=? AND scope=? AND idempotency_key=?",
                            (recipient,scope,idempotency_key)).fetchone()
            if row:
                return _resource(row)
        approval_id = uuid4().hex
        c.execute("""INSERT INTO deferred_approvals
            (id,recipient,scope,action,summary,payload,risk_level,context_note,expires_at,created_at,idempotency_key)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (approval_id,recipient,scope,action,summary,encoded,risk_level,context_note,now+ttl,now,idempotency_key or None))
        return _resource(c.execute("SELECT * FROM deferred_approvals WHERE id=?",(approval_id,)).fetchone())


def list_approvals(recipient=None,scope=None):
    with db._conn() as c:
        return [_resource(r) for r in c.execute(
            "SELECT * FROM deferred_approvals WHERE (? IS NULL OR recipient=?) AND (? IS NULL OR scope=?) ORDER BY created_at",
            (recipient,recipient,scope,scope))]


def cancel_approval(approval_id):
    with db._conn() as c:
        return c.execute("UPDATE deferred_approvals SET state='cancelled',decided_at=? WHERE id=? AND state='pending'",
                         (time.time(),approval_id)).rowcount == 1


def _decision_event(c,row,state,note,decided_by,now):
    c.execute("""UPDATE deferred_approvals SET state=?,decided_at=?,decision_note=?,decided_by=?
                 WHERE id=? AND state='pending'""",(state,now,note,decided_by,row["id"]))
    payload = {k:row[k] for k in ("action","summary","context_note")}
    payload.update(approval_id=row["id"],payload=json.loads(row["payload"]),
                   decision_note=note,decided_by=decided_by)
    mailbox.enqueue_event(row["recipient"],row["scope"],"approval",
        f"[APPROVAL {state.upper()}] " + json.dumps(payload,ensure_ascii=False),
        provenance=MessageProvenance("system",("approval",),"approval",row["id"]),
        idempotency_key=f"approval:{row['id']}:resolved",_connection=c)


async def resolve_approval(approval_id, decision, *, note="",decided_by="owner",manager=None):
    if decision not in {"approved","rejected"}:
        raise ValueError("decision must be approved or rejected")
    with db._conn() as c:
        c.execute("BEGIN IMMEDIATE")
        row = c.execute("SELECT * FROM deferred_approvals WHERE id=?",(approval_id,)).fetchone()
        if row is None:
            raise KeyError(approval_id)
        if row["state"] == "pending":
            state = "expired" if row["expires_at"] <= time.time() else decision
            _decision_event(c,row,state,note,decided_by,time.time())
        result = _resource(c.execute("SELECT * FROM deferred_approvals WHERE id=?",(approval_id,)).fetchone())
    if manager is not None and result["state"] in {"approved","rejected","expired"}:
        await mailbox.wake_recipient(row["recipient"],row["scope"],manager=manager)
    return result


async def sweep_expired_approvals(*,now=None,manager=None):
    now = time.time() if now is None else seconds(now)
    with db._conn() as c:
        c.execute("BEGIN IMMEDIATE")
        rows = c.execute("SELECT * FROM deferred_approvals WHERE state='pending' AND expires_at<=?",(now,)).fetchall()
        for row in rows:
            _decision_event(c,row,"expired","Approval expired","system",now)
    if manager is not None:
        import asyncio
        await asyncio.gather(*(mailbox.wake_recipient(r["recipient"],r["scope"],manager=manager) for r in rows))
    return len(rows)
