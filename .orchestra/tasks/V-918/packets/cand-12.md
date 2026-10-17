# Candidate cand-12

## ORIGIN commit fc175c0703 (2026-06-01): #43, #44: #43: SSH tunnel proxies — systemd services, proxy-setup docs
(diff of code only, excluding .orchestra/ and *.md; capped 1200 lines)

diff --git a/app/ssh_tunnel.py b/app/ssh_tunnel.py
index 62a3cf35f..ab7461124 100644
--- a/app/ssh_tunnel.py
+++ b/app/ssh_tunnel.py
@@ -1,93 +1,144 @@
+"""SSH tunnel manager — multiple tunnels with auto-restart.
+
+Config via SSH_TUNNELS env var (pipe-separated fields, comma-separated entries):
+  SSH_TUNNELS=name|local_port|host|remote_port|key_path,...
+
+Example:
+  SSH_TUNNELS=ezhik|12340|194.87.250.243|18080|/path/to/key,timeweb|12341|147.45.101.84|3128|
+"""
+
 import asyncio
 import logging
 import os
+from dataclasses import dataclass, field
 
 logger = logging.getLogger("ssh-tunnel")
 
-_proc: asyncio.subprocess.Process | None = None
-_running = False
-_host = ""
-_local_port = 0
-_remote_port = 0
-_task: asyncio.Task | None = None
+RECONNECT_DELAY = 5
+DEFAULT_KEY = os.path.expanduser("~/.ssh/id_ed25519")
 
 
-async def start_tunnel():
-    global _host, _local_port, _remote_port, _task
+@dataclass
+class Tunnel:
+    name: str
+    local_port: int
+    host: str
+    remote_port: int
+    key_path: str
+    proc: asyncio.subprocess.Process | None = field(default=None, repr=False)
+    task: asyncio.Task | None = field(default=None, repr=False)
+    running: bool = False
 
-    _host = os.getenv("SSH_TUNNEL_HOST", "")
-    key = os.getenv("SSH_TUNNEL_KEY", "")
-    _local_port = int(os.getenv("SSH_TUNNEL_LOCAL_PORT", "12338"))
-    _remote_port = int(os.getenv("SSH_TUNNEL_REMOTE_PORT", "18080"))
 
-    if not _host:
-        logger.info("SSH tunnel disabled (no SSH_TUNNEL_HOST)")
-        return
-    if not key:
-        logger.error("SSH_TUNNEL_HOST set but SSH_TUNNEL_KEY missing")
-        return
+_tunnels: list[Tunnel] = []
+
+
+def _parse_tunnels() -> list[Tunnel]:
+    raw = os.getenv("SSH_TUNNELS", "")
+    if not raw:
+        return _parse_legacy()
+    tunnels = []
+    for entry in raw.split(","):
+        entry = entry.strip()
+        if not entry:
+            continue
+        parts = entry.split("|")
+        if len(parts) < 4:
+            logger.warning(f"SSH tunnel config invalid (need 4+ fields): {entry}")
+            continue
+        name = parts[0].strip()
+        local_port = int(parts[1].strip())
+        host = parts[2].strip()
+        remote_port = int(parts[3].strip())
+        key = parts[4].strip() if len(parts) > 4 and parts[4].strip() else DEFAULT_KEY
+        tunnels.append(Tunnel(name=name, local_port=local_port, host=host,
+                              remote_port=remote_port, key_path=key))
+    return tunnels
+
 
-    _task = asyncio.create_task(_tunnel_loop(_host, key, _local_port, _remote_port))
-    logger.info(f"SSH tunnel starting: localhost:{_local_port} -> {_host}:{_remote_port}")
+def _parse_legacy() -> list[Tunnel]:
+    host = os.getenv("SSH_TUNNEL_HOST", "")
+    if not host:
+        return []
+    key = os.getenv("SSH_TUNNEL_KEY", DEFAULT_KEY)
+    local = int(os.getenv("SSH_TUNNEL_LOCAL_PORT", "12338"))
+    remote = int(os.getenv("SSH_TUNNEL_REMOTE_PORT", "18080"))
+    return [Tunnel(name="legacy", local_port=local, host=host,
+                   remote_port=remote, key_path=key)]
 
 
-async def _tunnel_loop(host: str, key: str, local_port: int, remote_port: int):
-    global _proc, _running
+async def _tunnel_loop(t: Tunnel):
     while True:
         try:
-            _proc = await asyncio.create_subprocess_exec(
+            t.proc = await asyncio.create_subprocess_exec(
                 "ssh", "-N",
-                "-L", f"{local_port}:127.0.0.1:{remote_port}",
-                "-i", key,
+                "-L", f"{t.local_port}:127.0.0.1:{t.remote_port}",
+                "-i", t.key_path,
                 "-o", "StrictHostKeyChecking=no",
                 "-o", "ServerAliveInterval=30",
                 "-o", "ServerAliveCountMax=3",
                 "-o", "ExitOnForwardFailure=yes",
-                f"root@{host}",
+                f"root@{t.host}",
                 stdout=asyncio.subprocess.DEVNULL,
                 stderr=asyncio.subprocess.PIPE,
             )
-            _running = True
-            logger.info(f"SSH tunnel connected (pid={_proc.pid})")
-            _, stderr = await _proc.communicate()
-            _running = False
-            if stderr:
-                logger.warning(f"SSH tunnel exited: {stderr.decode().strip()}")
-            else:
-                logger.warning("SSH tunnel exited")
+            t.running = True
+            logger.info(f"tunnel {t.name} started pid={t.proc.pid} "
+                        f"(:{t.local_port} → {t.host}:{t.remote_port})")
+            _, stderr = await t.proc.communicate()
+            t.running = False
+            msg = stderr.decode().strip() if stderr else ""
+            logger.warning(f"tunnel {t.name} died pid={t.proc.pid}"
+                           f"{': ' + msg if msg else ''}")
         except asyncio.CancelledError:
-            if _proc and _proc.returncode is None:
-                _proc.terminate()
-            _running = False
+            if t.proc and t.proc.returncode is None:
+                t.proc.terminate()
+            t.running = False
             return
         except Exception as e:
-            _running = False
-            logger.error(f"SSH tunnel error: {e}")
-        logger.info("SSH tunnel reconnecting in 5s...")
-        await asyncio.sleep(5)
+            t.running = False
+            logger.error(f"tunnel {t.name} error: {e}")
+        logger.info(f"tunnel {t.name} reconnecting in {RECONNECT_DELAY}s...")
+        await asyncio.sleep(RECONNECT_DELAY)
+
+
+async def start_tunnel():
+    global _tunnels
+    _tunnels = _parse_tunnels()
+    if not _tunnels:
+        logger.info("SSH tunnels: none configured")
+        return
+    for t in _tunnels:
+        t.task = asyncio.create_task(_tunnel_loop(t))
+    names = ", ".join(f"{t.name}(:{t.local_port})" for t in _tunnels)
+    logger.info(f"SSH tunnels starting: {names}")
 
 
 async def stop_tunnel():
-    global _proc, _running, _task
-    if _task:
-        _task.cancel()
-        try:
-            await _task
-        except asyncio.CancelledError:
-            pass
-        _task = None
-    if _proc and _proc.returncode is None:
-        _proc.terminate()
-    _proc = None
-    _running = False
-    logger.info("SSH tunnel stopped")
-
-
-def tunnel_status() -> dict:
-    return {
-        "running": _running,
-        "host": _host,
-        "local_port": _local_port,
-        "remote_port": _remote_port,
-        "pid": _proc.pid if _proc and _proc.returncode is None else None,
-    }
+    for t in _tunnels:
+        if t.task:
+            t.task.cancel()
+            try:
+                await t.task
+            except asyncio.CancelledError:
+                pass
+            t.task = None
+        if t.proc and t.proc.returncode is None:
+            t.proc.terminate()
+        t.proc = None
+        t.running = False
+    logger.info(f"SSH tunnels stopped ({len(_tunnels)})")
+
+
+def tunnel_status() -> list[dict]:
+    return [
+        {
+            "name": t.name,
+            "running": t.running,
+            "host": t.host,
+            "local_port": t.local_port,
+            "remote_port": t.remote_port,
+            "pid": t.proc.pid if t.proc and t.proc.returncode is None else None,
+        }
+        for t in _tunnels
+    ]


## LATER FIX 18d8061390 (29.7 days later): #4: #proxy-fix: force stable id='direct' for direct proxy
lines of origin it changed/deleted: 2
(code only, capped 400 lines)

#4: #proxy-fix: force stable id='direct' for direct proxy

Squashed commits:
- #proxy-fix: force stable id='direct' for direct proxy
- #proxy-fix #4: backoff + health-gate против zombie-туннелей
- #proxy-fix: .env = единственный источник истины прокси (вырезать DB/hot-switch)
- #proxy-fix: CHANGELOG v2.24.0 + report
- take main check-proxies.sh (priority-aware retry)


diff --git a/app/main.py b/app/main.py
index 73346246f..f218a9d81 100644
--- a/app/main.py
+++ b/app/main.py
@@ -16,18 +16,16 @@ from app.deps import manager
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
@@ -49,20 +47,18 @@ async def lifespan(app: FastAPI):
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
diff --git a/app/proxy_manager.py b/app/proxy_manager.py
index c6848f697..f4aad0e0f 100644
--- a/app/proxy_manager.py
+++ b/app/proxy_manager.py
@@ -1,24 +1,25 @@
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
@@ -52,66 +53,38 @@ def _parse_proxy_list() -> list[ProxyEntry]:
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
@@ -119,85 +92,37 @@ class ProxyManager:
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
@@ -25,32 +25,12 @@ async def proxy_list():
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
@@ -5,25 +5,48 @@ Config via SSH_TUNNELS env var (pipe-separated fields, comma-separated entries):
 
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
@@ -88,18 +111,27 @@ def _parse_legacy() -> list[Tunnel]:
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
@@ -110,30 +142,36 @@ async def _tunnel_loop(t: Tunnel):
             t.running = True
             logger.info(f"tunnel {t.name} started pid={t.proc.pid} "
                         f"(:{t.local_port} → {t.host}:{t.remote_port})")
             _, stderr = await t.proc.communicate()
             t.running = False
             msg = stderr.decode().strip() if stderr else ""
             logger.warning(f"tunnel {t.name} died pid={t.proc.pid}"
                            f"{': ' + msg if msg else ''}")
+            # Reset backoff only if the tunnel stayed up long enough to be healthy