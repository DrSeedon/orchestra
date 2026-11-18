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
if mode=="client":
    pass
elif mode=="before":
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
elif mode=="wake":
    assert not (HERE/"recovery-pings.json").exists(), "Recovery intents already exist; inspect receipts, never resend blindly"
    target_names=("Orchestra-orchestrator","seedon-orchestrator","kesha-tg-bot-orchestrator")
    targets={r["name"]:r for r in rows() if r["name"] in NAMES}
    assert len(targets)==10 and all(r["model"]=="gpt-6.2-sol" and r["effort"]=="high" for r in targets.values())
    notices={
        "Orchestra-orchestrator":"Восстанови пропущенные ночные/утренние проверки и задачи Orchestra после EgressSafetyError.",
        "seedon-orchestrator":"Проверь пропущенные утренние задания Seedon в 02:01 и 04:00 UTC; восстанови безопасную незавершённую работу.",
        "kesha-tg-bot-orchestrator":"Проверь недоставленное сообщение владельца от 11:21 об ошибке Кеши. Сам kesha-bot-vps уже исправлен и переведён на gpt-6.2-sol medium, коммит 7e69f5d; учти это и не повторяй выполненный ремонт."
    }
    outcomes=[]
    for name in target_names:
        target=targets[name]
        assert target["status"]=="idle"
        c=sqlite3.connect("file:"+str(PROD/"data/orchestra.db")+"?mode=ro",uri=True)
        marker=c.execute("SELECT COALESCE(MAX(id),0) FROM logs WHERE session_id=?",(target["id"],)).fetchone()[0]
        c.close()
        receipt=str(uuid4())
        intent={"name":name,"id":target["id"],"delivery_id":receipt,"after_log_id":marker,
                "native_id_before":target["session_id"],"attempts":1,"state":"INTENT"}
        outcomes.append(intent);write("recovery-pings.json",outcomes)
        message=("Разовый восстановительный пинг по прямому поручению владельца. Прокси восстановлен и проверен, модель теперь gpt-6.2-sol high. "
            "В начале ответа кратко подтверди живой старт словами SOL62_START_OK. "+notices[name]+
            " Сверь фактический журнал/результаты перед восстановлением: не дублируй уже выполненные или неоднозначно отправленные операции. "
            "Не создавай новые кроны и не меняй их расписание; это разовый запуск. Сообщи результат или конкретный оставшийся блокер.")
        result=api("POST","/api/sessions/"+quote(name,safe="")+"/send",{
            "scope":target["scope"],"message":message,"channel":"dashboard","delivery_id":receipt},timeout=45)
        intent["state"]=result.get("delivery_state") or result.get("state") or "ACCEPTED"
        write("recovery-pings.json",outcomes)
    deadline=time.monotonic()+90
    while True:
        all_started=True
        for item in outcomes:
            c=sqlite3.connect("file:"+str(PROD/"data/orchestra.db")+"?mode=ro",uri=True);c.row_factory=sqlite3.Row
            receipt=c.execute("SELECT state FROM message_deliveries WHERE delivery_id=?",(item["delivery_id"],)).fetchone()
            live=c.execute("SELECT model,effort,status,session_id FROM sessions WHERE id=?",(item["id"],)).fetchone()
            logs=c.execute("SELECT type,content FROM logs WHERE session_id=? AND id>? ORDER BY id",(item["id"],item["after_log_id"])).fetchall()
            c.close()
            item.update(delivery_state=receipt["state"] if receipt else item["state"],
                model=live["model"],effort=live["effort"],status=live["status"],
                start_ack=any("SOL62_START_OK" in (r["content"] or "") for r in logs if r["type"]=="text"),
                tool_events=sum(r["type"]=="tool" for r in logs),
                error_events=sum(r["type"]=="error" for r in logs),
                observed_output=any(r["type"] in {"thinking","text","tool","tool_result"} for r in logs),
                native_id_preserved=live["session_id"]==item["native_id_before"])
            assert item["model"]=="gpt-6.2-sol" and item["effort"]=="high"
            if item["delivery_state"] in {"FAILED_BEFORE_SUBMIT","DELIVERY_UNKNOWN","CANCELLED"} or item["error_events"]:
                write("recovery-pings.json",outcomes)
                raise RuntimeError("Recovery ping failed for "+item["name"]+"; no replay")
            started=item["delivery_state"]=="SUBMITTED" and (item["observed_output"] or item["start_ack"])
            item["live_start_verified"]=started
            all_started=all_started and started
        write("recovery-pings.json",outcomes)
        if all_started:break
        if time.monotonic()>deadline:
            raise RuntimeError("Recovery start observation deadline; submitted work left running, no replay")
        time.sleep(1)
    print(json.dumps([{k:r[k] for k in ("name","model","effort","delivery_state","status","live_start_verified","error_events")} for r in outcomes]))
elif mode=="health":
    current=snapshot()
    write("health.json",current)
    broken=[r["name"] for r in current if r.get("runtime_error") or r.get("status") in {"broken","error","interrupted"}]
    assert not broken,"Session health requires explicit inspection"
    print(json.dumps({"non_archived":len(current),"broken":broken}))
else:raise ValueError("unknown mode")
