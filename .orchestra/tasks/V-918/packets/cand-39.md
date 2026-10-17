# Candidate cand-39

## ORIGIN commit 0d8208a776 (2026-08-21): опрос дашборда: фазовый сдвиг и 304 на /api/sessions
(diff of code only, excluding .orchestra/ and *.md; capped 1200 lines)

diff --git a/app/routes/sessions.py b/app/routes/sessions.py
index caadff3f1..ab98d9c34 100644
--- a/app/routes/sessions.py
+++ b/app/routes/sessions.py
@@ -1,11 +1,13 @@
 """Session routes: CRUD, send, stream, merge/switch, model/prompt/description management."""
 
 import asyncio
+import hashlib
+import json
 import logging
 import math
 import re
 import sqlite3
 from contextlib import AsyncExitStack
 from pathlib import Path
 from typing import Optional
 
@@ -211,19 +213,37 @@ class OpenFanRequest(BaseModel):
             return v
         if not math.isfinite(v):
             raise ValueError("deadline_seconds must be finite")
         if v < 0 or v > 86400:
             raise ValueError("deadline_seconds must be within [0, 86400]")
         return v
 
 
+def _conditional(request: Request, payload) -> JSONResponse:
+    """Отдать payload с ETag, а при совпадении If-None-Match — пустой 304.
+
+    Дашборд опрашивает `/api/sessions` каждые 3 секунды, и ответ весит 48.8 КБ даже когда
+    ничего не изменилось (замер 21.08) — почти мегабайт в минуту и один из ШЕСТИ браузерных
+    слотов, из которых один навсегда занят SSE. Условный запрос убирает тело целиком, пока
+    состояние агентов не поменялось; ключ считается от самого ответа, поэтому рассинхрон
+    невозможен by design. `no-cache` означает «кешируй, но всегда переспрашивай» — без него
+    браузер не пришлёт If-None-Match.
+    """
+    body = json.dumps(payload, ensure_ascii=False, default=str, sort_keys=True)
+    tag = '"' + hashlib.md5(body.encode()).hexdigest() + '"'
+    headers = {"ETag": tag, "Cache-Control": "no-cache"}
+    if request.headers.get("if-none-match") == tag:
+        return JSONResponse(None, status_code=304, headers=headers)
+    return JSONResponse(payload, headers=headers)
+
+
 @router.get("/api/sessions")
-async def list_sessions(scope: Optional[str] = None):
-    return manager.list_sessions(scope)
+async def list_sessions(request: Request, scope: Optional[str] = None):
+    return _conditional(request, manager.list_sessions(scope))
 
 
 @router.post("/api/sessions", status_code=201)
 async def create_session(req: CreateSessionRequest):
     from app.routes.system import _is_safe_path
     if not _is_safe_path(req.cwd):
         return JSONResponse({"error": f"cwd not in allowed paths: {req.cwd}"}, status_code=403)
     scope = req.scope or req.cwd
diff --git a/app/static/js/app.js b/app/static/js/app.js
index 2031e3f83..84bac088a 100644
--- a/app/static/js/app.js
+++ b/app/static/js/app.js
@@ -928,28 +928,44 @@ document.addEventListener('DOMContentLoaded', () => {
     // Только после load: холодная синхронизация ~100 КБ не должна делить узкий канал
     // с загрузкой самой страницы (HTTP/1.1, 6 соединений, одно занято SSE).
     window.addEventListener('load', initStoreSync, {once: true});
 });
 
 let eventSource = null;
 
 const _POLL_MAX_BACKOFF_MS = 120000;
+// Ширина разведения фаз. Меньше самого частого интервала (3 с), чтобы сдвиг не
+// превращался в заметную задержку обновления.
+const _POLL_PHASE_SPREAD_MS = 900;
 const _pollers = new Map();
 const _pollTimers = new Map();
 const _pollInFlight = new Map();
 const _pollFailures = new Map();
 
 function _pollCanRun() {
     return !document.hidden && navigator.onLine !== false;
 }
 
+// Фазовый сдвиг: у поллеров базы кратны друг другу (3000/5000/8000/10000/15000/60000),
+// поэтому они регулярно совпадают и бьют пачкой в шесть соединений браузера, одно из
+// которых навсегда держит SSE. Сдвиг детерминирован по имени ключа — он не «размазывает
+// случайностью», а разводит поллеры по постоянным фазам, так что совпадение перестаёт
+// быть периодическим. Замер 21.08: сам туннель прогоняет 20 параллельных запросов за
+// 0.43 с, то есть узкое место — одновременность, а не канал.
+function _pollPhase(key) {
+    let h = 0;
+    for (let i = 0; i < key.length; i++) h = (h * 31 + key.charCodeAt(i)) | 0;
+    return Math.abs(h) % _POLL_PHASE_SPREAD_MS;
+}
+
 function _pollDelay(key, base) {
     const failures = _pollFailures.get(key) || 0;
-    return Math.min(base * (2 ** failures), _POLL_MAX_BACKOFF_MS);
+    if (failures) return Math.min(base * (2 ** failures), _POLL_MAX_BACKOFF_MS);
+    return base + _pollPhase(key);
 }
 
 function _pollNoteFailure(key, error) {
     if (!key || !error) return;
     const transient = navigator.onLine === false
         || ['TimeoutError', 'TypeError', 'AbortError'].includes(error.name)
         || (Number(error.status) >= 500 && Number(error.status) < 600);
     if (transient) _pollFailures.set(key, Math.min((_pollFailures.get(key) || 0) + 1, 8));
diff --git a/tests/test_sessions_conditional.py b/tests/test_sessions_conditional.py
new file mode 100644
index 000000000..e079e1ec0
--- /dev/null
+++ b/tests/test_sessions_conditional.py
@@ -0,0 +1,58 @@
+"""`/api/sessions` отвечает 304, пока состояние агентов не изменилось.
+
+Дашборд опрашивает этот маршрут каждые 3 секунды, и ответ весит 48.8 КБ даже когда
+ничего не поменялось (замер 21.08) — почти мегабайт в минуту и один из шести браузерных
+слотов, из которых один навсегда держит SSE.
+"""
+from unittest.mock import patch
+
+import pytest
+from fastapi.testclient import TestClient
+
+
+@pytest.fixture
+def client(tmp_path, monkeypatch):
+    import app.db as dbmod
+
+    monkeypatch.setattr(dbmod, "DB_PATH", tmp_path / "t.db")
+    dbmod.init_db()
+    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
+    from tests.conftest import make_backend_mock
+
+    with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
+        from app.main import app, manager
+
+        manager.sessions.clear()
+        with TestClient(app) as c:
+            yield c
+
+
+def _get(client, **headers):
+    return client.get("/api/sessions?scope=/scope", headers=headers)
+
+
+def test_unchanged_state_costs_no_body(client):
+    first = _get(client)
+    assert first.status_code == 200
+    tag = first.headers.get("ETag")
+    assert tag, "без ETag браузер не пришлёт If-None-Match и тело поедет каждые 3 с"
+    # `no-cache` = «кешируй, но всегда переспрашивай». Без него ревалидации не будет вовсе.
+    assert first.headers.get("Cache-Control") == "no-cache"
+
+    repeat = _get(client, **{"If-None-Match": tag})
+    assert repeat.status_code == 304
+    # 304 по спецификации не несёт полезной нагрузки; на живом стенде это 48.8 КБ -> 0.
+    assert b"session" not in repeat.content
+
+
+def test_stale_etag_still_returns_the_payload(client):
+    """Обратное направление: несовпадение обязано отдать тело, иначе дашборд ослепнет."""
+    fresh = _get(client, **{"If-None-Match": '"definitely-not-the-current-state"'})
+    assert fresh.status_code == 200
+    assert fresh.headers.get("ETag") != '"definitely-not-the-current-state"'
+
+
+def test_etag_tracks_the_payload_not_the_clock(client):
+    """Ключ считается от самого ответа — два запроса подряд дают один и тот же тег."""
+    a, b = _get(client), _get(client)
+    assert a.headers["ETag"] == b.headers["ETag"]


## LATER FIX a121102291 (2.8 days later): fix: send an empty 304 sessions response
lines of origin it changed/deleted: 3
(code only, capped 400 lines)

fix: send an empty 304 sessions response


diff --git a/app/routes/sessions.py b/app/routes/sessions.py
index f20b297c5..fd1d82cb6 100644
--- a/app/routes/sessions.py
+++ b/app/routes/sessions.py
@@ -7,17 +7,17 @@ import logging
 import math
 import re
 import sqlite3
 from contextlib import AsyncExitStack
 from pathlib import Path
 from typing import Optional
 
 from fastapi import APIRouter, Request
-from fastapi.responses import JSONResponse
+from fastapi.responses import JSONResponse, Response
 from starlette.responses import StreamingResponse
 from pydantic import BaseModel, field_validator, model_validator
 
 from app.db import (
     get_all_sessions,
     get_history_logs,
     get_log,
     get_logs,
@@ -215,31 +215,31 @@ class OpenFanRequest(BaseModel):
             return v
         if not math.isfinite(v):
             raise ValueError("deadline_seconds must be finite")
         if v < 0 or v > 86400:
             raise ValueError("deadline_seconds must be within [0, 86400]")
         return v
 
 
-def _conditional(request: Request, payload) -> JSONResponse:
+def _conditional(request: Request, payload) -> Response:
     """Отдать payload с ETag, а при совпадении If-None-Match — пустой 304.
 
     Дашборд опрашивает `/api/sessions` каждые 3 секунды, и ответ весит 48.8 КБ даже когда
     ничего не изменилось (замер 21.08) — почти мегабайт в минуту и один из ШЕСТИ браузерных
     слотов, из которых один навсегда занят SSE. Условный запрос убирает тело целиком, пока
     состояние агентов не поменялось; ключ считается от самого ответа, поэтому рассинхрон
     невозможен by design. `no-cache` означает «кешируй, но всегда переспрашивай» — без него
     браузер не пришлёт If-None-Match.
     """
     body = json.dumps(payload, ensure_ascii=False, default=str, sort_keys=True)
     tag = '"' + hashlib.md5(body.encode()).hexdigest() + '"'
     headers = {"ETag": tag, "Cache-Control": "no-cache"}
     if request.headers.get("if-none-match") == tag:
-        return JSONResponse(None, status_code=304, headers=headers)
+        return Response(status_code=304, headers=headers)
     return JSONResponse(payload, headers=headers)
 
 
 @router.get("/api/sessions")
 async def list_sessions(request: Request, scope: Optional[str] = None):
     return _conditional(request, manager.list_sessions(scope))
 
 
diff --git a/tests/test_sessions_conditional.py b/tests/test_sessions_conditional.py
index e079e1ec0..aed2b53b5 100644
--- a/tests/test_sessions_conditional.py
+++ b/tests/test_sessions_conditional.py
@@ -37,17 +37,18 @@ def test_unchanged_state_costs_no_body(client):
     tag = first.headers.get("ETag")
     assert tag, "без ETag браузер не пришлёт If-None-Match и тело поедет каждые 3 с"
     # `no-cache` = «кешируй, но всегда переспрашивай». Без него ревалидации не будет вовсе.
     assert first.headers.get("Cache-Control") == "no-cache"
 
     repeat = _get(client, **{"If-None-Match": tag})
     assert repeat.status_code == 304
     # 304 по спецификации не несёт полезной нагрузки; на живом стенде это 48.8 КБ -> 0.
-    assert b"session" not in repeat.content
+    assert repeat.content == b""
+    assert "content-type" not in repeat.headers
 
 
 def test_stale_etag_still_returns_the_payload(client):
     """Обратное направление: несовпадение обязано отдать тело, иначе дашборд ослепнет."""
     fresh = _get(client, **{"If-None-Match": '"definitely-not-the-current-state"'})
     assert fresh.status_code == 200
     assert fresh.headers.get("ETag") != '"definitely-not-the-current-state"'
 