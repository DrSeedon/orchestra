# Context for item-20

## Diff reviewed (-U20, capped at 1500 lines)

diff --git a/app/session_turns.py b/app/session_turns.py
index a6361b81f..26c3dede4 100644
--- a/app/session_turns.py
+++ b/app/session_turns.py
@@ -179,78 +179,40 @@ def _cached_quota_snapshot(
     if all(value is None for key, value in state.items() if key != "quota_sampled_at"):
         return _unknown_quota_snapshot()
     try:
         state["quota_sampled_at"] = datetime.fromtimestamp(
             sampled_ts, timezone.utc,
         ).isoformat()
     except (OSError, OverflowError, ValueError):
         return _unknown_quota_snapshot()
     return {"state": state, "display": display}
 
 
 def _cached_quota_state(
     runtime: str,
     model: str,
     *,
     now: float | None = None,
 ) -> dict:
     return _cached_quota_snapshot(runtime, model, now=now)["state"]
 
 
-def _format_limits(snapshot: dict, *, now: float | None = None) -> str:
-    checked_at = time.time() if now is None else now
-    parts = []
-    for label, window in snapshot.get("display", ()):
-        if not isinstance(window, dict):
-            continue
-        utilization = window.get("utilization")
-        if (
-            isinstance(utilization, bool)
-            or not isinstance(utilization, (int, float))
-            or not math.isfinite(utilization)
-            or not 0 <= utilization <= 100
-        ):
-            continue
-        reset_s = ""
-        reset_at = window.get("resets_at")
-        if reset_at:
-            try:
-                reset = datetime.fromisoformat(str(reset_at).replace("Z", "+00:00"))
-                if reset.tzinfo is None:
-                    raise ValueError("timezone missing")
-                remaining = reset.timestamp() - checked_at
-                if remaining > 0:
-                    if remaining >= 86400:
-                        days, remainder = divmod(int(remaining), 86400)
-                        reset_s = f" reset {days}d{remainder // 3600}h"
-                    else:
-                        hours, minutes = divmod(int(remaining) // 60, 60)
-                        reset_s = f" reset {hours}h{minutes:02d}m"
-            except (OSError, OverflowError, TypeError, ValueError) as error:
-                logger.debug(
-                    "%s resets_at unparsable (%r): %s: %s",
-                    label, reset_at, type(error).__name__, error,
-                )
-        parts.append(f"{label}:{utilization:g}%{reset_s}")
-    return " | " + " ".join(parts) if parts else ""
-
-
 class TurnManager:
     def __init__(self, s: "AgentSession") -> None:
         self.s = s
 
     def cancel_auto_report(self) -> None:
         s = self.s
         if s._auto_report_task and not s._auto_report_task.done():
             s._auto_report_task.cancel()
         s._auto_report_task = None
 
     def bump_turn_gen(self) -> None:
         """Новый ход начался — инвалидируем отложенный авто-репорт прошлого хода."""
         self.s._turn_gen += 1
         self.s._turn_finished_event.clear()
         self.cancel_auto_report()
 
     def publish_turn_finished(self) -> None:
         self.s._turn_finished_event.set()
 
     def fire_auto_report(self) -> None:
@@ -462,51 +424,50 @@ class TurnManager:
         if not ok and model_error == "server_error":
             if s._server_error_retries < s.SERVER_ERROR_MAX_RETRIES:
                 s._server_error_retries += 1
                 delay = s.SERVER_ERROR_RETRY_DELAY * s._server_error_retries
                 server_error_retry = (delay, s._turn_gen)
                 s._log(
                     "status",
                     f"transient server_error — fresh-backend retry in {delay}s "
                     f"({s._server_error_retries}/{s.SERVER_ERROR_MAX_RETRIES})",
                 )
             else:
                 s._log(
                     "error",
                     f"server_error — gave up after {s.SERVER_ERROR_MAX_RETRIES} retries",
                 )
 
         live_pct = s._last_context.get("percentage", 0)
         ctx_s = f"ctx:{live_pct}%" if live_pct else ""
         def _fc(v):
             return f"{v:.4f}" if v < 0.01 and v > 0 else f"{v:.2f}"
-        limits_s = _format_limits(quota_snapshot)
         if cost_unaccounted:
             cost_summary = f"cost unaccounted for {s.model}"
         else:
             cost_summary = (
                 f"${_fc(s._turn_cost)} turn, ${_fc(s._context_cost)} ctx, "
                 f"${_fc(s._session_cost)} session, ${_fc(s.cost_usd)} total"
             )
         s._log(
             "status",
-            f"turn ended ({sr}, {nt} turns, {cost_summary} {ctx_s}){limits_s}",
+            f"turn ended ({sr}, {nt} turns, {cost_summary} {ctx_s})",
             event_id=event_id,
         )
 
         self.finish_turn_status()
         self.after_turn_idle_actions(
             live_pct,
             allow_auto_report=server_error_retry is None,
             allow_precompact=allow_context_compaction and context_known,
             subscription_limited=subscription_limited,
         )
         if server_error_retry is not None:
             s._spawn_bg(s._retry_after_server_error(*server_error_retry))
 
     def finish_turn_status(self) -> None:
         """Set IDLE or WAITING based on bg jobs, then persist."""
         s = self.s
         from app.bg_jobs import bg_manager
         if bg_manager and bg_manager.has_active_jobs(s.id):
             s.status = AgentStatus.WAITING
             s._log("status", "waiting for bg jobs")
diff --git a/docs/workers/grok-200.md b/docs/workers/grok-200.md
index 2656fb4dd..32be7ea14 100644
--- a/docs/workers/grok-200.md
+++ b/docs/workers/grok-200.md
@@ -1,5 +1,6 @@
 # grok-200
 
 - Unifying a duplicated helper: re-export the function object (`from app.x import fn`), do not copy the corrected body. A test that builds fixture paths from the same helper it asserts against stays green when that helper is mutated — pin expected directory names as literals.
 - A question to the orchestrator currently trips the fan barrier (platform bug, 14.08). Ask only when actually blocked, not “just in case”.
 - `pipeline.yaml` is hand-edited. `scripts/extract-manifest.py` was a dead bridge from deleted `app/prompts/` — do not restore generation; `--check` only verifies roles/modules exist as files.
+- `limit_wake` keys off `content LIKE 'turn ended%'`; percentages come from `current_provider_usage`, not the TG suffix.
diff --git a/tests/test_session.py b/tests/test_session.py
index 8e95f4939..ad1a853b1 100644
--- a/tests/test_session.py
+++ b/tests/test_session.py
@@ -2406,83 +2406,84 @@ class TestRateLimitClassification:
             "data": {
                 "primary": {"utilization": 33, "window_minutes": 300},
                 "secondary": {"utilization": 44, "window_minutes": 10080},
             },
             "ts": sampled_at,
         })
         monkeypatch.setattr("app.session_turns.time.time", lambda: sampled_at + 1)
         logs = []
         session.backend_type = "codex"
         session.model = "gpt-5.6-sol"
         session._log = lambda kind, content, **_kwargs: logs.append((kind, content))
         session._spawn_bg = lambda coro: coro.close()
         session._hibernate.schedule = MagicMock()
 
         session._turns.handle_turn_end(AgentEvent(type="turn_end", metadata={
             "ok": True, "stop_reason": "end_turn", "num_turns": 1,
         }))
         await session._drain_persist()
 
         ended = next(content for kind, content in logs if kind == "status" and "turn ended" in content)
-        assert "Codex 5h:33%" in ended
-        assert "Codex 7d:44%" in ended
+        assert "5h:" not in ended
+        assert "7d:" not in ended
         assert "88%" not in ended
         assert "100%" not in ended
 
     @pytest.mark.asyncio
     async def test_turn_end_persists_and_logs_one_selected_quota_snapshot(
         self, session, monkeypatch,
     ):
         from app.events import AgentEvent
 
         snapshot = {
             "state": {
                 "quota_five_hour_pct": None,
                 "quota_seven_day_pct": None,
                 "quota_primary_pct": 33,
                 "quota_sampled_at": "2033-05-18T03:33:20+00:00",
             },
             "display": (("Codex 5h", {"utilization": 33}),),
         }
         selected = MagicMock(return_value=snapshot)
         add_usage = MagicMock(return_value=True)
         monkeypatch.setattr("app.session_turns._cached_quota_snapshot", selected)
         monkeypatch.setattr("app.session_turns.turn_usage_add", add_usage)
         logs = []
         session.backend_type = "codex"
         session.model = "gpt-5.6-sol"
         session._log = lambda kind, content, **_kwargs: logs.append((kind, content))
         session._spawn_bg = lambda coro: coro.close()
         session._hibernate.schedule = MagicMock()
 
         session._turns.handle_turn_end(AgentEvent(type="turn_end", metadata={
             "event_id": "quota-snapshot-turn",
             "ok": True, "stop_reason": "end_turn", "num_turns": 1,
         }))
         if session._log_futures:
             await asyncio.gather(*tuple(session._log_futures), return_exceptions=True)
         await session._drain_persist()
 
         selected.assert_called_once_with("codex", "gpt-5.6-sol")
         assert add_usage.call_args.kwargs["quota_primary_pct"] == 33
         ended = next(content for kind, content in logs if kind == "status" and "turn ended" in content)
-        assert "Codex 5h:33%" in ended
+        assert "5h:" not in ended
+        assert "7d:" not in ended
 
     def test_monthly_spend_limit_is_terminal_and_never_retried(self, session):
         from app.events import AgentEvent
         spawned = self._capture_coroutines(session)
 
         session._handle_event(AgentEvent(
             type="text",
             content="You've hit your monthly spend limit · raise it at claude.ai/settings/usage",
         ))
         session._handle_event(AgentEvent(type="error", content="rate_limit"))
 
         assert session._rate_limit_retries == 0
         assert spawned == []
 
     @pytest.mark.asyncio
     async def test_terminal_limit_turn_skips_duplicate_error_and_precompact(
         self, session, monkeypatch
     ):
         from app.events import AgentEvent
         from app.session import AgentStatus
diff --git a/tests/test_turn_ended_no_quota_suffix.py b/tests/test_turn_ended_no_quota_suffix.py
new file mode 100644
index 000000000..25272aab8
--- /dev/null
+++ b/tests/test_turn_ended_no_quota_suffix.py
@@ -0,0 +1,57 @@
+"""#277: turn ended keeps cost/turns/ctx, drops the quota-percent tail."""
+from datetime import datetime, timezone
+from unittest.mock import MagicMock
+
+import pytest
+
+
+@pytest.fixture
+def session(monkeypatch):
+    monkeypatch.setattr("app.session.save_session", MagicMock())
+    monkeypatch.setattr("app.session.add_log", MagicMock(return_value=1))
+    monkeypatch.setattr("app.bg_jobs.bg_manager", None)
+    from app.session import AgentSession
+    return AgentSession(
+        id="test-277", name="w1", scope="/test", cwd="/tmp",
+        model="claude-opus-5[1m]", system_prompt="test",
+        created_at=datetime.now(timezone.utc),
+    )
+
+
+@pytest.mark.asyncio
+async def test_turn_ended_line_has_cost_and_ctx_but_no_quota_percents(
+    session, monkeypatch,
+):
+    from app.events import AgentEvent
+    from app.routes import system
+
+    sampled_at = 2_000_000_000.0
+    monkeypatch.setattr(system, "_usage_cache", {
+        "data": {
+            "five_hour": {"utilization": 67, "resets_at": "2033-05-18T05:04:00+00:00"},
+            "seven_day": {"utilization": 86, "resets_at": "2033-05-22T17:33:20+00:00"},
+        },
+        "ts": sampled_at,
+        "token": None,
+    })
+    monkeypatch.setattr("app.session_turns.time.time", lambda: sampled_at + 1)
+    logs = []
+    session.backend_type = "claude"
+    session.model = "claude-opus-5[1m]"
+    session._last_context["percentage"] = 35
+    session._cost.update_context_from_turn = lambda *_a, **_k: (True, None)
+    session._log = lambda kind, content, **_kwargs: logs.append((kind, content))
+    session._spawn_bg = lambda coro: coro.close()
+    session._hibernate.schedule = MagicMock()
+
+    session._turns.handle_turn_end(AgentEvent(type="turn_end", metadata={
+        "ok": True, "stop_reason": "end_turn", "num_turns": 18,
+    }))
+
+    ended = next(c for k, c in logs if k == "status" and c.startswith("turn ended"))
+    assert "18 turns" in ended
+    assert "turn" in ended and "$" in ended
+    assert "ctx:35%" in ended
+    assert "5h:" not in ended
+    assert "7d:" not in ended
+    assert " reset " not in ended
diff --git a/tests/test_turn_usage.py b/tests/test_turn_usage.py
index cccafc6a4..2956427ac 100644
--- a/tests/test_turn_usage.py
+++ b/tests/test_turn_usage.py
@@ -84,109 +84,40 @@ def test_cached_quota_state_selects_fresh_runtime_window(monkeypatch):
 
     assert _cached_quota_state(
         "claude", "claude-opus-5[1m]", now=sampled_ts + 30,
     ) == {
         "quota_five_hour_pct": 12.5,
         "quota_seven_day_pct": 41,
         "quota_primary_pct": None,
         "quota_sampled_at": sampled_at,
     }
     assert _cached_quota_state(
         "codex", "gpt-5.6-sol", now=sampled_ts + 30,
     )["quota_primary_pct"] == 63
     assert _cached_quota_state(
         "codex", "gpt-5.3-codex-spark", now=sampled_ts + 30,
     )["quota_primary_pct"] == 9
     assert _cached_quota_state(
         "grok", "grok-4.5", now=sampled_ts + 30,
     )["quota_primary_pct"] == 27
 
 
-def test_runtime_quota_formatting_selects_only_own_windows(monkeypatch):
-    from app.routes import system
-    from app.session_turns import _cached_quota_snapshot, _format_limits
-
-    sampled_ts = 2_000_000_000.0
-    monkeypatch.setattr(system, "_usage_cache", {
-        "data": {
-            "five_hour": {"utilization": 88},
-            "seven_day": {"utilization": 100},
-        },
-        "ts": sampled_ts,
-        "token": None,
-    })
-    monkeypatch.setattr(system, "_codex_usage_cache", {
-        "data": {
-            "primary": {"utilization": 33, "window_minutes": 300},
-            "secondary": {"utilization": 44, "window_minutes": 10080},
-            "spark": {
-                "primary": {"utilization": 9, "window_minutes": 300},
-                "secondary": {"utilization": 10, "window_minutes": 10080},
-            },
-        },
-        "ts": sampled_ts,
-    })
-
-    claude = _format_limits(_cached_quota_snapshot(
-        "claude", "claude-opus-5[1m]", now=sampled_ts + 1,
-    ), now=sampled_ts + 1)
-    codex = _format_limits(_cached_quota_snapshot(
-        "codex", "gpt-5.6-sol", now=sampled_ts + 1,
-    ), now=sampled_ts + 1)
-    spark = _format_limits(_cached_quota_snapshot(
-        "codex", "gpt-5.3-codex-spark", now=sampled_ts + 1,
-    ), now=sampled_ts + 1)
-
-    assert claude == " | Claude 5h:88% Claude 7d:100%"
-    assert codex == " | Codex 5h:33% Codex 7d:44%"
-    assert spark == " | Spark 5h:9% Spark 7d:10%"
-
-
-@pytest.mark.parametrize(
-    ("runtime", "model"),
-    [
-        ("claude", "claude-opus-5[1m]"),
-        ("codex", "gpt-5.6-sol"),
-        ("codex", "gpt-5.3-codex-spark"),
-    ],
-)
-def test_stale_runtime_cache_has_no_turn_end_quota_suffix(monkeypatch, runtime, model):
-    from app.routes import system
-    from app.session_turns import _cached_quota_snapshot, _format_limits
-
-    monkeypatch.setattr(system, "_usage_cache", {
-        "data": {"five_hour": {"utilization": 88}}, "ts": 1_999_999_699.0,
-    })
-    monkeypatch.setattr(system, "_codex_usage_cache", {
-        "data": {
-            "primary": {"utilization": 33},
-            "spark": {"primary": {"utilization": 9}},
-        },
-        "ts": 1_999_999_699.0,
-    })
-
-    snapshot = _cached_quota_snapshot(runtime, model, now=2_000_000_000.0)
-
-    assert snapshot["state"]["quota_sampled_at"] is None
-    assert _format_limits(snapshot, now=2_000_000_000.0) == ""
-
-
 @pytest.mark.parametrize("cache_data,cache_ts", [
     (None, time.time()),
     ({"primary": {"utilization": 88}}, time.time() - 301),
 ])
 def test_cached_quota_state_returns_null_without_fresh_data(
     usage_db, monkeypatch, cache_data, cache_ts,
 ):
     from app.routes import system
     from app.db import _conn, turn_usage_add
     from app.session_turns import _cached_quota_state
 
     monkeypatch.setattr(system, "_codex_usage_cache", {
         "data": cache_data,
         "ts": cache_ts,
     })
 
     quota_state = _cached_quota_state("codex", "gpt-5.6-sol")
     assert quota_state == {
         "quota_five_hour_pct": None,
         "quota_seven_day_pct": None,


## Later history of the touched files on main (after this commit)

66 later commits touch these paths; the first 40 (oldest first):
740d749a2 2026-08-14 #242, #278: #242: recount live-state tests — 70 DB_PATH sites in 56 files
4f0c87aa3 2026-08-14 #282: #282: wait for notify card and reconnect, not a 5s sleep
5a11c5a14 2026-08-14 #280: #280: drop vacuum fail-open spawn test; deny unknown parent role
a93d8aee1 2026-08-14 #267: #267: no fix — managed auth symlink survives oauth rewrite; dead token is loud
b92be6ec2 2026-08-16 #180: restore Codex project trust and context
3cfeb617a 2026-08-16 #297: #297: suppress silent marker auto-report
366367f5d 2026-08-16 Merge origin/main into VPS main
b47679c16 2026-08-16 #291: #291: implement T1 quota topology and schema
3c037bdb8 2026-08-18 #290: cross-runtime handoff + канареечный скип по продовому предикату (scratch/290, вердикт #328)
0707d9257 2026-08-19 #343: одно правило допуска по квоте, прежние квотные системы вырезаны
fa3e993db 2026-08-23 Allow fresh model switches without handoff
150e696e0 2026-08-23 #284: #284: make Codex JSONL reader fail-soft and clear lost turns
71374ea56 2026-08-23 #385: #385: research deferred turn control and provenance
9d2627281 2026-08-24 Merge origin/main into main (2026-08-24 sync)
b11ba9be1 2026-08-24 #307: harden Codex oversized resume recovery
db8708aaa 2026-08-24 #319: #319: port bounded Codex cleanup onto current main
e26dcde85 2026-08-24 fix: switch Codex models in place
247fe6b37 2026-08-24 fix: retarget models within every runtime
4d58b176a 2026-08-24 refactor: remove OpenCode runtime
2fcc0e2fa 2026-08-24 chore: remove inert blob and stale docs artifacts
ebb38764a 2026-08-25 #365: harden free OpenRouter harness
236b385fd 2026-08-25 #363: add text tail Codex to Opus handoff
8e2b564cd 2026-08-26 #407: freeze durable fan interception oracle
1b0fa3d23 2026-08-28 Compact every runtime immediately at critical context
3dfa39bc0 2026-09-02 #438: compact before Claude CLI threshold
4e5940ef6 2026-09-02 #433: research message provenance
498c0d149 2026-09-03 Orchestra: migrate project state to .orchestra
f8e00522e 2026-09-03 #430: research .orchestra path migration
73f21324a 2026-09-04 #480: freeze fan report selection regressions
42e0352e8 2026-09-05 fix: fence stale retries and isolate dashboard recovery failures
e2e83139f 2026-09-05 fix: complete scoped recovery and continuation lifecycle safeguards
264daeb75 2026-09-07 Separate runtime control from model prose and preserve review results
fe507ac6e 2026-09-08 Namespace VPS tasks and simplify runtime chat transfer and worker notes
ae30028d3 2026-09-08 Remove unreachable cross-runtime canary pipeline and retired rule API
98574f427 2026-09-08 Replace duplicate task stores with private Git and one versioned SQLite projection
d9ce293fa 2026-09-08 Integrate current main before storage cutover
e6da7e30a 2026-09-10 #537: stop runtime trees with Orchestra and remove live adoption
b15940ba5 2026-09-12 V-562: preserve steered messages after failed turns
a8d2e20ad 2026-09-17 V-582: #V-582: харнес-маршруты из живого каталога, допуск по данным провайдера
7f291ae99 2026-09-21 V-606: #V-606: compact idle sessions before cache expiry

## Patches of the first 8 later commits, restricted to the touched paths (each capped at 150 lines)

### 740d749a2 #242, #278: #242: recount live-state tests — 70 DB_PATH sites in 56 files

diff --git a/docs/workers/grok-200.md b/docs/workers/grok-200.md
index 32be7ea14..514e9cfa1 100644
--- a/docs/workers/grok-200.md
+++ b/docs/workers/grok-200.md
@@ -2,5 +2,6 @@
 
 - Unifying a duplicated helper: re-export the function object (`from app.x import fn`), do not copy the corrected body. A test that builds fixture paths from the same helper it asserts against stays green when that helper is mutated — pin expected directory names as literals.
 - A question to the orchestrator currently trips the fan barrier (platform bug, 14.08). Ask only when actually blocked, not “just in case”.
 - `pipeline.yaml` is hand-edited. `scripts/extract-manifest.py` was a dead bridge from deleted `app/prompts/` — do not restore generation; `--check` only verifies roles/modules exist as files.
 - `limit_wake` keys off `content LIKE 'turn ended%'`; percentages come from `current_provider_usage`, not the TG suffix.
+- `wait_for(..., timeout=0.1)` in tests: 0 on 14.08. The short ones now are `timeout=0.05` in `test_tg_bridge.py` (4).
### 4f0c87aa3 #282: #282: wait for notify card and reconnect, not a 5s sleep

diff --git a/docs/workers/grok-200.md b/docs/workers/grok-200.md
index 514e9cfa1..fb3e1ff83 100644
--- a/docs/workers/grok-200.md
+++ b/docs/workers/grok-200.md
@@ -3,5 +3,6 @@
 - Unifying a duplicated helper: re-export the function object (`from app.x import fn`), do not copy the corrected body. A test that builds fixture paths from the same helper it asserts against stays green when that helper is mutated — pin expected directory names as literals.
 - A question to the orchestrator currently trips the fan barrier (platform bug, 14.08). Ask only when actually blocked, not “just in case”.
 - `pipeline.yaml` is hand-edited. `scripts/extract-manifest.py` was a dead bridge from deleted `app/prompts/` — do not restore generation; `--check` only verifies roles/modules exist as files.
 - `limit_wake` keys off `content LIKE 'turn ended%'`; percentages come from `current_provider_usage`, not the TG suffix.
 - `wait_for(..., timeout=0.1)` in tests: 0 on 14.08. The short ones now are `timeout=0.05` in `test_tg_bridge.py` (4).
+- Flake `cards==0` after `wait_for_timeout(5000)`: wait for `.chat-notify-user` and stream reconnect count, never the clock.
### 5a11c5a14 #280: #280: drop vacuum fail-open spawn test; deny unknown parent role

diff --git a/docs/workers/grok-200.md b/docs/workers/grok-200.md
index fb3e1ff83..aaf28396a 100644
--- a/docs/workers/grok-200.md
+++ b/docs/workers/grok-200.md
@@ -4,5 +4,6 @@
 - A question to the orchestrator currently trips the fan barrier (platform bug, 14.08). Ask only when actually blocked, not “just in case”.
 - `pipeline.yaml` is hand-edited. `scripts/extract-manifest.py` was a dead bridge from deleted `app/prompts/` — do not restore generation; `--check` only verifies roles/modules exist as files.
 - `limit_wake` keys off `content LIKE 'turn ended%'`; percentages come from `current_provider_usage`, not the TG suffix.
 - `wait_for(..., timeout=0.1)` in tests: 0 on 14.08. The short ones now are `timeout=0.05` in `test_tg_bridge.py` (4).
 - Flake `cards==0` after `wait_for_timeout(5000)`: wait for `.chat-notify-user` and stream reconnect count, never the clock.
+- `create_session(parent_name=...)`: missing session → `_resolve_role` returns `None` → `validate_spawn` treats it as **root**, not as unknown role. Unknown **role** is a live parent session whose `role` is absent from the manifest. A test named fail-open that passes a ghost parent_name stays green after a fail-closed inversion.
### a93d8aee1 #267: #267: no fix — managed auth symlink survives oauth rewrite; dead token is loud

diff --git a/docs/workers/grok-200.md b/docs/workers/grok-200.md
index aaf28396a..4455c37ad 100644
--- a/docs/workers/grok-200.md
+++ b/docs/workers/grok-200.md
@@ -5,5 +5,6 @@
 - `pipeline.yaml` is hand-edited. `scripts/extract-manifest.py` was a dead bridge from deleted `app/prompts/` — do not restore generation; `--check` only verifies roles/modules exist as files.
 - `limit_wake` keys off `content LIKE 'turn ended%'`; percentages come from `current_provider_usage`, not the TG suffix.
 - `wait_for(..., timeout=0.1)` in tests: 0 on 14.08. The short ones now are `timeout=0.05` in `test_tg_bridge.py` (4).
 - Flake `cards==0` after `wait_for_timeout(5000)`: wait for `.chat-notify-user` and stream reconnect count, never the clock.
 - `create_session(parent_name=...)`: missing session → `_resolve_role` returns `None` → `validate_spawn` treats it as **root**, not as unknown role. Unknown **role** is a live parent session whose `role` is absent from the manifest. A test named fail-open that passes a ghost parent_name stays green after a fail-closed inversion.
+- Grok probes: own `GROK_HOME` under `/tmp`, never write `~/.grok/`. Do not force a live refresh (`GROK_AUTH_EARLY_INVALIDATION_SECS` + real `refresh_token`) — it can rotate the prod token. Dead auth is loud: missing file → `ensure_grok_home` RuntimeError; present-but-dead → ACP `session/new` `Authentication required`. `linux rename()` onto a symlink replaces the link; `ensure_grok_home` then deletes that regular file and re-links.
### b92be6ec2 #180: restore Codex project trust and context

diff --git a/tests/test_session.py b/tests/test_session.py
index ad1a853b1..a31322291 100644
--- a/tests/test_session.py
+++ b/tests/test_session.py
@@ -3358,14 +3358,21 @@ class TestEnsureBackendForceFresh:
         session._make_backend = MagicMock(
             side_effect=lambda **_kwargs: order.append("build") or backend,
         )
         session._hibernate.heartbeat_loop = AsyncMock()
 
-        result = await session._ensure_backend()
+        with patch(
+            "app.workspace.sync_agents_md",
+            side_effect=lambda path: order.append(("agents", path)),
+        ) as sync_agents:
+            result = await session._ensure_backend()
 
         assert result is backend
-        assert order == ["skills", "project-doc", "build", "connect"]
+        sync_agents.assert_called_once_with(session.cwd)
+        assert order == [
+            ("agents", session.cwd), "skills", "project-doc", "build", "connect",
+        ]
 
     @pytest.mark.asyncio
     async def test_force_fresh_rebuilds_existing_backend(self, session):
         # Codex diff #P1: _ensure_backend(force_fresh=True) must rebuild even
         # when a backend already exists (old one disconnected, fresh one made).
### 3cfeb617a #297: #297: suppress silent marker auto-report

diff --git a/app/session_turns.py b/app/session_turns.py
index 26c3dede4..01ac1f1af 100644
--- a/app/session_turns.py
+++ b/app/session_turns.py
@@ -13,10 +13,11 @@ from datetime import datetime, timezone
 from typing import TYPE_CHECKING
 
 from app.db import turn_usage_add
 from app.events import AgentEvent
 from app.session_state import AgentStatus
+from app.turn_markers import is_successful_silent_turn
 
 if TYPE_CHECKING:
     from app.session import AgentSession
 
 
@@ -229,10 +230,13 @@ class TurnManager:
             return
         if s._pending_messages or s._compacting:
             return
         if s._last_turn_ok and not s._turn_logs:
             return
+        silent_turn = is_successful_silent_turn(
+            getattr(s, "_last_text_output", None), s._last_turn_ok
+        )
         # An unparented worker started directly from dashboard/TG has nobody to report
         # to. A parented child must still report: parent_name survives service restarts
         # even when the transient last_task_sender metadata does not.
         if not s.last_task_sender and not s.parent_name:
             return
@@ -246,11 +250,13 @@ class TurnManager:
         # по `_did_report` оставлял его pending навсегда.
         if fan_barrier.should_buffer(s.name):
             # #231: осушение проверяется В ТОЙ ЖЕ транзакции, что и фиксация терминала.
             # Раздельные «посмотреть» и «записать» пропускают `wake=False`, легший
             # между ними, — и веер отпустится по ребёнку, не видевшему своего входа.
-            silent_text = "\n".join(str(item) for item in (s._turn_logs or []))
+            silent_text = "" if silent_turn else "\n".join(
+                str(item) for item in (s._turn_logs or [])
+            )
             if fan_barrier.record_terminal(
                 s.name,
                 "done",
                 summary=silent_text,
                 require_drained_scope=s.scope,
@@ -273,11 +279,11 @@ class TurnManager:
                                 dest.id, fan_barrier.manifest_text(fid)
                             )
                     s._auto_report_task = asyncio.create_task(_deliver_manifest())
             return
 
-        if s._did_report:
+        if s._did_report or silent_turn:
             return
 
         last_texts = s._turn_logs[-5:] if s._turn_logs else []
         stop_reason = s._last_stop_reason
 
diff --git a/tests/test_session.py b/tests/test_session.py
index ad1a853b1..b6e7d676c 100644
--- a/tests/test_session.py
+++ b/tests/test_session.py
@@ -921,10 +921,161 @@ async def test_auto_report_skips_successful_silent_turn(monkeypatch):
     await asyncio.sleep(0)
 
     s.on_idle.assert_not_awaited()
 
 
+@pytest.mark.asyncio
+async def test_auto_report_skips_exact_silent_marker(monkeypatch):
+    s = _mk_session(monkeypatch)
+    s.on_idle = AsyncMock()
+    s.last_task_sender = "parent"
+    s._turn_logs = ["[[ORCHESTRA:SILENT_TURN]]"]
+    s._last_text_output = "[[ORCHESTRA:SILENT_TURN]]"
+
+    s._turns.fire_auto_report()
+    await asyncio.sleep(0)
+
+    s.on_idle.assert_not_awaited()
+    assert s._auto_report_task is None
+
+
+@pytest.mark.asyncio
+@pytest.mark.parametrize(
+    "content",
+    [
+        " [[ORCHESTRA:SILENT_TURN]]",
+        "[[ORCHESTRA:SILENT_TURN]] ",
+        "prefix [[ORCHESTRA:SILENT_TURN]]",
+        "[[ORCHESTRA:SILENT_TURN]] suffix",
+    ],
+)
+async def test_auto_report_keeps_silent_marker_near_misses(monkeypatch, content):
+    s = _mk_session(monkeypatch)
+    fired = []
+
+    async def on_idle(name, scope, texts, stop_reason="", turn_ok=True):
+        fired.append(texts)
+
+    s.on_idle = on_idle
+    s.last_task_sender = "parent"
+    s._turn_logs = [content]
+    s._last_text_output = content
+
+    s._turns.fire_auto_report()
+    await asyncio.sleep(0.05)
+
+    assert fired == [[content]]
+
+
+@pytest.mark.asyncio
+async def test_failed_turn_with_silent_marker_is_reported(monkeypatch):
+    s = _mk_session(monkeypatch)
+    fired = []
+
+    async def on_idle(name, scope, texts, stop_reason="", turn_ok=True):
+        fired.append((texts, turn_ok))
+
+    s.on_idle = on_idle
+    s.last_task_sender = "parent"
+    s._last_turn_ok = False
+    s._turn_logs = ["[[ORCHESTRA:SILENT_TURN]]"]
+    s._last_text_output = "[[ORCHESTRA:SILENT_TURN]]"
+
+    s._turns.fire_auto_report()
+    await asyncio.sleep(0.05)
+
+    assert fired == [(["[[ORCHESTRA:SILENT_TURN]]"], False)]
+
+
+@pytest.mark.asyncio
+async def test_unparented_silent_marker_does_not_wake_anyone(monkeypatch):
+    s = _mk_session(monkeypatch)
+    s.on_idle = AsyncMock()
+    s.parent_name = ""
+    s.last_task_sender = ""
+    s._turn_logs = ["[[ORCHESTRA:SILENT_TURN]]"]
+    s._last_text_output = "[[ORCHESTRA:SILENT_TURN]]"
+
+    s._turns.fire_auto_report()
+    await asyncio.sleep(0)
+
+    s.on_idle.assert_not_awaited()
+    assert s._auto_report_task is None
+
+
+@pytest.mark.asyncio
### 366367f5d Merge origin/main into VPS main

### b47679c16 #291: #291: implement T1 quota topology and schema

diff --git a/app/session_turns.py b/app/session_turns.py
index 01ac1f1af..6c881399c 100644
--- a/app/session_turns.py
+++ b/app/session_turns.py
@@ -314,10 +314,22 @@ class TurnManager:
             logger.warning(
                 f"[{s.name}] quota cache read failed: "
                 f"{type(error).__name__}: {error}"
             )
             quota_snapshot = _unknown_quota_snapshot()
+        reservation = getattr(s, "_active_shadow_reservation", None)
+        if event_id and reservation is not None:
+            s._shadow_settle(
+                reservation,
+                event_id,
+                str(meta.get("ended_at") or datetime.now(timezone.utc).isoformat()),
+                actual={
+                    "ok": ok,
+                    "stop_reason": sr,
+                    "terminal_quota": quota_snapshot["state"],
+                },
+            )
         if event_id:
             cost_fields = {"cost_usd": s._turn_cost}
             if cost_unaccounted:
                 cost_fields = {"cost_usd": None, "cost_unaccounted": True}
             s._submit_db_write(