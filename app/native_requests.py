"""Foreground ACP native RPC decisions. No mailbox wake or model prompt is used."""
import asyncio
import hashlib
import json
import time
import uuid
from dataclasses import dataclass
from app import db

TTL=120.0
_active={}


def schema():
    with db._conn() as c:
        c.executescript("""CREATE TABLE IF NOT EXISTS acp_profile_epochs (
          profile_key TEXT PRIMARY KEY, epoch TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS acp_session_bindings (
          profile_key TEXT, native_id TEXT, owner_id TEXT, epoch TEXT,
          PRIMARY KEY(profile_key,native_id));
        CREATE TABLE IF NOT EXISTS acp_native_requests (
          id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, native_id TEXT NOT NULL,
          profile_key TEXT NOT NULL, epoch TEXT NOT NULL, transport TEXT NOT NULL,
          turn_id TEXT NOT NULL, rpc_id TEXT NOT NULL, binding TEXT NOT NULL,
          kind TEXT NOT NULL, payload TEXT NOT NULL, state TEXT NOT NULL,
          expires REAL NOT NULL, decision TEXT, created REAL NOT NULL,
          UNIQUE(transport,rpc_id));""")


def profile_key(home):return hashlib.sha256(str(home.resolve()).encode()).hexdigest()


def profile_epoch(home):
    schema();key=profile_key(home)
    with db._conn() as c:
        c.execute("INSERT OR IGNORE INTO acp_profile_epochs VALUES (?,?)",(key,uuid.uuid4().hex))
        return c.execute("SELECT epoch FROM acp_profile_epochs WHERE profile_key=?",(key,)).fetchone()[0]


def bind_session(owner,native_id,app_id,resume=False):
    schema()
    if profile_epoch(owner.home)!=owner.epoch:raise ValueError("ACP profile epoch changed; explicit new profile required")
    if not app_id:return  # Backend-only synthetic clients have no UI callbacks.
    key=profile_key(owner.home)
    with db._conn() as c:
        row=c.execute("SELECT * FROM acp_session_bindings WHERE profile_key=? AND native_id=?",(key,native_id)).fetchone()
        if row and (row["epoch"]!=owner.epoch or row["owner_id"]!=app_id):raise ValueError("Stale or foreign ACP session binding")
        if resume and row is None:raise ValueError("Unbound ACP resume requires explicit new session")
        c.execute("INSERT OR IGNORE INTO acp_session_bindings VALUES (?,?,?,?)",(key,native_id,app_id,owner.epoch))


def validate_payload(params):
    tool=params.get("toolCall");options=params.get("options")
    if not isinstance(tool,dict) or not isinstance(tool.get("toolCallId"),str):raise ValueError("Missing native tool ID")
    if not isinstance(options,list) or not 1<=len(options)<=12:raise ValueError("Invalid native options")
    ids=set();clean=[];question=tool["toolCallId"].startswith("interaction_")
    for option in options:
        if not isinstance(option,dict):raise ValueError("Invalid native option")
        oid=option.get("optionId");kind=option.get("kind")
        if not isinstance(oid,str) or not oid.strip() or len(oid)>128 or oid in ids:raise ValueError("Invalid native option ID")
        if not question and kind not in {"allow_once","allow_always","reject_once","reject_always"}:raise ValueError("Unsupported permission option")
        ids.add(oid)
        warning=(option.get("_meta") or {}).get("agy.security.warning") or {}
        clean.append({"optionId":oid,"name":str(option.get("name") or oid)[:512],"kind":kind,
                      "warning":str(warning.get("message") or warning.get("title") or "")[:512] if isinstance(warning,dict) else ""})
    from app.acp_tools import bounded
    details={k:bounded(tool[k]) for k in ("name","kind","rawInput","content","locations") if k in tool}
    return {"title":str(tool.get("title") or "Choose an option")[:8000],"toolCallId":tool["toolCallId"][:256],
            "details":details,"options":clean,"kind":"question" if question else "permission","custom_answer":False}


@dataclass
class Pending:
    owner:object
    future:object
    app_id:str
    turn_id:str


def resource(row):
    if row is None:return None
    out={k:row[k] for k in ("id","owner_id","binding","kind","state","expires","decision")}
    out.update(json.loads(row["payload"]))
    return out


def get(request_id):
    schema()
    with db._conn() as c:row=c.execute("SELECT * FROM acp_native_requests WHERE id=?",(request_id,)).fetchone()
    return resource(row)


def pending_for(app_id):
    schema()
    with db._conn() as c:
        rows=c.execute("SELECT * FROM acp_native_requests WHERE owner_id=? AND state='pending' ORDER BY created,id",(app_id,)).fetchall()
    result=[]
    for row in rows:
        if row["id"] not in _active:
            finish(row["id"],"stale")
        else:result.append(resource(row))
    return result


def finish(request_id,state,decision=None):
    with db._conn() as c:c.execute("UPDATE acp_native_requests SET state=?,decision=COALESCE(?,decision) WHERE id=?",(state,decision,request_id))


async def request(owner,rpc_id,params,backend):
    if not backend.app_session_id: return {"outcome":{"outcome":"cancelled"}}
    payload=json.loads(backend._redact(json.dumps(validate_payload(params),ensure_ascii=False)));schema();rid=uuid.uuid4().hex
    binding=hashlib.sha256(json.dumps([backend.app_session_id,params["sessionId"],owner.epoch,owner.transport_generation,backend._turn_id,rpc_id,payload,hashlib.sha256(json.dumps(params,sort_keys=True).encode()).hexdigest()],sort_keys=True).encode()).hexdigest()
    now=time.time();future=asyncio.get_running_loop().create_future()
    with db._conn() as c:
        c.execute("INSERT INTO acp_native_requests VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (rid,backend.app_session_id,params["sessionId"],profile_key(owner.home),owner.epoch,owner.transport_generation,
             backend._turn_id,json.dumps(rpc_id),binding,payload["kind"],json.dumps(payload,ensure_ascii=False),"pending",now+TTL,None,now))
    _active[rid]=Pending(owner,future,backend.app_session_id,backend._turn_id)
    backend._flush_segment()
    backend._queue.put_nowait(__import__("app.events",fromlist=["AgentEvent"]).AgentEvent("native_request",json.dumps(get(rid),ensure_ascii=False),metadata={"item_id":"acp-native:"+rid}))
    try:
        try:outcome=await asyncio.wait_for(asyncio.shield(future),TTL)
        except TimeoutError:
            finish(rid,"expired","timeout");outcome={"outcome":{"outcome":"cancelled"}}
        return rid,outcome
    except asyncio.CancelledError:
        finish(rid,"stale");raise
    finally:_active.pop(rid,None)


def resolve(request_id,*,owner_id,binding,option_id=None,cancel=False):
    schema();live=_active.get(request_id)
    live_epoch=profile_epoch(live.owner.home) if live else None
    owner_row=db.get_session(owner_id)
    with db._conn() as c:
        c.execute("BEGIN IMMEDIATE")
        row=c.execute("SELECT * FROM acp_native_requests WHERE id=?",(request_id,)).fetchone()
        if row is None:raise KeyError(request_id)
        if row["owner_id"]!=owner_id or row["binding"]!=binding:raise PermissionError("Foreign or changed native request")
        decision="cancelled" if cancel else option_id
        if owner_row is None or owner_row.get("status")=="archived":raise ValueError("Stale native request owner")
        if row["state"]=="responded" and row["decision"]==decision:return resource(row)
        handler=live.owner.permission_handlers.get(row["native_id"]) if live else None
        if (not live or live.owner.failure or live.owner.transport_generation!=row["transport"] or live_epoch!=row["epoch"]
            or handler is None or handler.app_session_id!=owner_id or handler._turn_id!=row["turn_id"]):
            raise ValueError("Stale native request")
        if row["expires"]<=time.time():raise ValueError("Native request expired")
        decision="cancelled" if cancel else option_id
        if row["state"]!="pending":
            if row["decision"]==decision:return resource(row)
            raise ValueError("Native request already decided")
        payload=json.loads(row["payload"])
        if not cancel and option_id not in {x["optionId"] for x in payload["options"]}:raise ValueError("Invalid native option ID")
        c.execute("UPDATE acp_native_requests SET state='responding',decision=? WHERE id=? AND state='pending'",(decision,request_id))
    outcome={"outcome":{"outcome":"cancelled"}} if cancel else {"outcome":{"outcome":"selected","optionId":option_id}}
    if not live.future.done():live.future.set_result(outcome)
    return get(request_id)


def cancel_turn(owner,turn_id):
    for rid,live in list(_active.items()):
        if live.owner is owner and live.turn_id==turn_id and not live.future.done():
            finish(rid,"responding","cancelled");live.future.set_result({"outcome":{"outcome":"cancelled"}})
