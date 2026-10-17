# Candidate cand-40

## ORIGIN commit 83eda0e057 (2026-08-13): #241: #241: tag the owner only when the turn calls notify_user
(diff of code only, excluding .orchestra/ and *.md; capped 1200 lines)

diff --git a/.env.example b/.env.example
index bf893424c..769a4c5ba 100644
--- a/.env.example
+++ b/.env.example
@@ -43,18 +43,19 @@ INTERNAL_TOKEN=change-me-use-openssl-rand-hex-32
 # ORCHESTRA_DB_PATH=data/orchestra.db
 
 # Claude CLI path override (optional)
 # CLAUDE_CLI_PATH=/usr/local/bin/claude
 
 # TG Bridge (optional)
 # TG_BRIDGE_TOKEN=your-bot-token
 # TG_BRIDGE_GROUP=-100xxxxxxxxxx
-# Tag this username in agent's messages to you (agent "speech" → 💬), so you get
-# notifications for messages addressed to you (not for agent-to-agent traffic 📨).
+# Who to tag in Telegram when an ORCHESTRATOR explicitly asks for your attention by
+# calling the `notify_user` MCP tool. No call → no tag: silence is the default, so the
+# tag stays a signal instead of firing on every turn.
 # TG_USER_MENTION=@your_username
 
 # Kesha inbox (optional)
 # KESHA_INBOX_URL=http://127.0.0.1:18081
 
 # Deepgram voice transcription (optional)
 # DEEPGRAM_API_KEY=your-api-key
 
diff --git a/app/mcp_stdio.py b/app/mcp_stdio.py
index 3e045d52c..f9c71f0a9 100644
--- a/app/mcp_stdio.py
+++ b/app/mcp_stdio.py
@@ -1242,16 +1242,39 @@ async def send_chart(kind: str, title: str, data: dict, caption: str = "") -> st
         # картинка нарисована и лежит на диске — путь обязан дойти до агента,
         # иначе работа потеряна из-за сбоя доставки
         exc.message = f"{exc.message} | chart kept at {path}"
         exc.details = {**exc.details, "chart_path": path}
         raise
     return f"{sent} | chart: {path}"
 
 
+@mcp.tool()
+async def notify_user(reason: str) -> str:
+    """Дёрнуть юзера тегом в Telegram на границе ЭТОГО хода. Только для оркестраторов.
+
+    Молчание — нормальный режим: без этого вызова тега не будет, и это не забывчивость.
+    Зови, когда юзер обязан узнать СЕЙЧАС: нужно его РЕШЕНИЕ (развилка, которую ты не
+    вправе закрыть сам); ВЫВОД РАЗВЕРНУЛСЯ (сделали не то, о чём договаривались, или
+    отозвано ранее сказанное); ИНЦИДЕНТ на живых системах; РЕЗУЛЬТАТ с числом, меняющий
+    план. НЕ зови на блокеры ревью, мержи, статусы, промежуточные шаги, «воркер
+    начал/закончил» — на это он смотреть не хочет.
+
+    `reason` — одна короткая фраза, ЗАЧЕМ дёрнули; она уедет юзеру вместе с тегом.
+    Тег ставится один раз за ход независимо от числа вызовов.
+    """
+    reason = reason.strip()
+    if not reason:
+        return "notify_user needs a non-empty reason — one short phrase saying WHY."
+    # Тул сознательно ничего не делает: сигналом служит САМА строка вызова в журнале,
+    # которую пишет рантайм, а читает `stream_logs`. Никакого нового контракта
+    # MCP↔route — значит правка доезжает без окна «новый MCP против старого роута».
+    return f"User will be tagged at the end of this turn: {reason}"
+
+
 @mcp.tool()
 async def update_progress(percent: int, status: str) -> str:
     """Update task progress. percent: 0-100, status: short description of current step."""
     result = await _api("POST", f"/api/sessions/{WORKER_NAME}/progress", json={
         "percent": percent, "status": status, "scope": SCOPE,
     })
     if isinstance(result, dict) and result.get("error"):
         return f"Progress update failed: {result['error']}"
diff --git a/app/tg_bridge.py b/app/tg_bridge.py
index 25c7f9d7b..63eb2dd25 100644
--- a/app/tg_bridge.py
+++ b/app/tg_bridge.py
@@ -90,31 +90,58 @@ _media_cache: dict[str, str] = _load_media_cache()
 
 def _media_name(prefix: str, ext: str, msg: types.Message) -> str:
     ts = msg.date.strftime("%Y%m%d_%H%M%S") if msg.date else str(msg.message_id)
     return f"{prefix}_{ts}_{msg.message_id}{ext}"
 
 
 UPLOADS_MAX_BYTES = int(os.getenv("UPLOADS_MAX_MB", "1024")) * 1024 * 1024
 
-# @mention of the owner, fired once per ORCHESTRATOR turn on the turn boundary (#158),
-# so a TG push arrives exactly when an orchestrator stopped and is waiting for an answer.
-# Accepts "@username" or a numeric user_id; the id renders as a tg:// text_mention and
-# notifies even when the username does not resolve for the bot.
+# @mention of the owner, delivered on the ORCHESTRATOR turn boundary (#158) so a TG push
+# arrives exactly when an orchestrator stopped — but only when that turn explicitly asked
+# for it (#241). Accepts "@username" or a numeric user_id; the id renders as a tg://
+# text_mention and notifies even when the username does not resolve for the bot.
 TG_USER_MENTION = os.getenv("TG_USER_MENTION", "").strip()
 
 # Exact protocol token: broadening this match can silently hide real user-facing text.
 TG_SILENT_TURN_MARKER = "[[ORCHESTRA:SILENT_TURN]]"
 
+# Единственный повод дёрнуть юзера (#241). Признак СТРУКТУРНЫЙ — строка журнала должна
+# БЫТЬ вызовом тула (`type == "tool"` + это имя в колонке `tool_name`), а не текстом,
+# который имя упоминает: иначе тегает любой, кто объясняет устройство тега (замер #161).
+TG_NOTIFY_TOOL = "mcp__orchestra__notify_user"
+TG_NOTIFY_REASON_MAX = 200
 
-def _mention_markup(mention: str) -> str:
-    """Markdown for the owner mention. Numeric → tg:// link (reliable), else @username."""
-    if mention.lstrip("-").isdigit():
-        return f"[⬆️ ответь](tg://user?id={mention})"
-    return f"⬆️ {mention}"
+
+def _mention_markup(mention: str, reason: str = "") -> str:
+    """Markdown for the owner mention. Numeric → tg:// link (reliable), else @username.
+
+    `reason` из `notify_user` объясняет, ЗАЧЕМ дёрнули, и обрезается: тег — это сигнал,
+    а полный текст причины и так лежит в журнале строкой вызова тула.
+    """
+    head = (f"[⬆️ ответь](tg://user?id={mention})" if mention.lstrip("-").isdigit()
+            else f"⬆️ {mention}")
+    reason = " ".join(reason.split())
+    if len(reason) > TG_NOTIFY_REASON_MAX:
+        reason = reason[:TG_NOTIFY_REASON_MAX].rstrip() + "…"
+    return f"{head} — {reason}" if reason else head
+
+
+def _notify_reason_from_args(content: str) -> str:
+    """`reason` из аргументов вызова `notify_user`.
+
+    Разбор — побочная услуга: тег определяется САМИМ фактом вызова, поэтому нечитаемые
+    аргументы дают тег без причины. Потеря тега здесь была бы проглоченной просьбой —
+    единственное опасное направление отказа в этой задаче.
+    """
+    _, _, raw = content.partition(":")
+    try:
+        return str(json.loads(raw).get("reason") or "").strip()
+    except Exception:
+        return ""
 
 
 def _cleanup_uploads():
     files = [f for f in UPLOADS_DIR.iterdir() if f.is_file() and not f.name.startswith(".")]
     total = sum(f.stat().st_size for f in files)
     if total <= UPLOADS_MAX_BYTES:
         return
     files.sort(key=lambda f: f.stat().st_mtime)
@@ -3027,17 +3054,19 @@ async def stream_logs(orch_name: str, thread_id: int):
     # Dedicated connection per stream loop — avoids sharing state with the request threads
     _poll_conn = _conn()
     logs = get_logs(session_id, after_id=0, conn=_poll_conn)
     last_id = logs[-1]["id"] if logs else 0
     turn = _TurnState()
     # Отметка «якорь по этой строке уже ушёл» живёт ВНЕ состояния хода: состояние
     # обнуляется на границе, а откат курсора переигрывает саму строку `turn ended`.
     _anchor_sent_for = None
-    _spoke_this_turn = False          # был ли текст юзеру в текущем ходе
+    # None — `notify_user` в текущем ходе не звали, значит тега не будет. Строка (пусть
+    # и пустая) — звали, и тег обязателен: молчание это дефолт, а не забывчивость.
+    _notify_reason = None
     _pending_turn_end_mention = False
     _idle_ticks = 0
     current_log_previous_id = last_id
 
     try:
         while True:
             try:
                 logs = get_logs(session_id, after_id=last_id, conn=_poll_conn)
@@ -3078,30 +3107,31 @@ async def stream_logs(orch_name: str, thread_id: int):
                             text = f"📨 {prefix}\n{body}"
                         else:
                             text = f"👤\n{c}" if c.startswith("> ") else f"👤 {c}"
                     elif t == "text":
                         if c == TG_SILENT_TURN_MARKER:
                             continue
                         from app.tool_call_guard import mark_unexecuted_tool_call
 
-                        _spoke_this_turn = True
                         await _update_progress(turn, thread_id, orch_name, force=True)
                         turn.new_block()
                         raw_text = f"💬\n{mark_unexecuted_tool_call(c)}"
                         for converted, aio_ents in _formatted_chunks(raw_text):
                             await _tg_send_safe(
                                 config["group_id"], converted, thread_id,
                                 entities=aio_ents, important=True,
                             )
                             await _mirror_send(
                                 orch_name, converted, entities=aio_ents, important=True,
                             )
                         continue
                     elif t == "tool":
+                        if log.get("tool_name") == TG_NOTIFY_TOOL:
+                            _notify_reason = _notify_reason_from_args(c)
                         tool_name = c.split(":")[0].strip() if ":" in c else "tool"
                         tool_body = c[len(tool_name) + 1:].strip() if ":" in c else c
                         turn.add(log["id"], _tool_line(tool_name, tool_body),
                                  log.get("tool_use_id") or "")
                         turn.raw[log["id"]] = tool_body
                         turn.names[log["id"]] = tool_name
                         await _update_progress(turn, thread_id, orch_name)
                         continue
@@ -3138,17 +3168,19 @@ async def stream_logs(orch_name: str, thread_id: int):
                         if "turn ended" in c:
                             still_running = _any_running_in_scope(scope)
                             if not still_running:
                                 _schedule_topic_status(orch_name, False)
                             # Граница хода — единственная durable-разметка «агент договорил»:
                             # на самой строке text её нет, мост стримит журнал вперёд и в
                             # момент отправки не знает, будет ли ещё текст (живой замер:
                             # 4777 из 6161 строк text — промежуточные).
-                            _pending_turn_end_mention = is_orch and _spoke_this_turn
+                            _pending_turn_end_mention = (
+                                is_orch and _notify_reason is not None
+                            )
                             await _update_progress(turn, thread_id, orch_name,
                                                    force=True)
                             if _anchor_sent_for == log["id"]:
                                 # Якорь по этой строке уже ушёл, а строка переигралась.
                                 # Пропускаем ТОЛЬКО повтор якоря: дальше по строке живёт
                                 # тег владельца, и `continue` здесь терял бы его молча.
                                 text = ""
                             else:
@@ -3200,27 +3232,28 @@ async def stream_logs(orch_name: str, thread_id: int):
                             important=is_important,
                         )
                     if _pending_turn_end_mention:
                         # Отдельным сообщением, а не хвостом к ⚡: status идёт по
                         # косметической полосе (important=False) и может быть дропнут,
                         # а дропнутое уведомление хуже отсутствующего.
                         if TG_USER_MENTION:
                             for converted, aio_ents in _formatted_chunks(
-                                _mention_markup(TG_USER_MENTION)
+                                _mention_markup(TG_USER_MENTION, _notify_reason or "")
                             ):
                                 await _tg_send_safe(
                                     config["group_id"], converted, thread_id,
                                     entities=aio_ents, important=True,
                                 )
                         # Флаги гасим только ПОСЛЕ доставки: перегрузка откатывает
                         # курсор и переигрывает строки хода, а сброшенный раньше
-                        # времени _spoke_this_turn дал бы на повторе тихую потерю тега.
+                        # времени _notify_reason дал бы на повторе тихую потерю тега —
+                        # строка вызова тула во второй раз уже не проиграется.
                         _pending_turn_end_mention = False
-                        _spoke_this_turn = False
+                        _notify_reason = None
             except _TgDeliveryOverloaded as e:
                 last_id = current_log_previous_id
                 logger.error(
                     f"Stream backpressure for {orch_name}, retaining cursor "
                     f"{last_id}: {e}"
                 )
                 _idle_ticks = 0
             except Exception as e:
diff --git a/tests/test_tg_bridge.py b/tests/test_tg_bridge.py
index e724f2825..4ff57b1b2 100644
--- a/tests/test_tg_bridge.py
+++ b/tests/test_tg_bridge.py
@@ -4013,24 +4013,37 @@ class TestBackgroundSubagentFilter:
             " | type= | id=a1d116686cc8ce | tool_use_id=toolu_01X5 | status=stopped"
         )
 
     def test_unparseable_content_is_kept(self, tb):
         """Unknown shape → announce it; silently dropping delegation is worse."""
         assert not tb._is_background_subagent("something unexpected")
 
 
+def _notify_row(log_id: int, reason: str = "развилка: два пути, оба ломают учёт",
+                tool_name: str = "mcp__orchestra__notify_user", args: str | None = None):
+    """Строка журнала о РЕАЛЬНОМ вызове notify_user — как её пишет рантайм."""
+    body = args if args is not None else json.dumps({"reason": reason}, ensure_ascii=False)
+    return {
+        "id": log_id,
+        "type": "tool",
+        "tool_name": tool_name,
+        "tool_use_id": f"notify-{log_id}",
+        "content": f"{tool_name}: {body}",
+    }
+
+
 class TestTurnEndMention:
-    """@mention юзера на ФИНАЛЬНОМ сообщении хода оркестратора (#158).
+    """ГДЕ и КАК уходит тег владельца. Условие «когда» переехало в #241 — оно живёт
+    в `TestNotifyUserMention`, здесь остались только общие для обоих правил свойства.
 
     Разметки «финальное сообщение» на строке `text` НЕТ и быть не может: мост
     стримит журнал вперёд и в момент отправки текста не знает, будет ли ещё один.
     Живой замер (1384 хода оркестраторов): 4777 из 6161 строк `text` —
-    промежуточные, то есть тег на каждом `text` = тег почти на всём подряд.
-    Границу хода даёт отдельная durable-строка `status: turn ended (...)`,
+    промежуточные. Границу хода даёт отдельная durable-строка `status: turn ended (...)`,
     которую мост и так читает. Тег уходит на ней — отдельным important-сообщением,
     потому что сам `status` идёт по косметической полосе и может быть дропнут.
     """
 
     def test_mention_renders_as_clickable_entity_for_numeric_id(self, tb):
         """user_id → text_link `tg://user?id=`: уведомление приходит даже если
         username не резолвится. Проверяем сущность, а не подстроку."""
         converted, entities = tb._formatted_chunks(tb._mention_markup("123456"))[0]
@@ -4088,30 +4101,16 @@ class TestTurnEndMention:
         monkeypatch.setattr(tb, "_tg_send_safe", tg_send_safe)
         monkeypatch.setattr(tb, "_mirror_send", mirror_send)
         monkeypatch.setattr(tb.asyncio, "sleep", no_sleep)
 
         with pytest.raises(asyncio.CancelledError):
             await tb.stream_logs("orch", 42)
         return (sent, mirrored) if capture_mirror else sent
 
-    @pytest.mark.asyncio
-    async def test_orchestrator_final_message_is_mentioned(self, tb, monkeypatch):
-        sent = await self._run(tb, monkeypatch, [
-            {"id": 1, "type": "text", "content": "промежуточный шаг"},
-            {"id": 2, "type": "text", "content": "готово, жду ответа"},
-            {"id": 3, "type": "status", "content": "turn ended (end_turn, 4 turns, $0.10 turn)"},
-        ])
-        mentions = [m for m in sent if "@DrSeedon" in m["text"]]
-        assert len(mentions) == 1, sent
-        # Тег обязан ехать по надёжной полосе: important=False молча дропается.
-        assert mentions[0]["important"] is True
-        # И только ПОСЛЕ финального текста, иначе уведомление опережает содержание.
-        assert sent.index(mentions[0]) == len(sent) - 1
-
     @pytest.mark.asyncio
     async def test_intermediate_messages_carry_no_mention(self, tb, monkeypatch):
         """Ход ещё не кончился — тега нет вообще."""
         sent = await self._run(tb, monkeypatch, [
             {"id": 1, "type": "text", "content": "работаю"},
             {"id": 2, "type": "tool", "content": 'Bash: {"command":"ls"}'},
         ])
         assert not [m for m in sent if "@DrSeedon" in m["text"]]
@@ -4120,24 +4119,16 @@ class TestTurnEndMention:
     async def test_worker_turn_end_is_not_mentioned(self, tb, monkeypatch):
         """Воркеры шлют оркестратору, а не юзеру — дёргать его нечем."""
         sent = await self._run(tb, monkeypatch, [
             {"id": 1, "type": "text", "content": "DONE #1"},
             {"id": 2, "type": "status", "content": "turn ended (end_turn, 2 turns, $0.01 turn)"},
         ], role="worker")
         assert not [m for m in sent if "@DrSeedon" in m["text"]]
 
-    @pytest.mark.asyncio
-    async def test_sub_orchestrator_is_mentioned(self, tb, monkeypatch):
-        sent = await self._run(tb, monkeypatch, [
-            {"id": 1, "type": "text", "content": "фаза закрыта"},
-            {"id": 2, "type": "status", "content": "turn ended (end_turn, 1 turns, $0.01 turn)"},
-        ], role="sub-orchestrator")
-        assert len([m for m in sent if "@DrSeedon" in m["text"]]) == 1
-
     @pytest.mark.asyncio
     async def test_turn_without_speech_is_not_mentioned(self, tb, monkeypatch):
         """Ход кончился, но юзеру ничего не сказали — уведомлять не о чем."""
         sent = await self._run(tb, monkeypatch, [
             {"id": 1, "type": "tool", "content": 'Bash: {"command":"ls"}'},
             {"id": 2, "type": "status", "content": "turn ended (end_turn, 1 turns, $0.01 turn)"},
         ])
         assert not [m for m in sent if "@DrSeedon" in m["text"]]
@@ -4196,96 +4187,59 @@ class TestTurnEndMention:
             "id": 1,
             "type": log_type,
             "content": "[[ORCHESTRA:SILENT_TURN]]",
         }])
 
         assert len(sent) == 1
         assert sent[0]["text"].startswith(prefix)
 
-    @pytest.mark.asyncio
-    async def test_two_turns_give_two_mentions(self, tb, monkeypatch):
-        """Счётчик речи сбрасывается на границе — второй ход тегается заново."""
-        sent = await self._run(tb, monkeypatch, [
-            {"id": 1, "type": "text", "content": "первый ответ"},
-            {"id": 2, "type": "status", "content": "turn ended (end_turn, 1 turns, $0.01 turn)"},
-            {"id": 3, "type": "text", "content": "второй ответ"},
-            {"id": 4, "type": "status", "content": "turn ended (end_turn, 1 turns, $0.02 turn)"},
-        ])
-        assert len([m for m in sent if "@DrSeedon" in m["text"]]) == 2
-
-    @pytest.mark.asyncio
-    async def test_silent_turn_after_a_speaking_turn_is_not_mentioned(
-        self, tb, monkeypatch,
-    ):
-        """Флаг речи обязан сбрасываться на границе.
-
-        Без сброса «оркестратор» и «был текст» остаются истинными от ПРОШЛОГО хода,
-        и молчаливый ход (только тулы — типовой ход воркер-менеджмента) дёргает юзера
-        зря. Прочие условия здесь помочь не могут: они оба уже true.
-        """
-        sent = await self._run(tb, monkeypatch, [
-            {"id": 1, "type": "text", "content": "ответ юзеру"},
-            {"id": 2, "type": "status", "content": "turn ended (end_turn, 1 turns, $0.01 turn)"},
-            {"id": 3, "type": "tool", "content": 'Bash: {"command":"ls"}'},
-            {"id": 4, "type": "status", "content": "turn ended (end_turn, 1 turns, $0.02 turn)"},
-        ])
-        assert len([m for m in sent if "@DrSeedon" in m["text"]]) == 1
-
-    @pytest.mark.asyncio
-    async def test_no_mention_configured_sends_nothing_extra(self, tb, monkeypatch):
-        sent = await self._run(tb, monkeypatch, [
-            {"id": 1, "type": "text", "content": "готово"},
-            {"id": 2, "type": "status", "content": "turn ended (end_turn, 1 turns, $0.01 turn)"},
-        ], mention="")
-        assert len(sent) == 2
-
     @pytest.mark.asyncio
     async def test_agent_speech_itself_is_not_tagged(self, tb, monkeypatch):
         """Регресс на прежнее поведение: тег на КАЖДОЙ строке text (78% из них —
         промежуточные) заменён тегом на границе хода."""
         sent = await self._run(tb, monkeypatch, [
             {"id": 1, "type": "text", "content": "шаг"},
         ])
         assert sent and "@DrSeedon" not in sent[0]["text"]
 
     @pytest.mark.asyncio
-    async def test_mention_survives_backpressure_replay(self, tb, monkeypatch):
-        """Перегрузка на ⚡ откатывает курсор и ПЕРЕИГРЫВАЕТ строки хода.
+    async def test_replay_after_mention_does_not_duplicate_it(self, tb, monkeypatch):
+        """Перегрузка на строке ПОСЛЕ тега не должна слать тег дважды.
 
-        Флаг речи к этому моменту уже сброшен первым проходом, поэтому наивная
-        реализация на повторе вычисляет `is_orch and False` и молча теряет тег —
-        ровно тот ход, ради которого юзер и просил уведомление.
+        Курсор откатывается на начало пачки, но `turn ended` уже переигран не будет:
+        рассылка идёт по строкам с id > last_id, а он сдвинут за границу хода.
         """
         class FakeConn:
             def close(self):
                 pass
 
         rows = [
-            {"id": 1, "type": "text", "content": "готово, жду ответа"},
+            _notify_row(1, reason="нужно решение"),
             {"id": 2, "type": "status", "content": "turn ended (end_turn, 1 turns, $0.01 turn)"},
+            {"id": 3, "type": "error", "content": "後из фона"},
         ]
         calls = 0
 
         def get_logs(session_id, after_id=0, conn=None):
             nonlocal calls
             calls += 1
             if calls == 1:
                 return []
             if calls in (2, 3):
                 return [r for r in rows if r["id"] > after_id]
             raise asyncio.CancelledError
 
         sent = []
-        overloaded_once = False
+        failed_once = False
 
         async def tg_send_safe(chat_id, text, thread_id, entities=None, important=False, **kw):
-            nonlocal overloaded_once
-            if text.startswith("⚡") and not overloaded_once:
-                overloaded_once = True
+            nonlocal failed_once
+            if text.startswith("❌") and not failed_once:
+                failed_once = True
                 raise tb._TgDeliveryOverloaded("queue full")
             sent.append({"text": text, "important": important})
 
         async def no_sleep(_delay):
             return None
 
         monkeypatch.setattr(tb, "TG_USER_MENTION", "@DrSeedon")
         monkeypatch.setattr(
@@ -4303,50 +4257,189 @@ class TestTurnEndMention:
         monkeypatch.setattr(tb, "_mirror_send", AsyncMock())
         monkeypatch.setattr(tb.asyncio, "sleep", no_sleep)
 
         with pytest.raises(asyncio.CancelledError):
             await tb.stream_logs("orch", 42)
 
         assert len([m for m in sent if "@DrSeedon" in m["text"]]) == 1, sent
 
+
+class TestNotifyUserMention:
+    """#241: тег приходит ТОЛЬКО по явному вызову `notify_user` в этом ходе.
+
+    Прежнее правило (#158) тегало на КАЖДОЙ границе хода оркестратора, где был текст,
+    то есть и на рутине — сигнал «посмотри» обесценился. Теперь молчание это дефолт.
+    Направление отказа: забыл вызвать → юзер прочитает позже (вреда нет); вызвал зря →
+    прежнее шумное поведение. Опасного направления (проглотить явную просьбу) нет.
+    """
+
+    # staticmethod(...) обязателен: голая ссылка на функцию в теле класса становится
+    # методом, и `self` уезжает в аргумент `tb` — тесты падают до единой проверки.
+    _run = staticmethod(TestTurnEndMention._run)
+    _END = {"id": 90, "type": "status",
+            "content": "turn ended (end_turn, 1 turns, $0.01 turn)"}
+
     @pytest.mark.asyncio
-    async def test_replay_after_mention_does_not_duplicate_it(self, tb, monkeypatch):
-        """Перегрузка на строке ПОСЛЕ тега не должна слать тег дважды.
+    async def test_notify_call_mentions_and_shows_its_reason(self, tb, monkeypatch):
+        sent = await self._run(tb, monkeypatch, [
+            _notify_row(1, reason="кеш падает 93.6% → 15%"),
+            {"id": 2, "type": "text", "content": "замер закончен"},
+            dict(self._END),
+        ])
 
-        Курсор откатывается на начало пачки, но `turn ended` уже переигран не будет:
-        рассылка идёт по строкам с id > last_id, а он сдвинут за границу хода.
+        mentions = [m for m in sent if "@DrSeedon" in m["text"]]
+        assert len(mentions) == 1, sent
+        assert "кеш падает 93.6% → 15%" in mentions[0]["text"]
+        # Надёжная полоса: important=False молча дропается под нагрузкой.
+        assert mentions[0]["important"] is True
+        # И только ПОСЛЕ содержания, иначе уведомление опережает то, ради чего оно.
+        assert sent.index(mentions[0]) == len(sent) - 1
+
+    @pytest.mark.asyncio
+    async def test_turn_without_notify_call_is_not_mentioned(self, tb, monkeypatch):
+        """Ядро #241: текст в ходе БОЛЬШЕ не является поводом дёрнуть юзера."""
+        sent = await self._run(tb, monkeypatch, [
+            {"id": 1, "type": "text", "content": "промежуточный шаг"},
+            {"id": 2, "type": "text", "content": "готово, жду ответа"},
+            dict(self._END),
+        ])
+
+        assert sent, "ход без тула всё равно обязан доставить свой текст"
+        assert not [m for m in sent if "@DrSeedon" in m["text"]]
+
+    @pytest.mark.asyncio
+    async def test_sub_orchestrator_notify_call_is_mentioned(self, tb, monkeypatch):
+        """Суб-оркестратор тоже разговаривает с юзером — гейт по роли его пускает."""
+        sent = await self._run(tb, monkeypatch, [
+            _notify_row(1, reason="фаза закрыта, нужен выбор"),
+            dict(self._END),
+        ], role="sub-orchestrator")
+
+        mentions = [m for m in sent if "@DrSeedon" in m["text"]]
+        assert len(mentions) == 1, sent
+        assert "фаза закрыта, нужен выбор" in mentions[0]["text"]
+
+    @pytest.mark.asyncio
+    async def test_worker_notify_call_never_mentions(self, tb, monkeypatch):
+        """Воркеры отчитываются оркестратору; тул у них есть, но тега быть не должно."""
+        sent = await self._run(tb, monkeypatch, [
+            _notify_row(1),
+            {"id": 2, "type": "text", "content": "DONE #241"},
+            dict(self._END),
+        ], role="worker")
+
+        assert not [m for m in sent if "@DrSeedon" in m["text"]]
+
+    @pytest.mark.asyncio
+    async def test_quoting_the_tool_name_in_text_does_not_mention(self, tb, monkeypatch):
+        """Признак — СТРУКТУРНЫЙ: строка журнала ЕСТЬ вызов тула.
+
+        Классификатор по имени тула в тексте тегал бы любого, кто это имя цитирует, —
+        а объяснять устройство тега агенты будут именно текстом (замер #161).
+        """
+        quoted = _notify_row(1)["content"]
+        sent = await self._run(tb, monkeypatch, [
+            {"id": 1, "type": "text", "content": f"зови так: {quoted}"},
+            {"id": 2, "type": "user_message", "content": quoted},
+            dict(self._END),
+        ])
+
+        assert not [m for m in sent if "@DrSeedon" in m["text"]]
+
+    @pytest.mark.asyncio
+    async def test_another_orchestra_tool_does_not_mention(self, tb, monkeypatch):
+        sent = await self._run(tb, monkeypatch, [
+            _notify_row(1, tool_name="mcp__orchestra__send_message"),
+            dict(self._END),
+        ])
+
+        assert not [m for m in sent if "@DrSeedon" in m["text"]]
+
+    @pytest.mark.asyncio
+    async def test_unreadable_args_still_mention_without_reason(self, tb, monkeypatch):
+        """Разбор аргументов — побочная услуга; сигналом является САМ вызов.
+
+        Потерять тег из-за нечитаемого `reason` значит проглотить явную просьбу —
+        единственное по-настоящему опасное направление в этой задаче.
+        """
+        sent = await self._run(tb, monkeypatch, [
+            _notify_row(1, args="{oops not json"),
+            dict(self._END),
+        ])
+
+        assert len([m for m in sent if "@DrSeedon" in m["text"]]) == 1, sent
+
+    @pytest.mark.asyncio
+    async def test_next_turn_without_notify_is_not_mentioned(self, tb, monkeypatch):
+        """Признак вызова обязан гаснуть на границе, иначе один вызов тегает навсегда."""
+        sent = await self._run(tb, monkeypatch, [
+            _notify_row(1, reason="первый"),
+            {"id": 2, "type": "text", "content": "ответ"},
+            {"id": 3, "type": "status",
+             "content": "turn ended (end_turn, 1 turns, $0.01 turn)"},
+            {"id": 4, "type": "text", "content": "рутина следующего хода"},
+            {"id": 5, "type": "status",
+             "content": "turn ended (end_turn, 1 turns, $0.02 turn)"},
+        ])
+
+        mentions = [m for m in sent if "@DrSeedon" in m["text"]]
+        assert len(mentions) == 1, sent
+        assert "первый" in mentions[0]["text"]
+
+    @pytest.mark.asyncio
+    async def test_two_notified_turns_give_two_mentions(self, tb, monkeypatch):
+        sent = await self._run(tb, monkeypatch, [
+            _notify_row(1, reason="первый"),
+            {"id": 2, "type": "status",
+             "content": "turn ended (end_turn, 1 turns, $0.01 turn)"},
+            _notify_row(3, reason="второй"),
+            {"id": 4, "type": "status",
+             "content": "turn ended (end_turn, 1 turns, $0.02 turn)"},
+        ])
+
+        mentions = [m["text"] for m in sent if "@DrSeedon" in m["text"]]
+        assert len(mentions) == 2, sent
+        assert "первый" in mentions[0] and "второй" in mentions[1]
+
+    @pytest.mark.asyncio
+    async def test_mention_survives_backpressure_replay(self, tb, monkeypatch):
+        """Перегрузка на ⚡ откатывает курсор и ПЕРЕИГРЫВАЕТ строки хода.
+
+        Признак вызова к этому моменту гасить нельзя: на повторе тул уже не переиграется,
+        и наивная реализация молча потеряла бы ровно тот тег, ради которого её писали.
         """
         class FakeConn:
             def close(self):
                 pass
 
         rows = [
-            {"id": 1, "type": "text", "content": "готово"},
-            {"id": 2, "type": "status", "content": "turn ended (end_turn, 1 turns, $0.01 turn)"},
-            {"id": 3, "type": "error", "content": "後из фона"},
+            _notify_row(1, reason="инцидент на живой"),
+            {"id": 2, "type": "text", "content": "подробности"},
+            {"id": 3, "type": "status",
+             "content": "turn ended (end_turn, 1 turns, $0.01 turn)"},
         ]
         calls = 0
 
         def get_logs(session_id, after_id=0, conn=None):
             nonlocal calls
             calls += 1
             if calls == 1:
                 return []
             if calls in (2, 3):
                 return [r for r in rows if r["id"] > after_id]
             raise asyncio.CancelledError
 
         sent = []
-        failed_once = False
+        overloaded_once = False
 
         async def tg_send_safe(chat_id, text, thread_id, entities=None, important=False, **kw):
-            nonlocal failed_once
-            if text.startswith("❌") and not failed_once:
-                failed_once = True
+            nonlocal overloaded_once
+            if text.startswith("⚡") and not overloaded_once:
+                overloaded_once = True
                 raise tb._TgDeliveryOverloaded("queue full")
             sent.append({"text": text, "important": important})
 
         async def no_sleep(_delay):
             return None
 
         monkeypatch.setattr(tb, "TG_USER_MENTION", "@DrSeedon")
         monkeypatch.setattr(
@@ -4362,17 +4455,39 @@ class TestTurnEndMention:
         monkeypatch.setattr(tb, "_any_running_in_scope", lambda scope: False)
         monkeypatch.setattr(tb, "_tg_send_safe", tg_send_safe)
         monkeypatch.setattr(tb, "_mirror_send", AsyncMock())
         monkeypatch.setattr(tb.asyncio, "sleep", no_sleep)
 
         with pytest.raises(asyncio.CancelledError):
             await tb.stream_logs("orch", 42)
 
-        assert len([m for m in sent if "@DrSeedon" in m["text"]]) == 1, sent
+        mentions = [m for m in sent if "@DrSeedon" in m["text"]]
+        assert len(mentions) == 1, sent
+        assert "инцидент на живой" in mentions[0]["text"]
+
+    @pytest.mark.asyncio
+    async def test_no_mention_configured_sends_nothing_extra(self, tb, monkeypatch):
+        sent = await self._run(tb, monkeypatch, [
+            _notify_row(1),
+            {"id": 2, "type": "text", "content": "готово"},
+            dict(self._END),
+        ], mention="")
+
+        # Считаем не длину (её задаёт свёртка хода), а факт: пустого тега нет, и
+        # последним ушёл якорь — после него ничего не дописано.
+        assert not [m for m in sent if "⬆️" in m["text"]]
+        assert sent[-1]["text"].startswith("━")
+
+    def test_reason_is_bounded_in_the_mention_line(self, tb):
+        """Причина едет юзеру ЦЕЛИКОМ в журнал, но в тег — обрезанной: тег это сигнал."""
+        line = tb._mention_markup("@DrSeedon", "д" * 400)
+
+        assert len(line) < 300
+        assert "…" in line
 
 
 # ── #189: свёртка хода — строка на действие, ⚙️ и якорь ────────────────────
 # Тела тулов взяты ДОСЛОВНО из живого журнала (logs.id 54910, 54916 и правка из
 # сессии back): выдуманный пример здесь бесполезен — экранирование `\"` появляется
 # именно у настоящей обёртки `/bin/bash -lc "..."`, которую пишет Codex.
 LIVE_BASH_SED = (
     'Bash: {"command": "/bin/bash -lc \\"sed -n \'1,260p\' '
@@ -4731,18 +4846,19 @@ class TestTurnFoldStream:
         assert "🌐 GPT-5.6-Cyber  2.9 КБ ✓" in final, final
 
     @pytest.mark.asyncio
     async def test_mention_survives_replay_of_an_already_sent_anchor(self, tb, monkeypatch):
         """Якорь ушёл, зеркало упало, строка переигралась. Пропустить надо ТОЛЬКО
         повтор якоря: тег владельца живёт дальше по той же строке журнала."""
         monkeypatch.setattr(tb, "TG_USER_MENTION", "@DrSeedon")
         batch = [
-            {"id": 1, "type": "text", "content": "готово, жду ответа"},
-            {"id": 2, "type": "status",
+            _notify_row(1, reason="жду ответа"),
+            {"id": 2, "type": "text", "content": "готово, жду ответа"},
+            {"id": 3, "type": "status",
              "content": "turn ended (end_turn, 0 turns, $1.60 turn)"},
         ]
         sent, _, _ = await self._run(
             tb, monkeypatch, [batch, batch], overload_after_anchor=True,
         )
         anchors = [m for m in sent if m["text"].startswith("━")]
         mentions = [m for m in sent if "@DrSeedon" in m["text"]]
         assert len(anchors) == 1, anchors


## LATER FIX f4b7d9acde (10.8 days later): fix(prompts): suppress notify tags for active users
lines of origin it changed/deleted: 5
(code only, capped 400 lines)

fix(prompts): suppress notify tags for active users


diff --git a/app/mcp_stdio.py b/app/mcp_stdio.py
index 866ab5ba4..5852a3123 100644
--- a/app/mcp_stdio.py
+++ b/app/mcp_stdio.py
@@ -1613,21 +1613,23 @@ async def send_chart(kind: str, title: str, data: dict, caption: str = "") -> st
     return f"{sent} | chart: {path}"
 
 
 @mcp.tool()
 async def notify_user(reason: str) -> str:
     """Дёрнуть юзера тегом в Telegram на границе ЭТОГО хода. Только для оркестраторов.
 
     Молчание — нормальный режим: без этого вызова тега не будет, и это не забывчивость.
-    Зови, когда юзер обязан узнать СЕЙЧАС: нужно его РЕШЕНИЕ (развилка, которую ты не
-    вправе закрыть сам); ВЫВОД РАЗВЕРНУЛСЯ (сделали не то, о чём договаривались, или
-    отозвано ранее сказанное); ИНЦИДЕНТ на живых системах; РЕЗУЛЬТАТ с числом, меняющий
-    план. НЕ зови на блокеры ревью, мержи, статусы, промежуточные шаги, «воркер
-    начал/закончил» — на это он смотреть не хочет.
+    СНАЧАЛА recency gate: НЕ зови, если юзер сам начал текущий ход, написал сообщение
+    во время хода или писал последние 10 минут. Он уже смотрит — обычного ответа достаточно.
+    Зови после долгой/фоновой работы, когда юзер ушёл и должен вернуться: нужно его РЕШЕНИЕ
+    (развилка, которую ты не вправе закрыть сам); ВЫВОД РАЗВЕРНУЛСЯ (сделали не то, о чём
+    договаривались, или отозвано ранее сказанное); ИНЦИДЕНТ на живых системах; РЕЗУЛЬТАТ
+    с числом, меняющий план. НЕ зови на блокеры ревью, мержи, статусы, промежуточные шаги,
+    «воркер начал/закончил» — на это он смотреть не хочет.
 
     `reason` — одна короткая фраза, ЗАЧЕМ дёрнули; она уедет юзеру вместе с тегом.
     Тег ставится один раз за ход независимо от числа вызовов.
     """
     reason = reason.strip()
     if not reason:
         return "notify_user needs a non-empty reason — one short phrase saying WHY."
     # Тул сознательно ничего не делает: сигналом служит САМА строка вызова в журнале,