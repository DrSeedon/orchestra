# Context for item-01

## Diff reviewed (-U20, capped at 1500 lines)

diff --git a/app/deps.py b/app/deps.py
index fe24a2622..a54127d44 100644
--- a/app/deps.py
+++ b/app/deps.py
@@ -1,8 +1,30 @@
 """Shared dependencies for routers — avoids importing from main."""
 
+from pathlib import Path
+
 from fastapi.templating import Jinja2Templates
 
 from app.manager import SessionManager
 
 manager = SessionManager()
 templates = Jinja2Templates(directory="app/templates")
+
+_STATIC_DIR = Path(__file__).parent / "static"
+
+
+def static_url(path: str) -> str:
+    """Ссылка на статику с версией в query — только так браузер узнаёт о правке.
+
+    Версия = mtime файла: изменился файл → изменился URL → браузер идёт за новым
+    и без Ctrl-Shift-R. Не изменился → берёт из кеша вообще без запроса (immutable
+    в main.py). Плата за mtime вместо хеша содержимого: git checkout, вернувший тот
+    же байт-в-байт файл, всё равно обновит время и стоит одной лишней загрузки.
+    Файла нет → отдаём путь как есть: видимый 404 честнее тихой подмены.
+    """
+    try:
+        return f"/static/{path}?v={(_STATIC_DIR / path).stat().st_mtime_ns:x}"
+    except OSError:
+        return f"/static/{path}"
+
+
+templates.env.globals["static_url"] = static_url
diff --git a/app/main.py b/app/main.py
index 411052c5b..e3f739e5b 100644
--- a/app/main.py
+++ b/app/main.py
@@ -1,26 +1,27 @@
 """Orchestra — AI Agent Orchestrator. App factory: lifespan, middleware, routers."""
 
 import asyncio
 import logging
 import os
 from contextlib import asynccontextmanager
+from urllib.parse import parse_qs
 
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
     from app.session import validate_auto_compact_window_config
     validate_auto_compact_window_config()
     init_db()
@@ -66,42 +67,63 @@ async def lifespan(app: FastAPI):
     from app.routes.system import _usage_snapshot_loop
     snapshot_task = asyncio.create_task(_usage_snapshot_loop())
     from app import rag_service
     if rag_service.is_enabled():
         rag_service.initialize()
     from app.merge_operations import restore_merge_operations
     await restore_merge_operations()
     yield
     snapshot_task.cancel()
     from app import rag_service as _rs
     from app.merge_operations import shutdown_merge_operations
     await shutdown_merge_operations()
     _rs.shutdown()
     if _tunnel_started:
         await stop_tunnel()
     await stop_bridge()
     await bg_manager.shutdown()
     await manager.shutdown_all()
 
 
+class VersionedStatic(StaticFiles):
+    """Есть ?v= в URL → кешируем навсегда, нет → обязательная ревалидация.
+
+    Версию проставляет static_url() из app/deps.py. Ошибиться здесь можно только
+    в безопасную сторону: забыли версию — юзер платит лишним 304, а не сидит
+    неделю со старым кодом, как было без Cache-Control вовсе (задача #9).
+    """
+
+    async def get_response(self, path, scope):
+        response = await super().get_response(path, scope)
+        # Только 200: закешировать навечно 404 по версионному URL — значит спрятать
+        # файл от юзера до конца жизни профиля браузера
+        versioned = b"v" in parse_qs(scope.get("query_string", b""))
+        response.headers["Cache-Control"] = (
+            "public, max-age=31536000, immutable"
+            if versioned and response.status_code == 200
+            else "no-cache"
+        )
+        return response
+
+
 app = FastAPI(title="Orchestra", lifespan=lifespan)
-app.mount("/static", StaticFiles(directory="app/static"), name="static")
+app.mount("/static", VersionedStatic(directory="app/static"), name="static")
 
 from app.routes.tm import router as tm_router
 from app.routes.bg import router as bg_router
 from app.routes.proxy import router as proxy_router
 from app.routes.sessions import router as sessions_router
 from app.routes.system import router as system_router
 from app.routes.tg import router as tg_router
 from app.routes.subagent import router as subagent_router
 from app.routes.memory import router as memory_router
 from app.routes.merge_operations import router as merge_operations_router
 app.include_router(tm_router)
 app.include_router(bg_router)
 app.include_router(proxy_router)
 app.include_router(sessions_router)
 app.include_router(system_router)
 app.include_router(tg_router)
 app.include_router(subagent_router)
 app.include_router(memory_router)
 app.include_router(merge_operations_router)
 
diff --git a/app/routes/system.py b/app/routes/system.py
index 84037802c..38349760a 100644
--- a/app/routes/system.py
+++ b/app/routes/system.py
@@ -53,48 +53,51 @@ class TestLockRequest(BaseModel):
     holder: str
     reason: str = ""
 
 
 class ChangeScopeRequest(BaseModel):
     old_scope: str
     new_scope: str
     new_cwd: Optional[str] = None
 
 
 # ── Pages / auth ──
 
 @router.get("/", response_class=HTMLResponse)
 async def dashboard(request: Request):
     return templates.TemplateResponse(request, "dashboard.html", {
         "currency_symbol": os.getenv("CURRENCY_SYMBOL", "₽"),
         "hide_thinking": is_auth_enabled(),
         "is_auth_enabled": is_auth_enabled(),
         "is_owner_mode": is_owner_mode(),
         "client_name": os.getenv("CLIENT_NAME", "Client"),
-    })
+    # Кешировать HTML нельзя: в нём лежат версии статики, устареет он — версии
+    # не обновятся, и весь механизм из #9 перестанет работать
+    }, headers={"Cache-Control": "no-cache"})
 
 
 @router.get("/login", response_class=HTMLResponse)
 async def login_page(request: Request):
     if not is_auth_enabled():
         return RedirectResponse("/", status_code=302)
-    return templates.TemplateResponse(request, "login.html", {"error": ""})
+    return templates.TemplateResponse(request, "login.html", {"error": ""},
+                                      headers={"Cache-Control": "no-cache"})
 
 
 @router.post("/login")
 async def login_submit(request: Request, username: str = Form(""), password: str = Form("")):
     from app.auth import check_credentials, create_session
     if not is_auth_enabled():
         return RedirectResponse("/", status_code=302)
     if check_credentials(username, password):
         token = create_session(username)
         response = RedirectResponse("/", status_code=302)
         secure = request.url.scheme == "https" or os.environ.get("COOKIE_SECURE") == "1"
         response.set_cookie("session", token, httponly=True, samesite="lax", max_age=2592000, secure=secure)
         return response
     return templates.TemplateResponse(request, "login.html", {"error": "Invalid credentials"})
 
 
 @router.post("/logout")
 async def logout(request: Request):
     response = RedirectResponse("/login", status_code=302)
     response.delete_cookie("session")
diff --git a/app/templates/dashboard.html b/app/templates/dashboard.html
index aab5f8e62..8ee3595fb 100644
--- a/app/templates/dashboard.html
+++ b/app/templates/dashboard.html
@@ -1,51 +1,51 @@
 <!DOCTYPE html>
 <html lang="en">
 <head>
     <meta charset="UTF-8">
-    <link rel="icon" href="/static/favicon.svg" type="image/svg+xml">
+    <link rel="icon" href="{{ static_url('favicon.svg') }}" type="image/svg+xml">
     <title>🎼 Orchestra</title>
-    <script src="/static/css/vendor/tailwind.js"></script>
+    <script src="{{ static_url('css/vendor/tailwind.js') }}"></script>
     <script>
       // Design tokens via Tailwind config (CDN). Lift faint slate shades to meet WCAG AA
       // on the #0a0e17 bg, and route sans utilities to Inter (hybrid typography).
       tailwind.config = {
         theme: { extend: {
           fontFamily: {
             sans: ['Inter', 'system-ui', '-apple-system', 'sans-serif'],
             mono: ['JetBrains Mono', 'Fira Code', 'ui-monospace', 'monospace'],
           },
           colors: { slate: {
             400: '#a6b3c6',  // was #94a3b8 — meta/secondary
             500: '#8595ab',  // was #64748b — faint labels (AA on bg)
             600: '#6b7c93',  // was #475569 — faintest still-readable
           } },
         } },
       };
     </script>
-    <script src="/static/css/vendor/marked.min.js"></script>
-    <script src="/static/css/vendor/purify.min.js"></script>
-    <script src="/static/css/vendor/diff_match_patch.js"></script>
+    <script src="{{ static_url('css/vendor/marked.min.js') }}"></script>
+    <script src="{{ static_url('css/vendor/purify.min.js') }}"></script>
+    <script src="{{ static_url('css/vendor/diff_match_patch.js') }}"></script>
     <script src="https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js"></script>
-    <script src="/static/css/vendor/highlight.min.js"></script>
-    <link rel="stylesheet" href="/static/css/vendor/highlight-github-dark.min.css">
-    <link rel="stylesheet" href="/static/css/style.css">
+    <script src="{{ static_url('css/vendor/highlight.min.js') }}"></script>
+    <link rel="stylesheet" href="{{ static_url('css/vendor/highlight-github-dark.min.css') }}">
+    <link rel="stylesheet" href="{{ static_url('css/style.css') }}">
 </head>
 <body class="h-screen overflow-hidden flex flex-col" data-currency="{{ currency_symbol }}" data-hide-thinking="{{ 'true' if hide_thinking else 'false' }}" data-auth-enabled="{{ 'true' if is_auth_enabled else 'false' }}" data-client-name="{{ client_name }}">
     <div id="rate-limit-banner" class="hidden items-center justify-center gap-2 px-4 py-2 bg-amber-500/15 border-b border-amber-500/40 text-amber-200 text-xs"></div>
     <div id="bug-report-banner" role="status" class="hidden fixed top-12 right-3 z-50 max-w-[min(28rem,calc(100vw-1.5rem))] items-center gap-2 rounded-lg border border-amber-500/40 bg-slate-950/95 px-3 py-2 text-xs text-amber-100 shadow-xl"></div>
     <div id="usage-bar"></div>
     <header class="flex items-center justify-between px-5 py-2 border-b border-slate-800/50">
         <div class="flex items-center gap-2 flex-1 min-w-0">
             <h1 class="text-lg font-bold tracking-tight shrink-0">🎼</h1>
             <div id="orch-tabs" class="flex items-center gap-1.5 overflow-x-auto no-scrollbar"></div>
             <select id="orch-picker" class="hidden"></select>
             <button id="new-orch-btn" class="px-2.5 py-1.5 bg-slate-800/50 hover:bg-slate-700 border border-dashed border-slate-700 rounded-full text-xs transition-colors shrink-0" title="New orchestrator">+</button>
             <button id="hidden-tabs-btn" class="px-2 py-1.5 hover:bg-slate-700 rounded-full text-xs transition-colors text-slate-500 hover:text-slate-300 shrink-0 hidden" title="Show hidden tabs">👁</button>
         </div>
         <div class="flex items-center gap-3 text-xs text-slate-600 shrink-0">
             <span id="stats-line"></span>
             {% if is_auth_enabled %}<span id="proxy-status" class="text-xs cursor-default" title="Proxy status">⏳</span>{% endif %}
             {% if is_owner_mode %}
             <div class="relative">
                 <button id="proxy-btn" class="px-2 py-1 bg-slate-800 hover:bg-slate-700 border border-slate-700 rounded-lg transition-colors text-slate-400 flex items-center gap-1" title="Proxy settings">
                     <span id="proxy-flag">🌐</span>
@@ -288,27 +288,27 @@
                 <div id="agent-list" class="p-2 space-y-1"></div>
             </div>
         </div>
     </div>
 
     <!-- File Preview Modal -->
     <div id="file-preview-modal" class="fixed inset-0 z-50 items-center justify-center hidden" style="pointer-events:none">
         <div class="glass glow rounded-xl flex flex-col w-[700px] max-w-[90vw] max-h-[80vh]" style="pointer-events:auto;box-shadow:0 8px 32px rgba(0,0,0,0.6)">
             <div class="flex items-center justify-between px-4 py-3 border-b border-slate-800/50 shrink-0">
                 <span id="file-preview-path" class="text-xs font-mono text-slate-400 truncate max-w-[70%]"></span>
                 <div class="flex items-center gap-2">
                     <a id="file-preview-download" href="#" download class="hidden text-xs px-2 py-1 rounded bg-emerald-600/30 text-emerald-300 hover:bg-emerald-600/50 transition-colors" title="Download file">⬇ Download</a>
                     <a id="file-preview-open" href="#" target="_blank" class="hidden text-xs px-2 py-1 rounded bg-indigo-600/30 text-indigo-300 hover:bg-indigo-600/50 transition-colors" title="Open in browser">🌐 Open</a>
                     <button id="file-preview-close" class="text-slate-500 hover:text-white text-lg">✕</button>
                 </div>
             </div>
             <pre id="file-preview-content" class="flex-1 overflow-auto text-xs p-4 whitespace-pre-wrap break-all text-slate-300" style="overflow-x:hidden;word-wrap:break-word"></pre>
         </div>
     </div>
 
-    <script src="/static/js/utils.js"></script>
-    <script src="/static/js/tool-renderers.js"></script>
-    <script src="/static/js/usage.js"></script>
-    <script src="/static/js/analytics.js"></script>
-    <script src="/static/js/app.js"></script>
+    <script src="{{ static_url('js/utils.js') }}"></script>
+    <script src="{{ static_url('js/tool-renderers.js') }}"></script>
+    <script src="{{ static_url('js/usage.js') }}"></script>
+    <script src="{{ static_url('js/analytics.js') }}"></script>
+    <script src="{{ static_url('js/app.js') }}"></script>
 </body>
 </html>
diff --git a/app/templates/login.html b/app/templates/login.html
index b3ebd5f22..94eaba081 100644
--- a/app/templates/login.html
+++ b/app/templates/login.html
@@ -1,26 +1,26 @@
 <!DOCTYPE html>
 <html lang="en">
 <head>
     <meta charset="UTF-8">
     <meta name="viewport" content="width=device-width, initial-scale=1.0">
-    <link rel="icon" href="/static/favicon.svg" type="image/svg+xml">
+    <link rel="icon" href="{{ static_url('favicon.svg') }}" type="image/svg+xml">
     <title>🎼 Orchestra — Login</title>
     <style>
         * { margin: 0; padding: 0; box-sizing: border-box; }
         body {
             min-height: 100vh;
             display: flex;
             align-items: center;
             justify-content: center;
             background: #0f172a;
             font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
             color: #e2e8f0;
         }
         .login-card {
             background: rgba(30, 41, 59, 0.6);
             backdrop-filter: blur(16px);
             border: 1px solid rgba(71, 85, 105, 0.4);
             border-radius: 16px;
             padding: 40px;
             width: 360px;
             box-shadow: 0 8px 32px rgba(0, 0, 0, 0.3);
diff --git a/docs/tasks/9/codex-review.md b/docs/tasks/9/codex-review.md
new file mode 100644
index 000000000..39d6b9465
--- /dev/null
+++ b/docs/tasks/9/codex-review.md
@@ -0,0 +1,26 @@
+# #9 — cross-LLM ревью: вердикта нет
+
+**Codex недоступен — лимиты подписки исчерпаны.** Гейт снят оркестратором. Вердикта второй
+модели по этому дифу **не существует**; ниже только мой self-review.
+
+## Self-review
+
+Что нашёл у себя и исправил до коммита:
+
+1. **Вечный кеш на 404.** Первая версия вешала заголовок в `file_response`, и я собирался
+   ставить `immutable` по одному факту наличия `?v=`. Для несуществующего файла это означало бы
+   спрятать его от браузера до конца жизни профиля: положишь файл позже — юзер его не увидит.
+   Условие ужато до `status_code == 200`.
+2. **Разбор query «на глазок».** Проверка `b"v=" in query_string` считает версией любой параметр,
+   в имени которого есть `v=` (`?nov=1`). Заменено на `parse_qs`, точное совпадение ключа.
+   Проверено curl'ом.
+3. **Позиционное обращение к чужому API.** `file_response(*args)` и `args[2]` — угадывание
+   сигнатуры Starlette; переехал на `get_response(self, path, scope)`, где `scope` назван явно.
+
+Слабое место, оставленное осознанно, — версия из mtime, а не из хеша содержимого (разбор
+и триггер отката в report.md).
+
+Отдельно про метод проверки: сначала я считал запросы к `/static/` и решил, что кеш не работает
+(12 запросов при F5 без правок). Настоящая картина — `transferSize: 0`, то есть сеть не тронута
+вовсе; событие `response` в Playwright приходит и на попадание в кеш. Вывод по числу событий был
+бы ложным — цифру давал инструмент, а не система.
diff --git a/docs/tasks/9/report.md b/docs/tasks/9/report.md
new file mode 100644
index 000000000..efdde0494
--- /dev/null
+++ b/docs/tasks/9/report.md
@@ -0,0 +1,76 @@
+# #9 — статика доезжает до браузера непредсказуемо
+
+## Что было
+
+`app.js` (342 КБ) отдавался вообще без `Cache-Control`, ссылка в шаблоне — без версии.
+Браузер в этом случае применяет эвристику и может держать старую копию, не перепроверяя.
+Симптом: после мержа фикса юзер видит старое поведение и жмёт Ctrl-Shift-R.
+
+Проверено попутно: nginx статику **не** отдаёт и не кеширует — `location /` просто проксирует
+на `127.0.0.1:8888`, то есть заголовки FastAPI доходят до браузера как есть.
+
+## Решение
+
+Версия в query + разные правила кеширования для версионного и голого URL.
+
+1. **`static_url()` в `app/deps.py`** — Jinja-глобал, отдаёт `/static/<path>?v=<mtime_ns>`.
+   Изменился файл → изменился URL → браузер идёт за новым. Шаблоны переведены на него
+   (13 ссылок в `dashboard.html`, 1 в `login.html`).
+2. **`VersionedStatic` в `app/main.py`** — есть `?v=` и ответ 200 → `max-age=31536000, immutable`
+   (браузер не перепроверяет вообще); нет версии → `no-cache` (обязательная ревалидация, ETag
+   уже отдаётся, ответ 304 стоит копейки).
+3. **HTML — `no-cache`** (`dashboard`, `login`). В нём лежат версии статики: устареет он —
+   версии не обновятся, и весь механизм перестанет работать.
+
+Почему именно так, а не хеш в имени файла: нет сборки и не хочется её заводить, переименование
+потребовало бы генерации файлов на диске. Почему не «просто `no-cache` на всё»: канал юзера
+15–80 КБ/с, 342 КБ на каждый заход — плохой ответ.
+
+Правило выбрано так, чтобы **ошибка была безопасной**: забыли версию у нового файла — юзер
+платит лишним 304, а не сидит со старым кодом.
+
+## Приёмка (реальный браузер, обычный F5, не Ctrl-Shift-R)
+
+Мерил `transferSize` из Resource Timing, а не число запросов: на попадание в кеш событие
+`response` в Playwright всё равно приходит, и по нему кажется, будто файл качается.
+
+| шаг | из кеша без запроса | ревалидация 304 | полная загрузка | по сети |
+|---|---|---|---|---|
+| 1. первый заход | 0 | 0 | 12 | 1083.7 КБ |
+| 2. F5, ничего не менялось | 12 | 0 | 0 | **0 КБ** |
+| 3. F5 после правки `app.js` | 11 | 0 | **1** (`js/app.js`) | 333.7 КБ |
+
+Маркер в файле на шаге 3 сменился с 1 на 2 — правка доехала **обычным F5**. Скрипт:
+`/tmp/test_cache2.py`, стенд — `/tmp/harness.py` (реальные `VersionedStatic`, `static_url` и роут
+дашборда, поднятые на :8899 из worktree; живой сервис не трогался).
+
+Краевые случаи:
+
+```
+GET /static/js/nope.js?v=deadbeef  → 404, immutable НЕ ставится (иначе файл спрятан от юзера навсегда)
+GET /static/js/app.js?nov=1        → 200, cache-control: no-cache (чужой параметр не считается версией)
+```
+
+## Что важно знать при выкатке
+
+- **Требуется рестарт orchestra** — это Python-код. До рестарта ничего не меняется.
+- Переход должен быть чистым без Ctrl-Shift-R: HTML отдаётся без валидаторов и потому
+  запрашивается заново, а ссылки в нём — новые URL, которых в кеше нет. Если у кого-то
+  всё же залипнет старый HTML, одного F5 хватит, и дальше проблема не воспроизводится.
+
+## Известная дыра (не закрывал)
+
+Версия = `mtime`, а не хеш содержимого. Два следствия:
+
+- `git checkout`, вернувший тот же файл байт-в-байт, обновит mtime → одна лишняя загрузка.
+  Дёшево, мирюсь.
+- Если mtime когда-нибудь поедет **назад** при изменившемся содержимом (развёртывание через
+  `rsync -a`, распаковка архива с сохранением времён, восстановление из бэкапа), браузер отдаст
+  закешированную навечно старую копию. Наш деплой — git, он всегда ставит текущее время, поэтому
+  оставил как есть. Лечится переходом на хеш содержимого с кешем по `(path, mtime, size)`.
+
+## Тесты
+
+`tests/test_auth.py tests/test_frontend.py tests/test_api.py` → **59 failed, 76 passed, 8 errors**.
+Ровно тот же результат на базе ветки без моих правок (`git stash` → прогон → `stash pop`), то есть
+красное не от этой задачи.
diff --git a/docs/workers/frontend.md b/docs/workers/frontend.md
index 03cac1a2b..736ac4f58 100644
--- a/docs/workers/frontend.md
+++ b/docs/workers/frontend.md
@@ -1,12 +1,14 @@
 # Frontend worker
 
 Я — `frontend`. Веду фронтенд дашборда: `app/static/js/app.js`, `dashboard.html`, CSS, баблы и таск-панель.
 
 ## Правила
 
 - Копируешь визуальный язык существующего элемента → бери общий словарь и копируй решение целиком: иконку, цвет, фон, отсутствие рамки и тени. Проверяй результат в реальном размере (1x) перед сдачей; не изобретай новые глифы ради экономии кода.
   Причина: глифы ►/‖/○ в 9px развалились из-за хинтинга шрифта; индикатор переделали на ⚡/☕️/⏳ в кружке 17px из общих `_STATUS_ICON` / `_STATUS_COLOR` / `_STATUS_BG`.
 - Аналитика живёт в `app/static/js/analytics.js`; не возвращай её в `app.js`.
 - Правку фронта НЕЛЬЗЯ проверить на живом :8888 — статику он отдаёт из основного чекаута, не из моего worktree. Симптом обманчивый: страница работает, а твоей функции просто нет (`typeof _stashChatDom → undefined`). Проверять так: Playwright + `page.route('**/static/js/app.js', lambda r: r.fulfill(body=<файл из worktree>))`, а «до/после» мерить `git show HEAD:путь` против рабочей копии.
+- Python-правку (роуты, StaticFiles, deps) на живом :8888 не проверить — он требует рестарта, а рестартить нельзя. Поднимай свой стенд из worktree: `/tmp/harness.py` импортирует РЕАЛЬНЫЕ классы (`from app.main import VersionedStatic`, `from app.routes.system import router`) и монтирует их в голый FastAPI на :8899, без менеджера сессий и lifespan. Работать надо с `os.chdir(worktree)` — пути `app/static` и `app/templates` относительные. Гасить стенд по PID из `ss -ltnp | grep :8899`, НЕ `pkill -f` (шаблон совпадает с собственной командной строкой и убивает мой же шелл — проверено).
+- Кеш браузера мерить только по `transferSize` из Resource Timing: событие `response` в Playwright приходит и на попадание в кеш, по числу запросов кажется, что кеш не работает. `transferSize=0` — сеть не тронута, `0 < transferSize < encodedBodySize` — 304.
 - Клиентский CPU (кодирование картинок и т.п.) на этом VPS мерить нельзя: при LA 11–19 одна и та же операция даёт 405 мс и 13.7 с. Ловить спокойный момент бесполезно — либо считать по МП из чистого замера, либо просить прогон на машине юзера. В отчёте так и писать: «не измерено», а не подставлять цифру с перегруженной машины.
 - Прежде чем кешировать/переиспользовать куски чата — вспомни, что часть узлов ещё НЕ строки лога: черновик стрима (`streamBubble`), локальное эхо (`localMessages`), отложенный финал (`_streamDeferredFinal`). Их строка придёт позже с id > lastId → дубль, а если строку уже прочитали, выкинешь узел → потеря. Логика в `_stashChatDom`.


## Later history of the touched files on main (after this commit)

167 later commits touch these paths; the first 40 (oldest first):
100929fc9 2026-08-03 #15 T2: сервер называет версию фронта, страница показывает баннер вместо молчания
c6fe33c20 2026-08-03 #15 T3: TG-мост уходит с критического пути старта
ede489b39 2026-08-03 #13: #13: разрешение истории usage по диапазону + разрывы вместо выдуманных линий
b41f617ce 2026-08-03 #13, #9, #19: #13: CHANGELOG v2.31.0 и Known tradeoff отдельной секцией в отчёте
1ade3ca25 2026-08-03 #16: #16: исследование RAG-узла — замер по живой БД, гипотеза о синхронном бэкфилле опровергнута
1f0d15171 2026-08-03 #134: #134: HTML-артефакт с итогами ресёрча по реранкеру
d6a700f0b 2026-08-03 #22: #22: usage.js больше не перекрывается app.js — панель истории была мертва в проде
3fa87d0ee 2026-08-03 #29: #29: незащищённый Jinja-глобал больше нельзя смержить
d7870ec0a 2026-08-04 #33, #32: #33: дубли при загрузке — 41 запрос → 23, три разные причины
7c2e3154d 2026-08-04 #33, #38: #33: окно замера в отчёте и оговорка про page.route (кеш браузера выключается) + личная память
8d80c0525 2026-08-04 #28, #37: #28: заглушки backfill в test_api приведены к сигнатуре с session_name
2a6ed638d 2026-08-04 #141: #141: tool-сообщения в TG доходят все
96d60a261 2026-08-04 #49: #49: chart.js со своего домена, defer, ноль внешних зависимостей
b49c1acc1 2026-08-04 #53: #53: плашка «Новые bug reports» удалена целиком
f1220edf7 2026-08-04 #53: #53: осиротевший GET /api/report_bug/status удалён
0d3975b02 2026-08-04 #56: #56: исследование — репорт пишется в стор и на этом всё; адресат вычислим, семь старых разобраны
c7eb88e52 2026-08-04 merge: контур VPS + контур ноутбука
249bef6e7 2026-08-04 #142: #142: замер производительности дашборда — отчёт
c9c53bafc 2026-08-04 #59: #59: чат следует за новыми только когда юзер внизу
14d3f9d04 2026-08-04 #58: #58 (1/3): api() ставит таймаут ВСЕГДА — вечный лоадинг вылечен
ef9c8057b 2026-08-04 #62: #62: фаза 1 — рабочие копии сносит pytest в главном чекауте, воспроизведено
0227e73d1 2026-08-04 #57, #64: #57: аудит фронта — профилирование главного потока, парные абляции, цена взаимодействий
2c9339149 2026-08-04 #143: #143: механизм обрыва — потеря ретрансмитов на обратном пути, не nginx
92057a8d0 2026-08-04 #68: #68: цвет подписи отправителя доезжает при позднем списке агентов
5265212d2 2026-08-04 #70: #70: повтор GET при обрыве — три попытки по 3.5 с, отказ виден юзеру
262b38b5b 2026-08-04 #71: #71: исследование — 92.8% провода даёт одно поле, второй вызов от нулевого дросселя
f26a4b218 2026-08-04 #146: #146: зеркало orc.seedon.ru — обход обрыва 16 КБ
d1109cefc 2026-08-04 #72: #72: холодная синхронизация без предзагрузки, история порциями по байтам
d793f7a5c 2026-08-04 Merge remote-tracking branch 'origin/main'
51b1cb4cf 2026-08-04 Merge remote-tracking branch 'origin/main'
6d9c60c56 2026-08-05 #153: #153: split background Bash from real subagents in analytics and TG
f54b2a3e0 2026-08-05 #154: #154: тест таймаута истории проверяет поведение, а не текст вызова
51bc7947c 2026-08-05 #154: #154: личная память — красный тест на дословном тексте чинить поведенчески
d5b234b80 2026-08-04 Squashed commits: - #71: loadOrchestrators помечает свежесть — дубль запроса на старте убран - #71: заметка про известный флак test_chat_drop в личной памяти
b941a9558 2026-08-04 #74: #74: потолок на строку, видимый маркер обрезки и загрузка строки целиком
3b0e16a01 2026-08-04 #75: #75: таймаут api() 3.5 → 2 с — ожидание перед повтором дешевле
fc54ea76e 2026-08-04 #74, #66: #74/#66: живая проверка после рестарта + чиненный устаревший тест таймаута истории
9f777f912 2026-08-04 Squashed commits: - #82: исследование — имя как внешний ключ в трёх слоях, тихий путь не тот, что в репорте - #82: план — env чинится пересборкой, сохранённые ссылки предпочитают id, 4 тикета - #82: T1 — bg-джобы будят по неизменяемому id, а не по имени - WIP #82: T2 наполовину — в session.py есть флаг _identity_stale и его гашение на границе хода; НЕ сделано: manager.refresh_identity (пересборка mcp_servers) и вызов из rename_session, весь T3, T4 - #82: T2 — переименование пересобирает MCP-идентичность, перезапуск на границе хода - #82: T3 — держатель тест-лока по неизменяемому id, дети переименованного родителя - #82: T4 — живой прогон переименования, отчёт и личная память
8491f441e 2026-08-05 #94: #94: путь картинки вставляется в позицию каретки, а не в конец поля
e137badbc 2026-08-05 #105, #94: #105: доказано, что флак test_chat_drop_ не от #94 — база 3/9 красных, main 1/9

## Patches of the first 8 later commits, restricted to the touched paths (each capped at 150 lines)

### 100929fc9 #15 T2: сервер называет версию фронта, страница показывает баннер вместо молчания

diff --git a/app/deps.py b/app/deps.py
index a54127d44..3d223aa1a 100644
--- a/app/deps.py
+++ b/app/deps.py
@@ -1,7 +1,8 @@
 """Shared dependencies for routers — avoids importing from main."""
 
+import hashlib
 from pathlib import Path
 
 from fastapi.templating import Jinja2Templates
 
 from app.manager import SessionManager
@@ -25,6 +26,33 @@ def static_url(path: str) -> str:
         return f"/static/{path}?v={(_STATIC_DIR / path).stat().st_mtime_ns:x}"
     except OSError:
         return f"/static/{path}"
 
 
+_BUILD_GLOBS = ("js/*.js", "css/style.css")
+
+
+def build_id() -> str:
+    """Версия фронта целиком — та же mtime-механика, что у static_url().
+
+    Нужна, чтобы страница поняла, что бэкенд уехал вперёд, и сказала об этом вслух.
+    Считается на КАЖДЫЙ вызов, а не кешируется на импорте: сценарий, ради которого
+    она существует, — мерж без рестарта, когда файл на диске сменился, а процесс живой.
+    С кешем сигнал промолчал бы ровно в единственном случае, где он нужен. Цена —
+    stat нескольких файлов, зовётся раз в 3 с из heartbeat.
+
+    Вендорные библиотеки не берём: они меняются раз в месяцы и вручную, и такая
+    правка всё равно приезжает вместе с рестартом.
+
+    Хеш от пар «имя: mtime», а не max(mtime): максимум ловит только «что-то стало
+    новее» и слеп к удалению файла и к откату на более старую версию. Разница в две
+    строки, а слепое пятно исчезает целиком.
+    """
+    parts = sorted(f"{p.name}:{p.stat().st_mtime_ns}"
+                   for pattern in _BUILD_GLOBS for p in _STATIC_DIR.glob(pattern))
+    if not parts:
+        return "0"
+    return hashlib.blake2s("|".join(parts).encode(), digest_size=8).hexdigest()
+
+
 templates.env.globals["static_url"] = static_url
+templates.env.globals["build_id"] = build_id
diff --git a/app/routes/system.py b/app/routes/system.py
index 38349760a..edb64a785 100644
--- a/app/routes/system.py
+++ b/app/routes/system.py
@@ -17,17 +17,17 @@ from collections.abc import Iterator
 from contextlib import contextmanager
 from datetime import datetime, timezone
 from pathlib import Path
 from typing import Optional
 
-from fastapi import APIRouter, HTTPException, Request, Form
+from fastapi import APIRouter, HTTPException, Request, Response, Form
 from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
 from pydantic import BaseModel
 
 from app.auth import is_auth_enabled, is_owner_mode
 from app.db import get_all_sessions, list_profiles, upsert_profile, delete_profile
-from app.deps import manager, templates
+from app.deps import build_id, manager, templates
 from app.models import (
     MODELS,
     cache_policy_for_runtime,
     get_model_spec,
     is_proxy_connected,
@@ -340,11 +340,15 @@ async def remove_profile(name: str):
         return JSONResponse({"error": str(e)}, status_code=409)
     return list_profiles()
 
 
 @router.get("/api/models")
-async def list_models():
+async def list_models(response: Response):
+    # Версию фронта отдаём ЗАГОЛОВКОМ, а не полем в теле: heartbeat дёргает этот маршрут
+    # раз в 3 с и читает только статус — разбирать ради одного значения несколько
+    # килобайт JSON незачем. Тело маршрута при этом не меняется, старый клиент цел.
+    response.headers["X-Orchestra-Build"] = build_id()
     models = []
     for mid, name in MODELS.items():
         spec = get_model_spec(mid)
         entry = {
             "id": mid,
diff --git a/app/templates/dashboard.html b/app/templates/dashboard.html
index 8ee3595fb..c68c71a17 100644
--- a/app/templates/dashboard.html
+++ b/app/templates/dashboard.html
@@ -28,11 +28,11 @@
     <script src="https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js"></script>
     <script src="{{ static_url('css/vendor/highlight.min.js') }}"></script>
     <link rel="stylesheet" href="{{ static_url('css/vendor/highlight-github-dark.min.css') }}">
     <link rel="stylesheet" href="{{ static_url('css/style.css') }}">
 </head>
-<body class="h-screen overflow-hidden flex flex-col" data-currency="{{ currency_symbol }}" data-hide-thinking="{{ 'true' if hide_thinking else 'false' }}" data-auth-enabled="{{ 'true' if is_auth_enabled else 'false' }}" data-client-name="{{ client_name }}">
+<body class="h-screen overflow-hidden flex flex-col" data-build="{{ build_id() if build_id is defined else '' }}" data-currency="{{ currency_symbol }}" data-hide-thinking="{{ 'true' if hide_thinking else 'false' }}" data-auth-enabled="{{ 'true' if is_auth_enabled else 'false' }}" data-client-name="{{ client_name }}">
     <div id="rate-limit-banner" class="hidden items-center justify-center gap-2 px-4 py-2 bg-amber-500/15 border-b border-amber-500/40 text-amber-200 text-xs"></div>
     <div id="bug-report-banner" role="status" class="hidden fixed top-12 right-3 z-50 max-w-[min(28rem,calc(100vw-1.5rem))] items-center gap-2 rounded-lg border border-amber-500/40 bg-slate-950/95 px-3 py-2 text-xs text-amber-100 shadow-xl"></div>
     <div id="usage-bar"></div>
     <header class="flex items-center justify-between px-5 py-2 border-b border-slate-800/50">
         <div class="flex items-center gap-2 flex-1 min-w-0">
### c6fe33c20 #15 T3: TG-мост уходит с критического пути старта

diff --git a/app/main.py b/app/main.py
index e3f739e5b..27aea02eb 100644
--- a/app/main.py
+++ b/app/main.py
@@ -16,10 +16,27 @@ from app.db import init_db
 from app.deps import manager
 
 logger = logging.getLogger("orchestra")
 
 
+async def _start_bridge_background(manager) -> None:
+    """Поднять TG-мост вне критического пути старта.
+
+    Отказ обязан быть громким: мост, умерший молча, заметят через часы по отсутствию
+    сообщений, а не по логу.
+    """
+    logger.info("TG bridge: starting in background (HTTP is already serving)")
+    try:
+        from app.tg_bridge import start_bridge
+        await start_bridge(manager)
+        logger.info("TG bridge: ready")
+    except asyncio.CancelledError:
+        raise
+    except Exception as e:
+        logger.error(f"TG bridge FAILED to start: {type(e).__name__}: {e}", exc_info=True)
+
+
 @asynccontextmanager
 async def lifespan(app: FastAPI):
     from dotenv import load_dotenv
     load_dotenv()
     from app.session import validate_auto_compact_window_config
@@ -60,12 +77,16 @@ async def lifespan(app: FastAPI):
     await ensure_bootstrap()
     manager.start_background_tasks()
     from app.bg_jobs import bg_manager
     bg_manager.set_session_manager(manager)
     await bg_manager.restore_from_db()
-    from app.tg_bridge import start_bridge, stop_bridge
-    await start_bridge(manager)
+    # TG-мост поднимаем фоном. Замер (docs/tasks/15/research.md): один только импорт
+    # app.tg_bridge стоит 4.05 с, из них 3.72 с — aiogram, и всё это время uvicorn не
+    # принимает запросы, а nginx отдаёт 502. Старт сервиса был 4.3-13.9 с; для приёма
+    # HTTP мост не нужен. Плата: polling TG стартует на несколько секунд позже, и команда
+    # из TG в это окно выполнится с задержкой (Telegram её не теряет).
+    bridge_task = asyncio.create_task(_start_bridge_background(manager))
     from app.routes.system import _usage_snapshot_loop
     snapshot_task = asyncio.create_task(_usage_snapshot_loop())
     from app import rag_service
     if rag_service.is_enabled():
         rag_service.initialize()
@@ -77,10 +98,17 @@ async def lifespan(app: FastAPI):
     from app.merge_operations import shutdown_merge_operations
     await shutdown_merge_operations()
     _rs.shutdown()
     if _tunnel_started:
         await stop_tunnel()
+    # Мост мог ещё не подняться — гасим задачу и только потом просим его остановиться
+    bridge_task.cancel()
+    try:
+        await bridge_task
+    except (asyncio.CancelledError, Exception):
+        pass
+    from app.tg_bridge import stop_bridge
     await stop_bridge()
     await bg_manager.shutdown()
     await manager.shutdown_all()
 
 
### ede489b39 #13: #13: разрешение истории usage по диапазону + разрывы вместо выдуманных линий

diff --git a/app/routes/system.py b/app/routes/system.py
index edb64a785..6465fbb1b 100644
--- a/app/routes/system.py
+++ b/app/routes/system.py
@@ -976,16 +976,46 @@ async def _usage_snapshot_loop():
         except Exception as e:
             logger.error(f"usage snapshot error: {e}")
         await asyncio.sleep(SNAPSHOT_INTERVAL)
 
 
+# График рисует не весь запрошенный диапазон, а одно окно лимита (≤7 сут)
+# в 252 px — это 40 минут на пиксель. Шаг 30 мин даёт 1.3 точки на пиксель,
+# больше отдавать нечего рисовать: год в 5-минутной сетке — 4.32 МБ (замер 03.08).
+HISTORY_FINE_STEP = 5
+HISTORY_COARSE_STEP = 30
+# Сразу после недельного сброса текущий период — это часы, и на прореженной
+# сетке в нём остаётся 2-3 точки. Плюс решение «пора остановиться» принимают
+# по текущему 5h-окну, где нужна минутная детализация. Поэтому свежий хвост
+# всегда отдаём в полном разрешении.
+HISTORY_FINE_HOURS = 48
+
+
 @router.get("/api/usage/history")
-async def usage_history(hours: int = 24):
+async def usage_history(hours: int = 24, step_minutes: int = 0):
+    """История снимков: {step_minutes, rows}.
+
+    step_minutes — шаг сетки в прореженной части ответа. Фронт по нему решает,
+    где разрыв данных: расстояние между соседними точками больше шага = дырка,
+    её нельзя соединять линией.
+    """
+    if step_minutes < 0:
+        # шаг сетки идёт в `t += step`: отрицательный зациклит выборку намертво
+        raise HTTPException(400, "step_minutes must be >= 0")
     if not is_owner_mode():
-        return []
+        return {"step_minutes": step_minutes or HISTORY_FINE_STEP, "rows": []}
     from app.db import usage_get_history
-    return usage_get_history(hours)
+    if step_minutes:
+        return {"step_minutes": step_minutes, "rows": usage_get_history(hours, step_minutes)}
+    if hours <= HISTORY_FINE_HOURS:
+        return {"step_minutes": HISTORY_FINE_STEP,
+                "rows": usage_get_history(hours, HISTORY_FINE_STEP)}
+    coarse = usage_get_history(hours, HISTORY_COARSE_STEP)
+    fine = usage_get_history(HISTORY_FINE_HOURS, HISTORY_FINE_STEP)
+    cut = fine[0]["ts"] if fine else None
+    rows = [row for row in coarse if cut is None or row["ts"] < cut] + fine
+    return {"step_minutes": HISTORY_COARSE_STEP, "rows": rows}
 
 
 @router.get("/api/usage/analytics")
 async def usage_analytics_endpoint(days: int = 7):
     """Return one coherent capacity, cost, efficiency and reliability snapshot."""
diff --git a/docs/workers/frontend.md b/docs/workers/frontend.md
index 736ac4f58..3abb02ddb 100644
--- a/docs/workers/frontend.md
+++ b/docs/workers/frontend.md
@@ -7,8 +7,9 @@
 - Копируешь визуальный язык существующего элемента → бери общий словарь и копируй решение целиком: иконку, цвет, фон, отсутствие рамки и тени. Проверяй результат в реальном размере (1x) перед сдачей; не изобретай новые глифы ради экономии кода.
   Причина: глифы ►/‖/○ в 9px развалились из-за хинтинга шрифта; индикатор переделали на ⚡/☕️/⏳ в кружке 17px из общих `_STATUS_ICON` / `_STATUS_COLOR` / `_STATUS_BG`.
 - Аналитика живёт в `app/static/js/analytics.js`; не возвращай её в `app.js`.
 - Правку фронта НЕЛЬЗЯ проверить на живом :8888 — статику он отдаёт из основного чекаута, не из моего worktree. Симптом обманчивый: страница работает, а твоей функции просто нет (`typeof _stashChatDom → undefined`). Проверять так: Playwright + `page.route('**/static/js/app.js', lambda r: r.fulfill(body=<файл из worktree>))`, а «до/после» мерить `git show HEAD:путь` против рабочей копии.
 - Python-правку (роуты, StaticFiles, deps) на живом :8888 не проверить — он требует рестарта, а рестартить нельзя. Поднимай свой стенд из worktree: `/tmp/harness.py` импортирует РЕАЛЬНЫЕ классы (`from app.main import VersionedStatic`, `from app.routes.system import router`) и монтирует их в голый FastAPI на :8899, без менеджера сессий и lifespan. Работать надо с `os.chdir(worktree)` — пути `app/static` и `app/templates` относительные. Гасить стенд по PID из `ss -ltnp | grep :8899`, НЕ `pkill -f` (шаблон совпадает с собственной командной строкой и убивает мой же шелл — проверено).
+- «До/после» для правки, размазанной по нескольким модулям, мерить не своей веткой и не stash'ем: `git archive <ref> app | tar -x -C /tmp/before` и запускать замер `PYTHONPATH=/tmp/before` тем же интерпретатором на том же файле БД. Так «до» — это реальный main, а не мой пересказ старого кода. БД брать копией (`cp` живой файл в `/tmp`) и перекопировать перед финальным прогоном: замер по копии часовой давности показывает выдуманный хвост forward-fill до «сейчас».
 - Кеш браузера мерить только по `transferSize` из Resource Timing: событие `response` в Playwright приходит и на попадание в кеш, по числу запросов кажется, что кеш не работает. `transferSize=0` — сеть не тронута, `0 < transferSize < encodedBodySize` — 304.
 - Клиентский CPU (кодирование картинок и т.п.) на этом VPS мерить нельзя: при LA 11–19 одна и та же операция даёт 405 мс и 13.7 с. Ловить спокойный момент бесполезно — либо считать по МП из чистого замера, либо просить прогон на машине юзера. В отчёте так и писать: «не измерено», а не подставлять цифру с перегруженной машины.
 - Прежде чем кешировать/переиспользовать куски чата — вспомни, что часть узлов ещё НЕ строки лога: черновик стрима (`streamBubble`), локальное эхо (`localMessages`), отложенный финал (`_streamDeferredFinal`). Их строка придёт позже с id > lastId → дубль, а если строку уже прочитали, выкинешь узел → потеря. Логика в `_stashChatDom`.
### b41f617ce #13, #9, #19: #13: CHANGELOG v2.31.0 и Known tradeoff отдельной секцией в отчёте

diff --git a/app/routes/system.py b/app/routes/system.py
index 6465fbb1b..cff71c75e 100644
--- a/app/routes/system.py
+++ b/app/routes/system.py
@@ -13,11 +13,11 @@ import stat
 import subprocess
 import time
 import uuid
 from collections.abc import Iterator
 from contextlib import contextmanager
-from datetime import datetime, timezone
+from datetime import datetime, timedelta, timezone
 from pathlib import Path
 from typing import Optional
 
 from fastapi import APIRouter, HTTPException, Request, Response, Form
 from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
@@ -989,33 +989,42 @@ HISTORY_COARSE_STEP = 30
 # всегда отдаём в полном разрешении.
 HISTORY_FINE_HOURS = 48
 
 
 @router.get("/api/usage/history")
-async def usage_history(hours: int = 24, step_minutes: int = 0):
-    """История снимков: {step_minutes, rows}.
+async def usage_history(hours: int = 24, step_minutes: int = 0, until: str = ""):
+    """История снимков: {step_minutes, rows, oldest_ts}.
 
     step_minutes — шаг сетки в прореженной части ответа. Фронт по нему решает,
     где разрыв данных: расстояние между соседними точками больше шага = дырка,
     её нельзя соединять линией.
+    until — правая граница окна (исключительно). Фронт грузит период по клику ◀,
+    передавая время самой старой уже загруженной точки. oldest_ts — время первого
+    снимка вообще, по нему видно, осталось ли что грузить.
     """
     if step_minutes < 0:
         # шаг сетки идёт в `t += step`: отрицательный зациклит выборку намертво
         raise HTTPException(400, "step_minutes must be >= 0")
+    from app.db import usage_get_history, usage_history_oldest_ts, usage_history_ts_before
+    step = step_minutes or (HISTORY_FINE_STEP if hours <= HISTORY_FINE_HOURS
+                            else HISTORY_COARSE_STEP)
     if not is_owner_mode():
-        return {"step_minutes": step_minutes or HISTORY_FINE_STEP, "rows": []}
-    from app.db import usage_get_history
-    if step_minutes:
-        return {"step_minutes": step_minutes, "rows": usage_get_history(hours, step_minutes)}
-    if hours <= HISTORY_FINE_HOURS:
-        return {"step_minutes": HISTORY_FINE_STEP,
-                "rows": usage_get_history(hours, HISTORY_FINE_STEP)}
-    coarse = usage_get_history(hours, HISTORY_COARSE_STEP)
-    fine = usage_get_history(HISTORY_FINE_HOURS, HISTORY_FINE_STEP)
-    cut = fine[0]["ts"] if fine else None
-    rows = [row for row in coarse if cut is None or row["ts"] < cut] + fine
-    return {"step_minutes": HISTORY_COARSE_STEP, "rows": rows}
+        return {"step_minutes": step, "rows": [], "oldest_ts": ""}
+    if until:
+        # Окно навигации привязываем к данным: после простоя длиннее запрошенного
+        # куска календарное окно пришло бы пустым, и ◀ упёрлась бы в него навсегда.
+        previous = usage_history_ts_before(until)
+        if previous:
+            until = (datetime.fromisoformat(previous) + timedelta(microseconds=1)).isoformat()
+    rows = usage_get_history(hours, step, until)
+    # Хвост в полном разрешении нужен только живому виду: в куске из прошлого
+    # «последние 48 часов» — это такое же прошлое, детализация там не нужна.
+    if not until and not step_minutes and hours > HISTORY_FINE_HOURS:
+        fine = usage_get_history(HISTORY_FINE_HOURS, HISTORY_FINE_STEP)
+        cut = fine[0]["ts"] if fine else None
+        rows = [row for row in rows if cut is None or row["ts"] < cut] + fine
+    return {"step_minutes": step, "rows": rows, "oldest_ts": usage_history_oldest_ts()}
 
 
 @router.get("/api/usage/analytics")
 async def usage_analytics_endpoint(days: int = 7):
     """Return one coherent capacity, cost, efficiency and reliability snapshot."""
diff --git a/docs/workers/frontend.md b/docs/workers/frontend.md
index 3abb02ddb..a3032cbcf 100644
--- a/docs/workers/frontend.md
+++ b/docs/workers/frontend.md
@@ -8,8 +8,11 @@
   Причина: глифы ►/‖/○ в 9px развалились из-за хинтинга шрифта; индикатор переделали на ⚡/☕️/⏳ в кружке 17px из общих `_STATUS_ICON` / `_STATUS_COLOR` / `_STATUS_BG`.
 - Аналитика живёт в `app/static/js/analytics.js`; не возвращай её в `app.js`.
 - Правку фронта НЕЛЬЗЯ проверить на живом :8888 — статику он отдаёт из основного чекаута, не из моего worktree. Симптом обманчивый: страница работает, а твоей функции просто нет (`typeof _stashChatDom → undefined`). Проверять так: Playwright + `page.route('**/static/js/app.js', lambda r: r.fulfill(body=<файл из worktree>))`, а «до/после» мерить `git show HEAD:путь` против рабочей копии.
 - Python-правку (роуты, StaticFiles, deps) на живом :8888 не проверить — он требует рестарта, а рестартить нельзя. Поднимай свой стенд из worktree: `/tmp/harness.py` импортирует РЕАЛЬНЫЕ классы (`from app.main import VersionedStatic`, `from app.routes.system import router`) и монтирует их в голый FastAPI на :8899, без менеджера сессий и lifespan. Работать надо с `os.chdir(worktree)` — пути `app/static` и `app/templates` относительные. Гасить стенд по PID из `ss -ltnp | grep :8899`, НЕ `pkill -f` (шаблон совпадает с собственной командной строкой и убивает мой же шелл — проверено).
 - «До/после» для правки, размазанной по нескольким модулям, мерить не своей веткой и не stash'ем: `git archive <ref> app | tar -x -C /tmp/before` и запускать замер `PYTHONPATH=/tmp/before` тем же интерпретатором на том же файле БД. Так «до» — это реальный main, а не мой пересказ старого кода. БД брать копией (`cp` живой файл в `/tmp`) и перекопировать перед финальным прогоном: замер по копии часовой давности показывает выдуманный хвост forward-fill до «сейчас».
+- Мутационную проверку откатывать ТОЛЬКО обратной точечной заменой (`str.replace` назад), НИКОГДА не `git checkout <file>`: в файле лежат мои же незакоммиченные правки, и checkout сносит их целиком. Так я потерял весь переписанный роут `usage_history` и восстанавливал его по памяти. Если правка большая — коммить её ДО мутации.
+- Стенд для браузерных прогонов должен отдавать и страницу, и API с одного origin (`@app.get("/spark-test")` рядом с API на :8899): `page.set_content(...)` даёт `about:blank`, и любой `fetch` из него падает `TypeError: Failed to fetch`. Симптом выглядит как «кнопка не работает», а не как проблема стенда.
+- Цифру роста/срока («хватит на N месяцев») считать командой и печатать формулу, а не в уме: «4.36 МБ вернутся через 2.5 года» разошлось с правдой в 8 раз (реально 114 суток) и уехало в отчёт, в CHANGELOG и в DONE-репорт.
 - Кеш браузера мерить только по `transferSize` из Resource Timing: событие `response` в Playwright приходит и на попадание в кеш, по числу запросов кажется, что кеш не работает. `transferSize=0` — сеть не тронута, `0 < transferSize < encodedBodySize` — 304.
 - Клиентский CPU (кодирование картинок и т.п.) на этом VPS мерить нельзя: при LA 11–19 одна и та же операция даёт 405 мс и 13.7 с. Ловить спокойный момент бесполезно — либо считать по МП из чистого замера, либо просить прогон на машине юзера. В отчёте так и писать: «не измерено», а не подставлять цифру с перегруженной машины.
 - Прежде чем кешировать/переиспользовать куски чата — вспомни, что часть узлов ещё НЕ строки лога: черновик стрима (`streamBubble`), локальное эхо (`localMessages`), отложенный финал (`_streamDeferredFinal`). Их строка придёт позже с id > lastId → дубль, а если строку уже прочитали, выкинешь узел → потеря. Логика в `_stashChatDom`.
### 1ade3ca25 #16: #16: исследование RAG-узла — замер по живой БД, гипотеза о синхронном бэкфилле опровергнута

diff --git a/app/main.py b/app/main.py
index 27aea02eb..f11d13d6a 100644
--- a/app/main.py
+++ b/app/main.py
@@ -14,10 +14,16 @@ from starlette.middleware.base import BaseHTTPMiddleware
 from app.auth import is_auth_enabled, validate_session, requires_auth, check_internal_token
 from app.db import init_db
 from app.deps import manager
 
 logger = logging.getLogger("orchestra")
+# Uvicorn настраивает только свои логгеры, рутовый остаётся без хендлера → всё, что Orchestra
+# пишет на INFO, съедает lastResort (WARNING). Так пропадал весь жизненный цикл RAG-бэкфилла,
+# из-за чего баг «память отдаёт устаревший файл» с 26.07 висел недоказуемым (#16).
+if not logger.handlers:
+    logger.addHandler(logging.StreamHandler())
+    logger.setLevel(logging.INFO)
 
 
 async def _start_bridge_background(manager) -> None:
     """Поднять TG-мост вне критического пути старта.
 
### 1f0d15171 #134: #134: HTML-артефакт с итогами ресёрча по реранкеру

diff --git a/docs/workers/frontend.md b/docs/workers/frontend.md
index 03cac1a2b..24ad09871 100644
--- a/docs/workers/frontend.md
+++ b/docs/workers/frontend.md
@@ -7,6 +7,7 @@
 - Копируешь визуальный язык существующего элемента → бери общий словарь и копируй решение целиком: иконку, цвет, фон, отсутствие рамки и тени. Проверяй результат в реальном размере (1x) перед сдачей; не изобретай новые глифы ради экономии кода.
   Причина: глифы ►/‖/○ в 9px развалились из-за хинтинга шрифта; индикатор переделали на ⚡/☕️/⏳ в кружке 17px из общих `_STATUS_ICON` / `_STATUS_COLOR` / `_STATUS_BG`.
 - Аналитика живёт в `app/static/js/analytics.js`; не возвращай её в `app.js`.
 - Правку фронта НЕЛЬЗЯ проверить на живом :8888 — статику он отдаёт из основного чекаута, не из моего worktree. Симптом обманчивый: страница работает, а твоей функции просто нет (`typeof _stashChatDom → undefined`). Проверять так: Playwright + `page.route('**/static/js/app.js', lambda r: r.fulfill(body=<файл из worktree>))`, а «до/после» мерить `git show HEAD:путь` против рабочей копии.
 - Клиентский CPU (кодирование картинок и т.п.) на этом VPS мерить нельзя: при LA 11–19 одна и та же операция даёт 405 мс и 13.7 с. Ловить спокойный момент бесполезно — либо считать по МП из чистого замера, либо просить прогон на машине юзера. В отчёте так и писать: «не измерено», а не подставлять цифру с перегруженной машины.
+- Путь файла задан в задании → `git check-ignore -v <путь>` ДО начала работы, не на коммите. Стоит секунду на старте против потерянного хода в конце: `artifacts/` лежит в `.gitignore` (строка 18, security-коммит `0c9105f` скопом с `docs/proxy-*.md`), и готовый артефакт пришлось переносить в `docs/tasks/<id>/`. Туда же класть артефакты по умолчанию — один task = один каталог. *(на триаже у оркестратора, метит в CLAUDE.md)*
 - Прежде чем кешировать/переиспользовать куски чата — вспомни, что часть узлов ещё НЕ строки лога: черновик стрима (`streamBubble`), локальное эхо (`localMessages`), отложенный финал (`_streamDeferredFinal`). Их строка придёт позже с id > lastId → дубль, а если строку уже прочитали, выкинешь узел → потеря. Логика в `_stashChatDom`.
### d6a700f0b #22: #22: usage.js больше не перекрывается app.js — панель истории была мертва в проде

diff --git a/docs/workers/frontend.md b/docs/workers/frontend.md
index a3032cbcf..d3d26bd35 100644
--- a/docs/workers/frontend.md
+++ b/docs/workers/frontend.md
@@ -11,8 +11,11 @@
 - Python-правку (роуты, StaticFiles, deps) на живом :8888 не проверить — он требует рестарта, а рестартить нельзя. Поднимай свой стенд из worktree: `/tmp/harness.py` импортирует РЕАЛЬНЫЕ классы (`from app.main import VersionedStatic`, `from app.routes.system import router`) и монтирует их в голый FastAPI на :8899, без менеджера сессий и lifespan. Работать надо с `os.chdir(worktree)` — пути `app/static` и `app/templates` относительные. Гасить стенд по PID из `ss -ltnp | grep :8899`, НЕ `pkill -f` (шаблон совпадает с собственной командной строкой и убивает мой же шелл — проверено).
 - «До/после» для правки, размазанной по нескольким модулям, мерить не своей веткой и не stash'ем: `git archive <ref> app | tar -x -C /tmp/before` и запускать замер `PYTHONPATH=/tmp/before` тем же интерпретатором на том же файле БД. Так «до» — это реальный main, а не мой пересказ старого кода. БД брать копией (`cp` живой файл в `/tmp`) и перекопировать перед финальным прогоном: замер по копии часовой давности показывает выдуманный хвост forward-fill до «сейчас».
 - Мутационную проверку откатывать ТОЛЬКО обратной точечной заменой (`str.replace` назад), НИКОГДА не `git checkout <file>`: в файле лежат мои же незакоммиченные правки, и checkout сносит их целиком. Так я потерял весь переписанный роут `usage_history` и восстанавливал его по памяти. Если правка большая — коммить её ДО мутации.
 - Стенд для браузерных прогонов должен отдавать и страницу, и API с одного origin (`@app.get("/spark-test")` рядом с API на :8899): `page.set_content(...)` даёт `about:blank`, и любой `fetch` из него падает `TypeError: Failed to fetch`. Симптом выглядит как «кнопка не работает», а не как проблема стенда.
 - Цифру роста/срока («хватит на N месяцев») считать командой и печатать формулу, а не в уме: «4.36 МБ вернутся через 2.5 года» разошлось с правдой в 8 раз (реально 114 суток) и уехало в отчёт, в CHANGELOG и в DONE-репорт.
+- Строка «OK … 404 … нужен рестарт» в логе приёмочного скрипта — НЕ факт о проде: `verify-*.py` сами подсовывают отказы перехватом, чтобы проверить, что клиент называет причину вслух. Прежде чем заявить «на живом сервере такого маршрута нет», дёрни его curl'ом. Я так выдал несуществующую поломку соседнему воркеру, и он её опроверг за одну команду.
+- Мой стенд грузит ПОДМНОЖЕСТВО скриптов страницы, прод грузит все пять. Новое глобальное имя в `usage.js`/`analytics.js` может быть перекрыто объявлением из `app.js` (грузится последним) — и панель молча зовёт чужую функцию. Перед сдачей нового `function _foo` грепни все `app/static/js/*.js`; страж — `tests/test_static_js_globals.py`.
+- «Что было на диске при старте сервиса» брать из `git reflog` и `find app -name '*.py' -newermt "<startup>"`, НЕ из `git rev-list --before=<время>`: после `pull --rebase` даты коммиттера переписаны и врут. Проверка на вменяемость — сверить с тем, что сервер реально отдаёт (нашёлся `static_url()` в HTML → значит #9 уже был в процессе).
 - Кеш браузера мерить только по `transferSize` из Resource Timing: событие `response` в Playwright приходит и на попадание в кеш, по числу запросов кажется, что кеш не работает. `transferSize=0` — сеть не тронута, `0 < transferSize < encodedBodySize` — 304.
 - Клиентский CPU (кодирование картинок и т.п.) на этом VPS мерить нельзя: при LA 11–19 одна и та же операция даёт 405 мс и 13.7 с. Ловить спокойный момент бесполезно — либо считать по МП из чистого замера, либо просить прогон на машине юзера. В отчёте так и писать: «не измерено», а не подставлять цифру с перегруженной машины.
 - Прежде чем кешировать/переиспользовать куски чата — вспомни, что часть узлов ещё НЕ строки лога: черновик стрима (`streamBubble`), локальное эхо (`localMessages`), отложенный финал (`_streamDeferredFinal`). Их строка придёт позже с id > lastId → дубль, а если строку уже прочитали, выкинешь узел → потеря. Логика в `_stashChatDom`.
### 3fa87d0ee #29: #29: незащищённый Jinja-глобал больше нельзя смержить

diff --git a/app/templates/dashboard.html b/app/templates/dashboard.html
index c68c71a17..b965c540e 100644
--- a/app/templates/dashboard.html
+++ b/app/templates/dashboard.html
@@ -1,12 +1,13 @@
+{% import '_globals.html' as g -%}
 <!DOCTYPE html>
 <html lang="en">
 <head>
     <meta charset="UTF-8">
-    <link rel="icon" href="{{ static_url('favicon.svg') }}" type="image/svg+xml">
+    <link rel="icon" href="{{ g.asset('favicon.svg') }}" type="image/svg+xml">
     <title>🎼 Orchestra</title>
-    <script src="{{ static_url('css/vendor/tailwind.js') }}"></script>
+    <script src="{{ g.asset('css/vendor/tailwind.js') }}"></script>
     <script>
       // Design tokens via Tailwind config (CDN). Lift faint slate shades to meet WCAG AA
       // on the #0a0e17 bg, and route sans utilities to Inter (hybrid typography).
       tailwind.config = {
         theme: { extend: {
@@ -20,19 +21,19 @@
             600: '#6b7c93',  // was #475569 — faintest still-readable
           } },
         } },
       };
     </script>
-    <script src="{{ static_url('css/vendor/marked.min.js') }}"></script>
-    <script src="{{ static_url('css/vendor/purify.min.js') }}"></script>
-    <script src="{{ static_url('css/vendor/diff_match_patch.js') }}"></script>
+    <script src="{{ g.asset('css/vendor/marked.min.js') }}"></script>
+    <script src="{{ g.asset('css/vendor/purify.min.js') }}"></script>
+    <script src="{{ g.asset('css/vendor/diff_match_patch.js') }}"></script>
     <script src="https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js"></script>
-    <script src="{{ static_url('css/vendor/highlight.min.js') }}"></script>
-    <link rel="stylesheet" href="{{ static_url('css/vendor/highlight-github-dark.min.css') }}">
-    <link rel="stylesheet" href="{{ static_url('css/style.css') }}">
+    <script src="{{ g.asset('css/vendor/highlight.min.js') }}"></script>
+    <link rel="stylesheet" href="{{ g.asset('css/vendor/highlight-github-dark.min.css') }}">
+    <link rel="stylesheet" href="{{ g.asset('css/style.css') }}">
 </head>
-<body class="h-screen overflow-hidden flex flex-col" data-build="{{ build_id() if build_id is defined else '' }}" data-currency="{{ currency_symbol }}" data-hide-thinking="{{ 'true' if hide_thinking else 'false' }}" data-auth-enabled="{{ 'true' if is_auth_enabled else 'false' }}" data-client-name="{{ client_name }}">
+<body class="h-screen overflow-hidden flex flex-col" data-build="{{ g.build() }}" data-currency="{{ currency_symbol }}" data-hide-thinking="{{ 'true' if hide_thinking else 'false' }}" data-auth-enabled="{{ 'true' if is_auth_enabled else 'false' }}" data-client-name="{{ client_name }}">
     <div id="rate-limit-banner" class="hidden items-center justify-center gap-2 px-4 py-2 bg-amber-500/15 border-b border-amber-500/40 text-amber-200 text-xs"></div>
     <div id="bug-report-banner" role="status" class="hidden fixed top-12 right-3 z-50 max-w-[min(28rem,calc(100vw-1.5rem))] items-center gap-2 rounded-lg border border-amber-500/40 bg-slate-950/95 px-3 py-2 text-xs text-amber-100 shadow-xl"></div>
     <div id="usage-bar"></div>
     <header class="flex items-center justify-between px-5 py-2 border-b border-slate-800/50">
         <div class="flex items-center gap-2 flex-1 min-w-0">
@@ -303,12 +304,12 @@
             </div>
             <pre id="file-preview-content" class="flex-1 overflow-auto text-xs p-4 whitespace-pre-wrap break-all text-slate-300" style="overflow-x:hidden;word-wrap:break-word"></pre>
         </div>
     </div>
 
-    <script src="{{ static_url('js/utils.js') }}"></script>
-    <script src="{{ static_url('js/tool-renderers.js') }}"></script>
-    <script src="{{ static_url('js/usage.js') }}"></script>
-    <script src="{{ static_url('js/analytics.js') }}"></script>
-    <script src="{{ static_url('js/app.js') }}"></script>
+    <script src="{{ g.asset('js/utils.js') }}"></script>
+    <script src="{{ g.asset('js/tool-renderers.js') }}"></script>
+    <script src="{{ g.asset('js/usage.js') }}"></script>
+    <script src="{{ g.asset('js/analytics.js') }}"></script>
+    <script src="{{ g.asset('js/app.js') }}"></script>
 </body>
 </html>
diff --git a/app/templates/login.html b/app/templates/login.html
index 94eaba081..25f64ac2d 100644
--- a/app/templates/login.html
+++ b/app/templates/login.html
@@ -1,11 +1,12 @@
+{% import '_globals.html' as g -%}
 <!DOCTYPE html>
 <html lang="en">
 <head>
     <meta charset="UTF-8">
     <meta name="viewport" content="width=device-width, initial-scale=1.0">
-    <link rel="icon" href="{{ static_url('favicon.svg') }}" type="image/svg+xml">
+    <link rel="icon" href="{{ g.asset('favicon.svg') }}" type="image/svg+xml">
     <title>🎼 Orchestra — Login</title>
     <style>
         * { margin: 0; padding: 0; box-sizing: border-box; }
         body {
             min-height: 100vh;
diff --git a/docs/workers/frontend.md b/docs/workers/frontend.md
index d3d26bd35..ade1a41f2 100644
--- a/docs/workers/frontend.md
+++ b/docs/workers/frontend.md
@@ -11,10 +11,11 @@
 - Python-правку (роуты, StaticFiles, deps) на живом :8888 не проверить — он требует рестарта, а рестартить нельзя. Поднимай свой стенд из worktree: `/tmp/harness.py` импортирует РЕАЛЬНЫЕ классы (`from app.main import VersionedStatic`, `from app.routes.system import router`) и монтирует их в голый FastAPI на :8899, без менеджера сессий и lifespan. Работать надо с `os.chdir(worktree)` — пути `app/static` и `app/templates` относительные. Гасить стенд по PID из `ss -ltnp | grep :8899`, НЕ `pkill -f` (шаблон совпадает с собственной командной строкой и убивает мой же шелл — проверено).
 - «До/после» для правки, размазанной по нескольким модулям, мерить не своей веткой и не stash'ем: `git archive <ref> app | tar -x -C /tmp/before` и запускать замер `PYTHONPATH=/tmp/before` тем же интерпретатором на том же файле БД. Так «до» — это реальный main, а не мой пересказ старого кода. БД брать копией (`cp` живой файл в `/tmp`) и перекопировать перед финальным прогоном: замер по копии часовой давности показывает выдуманный хвост forward-fill до «сейчас».
 - Мутационную проверку откатывать ТОЛЬКО обратной точечной заменой (`str.replace` назад), НИКОГДА не `git checkout <file>`: в файле лежат мои же незакоммиченные правки, и checkout сносит их целиком. Так я потерял весь переписанный роут `usage_history` и восстанавливал его по памяти. Если правка большая — коммить её ДО мутации.
 - Стенд для браузерных прогонов должен отдавать и страницу, и API с одного origin (`@app.get("/spark-test")` рядом с API на :8899): `page.set_content(...)` даёт `about:blank`, и любой `fetch` из него падает `TypeError: Failed to fetch`. Симптом выглядит как «кнопка не работает», а не как проблема стенда.
 - Цифру роста/срока («хватит на N месяцев») считать командой и печатать формулу, а не в уме: «4.36 МБ вернутся через 2.5 года» разошлось с правдой в 8 раз (реально 114 суток) и уехало в отчёт, в CHANGELOG и в DONE-репорт.
+- Меняешь ФОРМУ вызова, а не поведение (обёртка пути, сигнатура, ключ ответа) — сразу грепни весь `tests/` по старой форме и прогони найденные файлы. За сутки таких поломок семь, и все лежали в файлах ЧУЖИХ задач: путь к скрипту за день обернули дважды (`/static/js/x.js` → `static_url('js/x.js')` → `g.asset('js/x.js')`), каждый раз роняя матчеры. Свои проверки писать по СМЫСЛУ (файл подключён скриптом), а не по тексту вызова.
 - Строка «OK … 404 … нужен рестарт» в логе приёмочного скрипта — НЕ факт о проде: `verify-*.py` сами подсовывают отказы перехватом, чтобы проверить, что клиент называет причину вслух. Прежде чем заявить «на живом сервере такого маршрута нет», дёрни его curl'ом. Я так выдал несуществующую поломку соседнему воркеру, и он её опроверг за одну команду.
 - Мой стенд грузит ПОДМНОЖЕСТВО скриптов страницы, прод грузит все пять. Новое глобальное имя в `usage.js`/`analytics.js` может быть перекрыто объявлением из `app.js` (грузится последним) — и панель молча зовёт чужую функцию. Перед сдачей нового `function _foo` грепни все `app/static/js/*.js`; страж — `tests/test_static_js_globals.py`.
 - «Что было на диске при старте сервиса» брать из `git reflog` и `find app -name '*.py' -newermt "<startup>"`, НЕ из `git rev-list --before=<время>`: после `pull --rebase` даты коммиттера переписаны и врут. Проверка на вменяемость — сверить с тем, что сервер реально отдаёт (нашёлся `static_url()` в HTML → значит #9 уже был в процессе).
 - Кеш браузера мерить только по `transferSize` из Resource Timing: событие `response` в Playwright приходит и на попадание в кеш, по числу запросов кажется, что кеш не работает. `transferSize=0` — сеть не тронута, `0 < transferSize < encodedBodySize` — 304.
 - Клиентский CPU (кодирование картинок и т.п.) на этом VPS мерить нельзя: при LA 11–19 одна и та же операция даёт 405 мс и 13.7 с. Ловить спокойный момент бесполезно — либо считать по МП из чистого замера, либо просить прогон на машине юзера. В отчёте так и писать: «не измерено», а не подставлять цифру с перегруженной машины.