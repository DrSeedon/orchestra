"""Read Codex rate limits once via `codex app-server` (same protocol as the dashboard)."""
import json, subprocess, sys, time

p = subprocess.Popen(["codex", "app-server"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                     stderr=subprocess.DEVNULL, text=True)
def send(m): p.stdin.write(json.dumps(m) + "\n"); p.stdin.flush()
send({"id": 1, "method": "initialize", "params": {"clientInfo": {"name": "v813-probe", "title": "v813", "version": "1"}, "capabilities": None}})
p.stdout.readline()
send({"method": "initialized"})
send({"id": 2, "method": "account/rateLimits/read", "params": None})
deadline = time.time() + 15
while time.time() < deadline:
    r = json.loads(p.stdout.readline())
    if r.get("id") == 2:
        rl = r["result"]["rateLimits"]
        out = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "label": sys.argv[1] if len(sys.argv) > 1 else "",
               "primary": rl.get("primary"), "secondary": rl.get("secondary"),
               "reset_credits": (r["result"].get("rateLimitResetCredits") or {}).get("availableCount")}
        print(json.dumps(out))
        break
p.terminate()
