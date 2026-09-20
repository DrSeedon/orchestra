import json, subprocess
p = subprocess.Popen(["codex","app-server"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
def s(m): p.stdin.write(json.dumps(m)+"\n"); p.stdin.flush()
s({"id":1,"method":"initialize","params":{"clientInfo":{"name":"probe","title":"probe","version":"1"},"capabilities":None}}); p.stdout.readline()
s({"method":"initialized"}); s({"id":2,"method":"account/rateLimits/read","params":None})
while True:
    r=json.loads(p.stdout.readline())
    if r.get("id")==2: break
p.kill(); print(json.dumps(r["result"], indent=1)[:2000])
