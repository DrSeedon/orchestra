"""V-637 driver: send each scenario message to the orchestrator of a stand, wait for quiet,
collect tool/turn counts from the stand DB, dump raw logs and run the machine check.

  local:  bench.py local <out_dir> <scenario ids|all> [--runs N] [--chain]
  A local stand = /home/kesha/bench-v637 (copy of the stand code on port 8912, own DB/workspace);
  reset.sh restores its pristine state before every non-chain run.
"""
import json, subprocess, sys, time, urllib.request, argparse, os
from pathlib import Path
from types import SimpleNamespace
from scenarios import SCENARIOS, WS

B = "/home/kesha/bench-v637"
DB = f"{B}/data/orchestra.db"
URL = "http://127.0.0.1:8912"
TOKEN = [l.split("=", 1)[1].strip() for l in open(f"{B}/stand/.env") if l.startswith("INTERNAL_TOKEN=")][0]
SCOPE = "/workspace/project"


class Env:
    def __init__(self):
        self.final_text = ""; self.task_base = 4; self.py_before = set()

    def run(self, cmd):
        p = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True, timeout=60)
        return SimpleNamespace(code=p.returncode, out=p.stdout + p.stderr)

    def sh(self, cmd):
        return self.run(cmd).out

    def exists(self, path):
        return os.path.exists(path)

    def read(self, path):
        return open(path, encoding="utf-8", errors="replace").read()

    def sql(self, q):
        p = subprocess.run(["sqlite3", "-json", DB, q], capture_output=True, text=True)
        return json.loads(p.stdout) if p.stdout.strip() else []


def api(method, path, body=None):
    req = urllib.request.Request(URL + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read() or b"null")


def statuses():
    return {s["name"]: s["status"] for s in api("GET", f"/api/sessions?scope={SCOPE.replace('/', '%2F')}")}


def wait_quiet(timeout=900, quiet=25):
    t0 = time.time(); seen = False; idle = None
    while time.time() - t0 < timeout:
        time.sleep(3)
        busy = any(v in ("running", "waiting", "starting") for v in statuses().values())
        seen |= busy
        if busy or (not seen and time.time() - t0 < 30):
            idle = None; continue
        idle = idle or time.time()
        if time.time() - idle >= quiet:
            return time.time() - t0 - quiet, False
    return time.time() - t0, True


def collect_final(env, base):
    rows = env.sql(f"select content from logs l join sessions s on s.id=l.session_id where l.id>{base} and s.name='orchestrator' and l.type='text' order by l.id")
    env.final_text = rows[-1]["content"] if rows else ""


def run_scenario(env, sc, out: Path, tag):
    base = env.sql("select coalesce(max(id),0) m from logs")[0]["m"]
    tu = env.sql("select coalesce(max(id),0) m from turn_usage")[0]["m"]
    env.task_base = env.sql("select coalesce(max(id),0) m from tm_tasks")[0]["m"]
    env.py_before = set(env.sh(f"cd {WS} && ls *.py 2>/dev/null").split())
    api("POST", f"/api/sessions/orchestrator/send", {"scope": SCOPE, "message": sc["msg"], "channel": "dashboard"})
    dt, timed_out = wait_quiet()
    sent = 1
    for follow in sc.get("followups", []):
        # a live user answers again when the first answer did not deliver
        collect_final(env, base)
        if sc["check"](env)[0]:
            break
        api("POST", f"/api/sessions/orchestrator/send", {"scope": SCOPE, "message": follow, "channel": "dashboard"})
        d2, t2 = wait_quiet(); dt += d2; timed_out |= t2; sent += 1
    logs = env.sql(f"select l.id,s.name,l.type,l.tool_name,l.tool_is_error,l.content from logs l join sessions s on s.id=l.session_id where l.id>{base} order by l.id")
    turns = env.sql(f"select s.name,t.ok,t.stop_reason,t.input_tokens,t.output_tokens from turn_usage t join sessions s on s.id=t.session_id where t.id>{tu}")
    orch_text = [l["content"] for l in logs if l["name"] == "orchestrator" and l["type"] == "text"]
    env.final_text = orch_text[-1] if orch_text else ""
    ok, detail = sc["check"](env)
    tools = [l for l in logs if l["type"] == "tool"]
    errs = [l for l in logs if l["type"] == "error"]
    row = dict(scenario=sc["id"], tag=tag, user_messages=sent, ok=bool(ok), detail=detail, seconds=round(dt), timed_out=timed_out,
               turns=len(turns), turns_failed=sum(1 for t in turns if not t["ok"]),
               tool_calls=len(tools), tool_errors=sum(1 for l in logs if l["type"] == "tool_result" and l["tool_is_error"]),
               loop_errors=len(errs), in_tokens=sum(t["input_tokens"] for t in turns), out_tokens=sum(t["output_tokens"] for t in turns),
               tools_by_name={n: sum(1 for l in tools if (l["tool_name"] or "?") == n) for n in sorted({l["tool_name"] or "?" for l in tools})},
               final_text=env.final_text[:1500])
    (out / f"{tag}.logs.json").write_text(json.dumps(logs, ensure_ascii=False, indent=1))
    (out / f"{tag}.row.json").write_text(json.dumps(row, ensure_ascii=False, indent=1))
    return row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out"); ap.add_argument("ids"); ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--chain", action="store_true"); ap.add_argument("--label", default="")
    a = ap.parse_args()
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    ids = [s["id"] for s in SCENARIOS] if a.ids == "all" else a.ids.split(",")
    env = Env()
    for r in range(1, a.runs + 1):
        if a.chain:
            subprocess.run([f"{B}/reset.sh"], check=True)
        for sc in [s for s in SCENARIOS if s["id"] in ids]:
            if not a.chain:
                subprocess.run([f"{B}/reset.sh"], check=True)
            tag = f"{a.label}{sc['id']}-run{r}"
            row = run_scenario(env, sc, out, tag)
            print(json.dumps({k: row[k] for k in ("tag", "ok", "detail", "seconds", "turns", "tool_calls", "tool_errors", "loop_errors", "in_tokens", "out_tokens")}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
