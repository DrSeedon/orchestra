"""Authorized operator HTTP rollout; credentials stay in memory on the VPS."""
import asyncio
import hashlib
import hmac
import json
import os
from pathlib import Path
import sqlite3
import sys
import time
import urllib.request
import urllib.error
from urllib.parse import quote
from uuid import uuid4
PROD=Path("/home/kesha/orchestra")
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(PROD))
from dotenv import dotenv_values
values=dotenv_values(PROD/".env")
user=values.get("DASHBOARD_USER") or ""
password=values.get("DASHBOARD_PASSWORD") or ""
assert user and password,"operator credentials unavailable"
cookie=hmac.new(password.encode(),user.encode(),hashlib.sha256).hexdigest()
csrf=hmac.new(password.encode(),("csrf:"+user).encode(),hashlib.sha256).hexdigest()
HEADERS={"Cookie":"session="+cookie,"X-CSRF-Token":csrf,"Content-Type":"application/json"}
NAMES=("Orchestra-orchestrator","seedon-orchestrator","kesha-tg-bot-orchestrator",
"Claude-Code-Game-Master-orchestrator","University-orchestrator","VPN-orchestrator",
"katya-work-orchestrator","comfy-image-orchestrator-vps","cog-second-brain-orchestrator","openrouter-lab-orchestrator")
def api(method,path,body=None,timeout=25):
    request=urllib.request.Request("http://127.0.0.1:8888"+path,
        data=json.dumps(body).encode() if body is not None else None,headers=HEADERS,method=method)
    try:
        with urllib.request.urlopen(request,timeout=timeout) as response:return json.load(response)
    except urllib.error.HTTPError as error:
        # No raw HTTP bodies/headers: they can contain private context.
        raise RuntimeError("Operator API "+method+" "+path.split("?")[0]+" returned "+str(error.code)) from None
def write(name,data):
    (HERE/name).write_text(json.dumps(data,ensure_ascii=False,indent=2)+"\n")
def rows():
    c=sqlite3.connect("file:"+str(PROD/"data/orchestra.db")+"?mode=ro",uri=True);c.row_factory=sqlite3.Row;c.execute("PRAGMA query_only=1")
    result=[dict(r) for r in c.execute("SELECT id,name,scope,model,role,is_orchestrator,status,effort,session_id,context_tokens,context_pct FROM sessions WHERE status<>'archived' ORDER BY name")]
    c.close();return result
def snapshot():
    sessions=api("GET","/api/sessions")
    assert isinstance(sessions,list)
    fields=("id","name","scope","model","status","backend_type","effort","runtime_connection","runtime_error","compaction","loaded")
    return [{"".join(k):r.get(k) for k in fields} for r in sessions]
mode=sys.argv[1]
if mode=="before":
    write("api-before.json",snapshot());print("Authenticated snapshot saved")
elif mode=="egress":
    for key,value in values.items():
        if key in {"ORCHESTRA_RESIDENTIAL_PROXY_URL","CODEX_PROXY_URL","ANTIGRAVITY_PROXY_URL",
                   "ORCHESTRA_DISABLED_PROVIDERS_FILE","ORCHESTRA_EGRESS_VERIFY_TTL_SECONDS"} and value:
            os.environ[key]=value
    from app.provider_safety import verify_provider_egress
    async def verify():
        result={}
        for provider in ("codex","antigravity"):
            identity=await verify_provider_egress(provider)
            assert identity.get("ok") and identity.get("mode")=="verified_proxy"
            assert identity.get("ip")=="178.93.29.64" and identity.get("country")=="NL"
            result[provider]={k:identity.get(k) for k in ("ok","mode","ip","country","asn","org","source")}
        return result
    result=asyncio.run(verify());write("egress.json",result)
    print(json.dumps(result))
elif mode=="switch":
    old=rows();targets={r["name"]:r for r in old if r["name"] in NAMES}
    assert set(targets)==set(NAMES) and not any(r["status"]=="running" for r in old)
    outcomes=[]
    for name in NAMES:
        r=targets[name]
        assert r["model"] in {"gpt-6.1-sol","gpt-6.2-sol"}
        response=api("POST","/api/sessions/"+quote(name,safe="")+"/change-model",{
            "scope":r["scope"],"model":"gpt-6.2-sol","via":"dashboard",
            "model_reason":"Owner-authorized 2026-11-18 local Sol62 high migration; preserve existing native thread and history."})
        assert response.get("ok") and response.get("history_transfer",{}).get("mode")=="native_in_place",name
        after=next(x for x in rows() if x["id"]==r["id"])
        assert after["model"]=="gpt-6.2-sol" and after["effort"]=="high"
        assert after["session_id"]==r["session_id"],"native history replaced"
        outcomes.append({"id":r["id"],"name":name,"old_model":r["model"],"new_model":after["model"],
                         "effort":after["effort"],"native_id_preserved":True,
                         "history_transfer":response.get("history_transfer")})
        write("sessions-switched.json",outcomes)
    hydrogen=next(r for r in old if r["name"]=="hydrogen-sandbox-orchestrator")
    current=next(r for r in rows() if r["id"]==hydrogen["id"])
    assert all(hydrogen[k]==current[k] for k in ("model","effort","session_id"))
    write("api-after-switch.json",snapshot());print("Switched 10/10 via API; native IDs preserved; Hydrogen unchanged")
elif mode=="canary":
    target=next(r for r in rows() if r["name"]=="Orchestra-orchestrator")
    assert target["model"]=="gpt-6.2-sol" and target["effort"]=="high" and target["status"]=="idle"
    c=sqlite3.connect("file:"+str(PROD/"data/orchestra.db")+"?mode=ro",uri=True)
    marker=c.execute("SELECT COALESCE(MAX(id),0) FROM logs WHERE session_id=?",(target["id"],)).fetchone()[0]
    c.close()
    receipt=str(uuid4())
    write("canary-intent.json",{"delivery_id":receipt,"session_id":target["id"],"native_id":target["session_id"],"after_log_id":marker,"attempts":1})
    started=time.monotonic()
    # One request only. Never retry a possibly submitted prompt.
    response=api("POST","/api/sessions/"+quote(target["name"],safe="")+"/send",{
        "scope":target["scope"],"message":"Это разрешённая владельцем однократная проверка после переключения модели. Не вызывай инструменты, не меняй файлы и не продолжай другие задачи. Ответь ровно одной строкой: ORCHESTRA_SOL62_READY",
        "channel":"dashboard","delivery_id":receipt},timeout=40)
    state=response.get("delivery_state") or response.get("state")
    deadline=time.monotonic()+180
    result=None
    while time.monotonic()<deadline:
        c=sqlite3.connect("file:"+str(PROD/"data/orchestra.db")+"?mode=ro",uri=True);c.row_factory=sqlite3.Row
        row=c.execute("SELECT state,error_json FROM message_deliveries WHERE delivery_id=?",(receipt,)).fetchone()
        live=c.execute("SELECT status,model,session_id FROM sessions WHERE id=?",(target["id"],)).fetchone()
        logrows=c.execute("SELECT type,content FROM logs WHERE session_id=? AND id>? ORDER BY id",(target["id"],marker)).fetchall()
        tool_count=sum(r["type"]=="tool" for r in logrows)
        text="\n".join(r["content"] or "" for r in logrows if r["type"]=="text")
        errors=[r for r in logrows if r["type"]=="error"]
        failed_receipt=row and row["state"] in {"FAILED_BEFORE_SUBMIT","DELIVERY_UNKNOWN","CANCELLED"}
        c.close()
        if failed_receipt or errors:
            write("canary-failure.json",{"delivery_state":row["state"] if row else state,
                 "error_logs":len(errors),"tool_count":tool_count,"attempts":1})
            raise RuntimeError("Canary failed; no automatic retry")
        if live and live["status"]=="idle" and "ORCHESTRA_SOL62_READY" in text:
            assert live["model"]=="gpt-6.2-sol" and live["session_id"]==target["session_id"]
            result={"ok":True,"delivery_id":receipt,"delivery_state":row["state"] if row else state,
                    "duration_seconds":round(time.monotonic()-started,3),"tool_count":tool_count,
                    "native_id_preserved":True,"reply":"ORCHESTRA_SOL62_READY","attempts":1}
            break
        time.sleep(1)
    if result is None:
        api("POST","/api/sessions/"+quote(target["name"],safe="")+"/interrupt",{"scope":target["scope"]})
        raise RuntimeError("Canary deadline reached; interrupted, no replay")
    write("canary.json",result);print(json.dumps(result))
elif mode=="health":
    current=snapshot()
    write("health.json",current)
    broken=[r["name"] for r in current if r.get("runtime_error") or r.get("status") in {"broken","error","interrupted"}]
    assert not broken,"Session health requires explicit inspection"
    print(json.dumps({"non_archived":len(current),"broken":broken}))
else:raise ValueError("unknown mode")
