"""Idle-only owner deployment and live catalog/admission verification; no generation."""
from pathlib import Path
import hashlib
import json
import os
import runpy
import sqlite3
import subprocess
import sys
import time
ROOT=Path("/home/kesha/orchestra-worktrees/gemini-routing-20261118")
PROD=Path("/home/kesha/orchestra")
EV=ROOT/".orchestra/tasks/gemini-routing-20261118"
CODE=subprocess.check_output(["git","-C",str(ROOT),"rev-parse","HEAD"],text=True).strip()
base=json.loads((EV/"before.json").read_text())
helper=PROD/".orchestra/tasks/sol62-rollout-20261118/live_control.py"
sys.argv=[str(helper),"client"]
client=runpy.run_path(str(helper))
api=client["api"];snapshot=client["snapshot"]
report={"code_commit":CODE,"idle_observations":[],"provider_prompts":0,"catalog_refresh_probes":0}
def save():
    (EV/"deployment.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")
def cmd(args):
    return subprocess.check_output(args,text=True,timeout=90).strip()
def preserved():
    return all(hashlib.sha256((PROD/path).read_bytes()).hexdigest()==value for path,value in base["dirty"].items())
def busy():
    return [r["name"] for r in snapshot() if r["status"]=="running" or r.get("compaction")]
assert preserved(),"foreign dirty files changed; inspect before proceeding"
assert cmd(["git","-C",str(PROD),"rev-parse","HEAD"])==base["head"],"production HEAD moved"
deadline=time.monotonic()+3600
prior=None
while True:
    active=busy()
    if active!=prior:
        report["idle_observations"].append({"elapsed_monotonic":round(time.monotonic(),3),"busy":active})
        save();print(json.dumps({"busy":active}),flush=True);prior=active
    if not active:break
    if time.monotonic()>deadline:raise RuntimeError("Idle deadline reached; no merge/restart performed")
    time.sleep(2)
assert preserved()
old_pid=cmd(["systemctl","show","orchestra.service","-p","MainPID","--value"])
tg_pid=cmd(["systemctl","show","telegram-bot-api.service","-p","MainPID","--value"])
cmd(["git","-C",str(PROD),"merge","--ff-only",CODE])
# Re-check the actual session projection, not just disk state.
assert not busy(),"new running turn appeared; source merged, restart deferred"
cmd(["sudo","-n","systemctl","restart","orchestra.service"])
assert cmd(["systemctl","is-active","orchestra.service"])=="active"
deadline=time.monotonic()+45
while True:
    try:
        sessions=snapshot()
        break
    except Exception:
        if time.monotonic()>deadline:raise
        time.sleep(1)
sys.path.insert(0,str(PROD))
from app import models
allowed=set(models.ANTIGRAVITY_G1_AGENT_MODELS)
assert len(allowed)==17
catalog=api("GET","/api/models/catalog")
entries={r["id"]:r for r in catalog["catalog"]}
updates=[]
for mid in sorted(allowed):
    # Respect stored overrides generally; this explicit owner task authorizes
    # clearing stale agents=false ONLY on the seventeen named model IDs.
    if not entries[mid]["flags"]["agents"]:
        answer=api("PATCH","/api/models/catalog/flags",{"id":mid,"agents":True})
        assert answer["ok"] and answer["flags"]["agents"]
        updates.append(mid)
catalog=api("GET","/api/models/catalog")
entries={r["id"]:r for r in catalog["catalog"]}
verified=[]
for mid in sorted(allowed):
    assert entries[mid]["flags"]["agents"] is True and not entries[mid]["provider_disabled"]
    models.ensure_spawn_allowed(mid,scope="/home/kesha/orchestra",role="worker",pipeline="default")
    verified.append({"id":mid,"agents":True,"context_length":entries[mid]["context_length"],"canonical_guard":"PASS"})
aliases={}
for alias in ("agy-hydrogen","agy-hydrogen-xhigh","agy-hydrogen-med","agy-argon","agy-argon-high","agy-flash","agy-flash-high","agy-opus","agy-opus-high","agy-sonnet","agy-sonnet-high"):
    mid=models.resolve_model(alias)
    models.ensure_spawn_allowed(mid,scope="/home/kesha/orchestra",role="worker",pipeline="default")
    aliases[alias]=mid
refused=[]
for raw in models.ANTIGRAVITY_RAW_MODELS:
    mid="antigravity/"+raw
    if mid in allowed:continue
    assert models.get_model_spec(mid).default_agents is False
    try:models.ensure_spawn_allowed(mid,scope="/home/kesha/projects/multicode",role="worker")
    except ValueError:refused.append(mid)
    else:raise AssertionError("unexpected non-listed local agent route")
for mid in sorted(models.ANTIGRAVITY_G1_CLAUDE_AGENT_MODELS):
    models.ensure_project_model_allowed(mid,"/home/kesha/projects/seedon")
for mid in ("hubopus","hubsonnet","claude-opus-5-5[1m]","claude-sonnet-5-5[1m]"):
    try:models.ensure_project_model_allowed(mid,"/home/kesha/projects/seedon")
    except ValueError as error:assert "claude_multicast_only" in str(error)
    else:raise AssertionError("Direct/Hub Claude project ban lost")
after_flags=models._load_model_flags()
for mid,flags in base["flags"].items():
    if mid not in allowed:
        assert after_flags.get(mid)==flags,"unrelated model flag changed"
before_disabled=(EV/"disabled-before.sha256").read_text().strip()
assert hashlib.sha256((PROD/"data/disabled_providers.json").read_bytes()).hexdigest()==before_disabled
c=sqlite3.connect("file:"+str(PROD/"data/orchestra.db")+"?mode=ro",uri=True);c.row_factory=sqlite3.Row
cuts=c.execute("SELECT COUNT(*) FROM restart_cut_turns").fetchone()[0]
rows=[dict(r) for r in c.execute("SELECT id,name,model,effort,status,session_id FROM sessions WHERE status<>'archived'")]
c.close()
assert cuts==0 and preserved()
current={r["id"]:r for r in rows}
assert all(all(current[r["id"]][key]==r[key] for key in ("model","effort","session_id")) for r in base["sessions"])
new_pid=cmd(["systemctl","show","orchestra.service","-p","MainPID","--value"])
assert old_pid!=new_pid
assert tg_pid==cmd(["systemctl","show","telegram-bot-api.service","-p","MainPID","--value"])
report.update(verdict="DEPLOYED_ADMISSION_VERIFIED",old_pid=old_pid,new_pid=new_pid,
    restart_cut_turns=cuts,telegram_pid_unchanged=True,dirty_files_preserved=True,
    disabled_providers_unchanged=True,sessions_unchanged=True,agents_flags_updated=updates,
    live_catalog_allowed=verified,aliases=aliases,non_allowed_local_refused=refused,
    tested_app=str(ROOT/"app"),deployed_app=str(PROD/"app"),
    runtime_errors_after_restart=[r["name"] for r in sessions if r.get("runtime_error")])
save()
print(json.dumps({"verdict":report["verdict"],"admitted":len(verified),"aliases":len(aliases),
    "flag_repairs":len(updates),"restart_cut_turns":cuts,"new_pid":new_pid,
    "runtime_errors":report["runtime_errors_after_restart"],"provider_prompts":0}),flush=True)
