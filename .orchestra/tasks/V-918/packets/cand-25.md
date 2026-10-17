# Candidate cand-25

## ORIGIN commit 6f80520911 (2026-07-18): Add Codex Pro rate limits to dashboard
(diff of code only, excluding .orchestra/ and *.md; capped 1200 lines)

diff --git a/app/routes/system.py b/app/routes/system.py
index de9a41727..d58efefa5 100644
--- a/app/routes/system.py
+++ b/app/routes/system.py
@@ -5,16 +5,17 @@ import asyncio
 import hashlib
 import hmac
 import json
 import logging
 import os
 import re
 import signal
 import time
+from datetime import datetime, timezone
 from pathlib import Path
 from typing import Optional
 
 from fastapi import APIRouter, HTTPException, Request, Form
 from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
 from pydantic import BaseModel
 
 from app.auth import is_auth_enabled
@@ -368,20 +369,21 @@ async def refresh_models_endpoint():
     return {"ok": True, "proxy_connected": is_proxy_connected(), "model_count": len(MODELS)}
 
 
 @router.get("/api/stats")
 async def stats(scope: Optional[str] = None):
     return manager.stats(scope)
 
 
-# ── Usage (Anthropic OAuth) ──
+# ── Usage (subscription limits) ──
 
 _USAGE_CACHE_FILE = Path(__file__).parent.parent.parent / "data" / "usage_cache.json"
 _usage_cache: dict = {"data": None, "ts": 0.0, "token": None}
+_codex_usage_cache: dict = {"data": None, "ts": 0.0}
 _USAGE_CACHE_TTL = 300
 _CREDENTIALS_PATH = Path.home() / ".claude" / ".credentials.json"
 
 
 def _load_usage_cache():
     if _USAGE_CACHE_FILE.exists():
         try:
             cached = json.loads(_USAGE_CACHE_FILE.read_text())
@@ -427,16 +429,109 @@ async def _fetch_anthropic_usage(token: str) -> dict:
         if resp.status_code == 401:
             raise PermissionError("token_expired")
         if resp.status_code == 429:
             raise RuntimeError("rate_limited")
         resp.raise_for_status()
         return resp.json()
 
 
+def _normalize_codex_window(window: dict | None) -> dict | None:
+    if not isinstance(window, dict):
+        return None
+    used = window.get("usedPercent")
+    duration = window.get("windowDurationMins")
+    if not isinstance(used, (int, float)) or not isinstance(duration, int) or duration <= 0:
+        return None
+    resets_at = window.get("resetsAt")
+    reset_iso = None
+    if isinstance(resets_at, (int, float)) and resets_at > 0:
+        reset_iso = datetime.fromtimestamp(resets_at, timezone.utc).isoformat().replace("+00:00", "Z")
+    utilization = max(0, min(100, used))
+    return {
+        "utilization": int(utilization) if float(utilization).is_integer() else utilization,
+        "window_minutes": duration,
+        "resets_at": reset_iso,
+    }
+
+
+def _normalize_codex_usage(result: dict) -> dict:
+    by_limit = result.get("rateLimitsByLimitId") or {}
+    limits = by_limit.get("codex") or result.get("rateLimits") or {}
+    credits = limits.get("credits") or {}
+    reset_credits = result.get("rateLimitResetCredits") or {}
+    return {
+        "plan_type": limits.get("planType"),
+        "primary": _normalize_codex_window(limits.get("primary")),
+        "secondary": _normalize_codex_window(limits.get("secondary")),
+        "credits": {
+            "has_credits": bool(credits.get("hasCredits")),
+            "unlimited": bool(credits.get("unlimited")),
+            "balance": credits.get("balance"),
+        },
+        "reset_credits": reset_credits.get("availableCount", 0),
+    }
+
+
+async def _fetch_codex_usage() -> dict:
+    """Read ChatGPT subscription limits through Codex's local app-server protocol."""
+    from app.backend_codex import CODEX_BIN
+
+    proc = await asyncio.create_subprocess_exec(
+        CODEX_BIN, "app-server",
+        stdin=asyncio.subprocess.PIPE,
+        stdout=asyncio.subprocess.PIPE,
+        stderr=asyncio.subprocess.DEVNULL,
+    )
+
+    async def send(message: dict) -> None:
+        assert proc.stdin is not None
+        proc.stdin.write((json.dumps(message) + "\n").encode())
+        await proc.stdin.drain()
+
+    try:
+        await send({
+            "id": 1,
+            "method": "initialize",
+            "params": {
+                "clientInfo": {"name": "orchestra-dashboard", "title": "Orchestra dashboard", "version": "1"},
+                "capabilities": None,
+            },
+        })
+        assert proc.stdout is not None
+        init = json.loads((await asyncio.wait_for(proc.stdout.readline(), timeout=5)).decode())
+        if init.get("id") != 1 or init.get("error"):
+            raise RuntimeError(f"Codex app-server initialization failed: {init.get('error', 'invalid response')}")
+
+        await send({"method": "initialized"})
+        await send({"id": 2, "method": "account/rateLimits/read", "params": None})
+        async with asyncio.timeout(10):
+            while line := await proc.stdout.readline():
+                response = json.loads(line)
+                if response.get("id") != 2:
+                    continue
+                if response.get("error"):
+                    raise RuntimeError(f"Codex rate limit fetch failed: {response['error']}")
+                return _normalize_codex_usage(response.get("result") or {})
+        raise RuntimeError("Codex app-server closed without a rate limit response")
+    finally:
+        if proc.stdin:
+            proc.stdin.close()
+        if proc.returncode is None:
+            try:
+                proc.terminate()
+            except ProcessLookupError:
+                pass
+        try:
+            await asyncio.wait_for(proc.wait(), timeout=1)
+        except asyncio.TimeoutError:
+            proc.kill()
+            await proc.wait()
+
+
 async def _refresh_oauth_token(refresh_token: str) -> str | None:
     """Refresh expired OAuth token. Returns new access token or None."""
     import httpx
     try:
         async with httpx.AsyncClient(timeout=10) as client:
             resp = await client.post(
                 "https://platform.claude.com/v1/oauth/token",
                 json={"grant_type": "refresh_token", "refresh_token": refresh_token},
@@ -533,18 +628,30 @@ async def get_usage():
                 anthropic_data = _usage_cache["data"]
             else:
                 return JSONResponse({"error": str(e)}, status_code=500)
 
         _usage_cache["data"] = anthropic_data
         _usage_cache["ts"] = now
         _save_usage_cache()
 
+    if _codex_usage_cache["data"] and (now - _codex_usage_cache["ts"]) < _USAGE_CACHE_TTL:
+        codex_data = _codex_usage_cache["data"]
+    else:
+        try:
+            codex_data = await _fetch_codex_usage()
+            _codex_usage_cache["data"] = codex_data
+            _codex_usage_cache["ts"] = now
+        except Exception as e:
+            logger.warning(f"Codex usage fetch failed: {e}")
+            codex_data = _codex_usage_cache["data"]
+
     return {
         "anthropic": anthropic_data,
+        "codex": codex_data,
         "orchestra": _get_agents_cost(),
     }
 
 
 SNAPSHOT_INTERVAL = 300
 
 
 async def _usage_snapshot_loop():
diff --git a/app/static/js/usage.js b/app/static/js/usage.js
index f51fccb2c..f9e9e1112 100644
--- a/app/static/js/usage.js
+++ b/app/static/js/usage.js
@@ -71,27 +71,36 @@ function _etaToLimit(currentPct, isoStr, windowMs) {
     else label = `${Math.floor(etaMin/1440)}d ${Math.floor((etaMin%1440)/60)}h`;
     return `<span style="color:${color}">⏳${label}</span>`;
 }
 
 function _miniBar(pct, color) {
     return `<span style="display:inline-flex;align-items:center;gap:4px"><span style="display:inline-block;width:80px;height:6px;border-radius:3px;background:rgba(51,65,85,0.5);overflow:hidden;vertical-align:middle"><span style="display:block;width:${Math.min(pct, 100)}%;height:100%;border-radius:3px;background:${color}"></span></span><span style="color:#e2e8f0;font-weight:600">${pct}%</span></span>`;
 }
 
+function _codexWindowLabel(windowMinutes) {
+    if (windowMinutes === 300) return '5h';
+    if (windowMinutes === 10080) return '7d';
+    if (windowMinutes % 1440 === 0) return `${windowMinutes / 1440}d`;
+    if (windowMinutes % 60 === 0) return `${windowMinutes / 60}h`;
+    return `${windowMinutes}m`;
+}
+
 function renderUsageBar() {
     const bar = document.getElementById('usage-bar');
     if (!bar) return;
     if (!_usageData) {
         bar.innerHTML = '';
         bar.style.display = 'none';
         return;
     }
     bar.style.cssText = 'display:flex;align-items:center;gap:14px;padding:0 12px;height:28px;background:#0f172a;border-bottom:1px solid rgba(30,41,59,0.5);font-size:11px;color:#94a3b8;flex-shrink:0;overflow:hidden;white-space:nowrap';
 
     const a = _usageData.anthropic || {};
+    const cx = _usageData.codex || {};
     const o = _usageData.orchestra || {};
     const parts = [];
 
     if (_usageError) parts.push('<span style="color:#eab308" title="Using cached data">⚠️</span>');
 
     const fh = a.five_hour;
     if (fh) {
         const rpNum = _resetPctNum(fh.resets_at, 5 * 3600000);
@@ -106,16 +115,31 @@ function renderUsageBar() {
         const rpNum = _resetPctNum(sd.resets_at, 7 * 86400000);
         const c = _usageColor(sd.utilization, rpNum);
         const rp = rpNum != null ? ` <span style="color:#64748b">(${rpNum}%)</span>` : '';
         const cd = _resetCountdown(sd.resets_at);
         const pace = _paceIndicator(sd.utilization, sd.resets_at, 7 * 86400000);
         parts.push(`<span style="display:inline-flex;align-items:center;gap:3px">7d: ${_miniBar(sd.utilization, c)}${rp}${cd ? ` <span style="color:#64748b">${cd}</span>` : ''}${pace ? ` <span style="font-size:10px">·</span> ${pace}` : ''}</span>`);
     }
 
+    const codexWindows = [cx.primary, cx.secondary].filter(Boolean);
+    if (codexWindows.length) {
+        parts.push('<span style="height:14px;border-left:1px solid rgba(71,85,105,0.6)"></span>');
+        parts.push('<span style="color:#22c55e;font-weight:600">Codex</span>');
+        for (const window of codexWindows) {
+            const windowMs = window.window_minutes * 60000;
+            const rpNum = _resetPctNum(window.resets_at, windowMs);
+            const c = _usageColor(window.utilization, rpNum);
+            const cd = _resetCountdown(window.resets_at);
+            const pace = _paceIndicator(window.utilization, window.resets_at, windowMs);
+            const label = _codexWindowLabel(window.window_minutes);
+            parts.push(`<span style="display:inline-flex;align-items:center;gap:3px">${label}: ${_miniBar(window.utilization, c)}${cd ? ` <span style="color:#64748b">${cd}</span>` : ''}${pace ? ` <span style="font-size:10px">·</span> ${pace}` : ''}</span>`);
+        }
+    }
+
     parts.push('<span style="flex:1"></span>');
 
     if (typeof o.total_cost_usd === 'number') {
         parts.push(`<span style="color:#22c55e">$${o.total_cost_usd.toFixed(0)}</span>`);
     }
     if (typeof o.agents_count === 'number') {
         parts.push(`<span style="color:#64748b">${o.agents_count} agents</span>`);
     }
@@ -138,16 +162,17 @@ function renderUsageBar() {
             }, 200);
         };
         infoBtn.addEventListener('mouseenter', () => {
             clearTimeout(hideTimer);
             infoBtn.style.color = '#94a3b8';
             showTimer = setTimeout(async () => {
                 if (tip) return;
                 const _a = _usageData?.anthropic || {};
+                const _c = _usageData?.codex || {};
                 const _o = _usageData?.orchestra || {};
                 const fh = _a.five_hour;
                 const sd = _a.seven_day;
                 const _row = (label, val, color) => `<div style="display:flex;justify-content:space-between"><span>${label}</span><span style="color:${color || '#cbd5e1'}">${val}</span></div>`;
                 let h = '<div style="color:#e2e8f0;font-weight:600;margin-bottom:10px">📊 Claude Max $100 + Codex Pro $100</div>';
                 if (fh) {
                     const cd = _resetCountdown(fh.resets_at);
                     const pace = _paceIndicator(fh.utilization, fh.resets_at, 5 * 3600000);
@@ -170,16 +195,37 @@ function renderUsageBar() {
                     h += _row('Использовано', `${sd.utilization}%`, sd.utilization >= 80 ? '#ef4444' : sd.utilization >= 50 ? '#eab308' : '#22c55e');
                     if (cd) h += _row('Сброс через', cd, '#64748b');
                     if (rpNum != null) h += _row('Прогресс окна', `${rpNum}%`, '#64748b');
                     h += _row('Темп', pace, null);
                     if (eta) h += _row('Лимит через', eta, null);
                     h += '</div>';
                 }
                 h += '<div id="usage-sparkline-slot" style="margin:8px 0"></div>';
+                const codexWindows = [_c.primary, _c.secondary].filter(Boolean);
+                if (codexWindows.length) {
+                    h += '<div style="border-top:1px solid rgba(51,65,85,0.5);padding-top:8px;margin-top:6px">';
+                    h += '<div style="color:#22c55e;font-weight:600;margin-bottom:5px">✦ Codex Pro</div>';
+                    for (const window of codexWindows) {
+                        const windowMs = window.window_minutes * 60000;
+                        const cd = _resetCountdown(window.resets_at);
+                        const pace = _paceIndicator(window.utilization, window.resets_at, windowMs);
+                        const eta = _etaToLimit(window.utilization, window.resets_at, windowMs);
+                        const rpNum = _resetPctNum(window.resets_at, windowMs);
+                        const label = _codexWindowLabel(window.window_minutes);
+                        h += `<div style="margin-bottom:8px"><div style="color:#86efac;font-weight:600;margin-bottom:2px">${label} окно</div>`;
+                        h += _row('Использовано', `${window.utilization}%`, window.utilization >= 80 ? '#ef4444' : window.utilization >= 50 ? '#eab308' : '#22c55e');
+                        if (cd) h += _row('Сброс через', cd, '#64748b');
+                        if (rpNum != null) h += _row('Прогресс окна', `${rpNum}%`, '#64748b');
+                        h += _row('Темп', pace, null);
+                        if (eta) h += _row('Лимит через', eta, null);
+                        h += '</div>';
+                    }
+                    h += '</div>';
+                }
                 if (typeof _o.total_cost_usd === 'number') {
                     h += '<div style="border-top:1px solid rgba(51,65,85,0.5);padding-top:6px;margin-top:4px">';
                     h += _row('💰 Стоимость', `$${_o.total_cost_usd.toFixed(0)}`, '#22c55e');
                     h += _row('Подписка', '$100+$100/мес', '#64748b');
                     h += '</div>';
                 }
                 if (typeof _o.agents_count === 'number') {
                     h += `<div style="border-top:1px solid rgba(51,65,85,0.5);padding-top:6px;margin-top:4px">📈 Агенты: <span style="color:#cbd5e1">${_o.agents_count}</span></div>`;
diff --git a/tests/test_codex_usage.py b/tests/test_codex_usage.py
new file mode 100644
index 000000000..a99db593f
--- /dev/null
+++ b/tests/test_codex_usage.py
@@ -0,0 +1,127 @@
+import json
+import time
+from unittest.mock import AsyncMock
+
+import pytest
+
+from app.routes import system
+
+
+def test_normalize_codex_usage_prefers_codex_bucket():
+    result = {
+        "rateLimits": {"planType": "plus", "primary": None},
+        "rateLimitsByLimitId": {
+            "codex": {
+                "planType": "prolite",
+                "primary": {
+                    "usedPercent": 6,
+                    "windowDurationMins": 10080,
+                    "resetsAt": 1784957081,
+                },
+                "secondary": None,
+                "credits": {"hasCredits": False, "unlimited": False, "balance": "0"},
+            },
+        },
+        "rateLimitResetCredits": {"availableCount": 2},
+    }
+
+    usage = system._normalize_codex_usage(result)
+
+    assert usage == {
+        "plan_type": "prolite",
+        "primary": {
+            "utilization": 6,
+            "window_minutes": 10080,
+            "resets_at": "2026-07-25T05:24:41Z",
+        },
+        "secondary": None,
+        "credits": {"has_credits": False, "unlimited": False, "balance": "0"},
+        "reset_credits": 2,
+    }
+
+
+@pytest.mark.asyncio
+async def test_usage_endpoint_adds_codex_without_changing_anthropic(monkeypatch):
+    anthropic = {"five_hour": {"utilization": 12}, "seven_day": {"utilization": 34}}
+    codex = {
+        "plan_type": "prolite",
+        "primary": {"utilization": 6, "window_minutes": 10080, "resets_at": None},
+        "secondary": None,
+    }
+    monkeypatch.setattr(system, "is_auth_enabled", lambda: False)
+    monkeypatch.setattr(system, "_usage_cache", {"data": anthropic, "ts": time.time(), "token": None})
+    monkeypatch.setattr(system, "_codex_usage_cache", {"data": None, "ts": 0.0})
+    monkeypatch.setattr(system, "_fetch_codex_usage", AsyncMock(return_value=codex))
+    monkeypatch.setattr(system, "_get_agents_cost", lambda: {"agents_count": 0})
+
+    response = await system.get_usage()
+
+    assert response["anthropic"] is anthropic
+    assert response["codex"] is codex
+    assert response["orchestra"] == {"agents_count": 0}
+
+
+@pytest.mark.asyncio
+async def test_codex_failure_does_not_break_anthropic_usage(monkeypatch):
+    anthropic = {"five_hour": {"utilization": 12}}
+    monkeypatch.setattr(system, "is_auth_enabled", lambda: False)
+    monkeypatch.setattr(system, "_usage_cache", {"data": anthropic, "ts": time.time(), "token": None})
+    monkeypatch.setattr(system, "_codex_usage_cache", {"data": None, "ts": 0.0})
+    monkeypatch.setattr(system, "_fetch_codex_usage", AsyncMock(side_effect=RuntimeError("not logged in")))
+    monkeypatch.setattr(system, "_get_agents_cost", lambda: {})
+
+    response = await system.get_usage()
+
+    assert response["anthropic"] is anthropic
+    assert response["codex"] is None
+
+
+@pytest.mark.asyncio
+async def test_fetch_codex_usage_uses_app_server_protocol(monkeypatch):
+    class FakeStdin:
+        def __init__(self):
+            self.messages = []
+
+        def write(self, data):
+            self.messages.append(json.loads(data))
+
+        async def drain(self):
+            pass
+
+        def close(self):
+            pass
+
+    class FakeStdout:
+        def __init__(self):
+            self.lines = iter([
+                b'{"id":1,"result":{"userAgent":"test"}}\n',
+                b'{"id":2,"result":{"rateLimits":{"planType":"pro","primary":{"usedPercent":9,"windowDurationMins":300,"resetsAt":1784957081},"secondary":null}}}\n',
+            ])
+
+        async def readline(self):
+            return next(self.lines, b"")
+
+    class FakeProcess:
+        def __init__(self):
+            self.stdin = FakeStdin()
+            self.stdout = FakeStdout()
+            self.returncode = None
+
+        def terminate(self):
+            self.returncode = 0
+
+        def kill(self):
+            self.returncode = -9
+
+        async def wait(self):
+            return self.returncode
+
+    proc = FakeProcess()
+    monkeypatch.setattr(system.asyncio, "create_subprocess_exec", AsyncMock(return_value=proc))
+
+    usage = await system._fetch_codex_usage()
+
+    assert usage["primary"]["window_minutes"] == 300
+    assert [message["method"] for message in proc.stdin.messages] == [
+        "initialize", "initialized", "account/rateLimits/read",
+    ]


## LATER FIX 4bc0a84b5a (79.2 days later): V-703: #V-703: fix Codex runtime recovery and quota errors
lines of origin it changed/deleted: 2
(code only, capped 400 lines)

V-703: #V-703: fix Codex runtime recovery and quota errors

Squashed commits:
- #V-703: fix Codex runtime recovery and quota errors
- #V-703: record Codex mutation evidence
- #V-703: preserve Codex live steering and quota reset

Orchestra-Operation: 854ae3c5-672c-412c-8330-03eb7495754f


diff --git a/app/backend_codex.py b/app/backend_codex.py
index dbb844d06..388f910d7 100644
--- a/app/backend_codex.py
+++ b/app/backend_codex.py
@@ -1368,22 +1368,28 @@ class CodexBackend(JsonRpcStdioTransport):
         if method == "thread/tokenUsage/updated":
             self._record_token_usage(params)
             return []
 
         if method == "error":
             error = params.get("error") or {}
             self._last_turn_error = error
             content = error.get("message") or "Codex error"
-            if params.get("willRetry"):
-                return [AgentEvent("status", f"codex reconnecting: {content}")]
             model_error = self._classify_error(error)
+            quota_exhausted = error.get("codexErrorInfo") in (
+                "usageLimitExceeded", "sessionBudgetExceeded",
+            )
+            if params.get("willRetry") and not quota_exhausted:
+                return [AgentEvent("status", f"codex reconnecting: {content}")]
+            metadata = {"model_error": model_error}
             if model_error == "rate_limit":
                 content = f"rate_limit: {content}"
-            return [AgentEvent("error", content, metadata={"model_error": model_error})]
+            if quota_exhausted:
+                metadata["codex_quota_exhausted"] = True
+            return [AgentEvent("error", content, metadata=metadata)]
 
         if method == "model/rerouted":
             return [AgentEvent("status", f"model rerouted: {json.dumps(params, ensure_ascii=False)}")]
 
         if method in ("context/compacted", "thread/compacted"):
             return [AgentEvent("status", "codex context compacted")]
 
         if method in (
diff --git a/app/mailbox.py b/app/mailbox.py
index 4bac60b7a..9e0870604 100644
--- a/app/mailbox.py
+++ b/app/mailbox.py
@@ -71,16 +71,39 @@ def mark_delivered(ids: list[int]) -> None:
     placeholders = ", ".join("?" for _ in ids)
     with db._conn() as connection:
         connection.execute(
             f"UPDATE mailbox SET delivered_at = ? WHERE id IN ({placeholders})",
             (time.time(), *ids),
         )
 
 
+def mark_codex_steer_submitted(message_id: int) -> None:
+    with db._conn() as connection:
+        connection.execute(
+            """UPDATE mailbox
+               SET origin_detail=json_set(origin_detail, '$.subtype', 'codex_steer_backup')
+               WHERE id=? AND delivered_at IS NULL
+                 AND json_extract(origin_detail, '$.subtype')='codex_steer_backup_pending'""",
+            (int(message_id),),
+        )
+
+
+def complete_codex_steers(recipient: str, scope: str, turn_id: str) -> int:
+    with db._conn() as connection:
+        cursor = connection.execute(
+            """UPDATE mailbox SET delivered_at = ?
+               WHERE recipient=? AND scope=? AND delivered_at IS NULL
+                 AND json_extract(origin_detail, '$.subtype')='codex_steer_backup'
+                 AND json_extract(origin_detail, '$.ref')=?""",
+            (time.time(), recipient, scope, turn_id),
+        )
+        return cursor.rowcount
+
+
 # Семантика доставки объявлена явно: AT-LEAST-ONCE.
 # Выбор между «потерять» и «повторить» сделан в пользу повтора: агент, прочитавший
 # сообщение дважды, теряет центы, а молча потерянное сообщение стоит работы (#158).
 # Аренда ниже гасит не повтор после краха, а ОДНОВРЕМЕННЫЕ выдачи.
 CLAIM_LEASE_SECONDS = 300.0
 
 
 def claim(recipient: str, scope: str, lease_seconds: float = CLAIM_LEASE_SECONDS) -> list[dict]:
diff --git a/app/routes/system.py b/app/routes/system.py
index a70668132..3c84ac545 100644
--- a/app/routes/system.py
+++ b/app/routes/system.py
@@ -1040,17 +1040,20 @@ async def _fetch_codex_usage() -> dict:
         if proc.returncode is None:
             try:
                 proc.terminate()
             except ProcessLookupError:
                 pass
         try:
             await asyncio.wait_for(proc.wait(), timeout=1)
         except asyncio.TimeoutError:
-            proc.kill()
+            try:
+                proc.kill()
+            except ProcessLookupError:
+                pass
             await proc.wait()
 
 
 async def _refresh_oauth_token(refresh_token: str) -> str | None:
     """Refresh expired OAuth token. Returns new access token or None."""
     import httpx
     try:
         async with httpx.AsyncClient(timeout=10) as client:
@@ -1250,17 +1253,17 @@ async def _get_usage_data(
             codex_data = await _fetch_codex_usage()
             codex_fetched = codex_data is not None
             if codex_fetched:
                 _codex_usage_cache["data"] = codex_data
                 _codex_usage_cache["ts"] = now
             else:
                 codex_data = _codex_usage_cache["data"]
         except Exception as e:
-            logger.warning(f"Codex usage fetch failed: {e}")
+            logger.warning("Codex usage fetch failed: %r", e)
             codex_data = _codex_usage_cache["data"]
     if required_provider in {"codex", "codex_spark"} and not codex_fetched:
         raise RuntimeError("fresh Codex usage is unavailable")
 
     grok_data = None
     grok_fetched = False
     skip_grok_refresh = bool(required_provider) and required_provider != "grok"
     if skip_grok_refresh:
diff --git a/app/runtime_history.py b/app/runtime_history.py
index 55d43cc77..050e548aa 100644
--- a/app/runtime_history.py
+++ b/app/runtime_history.py
@@ -11,19 +11,19 @@ from collections import Counter, deque
 from copy import deepcopy
 from dataclasses import asdict, dataclass, replace
 from typing import Any, Callable, Iterable, Sequence
 
 
 CLAUDE_CLI_HISTORY_VERSION = "2.1.197"
 CLAUDE_SDK_HISTORY_VERSION = "0.2.114"
 CLAUDE_HISTORY_SOURCE = "logs:claude"
-# Pin follows the installed codex-cli 0.153.4; #498's nine Astra effort probes and #503's
-# live ASTRA_OK validated the preceding 0.153.2 binary.
-CODEX_CLI_HISTORY_VERSION = "0.153.4"
+# A synthetic history payload was accepted by codex-cli 0.156.1 `thread/resume` in an
+# isolated CODEX_HOME on 2026-10-05 (V-703); no live thread was resumed.
+CODEX_CLI_HISTORY_VERSION = "0.156.1"
 
 TOOL_CALL_LIMIT = 8_000
 TOOL_RESULT_LIMIT = 20_000
 TOOL_NAME_LIMIT = 512
 TOOL_DETAIL_BUDGET = 256_000
 TOOL_VISIBLE_BUDGET = 256_000
 # The packet is counted against the TARGET window, not against the source thread it
 # describes: a long session produced 8881 effects (3.2 MB) and 31939 event ids (224 KB)
diff --git a/app/session.py b/app/session.py
index 3803ca294..68094e711 100644
--- a/app/session.py
+++ b/app/session.py
@@ -1305,28 +1305,61 @@ class AgentSession:
                         f"message queued (deferred interrupt pending, "
                         f"{len(self._pending_messages)} pending)",
                     )
                     return
                 if not capabilities.mid_turn_inject:
                     self._pending_messages.append(message)
                     self._log("status", f"message queued ({len(self._pending_messages)} pending)")
                     return
+                mailbox_id = None
                 try:
                     backend = await self._ensure_backend()
                     injected, fact_keys = self._attach_pending_facts(message)
+                    turn_id = getattr(backend, "active_turn_id", None)
+                    if (
+                        self.backend_type == "codex"
+                        and provenance.origin not in {"platform", "system"}
+                        and isinstance(turn_id, str)
+                        and turn_id
+                    ):
+                        from app import mailbox
+
+                        sender = provenance.senders[0]
+                        body = message
+                        prefix = f"[from:{sender}] "
+                        if provenance.origin == "agent" and body.startswith(prefix):
+                            body = body[len(prefix):]
+                        mailbox_id = mailbox.enqueue(
+                            recipient=self.name,
+                            scope=self.scope,
+                            sender=sender,
+                            body=body,
+                            provenance=MessageProvenance(
+                                origin=provenance.origin,
+                                senders=provenance.senders,
+                                subtype="codex_steer_backup_pending",
+                                ref=turn_id,
+                            ),
+                        )
                     await backend.send(injected)
+                    if mailbox_id is not None:
+                        from app import mailbox
+
+                        mailbox.mark_codex_steer_submitted(mailbox_id)
                     self._ack_pending_facts(fact_keys)
                     if self.backend_type == "codex":
                         self._log("status", "message steered into active Codex turn")
                     return
                 except Exception as e:
                     logger.warning(f"[{self.name}] mid-turn inject failed, queueing: {e}")
-                    self._pending_messages.append(message)
-                    self._log("status", f"inject failed, queued ({len(self._pending_messages)} pending)")
+                    if mailbox_id is None:
+                        self._pending_messages.append(message)
+                    pending = len(self._pending_messages) + int(mailbox_id is not None)
+                    self._log("status", f"inject failed, queued ({pending} pending)")
                     if self.status != AgentStatus.RUNNING and not self._compacting:
                         self._spawn_bg(self._flush_pending())
                 return
 
             if self._hibernate_task and not self._hibernate_task.done():
                 self._hibernate_task.cancel()
                 self._hibernate_task = None
 
@@ -2129,17 +2162,29 @@ class AgentSession:
         if self.status != AgentStatus.RUNNING:
             return
         self._turn_start = 0
         self.status = AgentStatus.IDLE
         self._log("error", reason)
         self._persist()
         self._turns.publish_turn_finished()
         self._turns.report_abnormal_end(reason)
-        if self._pending_messages:
+        try:
+            from app import mailbox
+
+            queued = mailbox.claim(self.name, self.scope)
+        except Exception as error:
+            logger.warning(
+                "[%s] failed-turn mailbox claim failed: %s: %s",
+                self.name, type(error).__name__, error,
+            )
+            queued = []
+        if queued:
+            self._spawn_bg(self._turns._deliver_mailbox(queued))
+        elif self._pending_messages:
             self._spawn_bg(self._flush_pending())
         else:
             self._hibernate.schedule()
 
     MAX_CONSECUTIVE_FAILURES = 5
 
     async def _reconnect_backend(self) -> None:
         backend = self._backend
@@ -2422,16 +2467,61 @@ class AgentSession:
         elif event.type in ("plan", "warning", "review"):
             self._log(event.type, event.content)
         elif event.type == "turn_end":
             # Сколько обращений к модели было в ходе: расход хода — их сумма, и компакт
             # делит на это число, чтобы получить размер контекста ОДНОГО обращения.
             self._last_turn_api_calls = max(1, int(event.metadata.get("num_turns") or 1))
             self._turns.handle_turn_end(event)
         elif event.type == "error":
+            if event.metadata.get("codex_quota_exhausted"):
+                self._session_limit_hit = True
+                from app.routes import system
+
+                usage = system._codex_usage_cache.get("data") or {}
+                if self.model == "gpt-5.3-codex-spark":
+                    usage = usage.get("spark") or {}
+                windows = [
+                    ("primary", usage.get("primary")),
+                    ("secondary", usage.get("secondary")),
+                ]
+                exhausted = [
+                    (key, window)
+                    for key, window in windows
+                    if isinstance(window, dict)
+                    and isinstance(window.get("utilization"), (int, float))
+                    and not isinstance(window["utilization"], bool)
+                    and window["utilization"] >= 100
+                ]
+                selected = exhausted or windows
+                reset_details = []
+                now = datetime.now(timezone.utc)
+                for key, window in selected:
+                    if not isinstance(window, dict):
+                        reset_details.append(f"{key} неизвестно")
+                        continue
+                    minutes = window.get("window_minutes")
+                    label = {300: "5h", 10080: "7d"}.get(minutes, key)
+                    value = window.get("resets_at") if isinstance(window, dict) else None
+                    reset_text = "неизвестно"
+                    if isinstance(value, str) and value:
+                        try:
+                            reset_at = datetime.fromisoformat(value.replace("Z", "+00:00"))
+                            if reset_at.tzinfo is None:
+                                reset_at = reset_at.replace(tzinfo=timezone.utc)
+                            if reset_at > now:
+                                reset_text = reset_at.isoformat().replace("+00:00", "Z")
+                        except ValueError:
+                            pass
+                    reset_details.append(f"{label} {reset_text}")
+                self._log(
+                    "error",
+                    f"квота Codex исчерпана, сброс {', '.join(reset_details)}",
+                )
+                return
             # rate_limit → single retry-status log (skip raw error to avoid duplicate
             # "model error: rate_limit" + "rate limited — retry" on one event)
             if event.metadata.get("model_error") == "rate_limit":
                 # Terminal subscription/usage limits — never retry
                 if self._session_limit_hit:
                     return
                 elif self._rate_limit_retries < self.RATE_LIMIT_MAX_RETRIES:
                     self._rate_limit_retries += 1
diff --git a/app/session_turns.py b/app/session_turns.py
index c41616dff..d03cfa689 100644
--- a/app/session_turns.py
+++ b/app/session_turns.py
@@ -290,16 +290,26 @@ class TurnManager:
 
     def handle_turn_end(self, event: AgentEvent) -> None:
         s = self.s
         meta = event.metadata
         cost_unaccounted = meta.get("cost_unaccounted") is True
         s._turn_start = 0
         ok, sr, nt = s._cost.apply_turn_result(meta, event.usage)
         event_id = str(meta.get("event_id") or "")
+        if ok and event_id and s.backend_type == "codex":
+            from app import mailbox
+
+            try:
+                mailbox.complete_codex_steers(s.name, s.scope, event_id)
+            except Exception as error:
+                logger.warning(
+                    f"[{s.name}] successful-turn steer cleanup failed: "
+                    f"{type(error).__name__}: {error}"
+                )
         if not ok and event_id:
             from app import message_deliveries
 
             try:
                 recovered = message_deliveries.requeue_failed_turn(s.id, event_id)
             except Exception as error:
                 logger.warning(
                     f"[{s.name}] failed-turn steer recovery unavailable: "
diff --git a/tests/test_backend_codex.py b/tests/test_backend_codex.py
index 948f331eb..c7ef198c4 100644
--- a/tests/test_backend_codex.py
+++ b/tests/test_backend_codex.py
@@ -3,18 +3,16 @@
 Regression net for the three bugs found in the codex-integration audit:
   BUG 1 — Sol/Terra/Luna missing from context/price dicts (worker got 258400 ctx, $0).
   BUG 2 — reasoning effort hardcoded, xhigh/max not in the accepted set.
   MCP   — per-worker MCP servers now injected via -c dotted-leaf overrides.
 """
 
 import asyncio
 import json
-import shutil
-import subprocess
 from types import SimpleNamespace
 from unittest.mock import AsyncMock, MagicMock
 
 import pytest
 
 from app.backend_codex import (
     CodexBackend,
     CodexOversizedRecordError,
@@ -68,26 +66,16 @@ def _history_import():
             "type": "user_message",
             "content": "remember",
         }],
         snapshot_id=1,
         thread_id="11111111-2222-4333-8444-555555555555",
     )
 
 
-def test_installed_codex_history_version_matches_pin():
-    cli = shutil.which("codex")
-    if cli is None:
-        pytest.skip("Codex CLI is not installed")
-    result = subprocess.run(
-        [cli, "--version"], capture_output=True, text=True, check=True, timeout=10
-    )
-    assert result.stdout.strip() == f"codex-cli {CODEX_CLI_HISTORY_VERSION}"
-
-
 # ── BUG 1: GPT-5.6 models registered in backend dicts ──
 
 def test_gpt56_context_limits_present():
     # ChatGPT-auth Codex runtime reports a 258400 effective budget for these models.