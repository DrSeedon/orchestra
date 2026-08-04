"""#82 — что делает СЕРВЕР, когда агент представился именем, которого больше нет.

Изолированная временная БД, живую не трогаем.
"""
import os
import tempfile
from pathlib import Path

os.environ.pop("DASHBOARD_USER", None)
os.environ.pop("DASHBOARD_PASSWORD", None)

import app.db as dbmod

tmp = Path(tempfile.mkdtemp(prefix="probe82-"))
dbmod.DB_PATH = tmp / "probe.db"
dbmod.init_db()

SCOPE = "/scope"

print("== P1: тест-лок, взят под старым именем ==")
print("acquire(old)      :", dbmod.acquire_test_lock(SCOPE, "old-name", "full suite"))
print("release(new)      :", dbmod.release_test_lock(SCOPE, "new-name"))
print("acquire(new)      :", dbmod.acquire_test_lock(SCOPE, "new-name", "retry"))
print("status            :", dict(dbmod.get_test_lock(SCOPE) or {}))
print("release(old)      :", dbmod.release_test_lock(SCOPE, "old-name"))

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app, raise_server_exceptions=False)

print("\n== P2: bg-джоб на несуществующее имя ==")
r = client.post("/api/bg/jobs", json={
    "type": "timer", "config": {"delay_seconds": 3600}, "message": "wake",
    "target_name": "ghost-name", "target_scope": SCOPE,
    "timeout_seconds": 3600, "created_by": "ghost-name",
})
print("status:", r.status_code, "body:", r.text[:300])

print("\n== P3: update_progress от несуществующего имени ==")
r = client.post("/api/sessions/ghost-name/progress",
                json={"scope": SCOPE, "percent": 50, "status": "работаю"})
print("status:", r.status_code, "body:", r.text[:300])

print("\n== P4: send с sender=несуществующее имя ==")
r = client.post("/api/sessions/ghost-name/send",
                json={"message": "hi", "scope": SCOPE, "sender": "another-ghost"})
print("status:", r.status_code, "body:", r.text[:300])

print("\n== P5: report_bug от несуществующего имени ==")
r = client.post("/api/report_bug", json={
    "title": "t", "description": "d", "reporter": "ghost-name", "scope": SCOPE,
})
print("status:", r.status_code, "body:", r.text[:200])

client.close()
print("\ntmp db:", dbmod.DB_PATH)
