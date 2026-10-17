# Context for item-38

## Diff reviewed (-U20, capped at 1500 lines)

diff --git a/app/main.py b/app/main.py
index b8f89f7c4..eaa572621 100644
--- a/app/main.py
+++ b/app/main.py
@@ -1,32 +1,33 @@
 """Orchestra — AI Agent Orchestrator. App factory: lifespan, middleware, routers."""
 
 import asyncio
 import logging
 import os
 from contextlib import asynccontextmanager
 from urllib.parse import parse_qs
 
 from fastapi import FastAPI, Request
 from fastapi.responses import JSONResponse, RedirectResponse
 from fastapi.staticfiles import StaticFiles
 from starlette.middleware.base import BaseHTTPMiddleware
+from starlette.middleware.gzip import GZipMiddleware
 
 from app.auth import is_auth_enabled, validate_session, requires_auth, check_internal_token
 from app.db import init_db
 from app.deps import manager
 from app.initial_deliveries import recover_initial_deliveries
 
 logger = logging.getLogger("orchestra")
 # Uvicorn настраивает только свои логгеры, рутовый остаётся без хендлера → всё, что Orchestra
 # пишет на INFO, съедает lastResort (WARNING). Так пропадал весь жизненный цикл RAG-бэкфилла,
 # из-за чего баг «память отдаёт устаревший файл» с 26.07 висел недоказуемым (#16).
 if not logger.handlers:
     logger.addHandler(logging.StreamHandler())
     logger.setLevel(logging.INFO)
 # И для пакета целиком. Модули пишут в ``logging.getLogger(__name__)`` — это "app.workspace",
 # "app.session" и т.д., а они НЕ потомки "orchestra": настройка одного этого имени оставила
 # весь пакет немым ниже WARNING. Именно поэтому удаление рабочих копий 03.08 не оставило в
 # журнале ни строчки (#62). Настраиваем корень пакета, чтобы СЛЕДУЮЩИЙ модуль был слышен
 # по умолчанию, а не попал в ту же ловушку.
 _app_logger = logging.getLogger("app")
 if not _app_logger.handlers:
@@ -447,20 +448,31 @@ class AuthMiddleware(BaseHTTPMiddleware):
             }
             return JSONResponse({"result": None, "error": error}, status_code=426)
         # Internal token bypasses cookie auth — allows MCP subprocess and workers
         # to call the API without a browser session
         if check_internal_token(request.headers.get("authorization", "")):
             return await call_next(request)
         if not is_auth_enabled():
             return await call_next(request)
         if not requires_auth(path, method):
             return await call_next(request)
         token = request.cookies.get("session")
         if token and validate_session(token):
             return await call_next(request)
         if path.startswith("/api/"):
             return JSONResponse({"error": "unauthorized"}, status_code=401)
         return RedirectResponse("/login", status_code=302)
 
 
 app.add_middleware(RequestCensusMiddleware)
 app.add_middleware(AuthMiddleware)
+# Статика первой загрузки — 814 КБ против 68 КБ у всех API вместе (#197). Отдавалась
+# несжатой: `curl --compressed` возвращал те же 434 627 байт для app.js. gzip даёт 3.7×
+# (814 -> 221 КБ), а на канале с ~17% потерь вчетверо меньше байт — это ещё и вчетверо
+# меньше шансов поймать обрыв посреди передачи.
+# Добавлен ПОСЛЕДНИМ, а значит стоит САМЫМ ВНЕШНИМ (add_middleware делает insert(0)).
+# Так и надо: gzip придерживает кадр `http.response.start` до первого куска тела, а
+# RequestCensusMiddleware именно на этом кадре читает `content-type`, чтобы отличить
+# поток от обычного ответа. Стой gzip внутри — счётчик дренажа узнавал бы о потоке с
+# опозданием. Снаружи он сжимает уже посчитанный ответ и ничего не сдвигает.
+# SSE не сжимается: DEFAULT_EXCLUDED_CONTENT_TYPES в Starlette 1.1.0 — ('text/event-stream',).
+app.add_middleware(GZipMiddleware, minimum_size=1024)
diff --git a/app/routes/system.py b/app/routes/system.py
index 908a7a197..181ea9036 100644
--- a/app/routes/system.py
+++ b/app/routes/system.py
@@ -382,42 +382,46 @@ async def head_models():
     return Response(status_code=200, headers={"X-Orchestra-Build": build_id()})
 
 
 @router.post("/api/models/refresh")
 async def refresh_models_endpoint():
     from app.models import refresh_models
     await refresh_models()
     return {"ok": True, "proxy_connected": is_proxy_connected(), "model_count": len(MODELS)}
 
 
 @router.get("/api/stats")
 async def stats(scope: Optional[str] = None):
     return manager.stats(scope)
 
 
 # ── Usage (subscription limits) ──
 
 _USAGE_CACHE_FILE = Path(__file__).parent.parent.parent / "data" / "usage_cache.json"
 _usage_cache: dict = {"data": None, "ts": 0.0, "token": None}
 _codex_usage_cache: dict = {"data": None, "ts": 0.0}
-_grok_usage_cache: dict = {"data": None, "ts": 0.0}
+_grok_usage_cache: dict = {"data": None, "ts": 0.0, "failed_at": 0.0}
 _USAGE_CACHE_TTL = 300
+# Провал провайдера кешируется отдельно и короче успеха (#197): держать отказ 5 минут
+# значит не заметить починку токена, а ходить за ним каждый раз — платить 0.88 с на
+# каждом `/api/usage`. Минута закрывает опрос дашборда (раз в 2 мин) с запасом.
+_USAGE_FAILURE_TTL = 60
 _quota_refresh_locks = {
     "anthropic": asyncio.Lock(),
     "codex": asyncio.Lock(),
     "grok": asyncio.Lock(),
 }
 _CREDENTIALS_PATH = Path.home() / ".claude" / ".credentials.json"
 _GROK_CREDENTIALS_PATH = Path.home() / ".grok" / "auth.json"
 
 
 def _load_usage_cache():
     if _USAGE_CACHE_FILE.exists():
         try:
             cached = json.loads(_USAGE_CACHE_FILE.read_text())
             _usage_cache["data"] = cached.get("data")
             _usage_cache["ts"] = cached.get("ts", 0.0)
         except Exception as e:
             logger.warning(f"usage cache load failed: {e}")
 
 
 def _save_usage_cache():
@@ -864,58 +868,76 @@ async def _get_usage_data(
                 _codex_usage_cache["ts"] = now
             else:
                 codex_data = _codex_usage_cache["data"]
         except Exception as e:
             logger.warning(f"Codex usage fetch failed: {e}")
             codex_data = _codex_usage_cache["data"]
     if required_provider in {"codex", "codex_spark"} and not codex_fetched:
         raise RuntimeError("fresh Codex usage is unavailable")
 
     grok_data = None
     grok_fetched = False
     skip_grok_refresh = bool(required_provider) and required_provider != "grok"
     if skip_grok_refresh:
         grok_data = _grok_usage_cache["data"]
     elif (
         not force_refresh
         and _grok_usage_cache["data"]
         and (now - _grok_usage_cache["ts"]) < _USAGE_CACHE_TTL
     ):
         grok_data = _grok_usage_cache["data"]
+    elif (
+        # Провал провайдера тоже кешируется (#197). Без этого протухший токен Grok стоил
+        # 0.88 с ЖИВОГО сетевого вызова на КАЖДЫЙ `/api/usage`: ветка провала обнуляет
+        # `ts`, а обнулённый `ts` не проходит проверку TTL никогда — то есть TTL для
+        # сбойного провайдера не действовал вовсе. Замер: /api/usage 0.88-1.21 с при
+        # /api/models 0.002 с. Окно короче успеха: токен могут починить в любой момент,
+        # и ждать полные 5 минут после починки незачем.
+        not force_refresh
+        # `.get`, а не `[...]`: словарь целиком подменяется извне (session_turns и тесты),
+        # и жёсткий ключ уронил бы `/api/usage` на чужой подмене без этого поля.
+        and (now - _grok_usage_cache.get("failed_at", 0.0)) < _USAGE_FAILURE_TTL
+    ):
+        grok_data = _grok_usage_cache["data"]
     else:
         token = _read_grok_token()
         if token:
             try:
                 grok_data = await _fetch_grok_usage(token)
                 grok_fetched = grok_data is not None
             except PermissionError:
                 logger.warning("Grok usage unavailable: OAuth token expired")
             except Exception as error:
                 logger.warning(f"Grok usage fetch failed: {error}")
         else:
             logger.warning("Grok usage unavailable: no OAuth credentials")
         if grok_fetched:
             _grok_usage_cache["data"] = grok_data
             _grok_usage_cache["ts"] = now
+            _grok_usage_cache["failed_at"] = 0.0
         elif required_provider == "grok" or not required_provider:
+            # `data=None, ts=0` сохраняем: «данных по Grok нет» должно оставаться видимым,
+            # подставлять вместо этого вчерашние проценты нельзя. Кешируется только САМ
+            # ФАКТ провала — чтобы не ходить в сеть за тем же отказом каждую секунду.
             _grok_usage_cache["data"] = None
             _grok_usage_cache["ts"] = 0.0
+            _grok_usage_cache["failed_at"] = now
     if required_provider == "grok" and not grok_fetched:
         raise RuntimeError("fresh Grok usage is unavailable")
 
     return {
         "anthropic": anthropic_data,
         "codex": codex_data,
         "grok": grok_data,
         "orchestra": _get_agents_cost(),
         "voice_cost_usd": round(_get_voice_cost_usd(), 4),
         # Единственное РЕАЛЬНОЕ число в этой панели (остальные — API-эквивалент).
         # Свободная строка, потому что тариф не выражается одним числом: "$200+$20/мес".
         # Не задано → фронт строку не рисует, чтобы не показывать устаревшую цену.
         "subscription_cost": os.getenv("SUBSCRIPTION_COST", ""),
     }
 
 
 @router.get("/api/usage")
 async def get_usage():
     if not is_owner_mode():
         return None
diff --git a/app/static/js/app.js b/app/static/js/app.js
index e1b9b0164..0baa02cc2 100644
--- a/app/static/js/app.js
+++ b/app/static/js/app.js
@@ -1151,58 +1151,70 @@ async function loadMoreLogs() {
                 if (!chatLogs[selectedAgent]) chatLogs[selectedAgent] = { lastId: 0, firstId: null, initialCount: 0 };
                 if (chatLogs[selectedAgent].firstId === null || l.id < chatLogs[selectedAgent].firstId) {
                     chatLogs[selectedAgent].firstId = l.id;
                 }
             }
         } finally {
             _chatTrimLimit = previousTrimLimit;
             _replayingHistory = false;
         }
         chat.scrollTop = chat.scrollHeight - oldHeight;
         // Full page (500) returned → more may exist, re-add button. Fewer → reached the start.
         if (logs.length >= 500) _addLoadMoreBtn();
     } catch (e) {
         if (btn) { btn.textContent = '▲ Load 500 more'; btn.style.pointerEvents = ''; }
         console.warn('loadMoreLogs error:', e);
     }
 }
 
 
 // === Models ===
+function _renderModels(data) {
+    const models = data.models || [];
+    _MODELS = models.map(m => ({ ...m, label: m.name }));
+    _modelsLoaded = true;
+    const select = $('#orch-model');
+    if (select) {
+        select.innerHTML = '';
+        for (const m of models) {
+            const opt = document.createElement('option');
+            opt.value = m.id;
+            opt.textContent = `${m.name} (${m.id})`;
+            select.appendChild(opt);
+        }
+    }
+    _updateProxyStatus(data.proxy_connected);
+}
+
 async function _loadModelsNow() {
     try {
         const data = await api('/api/models', {pollKey: 'models'});
-        const models = data.models || [];
-        _MODELS = models.map(m => ({ ...m, label: m.name }));
-        _modelsLoaded = true;
-        const select = $('#orch-model');
-        if (select) {
-            select.innerHTML = '';
-            for (const m of models) {
-                const opt = document.createElement('option');
-                opt.value = m.id;
-                opt.textContent = `${m.name} (${m.id})`;
-                select.appendChild(opt);
-            }
-        }
-        _updateProxyStatus(data.proxy_connected);
-    } catch {}
+        _renderModels(data);
+        snapshotSave('models', data);
+    } catch (e) {
+        // Каталог моделей почти статичен — снимок тут не «может пригодиться», а закрывает
+        // дыру целиком: без него пустой селектор не даёт создать оркестратора вовсе.
+        console.warn(`models: ${e.name}: ${e.message}`);
+        if (_modelsLoaded) return;
+        const snapshot = snapshotLoad('models');
+        if (snapshot) _renderModels(snapshot.data);
+    }
 }
 
 function loadModels() {
     return _pollCoalesce('models-request', _loadModelsNow);
 }
 
 // === Profile / Pipeline / Role dropdowns (модалка создания корня) ===
 let _pipelineRoles = {};  // карта pipeline-name → [roles]
 
 async function loadProfilesDropdown() {
     try {
         const profiles = await api('/api/profiles');
         const select = $('#orch-profile');
         select.innerHTML = '';
         for (const p of profiles) {
             const opt = document.createElement('option');
             opt.value = p.name;
             opt.textContent = `${p.name} (${p.config_dir || 'env процесса'})`;
             select.appendChild(opt);
         }
@@ -1598,84 +1610,101 @@ async function restartServer() {
     // Возврат ловит heartbeat и восстанавливает состояние на месте.
 }
 
 async function deleteOrchestrator() {
     if (!currentScope || !selectedAgent) return;
     if (!confirm(`Delete "${selectedAgent}" and all its workers?`)) return;
     try {
         await api(`/api/orchestrators/${selectedAgent}?scope=${encodeURIComponent(currentScope)}`, { method: 'DELETE' });
         localStorage.removeItem('lastOrchScope');
         localStorage.removeItem('lastOrchName');
         currentScope = null;
         selectedAgent = null;
         await loadOrchestrators();
     } catch (e) { alert(`Delete failed: ${e.message}`); }
 }
 
 // === Orchestrator Picker ===
 let orchData = [];
 const _unreadTabs = new Set();
 
+function _renderOrchestrators(allOrchs) {
+    // Sub-orchestrators (have parent) get TG topics but don't show in top tab bar
+    orchData = allOrchs.filter(o => !o.parent_name);
+    const picker = $('#orch-picker');
+    picker.innerHTML = '';
+    for (const o of orchData) {
+        const opt = document.createElement('option');
+        opt.value = o.scope;
+        opt.dataset.id = o.id;
+        opt.dataset.name = o.name;
+        opt.textContent = o.name;
+        picker.appendChild(opt);
+    }
+
+    const lastScope = localStorage.getItem('lastOrchScope');
+    const lastName = localStorage.getItem('lastOrchName');
+    const recentRaw = localStorage.getItem('recentOrchs');
+    const recent = recentRaw ? JSON.parse(recentRaw) : [];
+
+    const sorted = [...orchData].sort((a, b) => {
+        const ai = recent.indexOf(a.name);
+        const bi = recent.indexOf(b.name);
+        if (ai >= 0 && bi >= 0) return ai - bi;
+        if (ai >= 0) return -1;
+        if (bi >= 0) return 1;
+        return 0;
+    });
+
+    renderOrchTabs(sorted);
+
+    if (orchData.length > 0 && !currentScope) {
+        const match = orchData.find(o => o.scope === lastScope && o.name === lastName);
+        if (match) {
+            selectOrchestrator(match.name, match.scope);
+        } else {
+            selectOrchestrator(sorted[0].name, sorted[0].scope);
+        }
+    }
+}
+
 async function _loadOrchestratorsNow() {
     try {
         const allOrchs = await api('/api/orchestrators', {pollKey: 'orchestrators'});
         // Данные только что получены. Без этой отметки дроссель в refreshSessions считает
         // их протухшими и через полсекунды тянет тот же список второй раз (#71).
         _orchFreshAt = Date.now();
-        // Sub-orchestrators (have parent) get TG topics but don't show in top tab bar
-        orchData = allOrchs.filter(o => !o.parent_name);
-        const picker = $('#orch-picker');
-        picker.innerHTML = '';
-        for (const o of orchData) {
-            const opt = document.createElement('option');
-            opt.value = o.scope;
-            opt.dataset.id = o.id;
-            opt.dataset.name = o.name;
-            opt.textContent = o.name;
-            picker.appendChild(opt);
-        }
-
-        const lastScope = localStorage.getItem('lastOrchScope');
-        const lastName = localStorage.getItem('lastOrchName');
-        const recentRaw = localStorage.getItem('recentOrchs');
-        const recent = recentRaw ? JSON.parse(recentRaw) : [];
-
-        const sorted = [...orchData].sort((a, b) => {
-            const ai = recent.indexOf(a.name);
-            const bi = recent.indexOf(b.name);
-            if (ai >= 0 && bi >= 0) return ai - bi;
-            if (ai >= 0) return -1;
-            if (bi >= 0) return 1;
-            return 0;
-        });
-
-        renderOrchTabs(sorted);
-
-        if (orchData.length > 0 && !currentScope) {
-            const match = orchData.find(o => o.scope === lastScope && o.name === lastName);
-            if (match) {
-                selectOrchestrator(match.name, match.scope);
-            } else {
-                selectOrchestrator(sorted[0].name, sorted[0].scope);
-            }
+        _renderOrchestrators(allOrchs);
+        snapshotSave('orchestrators', allOrchs);
+        _clearStaleNotice('orchestrators');
+    } catch (e) {
+        // Пустые вкладки без причины — это то, на что юзер и жалуется. Молчать нельзя:
+        // без вкладок дашборд не выбирает scope, и не работает ВООБЩЕ ничего.
+        console.warn(`orchestrators: ${e.name}: ${e.message}`);
+        const snapshot = orchData.length ? null : snapshotLoad('orchestrators');
+        if (snapshot) {
+            _renderOrchestrators(snapshot.data);
+            _showStaleNotice('orchestrators', snapshot.ts);
+        } else if (!orchData.length) {
+            _showErrorNotice('orchestrators', 'Список оркестраторов не загрузился', e);
         }
-    } catch {}
+    }
 }
 
 function loadOrchestrators() {
     return _pollCoalesce('orchestrators-request', _loadOrchestratorsNow);
 }
 
 function _applyTabOrder(list) {
     const saved = JSON.parse(localStorage.getItem('tabOrder') || '[]');
     if (!saved.length) return list;
     return [...list].sort((a, b) => {
         const ai = saved.indexOf(a.name);
         const bi = saved.indexOf(b.name);
         if (ai >= 0 && bi >= 0) return ai - bi;
         if (ai >= 0) return -1;
         if (bi >= 0) return 1;
         return 0;
     });
 }
 
 function _saveTabOrder() {
@@ -2663,41 +2692,47 @@ function setContextDisplay(text) {
 }
 
 function formatContext(ctx) {
     const pct = Math.round(ctx.percentage || 0);
     const total = ctx.total_tokens || 0;
     const max = ctx.max_tokens || 0;
     const totalK = total > 1000 ? `${(total/1000).toFixed(0)}k` : total;
     const maxK = max > 1000 ? `${(max/1000).toFixed(0)}k` : max;
     let s = `${pct}% (${totalK}/${maxK})`;
     if (ctx.cache_hit !== undefined) s += ` · cache ${Number(ctx.cache_hit).toFixed(2)}%`;
     return s;
 }
 
 async function _fetchAgentContextNow(name) {
     if (!currentScope) return;
     try {
         const ctx = await api(`/api/sessions/${name}/context?scope=${encodeURIComponent(currentScope)}`, {pollKey: 'context'});
         const text = formatContext(ctx);
         contextCache[`${currentScope}:${name}`] = text;
         if (name === selectedAgent) setContextDisplay(text);
-    } catch {}
+    } catch (e) {
+        console.warn(`context ${name}: ${e.name}: ${e.message}`);
+        // Прошлое значение показать честнее, чем прочерк: контекст растёт медленно, и
+        // цифра минутной давности осмысленна, а «-» неотличим от «агент только что создан».
+        const known = contextCache[`${currentScope}:${name}`];
+        if (known && name === selectedAgent) setContextDisplay(`${known} (не обновлено)`);
+    }
 }
 
 function fetchAgentContext(name) {
     return _pollCoalesce(`context-request:${name}`, () => _fetchAgentContextNow(name));
 }
 
 // === Agent List ===
 function renderAgentList(sessions) {
     if (!sessions) return;
     const list = $('#agent-list');
     list.innerHTML = '';
 
     let colorsChanged = false;
     for (const s of sessions) {
         if (s.color && agentColors[s.name] !== s.color) {
             agentColors[s.name] = s.color;
             colorsChanged = true;
         }
         _sessionIds[_chatPositionKey(currentScope, s.name)] = s.id;  // ключ валидности кеша чата
     }
@@ -6864,91 +6899,132 @@ async function refreshSessions() {
     refreshController = new AbortController();
     const signal = refreshController.signal;
     // Capture scope at call time — guard below checks it didn't change while we were fetching
     const capturedScope = currentScope;
 
     try {
         if (!capturedScope) return;
 
         const [sessions, stats] = await Promise.all([
             // Свой бюджет тут был 20 с — из предположения, что канал юзера 15–80 КБ/с.
             // Замер perf это опроверг: здоровый ответ приезжает за секунды, а сломанный не
             // приезжает вовсе. Длинное ожидание не спасало ни одного запроса, зато мешало
             // повтору, поэтому здесь теперь дефолтный бюджет и три попытки.
             api(`/api/sessions?scope=${encodeURIComponent(capturedScope)}`, { signal, pollKey: 'sessions' }),
             api(`/api/stats?scope=${encodeURIComponent(capturedScope)}`, { signal, pollKey: 'sessions' }),
         ]);
 
         if (capturedScope !== currentScope) return;
         _onServerOk();
 
-        $('#stats-line').innerHTML = `${stats.active} active · ${stats.total_sessions} total<br><span style="color:#64748b;font-size:10px">${MODEL_COST_CURRENCY}${stats.total_cost_usd} (w/o cache)</span>`;
-        renderAgentList(sessions);
+        _renderSessionsAndStats(sessions, stats);
+        snapshotSave(`sessions:${capturedScope}`, {sessions, stats});
+        _clearStaleNotice('sessions');
 
         // Список оркестраторов нужен для меток непрочитанного по ЧУЖИМ вкладкам, но он
         // весит 55 КБ и раньше тянулся каждые 3 с вместе с сессиями — 1.1 МБ в минуту на
         // канале 15–80 КБ/с. Метка, опоздавшая на десяток секунд, никому не мешает.
         if (Date.now() - _orchFreshAt >= _ORCH_REFRESH_MS) try {
             _orchFreshAt = Date.now();
             const freshOrchs = await api('/api/orchestrators', { signal });
             for (const fo of freshOrchs) {
                 const existing = orchData.find(o => o.name === fo.name);
                 if (existing) {
                     if (_orchestratorTurnFinished(existing, fo) && fo.scope !== currentScope) {
                         _unreadTabs.add(fo.scope);
                     }
                     existing.status = fo.status; existing.cost_usd = fo.cost_usd; existing.any_running = fo.any_running;
                 }
             }
             updateOrchTabDots();
-        } catch {}
+        } catch (e) {
+            // Метки непрочитанного — украшение, но их пропажа не должна быть немой:
+            // юзер иначе решит, что чужие вкладки молчат, а они просто не доехали.
+            console.warn(`orchestrator dots: ${e.name}: ${e.message}`);
+        }
 
         if (selectedAgent) {
             const agentSession = sessions.find(s => s.name === selectedAgent);
             if (agentSession) {
                 updateStopButton(agentSession.status);
                 if (agentSession.status !== 'running') {
                     removeWaitingIndicator();
                 }
             }
             if (!eventSource) connectSSE();
         }
     } catch (e) {
-        if (e.name !== 'AbortError') { console.warn('refresh error:', e); _onFetchFail(e); }
+        if (e.name !== 'AbortError') {
+            console.warn('refresh error:', e);
+            _onFetchFail(e);
+            _restoreSessionsSnapshot(capturedScope, e);
+        }
     } finally {
         refreshInProgress = false;
     }
 }
 
+function _renderSessionsAndStats(sessions, stats) {
+    $('#stats-line').innerHTML = `${stats.active} active · ${stats.total_sessions} total<br><span style="color:#64748b;font-size:10px">${MODEL_COST_CURRENCY}${stats.total_cost_usd} (w/o cache)</span>`;
+    renderAgentList(sessions);
+}
+
+// Список агентов — то, из чего заполняются Model/Role/Cost/Branch/Scope. Пока он пуст,
+// пуста и панель, и юзер видит прочерки вместо интерфейса. Снимок закрывает окно между
+// загрузкой страницы и первым дошедшим ответом; когда список уже нарисован, не трогаем
+// его вовсе — свежее в памяти всегда лучше снимка с диска.
+function _restoreSessionsSnapshot(scope, error) {
+    if (!scope || scope !== currentScope) return;
+    if ($('#agent-list')?.children.length) return;
+    const snapshot = snapshotLoad(`sessions:${scope}`);
+    if (!snapshot?.data?.sessions || !snapshot.data.stats) {
+        _showErrorNotice('sessions', 'Список агентов не загрузился', error);
+        return;
+    }
+    _renderSessionsAndStats(snapshot.data.sessions, snapshot.data.stats);
+    _showStaleNotice('sessions', snapshot.ts);
+}
+
 // === API ===
 // Таймаут и число попыток — из замеров perf через канал юзера. Сломанный ответ не приходит
 // НИКОГДА: между сервером и юзером сидит посредник, который подтверждает нам 165 КБ, а до
 // браузера доносит 19–23 КБ. Каждая попытка падает с вероятностью ~0.48, три попытки
 // опускают «сломано навсегда» с 48% до ~5%.
 // Величина таймаута — цена ожидания перед повтором, и она снижена с 3.5 с до 2 с: замер с
 // ноутбука юзера через зеркало показал, что самое тяжёлое приезжает быстрее — `logs/sync`
 // 130 КБ за 0.72–1.33 с, `app.js` 382 КБ за 0.75–0.98 с, обычный API 0.2–0.7 с. Двойка
 // накрывает виденный максимум с запасом 1.5×, а «аномалия 3.5 с на холодном заходе»,
 // которую искали полдня, была этим самым таймаутом: первая попытка `wire=0 Б dur=3500`,
 // вторая `wire=2009 Б dur=228`. Повтор отработал штатно — дорого стоило ожидание.
 const _API_TIMEOUT_MS = 2000;
 const _API_ATTEMPTS = 3;
+// #197: канал юзера рвёт не передачу, а УСТАНОВКУ соединения — `conn=0.000000s`, `code=000`,
+// висит 8-12 с. Замер: 12 попыток, 10 прошли, 2 умерли наглухо (~17%). Отсюда два следствия,
+// оба противоположные тому, что подсказывает слово «медленный канал»:
+// 1) ждать дольше бесполезно. Соединение либо встаёт быстро, либо не встаёт вовсе, поэтому
+//    2 с остаются — растить бюджет значит просто дольше сидеть на заведомо мёртвой попытке;
+// 2) а вот подряд повторять вредно. ТСПУ режет пачками, и три попытки вплотную попадают в
+//    одно окно потерь. Джиттер разносит их: пауза случайна в [0, _API_RETRY_JITTER_MS],
+//    и одна дешёвая пауза меняет три коррелированные попытки на три независимые.
+// Верхняя граница выбрана так, чтобы худший случай (2 попытки × 2 с + 2 паузы) укладывался
+// в ~5.6 с — меньше, чем те 6 с, что юзер и так ждал раньше без всякого джиттера.
+const _API_RETRY_JITTER_MS = 800;
 // Мутации остаются на прежних 5 с: повтора у них нет (не идемпотентны), и работу на сервере
 // они делают ДО ответа — оборвать спавн воркера раньше значит соврать юзеру про неудачу.
 const _API_MUTATION_TIMEOUT_MS = 5000;
 // Таймаут ставится ВСЕГДА, даже когда вызывающий передал свой signal. Раньше здесь было
 // `opts.signal || AbortSignal.timeout(5000)`: свой signal (у нас это AbortController для
 // single-flight) молча отменял таймаут, и зависший ответ висел вечно. В refreshSessions
 // это фатально — `refreshInProgress` снимается в finally, который при зависании не
 // наступает никогда, и список сессий больше не обновляется до перезагрузки страницы.
 // Свой бюджет — параметром timeoutMs, а не собственным signal: одна ручка вместо двух.
 // Повторяем ТОЛЬКО GET и только обрыв: 4xx/5xx — это ответ сервера, повтор его не изменит,
 // а не-GET повторять нельзя, он не идемпотентен. Свой timeoutMs = вызывающий заявил, что
 // запрос долгий по своей природе (агрегация usage) — такой бюджет он и получает, без повторов.
 async function api(url, opts = {}) {
     const isGet = !opts.method || opts.method.toUpperCase() === 'GET';
     const attempts = (isGet && opts.timeoutMs === undefined) ? _API_ATTEMPTS : 1;
     const pollKey = opts.pollKey;
     const requestOpts = {...opts};
     delete requestOpts.pollKey;
     for (let attempt = 1; ; attempt++) {
         const timeout = AbortSignal.timeout(opts.timeoutMs ?? (isGet ? _API_TIMEOUT_MS : _API_MUTATION_TIMEOUT_MS));
@@ -6967,70 +7043,126 @@ async function api(url, opts = {}) {
                 }
                 const serverError = new Error(`${resp.status}: ${text}`);
                 serverError.status = resp.status;
                 throw serverError;
             }
             const data = await resp.json();
             _pollNoteSuccess(pollKey);
             _hideNetFailBanner(url);
             return data;
         } catch (e) {
             // Отмена вызывающим (смена scope, single-flight) — намеренная, повтор воскресил бы
             // запрос, который уже никому не нужен.
             if (opts.signal?.aborted) throw e;
             const broken = e.name === 'TimeoutError' || e.name === 'TypeError';
             const transient = broken || (Number(e.status) >= 500 && Number(e.status) < 600);
             if (!broken || attempt >= attempts) {
                 if (transient) _pollNoteFailure(pollKey, e);
                 if (broken && attempts > 1) _showNetFailBanner(url, attempts);
                 throw e;
             }
-            console.warn(`api ${url}: попытка ${attempt}/${attempts} — ${e.name}`);
+            const pause = Math.round(Math.random() * _API_RETRY_JITTER_MS);
+            console.warn(`api ${url}: попытка ${attempt}/${attempts} — ${e.name}, пауза ${pause} мс`);
+            await new Promise(resolve => setTimeout(resolve, pause));
         }
     }
 }
 
 // После исчерпания попыток юзер должен видеть причину, а не пустой экран: обрыв происходит
 // МЕЖДУ браузером и сервером, сервер при этом жив, поэтому оверлей «сервер перезагружается»
 // тут врал бы. Снимает баннер успех ТОГО ЖЕ пути, а не любой: посредник режет крупные
 // ответы, мелкие при этом ходят нормально и стёрли бы сообщение через миллисекунды —
 // замерено, в первом прогоне баннер не доживал до конца окна.
 let _netFailPath = null;
 
 function _showNetFailBanner(url, attempts) {
     _netFailPath = url.split('?')[0];
     const banner = document.getElementById('net-fail-banner');
     if (!banner) return;
     banner.classList.remove('hidden');
     banner.classList.add('flex');
     banner.innerHTML = `📡 <b>Ответ не дошёл</b> — ${escHtml(_netFailPath)}: ${attempts} попытки по ${(_API_TIMEOUT_MS / 1000).toFixed(1)} с. <span class="text-red-300/70">Обрыв между браузером и сервером; сервер отвечает. Повторим на следующем обновлении.</span>`;
 }
 
 function _hideNetFailBanner(url) {
     if (!_netFailPath || url.split('?')[0] !== _netFailPath) return;
     _netFailPath = null;
     const banner = document.getElementById('net-fail-banner');
     if (!banner) return;
     banner.classList.add('hidden');
     banner.classList.remove('flex');
 }
 
+// === Полоса «показано из кеша» / «не загрузилось» (#197) ===
+// Строится в JS, а не в шаблоне: шаблон отдаётся главным чекаутом и доехал бы до юзера
+// только рестартом. Полос две по СМЫСЛУ, а не по вкусу: «данные старые, но они есть» и
+// «данных нет вовсе» лечатся по-разному, и путать их — то же, что молчащий catch.
+function _noticeStrip() {
+    let strip = document.getElementById('stale-notice-strip');
+    if (strip) return strip;
+    strip = document.createElement('div');
+    strip.id = 'stale-notice-strip';
+    strip.className = 'flex flex-col';
+    const usageBar = document.getElementById('usage-bar');
+    if (usageBar?.parentNode) usageBar.parentNode.insertBefore(strip, usageBar);
+    else document.body.prepend(strip);
+    return strip;
+}
+
+function _noticeRow(key) {
+    const strip = _noticeStrip();
+    let row = document.getElementById(`notice-${key}`);
+    if (!row) {
+        row = document.createElement('div');
+        row.id = `notice-${key}`;
+        row.className = 'flex items-center justify-center gap-2 px-4 py-1 text-xs border-b';
+        strip.appendChild(row);
+    }
+    return row;
+}
+
+// Данные на экране есть, но они из снимка. Жёлтый: работать можно, доверять частично.
+function _showStaleNotice(key, ts) {
+    const row = _noticeRow(key);
+    row.className = 'flex items-center justify-center gap-2 px-4 py-1 text-xs border-b '
+        + 'bg-amber-500/10 border-amber-500/30 text-amber-200';
+    row.dataset.staleKey = key;
+    row.textContent = `🕒 ${key}: показано из кеша — ${snapshotAgeLabel(ts)}. Обновим, как только ответ дойдёт.`;
+}
+
+// Данных нет и подставить нечего. Красный, и с КЛАССОМ исключения: «не загрузилось»
+// без причины отправляет юзера гадать, а причины у обрыва и у 500 разные.
+function _showErrorNotice(key, what, error) {
+    const row = _noticeRow(key);
+    row.className = 'flex items-center justify-center gap-2 px-4 py-1 text-xs border-b '
+        + 'bg-red-500/10 border-red-500/30 text-red-200';
+    delete row.dataset.staleKey;
+    const reason = error?.status
+        ? `сервер ответил ${error.status}`
+        : `${error?.name || 'Error'}: ${error?.message || 'без текста'}`;
+    row.textContent = `⚠ ${what} — ${reason}`;
+}
+
+function _clearStaleNotice(key) {
+    document.getElementById(`notice-${key}`)?.remove();
+}
+
 // === Usage Bar ===
 
 // === Перезапуск Orchestra (#270) ===
 // Во время перезапуска сервер ЖИВ и отвечает на чтения — немеют только мутирующие вызовы,
 // и юзер узнавал об этом сырым служебным JSON в чате. Признак ловим на существующем пути
 // ответов (503 + `error.code = restart_pending`), своего опроса не заводим.
 let _restartPending = false;
 let _restartPendingSince = 0;
 // Перезапуск может не состояться: preflight не смог слить хвост мутаций и молча
 // переоткрыл приём, не сказав об этом ни одному клиенту. Без потолка полоса висела бы вечно.
 const _RESTART_PENDING_MAX_MS = 120000;
 
 function _restartPendingFromBody(status, text) {
     if (status !== 503) return false;
     try { return JSON.parse(text)?.error?.code === 'restart_pending'; } catch { return false; }
 }
 
 // Полосу строим в JS: шаблон отдаётся из главного чекаута и доехал бы до юзера только
 // рестартом — тем самым, про который она и рассказывает.
 function _restartBanner() {
diff --git a/app/static/js/usage.js b/app/static/js/usage.js
index 86608c2cf..da30a00eb 100644
--- a/app/static/js/usage.js
+++ b/app/static/js/usage.js
@@ -730,81 +730,100 @@ function _renderSparklines(slot, providerFilter = null) {
             const delta = button.dataset.sparkNav === 'older' ? 1 : -1;
             const idx = Math.max(0, (_sparkPeriodIdx[key] || 0) + delta);
             _sparkPeriodIdx[key] = idx;
             const loaded = Number(button.dataset.sparkPeriods) || 1;
             if (delta > 0 && idx >= loaded - 1 && _sparkHasOlder()) {
                 _sparkMessage(slot, 'Загружаю предыдущий период…', false);
                 try {
                     _sparkData = (await _sparkFetch(_sparkData[0].ts)).concat(_sparkData);
                 } catch (e) {
                     _sparkError = `${e?.name || 'Error'}: ${e?.message || 'без текста'}`;
                     console.error(`usage history chunk failed: ${_sparkError}`);
                     _sparkMessage(slot, `Предыдущий период не загрузился — ${_sparkError}`, true);
                     return;
                 }
             }
             _renderSparklines(slot, providerFilter);
         });
     });
 }
 
+// Снимок с прошлой загрузки страницы. Без него первый недошедший `/api/usage` на дырявом
+// канале давал «⚠ Usage unavailable» — не потому, что данных нет, а потому, что их негде
+// было взять: память пуста, пока не ответит сеть.
+function _restoreUsageSnapshot() {
+    if (_usageData) return;
+    const snapshot = snapshotLoad('usage');
+    if (!snapshot) return;
+    _usageData = snapshot.data;
+    _usageLastSuccessAt = snapshot.ts;
+}
+
 async function fetchUsage() {
     if (_usageFetchPromise) return _usageFetchPromise;
     _usageLastFetchStartedAt = Date.now();
     _usageFetchPromise = (async () => {
         try {
             const [usage, quotaMap] = await Promise.allSettled([
                 api('/api/usage'),
                 api('/api/usage/quota-map'),
             ]);
             _usageData = usage.status === 'fulfilled' ? usage.value : null;
             _quotaMapData = quotaMap.status === 'fulfilled' ? quotaMap.value : null;
             _usageError = usage.status !== 'fulfilled';
             if (!_usageError && quotaMap.status !== 'fulfilled') {
                 console.error(`quota-map fetch failed: ${quotaMap.reason && quotaMap.reason.message || 'unknown'}`);
             }
             if (_usageError) {
                 const reason = usage.reason || null;
                 const detail = reason instanceof Error
                     ? `${reason.name}: ${reason.message || '(no message)'}`
                     : String(reason);
                 console.error(`Usage fetch failed: ${detail}`);
             }
             _usageLastSuccessAt = Date.now();
+            snapshotSave('usage', _usageData);
         } catch (error) {
             _usageError = true;
             const detail = error instanceof Error
                 ? `${error.name}: ${error.message || '(no message)'}`
                 : String(error);
             console.error(`Usage fetch failed: ${detail}`);
+            // Своих данных ещё нет — показываем прошлые с меткой возраста вместо пустоты.
+            _restoreUsageSnapshot();
         }
     })();
     renderUsageBar();
     try {
         await _usageFetchPromise;
     } finally {
         _usageFetchPromise = null;
         renderUsageBar();
     }
 }
 
 function initUsageBar() {
+    // Сперва снимок, потом сеть: полоса заполнена с первого кадра, а свежий ответ её
+    // молча заменит. Обратный порядок показывал пустоту ровно на время запроса — на
+    // канале юзера это 2-6 с, а при провале навсегда.
+    _restoreUsageSnapshot();
+    renderUsageBar();
     fetchUsage();
     const bar = document.getElementById('usage-bar');
     if (bar) {
         bar.addEventListener('click', () => {
             if (_usageFetchPromise) return;
             if (Date.now() - _usageLastFetchStartedAt < _USAGE_CLICK_DEBOUNCE_MS) return;
             fetchUsage();
         });
     }
     document.addEventListener('visibilitychange', () => {
         if (document.visibilityState !== 'visible') return;
         const lastRefresh = Math.max(_usageLastSuccessAt, _usageLastFetchStartedAt);
         if (Date.now() - lastRefresh >= _USAGE_REFRESH_INTERVAL_MS) fetchUsage();
     });
     // Full data refresh every 2 minutes; countdown rerender every minute (no API call)
     setInterval(fetchUsage, _USAGE_REFRESH_INTERVAL_MS);
     _usageCountdownInterval = setInterval(() => {
         if (_usageData) renderUsageBar();
     }, 60000);
 }
diff --git a/app/static/js/utils.js b/app/static/js/utils.js
index 35f6739a4..50c2aa562 100644
--- a/app/static/js/utils.js
+++ b/app/static/js/utils.js
@@ -1,34 +1,87 @@
 /* utils.js — pure helpers, marked setup, autolink. Loaded before app.js. */
 
 // Client task/payment amounts use the configured billing currency; model costs are stored in USD.
 const CUR = document.body.dataset.currency || '₽';
 const MODEL_COST_CURRENCY = '$';
 const $ = (s) => document.querySelector(s);
 const taskNum = (par) => String(par || '').replace(/^[A-Z]+-/, '');
 
 const _PROVIDER_COLORS = {
     anthropic: '#fb923c', openai: '#22c55e', 'x-ai': '#e2e8f0',
     openrouter: '#a78bfa', deepseek: '#60a5fa', opencode: '#a78bfa',
     unknown: '#94a3b8',
 };
 
+// === Кеш последнего успешного ответа (#197) ===
+// Канал юзера теряет ~17% TLS-хендшейков. Провал в середине сессии переживают те панели,
+// что держат данные в памяти, а вот ЗАГРУЗКА страницы не переживает ничего: память пуста,
+// и первый же недошедший запрос даёт «нет данных» вместо интерфейса. Поэтому снимок
+// последнего успеха живёт в localStorage — он и есть то, что рисуется, пока сеть молчит.
+// Возраст снимка показывается всегда: тихо подсунуть вчерашние цифры хуже, чем не подсунуть.
+const _SNAPSHOT_PREFIX = 'orchestra_snapshot:';
+// Старше суток не показываем даже с меткой: за сутки меняется всё, включая состав агентов.
+const _SNAPSHOT_MAX_AGE_MS = 86400000;
+
+function snapshotSave(key, data) {
+    try {
+        localStorage.setItem(_SNAPSHOT_PREFIX + key, JSON.stringify({ts: Date.now(), data}));
+    } catch (e) {
+        // Переполнение квоты localStorage — не повод ронять обновление интерфейса,
+        // но и молчать нельзя: кеш просто перестал бы работать без единого слова.
+        console.warn(`snapshot ${key}: не сохранён — ${e.name}: ${e.message}`);
+    }
+}
+
+// null = снимка нет или он протух. Иначе {data, ts, ageMs}.
+function snapshotLoad(key) {
+    let raw;
+    try {
+        raw = localStorage.getItem(_SNAPSHOT_PREFIX + key);
+    } catch (e) {
+        console.warn(`snapshot ${key}: не прочитан — ${e.name}: ${e.message}`);
+        return null;
+    }
+    if (!raw) return null;
+    let parsed;
+    try {
+        parsed = JSON.parse(raw);
+    } catch (e) {
+        console.warn(`snapshot ${key}: битый JSON — ${e.name}`);
+        return null;
+    }
+    const ts = Number(parsed?.ts);
+    if (!ts || parsed?.data === undefined) return null;
+    const ageMs = Date.now() - ts;
+    if (ageMs < 0 || ageMs > _SNAPSHOT_MAX_AGE_MS) return null;
+    return {data: parsed.data, ts, ageMs};
+}
+
+// «данные от 14:32» — метка времени, а не относительный возраст: юзер и так знает,
+// который час, а «5 минут назад» надо держать в голове и пересчитывать.
+function snapshotAgeLabel(ts) {
+    const when = new Date(ts);
+    const hh = String(when.getHours()).padStart(2, '0');
+    const mm = String(when.getMinutes()).padStart(2, '0');
+    return `данные от ${hh}:${mm}`;
+}
+
 // One table owns provider labels, capacity routing and window shapes for every usage view.
 const _PROVIDER_META = {
     claude: {
         title: 'Claude Max', usageTitle: '☕ Claude Max', runtime: 'Opus · orchestrators',
         provider: 'anthropic', capacityKey: 'anthropic', tone: 'violet',
         usageAccent: '#38bdf8', windowAccent: '#38bdf8',
         historyProviders: ['anthropic'],
         windows: c => [['5h', c.five_hour, 300], ['7d', c.seven_day, 10080]],
     },
     codex: {
         title: 'Codex Pro', usageTitle: '✦ Codex Pro', compactTitle: 'Codex',
         runtime: 'Sol · workers', provider: 'openai', capacityKey: 'codex',
         tone: 'cyan', windowAccent: '#86efac',
         historyProviders: ['codex', 'codex_spark'],
         windows: c => [['Основной', c.primary], ['Вторичный', c.secondary]],
     },
     grok: {
         title: 'Grok', usageTitle: '𝕏 Grok', compactTitle: 'Grok',
         runtime: 'Grok 4.5 · workers', provider: 'x-ai', capacityKey: 'grok',
         tone: 'slate', windowAccent: '#cbd5e1',
diff --git a/docs/tasks/197/codex-review-sol.md b/docs/tasks/197/codex-review-sol.md
new file mode 100644
index 000000000..f4b528922
--- /dev/null
+++ b/docs/tasks/197/codex-review-sol.md
@@ -0,0 +1,100 @@
+# #197 — журнал попыток review
+
+## Маршрут по gate
+
+Входы decision gate, зафиксированные ДО выбора маршрута:
+
+- **Изменённые файлы:** `app/main.py`, `app/routes/system.py`,
+  `app/static/js/{utils,usage,app}.js`, `tests/test_frontend.py`,
+  `tests/test_static_compression.py`.
+- **Consumers:** каждая панель дашборда; **каждый HTTP-ответ приложения** (middleware);
+  `app/session_turns.py:144` (подменяет `_grok_usage_cache` целиком).
+- **Author model/runtime:** Opus 5 (`claude-opus-5[1m]`), Claude runtime — из metadata
+  текущей сессии, не из имени агента.
+- **AC:** пункты 1-5 задачи #197 + приёмка «эмулировать потерю ~20% запросов → интерфейс
+  остаётся заполненным», «замер запросов/мин до и после», «мутационная проверка».
+- **Named command + output:** `uv run pytest -q tests/test_frontend.py` → `72 passed`;
+  `uv run pytest -q tests/test_static_compression.py` → `6 passed`.
+
+**Risk floor: HIGH, взведён доказательно, а не объявлен автором.** Сработавшие классы:
+
+1. *shared process / message delivery* — `GZipMiddleware` встаёт на путь ВСЕХ ответов
+   процесса, который одновременно супервизирует живые CLI-сессии агентов. Поломка SSE =
+   потеря живого потока журнала агента.
+2. *lifecycle gate* — `RequestCensusMiddleware` считает in-flight потоки для дренажа при
+   рестарте, классифицируя ответ по `content-type` на кадре `http.response.start`. gzip
+   этот кадр придерживает. Сбой счётчика = рестарт не достигается либо режет ходы.
+
+Правило 4 gate: **Sol обязателен при любом размере** для shared runtime. Малый дифф и
+зелёные тесты этот floor не снижают.
+
+Правило 5: high-risk код, авторства Claude, — Sol и есть кросс-семейный ревьюер
+(автор Claude, ревьюер Codex-family), то есть независимость обеспечивалась бы им.
+
+## Попытка 1 — Sol через `codex_review`, ОТКАЗ ИНСТРУМЕНТА
+
+```
+codex_review(mode="exec", target="/tmp/t197-impl.diff", model="codex",
+             output="docs/tasks/197/codex-review-sol.md", context=<полный, с PROJECT CONTEXT>)
+```
+
+Ответ:
+
+```
+weekly_quota_blocked: New Codex worker turn blocked: Codex weekly quota is 100%
+(threshold 95%). Available provider: Claude. Stop/model change remain available.
+```
+
+Проверено до вызова по `/api/usage`: `codex primary utilization=100`,
+`resets_at=2026-08-23T07:26:39Z`.
+
+**Исход: ПОПЫТКА, раунд НЕ потрачен.** Весь вывод — сообщение об отказе инструмента и
+ничего кроме; ревьюер текста не выдавал. Классификация по таблице исходов скилла, строка
+«весь вывод — отказ инструмента и ничего кроме».
+
+Luna в этот же вызов не пробовалась отдельно: Luna и Sol идут через тот же Codex runtime
+и ту же недельную квоту, поэтому отказ детерминированно тот же. Кроме того, по правилу 4
+Luna для shared-runtime floor gate'ом не является.
+
+## Статус маршрута
+
+**`review route unavailable`** — громко, а не skip и не ложный вердикт.
+
+Оставшийся законный маршрут для этого floor — **targeted Opus cross-family review свежей
+reviewer-сессией**. Terminal worker её не поднимает: `spawn_worker` мне запрещён. Поэтому
+review handoff отправлен оркестратору (`Orchestra-orchestrator`) с точным target, AC и
+запретом реализации.
+
+Независимость на момент написания: **cross-family verdict unavailable** — дословно, как
+предписано скиллом. Ни одно утверждение в `report.md` не называет эту работу
+отревьюированной.
+
+## Adversarial self-review (замена, а не эквивалент)
+
+Скилл требует при исчерпании попыток сделать self-review вместо ревью. Он НЕ засчитывается
+как вердикт и приводится только чтобы находки не потерялись.
+
+Что я атаковал в собственной правке и с каким результатом:
+
+1. **Порядок middleware.** Первоначальный комментарий в `app/main.py` обосновывал
+   «последний = внешний» неверным рассуждением о `user_middleware[-1]`. Тест это вскрыл:
+   Starlette делает `insert(0)`, фактический стек
+   `['GZipMiddleware', 'AuthMiddleware', 'RequestCensusMiddleware']`. Размещение оказалось
+   верным, обоснование — нет; комментарий и ассерт исправлены по факту прогона.
+2. **Оракул SSE на `ASGITransport`.** Первая версия была бы КРАСНОЙ при исправном коде
+   (транспорт собирает тело целиком → один кусок). Переписано на живой сокет uvicorn и
+   добавлено контрольное плечо с принудительным сжатием, которое требует схлопывания, —
+   без него зелёный не отличал бы работающее освобождение SSE от стенда, не умеющего
+   показать буферизацию.
+3. **`failed_at` на подменённом словаре.** `_grok_usage_cache` подменяется целиком в
+   `session_turns.py` и в 4 тестах; жёсткий `["failed_at"]` уронил бы `/api/usage`.
+   Читается через `.get("failed_at", 0.0)`; те 4 теста зелёные.
+4. **Мутация только примитива читалась бы как покрытие.** Мутация `snapshotLoad` падает на
+   ТЁПЛОЙ фазе (положительный контроль), а не на проверяемой. Добавлена вторая мутация — по
+   проводке `_restoreSessionsSnapshot`, — и она падает именно на холодной проверке.
+5. **Замер gzip через `httpx` соврал** «1.0×, сжатия нет»: клиент распаковывает прозрачно.
+   Перемерено сокетом: 829 751 → 227 573 Б.
+
+Не закрыто самопроверкой и требует чужих глаз: пункты (a)-(d) из запроса выше, прежде
+всего взаимодействие gzip с дренажным счётчиком на РЕАЛЬНОМ `app.main` (мои тесты
+проверяют его на стенде с тем же порядком, но не на боевом приложении с живым рестартом).
diff --git a/docs/tasks/197/report.md b/docs/tasks/197/report.md
new file mode 100644
index 000000000..0e6d2c3fe
--- /dev/null
+++ b/docs/tasks/197/report.md
@@ -0,0 +1,217 @@
+# #197 — дашборд на канале, где ~17% запросов не доходят
+
+Диагностика — в `research.md`; здесь только сделанное и замеренное.
+Два коммита, снимаются независимо: `92a01411` (кеш и ретраи), `fd9ae9ea` (gzip).
+
+## Главный итог первым
+
+| Что | До | После |
+| --- | --- | --- |
+| Статика первой загрузки, ПО ПРОВОДУ | 829 751 Б | 227 573 Б (**3.6×**) |
+| Она же на 30 КБ/с | 27.0 с | 7.4 с |
+| `/api/usage`, 2-й и далее запрос | 0.90–1.21 с | **0.002 с** |
+| Панели при недошедшем запросе | пустые + «нет данных» | заполнены, помечены `данные от HH:MM` |
+| Запросов/мин, активная вкладка | 54.0 | 54.0 (не трогал, см. ниже) |
+
+## 1. Кеш последнего успешного ответа (главный приоритет)
+
+`snapshotSave` / `snapshotLoad` / `snapshotAgeLabel` в `utils.js` — снимок в
+`localStorage`, потолок возраста сутки. Подключено к `usage`, `sessions`+`stats`,
+`orchestrators`, `models`.
+
+Почему именно `localStorage`, а не память: в памяти данные провал уже переживали
+(`_usageData` при провале не стирался, полоса честно писала «данные от N мин назад»).
+Не переживала **загрузка страницы** — а на канале с 17% потерь это самое частое место
+встречи с обрывом: там разом идут `models`, `orchestrators`, `sessions`, `stats`,
+`usage`. Первый провал давал `⚠ Usage unavailable` и пустой список агентов не потому,
+что данных нет, а потому, что их негде было взять.
+
+Порядок в `initUsageBar` тоже важен: снимок восстанавливается ДО первого запроса, и
+полоса заполнена с первого кадра. Раньше пустота висела всё время запроса — на канале
+юзера это 2–6 с, а при провале навсегда.
+
+## 2. Честная индикация
+
+Полоса «показано из кеша — данные от HH:MM» (жёлтая) и «не загрузилось + класс
+исключения» (красная) — два РАЗНЫХ состояния, и лечатся они по-разному. Строятся в JS
+и вставляются перед `#usage-bar`: шаблон отдаётся главным чекаутом и доехал бы до юзера
+только рестартом.
+
+Три молчащих `catch {}` теперь называют причину:
+`_loadModelsNow`, `_loadOrchestratorsNow`, `_fetchAgentContextNow`.
+Контекст при провале показывает прошлое значение с пометкой `(не обновлено)` —
+прочерк неотличим от «агент только что создан».
+
+## 3. Ретраи
+
+Добавлен джиттер `[0, 800]` мс между попытками. Бюджет попытки НЕ увеличен, и это
+осознанно против первого впечатления: постановка говорит «2 с мало на плохом канале»,
+но её же замер говорит обратное — обрыв происходит на УСТАНОВКЕ соединения
+(`conn=0.000000s`, `code=000`), то есть соединение либо встаёт быстро, либо не встаёт
+вовсе. Растить бюджет = дольше сидеть на заведомо мёртвой попытке. Настоящая дыра была
+в другом: три попытки шли вплотную, а ТСПУ режет пачками — все три попадали в одно окно
+потерь. Джиттер делает их независимыми. Худший случай ≈5.6 с против прежних 6 с.
+
+## 4. Серверный кеш — найдена причина, а не симптом
+
+`/api/usage` держал 0.9–1.2 с при 300-секундном кеше провайдеров и локальном
+`/api/models` за 0.002 с.
+
+Гипотеза «виноват синхронный скан истории в `usage_exchange_rate()`» **опровергнута
+замером** (0.002–0.003 с), а не оставлена вероятной. Разложение по слагаемым:
+
+```
+agents_cost: 0.006s   voice: 0.001s
+grok fetch:  0.877s RAISED PermissionError: token_expired
+grok cache ts: 0.0
+```
+
+Токен Grok протух, поход к провайдеру падает за 0.877 с, и ветка провала **обнуляла**
+`ts = 0.0`. Обнулённый `ts` не проходит проверку TTL никогда → следующий запрос снова
+идёт в сеть → снова падает. **TTL для сбойного провайдера не действовал по построению.**
+
+Фикс: отдельный `failed_at` с окном 60 с. `data=None, ts=0` сохранены намеренно —
+«данных по Grok нет» должно оставаться видимым, подставлять вчерашние проценты нельзя.
+Кешируется только САМ ФАКТ провала. Окно короче успеха, чтобы починка токена подхватилась
+за минуту, а не за пять. Замер после: 1-й вызов 4.86 с (идёт в сеть, как и раньше),
+2–5-й — 0.002 с.
+
+`_grok_usage_cache` читается через `.get("failed_at", 0.0)`: словарь целиком подменяется
+извне (`session_turns.py:144` и четыре теста), жёсткий ключ уронил бы `/api/usage` на
+чужой подмене.
+
+Сам протухший токен НЕ чинил — это #267, и правка не притворяется, что чинит.
+
+### `/api/stats` — кеш не нужен, замерено
+
+Просили добавить его к пункту 4. Не добавил, потому что кешировать нечего:
+`get_stats()` целиком — **0.005 с** при 138 583 строках `logs` и 442 сессиях, тёплый
+роут 0.014–0.021 с (8 подряд). Холодный горб, из-за которого он разово показывал 0.27–4.45 с,
+— это page cache и прогрев процесса; серверный кеш от него не спасает, потому что ПЕРВЫЙ
+запрос всё равно холодный. Класть кеш ради 5 мс — это код, который надо сопровождать,
+без выигрыша.
+
+## 5. Холодный старт: горб в статике, а не в API
+
+Замер первой загрузки: API суммарно **68 КБ** (`sessions` 11 КБ, `orchestrators` 18 КБ,
+`tm/tasks` 39 КБ, все по 0.035–0.044 с), статика — **814 КБ**, из них `app.js` 435 КБ.
+Отдавалась несжатой: `curl --compressed` возвращал те же 434 627 байт, заголовка
+`content-encoding` в ответе не было вовсе.
+
+`app.add_middleware(GZipMiddleware, minimum_size=1024)` — по сокету **829 751 → 227 573 Б,
+3.6×**; на 30 КБ/с 27.0 → 7.4 с. На дырявом канале вчетверо меньше байт — это ещё и
+вчетверо меньше шансов поймать обрыв посреди передачи.
+
+**Мерить пришлось сокетом.** Первая попытка через `httpx` показала «1.0×, сжатия нет»:
+клиент распаковывает прозрачно, и `content-length` в его ответе — это размер РАСПАКОВАННОГО
+тела. Замер врал, код был исправен.
+
+«Рендер частями» не делал: кеширование уже верное (`VersionedStatic` отдаёт
+`max-age=31536000, immutable` на версионных URL), значит цена платится ОДИН раз на версию.
+Переделывать первый рендер ради второго по величине слагаемого, когда первое снимается
+однострочником, — не тот размен.
+
+**Порядок middleware.** gzip добавлен последним и потому стоит самым ВНЕШНИМ
+(`add_middleware` делает `insert(0)`; проверено прогоном:
+`['GZipMiddleware', 'AuthMiddleware', 'RequestCensusMiddleware']`). Так и надо: gzip
+придерживает кадр `http.response.start` до первого куска тела, а `RequestCensusMiddleware`
+именно на этом кадре читает `content-type`, чтобы отличить поток от обычного ответа —
+изнутри gzip сдвигал бы счётчик дренажа.
+
+Оба потоковых маршрута проверены:
+- `/api/sessions/*/stream` (SSE) — не сжимается вовсе,
+  `DEFAULT_EXCLUDED_CONTENT_TYPES = ('text/event-stream',)` в Starlette 1.1.0;
+- `/api/report_bug` (`text/markdown`, конечный генератор) — сжимается, тело доезжает
+  целиком, проверено побайтным сравнением с ожидаемым.
+
+## 6. Частота опроса — намеренно не тронута
+
+54.0 запроса/мин на активной вкладке, 0 на скрытой. **До и после одинаково**, и это
+не упущение: развела их #301, а постановка прямо запрещает рефакторить работающее.
+`git diff main` по `_pollRegister`, `_ORCH_REFRESH_MS`, `setInterval` и
+`_USAGE_REFRESH_INTERVAL_MS` — пусто.
+
+Цифра посчитана по расписанию (базовые интервалы поллеров), а не прогоном, потому что
+прогонный замер #301 недостоверен — см. ниже.
+
+## Мутационные проверки
+
+Каждая: `cp F F.bak` → мутация → прогон → `mv F.bak F` → `touch` → зелёный повтор.
+Маркер печатался ДО и ПОСЛЕ.
+
+| # | Мутация | Результат | Маркер до/после |
+| --- | --- | --- | --- |
+| 1 | `snapshotLoad` всегда возвращает `null` | 🔴 red | 1 → 0 |
+| 2 | `_restoreSessionsSnapshot` выходит сразу (`if (true) return`) | 🔴 red на ХОЛОДНОЙ фазе | 1 → 0 |
+| 3 | строка `add_middleware(GZipMiddleware …)` убрана | 🔴 red | 1 → 0 |
+
+Зелёный повтор после каждого отката: `3 passed`, `1 passed`, `6 passed`.
+
+Мутация 1 упала на положительном контроле (тёплая фаза), мутация 2 — на самой холодной
+проверке, ради которой тест и написан. Обе нужны: первая доказывает, что примитив жив,
+вторая — что жива ПРОВОДКА к прод-пути. Мутация только примитива читалась бы как
+покрытие и им не была.
+
+## Оракулы
+
+- `test_dashboard_survives_lossy_channel_from_snapshot` — два захода в одном browser
+  context (иначе `localStorage` негде проверять). Первый всё получает, второй теряет
+  `sessions`/`stats`/`usage`/`orchestrators` через `route.abort()` — это `TypeError` в
+  fetch, ровно то, что видит браузер при обрыве TLS. Проверяет: агенты на месте, usage
+  не пуст, есть пометка «из кеша» и метка времени. Гард `assert lossy["dropped"]` — без
+  него тест мог бы зеленеть, ничего не уронив.
+- `test_dashboard_shows_error_class_when_nothing_cached` — пустой `localStorage`, нечего
+  показать → красная полоса с КЛАССОМ исключения.
+- `test_api_retry_spaces_attempts_with_jitter`.
+- `test_static_compression.py`, 6 штук. Ключевой — `test_sse_arrives_incrementally…`:
+  проверяет не заголовок, а что события РАЗНЕСЕНЫ во времени.
+
+**Контрольное плечо к SSE-оракулу.** `test_control_arm_forced_compression_does_collapse_the_stream`
+гоняет тот же поток с принудительным сжатием (исключения сняты) и требует, чтобы разброс
+СХЛОПНУЛСЯ. Без него зелёный ничего не значил бы: первая версия теста стояла на
+`ASGITransport`, который собирает тело целиком и отдаёт ОДИН кусок при любом коде —
+такая проверка мерила транспорт вместо сжатия и была бы одинаковой при исправном
+освобождении SSE и при полностью сломанном. Поэтому оракул поднимает настоящий uvicorn
+на живом сокете.
+
+## Прогоны
+
+- `tests/test_frontend.py` — **72 passed** (69 прежних + 3 моих).
+- `tests/test_static_compression.py` — **6 passed**.
+- Usage-семейство (`codex_usage`, `usage_snapshot`, `usage_readiness`, `turn_usage`,
+  `grok_usage_frontend`, `antigravity_usage_frontend`) — **55 passed, 6 skipped**.
+
+### Чужое, не чинил
+
+- `tests/test_api.py` — **18 failed**. Проверено запуском на ЧИСТОМ `main` в отдельном
+  worktree: тот же результат, `diff` списков падений пуст. Все 18 предсуществуют.
+- `test_quota_headroom_frontend.py::test_free_week_looks_exactly_like_today` — падает и
+  на базе ветки, и на `main` (`HEAD == main == ad1697ef`).
+- `test_dashboard_polling_equivalent_twelve_minutes_before_after` (#301) — **флакует, и
+  это не моя правка**. На моей ветке 2 из 3 красных; на чистом `main`, где тест сравнивает
+  main САМ С СОБОЙ, — тоже 2 из 3 красных. Его собственный шум больше измеряемого эффекта:
+  `before_total` гуляет 1456–2242 на одном и том же коде. Поэтому цифру запросов/мин я
+  взял из расписания, а не из него.
+
+### Откат в тестовом слое
+
+`_usageFreshnessHtml` я сперва дополнил меткой возраста в ветке «обновление…». Это
+уронило существующий `test_usage_refreshes_on_click_and_stale_tab_return_without_request_storm`,
+который ждёт дословное `обновление…`. Правку СНЯЛ, тест не трогал: разрешения на
+редактирование тестового слоя у меня нет, а честность и так обеспечивают ветки `stale`
+и `_usageError`.
+
+## Пре-мортем: чем это может сломаться
+
+1. **Снимок переживает смену данных на сервере** (агента убили, а он в списке).
+   Закрыто потолком возраста в сутки и тем, что снимок рисуется ТОЛЬКО когда живых
+   данных нет (`#agent-list` пуст), а любой успешный ответ его затирает.
+2. **Снимок от чужого scope.** Ключ `sessions:<scope>`, плюс проверка
+   `scope !== currentScope` на входе в восстановление.
+3. **Переполнение `localStorage`.** `snapshotSave` ловит и пишет причину в консоль;
+   обновление интерфейса не падает.
+4. **gzip ломает SSE.** Закрыто оракулом на живом сокете + контрольным плечом; плюс
+   отдельный тест на константу Starlette, чтобы обновление библиотеки ломало тест, а не
+   живые потоки.
+5. **`failed_at` роняет `/api/usage` на подменённом словаре.** Закрыто `.get(...)`;
+   4 существующих теста подменяют этот словарь без нового поля и зелены.
diff --git a/docs/tasks/197/research.md b/docs/tasks/197/research.md
new file mode 100644
index 000000000..ddf2d87fc
--- /dev/null
+++ b/docs/tasks/197/research.md
@@ -0,0 +1,107 @@
+# #197 — что на самом деле пустеет и почему
+
+Замеры сделаны 20.08.2026 в этом worktree против живого сервера на :8888 и чтением
+текущего кода ветки. Задача #301 (visibility-aware polling) уже в main и владеет
+координатором опроса — часть пунктов постановки ею закрыта, это выяснено до правок.
+
+## Что УЖЕ есть в main (правку не требует)
+
+| Пункт постановки | Состояние | Где |
+| --- | --- | --- |
+| 1. Ретраи с backoff | Частично. `_pollDelay` даёт экспоненту до 120 с **между циклами опроса**. Внутри `api()` — 3 попытки подряд по 2.0 с, без джиттера и без роста бюджета | `app.js:916-928`, `app.js:6856-6912` |
+| 2. Кеш последнего ответа | Только для usage и только **в памяти** (`_usageData` переживает провал fetch). После перезагрузки страницы — пусто | `usage.js:3-9, 145-166` |
+| 3. Снижение частоты опроса | Сделано в #301: hidden-вкладка останавливает расписание, coalescing по ключу | `app.js:960-1000` |
+| 4. Серверный кеш `/api/usage` | Есть, TTL 300 с, переживает рестарт (пишется на диск) | `system.py:413-444, 805-857` |
+| 5. Честная индикация | Частично: `_showNetFailBanner` отличает обрыв от ответа сервера | `app.js:6920-6940` |
+
+## Дефект 1 — `/api/usage` 0.9 с при живом кеше: провал провайдера ОТКЛЮЧАЕТ TTL
+
+Замер живого сервера, пять подряд:
+
+```
+0.935 0.918 1.208 0.976 0.879  (все 200)
+```
+
+Для сравнения на той же машине: `/api/models` 0.0016 с, `/api/stats` 0.27 с.
+
+Гипотеза «виноват `usage_exchange_rate()` — синхронный скан 72 ч истории на каждом
+запросе» **опровергнута прямым замером**: 0.003/0.002/0.002 с. Отвергнута, а не
+оставлена «вероятной».
+
+Настоящая причина найдена разложением ответа по слагаемым:
+
+```
+agents_cost: 0.006s
+voice:       0.001s
+grok token present: True
+grok fetch:  0.877s RAISED PermissionError: token_expired
+grok cache ts: 0.0
+```
+
+`_read_grok_token()` находит токен (файл на месте), поход к провайдеру падает
+`PermissionError: token_expired` за 0.877 с, и в ветке провала (`system.py:909-914`)
+кеш Grok **обнуляется**: `ts = 0.0`. Обнулённый `ts` не проходит проверку
+`now - ts < _USAGE_CACHE_TTL` никогда, поэтому следующий запрос снова идёт в сеть —
+и снова падает. TTL для сбойного провайдера не действует по построению.
+
+То есть 0.88 с из 0.92 с — это гарантированно-провальный сетевой вызов, повторяемый
+на КАЖДЫЙ запрос дашборда. На дырявом канале юзера этот запрос ещё и держит одно из
+шести HTTP/1.1-соединений почти секунду.
+
+Правка целится сюда: **негативный результат провайдера тоже кешируется** (короче, чем
+успех), а не выбрасывается. Grok-токен при этом остаётся протухшим — чинить его не
+моя задача (#267 про это), и правка не должна притворяться, что чинит.
+
+## Дефект 2 — переживает провал только usage, и только до перезагрузки
+
+`_usageData` живёт в модульной переменной. Провал fetch данные не стирает
+(`usage.js:684-694` пишет `_usageError = true`, но `_usageData` не трогает) — и полоса
+честно рисует «данные от N мин назад». Это работает.
+
+Ломается ровно там, где юзер и жалуется: **на загрузке страницы**. Первый `fetchUsage()`
+провалился → `_usageData === null` → `⚠ Usage unavailable`. Показать нечего, потому что
+предыдущий успешный ответ нигде не сохранён. На канале с 17% потерь загрузка страницы —
+самое частое место встречи с провалом: там разом идут `models`, `orchestrators`,
+`sessions`, `stats`, `usage`.
+
+То же и с панелями `Model/Role/Cost/Branch/Scope` (`#ai-*`, `dashboard.html:278-282`):
+они заполняются из `/api/sessions`. Провал → `renderAgentList` не вызывается → панель
+остаётся с прочерками из `app.js:2526-2530`.
+
+## Дефект 3 — три молчащих `catch {}`
+
+```
+app.js:1187  _loadModelsNow          } catch {}
+app.js:1658  _loadOrchestratorsNow   } catch {}
+app.js:2645  _fetchAgentContextNow   } catch {}
+```
+
+Прямо запрещено в `CLAUDE.md` («каждая ветка ошибки обязана показать класс исключения
+или ответ сервера») и это пункт 5 постановки. Юзер видит пустой селектор моделей и
+пустые вкладки оркестраторов без единого слова о причине.
+
+## Дефект 4 — таймаут 2 с не подходит каналу, где рвётся УСТАНОВКА соединения
+
+Комментарий у `_API_TIMEOUT_MS` (`app.js:6845-6856`) обосновывает 2 с замером
+**скорости передачи**: тяжёлое приезжает за 0.72–1.33 с. Это верно и к делу не
+относится. Замер постановки #197 — про другое: обрыв происходит на TLS-хендшейке
+(`conn=0.000000s`, `code=000`), соединение висит 8–12 с и не встаёт.
+
+Следствие: три попытки по 2 с = 6 с гарантированного провала, после чего баннер
+«Ответ не дошёл». При этом ЖИВОЕ соединение встаёт быстро — значит правильная
+стратегия не «ждать дольше», а «бросать быстро и пробовать снова, разнося попытки
+джиттером». Джиттера сейчас нет вовсе: три попытки идут вплотную, и если ТСПУ режет
+пачкой, все три попадают в одно окно.
+
+## Что из этого делаю
+
+1. Кеш последнего успешного ответа в `localStorage` для того, что рисует интерфейс
+   при загрузке: usage, список оркестраторов, список сессий+stats, models. Возраст
+   показывается явно. Это пункт 2 и главный приоритет.
+2. Джиттер между попытками в `api()` + отдельный, больший бюджет первой попытки.
+3. Кеширование НЕГАТИВНОГО ответа провайдера в `/api/usage` — снимает 0.88 с с
+   каждого запроса.
+4. Три `catch {}` получают текст ошибки на экран.
+
+Частоту опроса (пункт 3) #301 уже развела; трогать её сверх этого — рефакторинг
+работающего, чего постановка прямо запрещает. Цифры до/после всё равно меряю.
diff --git a/docs/workers/fix-dashboard-resilience.md b/docs/workers/fix-dashboard-resilience.md
new file mode 100644
index 000000000..35c768862
--- /dev/null
+++ b/docs/workers/fix-dashboard-resilience.md
@@ -0,0 +1,51 @@
+# fix-dashboard-resilience — личная память
+
+## Меряешь СЖАТИЕ — только сырой сокет, никогда не httpx/requests
+
+`httpx` (и `requests`) распаковывают `content-encoding: gzip` прозрачно, а
+`response.headers['content-length']` в их ответе — размер УЖЕ РАСПАКОВАННОГО тела.
+Замер печатает «1.0×, сжатия нет» на полностью исправном коде, причём заголовок
+`content-encoding: gzip` при этом видно — то есть данные выглядят
+самопротиворечиво, и легко решить, что сломан код.
+
+Рабочий способ (#197): `socket.create_connection` + руками
+`GET ... HTTP/1.1 / Accept-Encoding: gzip / Connection: close`, считать `len(data)`
+из `recv`. Дало 829 751 → 227 573 Б (3.6×) там, где httpx показывал 1.0×.
+
+## Оракул на ИНКРЕМЕНТАЛЬНОСТЬ потока не строится на ASGITransport
+
+`httpx.ASGITransport` собирает тело целиком перед отдачей: `aiter_bytes` даёт ОДИН
+кусок независимо от того, буферизует приложение поток или нет. Тест «события
+разнесены во времени» на нём КРАСНЫЙ при исправном коде — мерит транспорт, а не
+предмет. Нужен настоящий сокет: `uvicorn.Server` в треде, `port=0`, ждать
+`server.started and server.servers[0].sockets`, брать порт из `getsockname()[1]`.
+
+И обязательно контрольное плечо, которое требует, чтобы поток СХЛОПНУЛСЯ при
+принудительном сжатии, — иначе зелёный не отличает «освобождение SSE работает» от
+«стенд в принципе не умеет показать буферизацию».
+
+## Порядок middleware в Starlette: `user_middleware` хранится ВНЕШНИМ-ПЕРВЫМ
+
+`add_middleware` делает `insert(0)`. Добавленный последним стоит в списке ПЕРВЫМ и
+обрабатывает запрос раньше всех. Проверено прогоном: при порядке добавления
+Census → Auth → GZip стек читается
+`['GZipMiddleware', 'AuthMiddleware', 'RequestCensusMiddleware']`.
+Я написал ассерт на `stack[-1]` по интуиции и получил красный — интуиция здесь
+ровно обратна реальности.
+
+## В этом репо: провал провайдера, обнуляющий `ts`, ОТКЛЮЧАЕТ TTL
+
+Шаблон `except: cache["ts"] = 0.0` встречался в `app/routes/system.py` и означал,
+что сбойный провайдер ходит в сеть на КАЖДЫЙ запрос: обнулённый `ts` не проходит
+`now - ts < TTL` никогда. Стоило 0.88 с на каждом `/api/usage`. Лечится отдельным
+ключом `failed_at` с более коротким окном; `data=None` при этом сохранять, если
+«данных нет» — осмысленное состояние для UI.
+
+Словари этих кешей подменяются целиком извне (`session_turns.py`, тесты) → новые
+ключи читать только через `.get(key, default)`, иначе `KeyError` на чужой подмене.
+
+## `git diff main HEAD` в отставшей ветке показывает ЧУЖИЕ удаления
+
+Мой дифф «удалял» `docs/tasks/192/` и `docs/workers/cdn-vendors-*`, которых я не
+трогал: ветка отстала от main. Для ревью и для оценки объёма брать
+`git diff $(git merge-base main HEAD) HEAD -- <свои пути>`.
diff --git a/tests/test_frontend.py b/tests/test_frontend.py
index 09ccc05be..3afadeb1f 100644
--- a/tests/test_frontend.py
+++ b/tests/test_frontend.py
@@ -3611,20 +3611,216 @@ def test_mobile_voice_input_records_transcribes_and_cancels(dashboard_browser: B
     assert b'filename="voice.m4a"' in requests["body"]
     assert page.evaluate("window.__voiceTrackStops") == 1
 
     page.locator("#voice-btn").click()
     page.wait_for_function("() => $('#voice-controls')?.dataset.state === 'recording'")
     page.locator("#voice-cancel-btn").click()
     page.wait_for_function("() => $('#voice-controls')?.dataset.state === 'idle'")
     assert requests["transcribe"] == 1
     assert page.locator("#chat-input").input_value() == "Надиктованный текст"
     assert page.evaluate("window.__voiceTrackStops") == 2
 
     page.evaluate(
         """() => Object.defineProperty(navigator, 'mediaDevices', {
             configurable: true,
             value: {getUserMedia: async () => { throw new DOMException('denied', 'NotAllowedError'); }},
         })"""
     )
     page.locator("#voice-btn").click()
     expect(page.locator("#voice-error")).to_contain_text("Доступ к микрофону запрещён")
     context.close()
+
+
+# ─────────────────────────────────────────────────────────────────────────────
+# #197 — интерфейс переживает канал, где часть запросов не доходит
+# ─────────────────────────────────────────────────────────────────────────────
+
+_LOSSY_SCOPE = "/tmp/fe-scope"
+_LOSSY_SESSIONS = [
+    {
+        "id": "fe-orch-id", "name": "fe-orch", "scope": _LOSSY_SCOPE, "status": "idle",
+        "model": "claude-opus-5[1m]", "role": "orchestrator", "cost_usd": 1.25,
+        "branch": "main", "is_orchestrator": True,
+    },
+    {
+        "id": "fe-worker-id", "name": "fe-worker", "scope": _LOSSY_SCOPE, "status": "idle",
+        "model": "claude-opus-5[1m]", "role": "worker", "cost_usd": 0.5,
+        "branch": "task-197/fe-worker", "parent_name": "fe-orch",
+    },
+]
+_LOSSY_STATS = {"active": 0, "total_sessions": 2, "total_cost_usd": 1.75}
+_LOSSY_ORCHS = [
+    {"id": "fe-orch-id", "name": "fe-orch", "scope": _LOSSY_SCOPE, "status": "idle"},
+]
+_LOSSY_USAGE = {
+    "anthropic": {
+        "five_hour": {"utilization": 41, "resets_at": None},
+        "seven_day": {"utilization": 62, "resets_at": None},
+    },
+    "codex": {}, "grok": None, "orchestra": {}, "voice_cost_usd": 0.0,
+    "subscription_cost": "",
+}
+
+
+def _lossy_payload(path: str):
+    """Тело ответа для путей первой загрузки. Неизвестный путь — пустой объект."""
+    if path == "/api/sessions":
+        return _LOSSY_SESSIONS


## Later history of the touched files on main (after this commit)

181 later commits touch these paths; the first 40 (oldest first):
b68ace219 2026-08-20 #202: бабл веб-поиска показывает запрос и результат
5165bcc02 2026-08-21 чат открывается на последних сообщениях и не ждёт зеркало
5e7163191 2026-08-21 чат держится низа всю начальную загрузку
71532403e 2026-08-21 потолок узлов чата 500 -> 200, и обрезка только когда юзер внизу
3985ef548 2026-08-21 открытие чата: 11 запросов -> 0-2, страница берётся одним запросом
ac08becdd 2026-08-21 чат: одна отрисовка вместо достройки экрана кусками, минус 4 механизма
5c77969b3 2026-08-21 таймаут API 2 с -> 4 с: бюджет сгорал в очереди, а не в ответе
47b28811e 2026-08-21 откат таймаута на 2 с и отказ от опроса скрытой панели файлов
0d8208a77 2026-08-21 опрос дашборда: фазовый сдвиг и 304 на /api/sessions
fa3e993db 2026-08-23 Allow fresh model switches without handoff
a7c1c369d 2026-08-22 #369: #369: render harness tool calls as proper chat bubbles
c74d0d75b 2026-08-22 #368: #368: Phase 1 — исследование источников счётчика запросов OpenRouter (гибрид: локальный счёт + /activity)
b2ee5b1bc 2026-08-22 фронт знает про рантайм harness — пара к PROVIDER_METADATA
dc09cc236 2026-08-22 Squashed commits: - #366: research + plan + 22 red tests (model catalog, two-level availability) - #366: plan review section + behavioral red reasons (no external reviewer: quota) - #366: T1 — kv_set/kv_delete writers + two-level availability flags (overlay, read-through kv) - #366: T2 — OpenRouter catalog fetch/normalize/kv-cache + registration re-applied inside every registry rebuild - #366: T3 — two-level enforcement: /api/models dashboard filter, agents gate in _create_session_locked, change-model via=dashboard|mcp, bounded unknown-model error; CONTRACT CHANGE: derived views are now a superset of SELECTABLE_MODEL_SPECS (test_derived_views_carry_exactly_the_declared_specs rewritten as subset assertions) - WIP #366: T4 catalog HTTP API written (GET/POST/PATCH /api/models/catalog*), tests not yet run; TODO: run test_catalog_api.py, mutation, T5 frontend+Playwright probe, T6 - #366: T4 — /api/models/catalog GET(union registry+cache)/refresh POST/flags PATCH; dropped counter surfaced; mutation: PATCH-echo-without-persist caught - #366: T5 — catalog modal screen: search/free/tools/image filters, two toggles per model, refresh button; picker untouched - #366: T5 — live Playwright probe evidence (probe-catalog.png): worktree js/css substituted on :8888, catalog modal renders 18 models / 36 toggles, search filters, clone-frozen screenshot - #366: T6 — live-agent shoulders: resume surface intact after both flags off, new spawn rejected with actionable message, switch-away allowed; mutation: message without screen name caught - #366: report + personal memory - #366: изоляция тестов — снимок и восстановление реестра моделей между тестами; kv-чтение флагов/кеша fail-soft при отсутствии таблицы - #366: route surface snapshot — +/api/models/catalog{,/refresh,/flags} (intentional new public endpoints)
1f0a526d3 2026-08-23 #225: group chat photo batches into compact galleries
c6022d4ad 2026-08-23 fix: open usage details without refreshing the bar
aa33578e2 2026-08-23 #234: #234: add red acceptance tests
b460149d4 2026-08-23 #379: #379: research socket restart failure
81a1c60f8 2026-08-24 #380: #380: research durable send acceptance
9d2627281 2026-08-24 Merge origin/main into main (2026-08-24 sync)
9f946a601 2026-08-24 #309: #309: freeze phase2 deletion oracles
e7d521de5 2026-08-24 fix: preserve generated images across chat switches
e26dcde85 2026-08-24 fix: switch Codex models in place
b09118919 2026-08-24 #338: #338: remove unreachable deleteOrchestrator
4d58b176a 2026-08-24 refactor: remove OpenCode runtime
2fa666288 2026-08-24 #337: #337: add durable primary TG file receipts
ebb38764a 2026-08-25 #365: harden free OpenRouter harness
7717ef880 2026-08-25 #349: WIP #349: implement agent-only knowledge pending oracle decision
0ce9151a0 2026-08-25 #361: research live knowledge activation
a2c45a484 2026-08-25 #396: restore weekly limits card and reuse renderer
4c1dfe9c7 2026-08-25 #396: close limits renderer and unify window count
33660cfd5 2026-08-25 #397: add final answer timeline navigation
bf1d013c4 2026-08-25 #365: send dashboard voice asynchronously
e7772a32b 2026-08-25 #364: зеркало логов держит 100 строк на сессию; секреты в своих логах не блокируют работу
00ab036d9 2026-08-25 #364: обрезать чат и при чтении истории — узлы копились без предела
13aceafe3 2026-08-25 рестарт: убрать блокировку ввода и починить сторож без pidfd_open
382bd22e8 2026-08-25 #364: freeze red oracle
46b02836a 2026-08-25 Merge remote-tracking branch 'origin/main'
0349fc14c 2026-08-26 Repair Orchestra startup and dashboard resilience
589528d1a 2026-08-26 Improve Orchestra runtime stability and live status

## Patches of the first 8 later commits, restricted to the touched paths (each capped at 150 lines)

### b68ace219 #202: бабл веб-поиска показывает запрос и результат

diff --git a/app/static/js/app.js b/app/static/js/app.js
index 0baa02cc2..e2ef50f53 100644
--- a/app/static/js/app.js
+++ b/app/static/js/app.js
@@ -5086,14 +5086,12 @@ function addChatEntry(type, content, ts, anchor, payload) {
         if (isWebSearchCall) {
             try {
                 const d = JSON.parse(body);
                 setCodexToolTitle(header, 'Web search', '🌐');
                 header.style.color = '#38bdf8';
-                if (rawName === 'WebSearch') {
-                    div.dataset.isCodexWebSearch = '1';
-                    updateCodexWebSearchActivity(div, codexWebSearchSpec(d));
-                }
+                div.dataset.isCodexWebSearch = '1';
+                updateCodexWebSearchActivity(div, codexWebSearchSpec(d));
                 if (d.model) {
                     const badge = document.createElement('span');
                     badge.textContent = d.model;
                     badge.style.cssText = 'font-size:9px;padding:1px 6px;border-radius:9999px;border:1px solid #38bdf8;color:#38bdf8;opacity:0.8;vertical-align:middle;margin-left:6px';
                     header.appendChild(badge);
@@ -5721,14 +5719,20 @@ function addChatEntry(type, content, ts, anchor, payload) {
         const preview = _hasMore ? _resultLines.slice(0, _RESULT_PREVIEW).join('\n') : linked;
         const full = _hasMore ? linked : null;
 
         if (lastTool) {
             if (lastTool.dataset.isCodexWebSearch) {
-                updateCodexWebSearchActivity(lastTool, codexWebSearchSpec(content));
-                delete lastTool.dataset.lastTool;
-                addTimestamp(lastTool, ts);
-                return;
+                // Codex шлёт результатом ту же структуру с action/queries — ею обновляем шапку.
+                // Встроенный WebSearch и MCP-поиск отдают ТЕКСТ: spec=null, и его надо
+                // отрисовать обычным телом результата, а не проглотить ранним return.
+                const resultSpec = codexWebSearchSpec(content);
+                if (resultSpec) {
+                    updateCodexWebSearchActivity(lastTool, resultSpec);
+                    delete lastTool.dataset.lastTool;
+                    addTimestamp(lastTool, ts);
+                    return;
+                }
             }
             if (lastTool.dataset.isSpawnWorker) {
                 const hdr = lastTool.querySelector('.flex.items-center');
                 if (hdr) setCodexToolTitle(hdr, `${lastTool.dataset.workerName || 'Worker'} spawned`);
                 delete lastTool.dataset.lastTool;
### 5165bcc02 чат открывается на последних сообщениях и не ждёт зеркало

diff --git a/app/static/js/app.js b/app/static/js/app.js
index e2ef50f53..5579725c3 100644
--- a/app/static/js/app.js
+++ b/app/static/js/app.js
@@ -491,12 +491,16 @@ function _restoreChatAnchor(key) {
     }
     const divider = document.createElement('div');
     divider.className = 'chat-unread-divider';
     divider.textContent = 'Непрочитанные';
     chat.insertBefore(divider, firstUnread);
-    divider.scrollIntoView({block: 'start'});
-    _chatHasNewBelow = true;
+    // Разделитель — МЕТКА для того, кто листает вверх, а не цель прыжка. Прыжок к нему
+    // открывал чат на сообщениях многодневной давности, и свежие «дорисовывались ниже»
+    // (жалоба юзера 21.08). Открываем внизу, у последнего сообщения; кнопка «вниз»
+    // при этом не нужна — ниже ничего не осталось.
+    _scrollChatToBottom();
+    _chatHasNewBelow = false;
     _syncChatJumpButton();
 }
 
 function _scheduleChatInitialSettle() {
     const key = _chatPositionKey();
@@ -518,10 +522,11 @@ function _scheduleChatInitialSettle() {
 const _sessionIds = {};  // _chatPositionKey() -> session.id, заполняется в renderAgentList и _storeSync
 const _CHAT_PAGE = 100;  // столько строк показываем при заходе — как и раньше при limit=100
 // Столько строк рисуем в ПЕРВОМ кадре; остальное — после него. Двадцать — это ровно то,
 // что раньше лежало в зеркале и давало чат за 871 мс против 1186 мс на сотне строк.
 const _CHAT_FIRST_PAINT = 20;
+const _CHAT_MIRROR_DEADLINE = 250;  // сколько ждём IndexedDB, прежде чем идти в сеть
 // Порция добора истории — И по строкам, И по байтам. Одних строк мало: замер по живой БД
 // дал на 25 строках от 5.2 до 46.6 КБ gzip в разных чатах, потому что размер сообщения
 // гуляет на три порядка. Бюджет 24 КБ content держит худшую порцию в пределах ~10 КБ по
 // проводу у всех проверенных агентов — ниже порога, на котором посредник у юзера рвёт ответ.
 const _CHAT_CHUNK = 25;
@@ -2309,12 +2314,25 @@ async function _showChatFor(name, scope) {
     $('#chat').innerHTML = '';
     chatLogs[name] = {lastId: 0, firstId: null, initialCount: 0};
     scrollAfterLoad = true;
     _chatLoading = true;
     try {
-        const sid = await _storeSessionId(scope, name);
-        let rows = sid ? await _storeRead(sid, _CHAT_PAGE) : [];
+        // Зеркало быстрее сети, но только пока оно свободно: холодная синхронизация
+        // (/api/logs/sync?after_id=0 — 2.23 с на замере 21.08) держит readwrite-транзакцию,
+        // и наши чтения стоят за ней в очереди. Замер того же дня: переключение на агента
+        // без зеркала = 3.08 с пустого чата при том, что /api/sessions/<name>/logs отвечает
+        // за 10–20 мс. Поэтому ждём зеркало ограниченно и уходим в сеть, не дожидаясь.
+        const mirror = (async () => {
+            const id = await _storeSessionId(scope, name);
+            return {id, rows: id ? await _storeRead(id, _CHAT_PAGE) : []};
+        })();
+        const hit = await Promise.race([
+            mirror,
+            new Promise((res) => setTimeout(() => res(null), _CHAT_MIRROR_DEADLINE)),
+        ]);
+        const sid = hit ? hit.id : null;
+        let rows = hit ? hit.rows : [];
         // Обрезанная строка раньше делала всю историю непригодной: пометить её было нечем,
         // и битую картинку показывать нельзя. Теперь у обрезки есть видимый маркер и кнопка
         // «загрузить целиком» (#74), а сервер режет тем же потолком, что и зеркало, — так что
         // обрезка перестала быть поводом перекачивать страницу целиком.
         const fromStore = rows.length > 0;
diff --git a/tests/test_frontend.py b/tests/test_frontend.py
index 3afadeb1f..1eb089eb2 100644
--- a/tests/test_frontend.py
+++ b/tests/test_frontend.py
@@ -2973,14 +2973,14 @@ def test_chat_restores_last_read_boundary_only_when_unread(
     divider = page.locator(".chat-unread-divider")
     expect(divider).to_have_count(1)
     assert page.evaluate(
         """() => Number($('.chat-unread-divider').nextElementSibling.dataset.chatLogId)"""
     ) == read_id + 1
-    expect(page.locator("#chat-jump-latest")).to_be_visible()
-    expect(page.locator("#chat-jump-latest")).to_have_text("↓ Новые ниже")
-    page.locator("#chat-jump-latest").click()
-    page.wait_for_function("() => _chatAtBottom()")
+    # Чат открывается ВНИЗУ, у последнего сообщения: разделитель — метка для того, кто
+    # листает вверх, а не цель прыжка (жалоба юзера 21.08 «показывает далёкие сообщения»).
+    # Кнопки «вниз» при этом быть не должно — ниже ничего не осталось.
+    assert page.evaluate("() => _chatAtBottom()")
     expect(page.locator("#chat-jump-latest")).to_be_hidden()
 
     # If the saved boundary fell outside the loaded window, start at the first
     # available unread record instead of cascading through older history.
     page.evaluate(
### 5e7163191 чат держится низа всю начальную загрузку

diff --git a/app/static/js/app.js b/app/static/js/app.js
index 5579725c3..58afc2b67 100644
--- a/app/static/js/app.js
+++ b/app/static/js/app.js
@@ -535,10 +535,16 @@ const _CHAT_CHUNK = 25;
 // всей истории каждой сессии, не по последней сотне) — 14.5 КБ, сессий сверх порога ноль.
 const _CHAT_CHUNK_BYTES = 16000;
 // Страховка от бесконечного добора. Двадцать, а не двенадцать: с меньшим бюджетом порций
 // нужно больше, и на двенадцати два самых тяжёлых чата (bizdev, payroll) не добирали сотню.
 const _CHAT_MAX_CHUNKS = 20;
+// Пока идёт НАЧАЛЬНАЯ загрузка чата, низ держим безусловно. История дорисовывается
+// порциями ВВЕРХ (первый кадр 20 строк, потом добор до 100 по 25), и каждая порция
+// меняет scrollHeight; решение «остаться внизу» принималось по _chatAtBottom, а он
+// на промежуточном кадре легко отвечает «нет» — юзер видел, как сообщения сперва
+// появляются сверху, а бабли доезжают ниже (жалоба 21.08, второй заход).
+let _chatInitialLoad = false;
 
 // === Зеркало журнала в IndexedDB (#8) ===
 // Строки logs неизменяемы (в app/db.py ровно один INSERT и оптовый DELETE по возрасту,
 // ни одного UPDATE), поэтому сохранённая строка не может стать неверной — только исчезнуть.
 // Отсюда вся инвалидация сводится к трём правилам: чистим сессии, которых больше нет,
@@ -2259,11 +2265,12 @@ function _prependHistory(name, scope, rows) {
             meta.initialCount++;
         }
     } finally { _replayingHistory = false; }
     // Дорисовка уходит ВВЕРХ. Юзер внизу — держим его внизу; читает выше — компенсируем
     // прирост высоты, чтобы текст под курсором не уехал (иначе добор из #38 сам себе рывок).
-    if (wasAtBottom) chat.scrollTop = chat.scrollHeight;
+    // Начальная загрузка — всегда низ: там «выше» ещё некому читать.
+    if (wasAtBottom || _chatInitialLoad) chat.scrollTop = chat.scrollHeight;
     else chat.scrollTop = desiredTop + (chat.scrollHeight - heightBefore);
     updateLoadMoreBtn();
     return rows.length;
 }
 
@@ -2312,10 +2319,11 @@ async function _fetchHistory(name, scope) {
 async function _showChatFor(name, scope) {
     if (!name || !scope) return;
     $('#chat').innerHTML = '';
     chatLogs[name] = {lastId: 0, firstId: null, initialCount: 0};
     scrollAfterLoad = true;
+    _chatInitialLoad = true;
     _chatLoading = true;
     try {
         // Зеркало быстрее сети, но только пока оно свободно: холодная синхронизация
         // (/api/logs/sync?after_id=0 — 2.23 с на замере 21.08) держит readwrite-транзакцию,
         // и наши чтения стоят за ней в очереди. Замер того же дня: переключение на агента
@@ -2347,13 +2355,20 @@ async function _showChatFor(name, scope) {
         const head = rows.length > _CHAT_FIRST_PAINT ? rows.slice(0, -_CHAT_FIRST_PAINT) : [];
         _renderHistory(name, head.length ? rows.slice(-_CHAT_FIRST_PAINT) : rows);
         connectSSE(true);
         // Остаток страницы и добор с сервера идут строго по очереди: и то и другое
         // вставляет НАД первой строкой, а серверные строки старше остатка зеркала.
-        _afterPaint(() => {
+        _afterPaint(async () => {
             _prependHistory(name, scope, head);
-            _completeChatPage(name, scope);   // и после промаха зеркала: _fetchHistory берёт одну порцию
+            await _completeChatPage(name, scope);   // и после промаха зеркала: _fetchHistory берёт одну порцию
+            // Страница добрана — начальная фаза кончилась. Снимаем флаг только здесь:
+            // добор идёт дольше, чем таймер _scheduleChatInitialSettle, и снятие по
+            // таймеру возвращало прыжки на последних порциях.
+            if (name === selectedAgent && scope === currentScope) {
+                _chatInitialLoad = false;
+                if (_chatAtBottom()) $('#chat').scrollTop = $('#chat').scrollHeight;
+            }
         });
         return fromStore;
     } finally {
         // Обязательно снимаем даже на раннем выходе: иначе восстановительный connectSSE
         // окажется заблокирован навсегда и умерший поток никто не поднимет.
### 71532403e потолок узлов чата 500 -> 200, и обрезка только когда юзер внизу

diff --git a/app/static/js/app.js b/app/static/js/app.js
index 58afc2b67..e16d7d011 100644
--- a/app/static/js/app.js
+++ b/app/static/js/app.js
@@ -1,7 +1,12 @@
 // Cap DOM nodes to avoid memory growth during long agent sessions
-const MAX_CHAT_NODES = 500;
+// Потолок узлов в живой вкладке. 500 держалось «на глаз» и для чата оркестратора значит
+// ≈109 000 px: замер 21.08 — 100 сообщений его журнала это 21 861 px, а за 12 часов
+// набегает 554 строки, то есть вкладка упирается в потолок за полдня и дальше тормозит
+// на каждом кадре. 200 узлов ≈ 44 000 px при той же странице входа в 100 сообщений;
+// старшее уходит из DOM, но не из истории — оно возвращается кнопкой «загрузить ещё».
+const MAX_CHAT_NODES = 200;
 function fmtCost(v) { v = Number(v) || 0; if (v === 0) return MODEL_COST_CURRENCY + '0.00'; if (v < 0.01) return MODEL_COST_CURRENCY + v.toFixed(4); return MODEL_COST_CURRENCY + v.toFixed(2); }
 const _MODEL_COLORS = {
     'claude-opus-5[1m]': '#d8b4fe',
     'claude-sonnet-5[1m]': '#38bdf8', 'claude-haiku-4-5': '#4ade80',
     'claude-fable-5[1m]': '#fb923c', 'gpt-5.5': '#f472b6', 'gpt-5.4': '#f472b6',
@@ -222,10 +227,18 @@ let _followPinRaf = null;
 // Поднимается обработчиками ввода и означает «следующее событие scroll — от юзера».
 let _userScrolled = false;
 function _pinChatBottom(chat) {
     chat.scrollTop = chat.scrollHeight;
 }
+
+// Срезать самые старые узлы. Режем ТОЛЬКО когда юзер внизу и следует за потоком:
+// иначе кнопка «загрузить ещё» бессмысленна — добранная история исчезала бы от первого
+// же нового сообщения, и текст под курсором прыгал бы вверх на высоту срезанного.
+function _trimChatNodes(chat) {
+    if (!chat || !_chatFollow) return;
+    while (chat.children.length > _chatTrimLimit) chat.removeChild(chat.firstChild);
+}
 function _keepPinnedIfFollowing() {
     if (!_chatFollow || _followPinRaf) return;
     _followPinRaf = requestAnimationFrame(() => {
         _followPinRaf = null;
         const chat = $('#chat');
@@ -4630,11 +4643,11 @@ function addChatEntry(type, content, ts, anchor, payload) {
         }
         const line = buildCompactToolLine(type, content, ts, payload);
         const wasAtBottom = _chatAtBottom(chat);
         _insert(line);
         // Trim oldest nodes to cap memory — loses old history but prevents unbounded DOM growth
-        while (chat.children.length > _chatTrimLimit) chat.removeChild(chat.firstChild);
+        _trimChatNodes(chat);
         if (type === 'tool') _adoptOrphanResults(chat, line.dataset.toolUseId);
         if (!anchor && !_insertedBeforeStream && wasAtBottom) chat.scrollTop = chat.scrollHeight;
         return;
     }
 
@@ -6769,11 +6782,11 @@ function addChatEntry(type, content, ts, anchor, payload) {
 
     addCopyBtn(div, content);
     addTimestamp(div, ts);
     const wasAtBottom = _chatAtBottom(chat);
     _insert(div);
-    while (chat.children.length > _chatTrimLimit) chat.removeChild(chat.firstChild);
+    _trimChatNodes(chat);
     if (type === 'tool') _adoptOrphanResults(chat, div.dataset.toolUseId);
     if (!anchor && !_insertedBeforeStream && wasAtBottom) chat.scrollTop = chat.scrollHeight;
 }
 
 
### 3985ef548 открытие чата: 11 запросов -> 0-2, страница берётся одним запросом

diff --git a/app/static/js/app.js b/app/static/js/app.js
index e16d7d011..75940b8d3 100644
--- a/app/static/js/app.js
+++ b/app/static/js/app.js
@@ -545,13 +545,18 @@ const _CHAT_MIRROR_DEADLINE = 250;  // сколько ждём IndexedDB, пре
 const _CHAT_CHUNK = 25;
 // 16 000 Б, а не 24 000: base64 не сжимается вообще, и порция из обрезанных блобов на 24 КБ
 // сырых даёт 19 КБ по проводу — выше порога. С 16 000 худшая порция ВО ВСЕЙ БД (прогон по
 // всей истории каждой сессии, не по последней сотне) — 14.5 КБ, сессий сверх порога ноль.
 const _CHAT_CHUNK_BYTES = 16000;
-// Страховка от бесконечного добора. Двадцать, а не двенадцать: с меньшим бюджетом порций
-// нужно больше, и на двенадцати два самых тяжёлых чата (bizdev, payroll) не добирали сотню.
-const _CHAT_MAX_CHUNKS = 20;
+// Сколько ДОБОРНЫХ запросов допустимо после первого. Каждый стоит круга по сети, а у юзера
+// канал в другую страну: прежние 20 проходов по 25 строк давали 11 запросов на открытие и
+// 2.40 с при латентности 200 мс (замер 21.08). Теперь запрашиваем сразу _CHAT_PAGE, и
+// сервер отдаёт столько, сколько влезает в _CHAT_CHUNK_BYTES — на живом журнале это 35
+// строк за проход, то есть сотня набирается за три. Тяжёлый чат наберёт меньше сотни;
+// это осознанный размен: остаток доступен кнопкой «загрузить ещё», а секунды ожидания при
+// каждом открытии — нет.
+const _CHAT_REFILL_PASSES = 3;
 // Пока идёт НАЧАЛЬНАЯ загрузка чата, низ держим безусловно. История дорисовывается
 // порциями ВВЕРХ (первый кадр 20 строк, потом добор до 100 по 25), и каждая порция
 // меняет scrollHeight; решение «остаться внизу» принималось по _chatAtBottom, а он
 // на промежуточном кадре легко отвечает «нет» — юзер видел, как сообщения сперва
 // появляются сверху, а бабли доезжают ниже (жалоба 21.08, второй заход).
@@ -2221,23 +2226,30 @@ function _renderHistory(agent, rows) {
     $('#chat').scrollTop = $('#chat').scrollHeight;
     _scheduleChatInitialSettle();
     _syncChatJumpButton();
 }
 
-// Добор страницы до _CHAT_PAGE порциями по _CHAT_CHUNK и запись добранного в зеркало:
-// следующий заход к этому же агенту снова бесплатный. Порции последовательные — каждая
-// следующая опирается на firstId предыдущей. Сотню строк одним ответом не берём: это
-// 27.1 КБ, а канал юзера рвёт крупные ответы (#70, #72).
+// Добор страницы до _CHAT_PAGE и запись добранного в зеркало: следующий заход к этому же
+// агенту снова бесплатный.
+//
+// НЕДОСТАЮЩЕЕ БЕРЁТСЯ ОДНИМ ЗАПРОСОМ, а не порциями по _CHAT_CHUNK. Прежнее «сотню строк
+// одним ответом не берём: это 27.1 КБ» (#70, #72) не подтвердилось замером 21.08: сервер
+// режет каждое сообщение по max_bytes, поэтому 100 строк весят 6 063 байта после gzip
+// против 16 598 сырых у 25 — четыре порции не экономят ничего, а стоят четырёх RTT.
+// Настоящая цена была видна только на канале юзера: частичное попадание в зеркало
+// запускало цепочку из ОДИННАДЦАТИ запросов подряд, и открытие чата занимало 2.40 с при
+// латентности 200 мс. Цикл оставлен на два прохода: ответ может оказаться короче
+// запрошенного из-за бюджета байт, и тогда второй проход добирает остаток.
 // Предзагружать зеркало на все сессии вместо этого нельзя: инкрементальная синхронизация
 // (after_id > 0) tail ИГНОРИРУЕТ, дозаполнить уже заведённое зеркало она не может, а
 // холодная предзагрузка стоила 145.5 КБ по проводу ради строк, из которых рисуется ~5%.
 async function _completeChatPage(name, scope) {
     let added = 0;
-    for (let i = 0; i < _CHAT_MAX_CHUNKS; i++) {
+    for (let i = 0; i < _CHAT_REFILL_PASSES; i++) {
         const meta = chatLogs[name];
         if (!meta || !meta.firstId) return added;
-        const need = Math.min(_CHAT_PAGE - (meta.initialCount || 0), _CHAT_CHUNK);
+        const need = _CHAT_PAGE - (meta.initialCount || 0);
         if (need <= 0) return added;
         let older;
         try {
             const q = new URLSearchParams({scope, before_id: String(meta.firstId), limit: String(need),
                                            max_bytes: String(_CHAT_CHUNK_BYTES), cap: String(_STORE_CAP)});
@@ -2252,11 +2264,10 @@ async function _completeChatPage(name, scope) {
         if (!Array.isArray(older) || !older.length) return added;
         if (!_prependHistory(name, scope, older)) return added;     // юзер ушёл к другому агенту
         _storePut(older);
         added += older.length;
     }
-    console.warn(`[chat] добор истории ${name} остановлен на ${_CHAT_MAX_CHUNKS} порциях — добрано ${added} строк`);
     return added;
 }
 
 // Дорисовать старые строки НАД уже показанными. Один владелец на два случая: остаток
 // страницы из зеркала (первый кадр рисует только хвост) и добор с сервера.
@@ -2307,13 +2318,20 @@ async function _storePut(rows) {
     } catch (e) { _storeDisable('не пишется в IndexedDB', e); }
 }
 
 // Промах зеркала: тянем историю обычным маршрутом. Он отдаёт application/json, который
 // nginx жмёт, — те же 100 сообщений едут в 5 раз меньшим объёмом, чем через SSE (D1).
+//
+// СТРАНИЦА БЕРЁТСЯ ОДНИМ ЗАПРОСОМ. Раньше здесь стоял _CHAT_CHUNK (25), а остальные три
+// четверти добирал _completeChatPage — то есть открытие чата стоило ЧЕТЫРЁХ круговых
+// задержек подряд. Локально это незаметно (6 мс на порцию), а у юзера канал до сервера в
+// другой стране, и цена открытия равна 4×RTT. Замер 21.08 на живом журнале: limit=100 —
+// 22 мс и 6 063 байта после gzip, limit=25 — 16 598 байт сырых, потому что max_bytes режет
+// каждое сообщение и четыре порции почти не экономят трафик. Один запрос строго лучше.
 async function _fetchHistory(name, scope) {
     try {
-        const q = new URLSearchParams({scope, before_id: String(2 ** 31 - 1), limit: String(_CHAT_CHUNK),
+        const q = new URLSearchParams({scope, before_id: String(2 ** 31 - 1), limit: String(_CHAT_PAGE),
                                        max_bytes: String(_CHAT_CHUNK_BYTES), cap: String(_STORE_CAP)});
         const rows = await api(`/api/sessions/${encodeURIComponent(name)}/logs?${q}`);
         if (!Array.isArray(rows)) return [];
         // Обязательно в зеркало: эти строки СТАРШЕ watermark, инкремент их уже не принесёт
         // никогда. Без этой записи в зеркале осталась бы дыра ровно на самом свежем куске
@@ -2370,11 +2388,15 @@ async function _showChatFor(name, scope) {
         connectSSE(true);
         // Остаток страницы и добор с сервера идут строго по очереди: и то и другое
         // вставляет НАД первой строкой, а серверные строки старше остатка зеркала.
         _afterPaint(async () => {
             _prependHistory(name, scope, head);
-            await _completeChatPage(name, scope);   // и после промаха зеркала: _fetchHistory берёт одну порцию
+            // Добираем ТОЛЬКО когда страница действительно неполная: зеркало отдало меньше
+            // _CHAT_PAGE. После сетевого пути добирать нечего — _fetchHistory уже привёз
+            // всю страницу одним запросом, а лишний вызов стоил ещё одного круга по сети
+            // и всегда возвращал пустоту в конце журнала.
+            if (rows.length < _CHAT_PAGE) await _completeChatPage(name, scope);
             // Страница добрана — начальная фаза кончилась. Снимаем флаг только здесь:
             // добор идёт дольше, чем таймер _scheduleChatInitialSettle, и снятие по
             // таймеру возвращало прыжки на последних порциях.
             if (name === selectedAgent && scope === currentScope) {
                 _chatInitialLoad = false;
### ac08becdd чат: одна отрисовка вместо достройки экрана кусками, минус 4 механизма

diff --git a/app/static/js/app.js b/app/static/js/app.js
index 75940b8d3..62a20fe03 100644
--- a/app/static/js/app.js
+++ b/app/static/js/app.js
@@ -534,35 +534,24 @@ function _scheduleChatInitialSettle() {
 // повторного и после F5. Один источник, одна инвалидация.
 const _sessionIds = {};  // _chatPositionKey() -> session.id, заполняется в renderAgentList и _storeSync
 const _CHAT_PAGE = 100;  // столько строк показываем при заходе — как и раньше при limit=100
 // Столько строк рисуем в ПЕРВОМ кадре; остальное — после него. Двадцать — это ровно то,
 // что раньше лежало в зеркале и давало чат за 871 мс против 1186 мс на сотне строк.
-const _CHAT_FIRST_PAINT = 20;
 const _CHAT_MIRROR_DEADLINE = 250;  // сколько ждём IndexedDB, прежде чем идти в сеть
-// Порция добора истории — И по строкам, И по байтам. Одних строк мало: замер по живой БД
-// дал на 25 строках от 5.2 до 46.6 КБ gzip в разных чатах, потому что размер сообщения
-// гуляет на три порядка. Бюджет 24 КБ content держит худшую порцию в пределах ~10 КБ по
-// проводу у всех проверенных агентов — ниже порога, на котором посредник у юзера рвёт ответ.
-const _CHAT_CHUNK = 25;
-// 16 000 Б, а не 24 000: base64 не сжимается вообще, и порция из обрезанных блобов на 24 КБ
-// сырых даёт 19 КБ по проводу — выше порога. С 16 000 худшая порция ВО ВСЕЙ БД (прогон по
-// всей истории каждой сессии, не по последней сотне) — 14.5 КБ, сессий сверх порога ноль.
-const _CHAT_CHUNK_BYTES = 16000;
-// Сколько ДОБОРНЫХ запросов допустимо после первого. Каждый стоит круга по сети, а у юзера
-// канал в другую страну: прежние 20 проходов по 25 строк давали 11 запросов на открытие и
-// 2.40 с при латентности 200 мс (замер 21.08). Теперь запрашиваем сразу _CHAT_PAGE, и
-// сервер отдаёт столько, сколько влезает в _CHAT_CHUNK_BYTES — на живом журнале это 35
-// строк за проход, то есть сотня набирается за три. Тяжёлый чат наберёт меньше сотни;
-// это осознанный размен: остаток доступен кнопкой «загрузить ещё», а секунды ожидания при
-// каждом открытии — нет.
-const _CHAT_REFILL_PASSES = 3;
-// Пока идёт НАЧАЛЬНАЯ загрузка чата, низ держим безусловно. История дорисовывается
-// порциями ВВЕРХ (первый кадр 20 строк, потом добор до 100 по 25), и каждая порция
-// меняет scrollHeight; решение «остаться внизу» принималось по _chatAtBottom, а он
-// на промежуточном кадре легко отвечает «нет» — юзер видел, как сообщения сперва
-// появляются сверху, а бабли доезжают ниже (жалоба 21.08, второй заход).
-let _chatInitialLoad = false;
+// Ниже этого числа строк зеркало считается непригодным и страница берётся сетью.
+// Замер 21.08: у редко открываемого агента зеркало отдавало 16 узлов — формально
+// «попадание», фактически пустой экран.
+const _CHAT_MIN_FROM_STORE = 40;
+// Потолок на СУММАРНЫЙ content ответа (db.py:1741). 16 000 Б выбирались под старую схему,
+// где страница набиралась четырьмя порциями и каждая должна была влезть под порог, на
+// котором посредник у юзера рвал ответ (~19 КБ по проводу, #70/#72). Теперь запрос ровно
+// один, и бюджет задаёт не размер порции, а сколько сообщений вообще попадёт на экран: при
+// 16 000 приходило 35 строк, то есть ~15 узлов после схлопывания пар «вызов+результат», и
+// чат выглядел пустым. 32 000 при замеренном соотношении (11 637 Б content -> 6 063 Б gzip)
+// даёт ~16 КБ по проводу — под тем же порогом. Увидишь в консоли «история не пришла» —
+// это первый кандидат на откат.
+const _CHAT_CHUNK_BYTES = 32000;
 
 // === Зеркало журнала в IndexedDB (#8) ===
 // Строки logs неизменяемы (в app/db.py ровно один INSERT и оптовый DELETE по возрасту,
 // ни одного UPDATE), поэтому сохранённая строка не может стать неверной — только исчезнуть.
 // Отсюда вся инвалидация сводится к трём правилам: чистим сессии, которых больше нет,
@@ -571,11 +560,11 @@ const _STORE_DB = 'orchestra';
 // Холодная синхронизация НЕ тянет строки: tail=0 — только карта сессий и отметка.
 // Замер (#72, по проводу через домен): tail=20 на все сессии стоил 145.5 КБ, а рисовалось
 // из них ~5% — хвост открытого агента. Причём даже при попадании в зеркало страница чата
 // всё равно добиралась с сервера (в зеркале 20 строк, показываем 100), так что предзагрузка
 // экономила не запрос, а один кадр отрисовки. Зеркало наполняется тем, что юзер открыл
-// (_storePut в _fetchHistory/_completeChatPage) и живёт между заходами — F5 по-прежнему
+// (_storePut в _fetchHistory) и живёт между заходами — F5 по-прежнему
 // рисует открытого агента без сети.
 const _STORE_TAIL = 0;
 const _STORE_CAP = 16384;       // байт на сообщение; блоб со скриншотом приедет обрезанным
 const _STORE_SYNC_MS = 15000;
 let _storeDb = null;            // IDBDatabase | null (null = хранилища нет, работаем как раньше)
@@ -2210,66 +2199,49 @@ function selectOrchestrator(name, scope) {
 // addChatEntry зовут из десятка мест и протаскивать признак через все — шум.
 let _replayingHistory = false;
 
 function _renderHistory(agent, rows) {
     const meta = chatLogs[agent] = {lastId: 0, firstId: null, initialCount: 0};
+    const chat = $('#chat');
+    // Страница рисуется ЦЕЛИКОМ и показывается один раз. Пока идёт цикл, контейнер скрыт:
+    // сотня узлов вставляется десятками мутаций, браузер успевает показать промежуточные
+    // кадры, и юзер видит, как чат достраивается сверху вниз (жалоба 21.08). Скрытый
+    // контейнер занимает то же место — раскладка не прыгает, просто не показываем черновик.
+    if (chat) chat.style.visibility = 'hidden';
     _replayingHistory = true;
     try {
     for (const l of rows) {
         addChatEntry(l.type, l.content, l.ts, null, l);
         if (!Number.isFinite(l.id)) continue;
         if (l.id > meta.lastId) meta.lastId = l.id;
         if (meta.firstId === null || l.id < meta.firstId) meta.firstId = l.id;
         meta.initialCount++;
     }
-    } finally { _replayingHistory = false; }
+    } finally {
+        _replayingHistory = false;
+        if (chat) { chat.scrollTop = chat.scrollHeight; chat.style.visibility = ''; }
+    }
     updateLoadMoreBtn();
     $('#chat').scrollTop = $('#chat').scrollHeight;
     _scheduleChatInitialSettle();
     _syncChatJumpButton();
 }
 
 // Добор страницы до _CHAT_PAGE и запись добранного в зеркало: следующий заход к этому же
 // агенту снова бесплатный.
 //
-// НЕДОСТАЮЩЕЕ БЕРЁТСЯ ОДНИМ ЗАПРОСОМ, а не порциями по _CHAT_CHUNK. Прежнее «сотню строк
+// НЕДОСТАЮЩЕЕ БЕРЁТСЯ ОДНИМ ЗАПРОСОМ, а не порциями по 25. Прежнее «сотню строк
 // одним ответом не берём: это 27.1 КБ» (#70, #72) не подтвердилось замером 21.08: сервер
 // режет каждое сообщение по max_bytes, поэтому 100 строк весят 6 063 байта после gzip
 // против 16 598 сырых у 25 — четыре порции не экономят ничего, а стоят четырёх RTT.
 // Настоящая цена была видна только на канале юзера: частичное попадание в зеркало
 // запускало цепочку из ОДИННАДЦАТИ запросов подряд, и открытие чата занимало 2.40 с при
 // латентности 200 мс. Цикл оставлен на два прохода: ответ может оказаться короче
 // запрошенного из-за бюджета байт, и тогда второй проход добирает остаток.
 // Предзагружать зеркало на все сессии вместо этого нельзя: инкрементальная синхронизация
 // (after_id > 0) tail ИГНОРИРУЕТ, дозаполнить уже заведённое зеркало она не может, а
 // холодная предзагрузка стоила 145.5 КБ по проводу ради строк, из которых рисуется ~5%.
-async function _completeChatPage(name, scope) {
-    let added = 0;
-    for (let i = 0; i < _CHAT_REFILL_PASSES; i++) {
-        const meta = chatLogs[name];
-        if (!meta || !meta.firstId) return added;
-        const need = _CHAT_PAGE - (meta.initialCount || 0);
-        if (need <= 0) return added;
-        let older;
-        try {
-            const q = new URLSearchParams({scope, before_id: String(meta.firstId), limit: String(need),
-                                           max_bytes: String(_CHAT_CHUNK_BYTES), cap: String(_STORE_CAP)});
-            older = await api(`/api/sessions/${encodeURIComponent(name)}/logs?${q}`);
-        } catch (e) {
-            // Молчать нельзя: юзер увидит короткий чат и не поймёт, почему он короткий.
-            console.warn(`[chat] добор истории для ${name} не удался: ${e?.name}: ${e?.message}`);
-            return added;
-        }
-        // Пустой ответ — единственный признак конца журнала. «Строк меньше, чем просили»
-        // им больше не является: столько же могло срезать бюджетом байт.
-        if (!Array.isArray(older) || !older.length) return added;
-        if (!_prependHistory(name, scope, older)) return added;     // юзер ушёл к другому агенту
-        _storePut(older);
-        added += older.length;
-    }
-    return added;
-}
 
 // Дорисовать старые строки НАД уже показанными. Один владелец на два случая: остаток
 // страницы из зеркала (первый кадр рисует только хвост) и добор с сервера.
 function _prependHistory(name, scope, rows) {
     if (name !== selectedAgent || scope !== currentScope) return 0;  // успели уйти к другому
@@ -2290,11 +2262,11 @@ function _prependHistory(name, scope, rows) {
         }
     } finally { _replayingHistory = false; }
     // Дорисовка уходит ВВЕРХ. Юзер внизу — держим его внизу; читает выше — компенсируем
### 5c77969b3 таймаут API 2 с -> 4 с: бюджет сгорал в очереди, а не в ответе

diff --git a/app/static/js/app.js b/app/static/js/app.js
index 62a20fe03..017a7d96b 100644
--- a/app/static/js/app.js
+++ b/app/static/js/app.js
@@ -7033,11 +7033,22 @@ function _restoreSessionsSnapshot(scope, error) {
 // ноутбука юзера через зеркало показал, что самое тяжёлое приезжает быстрее — `logs/sync`
 // 130 КБ за 0.72–1.33 с, `app.js` 382 КБ за 0.75–0.98 с, обычный API 0.2–0.7 с. Двойка
 // накрывает виденный максимум с запасом 1.5×, а «аномалия 3.5 с на холодном заходе»,
 // которую искали полдня, была этим самым таймаутом: первая попытка `wire=0 Б dur=3500`,
 // вторая `wire=2009 Б dur=228`. Повтор отработал штатно — дорого стоило ожидание.
-const _API_TIMEOUT_MS = 2000;
+// 21.08: поднято до 4 с. Двойка выбиралась под сценарий #197 — «канал рвёт УСТАНОВКУ
+// соединения, ждать дольше бесполезно». Замер с ноутбука в тот же день показал, что этот
+// сценарий сейчас не действует: установка занимает 0.0001 с через туннель и 0.13 с через
+// домен, обрывов 0 из 24, шесть параллельных запросов проходят за 0.42 с. Зато действует
+// другое: дашборд опрашивает 7 живых scope, за 8 секунд уходит 19 запросов, и при шести
+// соединениях HTTP/1.1 запрос ждёт СЛОТА, а не ответа. Замер самого юзера в его браузере:
+// самый долгий ответ 526 мс при десятке TimeoutError — бюджет сгорал в очереди. Отвалившись,
+// запрос ретраится и снова занимает слот, то есть очередь разгоняла сама себя. Успешные
+// ответы приходят за 0.2–0.5 с, поэтому больший бюджет не удлиняет обычную работу — он
+// выключает ложные срабатывания. Вернётся сценарий #197 (conn=0.000000s, code=000) — это
+// первый кандидат на откат.
+const _API_TIMEOUT_MS = 4000;
 const _API_ATTEMPTS = 3;
 // #197: канал юзера рвёт не передачу, а УСТАНОВКУ соединения — `conn=0.000000s`, `code=000`,
 // висит 8-12 с. Замер: 12 попыток, 10 прошли, 2 умерли наглухо (~17%). Отсюда два следствия,
 // оба противоположные тому, что подсказывает слово «медленный канал»:
 // 1) ждать дольше бесполезно. Соединение либо встаёт быстро, либо не встаёт вовсе, поэтому
### 47b28811e откат таймаута на 2 с и отказ от опроса скрытой панели файлов

diff --git a/app/static/js/app.js b/app/static/js/app.js
index 017a7d96b..2031e3f83 100644
--- a/app/static/js/app.js
+++ b/app/static/js/app.js
@@ -6899,10 +6899,15 @@ async function _refreshContainer(container, dirPath) {
 }
 
 async function refreshOpenFolders() {
     const tree = $('#file-tree');
     if (!tree || !currentScope) return;
+    // Панель файлов свёрнута — опрашивать нечего. Запрос всё равно уходил каждые 10 с и
+    // занимал одно из ШЕСТИ соединений браузера, из которых одно навсегда держит SSE.
+    // Замер 21.08: сам туннель прогоняет 20 параллельных запросов за 0.43 с — узкое место
+    // не канал, а число одновременных запросов от вкладки.
+    if (tree.offsetParent === null) return;
     await _refreshContainer(tree, currentScope);
     const containers = tree.querySelectorAll('.file-children:not(.hidden)');
     for (const container of containers) {
         const dirItem = container.previousElementSibling;
         if (!dirItem?.dataset?.path) continue;
@@ -7033,22 +7038,24 @@ function _restoreSessionsSnapshot(scope, error) {
 // ноутбука юзера через зеркало показал, что самое тяжёлое приезжает быстрее — `logs/sync`
 // 130 КБ за 0.72–1.33 с, `app.js` 382 КБ за 0.75–0.98 с, обычный API 0.2–0.7 с. Двойка
 // накрывает виденный максимум с запасом 1.5×, а «аномалия 3.5 с на холодном заходе»,
 // которую искали полдня, была этим самым таймаутом: первая попытка `wire=0 Б dur=3500`,
 // вторая `wire=2009 Б dur=228`. Повтор отработал штатно — дорого стоило ожидание.
-// 21.08: поднято до 4 с. Двойка выбиралась под сценарий #197 — «канал рвёт УСТАНОВКУ
+// 21.08: пробовали 4 с — юзер сообщил, что стало ХУЖЕ, и это сходится с механикой:
+// когда узкое место — ОЧЕРЕДЬ за шестью соединениями, больший бюджет заставляет
+// повисший запрос дольше удерживать слот. Откачено. Двойка выбиралась под сценарий #197 — «канал рвёт УСТАНОВКУ
 // соединения, ждать дольше бесполезно». Замер с ноутбука в тот же день показал, что этот
 // сценарий сейчас не действует: установка занимает 0.0001 с через туннель и 0.13 с через
 // домен, обрывов 0 из 24, шесть параллельных запросов проходят за 0.42 с. Зато действует
 // другое: дашборд опрашивает 7 живых scope, за 8 секунд уходит 19 запросов, и при шести
 // соединениях HTTP/1.1 запрос ждёт СЛОТА, а не ответа. Замер самого юзера в его браузере:
 // самый долгий ответ 526 мс при десятке TimeoutError — бюджет сгорал в очереди. Отвалившись,
 // запрос ретраится и снова занимает слот, то есть очередь разгоняла сама себя. Успешные
 // ответы приходят за 0.2–0.5 с, поэтому больший бюджет не удлиняет обычную работу — он
 // выключает ложные срабатывания. Вернётся сценарий #197 (conn=0.000000s, code=000) — это
 // первый кандидат на откат.
-const _API_TIMEOUT_MS = 4000;
+const _API_TIMEOUT_MS = 2000;
 const _API_ATTEMPTS = 3;
 // #197: канал юзера рвёт не передачу, а УСТАНОВКУ соединения — `conn=0.000000s`, `code=000`,
 // висит 8-12 с. Замер: 12 попыток, 10 прошли, 2 умерли наглухо (~17%). Отсюда два следствия,
 // оба противоположные тому, что подсказывает слово «медленный канал»:
 // 1) ждать дольше бесполезно. Соединение либо встаёт быстро, либо не встаёт вовсе, поэтому