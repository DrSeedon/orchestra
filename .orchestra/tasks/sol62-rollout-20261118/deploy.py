"""Authorized code deployment; no provider prompt and no model assignment SQL."""
from pathlib import Path
import hashlib
import json
import os
import runpy
import sqlite3
import subprocess
import sys
import time
ROOT=Path("/home/kesha/orchestra-worktrees/sol62-rollout-20261118")
PROD=Path("/home/kesha/orchestra")
EV=ROOT/".orchestra/tasks/sol62-rollout-20261118"
CODE="e8a47391146e01d79e3e881f429b99fa9181ba27"
before=json.loads((EV/"before.json").read_text())
sys.argv=[str(EV/"live_control.py"),"client"]
client=runpy.run_path(str(EV/"live_control.py"))
def api(*args,**kwargs):return client["api"](*args,**kwargs)
def command(args):
    r=subprocess.run(args,check=True,capture_output=True,text=True,timeout=90)
    return r.stdout.strip()
def preserved():
    return all(hashlib.sha256((PROD/p).read_bytes()).hexdigest()==v for p,v in before["preserve"].items())
assert preserved()
assert command(["git","-C",str(PROD),"rev-parse","HEAD"])==before["base"]
live=client["snapshot"]()
assert not [r for r in live if r["status"]=="running" or r.get("compaction")],"active turn/compact"
telegram=command(["systemctl","show","telegram-bot-api.service","-p","MainPID","--value"])
old_pid=command(["systemctl","show","orchestra.service","-p","MainPID","--value"])
command(["git","-C",str(PROD),"merge","--ff-only",CODE])
assert preserved()
# Recheck actual in-memory session projection immediately before signalling.
live=client["snapshot"]()
assert not [r for r in live if r["status"]=="running" or r.get("compaction")]
command(["sudo","-n","systemctl","restart","orchestra.service"])
assert command(["systemctl","is-active","orchestra.service"])=="active"
deadline=time.monotonic()+40
while True:
    try:
        after=client["snapshot"]()
        break
    except Exception:
        if time.monotonic()>deadline:raise
        time.sleep(1)
assert len(after)==23
c=sqlite3.connect("file:"+str(PROD/"data/orchestra.db")+"?mode=ro",uri=True)
cuts=c.execute("SELECT COUNT(*) FROM restart_cut_turns").fetchone()[0];c.close()
assert cuts==0 and preserved()
new_pid=command(["systemctl","show","orchestra.service","-p","MainPID","--value"])
assert new_pid!=old_pid
assert telegram==command(["systemctl","show","telegram-bot-api.service","-p","MainPID","--value"])
report={"code_commit":CODE,"orchestra":"active","old_pid":old_pid,"new_pid":new_pid,
    "telegram_pid_unchanged":True,"restart_cut_turns":cuts,"dirty_files_preserved":True,
    "runtime_errors_after_restart":[r["name"] for r in after if r.get("runtime_error")],
    "non_archived":len(after),"process_cwd":os.readlink("/proc/"+new_pid+"/cwd"),
    "tested_app":str(ROOT/"app"),"deployed_app":str(PROD/"app")}
(EV/"deployment.json").write_text(json.dumps(report,indent=2)+"\n")
print(json.dumps(report))
