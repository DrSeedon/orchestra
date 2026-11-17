"""Authorized controlled deployment. No provider prompts or secret exports."""
from pathlib import Path
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import time
import urllib.request
import urllib.error

CANDIDATE=Path("/home/kesha/orchestra-worktrees/agy-acp-safe")
PROD=Path("/home/kesha/orchestra")
EVIDENCE=CANDIDATE/".orchestra/tasks/agy-audit-fixes-20261117"
CODE_COMMIT="912b2f18afe65986c4158286a16676046489ce5e"
baseline=json.loads((EVIDENCE/"baseline.json").read_text())
before=json.loads((EVIDENCE/"pre-deploy-state.json").read_text())
report={"code_commit":CODE_COMMIT,"steps":[],"real_provider_prompts_sent":0}
def save():
    (EVIDENCE/"deployment.json").write_text(json.dumps(report,indent=2)+"\n")
def run(argv,**kw):
    result=subprocess.run(argv,capture_output=True,text=True,timeout=90,**kw)
    report["steps"].append({"argv":argv,"returncode":result.returncode})
    save()
    if result.returncode:
        raise RuntimeError("Deployment command failed: "+argv[0]+" ("+str(result.returncode)+")")
    return result.stdout.strip()
def preserved():
    return all(hashlib.sha256((PROD/p).read_bytes()).hexdigest()==v for p,v in baseline["preserve"].items())
def database_snapshot():
    connection=sqlite3.connect("file:"+str(PROD/"data/orchestra.db")+"?mode=ro",uri=True)
    connection.row_factory=sqlite3.Row
    connection.execute("PRAGMA query_only=1")
    rows=[dict(r) for r in connection.execute(
        "SELECT id,name,model,status,backend_type FROM sessions WHERE status='running' OR name='hydrogen-sandbox-orchestrator'")]
    cuts=connection.execute("SELECT COUNT(*) FROM restart_cut_turns").fetchone()[0]
    compact=[]
    for row in connection.execute("SELECT id,name FROM sessions WHERE status<>'archived'"):
        latest=connection.execute(
            "SELECT content FROM logs WHERE session_id=? AND type='status' AND content LIKE 'compact %' ORDER BY id DESC LIMIT 1",
            (row["id"],)).fetchone()
        if latest and str(latest[0]).startswith("compact started"):
            compact.append(row["name"])
    connection.close()
    return {"sessions":rows,"restart_cut_turns":cuts,"possibly_compacting":compact}
def children(unit):
    path=Path("/sys/fs/cgroup/system.slice")/(unit+".service")/"cgroup.procs"
    main=int(run(["systemctl","show",unit+".service","-p","MainPID","--value"]) or 0)
    return [int(p) for p in path.read_text().split() if int(p)!=main]
def vendor_pids():
    result=[]
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():continue
        try:
            args=(entry/"cmdline").read_bytes().split(b"\0")
            if args and args[0].endswith(b"/agy-vendor.elf"):
                result.append(int(entry.name))
        except (PermissionError,FileNotFoundError,ProcessLookupError):pass
    return result
assert preserved(),"production dirty file changed"
assert run(["git","-C",str(PROD),"rev-parse","HEAD"])==baseline["base"],"production HEAD moved"
pre=database_snapshot()
assert pre["restart_cut_turns"]==0 and not pre["possibly_compacting"],"restart state is not clear"
assert not any(r["status"]=="running" for r in pre["sessions"]),"running turn; defer restart"
report["before"]=pre
# Fast-forward only; never stash, reset dirty files or change provider settings.
run(["git","-C",str(PROD),"merge","--ff-only",CODE_COMMIT])
assert preserved()
run(["sudo","-n","install","-o","root","-g","root","-m","0755",
     str(PROD/"deploy/bin/orchestra_agy_ipc.py"),"/usr/local/libexec/orchestra-agy-ipc.py"])
for unit in ("orchestra-agy-spawner","orchestra-agy-tool-exec"):
    run(["sudo","-n","install","-o","root","-g","root","-m","0644",
         str(PROD/"deploy/systemd"/(unit+".service")),"/etc/systemd/system/"+unit+".service"])
run(["sudo","-n","systemctl","daemon-reload"])
# Verify again immediately before signalling the service.
check=database_snapshot()
assert not any(r["status"]=="running" for r in check["sessions"]) and not check["possibly_compacting"]
run(["sudo","-n","systemctl","restart","orchestra.service"])
assert run(["systemctl","is-active","orchestra.service"])=="active"
deadline=time.monotonic()+12
while True:
    vendor=vendor_pids()
    tool=children("orchestra-agy-tool-exec")
    spawn=children("orchestra-agy-spawner")
    if not vendor and not tool and not spawn:break
    if time.monotonic()>=deadline:
        report["idle_restart_blocker"]={"vendor_pids":vendor,"tool_children":tool,"spawner_children":spawn}
        save()
        raise RuntimeError("IPC daemon restart deferred: non-idle children remain; none were killed")
    time.sleep(.5)
run(["sudo","-n","systemctl","restart","orchestra-agy-spawner.service","orchestra-agy-tool-exec.service"])
# Local file preparation only, with no vendor process/auth/probe.
sys.path.insert(0,str(PROD))
from app.antigravity_auth import prepare_acp_token_store
prepare_acp_token_store(PROD/"data/antigravity-auth-home")
home=PROD/"data/antigravity-auth-home"
canonical=home/".gemini/antigravity-acp/antigravity-oauth-token"
legacy=home/".gemini/antigravity-cli/antigravity-oauth-token"
assert canonical.is_file() and not canonical.is_symlink()
assert legacy.is_symlink() and legacy.resolve()==canonical.resolve()
report["credential_store"]={"single_source":True,"canonical_mode":oct(canonical.stat().st_mode&0o777),
                            "legacy_link":True,"secret_values_exported":0}
report["units"]={}
for unit in ("orchestra","orchestra-agy-spawner","orchestra-agy-tool-exec","telegram-bot-api"):
    props=run(["systemctl","show",unit+".service",
               "--property=MainPID,ActiveState,MemoryMax,MemoryHigh,ActiveEnterTimestampMonotonic"])
    report["units"][unit]=dict(line.split("=",1) for line in props.splitlines())
    assert report["units"][unit]["ActiveState"]=="active"
assert report["units"]["telegram-bot-api"]["MainPID"]==dict(
    line.split("=",1) for line in before["units"]["telegram-bot-api"].splitlines())["MainPID"]
for unit in ("orchestra-agy-spawner","orchestra-agy-tool-exec"):
    assert report["units"][unit]["MemoryMax"]==str(8*1024**3)
    assert report["units"][unit]["MemoryHigh"]==str(6*1024**3)
assert hashlib.sha256(Path("/usr/local/libexec/orchestra-agy-ipc.py").read_bytes()).digest()==hashlib.sha256((PROD/"deploy/bin/orchestra_agy_ipc.py").read_bytes()).digest()
assert hashlib.sha256((PROD/"data/disabled_providers.json").read_bytes()).hexdigest()==before["disabled_file_sha256"]
assert preserved()
post=database_snapshot()
assert post["restart_cut_turns"]==0
hydrogen=[r for r in post["sessions"] if r["name"]=="hydrogen-sandbox-orchestrator"]
assert hydrogen and hydrogen[0]["model"]=="antigravity/gemini-4-hydrogen-high" and hydrogen[0]["backend_type"]=="antigravity"
report["after"]=post
report["preserved_dirty_files"]=True
report["disabled_providers_unchanged"]=True
report["production_app_root"]=str(PROD/"app")
report["main_pid_cwd"]=os.readlink("/proc/"+report["units"]["orchestra"]["MainPID"]+"/cwd")
report["vendor_pids_after"]=vendor_pids()
report["verdict"]="DEPLOYED_SCOPED_CHECKS_PASS"
save()
print(json.dumps({"verdict":report["verdict"],"code_commit":CODE_COMMIT,"restart_cut_turns":0,
                 "memory_max_gib":8,"telegram_pid_unchanged":True,"preserved_dirty_files":True,
                 "hydrogen_model":hydrogen[0]["model"],"vendor_pids":report["vendor_pids_after"]}))
