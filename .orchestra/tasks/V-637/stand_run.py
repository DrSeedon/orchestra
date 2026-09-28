"""V-637: run scenarios in the real stand chat through the browser (screenshots), check them over ssh.

  STAND_HOST=... stand_run.py <out_dir> <ids,...>
Nothing is reset: the messages continue the orchestrator's existing chat.
"""
import json, os, shlex, subprocess, sys, time
from pathlib import Path
from types import SimpleNamespace
from playwright.sync_api import sync_playwright
from scenarios import SCENARIOS, WS

HOST = os.environ["STAND_HOST"]
DIR = "/home/kesha/orchestra-reestr-demo"
env_f = dict(l.strip().split("=", 1) for l in open("/home/kesha/projects/seedon/secrets/reestr-demo-access.env") if "=" in l and not l.startswith("#"))
U, P, BASE = env_f["DEMO_DASHBOARD_USER"], env_f["DEMO_DASHBOARD_PASSWORD"], env_f["DEMO_URL"].rstrip("/")
SCOPE = "%2Fworkspace%2Fproject"


def ssh(cmd, timeout=90):
    p = subprocess.run(["ssh", "-o", "BatchMode=yes", f"root@{HOST}", cmd], capture_output=True, text=True, timeout=timeout)
    return SimpleNamespace(code=p.returncode, out=p.stdout + p.stderr)


class Env:
    task_base = 0
    py_before = set()
    final_text = ""

    def run(self, cmd):
        return ssh("sudo -u kesha bash -c " + shlex.quote(cmd))

    def sh(self, cmd):
        return self.run(cmd).out

    def exists(self, path):
        return ssh(f"test -e {shlex.quote(path)}").code == 0

    def read(self, path):
        return ssh(f"cat {shlex.quote(path)}").out

    def sql(self, q):
        code = ("import sqlite3,json,sys;c=sqlite3.connect('file:%s/data/orchestra.db?mode=ro',uri=True);c.row_factory=sqlite3.Row;"
                "print(json.dumps([dict(r) for r in c.execute(sys.argv[1])],ensure_ascii=False))" % DIR)
        return json.loads(ssh(f"python3 -c {shlex.quote(code)} {shlex.quote(q)}").out or "[]")


def main():
    out = Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)
    ids = sys.argv[2].split(",")
    env = Env(); rows = []
    with sync_playwright() as p:
        b = p.chromium.launch(); ctx = b.new_context(viewport={"width": 1440, "height": 900}, locale="ru-RU")
        pg = ctx.new_page()
        pg.goto(BASE); pg.fill("input[name=username]", U); pg.fill("input[name=password]", P)
        pg.click("button[type=submit]"); pg.wait_for_timeout(6000)

        def statuses():
            return {s["name"]: s["status"] for s in pg.request.get(f"{BASE}/api/sessions?scope={SCOPE}").json()}

        def send(msg):
            ta = pg.locator("textarea:visible").first; ta.fill(msg)
            pg.get_by_text("Отправить", exact=True).first.click()
            t0 = time.time(); idle = None; seen = False
            while time.time() - t0 < 900:
                pg.wait_for_timeout(3000)
                busy = any(v in ("running", "waiting", "starting") for v in statuses().values())
                seen |= busy
                if busy or (not seen and time.time() - t0 < 30):
                    idle = None; continue
                idle = idle or time.time()
                if time.time() - idle >= 25:
                    break
            pg.wait_for_timeout(1500)
            return time.time() - t0

        cp = os.environ.get("START_CP", "s0")
        for sc in [next(s for s in SCENARIOS if s["id"] == i) for i in ids]:
            for attempt in range(1, 4):
                tag = f"{sc['id']}-a{attempt}"
                base = env.sql("select coalesce(max(id),0) m from logs")[0]["m"]
                tu = env.sql("select coalesce(max(id),0) m from turn_usage")[0]["m"]
                env.task_base = env.sql("select coalesce(max(id),0) m from tm_tasks")[0]["m"]
                env.workers_before = {r["name"] for r in env.sql("select name from sessions where is_orchestrator=0")}
                env.py_before = set(env.sh(f"cd {WS} && ls *.py 2>/dev/null").split())
                dt = send(sc["msg"]); n = 1
                def final():
                    r = env.sql(f"select content from logs l join sessions s on s.id=l.session_id where l.id>{base} and s.name='orchestrator' and l.type='text' order by l.id")
                    env.final_text = r[-1]["content"] if r else ""
                final(); ok, detail = sc["check"](env)
                for follow in sc.get("followups", []):
                    if ok: break
                    dt += send(follow); n += 1; final(); ok, detail = sc["check"](env)
                pg.screenshot(path=str(out / f"{tag}.png"))
                logs = env.sql(f"select l.id,s.name,l.type,l.tool_name,l.tool_is_error,l.content from logs l join sessions s on s.id=l.session_id where l.id>{base} order by l.id")
                tok = env.sql(f"select coalesce(sum(input_tokens),0) i, coalesce(sum(output_tokens),0) o, count(*) n from turn_usage where id>{tu}")[0]
                row = dict(scenario=sc["id"], attempt=attempt, ok=bool(ok), detail=detail, seconds=round(dt), user_messages=n,
                           turns=tok["n"], in_tokens=tok["i"], out_tokens=tok["o"],
                           tool_calls=sum(1 for l in logs if l["type"] == "tool"),
                           tool_errors=sum(1 for l in logs if l["type"] == "tool_result" and l["tool_is_error"]),
                           final_text=env.final_text[:1500])
                (out / f"{tag}.logs.json").write_text(json.dumps(logs, ensure_ascii=False, indent=1))
                (out / f"{tag}.row.json").write_text(json.dumps(row, ensure_ascii=False, indent=1))
                print(json.dumps({k: row[k] for k in ("scenario", "attempt", "ok", "detail", "seconds", "tool_calls", "in_tokens", "out_tokens")}, ensure_ascii=False), flush=True)
                if ok:
                    cp = sc["id"]
                    print(ssh(f"/root/v637-checkpoint.sh checkpoint {cp}", timeout=300).out.strip(), flush=True)
                    break
                print(ssh(f"/root/v637-checkpoint.sh restore {cp}", timeout=300).out.strip(), flush=True)
                pg.goto(BASE); pg.wait_for_timeout(5000)
                if pg.locator("input[name=username]").count():
                    pg.fill("input[name=username]", U); pg.fill("input[name=password]", P)
                    pg.click("button[type=submit]"); pg.wait_for_timeout(6000)
            else:
                print("GIVING UP on", sc["id"], flush=True)
                break
        b.close()


if __name__ == "__main__":
    main()
