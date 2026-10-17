# Context for item-29

## Diff reviewed (-U20, capped at 1500 lines)

diff --git a/CHANGELOG.md b/CHANGELOG.md
index 8d0746312..b615ce790 100644
--- a/CHANGELOG.md
+++ b/CHANGELOG.md
@@ -1,22 +1,40 @@
 # Changelog
 
+## v2.24.0 — 2026-07-01
+
+### Changed
+- 🔌 **Прокси: `.env` HTTPS_PROXY = единственный источник истины (вырезан DB/hot-switch)** — юзер: «всё лишнее вырежем». Управление прокси только через `.env` + `sudo systemctl restart orchestra`. Вся runtime-мутация env удалена → рассинхрон (`.env` показывал 12343, а CLI-агенты держали 12342 из DB) стал невозможен by design.
+  - **Root cause рассинхрона**: `kv.active_proxy` в DB **побеждал** `.env` — `load_saved_proxy()` при старте перезаписывал `os.environ` из DB. А живые CLI-агенты держали РАЗНЫЙ прокси, т.к. `backend_claude._make_client()` снимает `os.environ["HTTPS_PROXY"]` в момент `connect()` и запаивает в персистентный SDK-клиент (проверено: pid A→12334, pid B→12342).
+  - **Вырезано из `proxy_manager.py`** (−107 строк net): `load_saved_proxy` (читала DB kv), `select_proxy` (мутировала `os.environ`+`MCP_BASE_ENV`, писала kv), `refresh_loop`, `_cache`/`CACHE_TTL`/`_ts`-штампы, `_active_id` state. Стало read-only: `list_proxies()` (`active` вычисляется из `os.environ` через `_active_id()`, read-only) + `check_all()`/`check_proxy()` (on-demand живость, без кеша).
+  - **`routes/proxy.py`**: удалён `POST /api/proxy/select/{proxy_id}` (+ interrupt-логика живых агентов). Осталось `list` + `check` + `tunnel/status`. `route_surface_snapshot.json` обновлён.
+  - **`main.py`**: убраны `proxy_manager.load_saved_proxy()` + `refresh_loop` task.
+  - **Frontend** (`app.js`): убрана кнопка «выбрать прокси» (`.proxy-select-btn`) + handler. Осталась Check (проверить живость) + индикатор активного.
+  - **DB**: `DELETE FROM kv WHERE key='active_proxy'`. Миграция/колонка не тронуты (мёртвые, код не читает).
+  - **#3 Direct id fix**: `id="direct"` форсится когда `url=="direct"` — раньше генерился из имени → `direct-(vpn/соту)` (кириллица+скобки) → `select/direct` 404'ил. Имя в `.env` упрощено до `Direct`.
+  - **#4 zombie backoff+health-gate** (`ssh_tunnel.py`): мёртвый VPS (timeweb/ezhik) реконнектил ssh каждые 5с вечно (`kex_exchange_identification: Connection reset` в логах) → зомби. Теперь TCP health-gate на `:22` (2с) перед спавном + exponential backoff 5→300с + reset при uptime >60с.
+  - **CLAUDE.md**: секция «🔌 ПРОКСИ» — источник истины, как сменить, дашборд read-only.
+  - **Codex-враппер** (`~/.local/bin/codex`): добавлен `HTTP_PROXY` (был только HTTPS) — websocket Codex падал без него.
+  - **Tests**: `tests/test_proxy.py` (6 — direct id, active-from-env, no-mutation-methods, port probe, health-gate). 48 зелёных.
+  - **Reverted из v2.23.0**: `CACHE_TTL`/`refresh_loop`/`_cache` (были добавлены в прошлой итерации, теперь не нужны — дашборд on-demand).
+  - **Docs**: `docs/tasks/proxy-fix/{best-practices,plan-simplify}.md`.
+
 ## v2.23.0 — 2026-07-01
 
 ### Fixed
 - 🔌 **SSH-туннели к прокси зависели от VPN + zombie-процессы (proxy-fix)** — все прокси Orchestra = `ssh -L` туннели к VPS. При смене сети / выключении Reality VPN старые ssh-процессы висли в полумёртвом состоянии, держали local-порт → новый туннель не мог забиндить → прокси молча возвращал HTTP 000. Плюс дубли копились (9 ssh на 4 туннеля).
   - **Root cause**: НЕ блокировка РКН. Contabo (158.220.127.161) и Fornex (89.127.206.225) достижимы напрямую с РФ-WiFi без VPN (проверено: SSH-баннер + `curl -x :12343 https://api.anthropic.com/v1/messages` → HTTP 405). Проблема — (1) при VPN ON xray TUN-режим (`ip rule 9001 lookup 2022`) заворачивал VPS-трафик в tun0, (2) stale ssh не убивались.
   - **`_kill_stale(t)`** (`app/ssh_tunnel.py:37`) — `pkill -f "ssh -N -L {local}:127.0.0.1:{remote} .*root@{host}"` перед стартом каждого туннеля (once в `start_tunnel`, НЕ в reconnect-loop). Паттерн пинит local+remote порт **и** host → убивает только СВОЙ tunnel-def, не чужой same-port форвард. Протестировано на реальных ssh-процессах (kill свой / оставить чужой).
   - **Hard-kill**: `stop_tunnel` + CancelledError-handler теперь `terminate()` → `wait_for(KILL_GRACE=3s)` → `kill()` (SIGKILL) если ssh завис на мёртвом маршруте. `KILL_GRACE=3` (`ssh_tunnel.py:18`).
   - **Дашборд TTL** (`app/proxy_manager.py`) — `_cache` без TTL показывал мёртвый прокси 🟢 навсегда. Теперь `CACHE_TTL=60s`, результаты штампуются `_ts` (monotonic), `list_proxies` дропает stale → фронт рисует ⚪ (unknown, уже поддержано `app.js:4879`). `refresh_loop()` (bg task в `main.py:56`) перепроверяет каждые 60с → самозаживает.
   - **.env**: `SSH_TUNNELS` переупорядочен — живые (contabo, fornex) первыми, мёртвые (ezhik, timeweb) последними. `check-proxies.sh` кандидаты аналогично.
   - **NM hook**: `scripts/99-orchestra-proxy` — dispatcher-скрипт (up/down/vpn-*/connectivity-change → `check-proxies.sh`). Ставит юзер вручную (root, инструкция в шапке файла).
   - **Triggered case**: юзер выключил Reality VPN на домашнем WiFi → Orchestra упала, т.к. туннели дохли. Цель: прокси как ЗАМЕНА VPN, а не зависимость от него.
   - **Skipped**: `ip rule` split-tunnel (#5) — юзер использует VPN **или** прокси, не одновременно → перехватывать нечего при VPN off.
   - **Codex review**: подтвердил safe (12340≠123400), правильное размещение `_kill_stale` в start_tunnel; принята суггестия сузить pkill-match до host+remote (сделано).
   - **Research**: `docs/tasks/proxy-fix/research.md`.
 
 ## v2.22.0 — 2026-06-21
 
 ### Added
 - 📡 **Real-time token streaming in dashboard (task #83)** — agent text now types out live in the chat bubble as the model generates it, instead of appearing all at once when the turn's text block completes. Latency drops from "whole block after completion" to ~5 chunks/sec (~80-100 chars/chunk — the Claude CLI batches deltas; not per-token).
   - **Backend**: `include_partial_messages=True` in `ClaudeAgentOptions` (`app/backend_claude.py:138`). `_convert` gained a `StreamEvent` branch (`backend_claude.py:242`) that emits `AgentEvent("stream", text)` — STRICTLY scoped to main-agent `text_delta`: `parent_tool_use_id is not None` (subagents), non-`content_block_delta` events, and `thinking_delta`/`input_json_delta`/`signature_delta` are all filtered out. The final `AssistantMessage` still emits `text`/`thinking`/`tool_use` and is persisted exactly as before.
diff --git a/CLAUDE.md b/CLAUDE.md
index 9768a2d73..83aa4998e 100644
--- a/CLAUDE.md
+++ b/CLAUDE.md
@@ -33,49 +33,62 @@
     ├── MCP: Orchestra + scope .mcp.json (Playwright и т.д.)
     └── Stats: turns, tokens, tool_calls
 ```
 
 Deployed: localhost:8888 (dev) + VPS клиента (auth enabled)
 
 ## Dev Commands
 ```bash
 uv sync
 uv run uvicorn app.main:app --host 127.0.0.1 --port 8888
 
 # Systemd
 sudo systemctl start orchestra
 sudo systemctl status orchestra
 ```
 
 ## Принципы
 - Persistent client per session (connect once, `query()` injects mid-turn via stdin)
 - External MCP (no in-process deadlocks)
 - Workers communicate via HTTP callback, not MCP inject
-- Proxy через Hiddify (127.0.0.1:12334) everywhere
+- Proxy — см. секцию «🔌 ПРОКСИ» ниже (источник истины = .env HTTPS_PROXY)
 - **НЕ рестартить сервер при изменении фронта** (JS/CSS/HTML) — статика подтягивается автоматически. Рестарт только при изменении Python-кода
 - **sudo без пароля** для `systemctl restart/stop/start/status orchestra` и `telegram-bot-api` — можно рестартить сервер самому через `sudo systemctl restart orchestra`
 - **НЕ рестартить сервер самостоятельно** — только по явной команде юзера ("ок", "рестартни", "перезапусти"). Ребут убивает все активные сессии агентов
 - **Рестарт безопасен** — сессии персистентные (SQLite), auto_resume_all поднимает агентов. Контекст НЕ теряется. Активные turns прерываются, но idle воркеры восстанавливаются
 - **НЕ обновлять VPS самостоятельно** — git pull, systemctl restart на VPS делает только юзер вручную. Не пушить и не деплоить на VPS без команды
 - **TG /restart** — команда в TG группе для рестарта Orchestra
 - **Воркеры могут общаться друг с другом** через `send_message(to="worker-name")`. Пример: backend воркер добавил endpoint → пишет frontend-opus чтобы тот добавил кнопку. Оркестратор не нужен как посредник для координации между воркерами
 
+## 🔌 ПРОКСИ (единственный источник истины = .env)
+- **`.env` `HTTPS_PROXY`/`HTTP_PROXY` = ЕДИНСТВЕННЫЙ источник.** Нет DB, нет hot-switch, нет кеша статусов
+- Один прокси везде: systemd EnvironmentFile → `os.environ` → наследуют все (Orchestra + CLI агенты + MCP subprocess). Рассинхрон невозможен by design
+- **Сменить прокси:**
+  ```
+  1. Отредактируй HTTPS_PROXY И HTTP_PROXY в .env (оба!)
+  2. sudo systemctl restart orchestra
+  ```
+  Всё. Живой прокси найти: `bash scripts/check-proxies.sh` (диагностика — покажет живой и впишет в .env; рестарт — руками)
+- **Дашборд:** только индикатор активного (из `os.environ`, read-only) + кнопка Check (проверить живость on-demand). Кнопки «выбрать/активировать» НЕТ — переключение только через .env
+- `proxy_manager.py` — read-only: `list_proxies()` + `check_all()`. НЕ мутирует env, НЕ пишет в DB
+- SSH-туннели (`ssh_tunnel.py`) поднимают локальные порты к VPS. `HTTPS_PROXY` указывает на нужный порт. Мёртвые VPS не спамят реконнектом (health-gate + backoff)
+
 ## Pricing
 - **Max 20x subscription ($200/мес)** — все $ в dashboard виртуальные (API-equivalent), НЕ реальные траты
 - API цены (для калькуляции): Opus $5/$25, Sonnet $3/$15, Haiku $1/$5 per M tokens
 - Не паниковать от "$172 на оркестратора" — monopoly money. Оптимизировать КАЧЕСТВО, не стоимость
 
 ## AI Efficiency (design principle)
 Orchestra automates humans — but the AI agents themselves must be optimized too.
 Every feature should minimize agent overhead: fewer tool calls, less context waste, less repetition.
 
 **Design for AI, not humans:**
 - If an agent does the same 3 tool calls every time → automate into 1 MCP tool or server-side logic
 - If agents waste context reading the same files → pre-inject via system prompt or worktree setup
 - If a pattern causes context rot (agent re-reads, re-explains, loops) → fix the root cause, don't add more instructions
 - Measure cost-per-task, not just "does it work". $2 task done in 3 tool calls > $8 task done in 30 tool calls
 - Prompt engineering = agent optimization. Shorter, clearer prompts = fewer confused retries = less $ burned
 - Every new feature ask: "does this reduce total agent tool calls/tokens across typical workflows?"
 
 **Anti-patterns to avoid:**
 - Agent reads entire file when it needs 5 lines → give it grep/line-range hints
 - Agent asks orchestrator for permission it could decide itself → expand decision tree
diff --git a/app/main.py b/app/main.py
index 73346246f..f218a9d81 100644
--- a/app/main.py
+++ b/app/main.py
@@ -4,77 +4,73 @@ import asyncio
 import logging
 from contextlib import asynccontextmanager
 
 from fastapi import FastAPI, Request
 from fastapi.responses import JSONResponse, RedirectResponse
 from fastapi.staticfiles import StaticFiles
 from starlette.middleware.base import BaseHTTPMiddleware
 
 from app.auth import is_auth_enabled, validate_session, requires_auth, check_internal_token
 from app.db import init_db
 from app.deps import manager
 
 logger = logging.getLogger("orchestra")
 
 
 @asynccontextmanager
 async def lifespan(app: FastAPI):
     from dotenv import load_dotenv
     load_dotenv()
     init_db()
-    from app.proxy_manager import proxy_manager
-    proxy_manager.load_saved_proxy()
     from app.models import refresh_models, is_proxy_connected
     await refresh_models()
     if is_auth_enabled() and not is_proxy_connected():
         async def _proxy_retry_loop():
             while not is_proxy_connected():
                 await asyncio.sleep(60)
                 await refresh_models()
                 if is_proxy_connected():
                     logger.info("Proxy reconnected, models loaded")
                     break
         asyncio.create_task(_proxy_retry_loop())
     from app import tm as _tm_mod
     _tm_mod.set_main_loop(asyncio.get_running_loop())
     if not is_auth_enabled():
         from app import tm_yougile  # noqa: F401 — registers tm sync hooks
     await manager.auto_resume_all()
     from app.bootstrap import ensure_bootstrap
     await ensure_bootstrap()
     manager.start_background_tasks()
     from app.bg_jobs import bg_manager
     bg_manager.set_session_manager(manager)
     await bg_manager.restore_from_db()
     from app.tg_bridge import start_bridge, stop_bridge
     await start_bridge(manager)
     _tunnel_started = False
     if not is_auth_enabled():
         from app.ssh_tunnel import start_tunnel, stop_tunnel
         await start_tunnel()
         _tunnel_started = True
     from app.routes.system import _usage_snapshot_loop
     snapshot_task = asyncio.create_task(_usage_snapshot_loop())
-    proxy_refresh_task = asyncio.create_task(proxy_manager.refresh_loop())
     yield
     snapshot_task.cancel()
-    proxy_refresh_task.cancel()
     if _tunnel_started:
         await stop_tunnel()
     await stop_bridge()
     await bg_manager.shutdown()
     await manager.shutdown_all()
 
 
 app = FastAPI(title="Orchestra", lifespan=lifespan)
 app.mount("/static", StaticFiles(directory="app/static"), name="static")
 
 from app.routes.tm import router as tm_router
 from app.routes.bg import router as bg_router
 from app.routes.proxy import router as proxy_router
 from app.routes.sessions import router as sessions_router
 from app.routes.system import router as system_router
 from app.routes.tg import router as tg_router
 app.include_router(tm_router)
 app.include_router(bg_router)
 app.include_router(proxy_router)
 app.include_router(sessions_router)
diff --git a/app/proxy_manager.py b/app/proxy_manager.py
index c6848f697..f4aad0e0f 100644
--- a/app/proxy_manager.py
+++ b/app/proxy_manager.py
@@ -1,36 +1,37 @@
-"""Proxy manager — switch HTTPS_PROXY for all agents."""
+"""Proxy list + on-demand health check — READ-ONLY.
+
+Source of truth for the active proxy is .env HTTPS_PROXY (systemd EnvironmentFile
+→ os.environ). This module NEVER mutates proxy env or persists anything: it only
+reads PROXY_LIST for the dashboard and probes liveness on demand. To switch proxy:
+edit .env + restart Orchestra.
+"""
 
 import asyncio
 import logging
 import os
-import time
 from dataclasses import dataclass
 
 import httpx
 
-from app.runtime_env import MCP_BASE_ENV
-
 logger = logging.getLogger(__name__)
 
-CACHE_TTL = 60  # seconds — stale check results are dropped so UI never shows a dead proxy as green
-
 COUNTRY_FLAGS = {
     "US": "🇺🇸", "GB": "🇬🇧", "DE": "🇩🇪", "NL": "🇳🇱", "FR": "🇫🇷",
     "FI": "🇫🇮", "SE": "🇸🇪", "NO": "🇳🇴", "CH": "🇨🇭", "AT": "🇦🇹",
     "RU": "🇷🇺", "UA": "🇺🇦", "KZ": "🇰🇿", "BY": "🇧🇾",
     "JP": "🇯🇵", "KR": "🇰🇷", "SG": "🇸🇬", "AU": "🇦🇺",
     "CA": "🇨🇦", "BR": "🇧🇷", "IN": "🇮🇳", "TR": "🇹🇷",
     "PL": "🇵🇱", "CZ": "🇨🇿", "RO": "🇷🇴", "BG": "🇧🇬",
     "HK": "🇭🇰", "TW": "🇹🇼", "IE": "🇮🇪", "ES": "🇪🇸",
     "IT": "🇮🇹", "PT": "🇵🇹", "DK": "🇩🇰", "LT": "🇱🇹",
     "LV": "🇱🇻", "EE": "🇪🇪", "IS": "🇮🇸", "MD": "🇲🇩",
 }
 IP_CHECK_URL = "https://ipinfo.io/json"
 IP_CHECK_TIMEOUT = 8
 
 
 @dataclass
 class ProxyEntry:
     id: str
     name: str
     url: str
@@ -40,164 +41,88 @@ def _parse_proxy_list() -> list[ProxyEntry]:
     raw = os.environ.get("PROXY_LIST", "")
     if not raw:
         current = os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY")
         if current:
             return [ProxyEntry(id="default", name="Default", url=current)]
         return []
     entries = []
     for item in raw.split(","):
         item = item.strip()
         if not item:
             continue
         if "|" in item:
             parts = item.split("|", 2)
             pid = parts[0].strip().lower().replace(" ", "-")
             name = parts[0].strip()
             url = parts[1].strip()
         else:
             url = item
             pid = url.split(":")[-1] if ":" in url else "proxy"
             name = url
+        # Stable id for direct — name-derived id mangles cyrillic/parens
+        # ("Direct (VPN/Соту)" → "direct-(vpn/соту)")
+        if url == "direct":
+            pid = "direct"
         entries.append(ProxyEntry(id=pid, name=name, url=url))
     return entries
 
 
-class ProxyManager:
-    def __init__(self):
-        self._active_id: str | None = None
-        self._cache: dict[str, dict] = {}
+def _active_id(entries: list[ProxyEntry]) -> str:
+    """Which entry matches the current HTTPS_PROXY (from .env). Read-only."""
+    current = os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY") or ""
+    if not current:
+        direct = next((e for e in entries if e.url == "direct"), None)
+        return direct.id if direct else ""
+    match = next((e for e in entries if e.url == current), None)
+    return match.id if match else ""
+
 
+class ProxyManager:
     def _get_entries(self) -> list[ProxyEntry]:
         return _parse_proxy_list()
 
-    def load_saved_proxy(self) -> None:
-        """Load saved proxy from DB and apply to os.environ. Call at startup before auto_resume."""
-        try:
-            from app.db import kv_get
-            saved_id = kv_get("active_proxy")
-            if not saved_id:
-                return
-            entries = self._get_entries()
-            entry = next((e for e in entries if e.id == saved_id), None)
-            if not entry:
-                return
-            if entry.url == "direct":
-                for k in ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy"):
-                    os.environ.pop(k, None)
-            else:
-                for k in ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy"):
-                    os.environ[k] = entry.url
-            self._active_id = saved_id
-            logger.info(f"Restored proxy from DB: '{entry.name}' ({entry.url})")
-        except Exception as e:
-            logger.warning(f"Failed to load saved proxy: {e}")
-
-    def _get_active_id(self) -> str:
-        if self._active_id:
-            return self._active_id
-        entries = self._get_entries()
-        current_proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY") or ""
-        if not current_proxy:
-            direct = next((e for e in entries if e.url == "direct"), None)
-            if direct:
-                self._active_id = direct.id
-                return direct.id
-        for e in entries:
-            if e.url == current_proxy:
-                self._active_id = e.id
-                return e.id
-        return entries[0].id if entries else ""
-
     async def check_proxy(self, proxy_id: str) -> dict:
         entries = self._get_entries()
         entry = next((e for e in entries if e.id == proxy_id), None)
         if not entry:
             return {"error": f"proxy '{proxy_id}' not found"}
         return await self._do_check(entry)
 
     async def _do_check(self, entry: ProxyEntry) -> dict:
         try:
             kwargs = {"timeout": IP_CHECK_TIMEOUT, "verify": False}
             if entry.url and entry.url != "direct":
                 kwargs["proxy"] = entry.url
             async with httpx.AsyncClient(**kwargs) as client:
                 resp = await client.get(IP_CHECK_URL)
                 if resp.status_code != 200:
                     return {"id": entry.id, "ok": False, "error": f"HTTP {resp.status_code}"}
                 data = resp.json()
-                ip = data.get("ip", "?")
                 country = data.get("country", "??")
-                city = data.get("city", "")
-                org = data.get("org", "")
-                flag = COUNTRY_FLAGS.get(country, "🏳️")
-                result = {
+                return {
                     "id": entry.id, "ok": True,
-                    "ip": ip, "country": country, "city": city,
-                    "org": org, "flag": flag,
+                    "ip": data.get("ip", "?"), "country": country,
+                    "city": data.get("city", ""), "org": data.get("org", ""),
+                    "flag": COUNTRY_FLAGS.get(country, "🏳️"),
                 }
-                self._cache[entry.id] = {**result, "_ts": time.monotonic()}
-                return result
         except Exception as e:
-            result = {"id": entry.id, "ok": False, "error": str(e)}
-            self._cache[entry.id] = {**result, "_ts": time.monotonic()}
-            return result
+            return {"id": entry.id, "ok": False, "error": str(e)}
 
     async def list_proxies(self) -> dict:
+        """List proxies from .env. `active` = current HTTPS_PROXY (read-only).
+
+        No liveness here — call check/{id} or check_all for that (on-demand).
+        """
         entries = self._get_entries()
-        active_id = self._get_active_id()
-        proxies = []
-        now = time.monotonic()
-        for e in entries:
-            cached = self._cache.get(e.id)
-            info = {
-                "id": e.id, "name": e.name, "url": e.url,
-                "active": e.id == active_id,
-            }
-            # Drop stale results — a proxy that died stays "green" forever otherwise
-            if cached and now - cached.get("_ts", 0) < CACHE_TTL:
-                info.update({k: cached[k] for k in ("ok", "ip", "country", "city", "flag", "error") if k in cached})
-            proxies.append(info)
+        active_id = _active_id(entries)
+        proxies = [
+            {"id": e.id, "name": e.name, "url": e.url, "active": e.id == active_id}
+            for e in entries
+        ]
         return {"proxies": proxies, "active": active_id}
 
     async def check_all(self) -> list[dict]:
         entries = self._get_entries()
-        tasks = [self._do_check(e) for e in entries]
-        return await asyncio.gather(*tasks)
-
-    async def refresh_loop(self):
-        """Periodically re-check all proxies so the dashboard self-heals.
-
-        WHY: without this a proxy that dies stays 🟢 until someone clicks Check.
-        Combined with CACHE_TTL, results older than one interval never render green.
-        """
-        while True:
-            try:
-                await self.check_all()
-            except Exception as e:
-                logger.warning(f"proxy refresh_loop error: {e}")
-            await asyncio.sleep(CACHE_TTL)
-
-    async def select_proxy(self, proxy_id: str) -> dict:
-        entries = self._get_entries()
-        entry = next((e for e in entries if e.id == proxy_id), None)
-        if not entry:
-            return {"error": f"proxy '{proxy_id}' not found"}
-        if entry.url == "direct":
-            for k in ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy"):
-                os.environ.pop(k, None)
-                MCP_BASE_ENV.pop(k, None)
-        else:
-            for k, v in [("HTTPS_PROXY", entry.url), ("HTTP_PROXY", entry.url),
-                         ("https_proxy", entry.url), ("http_proxy", entry.url)]:
-                os.environ[k] = v
-                MCP_BASE_ENV[k] = v
-        self._active_id = proxy_id
-        try:
-            from app.db import kv_set
-            kv_set("active_proxy", proxy_id)
-        except Exception as e:
-            logger.warning(f"Failed to persist proxy choice: {e}")
-        logger.info(f"Proxy switched to '{entry.name}' ({entry.url})")
-        return {"ok": True, "active": proxy_id, "url": entry.url}
+        return await asyncio.gather(*(self._do_check(e) for e in entries))
 
 
 proxy_manager = ProxyManager()
diff --git a/app/routes/proxy.py b/app/routes/proxy.py
index cd85c6426..30e95f78a 100644
--- a/app/routes/proxy.py
+++ b/app/routes/proxy.py
@@ -13,44 +13,24 @@ router = APIRouter(tags=["proxy"])
 def _block_if_enterprise():
     if is_auth_enabled():
         raise HTTPException(403, "Not available")
 
 
 @router.get("/api/proxy/list")
 async def proxy_list():
     _block_if_enterprise()
     return await proxy_manager.list_proxies()
 
 
 @router.post("/api/proxy/check/{proxy_id}")
 async def proxy_check(proxy_id: str):
     _block_if_enterprise()
     result = await proxy_manager.check_proxy(proxy_id)
     if result.get("error"):
         return JSONResponse(result, status_code=400)
     return result
 
 
-@router.post("/api/proxy/select/{proxy_id}")
-async def proxy_select(proxy_id: str):
-    _block_if_enterprise()
-    result = await proxy_manager.select_proxy(proxy_id)
-    if result.get("error"):
-        return JSONResponse(result, status_code=400)
-    from app.deps import manager
-    reconnected = 0
-    for s in list(manager.sessions.values()):
-        if s.status.value == "running" and s._backend:
-            try:
-                await s._backend.interrupt()
-                reconnected += 1
-            except Exception:
-                pass
-    if reconnected:
-        result["interrupted"] = reconnected
-    return result
-
-
 @router.get("/api/tunnel/status")
 async def api_tunnel_status():
     _block_if_enterprise()
     return tunnel_status()
diff --git a/app/ssh_tunnel.py b/app/ssh_tunnel.py
index 25e9aa166..cf85be99d 100644
--- a/app/ssh_tunnel.py
+++ b/app/ssh_tunnel.py
@@ -1,41 +1,64 @@
 """SSH tunnel manager — multiple tunnels with auto-restart.
 
 Config via SSH_TUNNELS env var (pipe-separated fields, comma-separated entries):
   SSH_TUNNELS=name|local_port|host|remote_port|key_path,...
 
 Example:
   SSH_TUNNELS=ezhik|12340|194.87.250.243|18080|/path/to/key,timeweb|12341|147.45.101.84|3128|
 """
 
 import asyncio
 import logging
 import os
+import time
 from dataclasses import dataclass, field
 
 logger = logging.getLogger("ssh-tunnel")
 
 RECONNECT_DELAY = 5
+BACKOFF_MAX = 300  # cap exponential backoff — dead VPS retries every 5min, not 5s
+HEALTHY_UPTIME = 60  # ssh alive this long → connection was healthy, reset backoff
+HEALTH_TIMEOUT = 2  # TCP :22 probe timeout before spawning ssh
 KILL_GRACE = 3  # seconds to wait after terminate() before SIGKILL
 DEFAULT_KEY = os.path.expanduser("~/.ssh/id_ed25519")
 
 
+async def _port_open(host: str, port: int, timeout: float) -> bool:
+    """Quick TCP reachability probe — gate ssh spawn so dead VPS don't churn.
+
+    WHY: without this, a dead/DPI-blocked VPS (timeweb/ezhik) respawns ssh every
+    5s forever, spamming logs and racing with half-dead forwards → zombies.
+    """
+    try:
+        fut = asyncio.open_connection(host, port)
+        _, writer = await asyncio.wait_for(fut, timeout=timeout)
+        writer.close()
+        try:
+            await writer.wait_closed()
+        except Exception:
+            pass
+        return True
+    except Exception:
+        return False
+
+
 @dataclass
 class Tunnel:
     name: str
     local_port: int
     host: str
     remote_port: int
     key_path: str
     proc: asyncio.subprocess.Process | None = field(default=None, repr=False)
     task: asyncio.Task | None = field(default=None, repr=False)
     running: bool = False
 
 
 _tunnels: list[Tunnel] = []
 
 
 async def _kill_stale(t: Tunnel):
     """Kill orphan ssh forwards for THIS tunnel left by prior runs / network changes.
 
     WHY: on network switch or non-graceful restart the old `ssh -N -L` process
     lingers holding the port in a half-dead state → new tunnel can't bind →
@@ -76,76 +99,91 @@ def _parse_tunnels() -> list[Tunnel]:
         host = parts[2].strip()
         remote_port = int(parts[3].strip())
         key = parts[4].strip() if len(parts) > 4 and parts[4].strip() else DEFAULT_KEY
         tunnels.append(Tunnel(name=name, local_port=local_port, host=host,
                               remote_port=remote_port, key_path=key))
     return tunnels
 
 
 def _parse_legacy() -> list[Tunnel]:
     host = os.getenv("SSH_TUNNEL_HOST", "")
     if not host:
         return []
     key = os.getenv("SSH_TUNNEL_KEY", DEFAULT_KEY)
     local = int(os.getenv("SSH_TUNNEL_LOCAL_PORT", "12338"))
     remote = int(os.getenv("SSH_TUNNEL_REMOTE_PORT", "18080"))
     return [Tunnel(name="legacy", local_port=local, host=host,
                    remote_port=remote, key_path=key)]
 
 
 async def _tunnel_loop(t: Tunnel):
+    backoff = RECONNECT_DELAY
     while True:
         try:
+            # Health-gate: don't spawn ssh at a VPS whose :22 is unreachable —
+            # that's what makes dead VPS churn processes every 5s.
+            if not await _port_open(t.host, 22, HEALTH_TIMEOUT):
+                logger.info(f"tunnel {t.name} :22 unreachable, retry in {backoff}s")
+                await asyncio.sleep(backoff)
+                backoff = min(backoff * 2, BACKOFF_MAX)
+                continue
+            started = time.monotonic()
             t.proc = await asyncio.create_subprocess_exec(
                 "ssh", "-N",
                 "-L", f"{t.local_port}:127.0.0.1:{t.remote_port}",
                 "-i", t.key_path,
                 "-o", "StrictHostKeyChecking=no",
                 "-o", "ServerAliveInterval=30",
                 "-o", "ServerAliveCountMax=3",
                 "-o", "ExitOnForwardFailure=yes",
                 f"root@{t.host}",
                 stdout=asyncio.subprocess.DEVNULL,
                 stderr=asyncio.subprocess.PIPE,
             )
             t.running = True
             logger.info(f"tunnel {t.name} started pid={t.proc.pid} "
                         f"(:{t.local_port} → {t.host}:{t.remote_port})")
             _, stderr = await t.proc.communicate()
             t.running = False
             msg = stderr.decode().strip() if stderr else ""
             logger.warning(f"tunnel {t.name} died pid={t.proc.pid}"
                            f"{': ' + msg if msg else ''}")
+            # Reset backoff only if the tunnel stayed up long enough to be healthy
+            if time.monotonic() - started >= HEALTHY_UPTIME:
+                backoff = RECONNECT_DELAY
+            else:
+                backoff = min(backoff * 2, BACKOFF_MAX)
         except asyncio.CancelledError:
             if t.proc and t.proc.returncode is None:
                 t.proc.terminate()
                 try:
                     await asyncio.wait_for(t.proc.wait(), timeout=KILL_GRACE)
                 except (asyncio.TimeoutError, asyncio.CancelledError):
                     t.proc.kill()
             t.running = False
             return
         except Exception as e:
             t.running = False
             logger.error(f"tunnel {t.name} error: {e}")
-        logger.info(f"tunnel {t.name} reconnecting in {RECONNECT_DELAY}s...")
-        await asyncio.sleep(RECONNECT_DELAY)
+            backoff = min(backoff * 2, BACKOFF_MAX)
+        logger.info(f"tunnel {t.name} reconnecting in {backoff}s...")
+        await asyncio.sleep(backoff)
 
 
 async def start_tunnel():
     global _tunnels
     _tunnels = _parse_tunnels()
     if not _tunnels:
         logger.info("SSH tunnels: none configured")
         return
     await asyncio.gather(*(_kill_stale(t) for t in _tunnels))
     for t in _tunnels:
         t.task = asyncio.create_task(_tunnel_loop(t))
     names = ", ".join(f"{t.name}(:{t.local_port})" for t in _tunnels)
     logger.info(f"SSH tunnels starting: {names}")
 
 
 async def stop_tunnel():
     for t in _tunnels:
         if t.task:
             t.task.cancel()
             try:
diff --git a/app/static/js/app.js b/app/static/js/app.js
index 785e122e7..d2f44a1fe 100644
--- a/app/static/js/app.js
+++ b/app/static/js/app.js
@@ -4876,65 +4876,54 @@ async function loadProxyList() {
         for (const p of proxies) {
             const el = document.createElement('div');
             el.className = `flex items-center gap-2 px-2.5 py-2 rounded-lg cursor-pointer transition-colors ${p.active ? 'bg-indigo-900/40 border border-indigo-500/50' : 'bg-slate-800/50 border border-slate-700/50 hover:bg-slate-700/50'}`;
             const status = p.ok === true ? '🟢' : p.ok === false ? '🔴' : '⚪';
             const flag = p.flag || '🏳️';
             const ip = p.ip || '';
             const location = p.city ? `${p.city}, ${p.country || ''}` : p.country || '';
             el.innerHTML = `
                 <span class="text-sm">${status}</span>
                 <div class="flex-1 min-w-0">
                     <div class="flex items-center gap-1.5">
                         <span class="text-xs font-medium text-white">${escHtml(p.name)}</span>
                         ${p.active ? '<span class="text-[9px] px-1 py-0.5 bg-indigo-500/30 text-indigo-300 rounded">ACTIVE</span>' : ''}
                     </div>
                     <div class="text-[10px] text-slate-500 truncate">${escHtml(p.url)}</div>
                     ${ip ? `<div class="text-[10px] text-slate-400">${flag} ${ip} ${location ? '· ' + escHtml(location) : ''}</div>` : ''}
                     ${p.error ? `<div class="text-[10px] text-red-400 truncate">${escHtml(String(p.error).slice(0, 60))}</div>` : ''}
                 </div>
                 <div class="flex gap-1 shrink-0">
                     <button class="proxy-check-btn text-[10px] px-1.5 py-0.5 bg-slate-700 hover:bg-slate-600 rounded text-slate-300" data-id="${p.id}" title="Check">🔍</button>
-                    ${!p.active ? `<button class="proxy-select-btn text-[10px] px-1.5 py-0.5 bg-indigo-600 hover:bg-indigo-500 rounded text-white" data-id="${p.id}" title="Activate">✓</button>` : ''}
                 </div>
             `;
             list.appendChild(el);
         }
         list.querySelectorAll('.proxy-check-btn').forEach(b => {
             b.addEventListener('click', async (e) => {
                 e.stopPropagation();
                 b.textContent = '⏳';
                 try {
                     await fetch(`/api/proxy/check/${b.dataset.id}`, {method:'POST'});
                     await loadProxyList();
                 } catch(err) { b.textContent = '❌'; }
             });
         });
-        list.querySelectorAll('.proxy-select-btn').forEach(b => {
-            b.addEventListener('click', async (e) => {
-                e.stopPropagation();
-                b.textContent = '⏳';
-                try {
-                    await fetch(`/api/proxy/select/${b.dataset.id}`, {method:'POST'});
-                    await loadProxyList();
-                } catch(err) { b.textContent = '❌'; }
-            });
-        });
         const active = proxies.find(p => p.active);
         if (active) {
             $('#proxy-flag').textContent = active.flag || '🌐';
             $('#proxy-ip').textContent = active.ip || '';
         }
     } catch (e) { console.warn('loadProxyList failed:', e); }
 }
 
 // ── Profiles Manager (редактор реестра профилей Claude) ──
 
 let _profilesDropdownOpen = false;
 
 function initProfilesManager() {
     const btn = $('#profiles-btn');
     const dropdown = $('#profiles-dropdown');
     if (!btn || !dropdown) return;
     btn.addEventListener('click', (e) => {
         e.stopPropagation();
         _profilesDropdownOpen = !_profilesDropdownOpen;
         dropdown.classList.toggle('hidden', !_profilesDropdownOpen);
diff --git a/docs/tasks/proxy-fix/best-practices.md b/docs/tasks/proxy-fix/best-practices.md
new file mode 100644
index 000000000..becc7b3d5
--- /dev/null
+++ b/docs/tasks/proxy-fix/best-practices.md
@@ -0,0 +1,197 @@
+# Proxy best-practices — как жить с этим надёжно
+
+**Дата:** 2026-07-01
+**Статус:** research only, ждёт approval
+**Аудитория:** 1 юзер, мобильный (раздача с телефона / дача), хочет «включил и работает».
+
+---
+
+## TL;DR — что делать прямо сейчас
+
+**Дома (стабильный WiFi):** прокси Contabo (`:12343`) напрямую, без VPN. Работает.
+
+**Мобильный / дача (нестабильно):** **включи Соту (tun-VPN) + переключи Orchestra на Direct.** SSH-туннели на плохой сети рвутся и плодят зомби — tun-VPN держит связь на уровне протокола (retry, обфускация) куда лучше. Ты уже платишь за Соту — используй её как основной канал, а не как костыль под SSH.
+
+**Правило одной кнопки:** цель — чтобы «включил Соту → всё заработало». Для этого нужны 4 фикса ниже (проблемы 1-4). Без них юзер дёргает скрипты руками.
+
+---
+
+## Как оно РЕАЛЬНО работает (проверено вживую)
+
+Цепочка сейчас (Соту ON, мобильный):
+```
+Claude CLI агент → HTTPS_PROXY=:12342 → ssh-туннель Fornex → tun0 (Соту) → Fornex VPS → Anthropic
+```
+
+Ключевой факт про **выбор прокси**: `.env` HTTPS_PROXY **игнорируется**. Реальный источник истины — **DB `kv.active_proxy`** (сейчас = `fornex-nl`). `load_saved_proxy()` при старте перезаписывает `os.environ` из DB. Поэтому `.env=12343`, а агенты на `12342` — не баг, а DB победила .env.
+
+---
+
+## ПРОБЛЕМА 1 — рассинхрон: живые агенты держат СТАРЫЙ прокси
+
+### Root cause (докопался)
+`backend_claude.py:_make_client()` (строка 121-125) снимает `os.environ["HTTPS_PROXY"]` **в момент `connect()`** и запаивает в персистентный SDK-клиент. Клиент живёт всю сессию (connect once, `query()` мид-терн). `select_proxy()` (`proxy_manager.py:179`) меняет `os.environ` + `MCP_BASE_ENV`, но **НЕ трогает уже подключённых агентов** — они реконнектятся только при resume/scope-change.
+
+**Доказательство** — живые CLI-процессы держат РАЗНЫЕ прокси:
+```
+pid 239194 → :12334 (Hiddify)   ← подключился когда активен был Hiddify
+pid 398866 → :12342 (Fornex)    ← подключился уже на Fornex
+```
+Каждый агент заморожен с тем прокси, что был активен в его `connect()`.
+
+### Решение (по возрастанию сложности)
+
+**A. Реконнект живых агентов при select_proxy** (рекомендую) — СРЕДНЯЯ сложность.
+Механизм уже есть: `manager.change_orchestrator_scope` делает `session._disconnect_backend()` → бэкенд лениво реконнектится на следующем `send()` через `_make_client()` → **пере-снимает `os.environ`**. Контекст цел (resume_session_id).
+- Правка: в `routes/proxy.py:select_proxy` после `proxy_manager.select_proxy()` пройтись по `manager.sessions.values()` и вызвать `_disconnect_backend()` для idle-сессий (running — пометить «reconnect on next turn», не рвать посреди ответа).
+- Файл: `app/routes/proxy.py` + хелпер в `app/manager.py` (напр. `reconnect_all_for_proxy()`).
+- Сложность: ~30 строк. Риск: рвать running-агента посреди turn нельзя → только idle + флаг для running.
+
+**B. НЕ снимать прокси в клиент, а читать динамически** — НИЗКАЯ отдача, высокий риск.
+SDK берёт env при спавне CLI-подпроцесса, изменить это нельзя без хака. Отклоняю.
+
+**C. Автовыбор живого прокси при старте + реконнект** (объединяет с #3 автоматизации) — см. раздел «Автоматизация».
+
+**Рекомендация:** A. Одна кнопка «переключить прокси» в дашборде должна дёргать реконнект idle-агентов. Running — на следующем turn.
+
+---
+
+## ПРОБЛЕМА 2 — SSH-туннель vs tun-VPN: что стабильнее на мобильном
+
+### Вывод: на нестабильной сети — tun-VPN (Соту), НЕ SSH-туннели. Гипотеза юзера ВЕРНА.
+
+**Почему SSH-forward плох на мобильном:**
+- SSH-forward = одно TCP-соединение. Мобильная сеть меняет IP / роняет пакеты → TCP рвётся → forward умирает целиком. `ServerAliveInterval=30` + `ServerAliveCountMax=3` = до 90с висит мёртвым прежде чем reconnect.
+- `ExitOnForwardFailure=yes`: если порт занят зомби (см. Проблема 4) — новый forward падает мгновенно, порт не встаёт. Отсюда «Orchestra 12343 не встаёт, а ручной ssh встаёт» — у ручного свой порт (19999), у Orchestra 12343 занят полу-мёртвым процессом.
+- Нет обфускации → на даче/мобильном DPI может резать SSH (`kex_exchange_identification: Connection reset` в логах timeweb — похоже именно на это).
+
+**Почему tun-VPN (Соту/Reality) держит лучше:**
+- Protocol-level reconnect + мультиплексирование. Рвётся туннель — восстанавливается прозрачно, приложения не замечают.
+- Reality/VLESS обфусцирован под TLS → DPI не режет.
+- Один раз поднял tun0 — весь трафик (включая прокси-туннели, если нужны) идёт стабильно.
+
+**Эмпирика (проверено сейчас):**
+- Contabo `:12343` напрямую → HTTP 405 (API живой, ~0.6с).
+- Fornex `:12342` → HTTP 000 (туннель есть, но squid на VPS лёг — отдельная проблема).
+- Timeweb в логах: reconnect каждые 10с, `Connection reset by peer` — DPI/firewall режет SSH-хендшейк.
+
+### Рекомендация по архитектуре
+**Основной канал = Соту (tun-VPN) + Direct прокси.** SSH-туннели — только как fallback для дома, где сеть стабильна и хочется не гонять весь трафик через VPN. На мобильном/даче SSH-туннели = боль. Юзер уже платит за Соту → это и есть «правильный» надёжный канал.
+
+Радикальный вариант (обсудить): **вообще выпилить SSH-туннели**, оставить Direct + Соту. Минус: теряешь возможность точечного прокси без VPN дома. Плюс: минус 4 источника зомби, минус вся эта диагностика. Для 1 юзера который «хочет чтоб работало» — возможно оправдано. Но это breaking → решать юзеру.
+
+---
+
+## ПРОБЛЕМА 3 — «Direct» не выбирается (кривой id)
+
+### Root cause
+`_parse_proxy_list()` (`proxy_manager.py:50`) генерит id из имени: `name.lower().replace(" ", "-")`. Для `Direct (VPN/Соту)` → id = `direct-(vpn/соту)` (кириллица + скобки + слеш). `POST /api/proxy/select/direct` не находит — реальный id мангленный.
+
+### Решение (ТРИВИАЛЬНО, ~3 строки)
+Когда `url == "direct"` — форсить `id = "direct"` в парсере:
+```python
+# proxy_manager.py, в _parse_proxy_list, после определения url:
+if url == "direct":
+    pid = "direct"
+```
+- Файл: `app/proxy_manager.py:48-57`.
+- Сложность: тривиально. Риск: если в DB сохранён старый id `direct-(vpn/соту)` — `load_saved_proxy` его не найдёт, но упадёт в fallback (первый прокси). Разово поправить kv: `UPDATE kv SET value='direct' WHERE key='active_proxy' AND value LIKE 'direct%'`.
+
+**Бонус:** упростить имя в `.env` до `Direct|direct` (убрать скобки/кириллицу) — тогда и id чистый без правки кода. Но правка кода надёжнее (не зависит от того как юзер назовёт).
+
+---
+
+## ПРОБЛЕМА 4 — зомби копятся: reconnect-loop для мёртвых VPS бесконечен
+
+### Root cause (подтверждено логами)
+`_tunnel_loop` (`ssh_tunnel.py:93`) реконнектится **вечно каждые 5с**, без health-gate и без cap. Логи:
+```
+tunnel timeweb died pid=X: kex_exchange_identification: Connection reset  (каждые 10с, бесконечно)
+tunnel ezhik died: Connection closed by 194.87.250.243
+```
+Мёртвый VPS → ssh спавнится, дохнет, спавнится снова. Окно где старый (зависший на dead route) + новый overlap = накопление зомби. Мой `_kill_stale` чистит при СТАРТЕ, но не во время runtime-цикла.
+
+### Решение — health-gate + exponential backoff (СРЕДНЯЯ, ~20 строк)
+1. **Exponential backoff** вместо фиксированных 5с: 5 → 10 → 20 → 40 → max 300с. Мёртвый VPS перестаёт спамить каждые 10с.
+2. **Health-gate**: перед спавном ssh — быстрый TCP-check `:22` (2с timeout). Недоступен → сразу backoff, не спавнить ssh вообще (не плодить процессы).
+3. **Reset backoff** при успешном коннекте (форвард простоял > 60с = здоров → сброс на 5с).
+
+Псевдо (`ssh_tunnel.py:_tunnel_loop`):
+```python
+backoff = RECONNECT_DELAY
+while True:
+    if not await _port_open(t.host, 22, timeout=2):  # health-gate
+        logger.info(f"{t.name} :22 unreachable, backoff {backoff}s")
+        await asyncio.sleep(backoff)
+        backoff = min(backoff * 2, 300)
+        continue
+    started = time.monotonic()
+    # ... spawn ssh, communicate ...
+    if time.monotonic() - started > 60:  # прожил долго = здоров
+        backoff = RECONNECT_DELAY
+    else:
+        backoff = min(backoff * 2, 300)
+    await asyncio.sleep(backoff)
+```
+- Сложность: средняя. Риск: health-gate `:22` TCP-check может дать false-negative если VPS жив но :22 фильтрован от нашего IP (как Timeweb) — но это и есть корректное поведение (не долбиться в закрытую дверь).
+
+**Альтернатива-минимум:** просто exponential backoff без health-gate (~8 строк). Убирает спам, не убирает полностью зомби-окно. Health-gate — правильно, backoff — дёшево.
+
+---
+
+## DECISION TREE для юзера
+
+```
+┌─ Где я сейчас?
+│
+├─ 🏠 ДОМА (стабильный WiFi)
+│   → Прокси: Contabo Direct-tunnel (:12343). VPN не нужен.
+│   → Если не работает: включи Соту, переключись на Direct.
+│
+├─ 📱 МОБИЛЬНЫЙ (раздача с телефона)
+│   → Включи Соту (tun-VPN). Переключи Orchestra на "Direct".
+│   → SSH-туннели НЕ используй — рвутся, плодят зомби.
+│
+└─ 🌲 ДАЧА (слабая/DPI-сеть)
+    → Обязательно Соту (обфускация обходит DPI). Orchestra → "Direct".
+    → SSH-туннели тут почти гарантированно сдохнут (kex reset).
+```
+
+**Единственное действие юзера в идеале:** включил Соту → Orchestra сама увидела tun0 и переключилась на Direct. См. автоматизацию.
+
+---
+
+## АВТОМАТИЗАЦИЯ — «включил и работает»
+
+Цель: юзер не думает. Реализуется поверх фиксов 1-4.
+
+1. **NM dispatcher hook** (`scripts/99-orchestra-proxy`, уже написан в прошлой задаче) — при up/down/vpn-up дёргает `check-proxies.sh`. Ставит юзер разово (root).
+2. **check-proxies.sh** находит живой прокси, переключает Orchestra. НО сейчас требует рестарт (sed в .env). **Улучшение:** вместо sed .env — дёргать `POST /api/proxy/select/<id>` (после фикса #1 это реконнектит живых агентов без рестарта). Тогда переключение — hot, без потери сессий.
+3. **Авто-detect Соту**: если tun0 up (Соту) → авто-select "Direct" (весь трафик и так через VPN, прокси не нужен). Логика в `check-proxies.sh`: `ip link show tun0 up 2>/dev/null && select direct`.
+4. **Итоговый флоу мечты:** включил Соту → NM hook → check-proxies видит tun0 → `POST select/direct` → idle-агенты реконнектятся → работает. Ноль ручных действий.
+
+Реалистично? **Да**, но требует фикс #1 (hot-reconnect) + фикс #3 (direct выбирается). Без них — только рестарт-based автоматизация (грубее, рвёт сессии).
+
+---
+
+## Приоритет фиксов (для orchestrator, после approval)
+
+| # | Проблема | Фикс | Сложность | Отдача |
+|---|----------|------|-----------|--------|
+| 3 | Direct не выбирается | `id="direct"` форсить | тривиально (3 стр) | 🔥 разблокирует автоматизацию |
+| 4 | Зомби от мёртвых VPS | backoff + health-gate | средняя (20 стр) | 🔥 убирает спам/зомби |
+| 1 | Рассинхрон живых агентов | reconnect idle на select | средняя (30 стр) | 🔥 hot-switch без рестарта |
+| 2 | SSH vs VPN | документация + рекомендация Соту | нет кода | 📋 поведенческое |
+
+**Рекомендую делать в порядке 3 → 4 → 1.** #3 разблокирует «Direct» (основа мобильного сценария), #4 останавливает зомби-спам, #1 даёт hot-switch. #2 — не код, а рекомендация юзеру (юзать Соту на мобильном).
+
+---
+
+## Найденные баги/проблемы (сверх задачи)
+
+1. **`.env` HTTPS_PROXY — мёртвая строка.** DB `kv.active_proxy` перезаписывает при старте. Юзер меняет .env, ждёт эффекта — ничего. Либо документировать «источник истины = DB/дашборд, не .env», либо при старте синхронизировать. Путаница гарантирована.
+2. **Fornex squid (:3128) лёг** — `:12342` HTTP 000. SSH до Fornex есть, прокси-демон мёртв. Поднять squid или убрать Fornex.
+3. **Legacy `:12338` root-zombie** — старый ssh от root, наш pkill от maxim не достаёт. Разово: `sudo pkill -f "ssh -N -L 12338:"`.
+4. **check-proxies.sh переключает через sed .env + рестарт** — грубо (рвёт сессии). После фикса #1 переводить на `POST /api/proxy/select`.
+
+📝 RULE предлагаю (в DONE): When источник конфига неоднозначен (.env vs DB) → документировать ЯВНО кто побеждает, не оставлять юзера гадать почему правка .env не действует.
diff --git a/docs/tasks/proxy-fix/plan-simplify.md b/docs/tasks/proxy-fix/plan-simplify.md
new file mode 100644
index 000000000..702559404
--- /dev/null
+++ b/docs/tasks/proxy-fix/plan-simplify.md
@@ -0,0 +1,120 @@
+# Plan — вырезать hot-switch/DB, .env = единственный источник истины
+
+**Дата:** 2026-07-01
+**Требование:** прокси управляется ТОЛЬКО через `.env` HTTPS_PROXY + рестарт. Нет DB, нет hot-switch, нет cache/refresh. + #4 backoff/health-gate (багфикс зомби).
+
+---
+
+## Источник истины (после рефактора)
+```
+.env HTTPS_PROXY  →  systemd EnvironmentFile  →  os.environ (load_dotenv в lifespan)
+                                                    ├→ Orchestra process
+                                                    ├→ CLI агенты (backend_claude._make_client снимает os.environ)
+                                                    └→ MCP subprocess (runtime_env.MCP_BASE_ENV снимает os.environ при импорте)
+Сменить прокси: правка .env → sudo systemctl restart orchestra. Всё.
+```
+Ничего не мутирует `os.environ` в рантайме → рассинхрон невозможен by design.
+
+---
+
+## ЧЕКЛИСТ УДАЛЕНИЯ
+
+### 1. `app/proxy_manager.py` — вырезать всю мутацию/DB/cache
+Оставить: чтение `PROXY_LIST` из .env + on-demand `check` (проверка живости для дашборда). Read-only.
+- ❌ `load_saved_proxy()` — удалить (читала kv.active_proxy, мутировала os.environ)
+- ❌ `select_proxy()` — удалить (писала kv, мутировала os.environ + MCP_BASE_ENV)
+- ❌ `refresh_loop()` — удалить (фоновый рефреш)
+- ❌ `_cache`, `CACHE_TTL`, `_ts` штампы, stale-drop в `list_proxies` — удалить кеш целиком. `check`/`check_all` возвращают результат напрямую, дашборд дёргает on-demand
+- ❌ `_active_id`, `_get_active_id()`, `load_saved_proxy` — удалить (нет «активного» состояния)
+- ✅ `_parse_proxy_list()` — оставить (читает .env)
+- ✅ `check_proxy()` / `_do_check()` / `check_all()` — оставить, но без записи в `_cache` (возвращать напрямую)
+- ✅ `list_proxies()` — оставить, но БЕЗ `active` флага и БЕЗ кеша: просто список из .env. «Активный» = тот что в HTTPS_PROXY (можно пометить сравнением с `os.environ["HTTPS_PROXY"]`, read-only, для индикатора)
+- Импорты `kv_get/kv_set`, `MCP_BASE_ENV`, `time`, `kv_set` — убрать осиротевшие
+
+**Альтернатива (проще, обсудить):** оставить `proxy_manager` как есть по структуре, но урезать до 2 методов: `list_proxies()` (read .env + пометить активный из os.environ) + `check_all()` (on-demand живость). Файл ~60 строк вместо 207. **Выбираю этот вариант** — proxy_manager нужен дашборду для списка+check, целиком выпиливать = больше правок в routes/frontend.
+
+### 2. `app/routes/proxy.py`
+- ❌ `POST /api/proxy/select/{proxy_id}` — удалить endpoint целиком (вместе с interrupt-логикой живых агентов)
+- ✅ `GET /api/proxy/list` — оставить (read-only список)
+- ✅ `POST /api/proxy/check/{proxy_id}` — оставить (on-demand проверка)
+- ✅ `GET /api/tunnel/status` — оставить
+
+### 3. `app/main.py` (lifespan)
+- ❌ строка 25 `proxy_manager.load_saved_proxy()` — удалить
+- ❌ строка 57 `proxy_refresh_task = asyncio.create_task(proxy_manager.refresh_loop())` + cancel в shutdown — удалить
+- ✅ `load_dotenv()` уже грузит .env → os.environ. Это и есть источник
+
+### 4. `app/db.py` (kv)
+- Код к `active_proxy` не обращается после удаления из proxy_manager → kv-таблица остаётся (мёртвая колонка, миграцию НЕ трогаем per требование). Разово почистить строку: `DELETE FROM kv WHERE key='active_proxy'` (или оставить — код её не читает)
+
+### 5. `app/ssh_tunnel.py` — #4 багфикс (backoff + health-gate)
+- ✅ `_port_open(host, port, timeout)` — TCP health-probe (УЖЕ написан в WIP)
+- ✅ exponential backoff 5→300с в `_tunnel_loop` (УЖЕ написан в WIP)
+- ✅ health-gate перед спавном ssh (УЖЕ написан, НО баг — см. ниже)
+- ⚠️ **БАГ в текущем WIP**: тест показал health-gate НЕ заблокировал спавн к unroutable `10.255.255.1` (1 ssh проспавнился). Причина: `open_connection` к blackhole-IP не фейлится быстро (SYN без RST висит до сетевого таймаута, не до нашего `HEALTH_TIMEOUT=2`). Реально `wait_for(timeout=2)` ДОЛЖЕН отменить через 2с → вернуть False. Надо перепроверить: возможно тест словил race (loop успел войти в spawn до первого probe). Исправление: probe СТРОГО до spawn в начале итерации (уже так), + увеличить проверку в тесте (ждать >HEALTH_TIMEOUT). Разберусь при реализации, тест дам корректный.
+
+### 6. `scripts/check-proxies.sh`
+- Оставить как ДИАГНОСТИКУ. Убрать автопереключение через API (его и не было — он писал в .env через sed). Оставить sed .env + подсказку «рестартни orchestra». Это ок — .env источник истины, sed в .env легитимен.
+- Убрать переключение Codex/TG? Нет — оставить (它們 тоже читают .env-подобные враппера). Не трогаю сверх нужного.
+
+### 7. Frontend `app/static/js/app.js` (координирую с frontend-opus ИЛИ сам — мелко)
+- ❌ `.proxy-select-btn` кнопка (строка 4896) + её handler (4911-4920) — удалить. Переключение только через .env
+- ✅ `.proxy-check-btn` (Check живости) — оставить
+- ✅ `loadProxyList` — оставить (список + индикатор активного)
+- ✅ `#proxy-check-all` — оставить
+- Индикатор «активный» = сравнение url с текущим HTTPS_PROXY (бэк отдаёт флаг). Строки 4921-4925 оставить
+
+### 8. `CLAUDE.md` — задокументировать источник истины
+Добавить секцию:
+```
+## 🔌 ПРОКСИ (единственный источник истины)
+- **`.env` HTTPS_PROXY = ЕДИНСТВЕННЫЙ источник.** Нет DB, нет hot-switch, нет кеша
+- Сменить прокси: правка `HTTPS_PROXY` в .env → `sudo systemctl restart orchestra`
+- systemd EnvironmentFile → os.environ → наследуют все (Orchestra, CLI агенты, MCP)
+- Дашборд: только индикатор + Check (проверить живость). Кнопки «выбрать» НЕТ
+- `scripts/check-proxies.sh` — диагностика, подсказывает живой прокси (вписывает в .env, но рестарт — руками)
+```
+
+---
+
+## Что НЕ трогаем
+- DB миграции (мёртвая kv-колонка пусть висит)
+- SSH туннели по сути (только #4 багфикс)
+- backend_claude._make_client (снимает os.environ — правильно, .env источник)
+- runtime_env.MCP_BASE_ENV (снимает os.environ при импорте — правильно)
+- Codex/TG враппера
+
+---
+
+## Риски / edge cases
+1. **`list_proxies` без `active` флага** — фронт (4921) ищет `p.active`. Надо либо оставить `active` (вычислять из os.environ, read-only), либо поправить фронт. Оставлю `active` (read-only вычисление) → фронт не трогать сверх удаления кнопки.
+2. **`load_saved_proxy` удаление** — сейчас восстанавливал прокси при старте из DB. После удаления прокси берётся ТОЛЬКО из .env (load_dotenv). Если .env HTTPS_PROXY пуст → нет прокси (Direct). Это корректное новое поведение
+3. **kv.active_proxy=fornex-nl в DB** — после удаления кода не читается. Оставить или DELETE — не влияет. Сделаю DELETE для чистоты
+4. **#4 health-gate race** — разобраться почему тест показал спавн. Дать корректный тест (мёртвый VPS → 0 ssh за >HEALTH_TIMEOUT)
+
+---
+
+## Порядок реализации
+1. #4 багфикс ssh_tunnel (backoff + health-gate, починить тест) — уже WIP
+2. Вырезать proxy_manager до read-only (list + check)
+3. Удалить select endpoint + main.py refresh_loop/load_saved_proxy
+4. Фронт: убрать select-кнопку
+5. CLAUDE.md секция
+6. kv DELETE active_proxy
+7. Тесты: старт, list из .env, select-endpoint 404, #4 зомби
+
+Коммиты раздельные: `#4 backoff`, `simplify: .env single source`.
+
+---
+
+## Codex review — НЕ УДАЛСЯ (proxy churn)
+Codex exec упал: `websocket connection refused (chatgpt.com)`. Причина — Codex-враппер ходит через мёртвый прокси (`:12340` Ёжик / `:12342` Fornex squid down). Ирония: та самая проблема которую чиним ломает и Codex. Живой прокси сейчас только `:12343` Contabo (405), но Codex-враппер на него не настроен.
+
+### Self-review вместо Codex (все точки проверены grep'ом):
+1. **Импорты не сломаются**: `proxy_manager` юзают только `main.py` (2 строки — удаляю), `routes/proxy.py` (select — удаляю, list/check — оставляю). `runtime_env`/`backend_claude` берут прокси из `os.environ` напрямую, `proxy_manager` не импортят. ✅
+2. **select endpoint** — зовётся ТОЛЬКО из frontend (app.js:4916). Нет в tests/mcp_stdio/scripts. Безопасно удалить. ✅
+3. **`p.active`** — 4 использования (highlight/badge/select-btn/indicator). Оставляю `active` вычисляемым read-only из `os.environ["HTTPS_PROXY"]` → фронт трогаю МИНИМАЛЬНО (только select-кнопку). ✅
+4. **load_saved_proxy удаление** — прокси берётся из .env через `load_dotenv()` в lifespan (строка 22, ДО остального). Достаточно. Пустой HTTPS_PROXY → Direct (корректно). ✅
+5. **#4 health-gate — БАГА НЕТ** (перепроверил чисто): `open_connection` к blackhole `10.255.255.1:22` таймаутит РОВНО за 2с (`wait_for` отменяет). Тест на чистом окружении: dead VPS → **0 ssh спавнов**. Прошлый «1 ssh» = stale-процесс от предыдущего прогона теста засорял `pgrep`, не баг гейта. `_port_open` верен: open→True, closed→False, blackhole→False(2s). ✅
+
+Retry Codex — когда починим прокси (после этого же рефактора). Не блокер: deletion-план, все зависимости выверены grep'ом.
diff --git a/docs/tasks/proxy-fix/report.md b/docs/tasks/proxy-fix/report.md
new file mode 100644
index 000000000..709500059
--- /dev/null
+++ b/docs/tasks/proxy-fix/report.md
@@ -0,0 +1,76 @@
+# Report — прокси: .env единственный источник истины + #3/#4 фиксы
+
+**Дата:** 2026-07-01
+**Задача:** упростить управление прокси до `.env` + рестарт. Вырезать DB/hot-switch/cache. + #3 direct id, #4 zombie backoff.
+
+---
+
+## Что сделано
+
+### #3 — Direct id fix (commit 19176e3)
+`_parse_proxy_list()` форсит `id="direct"` когда `url=="direct"`. Раньше id генерился из имени → `direct-(vpn/соту)` (кириллица+скобки) → `POST /api/proxy/select/direct` 404'ил. Имя в `.env` упрощено до `Direct`.
+
+### #4 — Zombie backoff + health-gate (commit 5fec40a)
+`ssh_tunnel.py _tunnel_loop`:
+- TCP health-gate `_port_open(host, 22, 2s)` перед спавном ssh — не долбиться в недоступный VPS.
+- Exponential backoff 5→300с (`BACKOFF_MAX`) вместо фиксированных 5с.
+- Reset backoff при uptime >60с (`HEALTHY_UPTIME`) — здоровый туннель.
+- Устраняет бесконечный спам мёртвых VPS (timeweb/ezhik: `kex_exchange_identification: Connection reset` каждые 10с в логах).
+
+### Основной рефактор — .env single source (commit 916047b)
+**Root cause рассинхрона (докопался):** DB `kv.active_proxy` побеждал `.env` (`load_saved_proxy` перезаписывал `os.environ` при старте). Живые CLI-агенты держали разный прокси — `backend_claude._make_client()` снимает `os.environ["HTTPS_PROXY"]` в момент `connect()` в персистентный клиент.
+
+**Вырезано:**
+- `proxy_manager.py` → read-only: удалены `load_saved_proxy`, `select_proxy`, `refresh_loop`, `_cache`/`CACHE_TTL`, `_active_id` state. Осталось `list_proxies` (active из `os.environ`) + `check_all` (on-demand). −107 строк net.
+- `routes/proxy.py` → удалён `POST /api/proxy/select`.
+- `main.py` → убраны `load_saved_proxy()` + `refresh_loop` task.
+- `app.js` → убрана select-кнопка + handler.
+- DB → `DELETE kv active_proxy` (миграция не тронута).
+- Codex-враппер → добавлен `HTTP_PROXY` (websocket падал без него).
+- CLAUDE.md → секция «🔌 ПРОКСИ».
+
+---
+
+## Файлы
+
+| Файл | Изменение |
+|------|-----------|
+| `app/proxy_manager.py` | −107 net (read-only) |
+| `app/ssh_tunnel.py` | +30 (#4 backoff+gate), +#3 в парсере |
+| `app/routes/proxy.py` | −20 (select endpoint) |
+| `app/main.py` | −4 (load_saved+refresh) |
+| `app/static/js/app.js` | −11 (select btn+handler) |
+| `tests/route_surface_snapshot.json` | −6 (select route) |
+| `tests/test_proxy.py` | +82 (новый, 6 тестов) |
+| `CLAUDE.md` | +секция прокси |
+| `~/.local/bin/codex` | +HTTP_PROXY |
+
+---
+
+## Тесты
+- `tests/test_proxy.py` — 6 новых, все зелёные: direct id стабилен, active из env, no-mutation-methods удалены, port probe (open/closed), health-gate блокирует dead VPS спавн.
+- Полный релевантный набор: **48 passed**. 2 fail (`test_route_surface_snapshot`, `test_api::test_list_empty`) — **пре-экзистинг** на base (env: auth-mode + `/workspace` sandbox mkdir; проверено `git stash`).
+
+## Codex review
+⚠️ **Output tool не записал файл** (recurring flakiness — reported "done" но файла нет ни в worktree, ни в main repo). Первый прогон вообще упал (websocket refused — Codex-враппер ходил без HTTP_PROXY, теперь починено).
+
+**Self-review вместо** (все точки выверены grep + import-test):
+1. Dangling refs: `MCP_BASE_ENV`/`kv_get`/`kv_set`/`time` удалены из proxy_manager. `MCP_BASE_ENV` жив в runtime_env+manager (не осиротел).
+2. `_active_id` из `os.environ["HTTPS_PROXY"]` — edge HTTP_PROXY без HTTPS покрыт (`or` fallback), в .env оба ставятся вместе.
+3. `select` endpoint — звался ТОЛЬКО из frontend. Удалён вместе.
+4. proxy_manager singleton потерял `_active_id`/`_cache` state — ок для read-only.
+5. `app.main` + `routes.proxy` импортятся, старт-путь чист.
+
+---
+
+## Breaking changes
+- `POST /api/proxy/select` удалён — переключение прокси только через .env+рестарт.
+- Прокси НЕ восстанавливается из DB при старте — берётся из .env (load_dotenv). Если .env HTTPS_PROXY пуст → Direct.
+
+## Осталось юзеру (root/ручное)
+1. Установить NM hook (из прошлой итерации): `sudo cp scripts/99-orchestra-proxy /etc/NetworkManager/dispatcher.d/ && sudo chmod 755 ...`
+2. Прибить legacy root-zombie: `sudo pkill -f "ssh -N -L 12338:"`.
+3. Fornex squid (:3128) лёг — поднять или оставить fallback.
+
+## 📝 RULE (предложен, ждёт approval)
+When источник конфига неоднозначен (.env vs DB) → документировать ЯВНО кто побеждает, не оставлять юзера гадать почему правка .env не действует. → добавлено в CLAUDE.md секцию «🔌 ПРОКСИ».
diff --git a/tests/route_surface_snapshot.json b/tests/route_surface_snapshot.json
index 0368c3a7e..24025fa4c 100644
--- a/tests/route_surface_snapshot.json
+++ b/tests/route_surface_snapshot.json
@@ -114,46 +114,40 @@
   ]
  ],
  [
   "/api/projects",
   [
    "GET"
   ]
  ],
  [
   "/api/proxy/check/{proxy_id}",
   [
    "POST"
   ]
  ],
  [
   "/api/proxy/list",
   [
    "GET"
   ]
  ],
- [
-  "/api/proxy/select/{proxy_id}",
-  [
-   "POST"
-  ]
- ],
  [
   "/api/report_bug",
   [
    "POST"
   ]
  ],
  [
   "/api/restart",
   [
    "POST"
   ]
  ],
  [
   "/api/role-icons",
   [
    "GET"
   ]
  ],
  [
   "/api/sessions",
diff --git a/tests/test_proxy.py b/tests/test_proxy.py
new file mode 100644
index 000000000..e4e4f1988
--- /dev/null
+++ b/tests/test_proxy.py
@@ -0,0 +1,83 @@
+"""Proxy manager (read-only, .env source of truth) + ssh_tunnel health-gate."""
+
+import asyncio
+
+import pytest
+
+from app import proxy_manager as pm
+from app import ssh_tunnel as st
+
+
+@pytest.fixture(autouse=True)
+def _clean_proxy_env(monkeypatch):
+    for k in ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy"):
+        monkeypatch.delenv(k, raising=False)
+    monkeypatch.delenv("PROXY_LIST", raising=False)
+
+
+def test_direct_id_stable(monkeypatch):
+    monkeypatch.setenv("PROXY_LIST", "Direct (VPN/Соту)|direct,Contabo DE|http://127.0.0.1:12343")
+    entries = pm._parse_proxy_list()
+    assert entries[0].id == "direct"  # not mangled 'direct-(vpn/соту)'
+    assert entries[1].id == "contabo-de"
+
+
+@pytest.mark.asyncio
+async def test_active_follows_env(monkeypatch):
+    monkeypatch.setenv("PROXY_LIST", "Direct|direct,Contabo|http://127.0.0.1:12343,Fornex|http://127.0.0.1:12342")
+    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:12343")
+    mgr = pm.ProxyManager()
+    r = await mgr.list_proxies()
+    assert r["active"] == "contabo"
+    # list carries NO cached liveness — that's on-demand via check
+    assert all("ok" not in p for p in r["proxies"])
+
+
+@pytest.mark.asyncio
+async def test_active_direct_when_no_env(monkeypatch):
+    monkeypatch.setenv("PROXY_LIST", "Direct|direct,Contabo|http://127.0.0.1:12343")
+    r = await pm.ProxyManager().list_proxies()
+    assert r["active"] == "direct"
+
+
+def test_no_mutation_methods_gone():
+    # hot-switch / DB persistence removed — .env is the only source
+    mgr = pm.ProxyManager()
+    assert not hasattr(mgr, "select_proxy")
+    assert not hasattr(mgr, "load_saved_proxy")
+    assert not hasattr(mgr, "refresh_loop")
+
+
+@pytest.mark.asyncio
+async def test_port_open_probe():
+    # closed port → False, fast
+    assert await st._port_open("127.0.0.1", 1, timeout=1) is False
+    # open port → True
+    server = await asyncio.start_server(lambda r, w: w.close(), "127.0.0.1", 0)
+    port = server.sockets[0].getsockname()[1]
+    try:
+        assert await st._port_open("127.0.0.1", port, timeout=2) is True
+    finally:
+        server.close()
+
+
+@pytest.mark.asyncio
+async def test_health_gate_blocks_dead_vps():
+    # unroutable host → health-gate must NOT spawn ssh
+    t = st.Tunnel(name="dead", local_port=19997, host="10.255.255.1",
+                  remote_port=3128, key_path="")
+    task = asyncio.create_task(st._tunnel_loop(t))
+    await asyncio.sleep(st.HEALTH_TIMEOUT + 1)  # one failed probe → backoff
+    # match only real ssh processes (comm==ssh) — pgrep -f self-matches this
+    # test's own cmdline otherwise
+    proc = await asyncio.create_subprocess_exec(
+        "pgrep", "-x", "ssh", "-f", "ssh -N -L 19997:127.0.0.1:",
+        stdout=asyncio.subprocess.PIPE)
+    out, _ = await proc.communicate()
+    task.cancel()
+    try:
+        await task
+    except asyncio.CancelledError:
+        pass
+    assert not out.decode().strip(), "dead VPS must not spawn ssh"
+    assert t.running is False


## Later history of the touched files on main (after this commit)

816 later commits touch these paths; the first 40 (oldest first):
1050a6580 2026-07-01 #proxy-fix: POST /api/proxy/set-env — write proxy to .env (no hot-switch)
6ce9c9c5c 2026-07-01 proxy: replace hot-switch with .env write + restart flow
1473e3745 2026-07-01 #proxy-fix: check liveness via Anthropic, ipinfo geo best-effort
3a3757ee6 2026-07-03 feat: visible rate-limit banner with countdown timer
3ef921eac 2026-07-03 feat: full sub-agent telemetry — subagents table + transcript endpoints
507a042ad 2026-07-03 feat: sub-agents telemetry modal with cards + transcripts
b9acb11fc 2026-07-03 docs: cleanup research — dead-code list + super-full-cycle roles plan
3478d558f 2026-07-03 feat: super-full-cycle role (research+experiment + ticketing), remove researcher/experimenter
5835b65b3 2026-07-03 docs: Fable 5 restored 2026-07-03 (verified live), was dead since 06-15
49c088f32 2026-07-03 docs: PROCESS RULE — orchestrator brevity, don't narrate tool calls / duplicate status
ce24f5032 2026-07-03 docs: session notes 2026-07-03 + open bugs
d0620cd24 2026-07-03 fix: readable sub-agents modal + markdown in .md file preview
51ccd702a 2026-07-03 Add SOCKS5 dynamic tunnel mode for proxychains (TG without Hiddify)
3f8fedcf3 2026-07-06 Session notes 2026-07-06: VPS deploy, Opus 4.6 restore, migration script, frontend fixes
a4805f9ed 2026-07-07 fix: hide 'Load 500 more' in empty/short chat
00eff7863 2026-07-07 Fix: show New Orchestrator button when auth enabled (was hidden by enterprise guard)
710a21be7 2026-07-07 Fix: rate-limit banner persists on agent switch + triggers on history replay
538a2f568 2026-07-07 fix: send_file shows Download/Preview instead of 'Disabled on server'
45f2d671c 2026-07-07 Session notes 2026-07-07: VPS finalization, frontend fixes, cleanup
b9e532d00 2026-07-07 Remove enterprise auth-guard: show all UI elements regardless of auth
9e56a8bed 2026-07-07 Add proxychains dual-config rule (user config has priority over /etc)
15f41d330 2026-07-07 fix: proxy check status not showing (always ⚪)
01e76200e 2026-07-07 feat: proxy panel — ping (colored latency) + IP + flag
7989faa38 2026-07-07 feat: image thumbnail in send_file bubbles
d206a4c44 2026-07-09 fix: no character loss — wrap instead of truncate everywhere
6bae186b6 2026-07-09 fix: no character loss — wrap instead of truncate everywhere
d7dcb84c1 2026-07-09 Session notes 2026-07-09: research day, prompt modules, cache timer, optimizations
a42803ec2 2026-07-10 Compact cache pill: inline with model, shorter labels, 10px font
b77de807f 2026-07-10 Compact agent list: short model names (opus-4-8 not claude-opus-4-8[1m]), cache pill inline before model
dfa28d5d5 2026-07-10 Model color badges in agent list + cache indicator on orchestrator tabs
eb142623d 2026-07-10 feat: cache hit/miss stats in usage analytics modal
ce612a29d 2026-07-11 Session notes 2026-07-09 to 07-11: shipped features, research, pending
22a6a78c6 2026-07-11 WIP: auto-saved uncommitted changes before worker spawn (2026-07-11 13:14)
8fb4b4763 2026-07-12 WIP: auto-saved uncommitted changes before worker spawn (2026-07-12 20:24)
2573942f9 2026-07-12 #rag-orchestra: RAG semantic memory (bge-m3 + sqlite-vec hybrid) ported from kesha
11f2e2a02 2026-07-16 Session 07-11 to 07-16: effort, RAG, Sol, Interaction Tax, worker-spawning, cache pills, TG UTF-16
38caf30b2 2026-07-17 WIP: auto-saved uncommitted changes before worker spawn (2026-07-17 12:03)
0c1804441 2026-07-17 refactor: make agent runtimes provider-agnostic
3b2b2415a 2026-07-17 fix: correlate subagent lifecycle events
b7c1e7940 2026-07-18 #usage: fix analytics agents/all-time period — request full range not capped 7d/365d

## Patches of the first 8 later commits, restricted to the touched paths (each capped at 150 lines)

### 1050a6580 #proxy-fix: POST /api/proxy/set-env — write proxy to .env (no hot-switch)

diff --git a/CHANGELOG.md b/CHANGELOG.md
index b615ce790..2b1d6926f 100644
--- a/CHANGELOG.md
+++ b/CHANGELOG.md
@@ -1,7 +1,17 @@
 # Changelog
 
+## v2.24.1 — 2026-07-01
+
+### Added
+- 🔀 **`POST /api/proxy/set-env` — сменить прокси кнопкой без ручной правки .env** — фронт шлёт `{"id": "contabo-de"}`, endpoint находит прокси в `PROXY_LIST` и переписывает ТОЛЬКО строки `HTTPS_PROXY`/`HTTP_PROXY` в `.env` (line-surgery через `(?m)^KEY=.*$`, токены TG/YouGile нетронуты). `url=="direct"` → пустое значение (прямой выход). Ответ `{"ok": true, "wrote": <url>, "need_restart": true}`.
+  - **НЕ hot-switch**: `os.environ` НЕ трогается, DB НЕ трогается. `.env` остаётся источником истины, применяется юзером через рестарт. Возврат старого `select_proxy` (мутировал env на лету → рассинхрон) исключён by design.
+  - **Реализация** (`app/routes/proxy.py`): `_set_env_proxy(url)` — atomic write (temp + `os.replace`, .env с токенами не должен побиться при crash). `ENV_FILE = Path(__file__).parent.parent.parent/.env` (= systemd `EnvironmentFile`/`WorkingDirectory`). `re.sub` с lambda-replacement (URL/пароль пишутся буквально, без `\`-escape).
+  - **Codex review**: 0 багов (проверены regex-anchor vs PROXY_LIST, case-sensitivity vs `https_proxy`, path traversal через `body.id`, direct→empty). Atomic write добавлен по остаточному замечанию.
+  - **Tests**: `tests/test_proxy.py` — token preservation, direct→empty, append-when-missing (9 pass).
+  - **Frontend**: кнопка выбора прокси под этот контракт — за frontend-opus.
+
 ## v2.24.0 — 2026-07-01
 
 ### Changed
 - 🔌 **Прокси: `.env` HTTPS_PROXY = единственный источник истины (вырезан DB/hot-switch)** — юзер: «всё лишнее вырежем». Управление прокси только через `.env` + `sudo systemctl restart orchestra`. Вся runtime-мутация env удалена → рассинхрон (`.env` показывал 12343, а CLI-агенты держали 12342 из DB) стал невозможен by design.
   - **Root cause рассинхрона**: `kv.active_proxy` в DB **побеждал** `.env` — `load_saved_proxy()` при старте перезаписывал `os.environ` из DB. А живые CLI-агенты держали РАЗНЫЙ прокси, т.к. `backend_claude._make_client()` снимает `os.environ["HTTPS_PROXY"]` в момент `connect()` и запаивает в персистентный SDK-клиент (проверено: pid A→12334, pid B→12342).
diff --git a/app/routes/proxy.py b/app/routes/proxy.py
index 30e95f78a..b953ae20f 100644
--- a/app/routes/proxy.py
+++ b/app/routes/proxy.py
@@ -1,22 +1,54 @@
 """Proxy & Tunnel API routes."""
 
+import os
+import re
+from pathlib import Path
+
 from fastapi import APIRouter, HTTPException
 from fastapi.responses import JSONResponse
+from pydantic import BaseModel
 
 from app.auth import is_auth_enabled
-from app.proxy_manager import proxy_manager
+from app.proxy_manager import proxy_manager, _parse_proxy_list
 from app.ssh_tunnel import tunnel_status
 
 router = APIRouter(tags=["proxy"])
 
+# The .env systemd reads (EnvironmentFile + WorkingDirectory = repo root).
+# parent.parent.parent: routes/ → app/ → repo root.
+ENV_FILE = Path(__file__).resolve().parent.parent.parent / ".env"
+
 
 def _block_if_enterprise():
     if is_auth_enabled():
         raise HTTPException(403, "Not available")
 
 
+def _set_env_proxy(url: str) -> None:
+    """Rewrite ONLY the HTTPS_PROXY/HTTP_PROXY lines in .env, in place.
+
+    WHY line-surgery (not load_dotenv/rewrite): .env holds TG/YouGile tokens —
+    a full rewrite could mangle them. url=="direct" → empty value (direct exit).
+    Does NOT touch os.environ: .env is the source of truth, applied on restart.
+    """
+    value = "" if url == "direct" else url
+    text = ENV_FILE.read_text(encoding="utf-8")
+    for key in ("HTTPS_PROXY", "HTTP_PROXY"):
+        pattern = rf"(?m)^{key}=.*$"
+        line = f"{key}={value}"
+        if re.search(pattern, text):
+            # lambda replacement — treat `line` literally (no \-escape in URL/pass)
+            text = re.sub(pattern, lambda _m: line, text)
+        else:
+            text = text.rstrip("\n") + f"\n{line}\n"
+    # Atomic write — .env holds tokens; a crash mid-write must not corrupt it
+    tmp = ENV_FILE.parent / (ENV_FILE.name + ".tmp")
+    tmp.write_text(text, encoding="utf-8")
+    os.replace(tmp, ENV_FILE)  # same fs → atomic rename
+
+
 @router.get("/api/proxy/list")
 async def proxy_list():
     _block_if_enterprise()
     return await proxy_manager.list_proxies()
 
@@ -28,9 +60,27 @@ async def proxy_check(proxy_id: str):
     if result.get("error"):
         return JSONResponse(result, status_code=400)
     return result
 
 
+class SetEnvBody(BaseModel):
+    id: str
+
+
+@router.post("/api/proxy/set-env")
+async def proxy_set_env(body: SetEnvBody):
+    """Write chosen proxy into .env (HTTPS_PROXY/HTTP_PROXY). Applied on restart.
+
+    NOT hot-switch: os.environ is untouched. .env is the single source of truth.
+    """
+    _block_if_enterprise()
+    entry = next((e for e in _parse_proxy_list() if e.id == body.id), None)
+    if not entry:
+        return JSONResponse({"ok": False, "error": "proxy not found"}, status_code=404)
+    _set_env_proxy(entry.url)
+    return {"ok": True, "wrote": entry.url, "id": entry.id, "need_restart": True}
+
+
 @router.get("/api/tunnel/status")
 async def api_tunnel_status():
     _block_if_enterprise()
     return tunnel_status()
diff --git a/tests/test_proxy.py b/tests/test_proxy.py
index e4e4f1988..ba55dcc54 100644
--- a/tests/test_proxy.py
+++ b/tests/test_proxy.py
@@ -4,10 +4,11 @@ import asyncio
 
 import pytest
 
 from app import proxy_manager as pm
 from app import ssh_tunnel as st
+from app.routes import proxy as proxy_routes
 
 
 @pytest.fixture(autouse=True)
 def _clean_proxy_env(monkeypatch):
     for k in ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy"):
@@ -46,10 +47,53 @@ def test_no_mutation_methods_gone():
     assert not hasattr(mgr, "select_proxy")
     assert not hasattr(mgr, "load_saved_proxy")
     assert not hasattr(mgr, "refresh_loop")
 
 
+def test_set_env_preserves_tokens(tmp_path, monkeypatch):
+    env = tmp_path / ".env"
+    env.write_text(
+        "HTTPS_PROXY=http://127.0.0.1:12343\n"
+        "HTTP_PROXY=http://127.0.0.1:12343\n"
+        "TG_BOT_TOKEN=123:ABC_secret\n"
+        "YOUGILE_KEY=xyz|special@chars\n"
+        "PROXY_LIST=Direct|direct,Contabo|http://127.0.0.1:12343\n",
+        encoding="utf-8")
+    monkeypatch.setattr(proxy_routes, "ENV_FILE", env)
+
+    proxy_routes._set_env_proxy("http://127.0.0.1:12342")
+    out = env.read_text()
+    assert "HTTPS_PROXY=http://127.0.0.1:12342" in out
+    assert "HTTP_PROXY=http://127.0.0.1:12342" in out
+    assert "TG_BOT_TOKEN=123:ABC_secret" in out  # tokens untouched
### 6ce9c9c5c proxy: replace hot-switch with .env write + restart flow

diff --git a/app/static/js/app.js b/app/static/js/app.js
index d2f44a1fe..1bab70e59 100644
--- a/app/static/js/app.js
+++ b/app/static/js/app.js
@@ -4873,30 +4873,37 @@ async function loadProxyList() {
             list.innerHTML = '<div class="text-[10px] text-slate-500 text-center py-2">No proxies configured.<br>Set PROXY_LIST in .env</div>';
             return;
         }
         for (const p of proxies) {
             const el = document.createElement('div');
-            el.className = `flex items-center gap-2 px-2.5 py-2 rounded-lg cursor-pointer transition-colors ${p.active ? 'bg-indigo-900/40 border border-indigo-500/50' : 'bg-slate-800/50 border border-slate-700/50 hover:bg-slate-700/50'}`;
+            el.className = `flex items-center gap-2 px-2.5 py-2 rounded-lg transition-colors ${p.active ? 'bg-indigo-900/40 border border-indigo-500/50' : 'bg-slate-800/50 border border-slate-700/50 hover:bg-slate-700/50'}`;
             const status = p.ok === true ? '🟢' : p.ok === false ? '🔴' : '⚪';
+            const statusTitle = p.ok === true ? 'Живой' : p.ok === false ? 'Мёртвый' : 'Не проверен';
             const flag = p.flag || '🏳️';
-            const ip = p.ip || '';
             const location = p.city ? `${p.city}, ${p.country || ''}` : p.country || '';
             el.innerHTML = `
-                <span class="text-sm">${status}</span>
+                <span class="text-sm" title="${statusTitle}">${status}</span>
                 <div class="flex-1 min-w-0">
                     <div class="flex items-center gap-1.5">
-                        <span class="text-xs font-medium text-white">${escHtml(p.name)}</span>
-                        ${p.active ? '<span class="text-[9px] px-1 py-0.5 bg-indigo-500/30 text-indigo-300 rounded">ACTIVE</span>' : ''}
+                        <span class="text-sm">${flag}</span>
+                        <span class="proxy-name text-xs font-medium text-white truncate">${escHtml(p.name)}</span>
+                        ${p.active ? '<span class="text-[9px] px-1 py-0.5 bg-indigo-500/30 text-indigo-300 rounded shrink-0">ACTIVE</span>' : ''}
                     </div>
-                    <div class="text-[10px] text-slate-500 truncate">${escHtml(p.url)}</div>
-                    ${ip ? `<div class="text-[10px] text-slate-400">${flag} ${ip} ${location ? '· ' + escHtml(location) : ''}</div>` : ''}
+                    ${location ? `<div class="text-[10px] text-slate-400 truncate">${escHtml(location)}</div>` : ''}
+                    <div class="proxy-url-line text-[9px] text-slate-600 truncate cursor-pointer hidden" title="Показать URL">${escHtml(p.url)}</div>
                     ${p.error ? `<div class="text-[10px] text-red-400 truncate">${escHtml(String(p.error).slice(0, 60))}</div>` : ''}
                 </div>
                 <div class="flex gap-1 shrink-0">
-                    <button class="proxy-check-btn text-[10px] px-1.5 py-0.5 bg-slate-700 hover:bg-slate-600 rounded text-slate-300" data-id="${p.id}" title="Check">🔍</button>
+                    <button class="proxy-check-btn text-[10px] px-1.5 py-0.5 bg-slate-700 hover:bg-slate-600 rounded text-slate-300" data-id="${p.id}" title="Проверить живость">🔍</button>
+                    ${!p.active ? `<button class="proxy-select-btn text-[10px] px-2 py-0.5 bg-indigo-600 hover:bg-indigo-500 rounded text-white font-medium" data-id="${p.id}" data-name="${escHtml(p.name)}" title="Выбрать этот прокси">Выбрать</button>` : ''}
                 </div>
             `;
+            // URL revealed on click of the name area — hidden by default to keep UI clean
+            el.querySelector('.proxy-name')?.addEventListener('click', (e) => {
+                e.stopPropagation();
+                el.querySelector('.proxy-url-line')?.classList.toggle('hidden');
+            });
             list.appendChild(el);
         }
         list.querySelectorAll('.proxy-check-btn').forEach(b => {
             b.addEventListener('click', async (e) => {
                 e.stopPropagation();
@@ -4905,18 +4912,55 @@ async function loadProxyList() {
                     await fetch(`/api/proxy/check/${b.dataset.id}`, {method:'POST'});
                     await loadProxyList();
                 } catch(err) { b.textContent = '❌'; }
             });
         });
+        list.querySelectorAll('.proxy-select-btn').forEach(b => {
+            b.addEventListener('click', async (e) => {
+                e.stopPropagation();
+                b.textContent = '⏳'; b.disabled = true;
+                try {
+                    const resp = await fetch('/api/proxy/set-env', {
+                        method: 'POST',
+                        headers: { 'Content-Type': 'application/json' },
+                        body: JSON.stringify({ id: b.dataset.id }),
+                    });
+                    const data = await resp.json();
+                    if (!resp.ok || data.ok === false) throw new Error(data.error || 'set-env failed');
+                    _showProxyRestartBanner(b.dataset.name, data.wrote);
+                } catch (err) {
+                    b.textContent = '❌'; b.disabled = false;
+                    console.warn('proxy set-env failed:', err);
+                }
+            });
+        });
         const active = proxies.find(p => p.active);
         if (active) {
             $('#proxy-flag').textContent = active.flag || '🌐';
             $('#proxy-ip').textContent = active.ip || '';
         }
     } catch (e) { console.warn('loadProxyList failed:', e); }
 }
 
+function _showProxyRestartBanner(name, wroteUrl) {
+    const banner = $('#proxy-restart-banner');
+    const msg = $('#proxy-restart-msg');
+    if (!banner || !msg) return;
+    msg.innerHTML = `<b>${escHtml(name)}</b> записан в .env${wroteUrl ? ` <span class="text-amber-400/60">(${escHtml(wroteUrl)})</span>` : ''}. Нажми Рестарт чтобы применить.`;
+    banner.classList.remove('hidden');
+    const btn = $('#proxy-restart-btn');
+    if (btn && !btn._wired) {
+        btn._wired = true;
+        btn.addEventListener('click', async (e) => {
+            e.stopPropagation();
+            btn.textContent = '⏳ Рестарт...'; btn.disabled = true;
+            try { await api('/api/restart', { method: 'POST' }); } catch {}
+            setTimeout(() => location.reload(), 3000);
+        });
+    }
+}
+
 // ── Profiles Manager (редактор реестра профилей Claude) ──
 
 let _profilesDropdownOpen = false;
 
 function initProfilesManager() {
### 1473e3745 #proxy-fix: check liveness via Anthropic, ipinfo geo best-effort

diff --git a/app/proxy_manager.py b/app/proxy_manager.py
index f4aad0e0f..c21b8fe70 100644
--- a/app/proxy_manager.py
+++ b/app/proxy_manager.py
@@ -24,12 +24,17 @@ COUNTRY_FLAGS = {
     "PL": "🇵🇱", "CZ": "🇨🇿", "RO": "🇷🇴", "BG": "🇧🇬",
     "HK": "🇭🇰", "TW": "🇹🇼", "IE": "🇮🇪", "ES": "🇪🇸",
     "IT": "🇮🇹", "PT": "🇵🇹", "DK": "🇩🇰", "LT": "🇱🇹",
     "LV": "🇱🇻", "EE": "🇪🇪", "IS": "🇮🇸", "MD": "🇲🇩",
 }
-IP_CHECK_URL = "https://ipinfo.io/json"
-IP_CHECK_TIMEOUT = 8
+# Liveness = can we reach Anthropic (what we actually use)? ANY HTTP response
+# (200/401/403/404) means the proxy tunnels fine. ipinfo.io was giving false
+# "dead" for live proxies (intermittent timeouts) — it's now best-effort geo only.
+LIVENESS_URL = "https://api.anthropic.com"
+GEO_URL = "https://ipinfo.io/json"
+CHECK_TIMEOUT = 8
+GEO_TIMEOUT = 5
 
 
 @dataclass
 class ProxyEntry:
     id: str
@@ -86,28 +91,40 @@ class ProxyManager:
         if not entry:
             return {"error": f"proxy '{proxy_id}' not found"}
         return await self._do_check(entry)
 
     async def _do_check(self, entry: ProxyEntry) -> dict:
+        """Two-tier: liveness via Anthropic (any HTTP response = alive), geo via
+        ipinfo (best-effort — its flakiness must NOT mark a live proxy dead)."""
+        proxy = entry.url if entry.url and entry.url != "direct" else None
         try:
-            kwargs = {"timeout": IP_CHECK_TIMEOUT, "verify": False}
-            if entry.url and entry.url != "direct":
-                kwargs["proxy"] = entry.url
-            async with httpx.AsyncClient(**kwargs) as client:
-                resp = await client.get(IP_CHECK_URL)
+            async with httpx.AsyncClient(timeout=CHECK_TIMEOUT, verify=False, proxy=proxy) as client:
+                await client.get(LIVENESS_URL)  # any response (200/401/403/404) = tunnel works
+        except Exception as e:
+            return {"id": entry.id, "ok": False, "error": str(e) or "unreachable"}
+        result = {"id": entry.id, "ok": True}
+        try:
+            result.update(await self._geo(proxy))  # best-effort, never flips ok
+        except Exception:
+            pass  # geo is decoration — its failure must not mark a live proxy dead
+        return result
+
+    async def _geo(self, proxy: str | None) -> dict:
+        try:
+            async with httpx.AsyncClient(timeout=GEO_TIMEOUT, verify=False, proxy=proxy) as client:
+                resp = await client.get(GEO_URL)
                 if resp.status_code != 200:
-                    return {"id": entry.id, "ok": False, "error": f"HTTP {resp.status_code}"}
+                    return {}
                 data = resp.json()
-                country = data.get("country", "??")
+                country = data.get("country", "")
                 return {
-                    "id": entry.id, "ok": True,
-                    "ip": data.get("ip", "?"), "country": country,
+                    "ip": data.get("ip", ""), "country": country,
                     "city": data.get("city", ""), "org": data.get("org", ""),
                     "flag": COUNTRY_FLAGS.get(country, "🏳️"),
                 }
-        except Exception as e:
-            return {"id": entry.id, "ok": False, "error": str(e)}
+        except Exception:
+            return {}  # geo unavailable — proxy still reported alive
 
     async def list_proxies(self) -> dict:
         """List proxies from .env. `active` = current HTTPS_PROXY (read-only).
 
         No liveness here — call check/{id} or check_all for that (on-demand).
diff --git a/app/static/js/app.js b/app/static/js/app.js
index 1bab70e59..760752b90 100644
--- a/app/static/js/app.js
+++ b/app/static/js/app.js
@@ -178,14 +178,14 @@ function connectSSE() {
                             localMessages.delete(m);
                             break;
                         }
                     }
                 } else {
-                    addChatEntry(l.type, l.content, l.ts);
+                    addChatEntry(l.type, l.content, l.ts, null, l);
                 }
             } else {
-                addChatEntry(l.type, l.content, l.ts);
+                addChatEntry(l.type, l.content, l.ts, null, l);
             }
             if (!chatLogs[selectedAgent]) chatLogs[selectedAgent] = { lastId: 0, firstId: null };
             // Live stream partials carry no id — skip id bookkeeping for them
             if (Number.isFinite(l.id)) {
                 if (l.id > chatLogs[selectedAgent].lastId) chatLogs[selectedAgent].lastId = l.id;
@@ -2061,14 +2061,52 @@ function _findLastBefore(parent, selector, anchor) {
     }
     return null;
 }
 
 const HIDE_THINKING = document.body.dataset.hideThinking === 'true';
+
+// Append a live sub-agent log line into its accordion body. If the accordion
+// isn't there yet (race: stream before start), no-op — the sub-agent block owns
+// its own rendering; live lines are best-effort decoration.
+function appendSubagentLog(subId, evType, content) {
+    const chat = $('#chat');
+    const host = chat.querySelector(`[data-subagent-id="${CSS.escape(subId)}"]`);
+    if (!host) return;
+    const body = host.querySelector('.sa-body');
+    if (!body) return;
+    if (evType === 'stream') {
+        // Coalesce contiguous stream text into one line (typewriter feel)
+        let last = body.lastElementChild;
+        if (last && last.classList.contains('sa-stream')) {
+            last.textContent += content;
+        } else {
+            last = document.createElement('div');
+            last.className = 'sa-stream';
+            last.textContent = content;
+            body.appendChild(last);
+        }
+    } else {
+        const line = document.createElement('div');
+        const icon = evType === 'tool_use' ? '🔧' : evType === 'tool_result' ? '↳' : evType === 'thinking' ? '💭' : '';
+        line.style.cssText = 'margin-top:2px;color:' + (evType === 'tool_use' ? '#c4b5fd' : '#94a3b8');
+        const short = content.length > 300 ? content.slice(0, 300) + '…' : content;
+        line.textContent = `${icon} ${short}`;
+        body.appendChild(line);
+    }
+    body.scrollTop = body.scrollHeight;
+}
+
 // Central renderer for all log entry types (text, tool, tool_result, stream, user_message, etc.)
 // anchor = insert before this node instead of appending — used by loadMoreLogs for prepend
-function addChatEntry(type, content, ts, anchor) {
+// payload = full SSE log object (carries subagent_id for sub-agent nesting)
+function addChatEntry(type, content, ts, anchor, payload) {
     if (HIDE_THINKING && type === 'thinking') return;
+    // Live sub-agent output → nest inside the sub-agent accordion, not the main flow
+    if ((type === 'subagent_stream' || type === 'subagent_event') && payload && payload.subagent_id) {
+        appendSubagentLog(payload.subagent_id, payload.event_type || 'stream', content);
+        return;
+    }
     if (type !== 'user_message' && type !== 'stream') removeWaitingIndicator();
     const chat = $('#chat');
### 3a3757ee6 feat: visible rate-limit banner with countdown timer

diff --git a/app/static/js/app.js b/app/static/js/app.js
index 760752b90..930da486d 100644
--- a/app/static/js/app.js
+++ b/app/static/js/app.js
@@ -2222,10 +2222,11 @@ function addChatEntry(type, content, ts, anchor, payload) {
     }
 
     // Stream events feed the typewriter buffer — RAF loop renders incrementally
     if (type === 'stream') {
         removeWaitingIndicator();
+        if (_rateLimitAgent) _hideRateLimitBanner();  // agent resumed → rate limit cleared
         if (!streamBubble) {
             streamBubble = document.createElement('div');
             streamBubble.className = 'px-3 py-2 rounded-lg text-sm break-words chat-bot markdown-body streaming';
             streamBubble.style.position = 'relative';
             const agentColor = agentColors[selectedAgent];
@@ -2252,13 +2253,21 @@ function addChatEntry(type, content, ts, anchor, payload) {
         streamPending = '';
         return;
     }
 
     if (type === 'status') {
+        const rl = _parseRateLimitStatus(content);
         const badge = document.createElement('div');
-        badge.className = 'text-center text-xs py-1 text-slate-500 italic';
-        badge.textContent = `⚡ ${content}`;
+        if (rl) {
+            // Rate limit: trigger the global banner (live logs only, not history replay)
+            if (!anchor) _showRateLimitBanner(selectedAgent, rl.retry, rl.max, rl.delay);
+            badge.className = 'text-center text-xs py-1 text-amber-400 italic';
+            badge.textContent = `⏳ Rate limit — Anthropic временно ограничил запросы, повтор ${rl.retry}/${rl.max} через ${rl.delay}с (это НЕ твой лимит подписки)`;
+        } else {
+            badge.className = 'text-center text-xs py-1 text-slate-500 italic';
+            badge.textContent = `⚡ ${content}`;
+        }
         addTimestamp(badge, ts);
         const wasAtBottom = chat.scrollHeight - chat.scrollTop - chat.clientHeight < 80;
         _insert(badge);
         if (!anchor && !_insertedBeforeStream && wasAtBottom) chat.scrollTop = chat.scrollHeight;
         return;
@@ -4006,11 +4015,18 @@ function addChatEntry(type, content, ts, anchor, payload) {
             };
             div.style.cursor = 'pointer';
             div.addEventListener('click', (e) => { if (e.target.tagName !== 'A') toggleStandalone(); });
         }
     }
-    else if (type === 'error') { div.textContent = content; }
+    else if (type === 'error') {
+        if (/rate.?limit/i.test(content)) {
+            div.textContent = '⏳ Rate limit — Anthropic временно ограничил запросы (это НЕ лимит твоей подписки). Orchestra автоматически повторит.';
+            div.className = div.className.replace('text-red-400', 'text-amber-400');
+        } else {
+            div.textContent = content;
+        }
+    }
     else {
         div.innerHTML = DOMPurify.sanitize(marked.parse(content));
         const agentColor = agentColors[selectedAgent];
         if (agentColor) div.style.borderLeft = `3px solid ${agentColor}`;
         renderImages(div, content);
@@ -4318,10 +4334,47 @@ async function _pollReconnect() {
 function _onServerError() {
     _rebootFails++;
     if (_rebootFails >= 2) _showRebootOverlay();
 }
 
+// === Rate Limit Banner (Anthropic server-side rate_limit, not subscription) ===
+let _rateLimitTimer = null;
+let _rateLimitAgent = null;
+
+function _showRateLimitBanner(agentName, retryNum, maxRetries, delaySec) {
+    const banner = document.getElementById('rate-limit-banner');
+    if (!banner) return;
+    _rateLimitAgent = agentName;
+    let remaining = delaySec;
+    banner.classList.remove('hidden');
+    banner.classList.add('flex');
+    const render = () => {
+        banner.innerHTML = `⏳ <b>Rate limit (сервер Anthropic)</b> — ${escHtml(agentName)}: повтор ${retryNum}/${maxRetries} через <b class="text-amber-100">${remaining}с</b> <span class="text-amber-400/70">· это НЕ лимит твоей подписки</span>`;
+    };
+    render();
+    if (_rateLimitTimer) clearInterval(_rateLimitTimer);
+    _rateLimitTimer = setInterval(() => {
+        remaining--;
+        if (remaining <= 0) { render(); _hideRateLimitBanner(); return; }
+        render();
+    }, 1000);
+}
+
+function _hideRateLimitBanner() {
+    const banner = document.getElementById('rate-limit-banner');
+    if (_rateLimitTimer) { clearInterval(_rateLimitTimer); _rateLimitTimer = null; }
+    _rateLimitAgent = null;
+    if (banner) { banner.classList.add('hidden'); banner.classList.remove('flex'); banner.innerHTML = ''; }
+}
+
+// Parse "rate limited — retry N/M in Xs" from status log content
+function _parseRateLimitStatus(content) {
+    const m = content.match(/rate limited\s*—\s*retry\s*(\d+)\/(\d+)\s*in\s*(\d+)s/i);
+    if (!m) return null;
+    return { retry: +m[1], max: +m[2], delay: +m[3] };
+}
+
 function _onServerOk() {
     _rebootFails = 0;
 }
 
 function initHeartbeat() {
@@ -4943,12 +4996,13 @@ async function loadProxyList() {
             return;
         }
         for (const p of proxies) {
             const el = document.createElement('div');
             el.className = `flex items-center gap-2 px-2.5 py-2 rounded-lg transition-colors ${p.active ? 'bg-indigo-900/40 border border-indigo-500/50' : 'bg-slate-800/50 border border-slate-700/50 hover:bg-slate-700/50'}`;
-            const status = p.ok === true ? '🟢' : p.ok === false ? '🔴' : '⚪';
-            const statusTitle = p.ok === true ? 'Живой' : p.ok === false ? 'Мёртвый' : 'Не проверен';
+            const isRateLimited = p.ok === false && /429|rate.?limit/i.test(String(p.error || ''));
+            const status = isRateLimited ? '⏳' : p.ok === true ? '🟢' : p.ok === false ? '🔴' : '⚪';
+            const statusTitle = isRateLimited ? 'Rate limit (429) — проверь позже' : p.ok === true ? 'Живой' : p.ok === false ? 'Мёртвый' : 'Не проверен';
             const flag = p.flag || '🏳️';
             const location = p.city ? `${p.city}, ${p.country || ''}` : p.country || '';
             el.innerHTML = `
                 <span class="text-sm" title="${statusTitle}">${status}</span>
                 <div class="flex-1 min-w-0">
### 3ef921eac feat: full sub-agent telemetry — subagents table + transcript endpoints

diff --git a/app/main.py b/app/main.py
index f218a9d81..dd8a3be3d 100644
--- a/app/main.py
+++ b/app/main.py
@@ -68,16 +68,18 @@ from app.routes.tm import router as tm_router
 from app.routes.bg import router as bg_router
 from app.routes.proxy import router as proxy_router
 from app.routes.sessions import router as sessions_router
 from app.routes.system import router as system_router
 from app.routes.tg import router as tg_router
+from app.routes.subagent import router as subagent_router
 app.include_router(tm_router)
 app.include_router(bg_router)
 app.include_router(proxy_router)
 app.include_router(sessions_router)
 app.include_router(system_router)
 app.include_router(tg_router)
+app.include_router(subagent_router)
 
 
 @app.exception_handler(Exception)
 async def global_exception_handler(request: Request, exc: Exception):
     import traceback
### 507a042ad feat: sub-agents telemetry modal with cards + transcripts

diff --git a/app/static/js/app.js b/app/static/js/app.js
index 930da486d..15ef151f1 100644
--- a/app/static/js/app.js
+++ b/app/static/js/app.js
@@ -1233,15 +1233,17 @@ function updateAgentInfo(session) {
         $('#ai-cost').textContent = '-';
         $('#ai-branch').textContent = '-';
         $('#ai-scope').textContent = '-';
         setContextDisplay('-');
         $('#view-prompt-btn').classList.add('hidden');
+        $('#subagents-btn')?.classList.add('hidden');
         $('#compact-btn').classList.add('hidden');
         $('#restart-cli-btn').classList.add('hidden');
         return;
     }
     $('#view-prompt-btn').classList.remove('hidden');
+    $('#subagents-btn')?.classList.remove('hidden');
     $('#compact-btn').classList.remove('hidden');
     $('#restart-cli-btn').classList.remove('hidden');
     const isRunning = session.status === 'running';
     $('#compact-btn').disabled = isRunning;
     $('#compact-btn').title = isRunning ? 'Wait for idle' : 'Compact context';
@@ -1407,10 +1409,11 @@ function createAgentItem(s) {
     item.className = `agent-item flex items-center gap-3 px-3 py-2 rounded-lg cursor-pointer transition-colors ${
         isSelected ? 'bg-indigo-900/30 border border-indigo-500/30' :
         isDead ? 'opacity-50 hover:opacity-70' : 'hover:bg-slate-800/50'
     }`;
     item.addEventListener('click', () => selectAgent(s.name));
+    if (s.id) item.dataset.sessionId = s.id;
 
     if (s.color) item.style.borderLeft = `3px solid ${s.color}`;
 
     const icon = document.createElement('span');
     const roleKey = s.role || (s.is_orchestrator ? 'orchestrator' : 'worker');
@@ -4670,10 +4673,205 @@ function _analyticsRateBar(label, data, windowMs) {
         <div class="w-full h-2 bg-slate-800 rounded-full overflow-hidden mb-2"><div class="h-full rounded-full transition-all" style="width:${Math.min(pct, 100)}%;background:${barColor}"></div></div>
         <div class="flex justify-between text-[10px] text-slate-500"><span>Reset: ${cd || '—'}</span>${rpNum != null ? `<span>Window: ${rpNum}%</span>` : ''}${pace ? `<span>${pace}</span>` : ''}</div>
     </div>`;
 }
 
+// === Sub-agents Modal (post-hoc telemetry + transcripts) ===
+function _fmtTokens(n) {
+    n = n || 0;
+    if (n >= 1e6) return (n / 1e6).toFixed(1) + 'M';
+    if (n >= 1000) return (n / 1000).toFixed(1) + 'K';
+    return String(n);
+}
+function _fmtDuration(ms) {
+    ms = ms || 0;
+    if (ms < 1000) return ms + 'ms';
+    const s = ms / 1000;
+    if (s < 60) return s.toFixed(1) + 's';
+    const m = Math.floor(s / 60);
+    const rem = Math.round(s % 60);
+    if (m < 60) return `${m}m ${rem}s`;
+    const h = Math.floor(m / 60);
+    return `${h}h ${m % 60}m`;
+}
+
+function openSubagentsModal() {
+    if (!selectedAgent || !currentScope) return;
+    const modal = document.getElementById('subagents-modal');
+    if (!modal) return;
+    modal.classList.remove('hidden');
+    modal.classList.add('flex');
+    document.getElementById('subagents-modal-agent').textContent = selectedAgent;
+    document.addEventListener('keydown', _subagentsEscHandler);
+    _loadSubagents();
+}
+function closeSubagentsModal() {
+    const modal = document.getElementById('subagents-modal');
+    if (!modal) return;
+    modal.classList.add('hidden');
+    modal.classList.remove('flex');
+    document.removeEventListener('keydown', _subagentsEscHandler);
+}
+function _subagentsEscHandler(e) { if (e.key === 'Escape') closeSubagentsModal(); }
+
+async function _loadSubagents() {
+    const body = document.getElementById('subagents-body');
+    if (!body) return;
+    body.innerHTML = '<div class="text-center text-slate-500 py-8">Loading...</div>';
+    try {
+        const sid = manager_session_id_for(selectedAgent);
+        // Telemetry + transcript agent_ids in parallel. agent_id (SDK file id) != task_id,
+        // so map telemetry cards → transcript ids by index (both time-ordered).
+        const [data, tData] = await Promise.all([
+            api(`/api/subagents/${encodeURIComponent(sid)}`),
+            api(`/api/subagent-transcripts/${encodeURIComponent(sid)}`).catch(() => ({ agent_ids: [] })),
+        ]);
+        const subs = (data && data.subagents) || [];
+        const agentIds = (tData && tData.agent_ids) || [];
+        if (!subs.length) {
+            body.innerHTML = '<div class="text-center text-slate-500 py-8 italic">Этот агент ещё не запускал субагентов.</div>';
+            return;
+        }
+        body.innerHTML = subs.map((s, i) => _renderSubagentCard(s, i, agentIds[i] || '')).join('');
+        // Wire transcript toggles
+        body.querySelectorAll('.sa-transcript-btn').forEach(btn => {
+            btn.addEventListener('click', () => _toggleTranscript(btn, sid));
+        });
+        body.querySelectorAll('.sa-summary-toggle').forEach(btn => {
+            btn.addEventListener('click', () => {
+                const full = btn.nextElementSibling;
+                if (full) full.classList.toggle('hidden');
+                btn.textContent = full && !full.classList.contains('hidden') ? '▼ Свернуть summary' : '▶ Показать summary';
+            });
+        });
+    } catch (e) {
+        body.innerHTML = `<div class="text-center text-red-400 py-8">Ошибка: ${_escHtml(e.message)}</div>`;
+    }
+}
+
+// session_id lookup — orchData/agent items carry the DB session id
+function manager_session_id_for(name) {
+    const el = [...document.querySelectorAll('.agent-item')].find(el => {
+        const nameEl = el.querySelector('.text-xs.font-medium');
+        return nameEl && nameEl.textContent === name;
+    });
+    return (el && el.dataset.sessionId) || name;
+}
+
+function _renderSubagentCard(s, idx, transcriptId) {
+    const statusMap = {
+        completed: ['🟢', '#22c55e', 'completed'],
+        failed: ['🔴', '#ef4444', 'failed'],
+        running: ['⏳', '#eab308', 'running'],
+    };
+    const [icon, color, label] = statusMap[s.status] || ['⚪', '#64748b', s.status || '?'];
+    const desc = _escHtml(s.description || 'Sub-agent');
+    const taskType = s.task_type ? `<span class="px-1.5 py-0.5 rounded text-[9px] font-semibold uppercase" style="background:rgba(167,139,250,0.15);color:#c4b5fd">${_escHtml(s.task_type)}</span>` : '';
+    const metrics = [
+        `🔢 ${_fmtTokens(s.total_tokens)}`,
+        `🔧 ${s.tool_uses || 0}`,
+        `⏱️ ${_fmtDuration(s.duration_ms)}`,
+    ];
+    if (s.last_tool_name) metrics.push(`⚙️ ${_escHtml(s.last_tool_name)}`);
+
+    let summaryBlock = '';
+    if (s.summary) {
+        summaryBlock = `<div class="mt-2">
+            <button class="sa-summary-toggle text-[10px] text-indigo-300 hover:text-indigo-200">▶ Показать summary</button>
+            <div class="hidden mt-1 p-2 bg-slate-900/60 rounded-lg text-[11px] text-slate-300 whitespace-pre-wrap break-words">${_escHtml(s.summary)}</div>
+        </div>`;
+    }
+    let fileBlock = '';
+    if (s.output_file) {
+        fileBlock = `<div class="mt-1 text-[10px] text-slate-500">📄 <span class="text-emerald-400 break-all">${_escHtml(s.output_file)}</span></div>`;
### b9acb11fc docs: cleanup research — dead-code list + super-full-cycle roles plan

diff --git a/app/static/js/app.js b/app/static/js/app.js
index 15ef151f1..bdbd96a6f 100644
--- a/app/static/js/app.js
+++ b/app/static/js/app.js
@@ -1935,11 +1935,11 @@ function buildCompactToolLine(type, content, ts) {
         const short = toolShortName(rawName);
 
         let preview = body;
         try {
             const parsed = JSON.parse(body);
-            if (rawName === 'mcp__orchestra__spawn_worker') preview = `🚀 ${parsed.name || '?'} (${({'claude-opus-4-8[1m]':'Opus 4.8 1M','claude-opus-4-7[1m]':'Opus 4.7 1M','claude-opus-4-6[1m]':'Opus 1M','claude-opus-4-6':'Opus','claude-sonnet-4-6':'Sonnet','claude-haiku-4-5':'Haiku','claude-haiku-4-6':'Haiku'})[parsed.model || 'claude-sonnet-4-6'] || parsed.model || 'Sonnet'})`;
+            if (rawName === 'mcp__orchestra__spawn_worker') preview = `🚀 ${parsed.name || '?'} (${({'claude-opus-4-8[1m]':'Opus 4.8 1M','claude-opus-4-6[1m]':'Opus 1M','claude-opus-4-6':'Opus','claude-sonnet-4-6':'Sonnet','claude-haiku-4-5':'Haiku'})[parsed.model || 'claude-sonnet-4-6'] || parsed.model || 'Sonnet'})`;
             else if (rawName === 'mcp__websearch__search' || rawName === 'mcp__websearch__search_web' || rawName === 'WebSearch') preview = `🌐 "${parsed.query || ''}"`;
             else if (rawName === 'ToolSearch') preview = `🔍 ${parsed.query || ''}`;
             else if (rawName === 'mcp__orchestra__report_bug') preview = `🐛 ${parsed.title || '?'}`;
             else if (rawName === 'mcp__orchestra__send_file') preview = `📎 ${(parsed.path || '').split('/').pop() || '?'}`;
             else if (rawName === 'mcp__orchestra__kill_worker') preview = `💀 Kill: ${parsed.name || '?'}`;
@@ -2495,25 +2495,21 @@ function addChatEntry(type, content, ts, anchor, payload) {
                 header.textContent = `🚀 Spawning ${workerName}`;
                 header.style.color = '#a78bfa';
 
                 const MODEL_SHORT = {
                     'claude-opus-4-8[1m]': 'Opus 4.8 1M',
-                    'claude-opus-4-7[1m]': 'Opus 4.7 1M',
                     'claude-opus-4-6[1m]': 'Opus 4.6 1M',
                     'claude-opus-4-6': 'Opus 4.6',
                     'claude-sonnet-4-6': 'Sonnet 4.6',
                     'claude-haiku-4-5': 'Haiku 4.5',
-                    'claude-haiku-4-6': 'Haiku 4.6',
                 };
                 const MODEL_COLOR = {
                     'claude-opus-4-8[1m]': '#c084fc',
-                    'claude-opus-4-7[1m]': '#a78bfa',
                     'claude-opus-4-6[1m]': '#a78bfa',
                     'claude-opus-4-6': '#a78bfa',
                     'claude-sonnet-4-6': '#38bdf8',
                     'claude-haiku-4-5': '#4ade80',
-                    'claude-haiku-4-6': '#4ade80',
                 };
                 if (model) {
                     const badge = document.createElement('span');
                     badge.textContent = MODEL_SHORT[model] || model;
                     badge.style.cssText = `font-size:9px;padding:1px 6px;border-radius:9999px;border:1px solid;color:${MODEL_COLOR[model] || '#94a3b8'};border-color:${MODEL_COLOR[model] || '#94a3b8'};opacity:0.8;vertical-align:middle;margin-left:6px`;
@@ -3350,11 +3346,11 @@ function addChatEntry(type, content, ts, anchor, payload) {
                         }
                         lastTool.appendChild(container);
                     }
                 } else if (tn === 'mcp__orchestra__get_worker_info') {
                     const stColor = {'running':'#22c55e','idle':'#eab308','error':'#ef4444','stopped':'#6b7280','starting':'#f97316'}[parsed.status] || '#94a3b8';
-                    const MODEL_SHORT = {'claude-opus-4-8[1m]':'Opus 4.8 1M','claude-opus-4-7[1m]':'Opus 4.7 1M','claude-opus-4-6[1m]':'Opus 4.6 1M','claude-opus-4-6':'Opus 4.6','claude-sonnet-4-6':'Sonnet 4.6','claude-haiku-4-5':'Haiku 4.5','gpt-5.5':'GPT 5.5'};
+                    const MODEL_SHORT = {'claude-opus-4-8[1m]':'Opus 4.8 1M','claude-opus-4-6[1m]':'Opus 4.6 1M','claude-opus-4-6':'Opus 4.6','claude-sonnet-4-6':'Sonnet 4.6','claude-haiku-4-5':'Haiku 4.5','gpt-5.5':'GPT 5.5'};
                     const modelShort = MODEL_SHORT[parsed.model] || parsed.model || '?';
                     if (hdr) {
                         hdr.innerHTML = `🤖 <b>${DOMPurify.sanitize(parsed.name || '?')}</b> <span style="font-size:10px;color:#64748b">(${DOMPurify.sanitize(modelShort)})</span> — <span style="color:${stColor}">${parsed.status || '?'}</span>`;
                     }
                     const grid = document.createElement('div');
### 3478d558f feat: super-full-cycle role (research+experiment + ticketing), remove researcher/experimenter

diff --git a/CLAUDE.md b/CLAUDE.md
index 83aa4998e..65cbe9c89 100644
--- a/CLAUDE.md
+++ b/CLAUDE.md
@@ -162,13 +162,13 @@ Every feature should minimize agent overhead: fewer tool calls, less context was
 ### Major refactoring
 - **P0-P4 full codebase refactor** (Fable 5 full-cycle, $33): session.py split → CostTracker/TurnManager/HibernateManager; main.py 1574→91 lines; 3 circular deps cut; 34 isinstance killed; 487 tests green
 - **tg_bridge split** — refactor-tg worker (Opus 4.8) in progress, research+plan done, awaiting impl
 
 ### New roles
-- `experimenter` — hypothesis → experiment → measure → conclude. Opus 4.8
-- `researcher` — search → verify → synthesize. Web research with counter-evidence. Opus 4.8
-- Both in `pipelines/default/pipeline.yaml` + `prompts/roles/`
+- ~~`experimenter`, `researcher`~~ — **MERGED into `full-cycle` Phase 1** (2026-07-01). Их суть
+  (hypothesis→measure + search→verify→counter-evidence) = research+experiment фаза super-full-cycle.
+  Отдельные роли УДАЛЕНЫ. «Только research» = оркестратор стопит после Phase 1
 
 ### Key features
 - **4-level cost**: turn/ctx/session/total. ctx persisted in DB (survives reboot), session = in-memory only
 - **Worker persistent memory** (#81): `docs/workers/{name}.md` auto-injects into prompt on spawn/resume
 - **Dynamic model list**: `available_models_block()` from models.py → orchestrator prompts
@@ -243,10 +243,11 @@ Every feature should minimize agent overhead: fewer tool calls, less context was
 
 ### Process rules
 - **Don't auto-approve implementation** — user asked about self-learning, I approved impl without permission. Rule: ASK before approving large implementations
 - **Orchestrators delegate content** — sales playbook, user guides = specialist workers, not orchestrator
 - **Dynamic Workflows blocked** — Claude Code's built-in Workflow tool blocked for all agents (wastes tokens, MCP tools don't propagate)
+- **«Мёртвый код» → грепни РЕАЛЬНЫЕ чтения перед удалением** — разведка сказала «app/prompts мёртвая» (грепнули строку `app/prompts`, нашли только комменты). Но `prompting.py._PROMPTS_DIR` читал её через 12 функций — это был живой fallback + дашборд-визуализация. Правило: перед удалением папки/модуля грепни кто РЕАЛЬНО импортит/читает (не строковые совпадения), проверь fallback-пути. Перепроверка спасла дашборд от поломки
 
 ## BUGS.md — баг-репорты от агентов
 - Агенты (оркестраторы и воркеры) могут вызывать `report_bug(title, description)` MCP tool
 - Баги пишутся в `BUGS.md` в корне проекта
 - **При старте сессии** — чекни `BUGS.md`, если есть новые баги — разбери или упомяни