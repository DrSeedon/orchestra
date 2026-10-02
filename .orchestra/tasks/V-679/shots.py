"""Изолированный дашборд из этого worktree + синтетические задания → скриншоты панели JOBS."""
import json, sqlite3, sys, tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from tests.test_frontend import _seed_dashboard_db, _start_dashboard_server, _stop_dashboard_server
from playwright.sync_api import sync_playwright

OUT = Path(__file__).parent
tmp = Path(tempfile.mkdtemp())
db = tmp / "orchestra.db"
_seed_dashboard_db(db)
now = datetime.now(timezone.utc)
iso = lambda d: d.isoformat()
rows = []
def add(i, typ, status, cfg, msg, by, created, trig=None, exp=None, trig_done=None, out="", err=None):
    rows.append((i, typ, json.dumps(cfg), msg, "fe-orch-id", "fe-orch", "/tmp/fe-scope", by, status, err,
                 iso(exp or now + timedelta(days=1)), iso(trig) if trig else None, iso(created),
                 iso(trig_done) if trig_done else None, out))
add("t1", "timer", "active", {"delay_seconds": 10800}, "НАПОМИНАНИЕ: завтра после пар встреча — спросить владельца про договор и сверить сроки платежей.", "fe-orch", now, trig=now + timedelta(hours=3))
add("t2", "timer", "active", {"delay_seconds": 172800}, "ЛИД #69: через 2 дня проверить, ответил ли клиент на предложение, и если нет — написать повторно.", "fe-orch", now - timedelta(hours=2), trig=now + timedelta(days=2))
add("t3", "timer", "triggered", {"delay_seconds": 180}, "Проверка после рестарта Orchestra: убедиться, что воркеры подняты.", "fe-orch", now - timedelta(hours=5), trig=now - timedelta(hours=4, minutes=57), trig_done=now - timedelta(hours=4, minutes=57))
add("c1", "cron", "active", {"cron_expr": "0 2 * * *", "no_expiry": True, "last_fired_at": iso(now - timedelta(hours=9)), "fire_count": 12}, "Ночной отчёт по квотам: свести расход за сутки и положить в хронику.", "fe-orch", now - timedelta(days=12), out="fired #12")
add("c2", "cron_command", "active", {"cron_expr": "*/3 * * * *", "command": "echo ok", "pattern": "ESCALATE", "no_expiry": True}, "Сторож ugrep: убивает раздувшийся ugrep, будит при подозрении на своп.", "fe-orch", now - timedelta(days=17))
add("i1", "idle", "active", {"no_expiry": True}, "Разбуди меня, когда все воркеры и фоновые задания затихнут.", "fe-orch", now - timedelta(days=3))
add("w1", "command", "active", {"command": "echo ok", "pattern": "DOWN", "interval_seconds": 600, "no_expiry": True}, "Проверка живости сервиса painter; будить, если пять попыток подряд неудачны.", "other-agent", now - timedelta(days=9))
add("r1", "run", "active", {"command": "sleep 99999"}, "OCR сборника: дождаться окончания и сообщить, сколько страниц распознано.", "fe-orch", now - timedelta(minutes=14))
add("r2", "run", "failed", {"command": "true"}, "OCR первой партии.", "fe-orch", now - timedelta(hours=7), err="Прерван рестартом сервиса, повторный запуск не выполнялся.")
add("t4", "timer", "active", {"delay_seconds": 600}, "Старый таймер, который не сработал вовремя.", "fe-orch", now - timedelta(hours=3), trig=now - timedelta(hours=2, minutes=50))
with sqlite3.connect(db) as c:
    c.executemany("INSERT INTO bg_jobs (id,type,config,message,target_session_id,target_name,target_scope,created_by_name,status,error,expires_at,trigger_at,created_at,triggered_at,last_output) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)

proc, origin = _start_dashboard_server(db)
try:
    with sync_playwright() as p:
        b = p.chromium.launch()
        page = b.new_page(viewport={"width": 1500, "height": 1000})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(origin, wait_until="domcontentloaded")
        page.wait_for_selector("#agent-list")
        page.evaluate("localStorage.removeItem('orchestra.jobsView')")
        page.click("[data-left-tab=jobs]")
        page.wait_for_selector(".job-card")
        page.screenshot(path=str(OUT / "jobs-by-agent.png"))
        page.click("[data-job-toggle=c2] >> nth=0") if False else None
        page.click(".job-card[data-job-id=c2] .job-msg")
        page.screenshot(path=str(OUT / "jobs-expanded.png"))
        page.click("[data-job-view=timeline]")
        page.wait_for_selector(".job-now")
        page.screenshot(path=str(OUT / "jobs-timeline.png"))
        page.once("dialog", lambda d: d.accept())
        page.click(".job-card[data-job-id=t2] .job-cancel-btn")
        page.wait_for_timeout(1500)
        state = page.evaluate("fetch('/api/bg/jobs?scope=/tmp/fe-scope').then(r=>r.json()).then(j=>j.find(x=>x.id==='t2').status)")
        print("t2 after cancel:", state, "errors:", errors)
        b.close()
finally:
    _stop_dashboard_server(proc)
