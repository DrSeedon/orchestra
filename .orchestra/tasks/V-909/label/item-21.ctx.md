# Context for item-21

## Diff reviewed (-U20, capped at 1500 lines)

diff --git a/app/routes/sessions.py b/app/routes/sessions.py
index d6e6d7d5c..08975e86f 100644
--- a/app/routes/sessions.py
+++ b/app/routes/sessions.py
@@ -16,40 +16,41 @@ from fastapi.responses import JSONResponse, Response
 from starlette.responses import StreamingResponse
 from pydantic import BaseModel, field_validator, model_validator
 
 from app.db import (
     get_all_sessions,
     get_history_logs,
     get_log,
     get_logs,
     get_logs_before,
     get_logs_sync,
     get_runtime_handoff,
     get_session as get_session_row,
     get_session_by_name,
 )
 from app.deps import manager
 from app.errtext import err_text
 from app.events import MessageProvenance
 from app.models import ensure_dashboard_visible, ensure_spawn_allowed, resolve_model, MODELS
 from app.quota_gate import QuotaGateError
 from app.session import AgentStatus
+from app.status_policy import is_internal_telemetry_status
 
 logger = logging.getLogger("orchestra.sessions")
 
 router = APIRouter()
 
 async def _wait_for_merge_idle(session) -> bool:
     """Wait for the current turn's explicit terminal signal; only IDLE is ready."""
     if session.status.value == "idle":
         return True
     if not session.loaded or session.status.value != "running":
         return False
     return await session.wait_for_turn_completion()
 
 
 def _existing_branch_verdict(worktree_path: str, branch: str, scope: str,
                              force: bool) -> dict:
     """Что делать с УЖЕ существующей целевой веткой при возврате воркера на задачу (#61).
 
     Три исхода в словаре #17:
     - ветки нет → обычный путь;
@@ -518,41 +519,46 @@ async def get_session_context(name: str, scope: str):
 @router.get("/api/sessions/{name}/stream")
 async def stream_session_logs(name: str, scope: str, request: Request, after_id: int = 0, limit: int = 500):
     limit = min(limit, 1000)
     import json
     session_id = manager.get_session_id(name, scope)
     if not session_id:
         return JSONResponse({"error": "not found"}, status_code=404)
     stored = get_session_row(session_id)
 
     def with_status(payload: dict) -> dict:
         # Живую сессию перерешаем на КАЖДОМ событии: на коннекте её может не быть в
         # реестре (idle-воркер не загружен), а через минуту её грузит `ensure_loaded`
         # и она идёт ход по ЭТОМУ же стриму. Клиент верит `agent_status` каждого
         # события, поэтому статус, замороженный на коннекте, затирал бы верный.
         live_session = manager.get(session_id)
         status = (
             live_session.status.value
             if live_session is not None
             else str((stored or {}).get("status") or "idle")
         )
-        return {**payload, "agent_status": status}
+        result = {**payload, "agent_status": status}
+        if payload.get("type") == "status":
+            result["status_hidden"] = is_internal_telemetry_status(
+                str(payload.get("content") or "")
+            )
+        return result
 
     async def event_generator():
         from app.db import _conn
         from app.live_broker import STREAM_CLOSE, broker
         last_id = after_id
         c = _conn()
         q = broker.subscribe(session_id)  # session_id == manager.get_session_id == session.id
         try:
             # Первым делом называем сессию, которую мы разрешили из name+scope. Клиент
             # держит историю по session_id и до этого события знает её лишь по своей карте,
             # которая могла устареть (агента убили и подняли под тем же именем). Правду
             # знает только сервер, и он обязан сказать её ДО первой строки истории.
             yield f"data: {json.dumps(with_status({'type': '__session', 'session_id': session_id}))}\n\n"
             # initial history first (one-shot) — preserves load-more behavior
             if after_id == 0:
                 for log in get_logs_before(session_id, before_id=2**31 - 1, limit=limit):
                     yield f"data: {json.dumps(with_status(log))}\n\n"
                     last_id = log["id"]
             while True:
                 if await request.is_disconnected():
@@ -578,45 +584,58 @@ async def stream_session_logs(name: str, scope: str, request: Request, after_id:
                 await asyncio.sleep(0.1 if (logs or drained) else 0.5)
         finally:
             broker.unsubscribe(session_id, q)
             c.close()
     return StreamingResponse(event_generator(), media_type="text/event-stream",
                              headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
 
 
 @router.get("/api/sessions/{name}/logs")
 async def get_session_logs(name: str, response: Response, scope: str,
                            after_id: int = 0, before_id: int = 0,
                            limit: int = 500, max_bytes: int = 0, cap: int = 0):
     # Live chat snapshots are authoritative state, not an asset. A browser/intermediary
     # replaying an older 200 here recreates the exact "old messages, then SSE catches up"
     # staircase that the network-first client is designed to eliminate.
     response.headers["Cache-Control"] = "no-store"
     limit = min(limit, 1000)
     session_id = manager.get_session_id(name, scope)
     if not session_id:
         return JSONResponse({"error": "not found"}, status_code=404)
+
+    def annotate(log: dict) -> dict:
+        if log.get("type") != "status":
+            return log
+        return {
+            **log,
+            "status_hidden": is_internal_telemetry_status(
+                str(log.get("content") or "")
+            ),
+        }
+
     if before_id > 0:
-        return get_logs_before(session_id, before_id, limit,
+        logs = get_logs_before(session_id, before_id, limit,
                                max(0, min(max_bytes, 1 << 20)),
                                max(0, min(cap, 1 << 20)))
-    return get_logs(session_id, after_id=after_id)
+    else:
+        logs = get_logs(session_id, after_id=after_id)
+    return [annotate(log) for log in logs]
 
 
 @router.get("/api/logs/sync")
 async def logs_sync(after_id: int = 0, tail: int = 20, cap: int = 16384):
     """Зеркало журнала для браузера: все сессии всех проектов одним ответом.
 
     Scope не принимает намеренно — пользователь один, а логи ключуются по session_id.
     ``tail=0`` — карта сессий без строк журнала; дашборд ходит именно так с #72, потому
     что предзагрузка на все сессии стоила 145 КБ по проводу, а рисовалось из неё ~5%.
     Инкремент (after_id > 0) tail игнорирует и весит единицы КБ.
     """
     return get_logs_sync(after_id=max(after_id, 0),
                          tail=max(0, min(tail, 200)),
                          cap=max(256, min(cap, 1 << 20)))
 
 
 @router.get("/api/logs/{log_id}")
 async def get_single_log(log_id: int):
     """Одна строка журнала целиком — для кнопки «загрузить целиком» под обрезанной (#74).
 
diff --git a/app/static/js/chat.js b/app/static/js/chat.js
index 27f8884c3..c8397ca1a 100644
--- a/app/static/js/chat.js
+++ b/app/static/js/chat.js
@@ -1794,42 +1794,43 @@ function _updateCompactToolResult(card, content, isBase64Image) {
 }
 
 function _renderCompactToolEntry(type, content, ts, payload, chat, anchor, insertAndFollow, isBase64Image) {
     if (!window.compactMode || (type !== 'tool' && type !== 'tool_result')) return false;
     if (type === 'tool_result') {
         const card = _toolForResult(chat, payload, anchor, true);
         if (card) {
             _updateCompactToolResult(card, content, isBase64Image);
             return true;
         }
     }
 
     const line = buildCompactToolLine(type, content, ts, payload);
     insertAndFollow(line, () => {
         _trimChatNodes(chat);
         if (type === 'tool') _adoptOrphanResults(chat, line.dataset.toolUseId);
     });
     return true;
 }
 
-function _renderStatusEntry(type, content, ts, anchor, insertAndFollow) {
+function _renderStatusEntry(type, content, ts, anchor, insertAndFollow, payload) {
     if (type !== 'status') return false;
+    if (payload?.status_hidden === true) return true;
     // A status row may beat the authoritative `text` row through async logging.
     // Never finalize streamBubble here or the later text becomes a duplicate answer.
     if (content?.startsWith('precompact timer')) return true;
     if (/^codex hook .+: (?:running|started|completed)(?: · \d+ms)?$/i.test(content || '')) return true;
     if (/^codex mcp .+: (?:starting|ready)$/i.test(content || '')) return true;
     if (/^compact started \(native Codex,/i.test(content || '')) return true;
 
     if (/^grok mcp ready\b/i.test(content || '')) {
         const badge = document.createElement('div');
         badge.className = 'text-center text-xs py-1 text-emerald-400 italic';
         badge.textContent = `🔌 ${content}`;
         addTimestamp(badge, ts);
         insertAndFollow(badge);
         return true;
     }
 
     const nativeCodexCompact = (content || '').match(
         /^compact done \(native Codex\):\s*(\d+)%\s*→\s*(\d+)%/i
     );
     const rateLimit = _parseRateLimitStatus(content);
@@ -3879,41 +3880,41 @@ function addChatEntry(type, content, ts, anchor, payload) {
 
     const platformNotice = renderSystemChatEntry(type, content, ts);
     if (platformNotice) {
         _insert(platformNotice);
         return;
     }
 
     if (type === 'review') {
         let reviewData = {};
         try { reviewData = JSON.parse(content); } catch {}
         const review = document.createElement('div');
         review.className = 'codex-review';
         const phase = reviewData.phase === 'exited' ? 'Review completed' : 'Review mode';
         review.innerHTML = `<div class="codex-review-title">◎ ${phase}</div><div class="codex-review-body"></div>`;
         review.querySelector('.codex-review-body').textContent = reviewData.review || '';
         addTimestamp(review, ts);
         _insert(review);
         return;
     }
 
-    if (_renderStatusEntry(type, content, ts, anchor, _insertAndFollow)) return;
+    if (_renderStatusEntry(type, content, ts, anchor, _insertAndFollow, payload)) return;
 
     if (_renderSubagentLifecycleEntry(type, content, ts, payload, chat, _insertAndFollow)) return;
 
     const div = document.createElement('div');
     div.className = `px-3 py-2 rounded-lg text-sm break-words ${
         type === 'user_message' ? 'chat-user ml-16' :
         type === 'tool' ? 'chat-tool' :
         type === 'tool_result' ? 'chat-tool-result' :
         type === 'error' ? 'text-red-400 text-xs' :
         'chat-bot markdown-body'
     }`;
     if (type === 'user_message') {
         const allowedOrigins = new Set([
             'user', 'agent', 'background_task', 'platform', 'system', 'unknown',
         ]);
         const suppliedOrigin = payload && payload.origin;
         const suppliedDetail = payload && payload.origin_detail;
         const suppliedSenders = suppliedDetail && suppliedDetail.senders;
         const detailKeys = suppliedDetail && typeof suppliedDetail === 'object'
             ? Object.keys(suppliedDetail)
diff --git a/app/status_policy.py b/app/status_policy.py
new file mode 100644
index 000000000..8baaf8043
--- /dev/null
+++ b/app/status_policy.py
@@ -0,0 +1,11 @@
+"""Audience classification for persisted status events."""
+
+import re
+
+
+_RAW_TELEMETRY_STATUS = re.compile(r"^[A-Z][A-Z0-9_]*_RAW\s+\{")
+
+
+def is_internal_telemetry_status(content: str) -> bool:
+    """Return whether a structured provider telemetry status is not user-facing."""
+    return bool(_RAW_TELEMETRY_STATUS.match(str(content)))
diff --git a/app/tg_bridge.py b/app/tg_bridge.py
index 1b5ba1a33..921ec4175 100644
--- a/app/tg_bridge.py
+++ b/app/tg_bridge.py
@@ -11,40 +11,41 @@ import os
 import re
 import time
 from collections import Counter, OrderedDict, deque
 from datetime import datetime, timezone, timedelta
 from pathlib import Path
 
 import aiohttp
 from aiogram import Bot, Dispatcher, types, F
 from aiogram.exceptions import (
     TelegramBadRequest,
     TelegramNetworkError,
     TelegramRetryAfter,
     TelegramServerError,
 )
 from aiogram.client.default import DefaultBotProperties
 from aiogram.types import LinkPreviewOptions
 from telegramify_markdown import convert as md_convert
 
 from app.errtext import err_text
 from app.events import MessageProvenance
+from app.status_policy import is_internal_telemetry_status
 from app.tasks import spawn_supervised
 from app.turn_markers import (
     SILENT_TURN_MARKER as TG_SILENT_TURN_MARKER,
     is_silent_turn_text,
 )
 from app.transcription import transcribe_audio as _transcribe_audio
 from app.upload_limits import MAX_UPLOAD_BYTES, MAX_UPLOAD_MB
 
 logger = logging.getLogger("tg-bridge")
 logger.setLevel(logging.DEBUG)
 if not logger.handlers:
     logger.addHandler(logging.StreamHandler())
 
 CONFIG_PATH = Path(__file__).parent.parent / "data" / "tg_bridge.json"
 UPLOADS_DIR = Path(__file__).parent.parent / "data" / "uploads"
 UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
 MEDIA_CACHE_PATH = UPLOADS_DIR / ".media_cache.json"
 
 config = {"group_id": 0, "topics": {}, "token": ""}
 bot = None
@@ -3383,40 +3384,42 @@ async def stream_logs(orch_name: str, thread_id: int):
                                 _read_params = json.loads(raw) if raw else {}
                                 _img_path = _read_params.get("file_path", "")
                                 if _img_path and Path(_img_path).is_file():
                                     await _tg_send_file_safe(
                                         config["group_id"], _img_path,
                                         f"📷 {Path(_img_path).name}", thread_id,
                                         is_photo=True, important=True,
                                         isolated_preview=True,
                                     )
                             except _TgDeliveryOverloaded:
                                 raise
                             except Exception as _e:
                                 logger.debug(f"Read image send failed: {_e}")
                         turn.close(log["id"], log.get("tool_use_id") or "",
                                    _result_mark(c, log.get("tool_is_error")))
                         await _update_progress(turn, thread_id, orch_name)
                         continue
                     elif t == "error":
                         text = f"❌ {c}"
                     elif t == "status":
+                        if is_internal_telemetry_status(c):
+                            continue
                         if "turn ended" in c:
                             still_running = _any_running_in_scope(scope)
                             if not still_running:
                                 _schedule_topic_status(orch_name, False)
                             # Граница хода — единственная durable-разметка «агент договорил»:
                             # на самой строке text её нет, мост стримит журнал вперёд и в
                             # момент отправки не знает, будет ли ещё текст (живой замер:
                             # 4777 из 6161 строк text — промежуточные).
                             _pending_turn_end_mention = (
                                 is_orch and _notify_reason is not None
                             )
                             await _update_progress(turn, thread_id, orch_name,
                                                    force=True)
                             if _anchor_sent_for == log["id"]:
                                 # Якорь по этой строке уже ушёл, а строка переигралась.
                                 # Пропускаем ТОЛЬКО повтор якоря: дальше по строке живёт
                                 # тег владельца, и `continue` здесь терял бы его молча.
                                 text = ""
                             elif not turn.all_lines():
                                 # Ход БЕЗ ДЕЙСТВИЙ не оставляет якорь — ни тихий, ни обычный.
diff --git a/tests/test_frontend.py b/tests/test_frontend.py
index 0fad5982d..694499d16 100644
--- a/tests/test_frontend.py
+++ b/tests/test_frontend.py
@@ -379,40 +379,71 @@ def test_live_stream_status_updates_selected_agent_badge(dashboard_page: Page):
             window._pollWake = key => seen.push(key);
             _streamStatusRefreshAt = 0;
             _wakeStatusRefreshFromStream();
             _wakeStatusRefreshFromStream();
             return seen;
         }""")
         assert wakes == ["sessions"]
     finally:
         dashboard_page.evaluate("""() => {
             renderAgentList = window.__savedRenderAgentList403;
             delete window.__savedRenderAgentList403;
         }""")
 
 
 def test_chat_input_exists(dashboard_page: Page):
     chat_input = dashboard_page.locator("#chat-input")
     expect(chat_input).to_be_visible()
     expect(chat_input).to_be_enabled()
 
 
+def test_internal_telemetry_status_is_not_rendered_in_chat(
+    dashboard_browser: Browser,
+):
+    """SSE status classification reaches the real addChatEntry wiring."""
+    source = (Path(__file__).parent.parent / "app/static/js/chat.js").read_text()
+    page = dashboard_browser.new_page()
+    page.route(
+        "**/static/js/chat.js*",
+        lambda route: route.fulfill(
+            status=200,
+            content_type="application/javascript",
+            body=source,
+        ),
+    )
+    _goto_dashboard(page)
+    try:
+        rendered = page.evaluate("""() => {
+            const chat = document.querySelector('#chat');
+            chat.replaceChildren();
+            const raw = 'RATE_LIMIT_RAW {"utilization":0.32}';
+            addChatEntry('status', raw, null, null, {
+                type: 'status', status_hidden: true,
+            });
+            return {raw, text: chat.textContent};
+        }""")
+    finally:
+        page.close()
+
+    assert rendered["raw"] not in rendered["text"]
+
+
 def test_send_button_exists(dashboard_page: Page):
     send_btn = dashboard_page.locator("#send-btn")
     expect(send_btn).to_be_visible()
     expect(send_btn).to_have_text("Send")
 
 
 def test_usage_bar_visible(dashboard_page: Page):
     usage_bar = dashboard_page.locator("#usage-bar")
     expect(usage_bar).to_be_attached()
 
 
 def test_stream_updates_preserve_chat_selection(dashboard_browser: Browser):
     source = (Path(__file__).parent.parent / "app/static/js/chat.js").read_text()
     stream_code = source.split("let streamBubble = null;", 1)[1].split(
         "function _renderJsonGrid", 1,
     )[0]
     page = dashboard_browser.new_page()
     page.set_content(
         '<div id="chat"><div id="stream"><p>Streaming text to copy</p>'
         '<span class="typing-cursor">▍</span></div></div>'
diff --git a/tests/test_tg_bridge.py b/tests/test_tg_bridge.py
index a9c3083c0..a1b5b75be 100644
--- a/tests/test_tg_bridge.py
+++ b/tests/test_tg_bridge.py
@@ -4811,40 +4811,68 @@ class TestReadImagePreview:
             '<invoke name="Bash"><parameter name="cmd">pwd</parameter></invoke>\n'
             "```",
             False,
         ),
     ],
 )
 async def test_text_tool_call_marker_reaches_topic_and_mirror(
     tb, monkeypatch, content, marked,
 ):
     log_calls = 0
 
     class FakeConn:
         def close(self):
             pass
 
 
 
 class TestTurnFoldStream:
     """Поток целиком: что мост РЕАЛЬНО отправляет за ход."""
 
+    @pytest.mark.asyncio
+    async def test_rate_limit_raw_stays_in_logs_but_not_user_channel(
+        self, tb, monkeypatch,
+    ):
+        """Claude raw rate-limit telemetry is durable status, not user-facing status."""
+        from app.events import AgentEvent
+        from app.session import AgentSession
+
+        raw_content = 'RATE_LIMIT_RAW {"utilization":0.16327272727272726}'
+        persisted = []
+        session = AgentSession(
+            id="sid", name="orch", scope="/s", cwd="/tmp",
+            model="claude-sonnet-5[1m]", system_prompt="test",
+        )
+        monkeypatch.setattr(
+            session, "_log",
+            lambda log_type, content, **kwargs: persisted.append({
+                "id": 1, "type": log_type, "content": content,
+            }),
+        )
+        session._handle_event(AgentEvent("status", raw_content))
+
+        assert persisted == [{"id": 1, "type": "status", "content": raw_content}]
+        sent, _, _ = await self._run(tb, monkeypatch, [persisted])
+
+        # Anchor on the bridge's own primary-TG send node, not the whole event stream.
+        assert not [item for item in sent if raw_content in item["text"]]
+
     async def _run(self, tb, monkeypatch, batches, overload_first_anchor=False,
                    overload_after_anchor=False):
         sent, expandables, edits = [], [], []
         calls = {"n": 0, "anchor": 0}
 
         def get_logs(session_id, after_id=0, conn=None):
             # Первый вызов stream_logs делает ДО цикла — им он берёт стартовый курсор.
             i = calls["n"] - 1
             calls["n"] += 1
             if i < 0:
                 return []
             if i >= len(batches):
                 raise asyncio.CancelledError
             return [dict(r) for r in batches[i]]
 
         async def send_safe(chat_id, text, thread_id=None, **kw):
             if text.startswith("━"):
                 calls["anchor"] += 1
                 if overload_first_anchor and calls["anchor"] == 1:
                     raise tb._TgDeliveryOverloaded("full")


## Later history of the touched files on main (after this commit)

118 later commits touch these paths; the first 40 (oldest first):
334c89b0f 2026-09-01 #429: show full arguments for thick tool calls
a1037725b 2026-09-01 #435: merge laptop history and reserve VPS task range
4eac349d7 2026-09-03 #508: freeze Telegram ingress regression tests
0afee6db5 2026-09-03 #509: freeze Telegram service-event regression oracle
cd39b74c9 2026-09-03 merge: забрать 38 коммитов контура VPS (#395,#426,#435,#500-#506) в переехавший main
43c82f0bd 2026-09-03 Merge remote-tracking branch 'origin/main'
afdf03ea0 2026-09-03 #450: hide user timestamps in human-facing channels
f3c2eaaaf 2026-09-03 merge: забрать 15 коммитов VPS; оглавление базы знаний сведено с обеих сторон
2a048e616 2026-09-03 #465: research taskless adhoc merge deadlock
7d1fc95d2 2026-09-04 #472: доска PROJECTS показывает проекты выбранного оркестратора
e47719104 2026-09-04 #473: миграция раскладки чинит владение воркеров в обоих владельцах
c444fec21 2026-09-04 #478: карточка результата record_review_outcome вместо сырого polотна
89f038425 2026-09-04 #475: замороженный оракул — метка полосы обязана повторять высоту сообщения
480ca55c2 2026-09-04 refactor: extract privacy and error helpers, trim duplicated validation
e3d29ad1f 2026-09-05 #499: surface and repair derived lifecycle quarantine
e2e83139f 2026-09-05 fix: complete scoped recovery and continuation lifecycle safeguards
da8876dfa 2026-09-06 лимиты файлов: 50 -> 2000 МБ по потолку локального Bot API, квота загрузок 1 -> 10 ГБ
979c46315 2026-09-06 мерж: чужой номер задачи в сообщении коммита — предупреждение, а не отказ всей операции
13e9b2601 2026-09-07 #526, #527: research formal prompts, decoding costs and Orchestra control seams
067679f36 2026-09-07 #515, #432, #523, #520, #526: CI шардируется на 6 процессов — полный сьют в один процесс убивает OOM
5f8894ec9 2026-09-07 #532: enforce role and persistent worker tool exclusions at MCP dispatch
264daeb75 2026-09-07 Separate runtime control from model prose and preserve review results
ad5d17664 2026-09-07 Merge VPS main with laptop runtime-control fixes
d55d3f6b5 2026-09-07 #534: WIP #534: preserve browser resource and pipe diagnostics
4fcc9d8a5 2026-09-07 Merge remote-tracking branch 'origin/main'
148d85437 2026-09-07 Isolate quota and browser fixtures across CI test order
25a7e6ed7 2026-09-07 Introduce advisory review and one pinned acceptance for new task assignments
bb115dcac 2026-09-07 Merge branch 'main' into codex/simplify-review
2d1f79126 2026-09-07 Merge completed VPS quota and browser fixes with isolated CI fixtures
8a3c8ad73 2026-09-07 Merge branch 'main' into codex/simplify-review
fe507ac6e 2026-09-08 Namespace VPS tasks and simplify runtime chat transfer and worker notes
4f87cecca 2026-09-08 #536: WIP #536: preserve writer conflict detection and regression coverage
715f0fc9f 2026-09-08 Merge remote-tracking branch 'origin/main' into codex/local-workflow
f5713f4df 2026-09-08 Retire legacy review gates and fix adopted Codex writer release
98574f427 2026-09-08 Replace duplicate task stores with private Git and one versioned SQLite projection
fc0d5143d 2026-09-08 Merge current main into storage simplification
5f7e72c50 2026-09-08 Add reusable idle watches and label dashboard message channel
d9ce293fa 2026-09-08 Integrate current main before storage cutover
3e068562f 2026-09-11 V-544: #V-544: тяжёлое фото уходит документом, отказ провайдера терминален, лимиты названы
360c846b7 2026-09-12 V-555: #V-555: replace retired fan launcher with dynamic workflows

## Patches of the first 8 later commits, restricted to the touched paths (each capped at 150 lines)

### 334c89b0f #429: show full arguments for thick tool calls

diff --git a/app/static/js/chat.js b/app/static/js/chat.js
index ed25f57f0..f50a8e527 100644
--- a/app/static/js/chat.js
+++ b/app/static/js/chat.js
@@ -996,20 +996,53 @@ function _renderJsonGrid(obj, container, maxDepth) {
     }
     container.appendChild(grid);
     return grid;
 }
 
+function _runFanSummary(data) {
+    const tasks = Array.isArray(data?.tasks) ? data.tasks : [];
+    const reuse = Array.isArray(data?.reuse) ? data.reuse : [];
+    const total = tasks.length + reuse.length;
+    const count = `${total} ${total === 1 ? 'воркер' : total < 5 ? 'воркера' : 'воркеров'}`;
+    const seconds = Number(data?.deadline_seconds);
+    let deadline = 'без дедлайна';
+    if (Number.isFinite(seconds) && seconds > 0) {
+        const minutes = Math.round(seconds / 60);
+        deadline = minutes >= 60
+            ? `${Math.floor(minutes / 60)} ч${minutes % 60 ? ` ${minutes % 60} мин` : ''}`
+            : `${minutes} мин`;
+    }
+    return `🎼 run_fan → ${count} · дедлайн ${deadline}`;
+}
+
+function _runFanItems(data) {
+    const tasks = Array.isArray(data?.tasks) ? data.tasks : [];
+    const reuse = Array.isArray(data?.reuse) ? data.reuse : [];
+    return [
+        ...tasks.map(item => ({
+            name: item?.name || '?',
+            model: item?.model || '',
+            role: item?.role || 'worker',
+        })),
+        ...reuse.map(item => ({
+            name: item?.name || '?',
+            model: '',
+            role: 'reuse',
+        })),
+    ];
+}
+
 function buildCompactToolLine(type, content, ts, payload) {
     const line = document.createElement('div');
     line.className = 'flex items-center gap-2 text-xs py-0.5 px-2 cursor-pointer rounded group';
     line.style.color = '#64748b';
 
     if (type === 'tool') {
         const colonIdx = content.indexOf(':');
         const rawName = canonicalToolName(colonIdx > 0 ? content.slice(0, colonIdx).trim() : content.slice(0, 30));
         const body = colonIdx > 0 ? content.slice(colonIdx + 1).trim() : '';
-        const icon = toolIcon(rawName);
+        let icon = toolIcon(rawName);
         const short = toolShortName(rawName);
 
         let preview = body;
         const _safeTaskFilter = (value) => typeof value === 'string' && value.length <= 32 && !/[<>\"'`]/.test(value);
         const _taskListFilter = (parsedObj) => {
@@ -1019,11 +1052,34 @@ function buildCompactToolLine(type, content, ts, payload) {
             return parts.length > 0 ? parts.join(', ') : '';
         };
         try {
             const parsed = JSON.parse(body);
             if (rawName === NOTIFY_USER_TOOL) preview = `🔔 ${parsed.reason || 'зовёт'}`;
-            else if (rawName === 'mcp__orchestra__spawn_worker') preview = `🚀 ${parsed.name || '?'} (${_modelLabel(parsed.model || 'claude-sonnet-4-6')})`;
+            else if (rawName === 'mcp__orchestra__spawn_worker') {
+                icon = '👶';
+                const role = parsed.role ? ` · ${parsed.role}` : '';
+                const task = parsed.task_id ? ` · #${taskNum(parsed.task_id)}` : '';
+                preview = `→ ${parsed.name || '?'} · ${_modelLabel(parsed.model || 'claude-sonnet-4-6')}${role}${task}`;
+            }
+            else if (rawName === 'mcp__orchestra__send_message') {
+                icon = '✉️';
+                const message = typeof parsed.message === 'string' ? parsed.message : '';
+                preview = `→ ${parsed.to || '?'} · ${message.length} симв.`;
+            }
+            else if (rawName === 'mcp__orchestra__task_create') {
+                icon = '📋';
+                const priority = parsed.priority != null ? ` · приоритет ${parsed.priority}` : '';
+                preview = `создаёт задачу «${typeof parsed.title === 'string' ? parsed.title : '?'}»${priority}`;
+            }
+            else if (rawName === 'mcp__orchestra__task_update') {
+                icon = '✏️';
+                const status = typeof parsed.status === 'string' && parsed.status ? ` • статус ${parsed.status}` : '';
+                preview = `обновляет задачу #${taskNum(parsed.par) || '?'}${status}`;
+            }
+            else if (rawName === 'mcp__orchestra__run_fan') {
+                preview = _runFanSummary(parsed).replace(/^🎼 run_fan → /, '→ ');
+            }
             else if (rawName === 'mcp__websearch__search' || rawName === 'mcp__websearch__search_web' || rawName === 'WebSearch') preview = codexWebSearchCompactLabel(codexWebSearchSpec(parsed));
             else if (rawName === 'ToolSearch') preview = `🔍 ${parsed.query || ''}`;
             else if (rawName === 'mcp__orchestra__report_bug') preview = `🐛 ${parsed.title || '?'}`;
             else if (rawName === 'mcp__orchestra__send_file') preview = `📎 ${(parsed.path || '').split('/').pop() || '?'}`;
             else if (rawName === 'mcp__orchestra__send_files') {
@@ -1055,15 +1111,11 @@ function buildCompactToolLine(type, content, ts, payload) {
                 preview = `📝 ${changes.length} file${changes.length === 1 ? '' : 's'}`;
             }
             else if (rawName === 'ViewImage') preview = `🖼 ${(parsed.file_path || '').split('/').pop() || 'image'}`;
             else if (rawName === 'ImageGeneration') preview = '🎨 generating image';
             else if (rawName === 'Sleep') preview = `⏱ ${Math.round((parsed.duration_ms || 0) / 1000)}s`;
-            else if (rawName === 'mcp__orchestra__task_create') preview = `создаёт задачу «${typeof parsed.title === 'string' ? parsed.title : '?'}»`;
-            else if (rawName === 'mcp__orchestra__task_update') {
-                const status = typeof parsed.status === 'string' && parsed.status.length > 0 ? ` • статус ${parsed.status}` : '';
-                preview = `обновляет задачу #${taskNum(parsed.par) || '?'}${status}`;
-            } else if (rawName === 'mcp__orchestra__task_list') {
+            else if (rawName === 'mcp__orchestra__task_list') {
                 const _fl = _taskListFilter(parsed);
                 preview = `читает список задач${_fl ? ` (${_fl})` : ''}`;
             } else if (rawName === 'mcp__orchestra__task_get') preview = `читает задачу #${taskNum(parsed.par) || '?'}`;
             else if (rawName === 'mcp__orchestra__bg_create') { const _bi = _JOB_ICONS[parsed.type]||'⚙️'; preview = `${_bi} BG: ${parsed.type||'?'} ${parsed.message ? '"'+parsed.message.slice(0,30)+'"' : ''}`; }
             else if (rawName === 'mcp__orchestra__bg_list') preview = '📊 BG Jobs';
@@ -1601,18 +1653,88 @@ function _appendToolTechnicalDetails(card, content) {
     details.dataset.toolTechnicalDetails = '1';
     details.style.cssText = 'margin-top:6px;border-top:1px solid rgba(51,65,85,0.55);padding-top:4px';
     const summary = document.createElement('summary');
     summary.style.cssText = 'font-size:10px;color:#64748b;cursor:pointer;user-select:none';
     summary.textContent = 'Технические детали';
+    details.addEventListener('click', event => event.stopPropagation());
     const raw = document.createElement('pre');
     raw.style.cssText = 'margin:5px 0 0;padding:6px 8px;border-radius:6px;background:#0d1117;color:#64748b;font-size:10px;white-space:pre-wrap;overflow-wrap:anywhere;max-height:220px;overflow:auto';
     try { raw.textContent = JSON.stringify(JSON.parse(content), null, 2); }
     catch { raw.textContent = content; }
     details.append(summary, raw);
     card.appendChild(details);
 }
 
+function _appendArgumentField(host, key, value) {
+    const field = document.createElement('div');
+    field.className = 'tool-argument-field';
+    const label = document.createElement('div');
+    label.className = 'tool-argument-label';
+    label.textContent = key;
+    const text = document.createElement('pre');
+    text.className = 'tool-argument-value';
+    text.textContent = typeof value === 'string' ? value : JSON.stringify(value, null, 2);
+    field.append(label, text);
+    host.appendChild(field);
+}
+
+function _appendFullToolArguments(card, rawName, data) {
+    const details = document.createElement('details');
+    details.dataset.toolFullArguments = '1';
+    details.className = 'tool-full-details';
+    const summary = document.createElement('summary');
+    summary.textContent = 'Полные аргументы';
+    details.appendChild(summary);
+    details.addEventListener('click', event => event.stopPropagation());
### a1037725b #435: merge laptop history and reserve VPS task range

### 4eac349d7 #508: freeze Telegram ingress regression tests

diff --git a/app/tg_bridge.py b/app/tg_bridge.py
index f7b3d1bb2..ac1e2a617 100644
--- a/app/tg_bridge.py
+++ b/app/tg_bridge.py
@@ -228,21 +228,62 @@ async def _download_file(file_id: str, filename: str, unique_id: str = "") -> st
     except Exception as e:
         logger.warning(f"download_file failed for {filename}: {e}")
         return None
 
 
+def _telegram_post_url(chat, message_id: int | None) -> str | None:
+    if not chat or not message_id:
+        return None
+    username = getattr(chat, "username", None)
+    if username:
+        return f"https://t.me/{username.lstrip('@')}/{message_id}"
+    chat_id = str(getattr(chat, "id", ""))
+    if chat_id.startswith("-100"):
+        return f"https://t.me/c/{chat_id[4:]}/{message_id}"
+    return None
+
+
 def _forward_meta(msg: types.Message) -> str:
-    if not msg.forward_date:
-        return ""
     fwd = "Forwarded"
-    if msg.forward_from:
-        name = msg.forward_from.first_name
-        if msg.forward_from.last_name:
-            name += " " + msg.forward_from.last_name
-        fwd += f" from {name}"
-    elif msg.forward_sender_name:
-        fwd += f" from {msg.forward_sender_name}"
+    origin = getattr(msg, "forward_origin", None)
+    source = None
+    post_url = None
+    if origin:
+        origin_type = getattr(origin, "type", None)
+        if origin_type == "user":
+            user = origin.sender_user
+            source = " ".join(
+                part for part in (user.first_name, user.last_name) if part
+            )
+        elif origin_type == "hidden_user":
+            source = origin.sender_user_name
+        elif origin_type == "chat":
+            chat = origin.sender_chat
+            source = chat.title or chat.username
+        elif origin_type == "channel":
+            source = origin.chat.title or origin.chat.username
+            post_url = _telegram_post_url(origin.chat, origin.message_id)
+    elif getattr(msg, "forward_date", None):
+        if msg.forward_from:
+            source = " ".join(
+                part
+                for part in (msg.forward_from.first_name, msg.forward_from.last_name)
+                if part
+            )
+        elif msg.forward_sender_name:
+            source = msg.forward_sender_name
+        elif msg.forward_from_chat:
+            source = msg.forward_from_chat.title or msg.forward_from_chat.username
+            post_url = _telegram_post_url(
+                msg.forward_from_chat, msg.forward_from_message_id
+            )
+    else:
+        return ""
+    if source:
+        fwd += f" from {source}"
+    if post_url:
+        fwd += f" | {post_url}"
     return f"[{fwd}] "
 
 
 async def _resolve_orch(msg: types.Message) -> tuple[str | None, object | None]:
     sender = msg.from_user.first_name if msg.from_user else "?"
@@ -3808,10 +3849,56 @@ async def handle_group_message(msg: types.Message):
         reply_prefix = f"> {quoted}\n\n"
     content = f"{reply_prefix}{_forward_meta(msg)}{msg.text}"
     await _send_to_agent(msg, session, content)
 
 
+def _fallback_payload(msg: types.Message) -> tuple[str, object]:
+    content_type = getattr(msg.content_type, "value", msg.content_type) or "unknown"
+    payload = getattr(msg, content_type, None) if content_type != "unknown" else None
+    if content_type == "unknown":
+        extra = {
+            key: value
+            for key, value in (msg.model_extra or {}).items()
+            if value is not None
+        }
+        if "rich_message" in extra:
+            return "rich_message", extra["rich_message"]
+        if len(extra) == 1:
+            content_type, payload = next(iter(extra.items()))
+        elif extra:
+            return "+".join(sorted(extra)), extra
+    return content_type, payload if payload is not None else msg
+
+
+def _serialize_fallback_payload(payload: object) -> str:
+    model_dump_json = getattr(payload, "model_dump_json", None)
+    if model_dump_json:
+        return model_dump_json(exclude_none=True, by_alias=True)
+    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str)
+
+
+@dp.message()
+async def handle_unhandled_message(msg: types.Message):
+    content_type, payload = _fallback_payload(msg)
+    logger.warning(
+        "TG ingress fallback: chat=%s thread=%s message=%s type=%s",
+        msg.chat.id,
+        msg.message_thread_id,
+        msg.message_id,
+        content_type,
+    )
+    orch_name, session = await _resolve_orch(msg)
+    if not session:
+        return
+    serialized = _serialize_fallback_payload(payload)
+    await _send_to_agent(
+        msg,
+        session,
+        f"{_forward_meta(msg)}[{content_type}] {serialized}",
+    )
+
+
 async def topic_sync_loop():
     while True:
         await asyncio.sleep(30)
         try:
             await ensure_topics()
diff --git a/tests/test_tg_bridge.py b/tests/test_tg_bridge.py
index 8e062bc6e..529923325 100644
--- a/tests/test_tg_bridge.py
+++ b/tests/test_tg_bridge.py
@@ -115,15 +115,15 @@ def tb(tmp_path, monkeypatch):
     monkeypatch.setattr(tg_bridge, "_tg_call_sequence", 0)
     return tg_bridge
 
 
 @pytest.mark.asyncio
-async def test_polling_does_not_override_uvicorn_signal_handlers(tb):
+async def test_polling_does_not_override_uvicorn_signal_handlers(tb, monkeypatch):
     dispatcher = AsyncMock()
     dispatcher.start_polling.side_effect = asyncio.CancelledError
     bot = object()
### 0afee6db5 #509: freeze Telegram service-event regression oracle

diff --git a/app/tg_bridge.py b/app/tg_bridge.py
index ac1e2a617..c74c343c9 100644
--- a/app/tg_bridge.py
+++ b/app/tg_bridge.py
@@ -14,10 +14,11 @@ from collections import Counter, OrderedDict, deque
 from datetime import datetime, timezone, timedelta
 from pathlib import Path
 
 import aiohttp
 from aiogram import Bot, Dispatcher, types, F
+from aiogram.enums import ContentType
 from aiogram.exceptions import (
     TelegramBadRequest,
     TelegramNetworkError,
     TelegramRetryAfter,
     TelegramServerError,
@@ -3874,20 +3875,47 @@ def _serialize_fallback_payload(payload: object) -> str:
     if model_dump_json:
         return model_dump_json(exclude_none=True, by_alias=True)
     return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str)
 
 
+_SERVICE_MESSAGE_TYPES = frozenset(
+    content_type.value
+    for content_type in (
+        ContentType.FORUM_TOPIC_CREATED,
+        ContentType.FORUM_TOPIC_EDITED,
+        ContentType.FORUM_TOPIC_CLOSED,
+        ContentType.FORUM_TOPIC_REOPENED,
+        ContentType.GENERAL_FORUM_TOPIC_HIDDEN,
+        ContentType.GENERAL_FORUM_TOPIC_UNHIDDEN,
+        ContentType.NEW_CHAT_MEMBERS,
+        ContentType.LEFT_CHAT_MEMBER,
+        ContentType.NEW_CHAT_TITLE,
+        ContentType.NEW_CHAT_PHOTO,
+        ContentType.DELETE_CHAT_PHOTO,
+        ContentType.PINNED_MESSAGE,
+        ContentType.MESSAGE_AUTO_DELETE_TIMER_CHANGED,
+        ContentType.GROUP_CHAT_CREATED,
+        ContentType.SUPERGROUP_CHAT_CREATED,
+        ContentType.CHANNEL_CHAT_CREATED,
+        ContentType.MIGRATE_TO_CHAT_ID,
+        ContentType.MIGRATE_FROM_CHAT_ID,
+    )
+)
+
+
 @dp.message()
 async def handle_unhandled_message(msg: types.Message):
     content_type, payload = _fallback_payload(msg)
     logger.warning(
         "TG ingress fallback: chat=%s thread=%s message=%s type=%s",
         msg.chat.id,
         msg.message_thread_id,
         msg.message_id,
         content_type,
     )
+    if content_type in _SERVICE_MESSAGE_TYPES:
+        return
     orch_name, session = await _resolve_orch(msg)
     if not session:
         return
     serialized = _serialize_fallback_payload(payload)
     await _send_to_agent(
### cd39b74c9 merge: забрать 38 коммитов контура VPS (#395,#426,#435,#500-#506) в переехавший main

### 43c82f0bd Merge remote-tracking branch 'origin/main'

### afdf03ea0 #450: hide user timestamps in human-facing channels

diff --git a/app/routes/sessions.py b/app/routes/sessions.py
index 08975e86f..8ffc26435 100644
--- a/app/routes/sessions.py
+++ b/app/routes/sessions.py
@@ -32,10 +32,11 @@ from app.errtext import err_text
 from app.events import MessageProvenance
 from app.models import ensure_dashboard_visible, ensure_spawn_allowed, resolve_model, MODELS
 from app.quota_gate import QuotaGateError
 from app.session import AgentStatus
 from app.status_policy import is_internal_telemetry_status
+from app.user_message_display import add_user_message_time_prefix, annotate_user_message
 
 logger = logging.getLogger("orchestra.sessions")
 
 router = APIRouter()
 
@@ -534,11 +535,11 @@ async def stream_session_logs(name: str, scope: str, request: Request, after_id:
         status = (
             live_session.status.value
             if live_session is not None
             else str((stored or {}).get("status") or "idle")
         )
-        result = {**payload, "agent_status": status}
+        result = annotate_user_message({**payload, "agent_status": status})
         if payload.get("type") == "status":
             result["status_hidden"] = is_internal_telemetry_status(
                 str(payload.get("content") or "")
             )
         return result
@@ -601,14 +602,15 @@ async def get_session_logs(name: str, response: Response, scope: str,
     session_id = manager.get_session_id(name, scope)
     if not session_id:
         return JSONResponse({"error": "not found"}, status_code=404)
 
     def annotate(log: dict) -> dict:
-        if log.get("type") != "status":
-            return log
+        result = annotate_user_message(log)
+        if result.get("type") != "status":
+            return result
         return {
-            **log,
+            **result,
             "status_hidden": is_internal_telemetry_status(
                 str(log.get("content") or "")
             ),
         }
 
@@ -643,11 +645,11 @@ async def get_single_log(log_id: int):
     ``sync`` должен достаться своему обработчику, а не свалиться сюда с 422.
     """
     row = get_log(log_id)
     if not row:
         return JSONResponse({"error": "not found"}, status_code=404)
-    return row
+    return annotate_user_message(row)
 
 
 @router.post("/api/fan/open")
 async def open_fan(req: OpenFanRequest):
     """#231 T1: единственный вход в барьер #219 — до этого `open_fan()` не звал никто.
@@ -1134,14 +1136,11 @@ async def send_message(name: str, req: SendRequest, request: Request = None):
             if hasattr(session, 'last_task_sender'):
                 session.last_task_sender = req.sender
         # Время ставится КАЖДОМУ входящему, включая агентские: юзер требует видеть,
         # когда сообщение написано, а не только от кого (28.08). Раньше метку получал
         # только он сам, и в ленте нельзя было отличить свежий отчёт от вчерашнего.
-        from datetime import datetime, timezone, timedelta
-        local_tz = timezone(timedelta(hours=7))
-        now = datetime.now(local_tz).strftime("%H:%M")
-        msg = f"[{now}] {msg}"
+        msg = add_user_message_time_prefix(msg)
         await manager.send(
             session.id, msg, provenance=provenance,
         )
         pn = session.parent_name or ""
         result = {"ok": True, "parent_name": pn}
diff --git a/app/static/js/chat.js b/app/static/js/chat.js
index 9e053788a..4d8b92366 100644
--- a/app/static/js/chat.js
+++ b/app/static/js/chat.js
@@ -4081,14 +4081,17 @@ function addChatEntry(type, content, ts, anchor, payload) {
         const validOrigin = allowedOrigins.has(suppliedOrigin);
         const origin = validOrigin && validDetail ? suppliedOrigin : 'unknown';
         const senders = validOrigin && validDetail
             ? suppliedSenders.map(sender => sender.trim())
             : ['unknown'];
+        const displayContent = payload && typeof payload.display_content === 'string'
+            ? payload.display_content
+            : content;
         if (origin === 'user') {
             div.className += ' markdown-body';
-            div.innerHTML = DOMPurify.sanitize(marked.parse(content));
-            renderImages(div, content);
+            div.innerHTML = DOMPurify.sanitize(marked.parse(displayContent));
+            renderImages(div, displayContent);
         } else {
             const originLabels = {
                 agent: 'Agent',
                 background_task: 'Background task',
                 platform: 'Platform',
@@ -4105,13 +4108,13 @@ function addChatEntry(type, content, ts, anchor, payload) {
             label.style.color = senderColor;
             label.textContent = `${originLabels[origin]}: ${senders.join(', ')} → ${selectedAgent}`;
             div.appendChild(label);
             const body = document.createElement('div');
             body.className = 'markdown-body';
-            body.innerHTML = DOMPurify.sanitize(marked.parse(content));
+            body.innerHTML = DOMPurify.sanitize(marked.parse(displayContent));
             div.appendChild(body);
-            renderImages(body, content);
+            renderImages(body, displayContent);
         }
     }
     else if (type === 'tool') {
         _renderFullToolCall(content, payload, div);
     }
diff --git a/app/tg_bridge.py b/app/tg_bridge.py
index 921ec4175..c64741c18 100644
--- a/app/tg_bridge.py
+++ b/app/tg_bridge.py
@@ -32,10 +32,14 @@ from app.status_policy import is_internal_telemetry_status
 from app.tasks import spawn_supervised
 from app.turn_markers import (
     SILENT_TURN_MARKER as TG_SILENT_TURN_MARKER,
     is_silent_turn_text,
 )
+from app.user_message_display import (
+    add_user_message_time_prefix,
+    user_message_display_content,
+)
 from app.transcription import transcribe_audio as _transcribe_audio
 from app.upload_limits import MAX_UPLOAD_BYTES, MAX_UPLOAD_MB
 
 logger = logging.getLogger("tg-bridge")
 logger.setLevel(logging.DEBUG)
@@ -58,11 +62,11 @@ def _format_user_message_log(log: dict, target_name: str) -> str:
     if not isinstance(detail, dict):
         origin, detail = "unknown", {"senders": ["unknown"]}
     senders = detail.get("senders")
     if not isinstance(senders, list) or not senders:
         origin, senders = "unknown", ["unknown"]
-    content = str(log.get("content") or "")
+    content = user_message_display_content(log)
     if origin == "user":
         return f"👤\n{content}"
     label = ", ".join(str(sender) for sender in senders)
     if origin == "agent":
### f3c2eaaaf merge: забрать 15 коммитов VPS; оглавление базы знаний сведено с обеих сторон
