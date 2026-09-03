import json, os, subprocess, sys, time, threading

HOME = "/tmp/probe224/codexhome"
PROBE = "/home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-secrets-argv/docs/tasks/224/probe/probe_mcp.py"
OUT = "/tmp/probe224/env-codexhome.json"
os.makedirs(HOME, exist_ok=True); os.chmod(HOME, 0o700)
# auth by symlink — part of what we are testing for feasibility
link = os.path.join(HOME, "auth.json")
if not os.path.exists(link): os.symlink(os.path.expanduser("~/.codex/auth.json"), link)
cfg = f'''[mcp_servers.probe]
command = "python3"
args = ["{PROBE}"]
enabled = true

[mcp_servers.probe.env]
PROBE_OUT = "{OUT}"
PROBE_FROM_CODEX_HOME = "MARKER_CODEX_HOME"
'''
p = os.path.join(HOME, "config.toml"); open(p, "w").write(cfg); os.chmod(p, 0o600)
if os.path.exists(OUT): os.remove(OUT)

env = dict(os.environ); env["CODEX_HOME"] = HOME
proc = subprocess.Popen(["codex", "app-server", "--stdio"], stdin=subprocess.PIPE,
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, text=True)
threading.Thread(target=lambda: [sys.stderr.write("STDERR: "+l) for l in proc.stderr], daemon=True).start()

def send(obj):
    proc.stdin.write(json.dumps(obj) + "\n"); proc.stdin.flush()

send({"jsonrpc":"2.0","id":1,"method":"initialize","params":{"clientInfo":{"name":"orchestra","title":"Orchestra","version":"1"}}})
send({"jsonrpc":"2.0","method":"initialized","params":{}})
send({"jsonrpc":"2.0","id":2,"method":"thread/start","params":{"cwd":"/tmp","approvalPolicy":"never","sandbox":"danger-full-access"}})

deadline = time.time() + 45
while time.time() < deadline:
    if os.path.exists(OUT):
        print("PROBE LAUNCHED FROM $CODEX_HOME/config.toml:", open(OUT).read()); break
    time.sleep(0.5)
else:
    print("PROBE NOT LAUNCHED within 45s")
proc.terminate()
try: proc.wait(5)
except Exception: proc.kill()
