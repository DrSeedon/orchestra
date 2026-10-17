# Context for item-40

## Diff reviewed (-U20, capped at 1500 lines)

diff --git a/app/static/js/app.js b/app/static/js/app.js
index 0baa02cc2..e2ef50f53 100644
--- a/app/static/js/app.js
+++ b/app/static/js/app.js
@@ -5071,44 +5071,42 @@ function addChatEntry(type, content, ts, anchor, payload) {
                     div.appendChild(hint);
                     div.style.cursor = 'pointer';
                     let spawnExpanded = false;
                     div.addEventListener('click', (e) => {
                         if (e.target.tagName === 'A') return;
                         spawnExpanded = !spawnExpanded;
                         expandables.forEach(el => el.style.display = spawnExpanded ? 'block' : 'none');
                         hint.textContent = spawnExpanded ? '▲ collapse' : '▼ expand';
                     });
                 }
 
                 div.dataset.isEdit = '1';
             } catch {}
         }
         const isWebSearchCall = rawName === 'mcp__websearch__search' || rawName === 'mcp__websearch__search_web' || rawName === 'WebSearch';
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
                 }
             } catch {}
         }
         const isToolSearchCall = rawName === 'ToolSearch';
         if (isToolSearchCall) {
             try {
                 const d = JSON.parse(body);
                 const q = d.query || '';
                 header.textContent = `🔍 Loading: ${q}`;
                 header.style.color = '#38bdf8';
             } catch {}
         }
         const isBugReport = rawName === 'mcp__orchestra__report_bug';
         if (isBugReport) {
             try {
@@ -5706,44 +5704,50 @@ function addChatEntry(type, content, ts, anchor, payload) {
                 _insert(div);
                 if (!anchor && !_insertedBeforeStream && wasAtBottom) chat.scrollTop = chat.scrollHeight;
             }
             return;
         }
         const clean = content.replace(/^\{?"?result"?:\s*"?|"?\}?$/g, '').replace(/\\n/g, '\n');
         // Strip raw JSON link arrays from WebSearch results (shown as ugly JSON at top)
         const stripped = clean.replace(/^(Links:\s*\[.*?\}\]\s*\n?)+/gms, '');
         const escaped = _escHtml(stripped);
         // Render markdown links [text](url) first, then bare URLs
         const mdLinked = escaped.replace(/\[([^\]]+)\]\((https?:\/\/[^)]+)\)/g, '<a href="$2" target="_blank" class="text-indigo-400 hover:text-indigo-300 underline">$1</a>');
         const linked = mdLinked.replace(/((?<!href="|">)https?:\/\/[^\s\])"&<]+)/g, '<a href="$1" target="_blank" class="text-indigo-400 hover:text-indigo-300 underline">$1</a>');
         const _resultLines = linked.split('\n');
         const _RESULT_PREVIEW = 5;
         const _hasMore = _resultLines.length > _RESULT_PREVIEW;
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
                 addTimestamp(lastTool, ts);
                 return;
             }
             delete lastTool.dataset.lastTool;
             if (lastTool.dataset.isEdit) {
                 addTimestamp(lastTool, ts);
                 return;
             }
             const isToolSearch = lastTool.dataset.toolRawName === 'ToolSearch';
             if (isToolSearch) {
                 let toolName = '';
                 try { const d = JSON.parse(content); toolName = d.tool_name || ''; } catch {}
                 if (!toolName) { const m = content.match(/tool_name['":\s]+(\w+)/); toolName = m ? m[1] : ''; }
                 const hdr = lastTool.querySelector('.flex.items-center');
                 if (hdr && toolName) hdr.textContent = `✅ Loaded: ${toolName}`;


## Later history of the touched files on main (after this commit)

86 later commits touch these paths; the first 40 (oldest first):
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
dc09cc236 2026-08-22 Squashed commits: - #366: research + plan + 22 red tests (model catalog, two-level availability) - #366: plan review section + behavioral red reasons (no external reviewer: quota) - #366: T1 — kv_set/kv_delete writers + two-level availability flags (overlay, read-through kv) - #366: T2 — OpenRouter catalog fetch/normalize/kv-cache + registration re-applied inside every registry rebuild - #366: T3 — two-level enforcement: /api/models dashboard filter, agents gate in _create_session_locked, change-model via=dashboard|mcp, bounded unknown-model error; CONTRACT CHANGE: derived views are now a superset of SELECTABLE_MODEL_SPECS (test_derived_views_carry_exactly_the_declared_specs rewritten as subset assertions) - WIP #366: T4 catalog HTTP API written (GET/POST/PATCH /api/models/catalog*), tests not yet run; TODO: run test_catalog_api.py, mutation, T5 frontend+Playwright probe, T6 - #366: T4 — /api/models/catalog GET(union registry+cache)/refresh POST/flags PATCH; dropped counter surfaced; mutation: PATCH-echo-without-persist caught - #366: T5 — catalog modal screen: search/free/tools/image filters, two toggles per model, refresh button; picker untouched - #366: T5 — live Playwright probe evidence (probe-catalog.png): worktree js/css substituted on :8888, catalog modal renders 18 models / 36 toggles, search filters, clone-frozen screenshot - #366: T6 — live-agent shoulders: resume surface intact after both flags off, new spawn rejected with actionable message, switch-away allowed; mutation: message without screen name caught - #366: report + personal memory - #366: изоляция тестов — снимок и восстановление реестра моделей между тестами; kv-чтение флагов/кеша fail-soft при отсутствии таблицы - #366: route surface snapshot — +/api/models/catalog{,/refresh,/flags} (intentional new public endpoints)
1f0a526d3 2026-08-23 #225: group chat photo batches into compact galleries
aa33578e2 2026-08-23 #234: #234: add red acceptance tests
9f946a601 2026-08-24 #309: #309: freeze phase2 deletion oracles
e7d521de5 2026-08-24 fix: preserve generated images across chat switches
e26dcde85 2026-08-24 fix: switch Codex models in place
b09118919 2026-08-24 #338: #338: remove unreachable deleteOrchestrator
ebb38764a 2026-08-25 #365: harden free OpenRouter harness
33660cfd5 2026-08-25 #397: add final answer timeline navigation
bf1d013c4 2026-08-25 #365: send dashboard voice asynchronously
e7772a32b 2026-08-25 #364: зеркало логов держит 100 строк на сессию; секреты в своих логах не блокируют работу
00ab036d9 2026-08-25 #364: обрезать чат и при чтении истории — узлы копились без предела
13aceafe3 2026-08-25 рестарт: убрать блокировку ввода и починить сторож без pidfd_open
382bd22e8 2026-08-25 #364: freeze red oracle
46b02836a 2026-08-25 Merge remote-tracking branch 'origin/main'
589528d1a 2026-08-26 Improve Orchestra runtime stability and live status
bdff230b0 2026-08-27 #410: add GLM-5.3-Flash harness route
9d43ceaab 2026-08-27 Revert "#410: add GLM-5.3-Flash harness route"
f77e06cee 2026-08-27 #403: render send_files batches in dashboard
ad76ba42e 2026-08-27 #411: freeze reliable restart oracles
a06fcc500 2026-08-27 #404: add mirror freshness regression oracles
07f97eeff 2026-08-27 Merge remote-tracking branch 'origin/main'
99fa70980 2026-08-27 #405: add upload size and progress oracles
735cf14e5 2026-08-28 чат берётся из сети, зеркало логов в IndexedDB удалено
6de7cb703 2026-08-28 Force live chat snapshots past HTTP caches
16f85b462 2026-08-28 Restore one-shot previous chat history loading
3318068b0 2026-08-28 Unify restart and connection status across dashboard
b757e8343 2026-08-28 порог Sol по параболе: жжём пул Codex в начале окна
772e3a748 2026-08-28 Extract dashboard connection state from app monolith
7c04ece72 2026-08-28 Encapsulate dashboard quota panel internals

## Patches of the first 8 later commits, restricted to the touched paths (each capped at 150 lines)

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
### 0d8208a77 опрос дашборда: фазовый сдвиг и 304 на /api/sessions

diff --git a/app/static/js/app.js b/app/static/js/app.js
index 2031e3f83..84bac088a 100644
--- a/app/static/js/app.js
+++ b/app/static/js/app.js
@@ -931,22 +931,38 @@ document.addEventListener('DOMContentLoaded', () => {
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