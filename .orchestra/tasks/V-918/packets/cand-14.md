# Candidate cand-14

## ORIGIN commit e1d694a586 (2026-06-24): feat: auto-retry on rate_limit errors — 3 retries with 30/60/90s backoff
(diff of code only, excluding .orchestra/ and *.md; capped 1200 lines)

diff --git a/app/session.py b/app/session.py
index 6359d27b4..7903b3650 100644
--- a/app/session.py
+++ b/app/session.py
@@ -171,19 +171,22 @@ class AgentSession:
     _last_stop_reason: str = field(default="", repr=False)
     _lifecycle_lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)
     _persist_task: Optional[asyncio.Task] = field(default=None, repr=False)
     _persist_dirty: bool = field(default=False, repr=False)
     _turn_gen: int = field(default=0, repr=False)
     _auto_report_task: Optional[asyncio.Task] = field(default=None, repr=False)
     _spawn_warning: str = field(default="", repr=False)
     _auto_continue_count: int = field(default=0, repr=False)
+    _rate_limit_retries: int = field(default=0, repr=False)
 
     TURN_TIMEOUT = 600
     AUTO_CONTINUE_MAX = 5
+    RATE_LIMIT_MAX_RETRIES = 3
+    RATE_LIMIT_DELAY = 30
 
     def __post_init__(self) -> None:
         # Systems over state (ECS): cost/turn/hibernate methods live in systems,
         # all fields stay on the session (persistence reads them directly)
         self._cost = CostTracker(self)
         self._turns = TurnManager(self)
         self._hibernate = HibernateManager(self)
 
@@ -539,16 +542,24 @@ class AgentSession:
             self._log("tool_result", event.content)
         elif event.type == "file_change":
             self._log("tool", f"file: {event.content}")
             self._turn_logs.append(f"[tool] file: {event.content[:60]}")
         elif event.type == "turn_end":
             self._turns.handle_turn_end(event)
         elif event.type == "error":
             self._log("error", event.content)
+            if "rate_limit" in event.content:
+                if self._rate_limit_retries < self.RATE_LIMIT_MAX_RETRIES:
+                    self._rate_limit_retries += 1
+                    delay = self.RATE_LIMIT_DELAY * self._rate_limit_retries
+                    self._log("status", f"rate limited — retry {self._rate_limit_retries}/{self.RATE_LIMIT_MAX_RETRIES} in {delay}s")
+                    self._spawn_bg(self._rate_limit_retry(delay))
+                else:
+                    self._log("error", f"rate limit — gave up after {self.RATE_LIMIT_MAX_RETRIES} retries")
         elif event.type == "subagent_start":
             self._log("subagent_start", event.content)
         elif event.type == "subagent_progress":
             self._log("subagent_progress", event.content)
         elif event.type == "subagent_end":
             self._log("subagent_end", event.content)
         elif event.type == "status":
             self._log("status", event.content)
@@ -751,16 +762,26 @@ class AgentSession:
     async def _notify_scope_running(self) -> None:
         if on_scope_running is None:
             return
         try:
             await on_scope_running(self)
         except Exception as e:
             logger.warning(f"[{self.name}] TG scope-running notify failed: {e}")
 
+    async def _rate_limit_retry(self, delay: int) -> None:
+        await asyncio.sleep(delay)
+        try:
+            await self.send("[system] Retrying after rate limit. Continue where you left off.")
+            logger.info(f"[{self.name}] rate-limit retry after {delay}s")
+        except Exception as e:
+            logger.warning(f"[{self.name}] rate-limit retry failed: {e}")
+            self.status = AgentStatus.IDLE
+            self._persist()
+
     async def _auto_continue(self) -> None:
         await asyncio.sleep(1)
         try:
             await self.send("[system] Turn limit reached. Continue where you left off.")
             logger.info(f"[{self.name}] auto-continue after max_turns")
         except Exception as e:
             logger.warning(f"[{self.name}] auto-continue failed: {e}")
             self.status = AgentStatus.IDLE
diff --git a/app/session_turns.py b/app/session_turns.py
index 98a872599..01db2e1c6 100644
--- a/app/session_turns.py
+++ b/app/session_turns.py
@@ -82,16 +82,17 @@ class TurnManager:
             else:
                 s._auto_continue_count += 1
                 s._log("status", f"{sr} ({nt} turns), auto-continuing "
                                  f"({s._auto_continue_count}/{s.AUTO_CONTINUE_MAX})")
                 s._spawn_bg(s._auto_continue())
                 return
         else:
             s._auto_continue_count = 0
+            s._rate_limit_retries = 0
 
         live_pct = s._last_context.get("percentage", 0)
         ctx_s = f"ctx:{live_pct}%" if live_pct else ""
         def _fc(v):
             return f"{v:.4f}" if v < 0.01 and v > 0 else f"{v:.2f}"
         s._log("status", f"turn ended ({sr}, {nt} turns, ${_fc(s._turn_cost)} turn, ${_fc(s._context_cost)} ctx, ${_fc(s._session_cost)} session, ${_fc(s.cost_usd)} total {ctx_s})")
 
         self.finish_turn_status()


## LATER FIX 42e0352e8b (72.8 days later): fix: fence stale retries and isolate dashboard recovery failures
lines of origin it changed/deleted: 3
(code only, capped 400 lines)

fix: fence stale retries and isolate dashboard recovery failures


diff --git a/app/session.py b/app/session.py
index 165af7f81..2f1237e80 100644
--- a/app/session.py
+++ b/app/session.py
@@ -1279,17 +1279,17 @@ class AgentSession:
         self._last_text_output = None
         self._turn_start = asyncio.get_event_loop().time()
         self._last_msg_time = self._turn_start
         self.status = AgentStatus.RUNNING
         self._persist()
 
     async def send(
         self, message: str | InjectedMessage, *, provenance: MessageProvenance,
-        delivery=None,
+        delivery=None, retry_generation: tuple[int, int] | None = None,
     ) -> None:
         if isinstance(message, InjectedMessage) and message.provenance != provenance:
             raise ValueError("injected message provenance mismatch")
         message_event_id = message.event_id if isinstance(message, InjectedMessage) else ""
         message = message.text if isinstance(message, InjectedMessage) else message
         original_user_message = message
         history_user_message = original_user_message
         if delivery is not None:
@@ -1302,16 +1302,26 @@ class AgentSession:
         if allow_running_delivery and self._compacting:
             return
         decision = None
         admitted_model = ""
         admitted_stop_gen = -1
 
         while True:
             await self._lifecycle_lock.acquire()
+            # Recheck after admission too: Stop or a newer turn can win while
+            # this sender is outside the lock waiting for quota data.
+            if retry_generation is not None and (
+                retry_generation != (self._turn_gen, self._turn_start_cancel_gen)
+                or self._manually_interrupted
+                or self.status != AgentStatus.IDLE
+                or self._compacting
+            ):
+                self._lifecycle_lock.release()
+                return
             if self._handoff_recovery_required:
                 self._lifecycle_lock.release()
                 raise RuntimeError(
                     "handoff_recovery_required: operator recovery is required before sends"
                 )
             if self._compacting or self.status == AgentStatus.RUNNING or self.is_orchestrator:
                 break
             if decision is None:
@@ -1346,22 +1356,22 @@ class AgentSession:
 
         try:
             if (
                 delivery is not None
                 and not allow_running_delivery
                 and (self._compacting or self.status == AgentStatus.RUNNING)
             ):
                 raise RuntimeError("initial delivery requires an idle session")
-        # Retry budgets belong to one logical request. A real new message resets both;
-        # each internal retry preserves only its own failure class.
-            if provenance.subtype != "rate_limit_retry":
+            # Both failure classes share the logical request: alternating upstream
+            # errors must not replenish each other's retry budget.
+            if provenance.subtype not in {"rate_limit_retry", "server_error_retry"}:
                 self._rate_limit_retries = 0
-            if provenance.subtype != "server_error_retry":
                 self._server_error_retries = 0
+            if provenance.subtype != "server_error_retry":
                 self._session_limit_hit = False
             self._safeguard_refusal = ""
 
             self._note_next_precompact_activity()
             capabilities = get_runtime(self.backend_type).capabilities
             if self._compacting:
                 if delivery is not None and allow_running_delivery:
                     return
@@ -2525,17 +2535,17 @@ class AgentSession:
             if "rate_limit" in event.content:
                 # Terminal subscription/usage limits — never retry
                 if self._session_limit_hit or _is_terminal_subscription_limit(event.content):
                     self._log("error", "⏳ subscription limit — ждём сброса квоты. НЕ ретраим")
                 elif self._rate_limit_retries < self.RATE_LIMIT_MAX_RETRIES:
                     self._rate_limit_retries += 1
                     delay = self.RATE_LIMIT_DELAY * self._rate_limit_retries
                     self._log("status", f"⏳ rate limit (Anthropic сервер) — повтор через {delay}s ({self._rate_limit_retries}/{self.RATE_LIMIT_MAX_RETRIES})")
-                    self._spawn_bg(self._rate_limit_retry(delay))
+                    self._spawn_bg(self._rate_limit_retry(delay, self._turn_gen))
                 else:
                     self._log("error", f"rate limit — gave up after {self.RATE_LIMIT_MAX_RETRIES} retries")
             else:
                 self._log("error", event.content)
         elif event.type == "subagent_start":
             self._log("subagent_start", event.content)
             self._persist_subagent(event.metadata)
         elif event.type == "subagent_progress":
@@ -3204,69 +3214,84 @@ class AgentSession:
     async def _notify_scope_running(self) -> None:
         if on_scope_running is None:
             return
         try:
             await on_scope_running(self)
         except Exception as e:
             logger.warning(f"[{self.name}] TG scope-running notify failed: {e}")
 
-    async def _rate_limit_retry(self, delay: int) -> None:
+    async def _rate_limit_retry(self, delay: int, expected_turn_gen: int) -> None:
+        generation = (expected_turn_gen, self._turn_start_cancel_gen)
         await asyncio.sleep(delay)
+        if self._manually_interrupted or self._turn_gen != expected_turn_gen:
+            return
         try:
             provenance = MessageProvenance(
                 origin="system", senders=("system",), subtype="rate_limit_retry",
             )
             await self.send(
                 "[system] Retrying after rate limit. Continue where you left off.",
                 provenance=provenance,
+                retry_generation=generation,
             )
-            logger.info(f"[{self.name}] rate-limit retry after {delay}s")
         except DrainingRefused as refusal:
+            if generation != (self._turn_gen, self._turn_start_cancel_gen):
+                return
             self._log("status", f"drain: {refusal}")
             self.status = AgentStatus.IDLE
             self._persist()
             self._turns.publish_turn_finished()
             self._queue_drain_fact("rate-limit-retry", "повтор после rate limit срезан")
         except Exception as e:
             logger.warning(f"[{self.name}] rate-limit retry failed: {e}")
+            if generation != (self._turn_gen, self._turn_start_cancel_gen):
+                return
             self.status = AgentStatus.IDLE
             self._persist()
             self._turns.publish_turn_finished()
 
     async def _retry_after_server_error(self, delay: int, expected_turn_gen: int) -> None:
         """Resume through a fresh SDK transport after an upstream stream failure."""
+        generation = (expected_turn_gen, self._turn_start_cancel_gen)
         await asyncio.sleep(delay)
         try:
             async with self._lifecycle_lock:
                 # A real user message already started a newer turn; it supersedes this
                 # automatic retry and must not be duplicated.
-                if self._turn_gen != expected_turn_gen or self.status != AgentStatus.IDLE:
+                if (self._manually_interrupted
+                        or self._turn_gen != expected_turn_gen
+                        or self.status != AgentStatus.IDLE
+                        or self._compacting):
                     return
                 await self._disconnect_backend()
             provenance = MessageProvenance(
                 origin="system", senders=("system",), subtype="server_error_retry",
             )
             await self.send(
                 "[system] Retrying after transient server error. Continue where you "
                 "left off. Do not repeat completed research; execute the pending "
                 "deliverable now.",
                 provenance=provenance,
+                retry_generation=generation,
             )
-            logger.info(f"[{self.name}] server-error retry after {delay}s")
         except DrainingRefused as refusal:
+            if generation != (self._turn_gen, self._turn_start_cancel_gen):
+                return
             self._log("status", f"drain: {refusal}")
             self.status = AgentStatus.IDLE
             self._persist()
             self._turns.publish_turn_finished()
             self._queue_drain_fact(
                 "server-error-retry", "повтор после сбоя апстрима срезан",
             )
         except Exception as e:
             logger.warning(f"[{self.name}] server-error retry failed: {e}")
+            if generation != (self._turn_gen, self._turn_start_cancel_gen):
+                return
             self.status = AgentStatus.IDLE
             self._persist()
             self._turns.publish_turn_finished()
 
     async def _auto_continue(self) -> None:
         await asyncio.sleep(1)
         try:
             provenance = MessageProvenance(
diff --git a/app/static/js/connection.js b/app/static/js/connection.js
index a87e38f97..adc30ff91 100644
--- a/app/static/js/connection.js
+++ b/app/static/js/connection.js
@@ -227,33 +227,53 @@ window.Connection = (() => {
             set('online');
         } else render();
     }
 
     async function recover() {
         if (recovering) return;
         recovering = true;
         const reason = state.reason;
-        set('recovering', {reason});
-        restartPending = false;
-        const restartBtn = document.getElementById('restart-btn');
-        if (restartBtn) { restartBtn.disabled = false; restartBtn.textContent = '⟳'; }
-        resetChatTransientState();
-        const calls = [
-            selectedAgent && currentScope ? _showChatFor(selectedAgent, currentScope) : null,
-            refreshSessions(), loadOrchestrators(), loadModels(), refreshOpenFolders(),
-            fetchUsage(), window.QuotaPanel?.fetch?.(),
-        ].filter(Boolean);
         try {
-            await Promise.allSettled(calls);
+            set('recovering', {reason});
+            restartPending = false;
+            const restartBtn = document.getElementById('restart-btn');
+            if (restartBtn) { restartBtn.disabled = false; restartBtn.textContent = '⟳'; }
+            // Defer invocation as well as awaiting: one synchronous renderer error
+            // must not prevent the other surfaces from recovering.
+            const refreshes = [
+                ['chat', () => {
+                    resetChatTransientState();
+                    return selectedAgent && currentScope
+                        ? _showChatFor(selectedAgent, currentScope) : null;
+                }],
+                ['sessions', () => refreshSessions()],
+                ['orchestrators', () => loadOrchestrators()],
+                ['models', () => loadModels()],
+                ['files', () => refreshOpenFolders()],
+                ['usage', () => fetchUsage()],
+                ['quota', () => window.QuotaPanel?.fetch?.()],
+            ];
+            const results = await Promise.allSettled(
+                refreshes.map(([, refresh]) => Promise.resolve().then(refresh)),
+            );
+            const errors = [];
+            results.forEach((result, index) => {
+                const key = `recovery/${refreshes[index][0]}`;
+                if (result.status === 'rejected') {
+                    state.failures.set(key, {error: result.reason, at: Date.now()});
+                    errors.push(`${refreshes[index][0]}: ${String(result.reason)}`);
+                } else state.failures.delete(key);
+            });
             wasDown = false;
             if (state.failures.size || state.stale.size) {
                 set('degraded', {
                     reason: 'partial_recovery',
                     path: state.failures.keys().next().value || '',
+                    message: errors.length ? `Не удалось обновить: ${errors.join('; ')}` : '',
                 });
                 return;
             }
             const flash = reason === 'restart'
                 ? 'Orchestra перезапустилась · данные обновлены'
                 : 'Связь восстановлена · данные обновлены';
             set('online', {reason: '', path: '', flash});
             state.flashTimer = setTimeout(() => {
diff --git a/tests/test_connection_recovery.py b/tests/test_connection_recovery.py
new file mode 100644
index 000000000..6aec0765f
--- /dev/null
+++ b/tests/test_connection_recovery.py
@@ -0,0 +1,60 @@
+"""Recovery errors cannot strand the dashboard or prevent other refreshes."""
+
+from pathlib import Path
+
+import pytest
+from playwright.sync_api import sync_playwright
+
+
+@pytest.fixture(scope="module")
+def recovery_browser():
+    with sync_playwright() as playwright:
+        browser = playwright.chromium.launch(headless=True)
+        yield browser
+        browser.close()
+
+
+@pytest.mark.parametrize("failure", ["sync", "async", "chat_reset"])
+def test_recovery_isolates_failure_and_can_run_again(recovery_browser, failure):
+    page = recovery_browser.new_page()
+    try:
+        page.set_content("<body><div id='connection-banner'></div></body>")
+        page.evaluate("""() => {
+            window.escHtml = text => String(text);
+            window.selectedAgent = 'worker'; window.currentScope = '/scope';
+            window.resetChatTransientState = () => {};
+            window._showChatFor = async () => {};
+            window.refreshSessions = async () => {};
+            window.loadOrchestrators = async () => {};
+            window.loadModels = async () => {};
+            window.refreshOpenFolders = async () => {};
+            window.fetchUsage = async () => {};
+        }""")
+        page.add_script_tag(path=str(
+            Path(__file__).parents[1] / "app/static/js/connection.js"
+        ))
+        result = page.evaluate("""async failure => {
+            const calls = [];
+            refreshSessions = async () => { calls.push('sessions'); };
+            refreshOpenFolders = async () => { calls.push('files'); };
+            const broken = () => { throw new Error('refresh exploded'); };
+            if (failure === 'sync') fetchUsage = broken;
+            if (failure === 'async') fetchUsage = async () => broken();
+            if (failure === 'chat_reset') resetChatTransientState = broken;
+            let escaped = '';
+            try { await Connection.recover(); } catch (error) { escaped = error.message; }
+            const first = {phase: Connection.state.phase, calls: [...calls],
+                banner: document.getElementById('connection-banner').textContent};
+            fetchUsage = async () => {};
+            resetChatTransientState = () => {};
+            await Connection.recover();
+            return {escaped, first, calls, phase: Connection.state.phase};
+        }""", failure)
+        assert result["escaped"] == ""
+        assert result["first"]["phase"] == "degraded"
+        assert result["first"]["calls"] == ["sessions", "files"]
+        assert "refresh exploded" in result["first"]["banner"]
+        assert result["calls"] == ["sessions", "files", "sessions", "files"]
+        assert result["phase"] == "online"
+    finally:
+        page.close()
diff --git a/tests/test_hot_apply.py b/tests/test_hot_apply.py
index 283046dc3..1ea2b9940 100644
--- a/tests/test_hot_apply.py
+++ b/tests/test_hot_apply.py
@@ -296,17 +296,17 @@ async def test_t2_internal_starter_queues_a_fact_instead_of_starting(
     _gate(manager)()
     try:
         with patch.object(s, "_make_backend", return_value=backend):
             # у каждого стартера свои аргументы; задержки нулевые, чтобы тест
             # не подрабатывал измерением времени
             args = {
                 "_flush_pending": (),
                 "_auto_continue": (),
-                "_rate_limit_retry": (0,),
+                "_rate_limit_retry": (0, s._turn_gen),
                 "_retry_after_server_error": (0, s._turn_gen),
             }[starter]
             await asyncio.wait_for(getattr(s, starter)(*args), timeout=10)
     finally:
         manager.end_drain()
 
     assert s.status is AgentStatus.IDLE, "ход не начат"
     assert backend.sent == [], "в бэкенд ничего не ушло"
diff --git a/tests/test_session.py b/tests/test_session.py
index 698b0fe9c..a4c719bbd 100644
--- a/tests/test_session.py
+++ b/tests/test_session.py
@@ -3129,16 +3129,110 @@ class TestRateLimitClassification:
         session.send.reset_mock()
         session._turn_gen = 5
 
         await session._retry_after_server_error(0, 4)
 
         session._disconnect_backend.assert_not_awaited()
         session.send.assert_not_awaited()
 
+    @pytest.mark.asyncio
+    @pytest.mark.parametrize("kind", ["server_error", "rate_limit"])
+    async def test_manual_stop_cancels_waiting_retry(self, session, monkeypatch, kind):
+        from app.session import AgentStatus
+
+        sleeping = asyncio.Event()
+        resume = asyncio.Event()
+
+        async def controlled_sleep(_delay):
+            sleeping.set()
+            await resume.wait()
+
+        monkeypatch.setattr("app.session.asyncio.sleep", controlled_sleep)
+        session.status = AgentStatus.IDLE
+        session._disconnect_backend = AsyncMock()
+        session.send = AsyncMock()
+        coroutine = (session._retry_after_server_error(5, session._turn_gen)
+                     if kind == "server_error" else session._rate_limit_retry(5, session._turn_gen))
+        retry = asyncio.create_task(coroutine)
+        try:
+            await sleeping.wait()
+            await session.interrupt()
+            resume.set()
+            await retry
+            session.send.assert_not_awaited()
+            session._disconnect_backend.assert_not_awaited()
+        finally:
+            resume.set()
+            retry.cancel()
+            await asyncio.gather(retry, return_exceptions=True)
+
+
+class TestRetryAdmissionRaces:
+    @pytest.mark.asyncio
+    async def test_alternating_retry_types_preserve_both_budgets(self, session):
+        from app.session import AgentStatus
+
+        backend = _MockBackend()
+        session._ensure_backend = AsyncMock(return_value=backend)
+        session._attach_pending_facts = lambda message: (message, ())
+        session._ack_pending_facts = lambda _keys: None