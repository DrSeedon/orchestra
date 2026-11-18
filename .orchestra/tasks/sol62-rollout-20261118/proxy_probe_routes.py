"""Narrow repair: IP identity probes must follow the existing residential route."""
import copy
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
SOURCE=Path("/usr/local/etc/xray/config.json")
raw=SOURCE.read_bytes()
config=json.loads(raw)
rules=config.get("routing",{}).get("rules",[])
selected=[r for r in rules if r.get("outboundTag")=="resi-nl" and isinstance(r.get("domain"),list)]
assert len(selected)==1
rule=selected[0]
old_domains=set(rule["domain"])
mirrors=[r for r in rules if r.get("outboundTag")=="block" and set(r.get("domain",[]))==old_domains]
additions={"domain:ipwho.is","domain:ipinfo.io"}
for entry in [rule,*mirrors]:
    entry["domain"]=sorted(set(entry["domain"])|additions)
# Outbound credentials and all non-domain configuration are byte-for-value unchanged.
new=json.dumps(config,ensure_ascii=False,indent=2).encode()+b"\n"
check=subprocess.run(["/usr/local/bin/xray","run","-test","-config","stdin:"],input=new,capture_output=True,timeout=15)
assert check.returncode==0,"Xray candidate config validation failed (raw output suppressed)"
active=subprocess.check_output(["ss","-Htn","state","established","( sport = :2443 or sport = :8443 or sport = :10809 )"],text=True)
assert not active.strip(),"Xray clients active; no restart performed"
assert SOURCE.read_bytes()==raw,"Xray config changed concurrently"
backup=SOURCE.with_name("config.json.sol62-rollout-20261118.bak")
assert not backup.exists(),"preserve existing deployment backup"
fd=os.open(backup,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
with os.fdopen(fd,"wb") as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())
stat=SOURCE.stat()
fd,name=tempfile.mkstemp(prefix=".orchestra-egress-",dir=SOURCE.parent)
try:
    os.fchmod(fd,stat.st_mode&0o777);os.fchown(fd,stat.st_uid,stat.st_gid)
    with os.fdopen(fd,"wb") as stream:stream.write(new);stream.flush();os.fsync(stream.fileno())
    os.replace(name,SOURCE)
finally:
    Path(name).unlink(missing_ok=True)
restart=subprocess.run(["systemctl","restart","xray.service"],capture_output=True,timeout=20)
if restart.returncode:
    SOURCE.write_bytes(raw)
    subprocess.run(["systemctl","start","xray.service"],check=True,capture_output=True,timeout=20)
    raise RuntimeError("Xray candidate restart failed; original config restored")
assert subprocess.check_output(["systemctl","is-active","xray.service"],text=True).strip()=="active"
print(json.dumps({"domains_added":sorted(additions-old_domains),"mirrored_block_rules":len(mirrors),
    "active_connections_before":0,"outbound_credentials_changed":False,"config_validation":"PASS",
    "before_sha256":hashlib.sha256(raw).hexdigest(),"after_sha256":hashlib.sha256(new).hexdigest(),
    "backup":"root-private config.json.sol62-rollout-20261118.bak","xray":"active"}))
