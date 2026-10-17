# Candidate cand-41

## ORIGIN commit 8d2b1fe7dc (2026-08-27): #370: freeze unknown delivery response oracle
(diff of code only, excluding .orchestra/ and *.md; capped 1200 lines)

diff --git a/app/mcp_stdio.py b/app/mcp_stdio.py
index 73d3b366d..6d959fb92 100644
--- a/app/mcp_stdio.py
+++ b/app/mcp_stdio.py
@@ -1171,16 +1171,34 @@ def _is_message_delivery_receipt(value: Any, delivery_id: str) -> bool:
 
 
 def _message_delivery_receipt_text(
     receipt: dict[str, Any], *, to: str = "", parent_name: str = "",
 ) -> str:
     delivery_id = str(receipt["delivery_id"])
     state = str(receipt.get("delivery_state") or receipt.get("state") or "UNKNOWN")
     target = f" to '{to}'" if to else ""
+    if state == "DELIVERY_UNKNOWN":
+        error = receipt.get("error")
+        code = error.get("code") if isinstance(error, dict) else None
+        message = error.get("message") if isinstance(error, dict) else None
+        code = str(code or "DELIVERY_OUTCOME_UNKNOWN")
+        message = _safe_response_text(str(message or "Provider outcome is unknown"))
+        output = (
+            f"Message delivery outcome is unknown{target}; delivery_id={delivery_id}; "
+            f"code={code}: {message}.\n"
+            f"Check with message_delivery_status(delivery_id=\"{delivery_id}\") "
+            "before acting; if retrying, reuse the same delivery_id and never use a new id."
+        )
+        if parent_name and parent_name != WORKER_NAME:
+            output += (
+                f"\n⚠️ This worker belongs to '{parent_name}'. "
+                f"Consider messaging '{parent_name}' instead."
+            )
+        return output
     output = f"Message accepted{target}; delivery_id={delivery_id}; state={state}."
     if parent_name and parent_name != WORKER_NAME:
         output += (
             f"\n⚠️ This worker belongs to '{parent_name}'. "
             f"Consider messaging '{parent_name}' instead."
         )
     return output
 
diff --git a/tests/test_message_delivery_receipts_380.py b/tests/test_message_delivery_receipts_380.py
index ac1d4211a..54aa624c3 100644
--- a/tests/test_message_delivery_receipts_380.py
+++ b/tests/test_message_delivery_receipts_380.py
@@ -672,16 +672,89 @@ async def test_t380_r3_blank_key_generates_once_before_post_and_status_tool_read
     calls.clear()
     status = await status_tool(DELIVERY_ID)
     assert status == receipt
     assert [(method, path) for method, path, _kwargs in calls] == [
         ("GET", f"/api/message-deliveries/{DELIVERY_ID}"),
     ]
 
 
+@pytest.mark.asyncio
+async def test_t370_unknown_receipt_tells_caller_how_to_check_and_retry_safely(
+    monkeypatch,
+):
+    import app.mcp_stdio as mcp
+
+    monkeypatch.setattr(mcp, "SCOPE", SCOPE)
+    monkeypatch.setattr(mcp, "WORKER_NAME", SOURCE_NAME)
+    unknown = {
+        "ok": True,
+        "acceptance": "ALREADY_ACCEPTED",
+        "delivery_id": DELIVERY_ID,
+        "delivery_state": "DELIVERY_UNKNOWN",
+        "error": {
+            "code": "DELIVERY_OUTCOME_UNKNOWN",
+            "message": "Provider acknowledgement was lost",
+            "outcome_unknown": True,
+        },
+        "next_action": {
+            "code": "CHECK_DELIVERY_STATUS",
+            "tool": "message_delivery_status",
+            "arguments": {"delivery_id": DELIVERY_ID},
+        },
+    }
+
+    async def provider_failure_then_status(method, path, **kwargs):
+        if method == "POST":
+            raise mcp.ApiToolError(
+                code="transport_timeout",
+                message="CodexProtocolError",
+                outcome_unknown=True,
+                details={"method": "POST", "path": path},
+            )
+        assert method == "GET"
+        return unknown
+
+    monkeypatch.setattr(mcp, "_api", provider_failure_then_status)
+    output = await mcp.send_message(
+        to=TARGET_NAME,
+        message=MESSAGE,
+        delivery_id=DELIVERY_ID,
+    )
+
+    assert "DELIVERY_OUTCOME_UNKNOWN" in output
+    assert DELIVERY_ID in output
+    assert f"message_delivery_status(delivery_id=\"{DELIVERY_ID}\")" in output
+    assert "same delivery_id" in output
+    assert "new id" in output
+
+
+@pytest.mark.asyncio
+async def test_t370_same_id_unknown_receipt_is_never_replayed(message_db, monkeypatch):
+    module = _message_module()
+    monkeypatch.setattr(module, "ensure_target_runner", lambda _target_id: None)
+    await _accept(module)
+    prepare = _required_callable(module, "prepare_message_delivery")
+    dispatching = _required_callable(module, "mark_message_delivery_dispatching")
+    unknown = _required_callable(module, "mark_message_delivery_unknown")
+    prepare(DELIVERY_ID)
+    dispatching(DELIVERY_ID)
+    unknown(DELIVERY_ID, RuntimeError("provider acknowledgement lost"))
+
+    repeated, status = await _accept(module)
+    assert status == 202
+    assert repeated["acceptance"] == "ALREADY_ACCEPTED"
+    assert repeated["delivery_state"] == "DELIVERY_UNKNOWN"
+    assert repeated["next_action"]["tool"] == "message_delivery_status"
+
+    manager = _ImmediateManager()
+    await module.run_target_message_deliveries(TARGET_ID, manager=manager)
+    assert manager.provider_attempts == []
+
+
 @pytest.mark.asyncio
 async def test_t380_r4_pre_dispatch_cancel_and_restart_recover_same_receipt_once(
     message_db, monkeypatch,
 ):
     """Known pre-submit cancellation is same-key retryable and restart-safe."""
     module = _message_module()
     monkeypatch.setattr(module, "ensure_target_runner", lambda _target_id: None)
     await _accept(module)


## LATER FIX 9093641f3f (5.1 days later): v2.41.0: аудит кодовой базы — 27 дефектов закрыто (3 P0 в tm.py), 2 фикса откачены как регрессии
lines of origin it changed/deleted: 12
(code only, capped 400 lines)

v2.41.0: аудит кодовой базы — 27 дефектов закрыто (3 P0 в tm.py), 2 фикса откачены как регрессии


diff --git a/app/backend_harness.py b/app/backend_harness.py
index 09600d994..02723e896 100644
--- a/app/backend_harness.py
+++ b/app/backend_harness.py
@@ -93,16 +93,20 @@ class HarnessBackend:
         self._pending_msg: Optional[str] = None
         self._turn_active = False
         self._abort_flag = False
         self._injected: list[str] = []   # steering messages awaiting the next round
 
         self._cumulative_cost: float = 0.0
         self._cumulative_input: int = 0
         self._cumulative_output: int = 0
+        # Cost stays cumulative (session_cost takes its own delta), tokens do NOT: they are
+        # added verbatim to the session totals and to the per-turn turn_usage row. Same
+        # normalization CodexBackend does with _usage_baseline.
+        self._usage_baseline: tuple[int, int] = (0, 0)
 
         # Gated planning (#125) — a per-session todo list; the todo_write tool is hard-gated onto
         # complex (effort=="high") turns only (_turn_tool_schemas). Simple turns never see it.
         self._todos = builtin.TodoStore()
 
     def _turn_tool_schemas(self, effort: str, allow_review: bool = True) -> list[dict]:
         """Tool schemas for THIS turn. `review` (read-only reviewer, #126) is added on parent turns;
         complex turns additionally get todo_write (#125). We never shadow a same-named MCP tool.
@@ -237,24 +241,29 @@ class HarnessBackend:
     async def events(self) -> AsyncIterator[AgentEvent]:
         if self._llm is None or self._mcp is None or self._store is None:
             return
         if not self._turn_active or self._pending_msg is None:
             return
 
         user_msg = self._pending_msg
         self._pending_msg = None
-        self._injected.clear()   # nothing steered yet; leftovers would replay stale text
+        self._usage_baseline = (self._cumulative_input, self._cumulative_output)
+        # Leftovers are steering the previous turn never drained (it ended or aborted past
+        # its last drain point) — session.py already marked them SUBMITTED, so dropping them
+        # loses the text silently. They predate `user_msg`, so the loop puts them AHEAD of it
+        # and labels them: delivered late, but never in the recency slot as the latest word.
+        carried_over = self._drain_injected()
         effort = classify_effort(user_msg, self._is_orchestrator)  # once per turn
         loop = AgentLoop(
             llm=self._llm, mcp=self._mcp, cwd=self.cwd, history=self._history,
             tool_schemas=self._turn_tool_schemas(effort), max_context=self._max_context(),
             abort=lambda: self._abort_flag, effort=effort, todo_store=self._todos,
             allow_review=True, review_ctx=self._review_ctx(),
-            drain_injected=self._drain_injected,
+            drain_injected=self._drain_injected, carried_over=carried_over,
         )
 
         error_out: str | None = None
         try:
             async for ev in loop.run(user_msg):
                 yield ev
         except asyncio.CancelledError:
             # Hard cancel — session.py's finally sets IDLE. Do not yield after this
@@ -327,18 +336,18 @@ class HarnessBackend:
                   detail: str = "") -> AgentEvent:
         usage = loop.last_usage or {}
         turn_input = int(usage.get("prompt_tokens", 0) or 0)
         max_tokens = self._max_context()
         # The last round's prompt_tokens IS the live context: OpenRouter re-sends the whole
         # history each round, so the final prompt carries everything the model still holds.
         turn_usage = TurnUsage(
             AggregateUsage.normalized(
-                input_tokens=self._cumulative_input,
-                output_tokens=self._cumulative_output,
+                input_tokens=self._cumulative_input - self._usage_baseline[0],
+                output_tokens=self._cumulative_output - self._usage_baseline[1],
             ),
             current_context(
                 turn_input or None,
                 max_tokens,
                 unknown_reason="OpenRouter returned no usage for the final round",
             ),
         )
         content = f"stop_reason={stop_reason}" + (f" ({detail})" if detail else "")
@@ -350,22 +359,22 @@ class HarnessBackend:
             "num_turns": 1,
             "cost_usd": self._cumulative_cost,
             "cost_usd_cached": self._cumulative_cost,   # no prompt-cache on MVP
             "cache_hit": 0,
             **turn_usage.metadata(),
         }, usage=turn_usage)
 
     def _error_turn_end(self, reason: str) -> AgentEvent:
-        # Even on error, cost/tokens are the AUTHORITATIVE cumulative — NOT 0 (plan B5),
-        # so session_cost's delta does not overcount the next turn.
+        # Even on error, cost is the AUTHORITATIVE cumulative — NOT 0 (plan B5), so
+        # session_cost's delta does not overcount the next turn. Tokens are this turn's.
         turn_usage = TurnUsage(
             AggregateUsage.normalized(
-                input_tokens=self._cumulative_input,
-                output_tokens=self._cumulative_output,
+                input_tokens=self._cumulative_input - self._usage_baseline[0],
+                output_tokens=self._cumulative_output - self._usage_baseline[1],
             ),
             current_context(
                 None, self._max_context(),
                 unknown_reason=f"turn ended on {reason} before a usage report",
             ),
         )
         return AgentEvent("turn_end", f"stop_reason={reason}", metadata={
             "event_id": str(uuid4()),
diff --git a/app/bg_jobs.py b/app/bg_jobs.py
index a28c7e804..591753ad0 100644
--- a/app/bg_jobs.py
+++ b/app/bg_jobs.py
@@ -498,25 +498,35 @@ class BgJobManager:
         expired_ids = bg_expire_overdue()
         for jid in expired_ids:
             task = self._tasks.pop(jid, None)
             if task and not task.done():
                 task.cancel()
         reset_ids = bg_reset_stale_triggering()
         if reset_ids:
             logger.info(f"bg_jobs: reset {len(reset_ids)} stale triggering jobs")
+        interrupted_delivery = set(reset_ids)
         active = bg_get_active_all()
         restored = 0
         for row in active:
             if row["id"] in self._tasks:
                 continue
             if row["status"] != "active":
                 continue
             config = json.loads(row["config"])
             if row["type"] == "run":
+                if row["id"] in interrupted_delivery:
+                    # 'triggering' у run значит, что команда УЖЕ вышла и рестарт убил
+                    # ДОСТАВКУ её результата: «повторный запуск не выполнялся» здесь ложь,
+                    # а результат лежит в строке. Досылаем его штатным путём триггера.
+                    await self._trigger(
+                        row["id"], row["message"], row["target_name"],
+                        row["target_scope"], row["last_output"],
+                    )
+                    continue
                 await self._interrupt_run_notify(
                     row["id"], row["message"], row["target_name"], row["target_scope"],
                 )
                 continue
             remaining = (datetime.fromisoformat(row["expires_at"]) - datetime.now(timezone.utc)).total_seconds()
             if remaining <= 0:
                 bg_expire_job(row["id"])
                 continue
diff --git a/app/db.py b/app/db.py
index 8bb033649..b35802a03 100644
--- a/app/db.py
+++ b/app/db.py
@@ -1319,25 +1319,37 @@ def _migrate(c) -> None:
     if merge_cols and "accepted_admission_json" not in merge_cols:
         c.execute(
             "ALTER TABLE merge_operations ADD COLUMN "
             "accepted_admission_json TEXT NOT NULL DEFAULT '{}'"
         )
     client_cols = {row[1] for row in c.execute("PRAGMA table_info(tm_clients)").fetchall()}
     if client_cols and "journal_yougile_id" not in client_cols:
         c.execute("ALTER TABLE tm_clients ADD COLUMN journal_yougile_id TEXT DEFAULT ''")
-    if task_cols:
+    if task_cols and not c.execute(
+        "SELECT 1 FROM kv WHERE key='money_units_v1'"
+    ).fetchone():
+        # Однократность держит маркер, а не значения: цена 1..999 — законный ввод
+        # (task_create принимает любое price >= 0), и без маркера сторож повторно
+        # умножал бы живые деньги на 1000 при каждом старте
         max_price = c.execute("SELECT MAX(price_rub) FROM tm_tasks").fetchone()[0] or 0
         if 0 < max_price < 1000:
             # Schema changed from "thousands" to exact kopeks — multiply all money
-            # columns by 1000 to bring old data in line with the new unit
+            # columns by 1000 to bring old data in line with the new unit.
+            # Маркер после ветки одинаков и при срабатывании, и при no-op, поэтому
+            # единственный след умножения живых денег — эта строка журнала
+            logger.warning("money units v1 migration fired: max_price=%s", max_price)
             c.execute("UPDATE tm_tasks SET price_rub = price_rub * 1000, paid_rub = paid_rub * 1000")
             c.execute("UPDATE tm_payment_allocations SET amount_rub = amount_rub * 1000")
             c.execute("UPDATE tm_payments SET amount_rub = amount_rub * 1000")
             c.execute("UPDATE tm_clients SET balance_rub = balance_rub * 1000")
+        c.execute(
+            "INSERT INTO kv(key, value) VALUES('money_units_v1', '1') "
+            "ON CONFLICT(key) DO NOTHING"
+        )
     if "role" not in cols:
         c.execute("ALTER TABLE sessions ADD COLUMN role TEXT DEFAULT 'worker'")
         c.execute("UPDATE sessions SET role = 'orchestrator' WHERE is_orchestrator = 1")
     if "parent_id" not in cols:
         c.execute("ALTER TABLE sessions ADD COLUMN parent_id TEXT DEFAULT ''")
     if "parent_name" not in cols:
         c.execute("ALTER TABLE sessions ADD COLUMN parent_name TEXT DEFAULT ''")
     if "pipeline" not in cols:
@@ -2799,22 +2811,24 @@ def bg_expire_overdue() -> list[str]:
             c.execute(f"UPDATE bg_jobs SET status='expired' WHERE id IN ({placeholders})", ids)
         stale = c.execute(
             "SELECT id FROM bg_jobs WHERE status='triggering' AND triggered_at < ?",
             ((datetime.now(timezone.utc).replace(second=0, microsecond=0)).isoformat(),),
         ).fetchall()
         return ids + [r["id"] for r in stale]
 
 
-def bg_reset_stale_triggering(max_age_seconds: int = 120) -> list[str]:
-    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=max_age_seconds)).isoformat()
+def bg_reset_stale_triggering() -> list[str]:
+    """Зовётся только при старте, где ЛЮБОЙ 'triggering' — сирота: процесс, забравший
+    его через bg_claim_trigger, мёртв. Порог по возрасту оставлял джоб, чей триггер
+    убит рестартом секунды назад, в 'triggering' навсегда: никто больше этот статус
+    не трогает, а слот scope он занимать продолжает.
+    """
     with _conn() as c:
-        rows = c.execute(
-            "SELECT id FROM bg_jobs WHERE status='triggering' AND triggered_at < ?", (cutoff,)
-        ).fetchall()
+        rows = c.execute("SELECT id FROM bg_jobs WHERE status='triggering'").fetchall()
         ids = [r["id"] for r in rows]
         if ids:
             placeholders = ",".join("?" * len(ids))
             c.execute(f"UPDATE bg_jobs SET status='active' WHERE id IN ({placeholders})", ids)
         return ids
 
 
 def bg_reset_wake_triggering() -> list[str]:
diff --git a/app/harness/loop.py b/app/harness/loop.py
index 288cbdd30..5c041ffe1 100644
--- a/app/harness/loop.py
+++ b/app/harness/loop.py
@@ -36,16 +36,17 @@ MAX_TOOL_ROUNDS = 100         # ceiling on tool-call rounds in a single turn (#3
                               # 2× the highest observed demand (>50, censored) on the OLD
                               # lying tools; measured defect-fixes cut rounds up to 4×;
                               # worst case = 10% of the daily OpenRouter budget per turn.
                               # Exhaustion is graceful: two wind-down warnings precede it.
 REVIEW_MAX_ROUNDS = 15        # tighter ceiling for a reviewer sub-loop (#126)
 WIND_DOWN_AT = (10, 3)        # warn the agent N rounds before the cap so it can finish
                               # with a report instead of dying silently (#367)
 CONTEXT_GUARD_RATIO = 0.85    # compact when estimated tokens exceed this × max_context
+CARRIED_OVER_PREFIX = "[carried over from the previous turn — not the latest instruction] "
 BYTES_PER_TOKEN = 3.5         # conservative across ASCII/Cyrillic; no tokenizer dependency
 
 
 class _NoopMCP:
     """MCP stand-in for the read-only reviewer sub-loop — no tools reachable (#126). Ensures the
     reviewer physically cannot call mutating MCP tools (spawn_worker, etc.), beyond the read-only
     schema + dispatch guard (defense in depth)."""
     def has_tool(self, name: str) -> bool:
@@ -66,17 +67,18 @@ class ReviewCtx:
 
 
 class AgentLoop:
     def __init__(self, llm: OpenRouterClient, mcp: MCPClient, cwd: str,
                  history: list[dict], tool_schemas: list[dict], max_context: int,
                  abort: Callable[[], bool] | None = None, effort: str | None = None,
                  todo_store=None, allow_review: bool = False, review_ctx=None,
                  readonly_mode: bool = False, max_rounds: int = MAX_TOOL_ROUNDS,
-                 drain_injected: Callable[[], list[str]] | None = None):
+                 drain_injected: Callable[[], list[str]] | None = None,
+                 carried_over: list[str] | None = None):
         self.llm = llm
         self.mcp = mcp
         self.cwd = cwd
         self.history = history            # full OpenAI-format message list (shared, mutated)
         self.tool_schemas = tool_schemas
         self.max_context = max_context
         self._abort = abort or (lambda: False)
         self.effort = effort              # OpenRouter reasoning effort for this turn (or None)
@@ -85,30 +87,40 @@ class AgentLoop:
         self.allow_review = allow_review  # parent loop → True; reviewer sub-loop → False (depth-1)
         self.review_ctx = review_ctx      # ReviewCtx(llm, cwd, max_context) for the sub-loop, or None
         self.readonly_mode = readonly_mode  # reviewer sub-loop: dispatch rejects non-READONLY tools
         self.max_rounds = max_rounds      # round ceiling (reviewer gets a tighter one)
         # Mid-turn steering: returns messages that arrived while this turn was running.
         # Drained at the TOP of a round, never between an assistant tool_calls message
         # and its tool results — a gap there makes the next request malformed.
         self._drain_injected = drain_injected or (lambda: [])
+        # Steering the PREVIOUS turn never drained. It was written BEFORE this turn's user
+        # message, so it goes into history first and labelled: the last position is the
+        # recency slot and belongs to the newest instruction, not to a stale one.
+        self.carried_over = list(carried_over or [])
         # terminal state read by the backend after run() exhausts
         self.stop_reason = "end_turn"
         self.ok = True
         self.last_usage: dict = {}          # usage of the LAST round (for context_pct)
         # round_usages = the usage dict of EVERY round (a tool turn has many
         # /chat/completions calls). The backend accumulates each round independently so a
         # round with native cost and a round with only tokens are each handled correctly.
         self.round_usages: list[dict] = []
         self.error_detail = ""
         self.truncated_history = False     # set by _fit_context; surfaced as a warning event
         self.truncated_dropped = 0
         self.new_messages: list[dict] = []  # messages produced this turn (for persistence)
 
     async def run(self, user_msg: str) -> AsyncIterator[AgentEvent]:
+        for stale in self.carried_over:
+            entry = {"role": "user", "content": CARRIED_OVER_PREFIX + stale}
+            self.history.append(entry)
+            self.new_messages.append(entry)
+            yield AgentEvent("status", "steering carried over from the previous turn")
+
         user_entry = {"role": "user", "content": user_msg}
         self.history.append(user_entry)
         self.new_messages.append(user_entry)
 
         try:
             for round_no in range(self.max_rounds):
                 remaining = self.max_rounds - round_no
                 if remaining in WIND_DOWN_AT and self.max_rounds > max(WIND_DOWN_AT):
@@ -119,20 +131,17 @@ class AgentLoop:
                     self.new_messages.append(entry)
                     logger.warning(f"round guard: {remaining} rounds left (cap {self.max_rounds})")
                     yield AgentEvent("warning", msg)
 
                 if self._abort():
                     self._terminal("aborted", ok=False, detail="aborted by interrupt")
                     return
 
-                for injected in self._drain_injected():
-                    entry = {"role": "user", "content": injected}
-                    self.history.append(entry)
-                    self.new_messages.append(entry)
+                for _ in self._absorb_injected():
                     yield AgentEvent("status", "message steered into active turn")
 
                 if not self._fit_context():
                     self._terminal("context_limit", ok=False,
                                    detail="history exceeds context window even after truncation")
                     return
                 if self.truncated_history:
                     self.truncated_history = False
@@ -155,16 +164,23 @@ class AgentLoop:
                     self._terminal("error", ok=False, detail=f"llm_error: {e}")
                     return
 
                 self.history.append(assistant_msg)
                 self.new_messages.append(assistant_msg)
 
                 tool_calls = assistant_msg.get("tool_calls") or []
                 if not tool_calls:
+                    # Steering that landed while this round was streaming has no later drain
+                    # point — ending here would strand it. Answer it in this turn instead.
+                    absorbed = self._absorb_injected()
+                    for _ in absorbed:
+                        yield AgentEvent("status", "message steered into active turn")
+                    if absorbed:
+                        continue
                     # No tools requested → turn is done. Normalize the OpenAI "stop"/""
                     # finish to "end_turn" (parity with other backends); pass through other
                     # explicit reasons (e.g. "length", "content_filter").
                     fr = self.stop_reason
                     stop = "end_turn" if fr in ("stop", "tool_calls", "") else fr
                     self._terminal(stop, ok=True)
                     return
 
@@ -189,16 +205,25 @@ class AgentLoop:
         finally:
             # Turn-scoped wind-down guards NEVER persist in the shared session history — a
             # stale "3 rounds remain" in future turns is the same lie this task fights (#367 B3).
             self.history[:] = [m for m in self.history
                                if not str(m.get("content", "")).startswith("[round guard]")]
             self.new_messages[:] = [m for m in self.new_messages
                                     if not str(m.get("content", "")).startswith("[round guard]")]
 
+    def _absorb_injected(self) -> list[str]:
+        """Move steering that arrived mid-turn into history; returns what was absorbed."""
+        taken = self._drain_injected()
+        for injected in taken:
+            entry = {"role": "user", "content": injected}
+            self.history.append(entry)
+            self.new_messages.append(entry)
+        return taken
+
     async def _one_round(self, assistant_msg: dict) -> AsyncIterator[AgentEvent]:
         """Stream one LLM completion. Yields text AgentEvents LIVE (so the session sees
         tokens as they arrive, not buffered to round-end) and fills `assistant_msg`
         in place with content + tool_calls. Accumulates this round's usage into the
         turn totals (every round counts toward the cumulative cost contract)."""
         text_parts: list[str] = []
         tool_calls: list[dict] = []
         reasoning_details: list = []
diff --git a/app/mcp_stdio.py b/app/mcp_stdio.py
index 4cd2a5e9a..28a087e18 100644
--- a/app/mcp_stdio.py
+++ b/app/mcp_stdio.py
@@ -649,18 +649,36 @@ def _delivery_receipt_text(
     name: str,
     model: str,
     mapping: dict[str, str],
     delivery: dict[str, Any],
 ) -> str:
     delivery_id = str(delivery.get("delivery_id") or "?")
     state = str(delivery.get("delivery_state") or delivery.get("state") or "UNKNOWN")
     status_url = str(delivery.get("status_url") or _delivery_status_path(delivery_id))
+    # Сверка после сбоя транспорта возвращает запись в ЛЮБОМ состоянии, включая
+    # терминальный отказ до отправки. «Task accepted» на нём — молчаливая потеря:
+    # воркер создан и стоит без задания, а спавнящий читает приёмку и уходит.
+    if state == "FAILED_BEFORE_SUBMIT":
+        headline = (
+            "Task was NOT delivered — the worker has no task yet. Resend the SAME task "
+            f"text with retry_initial_delivery(name='{name}', delivery_id='{delivery_id}')."
+        )
+    elif state in {"DELIVERY_UNKNOWN", "UNKNOWN"}:
+        # Та же сверка может вернуть запись, чей исход у провайдера неизвестен, — или