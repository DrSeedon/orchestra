# Candidate cand-34

## ORIGIN commit c4ff89c990 (2026-07-28): #98: #98: separate aggregate usage from current context
(diff of code only, excluding .orchestra/ and *.md; capped 1200 lines)

diff --git a/app/backend_claude.py b/app/backend_claude.py
index 1fcd01576..4cabd3472 100644
--- a/app/backend_claude.py
+++ b/app/backend_claude.py
@@ -24,16 +24,17 @@ from claude_agent_sdk import (
     SystemMessage,
     StreamEvent,
 )
 from claude_agent_sdk.types import (
     ToolResultBlock, ServerToolResultBlock, UserMessage,
 )
 
 from app.events import AgentEvent
+from app.usage_contract import AggregateUsage, TurnUsage, deferred_context
 
 logger = logging.getLogger(__name__)
 
 CLAUDE_INTERRUPT_TIMEOUT = 5.0
 
 _BLOCKED_TOOLS = {"AskUserQuestion", "Monitor"}
 _ORCH_BLOCKED_TOOLS = {"AskUserQuestion", "Agent", "Monitor"}
 # Orchestrators must use spawn_worker instead of the built-in Agent/Task tools —
@@ -551,36 +552,40 @@ class ClaudeBackend:
                     if not self.model.startswith("claude-"):
                         cost = real_cost
                     # Anthropic cache pricing: cache_read = 10% of input, cache_create = 125%
                     cost_cached = (input_tokens * p_in + cache_read * p_in * 0.1 + cache_create * p_in * 1.25 + output_tokens * p_out) / 1_000_000
 
             if denials:
                 logger.info(f"[{self.model}] {len(denials)} permission denial(s) this turn")
 
+            turn_usage = TurnUsage(
+                AggregateUsage.normalized(
+                    input_tokens=input_tokens,
+                    output_tokens=output_tokens,
+                    cache_read_tokens=cache_read,
+                    cache_create_tokens=cache_create,
+                    model_calls=nt or None,
+                ),
+                deferred_context(max_tokens, "claude_context_usage"),
+            )
             events.append(AgentEvent("turn_end", f"stop_reason={sr}, num_turns={nt}", metadata={
                 "event_id": getattr(msg, "uuid", None) or "",
                 "session_id": self._session_id,
                 "ok": not is_err,
                 "is_error": is_err,
                 "errors": err_list,
                 "model_error": model_error,
                 "stop_reason": sr,
                 "num_turns": nt,
                 "cost_usd": cost,
                 "cost_usd_cached": round(cost_cached, 6),
-                "context_pct": 0,
-                "context_tokens": 0,
-                "max_tokens": max_tokens,
                 "cache_hit": cache_hit,
-                "cache_read": cache_read,
-                "cache_create": cache_create,
-                "input_tokens": input_tokens,
-                "output_tokens": output_tokens,
-            }))
+                **turn_usage.metadata(),
+            }, usage=turn_usage))
 
         if (isinstance(msg, SystemMessage)
                 and not isinstance(msg, (TaskStartedMessage, TaskProgressMessage, TaskNotificationMessage))
                 and getattr(msg, "subtype", "") == "compact_boundary"):
             data = getattr(msg, "data", {}) or {}
             meta = data.get("compactMetadata", data)
             pre = meta.get("preTokens", 0)
             post = meta.get("postTokens", 0)
diff --git a/app/backend_codex.py b/app/backend_codex.py
index 7ff4ab657..58e474f1e 100644
--- a/app/backend_codex.py
+++ b/app/backend_codex.py
@@ -4,16 +4,17 @@ import asyncio
 import json
 import logging
 import os
 import shutil
 from pathlib import Path
 from typing import AsyncIterator, Optional
 
 from app.events import AgentEvent
+from app.usage_contract import AggregateUsage, TurnUsage, current_context
 
 logger = logging.getLogger(__name__)
 
 CODEX_BIN = shutil.which("codex") or os.environ.get("CODEX_BIN", "codex")
 
 # Effective context budgets reported by the ChatGPT-auth Codex runtime. The public API
 # advertises a larger GPT-5.6 window, but that is a different surface; local rollout
 # token_count events are the runtime source of truth and may override these fallbacks.
@@ -812,29 +813,35 @@ class CodexBackend:
 
         if method == "turn/completed":
             turn = params.get("turn") or {}
             self._active_turn_id = None
             return self._turn_completed(turn)
 
         if method == "_process/exited":
             self._active_turn_id = None
+            normalized_usage = TurnUsage(
+                AggregateUsage.normalized(),
+                current_context(
+                    None,
+                    self._model_context_window,
+                    unknown_reason="Codex exited before reporting current context",
+                ),
+            )
             return [AgentEvent("turn_end", "stop_reason=process_exit", metadata={
                 "session_id": self._thread_id,
                 "ok": False,
                 "stop_reason": f"process_exit_{params.get('returncode')}",
                 "returncode": params.get("returncode"),
                 "stderr_tail": params.get("stderr", ""),
                 "model_error": "server_error",
                 "errors": ["server_error"],
                 "cost_usd": 0,
-                "context_pct": 0,
-                "context_tokens": 0,
-                "max_tokens": self._model_context_window,
-            })]
+                **normalized_usage.metadata(),
+            }, usage=normalized_usage)]
 
         return []
 
     def _item_started(self, item: dict) -> list[AgentEvent]:
         item_type = item.get("type", "")
         item_id = str(item.get("id") or "")
         if item_type == "commandExecution":
             payload = {
@@ -1132,58 +1139,65 @@ class CodexBackend:
         model_error = "" if ok else self._classify_error(error)
         stop_reason = {
             "completed": "end_turn",
             "interrupted": "interrupted",
             "failed": "error",
         }.get(status, status)
 
         totals = self._thread_usage_total or self._runtime_totals() or {}
-        turn_usage = _usage_delta(totals, self._usage_baseline)
-        turn_input = turn_usage["input_tokens"]
-        turn_cached = turn_usage["cached_input_tokens"]
-        turn_output = turn_usage["output_tokens"]
+        delta = _usage_delta(totals, self._usage_baseline)
+        turn_input = delta["input_tokens"]
+        turn_cached = delta["cached_input_tokens"]
+        turn_output = delta["output_tokens"]
         context = self._last_call_usage or self._runtime_context()
         if context:
             ctx_tokens = int(context.get("input_tokens") or 0)
             ctx_window = int(
                 context.get("model_context_window") or self._model_context_window
             )
-            context_known = True
         else:
-            ctx_tokens = 0
+            ctx_tokens = None
             ctx_window = self._model_context_window
-            context_known = False
-        ctx_pct = min(100, int(ctx_tokens * 100 / ctx_window)) if ctx_window else 0
+        normalized_usage = TurnUsage(
+            AggregateUsage.normalized(
+                input_tokens=turn_input,
+                output_tokens=turn_output,
+                cache_read_tokens=turn_cached,
+            ),
+            current_context(
+                ctx_tokens,
+                ctx_window,
+                semantics_known=context is not None,
+                unknown_reason="Codex did not report last-call context",
+            ),
+        )
         cost = _codex_cost(self.model, turn_input, turn_cached, turn_output)
         metadata = {
             "event_id": str(turn.get("id") or ""),
             "session_id": self._thread_id,
             "ok": ok,
             "stop_reason": stop_reason,
             "cost_usd": cost,
             "cost_usd_cached": cost,
             "cost_is_delta": True,
-            "context_pct": ctx_pct,
-            "context_tokens": ctx_tokens,
-            "context_known": context_known,
-            "max_tokens": ctx_window,
             "cache_hit": int(turn_cached * 100 / turn_input) if turn_input else 0,
-            "cache_read": turn_cached,
-            "cache_create": 0,
-            "input_tokens": turn_input,
-            "cached_input_tokens": turn_cached,
-            "output_tokens": turn_output,
+            **normalized_usage.metadata(),
             "model_error": model_error,
             "errors": [model_error] if model_error else [],
         }
         events = []
         if not ok and error.get("message"):
             events.append(AgentEvent("error", error["message"], {"model_error": model_error}))
-        events.append(AgentEvent("turn_end", f"stop_reason={stop_reason}", metadata=metadata))
+        events.append(AgentEvent(
+            "turn_end",
+            f"stop_reason={stop_reason}",
+            metadata=metadata,
+            usage=normalized_usage,
+        ))
         self._last_turn_error = {}
         return events
 
     @staticmethod
     def _usage_breakdown(data: dict) -> dict[str, int]:
         return {
             "input_tokens": max(0, int(data.get("inputTokens") or 0)),
             "cached_input_tokens": max(0, int(data.get("cachedInputTokens") or 0)),
diff --git a/app/backend_grok.py b/app/backend_grok.py
index 9ab209184..c3538618e 100644
--- a/app/backend_grok.py
+++ b/app/backend_grok.py
@@ -6,16 +6,17 @@ import logging
 import os
 import shutil
 import tempfile
 import uuid
 from pathlib import Path
 from typing import AsyncIterator, Optional
 
 from app.events import AgentEvent
+from app.usage_contract import AggregateUsage, TurnUsage, current_context
 
 logger = logging.getLogger(__name__)
 
 # Explicit configuration beats autodiscovery: an unrelated `grok` earlier in PATH must not
 # silently win over a deliberately configured binary.
 GROK_BIN = (
     os.environ.get("GROK_BIN")
     or shutil.which("grok")
@@ -235,17 +236,17 @@ class GrokBackend:
         # the agent queues extras, so the event loop must not stop at the first completion.
         self._active_prompts = 0
         self._queue_depth = 0
         self._completed_prompts: set[str] = set()
         self._tool_names: dict[str, str] = {}
         # turn_completed carries usage; the turn_end is emitted by the prompt completion.
         self._pending_usage: dict = {}
         self._model_context_window = GROK_CONTEXT_LIMITS.get(model, GROK_DEFAULT_CONTEXT)
-        self._context_tokens = 0
+        self._context_tokens: int | None = None
         # A matching name is insufficient: a repository can define another command under it.
         expected_configs = self._mcp_server_configs()
         self._expected_server_identities = {
             str(server["name"]): _mcp_server_identity(server)
             for server in expected_configs
         }
         self._expected_servers: set[str] = set(self._expected_server_identities)
         self._started_servers: set[str] = set()
@@ -799,29 +800,35 @@ class GrokBackend:
             )
             content = error.get("message") or "Grok error"
             return [AgentEvent("error", content,
                                {"model_error": self._classify_error(error)})]
 
         if method == "_process/exited":
             self._active_prompts = 0
             self._queue_depth = 0
+            turn_usage = TurnUsage(
+                AggregateUsage.normalized(),
+                current_context(
+                    None,
+                    self._model_context_window,
+                    unknown_reason="Grok exited before reporting current context",
+                ),
+            )
             return [AgentEvent("turn_end", "stop_reason=process_exit", metadata={
                 "session_id": self._session_id,
                 "ok": False,
                 "stop_reason": f"process_exit_{params.get('returncode')}",
                 "returncode": params.get("returncode"),
                 "stderr_tail": params.get("stderr", ""),
                 "model_error": "server_error",
                 "errors": ["server_error"],
                 "cost_usd": 0,
-                "context_pct": 0,
-                "context_tokens": 0,
-                "max_tokens": self._model_context_window,
-            })]
+                **turn_usage.metadata(),
+            }, usage=turn_usage)]
 
         return []
 
     def _session_update(self, params: dict) -> list[AgentEvent]:
         update = params.get("update") or {}
         kind = update.get("sessionUpdate", "")
         meta = params.get("_meta") or {}
         total = meta.get("totalTokens")
@@ -931,41 +938,49 @@ class GrokBackend:
         input_tokens = max(0, int(totals.get("inputTokens") or 0))
         cached = max(0, int(totals.get("cachedReadTokens") or 0))
         output_tokens = max(0, int(totals.get("outputTokens") or 0))
         ticks = totals.get("costUsdTicks")
         if isinstance(ticks, (int, float)) and ticks >= 0:
             cost = float(ticks) * GROK_COST_TICK_USD
         else:
             cost = _grok_cost(self.model, input_tokens, cached, output_tokens)
-        context_tokens = max(0, int(totals.get("totalTokens") or self._context_tokens))
         window = self._model_context_window or GROK_DEFAULT_CONTEXT
+        turn_usage = TurnUsage(
+            AggregateUsage.normalized(
+                input_tokens=input_tokens,
+                output_tokens=output_tokens,
+                cache_read_tokens=cached,
+                model_calls=totals.get("modelCalls"),
+            ),
+            current_context(
+                self._context_tokens,
+                window,
+                unknown_reason=(
+                    "Grok ACP emitted no per-call current-context value; "
+                    "turn usage totals are aggregate"
+                ),
+            ),
+        )
         stop_map = {"end_turn": "end_turn", "cancelled": "interrupted",
                     "max_tokens": "max_tokens", "refusal": "refusal"}
         self._pending_usage = {}
+        self._context_tokens = None
         return AgentEvent("turn_end", f"stop_reason={stop_reason}", metadata={
             "session_id": self._session_id,
             "ok": ok,
             "stop_reason": stop_map.get(stop_reason, stop_reason),
             "cost_usd": cost,
             "cost_usd_cached": cost,
             "cost_is_delta": True,
-            "context_pct": min(100, int(context_tokens * 100 / window)) if window else 0,
-            "context_tokens": context_tokens,
-            "context_known": bool(context_tokens),
-            "max_tokens": window,
             "cache_hit": int(cached * 100 / input_tokens) if input_tokens else 0,
-            "cache_read": cached,
-            "cache_create": 0,
-            "input_tokens": input_tokens,
-            "cached_input_tokens": cached,
-            "output_tokens": output_tokens,
+            **turn_usage.metadata(),
             "model_error": model_error,
             "errors": [model_error] if model_error else [],
-        })
+        }, usage=turn_usage)
 
     @staticmethod
     def _classify_error(error: dict) -> str:
         """Classify structurally; text matching only as a last resort.
 
         The terminal quota-exhaustion shape is NOT known yet (could not exhaust SuperGrok —
         see docs/tasks/95/research.md F7). Unknown errors stay "error" and fail loud rather
         than being guessed into a rate_limit that silently retries.
diff --git a/app/backend_opencode.py b/app/backend_opencode.py
index d80c49eb9..39e68ec7e 100644
--- a/app/backend_opencode.py
+++ b/app/backend_opencode.py
@@ -23,16 +23,17 @@ import logging
 import os
 import shutil
 import socket
 from typing import AsyncIterator, Optional
 
 import httpx
 
 from app.events import AgentEvent
+from app.usage_contract import AggregateUsage, TurnUsage, current_context
 
 logger = logging.getLogger(__name__)
 
 OPENCODE_BIN = shutil.which("opencode") or os.environ.get("OPENCODE_BIN", "opencode")
 
 # Boundary-hint sentinels yielded by _handle_sse — the caller verifies completion via
 # GET /session/status rather than trusting these SSE events (which can be missed/lie).
 _SESSION_IDLE = object()
@@ -542,54 +543,59 @@ class OpenCodeBackend:
         max_tokens = (
             self._context_limit
             or OPENCODE_CONTEXT_LIMITS.get(self.model, DEFAULT_CONTEXT)
         )
         cache_total = cache_read + cache_create
         cost = float(info.get("cost", 0) or 0)
         err = info.get("error")
         stop_reason = info.get("finish", "end_turn") if err is None else "error"
+        turn_usage = TurnUsage(
+            AggregateUsage.normalized(
+                input_tokens=input_t,
+                output_tokens=output_t,
+                cache_read_tokens=cache_read,
+                cache_create_tokens=cache_create,
+                model_calls=1,
+            ),
+            current_context(input_t, max_tokens),
+        )
         return AgentEvent("turn_end", f"stop_reason={stop_reason}", metadata={
             "session_id": self._session_id,
             "ok": err is None,
             "stop_reason": stop_reason,
             "num_turns": 1,
             "cost_usd": cost,
             "cost_usd_cached": cost,
-            "context_pct": min(100, int(input_t * 100 / max_tokens)) if max_tokens else 0,
-            "context_tokens": input_t,
-            "max_tokens": max_tokens,
             "cache_hit": int(cache_read * 100 / cache_total) if cache_total else 0,
-            "cache_read": cache_read,
-            "cache_create": cache_create,
-            "input_tokens": input_t,
-            "output_tokens": output_t,
-            "cached_input_tokens": cache_read,
-        })
+            **turn_usage.metadata(),
+        }, usage=turn_usage)
 
     def _error_turn_end(self, reason: str) -> AgentEvent:
+        max_tokens = (
+            self._context_limit
+            or OPENCODE_CONTEXT_LIMITS.get(self.model, DEFAULT_CONTEXT)
+        )
+        turn_usage = TurnUsage(
+            AggregateUsage.normalized(),
+            current_context(
+                None,
+                max_tokens,
+                unknown_reason="OpenCode turn failed before reporting current context",
+            ),
+        )
         return AgentEvent("turn_end", f"stop_reason={reason}", metadata={
             "session_id": self._session_id,
             "ok": False,
             "stop_reason": reason,
             "cost_usd": 0,
             "cost_usd_cached": 0,
-            "context_pct": 0,
-            "context_tokens": 0,
-            "max_tokens": (
-                self._context_limit
-                or OPENCODE_CONTEXT_LIMITS.get(self.model, DEFAULT_CONTEXT)
-            ),
             "cache_hit": 0,
-            "cache_read": 0,
-            "cache_create": 0,
-            "input_tokens": 0,
-            "output_tokens": 0,
-            "cached_input_tokens": 0,
-        })
+            **turn_usage.metadata(),
+        }, usage=turn_usage)
 
     # ── teardown ──
 
     async def interrupt(self) -> None:
         if self._http and self._session_id:
             try:
                 await asyncio.wait_for(
                     self._http.post(f"/session/{self._session_id}/abort"), timeout=3)
diff --git a/app/events.py b/app/events.py
index b8f7ae22d..60bc93fe1 100644
--- a/app/events.py
+++ b/app/events.py
@@ -1,18 +1,21 @@
 """Unified event model for all agent backends."""
 
 from dataclasses import dataclass, field
 
+from app.usage_contract import TurnUsage
+
 
 @dataclass
 class AgentEvent:
     type: str
     content: str = ""
     metadata: dict = field(default_factory=dict)
+    usage: TurnUsage | None = None
 
 # type values:
 # "text"              — agent text output
 # "thinking"          — agent reasoning/thinking output
 # "tool_use"          — tool invocation (content = "tool_name: input_summary")
 # "tool_result"       — tool output
 # "file_change"       — file edit (content = "add /path" or "update /path")
 # "turn_end"          — turn completed (metadata: session_id, cost_usd, input_tokens, context_pct, ok, stop_reason, ...)
diff --git a/app/session.py b/app/session.py
index edc4878f0..afd40a6c9 100644
--- a/app/session.py
+++ b/app/session.py
@@ -22,16 +22,17 @@ from app.runtime_registry import (
     get_runtime,
 )
 from app.session_cost import CostTracker
 from app.session_hibernate import HibernateManager
 from app.session_state import (  # noqa: F401 — re-exported: importers use app.session.AgentStatus
     AgentStatus, IDLE_TIMEOUT_ORCHESTRATOR, IDLE_TIMEOUT_WORKER,
 )
 from app.session_turns import TurnManager
+from app.usage_contract import KnownContext, current_context
 
 if TYPE_CHECKING:
     from app.backend_protocol import BackendLike
 from app.db import add_log, get_logs, save_session, tool_error_add
 
 logger = logging.getLogger(__name__)
 
 
@@ -401,16 +402,24 @@ class AgentSession:
             self._precompact_timer["crossed_cache_window"] = crossed_cache_window
             self._precompact_timer["crossed_60m"] = crossed_60m
             self._log(
                 "status",
                 f"precompact timer outcome: {self._precompact_payload(self._precompact_timer)}",
             )
             self._precompact_timer = None
 
+    def _context_is_known(self) -> bool:
+        if "known" in self._last_context:
+            return bool(self._last_context["known"])
+        return bool(
+            self._last_context.get("percentage", 0)
+            or self._last_context.get("total_tokens", 0)
+        )
+
     def _schedule_precompact_timer(self, context_pct: int) -> None:
         if self._precompact_timer is not None:
             return
         policy = self._precompact_policy()
         if policy is None or context_pct < policy["arm_threshold"]:
             return
         window_warning_logged = False
         if context_pct > 90:
@@ -477,16 +486,25 @@ class AgentSession:
             state["skip_reason"] = "backend_changed"
             self._log(
                 "status",
                 f"precompact timer skipped: {self._precompact_payload(state)}",
             )
             self._precompact_timer = None
             return
 
+        if not self._context_is_known():
+            state["skip_reason"] = "unknown_context"
+            self._log(
+                "status",
+                f"precompact timer skipped: {self._precompact_payload(state)}",
+            )
+            self._precompact_timer = None
+            return
+
         threshold = int(state.get("context_threshold", policy["context_threshold"]))
         if self._last_context.get("percentage", 0) < threshold:
             state["skip_reason"] = "low_context"
             self._log(
                 "status",
                 f"precompact timer skipped: {self._precompact_payload(state)}",
             )
             self._precompact_timer = None
@@ -1402,31 +1420,56 @@ class AgentSession:
             await self.send("[system] Turn limit reached. Continue where you left off.")
             logger.info(f"[{self.name}] auto-continue after max_turns")
         except Exception as e:
             logger.warning(f"[{self.name}] auto-continue failed: {e}")
             self.status = AgentStatus.IDLE
             self._persist()
             self._turns.publish_turn_finished()
 
-    async def _refresh_context_from_api(self) -> None:
+    async def _refresh_context_from_api(
+        self, *, schedule_compaction_on_success: bool = False,
+    ) -> None:
         if not self._backend or not hasattr(self._backend, 'context_usage'):
             return
         try:
             usage = await asyncio.wait_for(self._backend.context_usage(), timeout=5)
             if usage and usage.get("percentage") is not None:
-                old_pct = self._last_context.get("percentage", 0)
-                self._last_context["percentage"] = usage["percentage"]
-                self._last_context["total_tokens"] = usage.get("total_tokens", 0)
                 raw_max = usage.get("raw_max_tokens") or usage.get("max_tokens")
-                if raw_max:
-                    self._last_context["max_tokens"] = raw_max
-                if abs(old_pct - usage["percentage"]) > 30:
-                    logger.info(f"[{self.name}] context corrected: {old_pct}% → {usage['percentage']}%")
+                context = current_context(
+                    usage.get("total_tokens"),
+                    raw_max,
+                    percentage=usage.get("percentage"),
+                    unknown_reason="context API omitted a current-context value",
+                )
+                if not isinstance(context, KnownContext):
+                    self._last_context["percentage"] = 0
+                    self._last_context["total_tokens"] = 0
+                    self._last_context["known"] = False
+                    self._log(
+                        "status",
+                        f"context unknown ({context.reason}); "
+                        "automatic compaction skipped",
+                    )
+                    self._cancel_precompact_timer("context_unknown")
+                    self._persist()
+                    return
+                old_pct = self._last_context.get("percentage", 0)
+                self._last_context["percentage"] = context.percentage
+                self._last_context["total_tokens"] = context.tokens
+                self._last_context["max_tokens"] = context.max_tokens
+                self._last_context["known"] = True
+                if abs(old_pct - context.percentage) > 30:
+                    logger.info(
+                        f"[{self.name}] context corrected: "
+                        f"{old_pct}% → {context.percentage}%"
+                    )
                 self._persist()
+                if schedule_compaction_on_success:
+                    self._turns.schedule_context_compaction(context.percentage)
         except asyncio.TimeoutError:
             logger.debug(f"[{self.name}] context refresh timeout (5s)")
         except Exception as e:
             logger.debug(f"[{self.name}] context refresh failed: {e}")
 
     async def _auto_compact(self) -> None:
         await asyncio.sleep(2)
         try:
diff --git a/app/session_cost.py b/app/session_cost.py
index 7bf9076a3..334407a9d 100644
--- a/app/session_cost.py
+++ b/app/session_cost.py
@@ -3,25 +3,36 @@
 Stateless method-holder (ECS style): all fields live on the session; this class
 only encapsulates the delta-based cost arithmetic. Extracted AS-IS from
 AgentSession — the delta→total rewrite suggested by the audit is a deliberate
 non-goal (behavior-preserving refactor).
 """
 
 from typing import TYPE_CHECKING
 
+from app.usage_contract import (
+    DeferredContext,
+    KnownContext,
+    TurnUsage,
+    UnknownContext,
+    current_context,
+    deferred_context,
+)
+
 if TYPE_CHECKING:
     from app.session import AgentSession
 
 
 class CostTracker:
     def __init__(self, s: "AgentSession") -> None:
         self.s = s
 
-    def apply_turn_result(self, meta: dict) -> tuple[bool, str, int]:
+    def apply_turn_result(
+        self, meta: dict, usage: TurnUsage | None = None,
+    ) -> tuple[bool, str, int]:
         """Update session_id, costs, token totals from turn metadata."""
         s = self.s
         ok = meta.get("ok", True)
         sr = meta.get("stop_reason", "unknown")
         nt = meta.get("num_turns", 0)
         s._last_turn_ok = ok
         s._last_stop_reason = sr
 
@@ -46,30 +57,79 @@ class CostTracker:
         new_cost_cached = meta.get("cost_usd_cached", 0)
         if is_delta:
             s.cost_usd_cached += max(0, new_cost_cached)
             s._last_cost_cached = 0.0
         else:
             s.cost_usd_cached += max(0, new_cost_cached - s._last_cost_cached)
             s._last_cost_cached = new_cost_cached
         s.total_turns += nt
-        s.total_input_tokens += meta.get("input_tokens", 0)
-        s.total_output_tokens += meta.get("output_tokens", 0)
-        s.total_cache_read_tokens += meta.get("cache_read", 0)
-        s.total_cache_create_tokens += meta.get("cache_create", 0)
+        aggregate = usage.aggregate if usage is not None else None
+        s.total_input_tokens += (
+            aggregate.input_tokens if aggregate else meta.get("input_tokens", 0)
+        )
+        s.total_output_tokens += (
+            aggregate.output_tokens if aggregate else meta.get("output_tokens", 0)
+        )
+        s.total_cache_read_tokens += (
+            aggregate.cache_read_tokens if aggregate else meta.get("cache_read", 0)
+        )
+        s.total_cache_create_tokens += (
+            aggregate.cache_create_tokens if aggregate else meta.get("cache_create", 0)
+        )
         return ok, sr, nt
 
-    def update_context_from_turn(self, meta: dict) -> None:
-        """Update context window stats from turn metadata."""
+    def update_context_from_turn(
+        self, meta: dict, usage: TurnUsage | None = None,
+    ) -> tuple[bool, str | None]:
+        """Update context stats and return whether compaction has valid input."""
         s = self.s
-        ctx_pct = meta.get("context_pct", 0)
-        ctx_tokens = meta.get("context_tokens", 0)
-        if meta.get("context_known") is False:
-            # Explicit fail-soft signal from a backend: clear stale dashboard data.
+        if usage is not None:
+            context = usage.current
+        elif meta.get("context_deferred"):
+            context = deferred_context(
+                meta.get("max_tokens"),
+                str(meta.get("context_source") or "external"),
+            )
+        elif meta.get("context_known") is True:
+            context = current_context(
+                meta.get("context_tokens"),
+                meta.get("max_tokens"),
+                percentage=meta.get("context_pct"),
+            )
+        else:
+            try:
+                max_tokens = max(0, int(meta.get("max_tokens") or 0))
+            except (TypeError, ValueError, OverflowError):
+                max_tokens = 0
+            context = UnknownContext(
+                max_tokens,
+                str(
+                    meta.get("context_unknown_reason")
+                    or "turn_end omitted a valid typed current context"
+                ),
+            )
+
+        if isinstance(context, KnownContext):
+            s._last_context["percentage"] = context.percentage
+            s._last_context["total_tokens"] = context.tokens
+            s._last_context["max_tokens"] = context.max_tokens
+            s._last_context["known"] = True
+            known = True
+            reason = None
+        elif isinstance(context, DeferredContext):
+            if context.max_tokens:
+                s._last_context["max_tokens"] = context.max_tokens
+            known = s._context_is_known()
+            reason = None
+        else:
             s._last_context["percentage"] = 0
             s._last_context["total_tokens"] = 0
-        elif ctx_pct:
-            s._last_context["percentage"] = ctx_pct
-            s._last_context["total_tokens"] = ctx_tokens
-        s._last_context["max_tokens"] = meta.get("max_tokens", 200000)
+            if context.max_tokens:
+                s._last_context["max_tokens"] = context.max_tokens
+            s._last_context["known"] = False
+            known = False
+            reason = context.reason
+
         s._last_context["cache_hit"] = meta.get("cache_hit", 0)
         s._last_context["cache_read"] = meta.get("cache_read", 0)
         s._last_context["cache_create"] = meta.get("cache_create", 0)
+        return known, reason
diff --git a/app/session_turns.py b/app/session_turns.py
index 7137ce5a3..e8c6e7b79 100644
--- a/app/session_turns.py
+++ b/app/session_turns.py
@@ -120,17 +120,17 @@ class TurnManager:
                 logger.error(f"Auto-report failed for {s.name}: {e}")
 
         s._auto_report_task = asyncio.create_task(_do_report())
 
     def handle_turn_end(self, event: AgentEvent) -> None:
         s = self.s
         meta = event.metadata
         s._turn_start = 0
-        ok, sr, nt = s._cost.apply_turn_result(meta)
+        ok, sr, nt = s._cost.apply_turn_result(meta, event.usage)
         event_id = str(meta.get("event_id") or "")
         if event_id:
             s._submit_db_write(
                 turn_usage_add,
                 event_id=event_id,
                 session_id=s.id,
                 scope=s.scope,
                 task_id=s.task_id,
@@ -139,19 +139,42 @@ class TurnManager:
                 ok=ok,
                 stop_reason=sr,
                 cost_usd=s._turn_cost,
                 input_tokens=meta.get("input_tokens", 0),
                 output_tokens=meta.get("output_tokens", 0),
                 cache_read_tokens=meta.get("cache_read", 0),
                 cache_create_tokens=meta.get("cache_create", 0),
             )
-        s._cost.update_context_from_turn(meta)
-        s._spawn_bg(s._refresh_context_from_api())
+        context_known, context_reason = s._cost.update_context_from_turn(
+            meta, event.usage,
+        )
+        if context_reason:
+            s._log(
+                "status",
+                f"context unknown ({context_reason}); automatic compaction skipped",
+            )
+        if not context_known:
+            s._cancel_precompact_timer("context_unknown")
         subscription_limited = s._session_limit_hit
+        will_auto_continue = (
+            sr in ("error_max_turns", "max_turns")
+            and ok
+            and s._auto_continue_count < s.AUTO_CONTINUE_MAX
+        )
+        allow_context_compaction = (
+            not subscription_limited and not will_auto_continue
+        )
+        s._spawn_bg(
+            s._refresh_context_from_api(
+                schedule_compaction_on_success=(
+                    allow_context_compaction and not context_known
+                ),
+            )
+        )
 
         if not ok:
             # CLI injects [ede_diagnostic] telemetry on interrupt — cosmetic noise, not real errors
             errors = [e for e in (meta.get("errors") or []) if not str(e).startswith("[ede_diagnostic]")]
             if errors and not (
                 subscription_limited
                 and all(str(error).lower() == "rate_limit" for error in errors)
             ):
@@ -204,17 +227,17 @@ class TurnManager:
             f"${_fc(s.cost_usd)} total {ctx_s}){limits_s}",
             event_id=event_id,
         )
 
         self.finish_turn_status()
         self.after_turn_idle_actions(
             live_pct,
             allow_auto_report=server_error_retry is None,
-            allow_precompact=not subscription_limited,
+            allow_precompact=allow_context_compaction and context_known,
         )
         if server_error_retry is not None:
             s._spawn_bg(s._retry_after_server_error(*server_error_retry))
 
     def finish_turn_status(self) -> None:
         """Set IDLE or WAITING based on bg jobs, then persist."""
         s = self.s
         from app.bg_jobs import bg_manager
@@ -232,36 +255,39 @@ class TurnManager:
             self, live_pct: int, *, allow_auto_report: bool = True,
             allow_precompact: bool = True) -> None:
         """Post-turn actions: compact ack, scope idle, auto-compact, auto-report, flush/hibernate."""
         s = self.s
         if s._compact_ack_event is not None and s._turn_gen == s._compact_ack_gen:
             s._compact_ack_event.set()
 
         if allow_precompact:
-            s._schedule_precompact_timer(live_pct)
+            self.schedule_context_compaction(live_pct)
         s._spawn_bg(s._notify_scope_idle())
 
-        if (
-            allow_precompact
-            and live_pct > 90
-            and s.backend_type != "codex"
-            and not s.is_orchestrator
-            and not s._compacting
-        ):
-            # Workers auto-compact to stay operational; orchestrators are left for
-            # the user to compact manually since they hold long-running session state.
-            # Codex app-server compacts the current thread natively; replacing that
-            # thread with Orchestra's generic handoff loses native thread continuity.
-            s._log("status", f"auto-compact triggered ({live_pct}%)")
-            s._spawn_bg(s._auto_compact())
-
         # Don't auto-report mid-flight: WAITING means a bg job (e.g. codex_review) is
         # still running and will wake the worker with its result — the turn isn't
         # really "done", so reporting now spams a half-status to the orchestrator.
         if allow_auto_report and s.status != AgentStatus.WAITING:
             self.fire_auto_report()
 
         if s._pending_messages:
             s._spawn_bg(s._flush_pending())
             return
 
         s._hibernate.schedule()
+
+    def schedule_context_compaction(self, live_pct: int) -> None:
+        """Run both automatic compaction decisions from one validated context."""
+        s = self.s
+        s._schedule_precompact_timer(live_pct)
+        if (
+            live_pct > 90
+            and s.backend_type != "codex"
+            and not s.is_orchestrator
+            and not s._compacting
+        ):
+            # Workers auto-compact to stay operational; orchestrators are left for
+            # the user to compact manually since they hold long-running session state.
+            # Codex app-server compacts the current thread natively; replacing that
+            # thread with Orchestra's generic handoff loses native thread continuity.
+            s._log("status", f"auto-compact triggered ({live_pct}%)")
+            s._spawn_bg(s._auto_compact())
diff --git a/app/usage_contract.py b/app/usage_contract.py
new file mode 100644
index 000000000..42773a712
--- /dev/null
+++ b/app/usage_contract.py
@@ -0,0 +1,184 @@
+"""Typed usage values shared by runtime backends and turn accounting."""
+
+from dataclasses import dataclass
+from typing import TypeAlias
+
+
+def _count(value: object) -> int:
+    if isinstance(value, bool):
+        return 0
+    try:
+        return max(0, int(value or 0))
+    except (TypeError, ValueError, OverflowError):
+        return 0
+
+
+def _optional_count(value: object) -> int | None:
+    if value is None or isinstance(value, bool):
+        return None
+    try:
+        return max(0, int(value))
+    except (TypeError, ValueError, OverflowError):
+        return None
+
+
+@dataclass(frozen=True)
+class AggregateUsage:
+    """Billed totals accumulated across every model call in one runtime turn."""
+
+    input_tokens: int
+    output_tokens: int
+    cache_read_tokens: int = 0
+    cache_create_tokens: int = 0
+    model_calls: int | None = None
+
+    @classmethod
+    def normalized(
+        cls,
+        *,
+        input_tokens: object = 0,
+        output_tokens: object = 0,
+        cache_read_tokens: object = 0,
+        cache_create_tokens: object = 0,
+        model_calls: object = None,
+    ) -> "AggregateUsage":
+        return cls(
+            input_tokens=_count(input_tokens),
+            output_tokens=_count(output_tokens),
+            cache_read_tokens=_count(cache_read_tokens),
+            cache_create_tokens=_count(cache_create_tokens),
+            model_calls=_optional_count(model_calls),
+        )
+
+
+@dataclass(frozen=True)
+class KnownContext:
+    """Occupied prompt/window measured at the end of the latest model call."""
+
+    tokens: int
+    max_tokens: int
+    percentage: int
+
+
+@dataclass(frozen=True)
+class UnknownContext:
+    """No valid current-context measurement is available for this turn."""
+
+    max_tokens: int
+    reason: str
+
+
+@dataclass(frozen=True)
+class DeferredContext:
+    """The provider reports context through a separate authoritative channel."""
+
+    max_tokens: int
+    source: str
+
+
+CurrentContext: TypeAlias = KnownContext | UnknownContext | DeferredContext
+
+
+def current_context(
+    current_tokens: object,
+    max_tokens: object,
+    *,
+    semantics_known: bool = True,
+    percentage: object = None,
+    unknown_reason: str = "",
+) -> KnownContext | UnknownContext:
+    """Validate a current-context measurement without rejecting the turn."""
+    valid_max = _optional_count(max_tokens)
+    normalized_max = valid_max or 0
+    if not semantics_known:
+        return UnknownContext(
+            normalized_max,
+            unknown_reason or "current context semantics are not proven",
+        )
+    if current_tokens is None:
+        return UnknownContext(
+            normalized_max,
+            unknown_reason or "current context is missing",
+        )
+    if isinstance(current_tokens, bool):
+        return UnknownContext(normalized_max, "current context is not an integer")
+    try:
+        normalized_current = int(current_tokens)
+    except (TypeError, ValueError, OverflowError):
+        return UnknownContext(normalized_max, "current context is not an integer")
+    if normalized_current < 0:
+        return UnknownContext(normalized_max, "current context is negative")
+    if not valid_max:
+        return UnknownContext(normalized_max, "maximum context is missing or invalid")
+    if normalized_current > valid_max:
+        return UnknownContext(
+            normalized_max,
+            f"current context {normalized_current} exceeds maximum {valid_max}",
+        )
+
+    if percentage is None:
+        normalized_percentage = int(normalized_current * 100 / valid_max)
+    elif isinstance(percentage, bool):
+        return UnknownContext(normalized_max, "context percentage is not numeric")
+    else:
+        try:
+            normalized_percentage = int(percentage)
+        except (TypeError, ValueError, OverflowError):
+            return UnknownContext(normalized_max, "context percentage is not numeric")
+        if not 0 <= normalized_percentage <= 100:
+            return UnknownContext(normalized_max, "context percentage is outside 0..100")
+
+    return KnownContext(
+        tokens=normalized_current,
+        max_tokens=valid_max,
+        percentage=normalized_percentage,
+    )
+
+
+def deferred_context(max_tokens: object, source: str) -> DeferredContext:
+    return DeferredContext(max_tokens=_optional_count(max_tokens) or 0, source=source)
+
+
+@dataclass(frozen=True)
+class TurnUsage:
+    """One turn's billed aggregate plus a semantically distinct current context."""
+
+    aggregate: AggregateUsage
+    current: CurrentContext
+
+    def metadata(self) -> dict:
+        aggregate = self.aggregate
+        result = {
+            "input_tokens": aggregate.input_tokens,
+            "output_tokens": aggregate.output_tokens,
+            "cached_input_tokens": aggregate.cache_read_tokens,
+            "cache_read": aggregate.cache_read_tokens,
+            "cache_create": aggregate.cache_create_tokens,
+            "model_calls": aggregate.model_calls,
+        }
+        current = self.current
+        if isinstance(current, KnownContext):
+            result.update({
+                "context_pct": current.percentage,
+                "context_tokens": current.tokens,
+                "context_known": True,
+                "max_tokens": current.max_tokens,
+            })
+        elif isinstance(current, DeferredContext):
+            result.update({
+                "context_pct": 0,
+                "context_tokens": 0,
+                "context_known": False,
+                "context_deferred": True,
+                "context_source": current.source,
+                "max_tokens": current.max_tokens,
+            })
+        else:
+            result.update({
+                "context_pct": 0,
+                "context_tokens": 0,
+                "context_known": False,
+                "context_unknown_reason": current.reason,
+                "max_tokens": current.max_tokens,
+            })
+        return result
diff --git a/tests/test_backend_claude.py b/tests/test_backend_claude.py
index e814ed975..b550c537c 100644
--- a/tests/test_backend_claude.py
+++ b/tests/test_backend_claude.py
@@ -183,16 +183,42 @@ def test_result_uuid_is_carried_as_durable_turn_event_id():
         session_id="sdk-session",
         stop_reason="end_turn",
         uuid="result-uuid-1",
     ))[-1]
 
     assert event.metadata["event_id"] == "result-uuid-1"
 
 
+def test_result_uses_deferred_context_without_losing_aggregate_usage():
+    from app.usage_contract import DeferredContext
+
+    event = _backend()._convert(ResultMessage(
+        subtype="result",
+        duration_ms=10,
+        duration_api_ms=10,
+        is_error=False,
+        num_turns=2,
+        session_id="sdk-session",
+        stop_reason="end_turn",
+        usage={
+            "input_tokens": 12_000,
+            "output_tokens": 500,
+            "cache_read_input_tokens": 8_000,
+            "cache_creation_input_tokens": 1_000,
+        },
+    ))[-1]
+
+    assert event.usage.aggregate.input_tokens == 12_000
+    assert event.usage.aggregate.model_calls == 2
+    assert isinstance(event.usage.current, DeferredContext)
+    assert event.metadata["context_deferred"] is True
+    assert event.metadata["context_known"] is False
+
+
 def test_tool_failure_preserves_stable_use_id_and_explicit_error():
     backend = _backend()
     started = backend._convert(AssistantMessage(
         content=[ToolUseBlock(id="tool-1", name="Read", input={"file_path": "/x"})],
         model="claude-sonnet-5[1m]",
     ))
     completed = backend._convert(UserMessage(
         content=[ToolResultBlock(
diff --git a/tests/test_backend_codex.py b/tests/test_backend_codex.py
index 1f0d45b86..2972a15be 100644
--- a/tests/test_backend_codex.py
+++ b/tests/test_backend_codex.py
@@ -605,16 +605,46 @@ def test_completed_turn_id_is_carried_as_durable_event_id():
     events = backend._turn_completed({
         "id": "turn-1",
         "status": "completed",
     })
 
     assert events[-1].metadata["event_id"] == "turn-1"
 
 
+def test_turn_usage_keeps_codex_delta_and_last_call_context_distinct():
+    from app.usage_contract import KnownContext
+
+    backend = CodexBackend(model="gpt-5.6-sol", cwd="/tmp")
+    backend._thread_usage_total = {
+        "input_tokens": 100_000,
+        "cached_input_tokens": 80_000,
+        "output_tokens": 2_000,
+    }
+    backend._usage_baseline = {
+        "input_tokens": 40_000,
+        "cached_input_tokens": 30_000,
+        "output_tokens": 500,
+    }
+    backend._last_call_usage = {
+        "input_tokens": 33_124,
+        "model_context_window": 258_400,
+    }
+
+    end = backend._turn_completed({
+        "id": "turn-usage",
+        "status": "completed",
+    })[-1]
+
+    assert end.usage.aggregate.input_tokens == 60_000
+    assert isinstance(end.usage.current, KnownContext)
+    assert end.metadata["context_tokens"] == 33_124
+    assert end.metadata["context_known"] is True
+
+
 def test_explicit_codex_tool_failures_keep_identity_and_tool_name():
     backend = CodexBackend(model="gpt-5.6-sol", cwd="/tmp")
 
     command = backend._item_completed({
         "id": "cmd-1",
         "type": "commandExecution",
         "command": "false",
         "aggregatedOutput": "exit 1",
diff --git a/tests/test_backend_grok.py b/tests/test_backend_grok.py
index ee609bb95..442392849 100644
--- a/tests/test_backend_grok.py
+++ b/tests/test_backend_grok.py
@@ -104,16 +104,17 @@ def test_cached_rate_is_runtime_value_not_published_value():
 
 def test_context_limit_is_runtime_reported():
     assert GROK_CONTEXT_LIMITS["grok-4.5"] == 500000


## LATER FIX 5e11d8772f (18.7 days later): fix: stabilize Grok session replay and chat finalization
lines of origin it changed/deleted: 2
(code only, capped 400 lines)

fix: stabilize Grok session replay and chat finalization


diff --git a/app/backend_grok.py b/app/backend_grok.py
index f33ae2d50..ce76723b9 100644
--- a/app/backend_grok.py
+++ b/app/backend_grok.py
@@ -164,26 +164,81 @@ def _grok_cost(model: str, input_tokens: int, cached_tokens: int, output_tokens:
     # Deliberately a short-context fallback. ACP exposes a turn aggregate, while the 200k
     # tier applies per model request; a tool-loop can mix tiers. Runtime costUsdTicks remains
     # the only exact source until ACP exposes per-request usage (docs/tasks/251/research.md).
     return (fresh * prices["input"] + cached * prices["cached"]
             + max(0, output_tokens) * prices["output"]) / 1_000_000
 
 
 def _content_text(content) -> str:
-    """Flatten an ACP content block (or list of them) to text."""
+    """Flatten an ACP content block (or list of them) to text.
+
+    Grok wraps tool results as `{type: "content", content: {type: "text", text: ...}}`
+    and MCP results as `{type: "MCP", tool_name, output: {OkayOutput: ...}}`.
+    Dumping the outer object left the dashboard showing raw JSON grids instead of
+    the tool output itself.
+    """
     if isinstance(content, dict):
-        if content.get("type") == "text":
+        ctype = content.get("type")
+        if ctype == "text":
+            return str(content.get("text", ""))
+        # Grok MCP tool_call_update payload (measured 15.08.2026).
+        if ctype == "MCP" or (
+            isinstance(content.get("output"), dict)
+            and ("tool_name" in content or "server_name" in content)
+        ):
+            output = content.get("output")
+            if isinstance(output, dict):
+                for key in (
+                    "OkayOutput", "ErrorOutput", "output", "text", "result", "content",
+                ):
+                    if key in output and output[key] not in (None, ""):
+                        return _content_text(output[key])
+                # Last resort: first non-empty string value in output.
+                for value in output.values():
+                    if isinstance(value, str) and value.strip():
+                        return value
+                    inner = _content_text(value)
+                    if inner.strip():
+                        return inner
+            elif output is not None:
+                return _content_text(output)
+        # Nested content wrapper from Grok tool_call_update / MCP results.
+        if "content" in content and ctype in (None, "content", "resource", "resource_link"):
+            inner = _content_text(content.get("content"))
+            if inner:
+                return inner
+        if "text" in content and ctype is None:
             return str(content.get("text", ""))
         return json.dumps(bounded_tool_arguments(content), ensure_ascii=False)
     if isinstance(content, list):
-        return "\n".join(_content_text(part) for part in content)
+        parts = [_content_text(part) for part in content]
+        return "\n".join(part for part in parts if part)
     return str(content) if content is not None else ""
 
 
+def _headers_to_acp(headers) -> list[dict]:
+    """ACP rejects bare http/sse MCP entries without a `headers` array (even empty)."""
+    if not headers:
+        return []
+    if isinstance(headers, dict):
+        return [{"name": str(k), "value": str(v)} for k, v in headers.items()]
+    if isinstance(headers, list):
+        out = []
+        for item in headers:
+            if not isinstance(item, dict):
+                continue
+            name = item.get("name")
+            if name is None:
+                continue
+            out.append({"name": str(name), "value": str(item.get("value", ""))})
+        return out
+    return []
+
+
 def _mcp_server_identity(server: dict) -> tuple:
     """Canonical identity for an ACP MCP config, excluding discovery metadata."""
     raw_env = server.get("env") or []
     if isinstance(raw_env, dict):
         env = tuple(sorted((str(k), str(v)) for k, v in raw_env.items()))
     else:
         env = tuple(sorted(
             (str(item.get("name")), str(item.get("value", "")))
@@ -254,16 +309,26 @@ class GrokBackend(JsonRpcStdioTransport):
         self._last_stderr = ""
         self._profile_path: Path | None = None
         # Turn bookkeeping. `_active_prompts` counts prompts accepted but not yet completed —
         # the agent queues extras, so the event loop must not stop at the first completion.
         self._active_prompts = 0
         self._queue_depth = 0
         self._completed_prompts: set[str] = set()
         self._tool_names: dict[str, str] = {}
+        # Grok only streams message/thought chunks — never a final item-complete event.
+        # Session persists `text`/`thinking`, not live `stream`/`thinking_stream`, so without
+        # these buffers assistant replies vanish from history and leave the UI bubble open
+        # across turns (messages glue, reasoning floats as a live card forever).
+        self._message_buf: list[str] = []
+        self._thought_buf: list[str] = []
+        # session/load replays prior turns as session/update notifications. If those land
+        # in the event stream they are re-logged as "new" tool/text/thinking rows and bury
+        # real user messages under a flood (measured: full history dumped at 07:36 and 07:40).
+        self._suppress_history_replay = False
         # turn_completed carries usage; the turn_end is emitted by the prompt completion.
         self._pending_usage: dict = {}
         self._model_context_window = GROK_CONTEXT_LIMITS.get(model, GROK_DEFAULT_CONTEXT)
         self._context_tokens: int | None = None
         self._mcp_canary: str | None = None
         self._issue_mcp_canary()
         # A matching name is insufficient: a repository can define another command under it.
         expected_configs = self._mcp_server_configs()
@@ -351,47 +416,61 @@ class GrokBackend(JsonRpcStdioTransport):
                 "clientCapabilities": {
                     "fs": {"readTextFile": False, "writeTextFile": False},
                     "terminal": False,
                 },
             })
             self._absorb_model_meta(result.get("_meta") or {})
             params = {"cwd": self.cwd, "mcpServers": self._mcp_server_configs()}
             result = None
-            if self._session_id:
-                try:
-                    result = await self._request(
-                        "session/load", {**params, "sessionId": self._session_id}
-                    )
-                except GrokProtocolError as exc:
-                    # A stale id must not brick the worker forever: the store is keyed by
-                    # (cwd, sessionId), so a moved or pruned worktree makes load fail
-                    # permanently. Start fresh — but never quietly, the lost history is
-                    # exactly what someone would otherwise spend an hour looking for.
-                    logger.warning(
-                        "Grok session/load failed for %s (%s) — starting a fresh session",
-                        self._session_id, exc,
-                    )
-                    self._notifications.put_nowait({
-                        "method": "_session/resume_failed",
-                        # NOT "sessionId": events() drops notifications whose sessionId is
-                        # not the current one, and this warning is about the OLD id — it
-                        # would filter out the very message announcing the lost history.
-                        "params": {"staleSessionId": self._session_id, "message": str(exc)},
-                    })
-                    self._session_id = None
-            if result is None:
-                result = await self._request("session/new", params)
-                session_id = result.get("sessionId")
-                if not session_id:
-                    raise RuntimeError("Grok ACP returned no session id")
-                self._session_id = session_id
-            self._absorb_models(result.get("models") or {})
+            # Drop session/update content while load/new runs — Grok replays the whole
+            # transcript into the notification queue, and the first turn after connect
+            # would re-persist it as brand-new logs.
+            self._suppress_history_replay = True
+            try:
+                if self._session_id:
+                    try:
+                        result = await self._request(
+                            "session/load", {**params, "sessionId": self._session_id}
+                        )
+                    except GrokProtocolError as exc:
+                        # A stale id must not brick the worker forever: the store is keyed by
+                        # (cwd, sessionId), so a moved or pruned worktree makes load fail
+                        # permanently. Start fresh — but never quietly, the lost history is
+                        # exactly what someone would otherwise spend an hour looking for.
+                        logger.warning(
+                            "Grok session/load failed for %s (%s) — starting a fresh session",
+                            self._session_id, exc,
+                        )
+                        self._notifications.put_nowait({
+                            "method": "_session/resume_failed",
+                            # NOT "sessionId": events() drops notifications whose sessionId is
+                            # not the current one, and this warning is about the OLD id — it
+                            # would filter out the very message announcing the lost history.
+                            "params": {
+                                "staleSessionId": self._session_id,
+                                "message": str(exc),
+                            },
+                        })
+                        self._session_id = None
+                if result is None:
+                    result = await self._request("session/new", params)
+                    session_id = result.get("sessionId")
+                    if not session_id:
+                        raise RuntimeError("Grok ACP returned no session id")
+                    self._session_id = session_id
+                self._absorb_models(result.get("models") or {})
+                # Anything already queued during load is history replay — drop content
+                # updates, keep MCP startup (isolation still needs them).
+                self._drain_history_replay_queue()
+            finally:
+                self._suppress_history_replay = False
             await self._verify_mcp_isolation()
         except BaseException:
+            self._suppress_history_replay = False
             await self.disconnect()
             raise
 
     async def _verify_mcp_isolation(self) -> None:
         """Fail connect unless the observed MCP roster exactly matches the launch plan.
 
         The GROK_HOME sandbox suppresses Claude-compat discovery, and a repo `.mcp.json` is
         additionally gated behind folder trust. Neither guarantee is ours to enforce, so the
@@ -691,16 +770,22 @@ class GrokBackend(JsonRpcStdioTransport):
                                 "method": "_prompt/result",
                                 "params": result,
                             })
                     continue
                 if message.get("method"):
                     # Track MCP startup here, not in events(): isolation is verified during
                     # connect(), before any consumer starts draining the event stream.
                     self._track_mcp(message)
+                    if (
+                        self._suppress_history_replay
+                        and message.get("method") == "session/update"
+                    ):
+                        # session/load replays prior turns; do not surface them as new events.
+                        continue
                     await self._notifications.put(message)
         except asyncio.CancelledError:
             return
         except Exception as exc:
             logger.exception("Grok ACP reader failed: %s", exc)
         finally:
             returncode = await proc.wait()
             error = RuntimeError(f"Grok ACP agent exited with code {returncode}")
@@ -846,17 +931,17 @@ class GrokBackend(JsonRpcStdioTransport):
                 "warning",
                 f"grok could not resume session {params.get('staleSessionId')} "
                 f"({params.get('message')}) — continuing in a NEW session, "
                 f"previous conversation history is not available",
             )]
 
         if method == "_prompt/failed":
             self._active_prompts = max(0, self._active_prompts - 1)
-            return [
+            return self._flush_open_streams() + [
                 AgentEvent("error", params.get("message", "Grok prompt failed"),
                            {"model_error": "error"}),
                 self._turn_end_event(False, "error", "error"),
             ]
 
         if method == "_x.ai/mcp/server_status":
             return self._mcp_status(params)
 
@@ -883,79 +968,136 @@ class GrokBackend(JsonRpcStdioTransport):
             turn_usage = TurnUsage(
                 AggregateUsage.normalized(),
                 current_context(
                     None,
                     self._model_context_window,
                     unknown_reason="Grok exited before reporting current context",
                 ),
             )
-            return [AgentEvent("turn_end", "stop_reason=process_exit", metadata={
-                "session_id": self._session_id,
-                "ok": False,
-                "stop_reason": f"process_exit_{params.get('returncode')}",
-                "returncode": params.get("returncode"),
-                "stderr_tail": params.get("stderr", ""),
-                "model_error": "server_error",
-                "errors": ["server_error"],
-                "cost_usd": 0,
-                **turn_usage.metadata(),
-            }, usage=turn_usage)]
+            return self._flush_open_streams() + [AgentEvent(
+                "turn_end", "stop_reason=process_exit", metadata={
+                    "session_id": self._session_id,
+                    "ok": False,
+                    "stop_reason": f"process_exit_{params.get('returncode')}",
+                    "returncode": params.get("returncode"),
+                    "stderr_tail": params.get("stderr", ""),
+                    "model_error": "server_error",
+                    "errors": ["server_error"],
+                    "cost_usd": 0,
+                    **turn_usage.metadata(),
+                }, usage=turn_usage,
+            )]
 
         return []
 
+    def _drain_history_replay_queue(self) -> None:
+        """Remove session/update content left in the queue after session/load."""
+        kept: list[dict] = []
+        while True:
+            try:
+                message = self._notifications.get_nowait()
+            except asyncio.QueueEmpty:
+                break
+            if message.get("method") == "session/update":
+                continue
+            kept.append(message)
+        for message in kept:
+            self._notifications.put_nowait(message)
+
+    def _flush_message(self) -> list[AgentEvent]:
+        text = "".join(self._message_buf)
+        self._message_buf.clear()
+        if not text:
+            return []
+        return [AgentEvent("text", text)]
+
+    def _flush_thought(self) -> list[AgentEvent]:
+        text = "".join(self._thought_buf)
+        self._thought_buf.clear()
+        if not text:
+            return []
+        return [AgentEvent("thinking", text)]
+
+    def _flush_open_streams(self) -> list[AgentEvent]:
+        # Thought before message: reasoning precedes the answer that used it.
+        return self._flush_thought() + self._flush_message()
+
     def _session_update(self, params: dict) -> list[AgentEvent]:
         update = params.get("update") or {}
         kind = update.get("sessionUpdate", "")
         meta = params.get("_meta") or {}
         total = meta.get("totalTokens")
         if isinstance(total, int) and total >= 0:
             self._context_tokens = total
 
         if kind == "agent_message_chunk":
-            return [AgentEvent("stream", _content_text(update.get("content")))]
+            chunk = _content_text(update.get("content"))
+            if chunk:
+                self._message_buf.append(chunk)
+            return [AgentEvent("stream", chunk)]
 
         if kind == "agent_thought_chunk":
-            return [AgentEvent("thinking_stream", _content_text(update.get("content")),
+            chunk = _content_text(update.get("content"))
+            if chunk:
+                self._thought_buf.append(chunk)
+            return [AgentEvent("thinking_stream", chunk,
                                {"activity": "reasoning",
                                 "item_id": str(meta.get("promptId") or "")})]
 
         if kind == "tool_call":
+            # Flush answer text before the tool so order is text → tool → result → text.
+            # Do NOT flush thinking here: Grok thinks between nearly every tool, and that
+            # produced 50+ reasoning cards per turn. One thinking card lands at turn_end.
+            events = self._flush_message()
             tool_id = str(update.get("toolCallId") or update.get("id") or "")
             name = str(update.get("title") or update.get("kind") or "tool")
             self._tool_names[tool_id] = name
-            return [AgentEvent(
+            events.append(AgentEvent(
                 "tool_use",
                 f"{name}: {json.dumps(bounded_tool_arguments(update.get('rawInput') or {}), ensure_ascii=False)}",
                 metadata={"tool_name": name, "short_name": name, "tool_use_id": tool_id},
-            )]
+            ))
+            return events
 
         if kind == "tool_call_update":
             return self._tool_call_update(update)
 
         if kind == "plan":
-            return [AgentEvent("plan", json.dumps(update.get("entries") or [],
-                                                  ensure_ascii=False))]
+            # Plan is mid-turn structure; keep reasoning open until the turn ends.
+            events = self._flush_message()
+            events.append(AgentEvent("plan", json.dumps(update.get("entries") or [],
+                                                        ensure_ascii=False)))
+            return events
         return []
 
     def _tool_call_update(self, update: dict) -> list[AgentEvent]:
         tool_id = str(update.get("toolCallId") or update.get("id") or "")
         status = update.get("status")
         title = update.get("title")
         if title and tool_id:
             # Grok routes MCP tools through a search_tool/use_tool meta-layer; the concrete
             # name (e.g. orchestra__list_agents) arrives on the update, not the initial call.
             self._tool_names[tool_id] = str(title)
         if status not in ("completed", "failed"):
             return []
         name = self._tool_names.get(tool_id, "tool")
         content = update.get("content")
-        text = _content_text(content) if content is not None else json.dumps(
-            {"status": status}, ensure_ascii=False
-        )
+        text = _content_text(content) if content is not None else ""
+        if not text.strip():
+            raw = update.get("rawOutput")
+            if raw is not None:
+                if isinstance(raw, (dict, list)):
+                    text = _content_text(raw)
+                    if not text.strip():
+                        text = json.dumps(bounded_tool_arguments(raw), ensure_ascii=False)
+                else:
+                    text = str(raw)
+        if not text.strip():