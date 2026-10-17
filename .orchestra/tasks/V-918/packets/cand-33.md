# Candidate cand-33

## ORIGIN commit 712254066c (2026-08-05): Merge remote-tracking branch 'origin/main'
(diff of code only, excluding .orchestra/ and *.md; capped 1200 lines)

diff --git a/app/limit_wake.py b/app/limit_wake.py
index a16cbceae..323b06475 100644
--- a/app/limit_wake.py
+++ b/app/limit_wake.py
@@ -21,17 +21,19 @@ from app.session_state import AgentStatus
 logger = logging.getLogger(__name__)
 
 WAKE_ACTION = "wake_subscription_limited"
 WAKE_JOB_PREFIX = "wake-limit-"
 WAKE_STAGGER_SECONDS = 30
 MANUAL_ACTION_URL = "https://claude.ai/settings/usage"
 WAKE_MESSAGE_PREFIX = "[system wake:"
 ANTHROPIC_BASE_WINDOWS = ("five_hour", "seven_day")
+WAKE_AUTO_DEBOUNCE_SECONDS = 60
 _schedule_lock = asyncio.Lock()
+_last_auto_schedule: datetime | None = None
 
 
 def _provider_for_model(model: str) -> str:
     if backend_for_model(model) == "claude":
         return "anthropic"
     if model == "gpt-5.3-codex-spark":
         return "codex_spark"
     return "codex"
@@ -359,16 +361,44 @@ def wake_status() -> dict:
         "manual_action_url": MANUAL_ACTION_URL if monthly else None,
         "scheduled": scheduled,
         "manual": [],
         "unavailable": [],
         "warnings": [],
     }
 
 
+async def schedule_wake_auto() -> None:
+    """Debounced automatic entry point used when a turn ends on a subscription limit.
+
+    The manual dashboard button calls schedule_wake_after_reset directly and is never
+    debounced — a human clicked it deliberately.
+    """
+    global _last_auto_schedule
+    now = datetime.now(timezone.utc)
+    if (
+        _last_auto_schedule is not None
+        and (now - _last_auto_schedule).total_seconds() < WAKE_AUTO_DEBOUNCE_SECONDS
+    ):
+        return
+    # Stamped BEFORE the await: a burst of limited agents lands in one event-loop
+    # tick, and stamping afterwards would let every one of them through into its
+    # own force_refresh of provider usage.
+    _last_auto_schedule = now
+    try:
+        await schedule_wake_after_reset()
+    except Exception as error:
+        # Waking is best-effort and must never break the turn that triggered it.
+        logger.warning(
+            "automatic wake scheduling failed: %s: %s",
+            type(error).__name__,
+            error,
+        )
+
+
 async def schedule_wake_after_reset() -> dict:
     """Freshly classify candidates and atomically replace provider wake timers."""
     from app.bg_jobs import bg_manager
     from app.routes.system import current_provider_usage
 
     async with _schedule_lock:
         agents = _load_limit_stopped_agents()
         existing_jobs = _active_wake_jobs()
diff --git a/app/session_turns.py b/app/session_turns.py
index 00181bd52..1421d1c10 100644
--- a/app/session_turns.py
+++ b/app/session_turns.py
@@ -319,16 +319,17 @@ class TurnManager:
             event_id=event_id,
         )
 
         self.finish_turn_status()
         self.after_turn_idle_actions(
             live_pct,
             allow_auto_report=server_error_retry is None,
             allow_precompact=allow_context_compaction and context_known,
+            subscription_limited=subscription_limited,
         )
         if server_error_retry is not None:
             s._spawn_bg(s._retry_after_server_error(*server_error_retry))
 
     def finish_turn_status(self) -> None:
         """Set IDLE or WAITING based on bg jobs, then persist."""
         s = self.s
         from app.bg_jobs import bg_manager
@@ -339,19 +340,27 @@ class TurnManager:
             s.status = AgentStatus.IDLE
             s.progress_pct = 0
             s.progress_status = ""
         s._persist()
         self.publish_turn_finished()
 
     def after_turn_idle_actions(
             self, live_pct: int, *, allow_auto_report: bool = True,
-            allow_precompact: bool = True) -> None:
+            allow_precompact: bool = True,
+            subscription_limited: bool = False) -> None:
         """Post-turn actions: compact ack, scope idle, auto-compact, auto-report, flush/hibernate."""
         s = self.s
+
+        # finish_turn_status() has already set IDLE/WAITING and persisted, so waking
+        # here can never resume an agent mid-turn.
+        if subscription_limited:
+            from app.limit_wake import schedule_wake_auto
+
+            s._spawn_bg(schedule_wake_auto())
         if s._compact_ack_event is not None and s._turn_gen == s._compact_ack_gen:
             s._compact_ack_event.set()
 
         if allow_precompact:
             self.schedule_context_compaction(live_pct)
         s._spawn_bg(s._notify_scope_idle())
 
         # Don't auto-report mid-flight: WAITING means a bg job (e.g. codex_review) is
diff --git a/tests/test_limit_wake.py b/tests/test_limit_wake.py
index 61f6900bf..bcf0f2766 100644
--- a/tests/test_limit_wake.py
+++ b/tests/test_limit_wake.py
@@ -1135,8 +1135,189 @@ async def test_interrupted_triggering_wake_timer_replays_after_restart(
         "_start_task",
         lambda *args, **kwargs: restored.append((args, kwargs)),
     )
 
     await manager.restore_from_db()
 
     assert len(restored) == 1
     assert restored[0][0][0] == "interrupted-wake"
+
+
+# ── automatic wake trigger (#156) ──
+
+
+@pytest.fixture
+def _reset_auto_debounce():
+    from app import limit_wake
+
+    limit_wake._last_auto_schedule = None
+    yield
+    limit_wake._last_auto_schedule = None
+
+
+@pytest.mark.asyncio
+async def test_auto_wake_debounces_a_burst_into_one_scheduling(
+    monkeypatch, _reset_auto_debounce
+):
+    """A burst of limited agents must trigger exactly one provider refresh."""
+    from app import limit_wake
+
+    calls = []
+    monkeypatch.setattr(
+        limit_wake,
+        "schedule_wake_after_reset",
+        AsyncMock(side_effect=lambda: calls.append(1) or {}),
+    )
+
+    await limit_wake.schedule_wake_auto()
+    await limit_wake.schedule_wake_auto()
+    await limit_wake.schedule_wake_auto()
+
+    assert len(calls) == 1
+
+
+@pytest.mark.asyncio
+async def test_auto_wake_debounce_stamped_before_await_survives_concurrency(
+    monkeypatch, _reset_auto_debounce
+):
+    """Ten agents limited in the same event-loop tick still schedule once."""
+    from app import limit_wake
+
+    calls = []
+
+    async def _slow():
+        calls.append(1)
+        await asyncio.sleep(0.01)
+        return {}
+
+    monkeypatch.setattr(limit_wake, "schedule_wake_after_reset", _slow)
+
+    await asyncio.gather(*(limit_wake.schedule_wake_auto() for _ in range(10)))
+
+    assert len(calls) == 1
+
+
+@pytest.mark.asyncio
+async def test_auto_wake_runs_again_after_the_debounce_window(
+    monkeypatch, _reset_auto_debounce
+):
+    from app import limit_wake
+
+    calls = []
+    monkeypatch.setattr(
+        limit_wake,
+        "schedule_wake_after_reset",
+        AsyncMock(side_effect=lambda: calls.append(1) or {}),
+    )
+
+    await limit_wake.schedule_wake_auto()
+    limit_wake._last_auto_schedule = datetime.now(timezone.utc) - timedelta(
+        seconds=limit_wake.WAKE_AUTO_DEBOUNCE_SECONDS + 1
+    )
+    await limit_wake.schedule_wake_auto()
+
+    assert len(calls) == 2
+
+
+@pytest.mark.asyncio
+async def test_auto_wake_failure_never_propagates_into_the_turn(
+    monkeypatch, _reset_auto_debounce
+):
+    """Waking is best-effort: a scheduling error must not break the finished turn."""
+    from app import limit_wake
+
+    monkeypatch.setattr(
+        limit_wake,
+        "schedule_wake_after_reset",
+        AsyncMock(side_effect=RuntimeError("provider usage unavailable")),
+    )
+
+    await limit_wake.schedule_wake_auto()
+
+
+@pytest.mark.asyncio
+async def test_turn_end_on_limit_wakes_only_after_status_left_running():
+    """The seam must fire after finish_turn_status, never mid-turn."""
+    from app.session_state import AgentStatus
+    from app.session_turns import TurnManager
+
+    observed = {}
+
+    class _Session:
+        status = AgentStatus.RUNNING
+        _compact_ack_event = None
+        _turn_gen = 0
+        _compact_ack_gen = -1
+        _pending_messages = []
+
+        def _spawn_bg(self, coro):
+            name = getattr(coro, "cr_code", None)
+            name = name.co_name if name is not None else ""
+            if name == "schedule_wake_auto":
+                observed["called"] = name
+                observed["status"] = self.status
+            if hasattr(coro, "close"):
+                coro.close()
+
+    session = _Session()
+    session.status = AgentStatus.IDLE  # finish_turn_status() already ran
+    turns = TurnManager.__new__(TurnManager)
+    turns.s = session
+    turns.schedule_context_compaction = lambda _pct: None
+    turns.fire_auto_report = lambda: None
+    session._hibernate = MagicMock()
+    session._notify_scope_idle = lambda: None
+
+    turns.after_turn_idle_actions(10, subscription_limited=True)
+
+    assert observed["called"] == "schedule_wake_auto"
+    assert observed["status"] is not AgentStatus.RUNNING
+
+
+@pytest.mark.asyncio
+async def test_normal_turn_end_does_not_schedule_a_wake():
+    from app.session_state import AgentStatus
+    from app.session_turns import TurnManager
+
+    spawned = []
+
+    class _Session:
+        status = AgentStatus.IDLE
+        _compact_ack_event = None
+        _turn_gen = 0
+        _compact_ack_gen = -1
+        _pending_messages = []
+
+        def _spawn_bg(self, coro):
+            code = getattr(coro, "cr_code", None)
+            spawned.append(code.co_name if code is not None else "")
+            if hasattr(coro, "close"):
+                coro.close()
+
+    session = _Session()
+    turns = TurnManager.__new__(TurnManager)
+    turns.s = session
+    turns.schedule_context_compaction = lambda _pct: None
+    turns.fire_auto_report = lambda: None
+    session._hibernate = MagicMock()
+    session._notify_scope_idle = lambda: None
+
+    turns.after_turn_idle_actions(10)
+
+    assert "schedule_wake_auto" not in spawned
+
+
+def test_subscription_limit_never_takes_the_auto_continue_early_return():
+    """AC from plan review: the seam at 287 must be reachable on a limited turn.
+
+    Measured, not assumed — the branch requires max_turns AND ok=True, while a
+    subscription limit ends the turn with stop_sequence.
+    """
+    import inspect
+
+    from app.session_turns import TurnManager
+
+    source = inspect.getsource(TurnManager.handle_turn_end)
+    branch = source.split("if sr in (\"error_max_turns\", \"max_turns\") and ok:")
+    assert len(branch) == 2, "auto-continue branch shape changed — re-verify the seam"
+    # The early return lives in that branch only; a stop_sequence turn cannot enter it.
+    assert "stop_sequence" not in branch[0]


## LATER FIX 227f843f74 (7.7 days later): #254: #254: repair stale doubles and native canary timeout
lines of origin it changed/deleted: 2
(code only, capped 400 lines)

#254: #254: repair stale doubles and native canary timeout

Squashed commits:
- #254: repair stale doubles and native canary timeout
- #254: record approved test review


diff --git a/tests/test_limit_wake.py b/tests/test_limit_wake.py
index bcf0f2766..d2491dce9 100644
--- a/tests/test_limit_wake.py
+++ b/tests/test_limit_wake.py
@@ -1230,24 +1230,28 @@ async def test_auto_wake_failure_never_propagates_into_the_turn(
         "schedule_wake_after_reset",
         AsyncMock(side_effect=RuntimeError("provider usage unavailable")),
     )
 
     await limit_wake.schedule_wake_auto()
 
 
 @pytest.mark.asyncio
-async def test_turn_end_on_limit_wakes_only_after_status_left_running():
+async def test_turn_end_on_limit_wakes_only_after_status_left_running(monkeypatch):
     """The seam must fire after finish_turn_status, never mid-turn."""
+    from app import mailbox
     from app.session_state import AgentStatus
     from app.session_turns import TurnManager
 
     observed = {}
+    monkeypatch.setattr(mailbox, "claim", lambda _name, _scope: [])
 
     class _Session:
+        name = "limit-worker"
+        scope = "/scope"
         status = AgentStatus.RUNNING
         _compact_ack_event = None
         _turn_gen = 0
         _compact_ack_gen = -1
         _pending_messages = []
 
         def _spawn_bg(self, coro):
             name = getattr(coro, "cr_code", None)
@@ -1269,23 +1273,27 @@ async def test_turn_end_on_limit_wakes_only_after_status_left_running():
 
     turns.after_turn_idle_actions(10, subscription_limited=True)
 
     assert observed["called"] == "schedule_wake_auto"
     assert observed["status"] is not AgentStatus.RUNNING
 
 
 @pytest.mark.asyncio
-async def test_normal_turn_end_does_not_schedule_a_wake():
+async def test_normal_turn_end_does_not_schedule_a_wake(monkeypatch):
+    from app import mailbox
     from app.session_state import AgentStatus
     from app.session_turns import TurnManager
 
     spawned = []
+    monkeypatch.setattr(mailbox, "claim", lambda _name, _scope: [])
 
     class _Session:
+        name = "normal-worker"
+        scope = "/scope"
         status = AgentStatus.IDLE
         _compact_ack_event = None
         _turn_gen = 0
         _compact_ack_gen = -1
         _pending_messages = []
 
         def _spawn_bg(self, coro):
             code = getattr(coro, "cr_code", None)
diff --git a/tests/test_native_history_import.py b/tests/test_native_history_import.py
index 1c9796fea..c45830d89 100644
--- a/tests/test_native_history_import.py
+++ b/tests/test_native_history_import.py
@@ -168,16 +168,17 @@ async def test_canary_collector_stops_at_persistent_claude_turn_end():
             continued.append(True)
             yield SimpleNamespace(type="text", content="next turn", metadata={})
 
     assert await _response_text(Backend()) == "answer"
     assert continued == []
 
 
 @pytest.mark.asyncio
+@pytest.mark.timeout(840)
 @pytest.mark.parametrize("runtime", ["claude", "codex"])
 async def test_pinned_runtime_semantically_recalls_long_native_history(
     runtime, tmp_path, monkeypatch,
 ):
     binary = shutil.which(runtime)
     if binary is None:
         pytest.skip(f"{runtime} binary is not installed")
 
@@ -225,15 +226,15 @@ async def test_pinned_runtime_semantically_recalls_long_native_history(
         )
 
     assert history.report.truncated > 0
     try:
         await asyncio.wait_for(backend.connect(), timeout=180)
         response = await asyncio.wait_for(_ask_for_markers(backend), timeout=600)
     finally:
         if backend is not None:
-            await backend.disconnect()
+            await asyncio.wait_for(backend.disconnect(), timeout=30)
 
     if os.environ.get("R174_PRINT_CANARY_RESPONSE") == "1":
         print("R174_RESPONSE " + json.dumps({"runtime": runtime, "text": response}))
     assert EARLY_USER_MARKER in response
     assert TOOL_RESULT_MARKER in response
     assert SYSTEM_PROMPT_MARKER in response