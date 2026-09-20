import json, subprocess, sys, time
p = subprocess.Popen(["codex", "app-server"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
def send(m): p.stdin.write(json.dumps(m) + "\n"); p.stdin.flush()
send({"id": 1, "method": "initialize", "params": {"clientInfo": {"name": "probe", "title": "probe", "version": "1"}, "capabilities": None}})
p.stdout.readline()
send({"method": "initialized"}); send({"id": 2, "method": "account/rateLimits/read", "params": None})
while True:
    r = json.loads(p.stdout.readline())
    if r.get("id") == 2: break
p.kill()
lim = (r["result"].get("rateLimitsByLimitId") or {}).get("codex") or r["result"]["rateLimits"]
print(time.strftime("%H:%M:%S"), lim.get("planType"), "5h", lim["primary"]["usedPercent"], "7d", lim["secondary"]["usedPercent"], "credits", json.dumps(lim.get("credits")))
