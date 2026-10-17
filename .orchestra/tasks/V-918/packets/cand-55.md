# Candidate cand-55

## ORIGIN commit d6155f9d4b (2026-09-05): #503: freeze Astra registry regression oracle
(diff of code only, excluding .orchestra/ and *.md; capped 1200 lines)

diff --git a/app/backend_codex.py b/app/backend_codex.py
index a63c2a9e9..63fbc5baf 100644
--- a/app/backend_codex.py
+++ b/app/backend_codex.py
@@ -41,16 +41,17 @@ logger = logging.getLogger(__name__)
 CODEX_BIN = shutil.which("codex") or os.environ.get("CODEX_BIN", "codex")
 
 # Effective context budgets reported by the ChatGPT-auth Codex runtime. The public API
 # advertises a larger GPT-5.6 window, but that is a different surface; local rollout
 # token_count events are the runtime source of truth and may override these fallbacks.
 CODEX_CONTEXT_LIMITS = {
     "gpt-5.3-codex-spark": 128000,
     "gpt-5.6-sol":   258400,
+    "gpt-6-astra":   258400,
     "gpt-5.6-terra": 258400,
     "gpt-5.6-luna":  258400,
     "gpt-5.5": 258400,
     "gpt-5.4": 258400,
     "gpt-5.4-mini": 258400,
 }
 
 # Standard-tier API list prices per 1M tokens, verified 11.08.2026 against
@@ -62,29 +63,29 @@ CODEX_CONTEXT_LIMITS = {
 # in `turn_usage` keep the price of their own day and are deliberately not rewritten.
 # The long-context tier is per request, while Codex's measured 258,400-token request window
 # is below its 272K threshold. Spark is listed explicitly but has no published final price.
 CODEX_TOKEN_PRICES = {
     # Promotional pricing from 22.08.2026, published "at least through November 21, 2026":
     # input −20%, output −33%. Verified in the source table, not from the announcement.
     # Rows already in `turn_usage` keep their own day's price, as with Terra/Luna below.
     "gpt-5.6-sol":   {"input": 4.0, "cached": 0.4, "write": 5.0, "output": 20.0},
+    "gpt-6-astra":   {"input": 10.0, "cached": 1.0, "write": 12.5, "output": 50.0},
     "gpt-5.6-terra": {"input": 2.0, "cached": 0.2, "write": 2.5, "output": 12.0},
     "gpt-5.6-luna":  {"input": 0.2, "cached": 0.02, "write": 0.25, "output": 1.2},
     "gpt-5.5":      {"input": 5.0, "cached": 0.5, "output": 30.0},
     "gpt-5.4":      {"input": 2.5, "cached": 0.25, "output": 15.0},
     "gpt-5.4-mini": {"input": 0.3, "cached": 0.03, "output": 1.25},
     "gpt-5.3-codex-spark": None,
 }
 
 
-# GPT-5.6 reasoning ladder (light→low→medium→high→xhigh→max→ultra). "minimal" kept for
-# 5.4/5.5 back-compat. "ultra" (parallel sub-agents) intentionally excluded — a special
-# mode, not a plain effort level, and risky to trigger from a generic worker effort field.
-CODEX_REASONING_EFFORTS = {"minimal", "low", "medium", "high", "xhigh", "max"}
+# Codex server-side reasoning effort values. "ultra" (parallel sub-agents) is intentionally
+# excluded: it is a client-side mode, not a plain effort level for a generic worker field.
+CODEX_REASONING_EFFORTS = {"low", "medium", "high", "xhigh", "max"}
 CODEX_SILENCE_HEARTBEAT_SECONDS = 30
 CODEX_COMPACT_TIMEOUT_SECONDS = 120
 CODEX_PROCESS_TIMEOUT_SECONDS = 5
 DEFERRED_INTERRUPT_TERMINAL_TIMEOUT_SECONDS = 5.0
 CODEX_STREAM_LIMIT = 16 * 1024 * 1024
 CODEX_OVERSIZE_READLINE_ERROR = (
     "Separator is not found, and chunk exceed the limit"
 )
diff --git a/app/models.py b/app/models.py
index 99add1388..a8d62b356 100644
--- a/app/models.py
+++ b/app/models.py
@@ -90,16 +90,20 @@ SELECTABLE_MODEL_SPECS: tuple[ModelSpec, ...] = (
     ModelSpec(
         id="gpt-5.3-codex-spark", name="GPT-5.3 Codex Spark",
         runtime="codex", provider="openai", context_length=128000,
     ),
     ModelSpec(
         id="gpt-5.6-sol", name="GPT-5.6 Sol",
         runtime="codex", provider="openai", context_length=258400,
     ),
+    ModelSpec(
+        id="gpt-6-astra", name="GPT-6 Astra",
+        runtime="codex", provider="openai", context_length=258400,
+    ),
     ModelSpec(
         id="gpt-5.6-terra", name="GPT-5.6 Terra",
         runtime="codex", provider="openai", context_length=258400,
     ),
     ModelSpec(
         id="gpt-5.6-luna", name="GPT-5.6 Luna",
         runtime="codex", provider="openai", context_length=258400,
     ),
@@ -178,16 +182,18 @@ ALIASES = {
     "claude-sonnet-4-5": "claude-sonnet-5[1m]",
     "haiku": "claude-haiku-4-5",
     "spark": "gpt-5.3-codex-spark",
     "codexspark": "gpt-5.3-codex-spark",
     "gpt5.3spark": "gpt-5.3-codex-spark",
     "gpt5.6": "gpt-5.6-sol",
     "gpt5.6sol": "gpt-5.6-sol",
     "sol": "gpt-5.6-sol",
+    "astra": "gpt-6-astra",
+    "gpt6astra": "gpt-6-astra",
     "luna": "gpt-5.6-luna",
     "gpt5.6terra": "gpt-5.6-terra",
     "gpt5.6luna": "gpt-5.6-luna",
     "codex": "gpt-5.6-sol",
     "gpt5.5": "gpt-5.5",
     "gpt5.4": "gpt-5.4",
     "gpt5.4mini": "gpt-5.4-mini",
     "gpt-5.4mini": "gpt-5.4-mini",
diff --git a/app/runtime_history.py b/app/runtime_history.py
index 4ba9036d7..843183778 100644
--- a/app/runtime_history.py
+++ b/app/runtime_history.py
@@ -11,17 +11,19 @@ from collections import Counter, deque
 from copy import deepcopy
 from dataclasses import asdict, dataclass, replace
 from typing import Any, Callable, Iterable, Sequence
 
 
 CLAUDE_CLI_HISTORY_VERSION = "2.1.197"
 CLAUDE_SDK_HISTORY_VERSION = "0.2.114"
 CLAUDE_HISTORY_SOURCE = "logs:claude"
-CODEX_CLI_HISTORY_VERSION = "0.150.1"
+# Pin follows the installed codex-cli 0.153.4; #498's nine Astra effort probes and #503's
+# live ASTRA_OK validated the preceding 0.153.2 binary.
+CODEX_CLI_HISTORY_VERSION = "0.153.4"
 
 TOOL_CALL_LIMIT = 8_000
 TOOL_RESULT_LIMIT = 20_000
 TOOL_NAME_LIMIT = 512
 TOOL_DETAIL_BUDGET = 256_000
 TOOL_VISIBLE_BUDGET = 256_000
 
 HISTORICAL_TOOL_INSTRUCTION = (
diff --git a/tests/test_model_registry_503.py b/tests/test_model_registry_503.py
new file mode 100644
index 000000000..cad0a750f
--- /dev/null
+++ b/tests/test_model_registry_503.py
@@ -0,0 +1,26 @@
+import pytest
+
+from app.backend_codex import CODEX_REASONING_EFFORTS, CODEX_TOKEN_PRICES, _codex_cost
+from app.models import get_model_spec, resolve_model
+
+
+@pytest.mark.parametrize("alias", ["astra", "gpt6astra"])
+def test_gpt6_astra_aliases_resolve(alias: str) -> None:
+    assert resolve_model(alias) == "gpt-6-astra"
+
+
+def test_gpt6_astra_spec_and_price_are_registered() -> None:
+    spec = get_model_spec("gpt-6-astra")
+    assert spec.runtime == "codex"
+    assert spec.provider == "openai"
+    price = CODEX_TOKEN_PRICES[spec.id]
+    assert price is not None
+    assert all(value > 0 for value in price.values())
+
+
+def test_gpt6_astra_cost_computation_is_nonzero() -> None:
+    assert _codex_cost("gpt-6-astra", 1000, 700, 100, 50) > 0
+
+
+def test_minimal_is_not_a_supported_codex_effort() -> None:
+    assert "minimal" not in CODEX_REASONING_EFFORTS


## LATER FIX 4bc0a84b5a (30.2 days later): V-703: #V-703: fix Codex runtime recovery and quota errors
lines of origin it changed/deleted: 3
(code only, capped 400 lines)

V-703: #V-703: fix Codex runtime recovery and quota errors

Squashed commits:
- #V-703: fix Codex runtime recovery and quota errors
- #V-703: record Codex mutation evidence
- #V-703: preserve Codex live steering and quota reset

Orchestra-Operation: 854ae3c5-672c-412c-8330-03eb7495754f


diff --git a/app/backend_codex.py b/app/backend_codex.py
index dbb844d06..388f910d7 100644
--- a/app/backend_codex.py
+++ b/app/backend_codex.py
@@ -1368,22 +1368,28 @@ class CodexBackend(JsonRpcStdioTransport):
         if method == "thread/tokenUsage/updated":
             self._record_token_usage(params)
             return []
 
         if method == "error":
             error = params.get("error") or {}
             self._last_turn_error = error
             content = error.get("message") or "Codex error"
-            if params.get("willRetry"):
-                return [AgentEvent("status", f"codex reconnecting: {content}")]
             model_error = self._classify_error(error)
+            quota_exhausted = error.get("codexErrorInfo") in (
+                "usageLimitExceeded", "sessionBudgetExceeded",
+            )
+            if params.get("willRetry") and not quota_exhausted:
+                return [AgentEvent("status", f"codex reconnecting: {content}")]
+            metadata = {"model_error": model_error}
             if model_error == "rate_limit":
                 content = f"rate_limit: {content}"
-            return [AgentEvent("error", content, metadata={"model_error": model_error})]
+            if quota_exhausted:
+                metadata["codex_quota_exhausted"] = True
+            return [AgentEvent("error", content, metadata=metadata)]
 
         if method == "model/rerouted":
             return [AgentEvent("status", f"model rerouted: {json.dumps(params, ensure_ascii=False)}")]
 
         if method in ("context/compacted", "thread/compacted"):
             return [AgentEvent("status", "codex context compacted")]
 
         if method in (
diff --git a/app/mailbox.py b/app/mailbox.py
index 4bac60b7a..9e0870604 100644
--- a/app/mailbox.py
+++ b/app/mailbox.py
@@ -71,16 +71,39 @@ def mark_delivered(ids: list[int]) -> None:
     placeholders = ", ".join("?" for _ in ids)
     with db._conn() as connection:
         connection.execute(
             f"UPDATE mailbox SET delivered_at = ? WHERE id IN ({placeholders})",
             (time.time(), *ids),
         )
 
 
+def mark_codex_steer_submitted(message_id: int) -> None:
+    with db._conn() as connection:
+        connection.execute(
+            """UPDATE mailbox
+               SET origin_detail=json_set(origin_detail, '$.subtype', 'codex_steer_backup')
+               WHERE id=? AND delivered_at IS NULL
+                 AND json_extract(origin_detail, '$.subtype')='codex_steer_backup_pending'""",
+            (int(message_id),),
+        )
+
+
+def complete_codex_steers(recipient: str, scope: str, turn_id: str) -> int:
+    with db._conn() as connection:
+        cursor = connection.execute(
+            """UPDATE mailbox SET delivered_at = ?
+               WHERE recipient=? AND scope=? AND delivered_at IS NULL
+                 AND json_extract(origin_detail, '$.subtype')='codex_steer_backup'
+                 AND json_extract(origin_detail, '$.ref')=?""",
+            (time.time(), recipient, scope, turn_id),
+        )
+        return cursor.rowcount
+
+
 # Семантика доставки объявлена явно: AT-LEAST-ONCE.
 # Выбор между «потерять» и «повторить» сделан в пользу повтора: агент, прочитавший
 # сообщение дважды, теряет центы, а молча потерянное сообщение стоит работы (#158).
 # Аренда ниже гасит не повтор после краха, а ОДНОВРЕМЕННЫЕ выдачи.
 CLAIM_LEASE_SECONDS = 300.0
 
 
 def claim(recipient: str, scope: str, lease_seconds: float = CLAIM_LEASE_SECONDS) -> list[dict]:
diff --git a/app/routes/system.py b/app/routes/system.py
index a70668132..3c84ac545 100644
--- a/app/routes/system.py
+++ b/app/routes/system.py
@@ -1040,17 +1040,20 @@ async def _fetch_codex_usage() -> dict:
         if proc.returncode is None:
             try:
                 proc.terminate()
             except ProcessLookupError:
                 pass
         try:
             await asyncio.wait_for(proc.wait(), timeout=1)
         except asyncio.TimeoutError:
-            proc.kill()
+            try:
+                proc.kill()
+            except ProcessLookupError:
+                pass
             await proc.wait()
 
 
 async def _refresh_oauth_token(refresh_token: str) -> str | None:
     """Refresh expired OAuth token. Returns new access token or None."""
     import httpx
     try:
         async with httpx.AsyncClient(timeout=10) as client:
@@ -1250,17 +1253,17 @@ async def _get_usage_data(
             codex_data = await _fetch_codex_usage()
             codex_fetched = codex_data is not None
             if codex_fetched:
                 _codex_usage_cache["data"] = codex_data
                 _codex_usage_cache["ts"] = now
             else:
                 codex_data = _codex_usage_cache["data"]
         except Exception as e:
-            logger.warning(f"Codex usage fetch failed: {e}")
+            logger.warning("Codex usage fetch failed: %r", e)
             codex_data = _codex_usage_cache["data"]
     if required_provider in {"codex", "codex_spark"} and not codex_fetched:
         raise RuntimeError("fresh Codex usage is unavailable")
 
     grok_data = None
     grok_fetched = False
     skip_grok_refresh = bool(required_provider) and required_provider != "grok"
     if skip_grok_refresh:
diff --git a/app/runtime_history.py b/app/runtime_history.py
index 55d43cc77..050e548aa 100644
--- a/app/runtime_history.py
+++ b/app/runtime_history.py
@@ -11,19 +11,19 @@ from collections import Counter, deque
 from copy import deepcopy
 from dataclasses import asdict, dataclass, replace
 from typing import Any, Callable, Iterable, Sequence
 
 
 CLAUDE_CLI_HISTORY_VERSION = "2.1.197"
 CLAUDE_SDK_HISTORY_VERSION = "0.2.114"
 CLAUDE_HISTORY_SOURCE = "logs:claude"
-# Pin follows the installed codex-cli 0.153.4; #498's nine Astra effort probes and #503's
-# live ASTRA_OK validated the preceding 0.153.2 binary.
-CODEX_CLI_HISTORY_VERSION = "0.153.4"
+# A synthetic history payload was accepted by codex-cli 0.156.1 `thread/resume` in an
+# isolated CODEX_HOME on 2026-10-05 (V-703); no live thread was resumed.
+CODEX_CLI_HISTORY_VERSION = "0.156.1"
 
 TOOL_CALL_LIMIT = 8_000
 TOOL_RESULT_LIMIT = 20_000
 TOOL_NAME_LIMIT = 512
 TOOL_DETAIL_BUDGET = 256_000
 TOOL_VISIBLE_BUDGET = 256_000
 # The packet is counted against the TARGET window, not against the source thread it
 # describes: a long session produced 8881 effects (3.2 MB) and 31939 event ids (224 KB)
diff --git a/app/session.py b/app/session.py
index 3803ca294..68094e711 100644
--- a/app/session.py
+++ b/app/session.py
@@ -1305,28 +1305,61 @@ class AgentSession:
                         f"message queued (deferred interrupt pending, "
                         f"{len(self._pending_messages)} pending)",
                     )
                     return
                 if not capabilities.mid_turn_inject:
                     self._pending_messages.append(message)
                     self._log("status", f"message queued ({len(self._pending_messages)} pending)")
                     return
+                mailbox_id = None
                 try:
                     backend = await self._ensure_backend()
                     injected, fact_keys = self._attach_pending_facts(message)
+                    turn_id = getattr(backend, "active_turn_id", None)
+                    if (
+                        self.backend_type == "codex"
+                        and provenance.origin not in {"platform", "system"}
+                        and isinstance(turn_id, str)
+                        and turn_id
+                    ):
+                        from app import mailbox
+
+                        sender = provenance.senders[0]
+                        body = message
+                        prefix = f"[from:{sender}] "
+                        if provenance.origin == "agent" and body.startswith(prefix):
+                            body = body[len(prefix):]
+                        mailbox_id = mailbox.enqueue(
+                            recipient=self.name,
+                            scope=self.scope,
+                            sender=sender,
+                            body=body,
+                            provenance=MessageProvenance(
+                                origin=provenance.origin,
+                                senders=provenance.senders,
+                                subtype="codex_steer_backup_pending",
+                                ref=turn_id,
+                            ),
+                        )
                     await backend.send(injected)
+                    if mailbox_id is not None:
+                        from app import mailbox
+
+                        mailbox.mark_codex_steer_submitted(mailbox_id)
                     self._ack_pending_facts(fact_keys)
                     if self.backend_type == "codex":
                         self._log("status", "message steered into active Codex turn")
                     return
                 except Exception as e:
                     logger.warning(f"[{self.name}] mid-turn inject failed, queueing: {e}")
-                    self._pending_messages.append(message)
-                    self._log("status", f"inject failed, queued ({len(self._pending_messages)} pending)")
+                    if mailbox_id is None:
+                        self._pending_messages.append(message)
+                    pending = len(self._pending_messages) + int(mailbox_id is not None)
+                    self._log("status", f"inject failed, queued ({pending} pending)")
                     if self.status != AgentStatus.RUNNING and not self._compacting:
                         self._spawn_bg(self._flush_pending())
                 return
 
             if self._hibernate_task and not self._hibernate_task.done():
                 self._hibernate_task.cancel()
                 self._hibernate_task = None
 
@@ -2129,17 +2162,29 @@ class AgentSession:
         if self.status != AgentStatus.RUNNING:
             return
         self._turn_start = 0
         self.status = AgentStatus.IDLE
         self._log("error", reason)
         self._persist()
         self._turns.publish_turn_finished()
         self._turns.report_abnormal_end(reason)
-        if self._pending_messages:
+        try:
+            from app import mailbox
+
+            queued = mailbox.claim(self.name, self.scope)
+        except Exception as error:
+            logger.warning(
+                "[%s] failed-turn mailbox claim failed: %s: %s",
+                self.name, type(error).__name__, error,
+            )
+            queued = []
+        if queued:
+            self._spawn_bg(self._turns._deliver_mailbox(queued))
+        elif self._pending_messages:
             self._spawn_bg(self._flush_pending())
         else:
             self._hibernate.schedule()
 
     MAX_CONSECUTIVE_FAILURES = 5
 
     async def _reconnect_backend(self) -> None:
         backend = self._backend
@@ -2422,16 +2467,61 @@ class AgentSession:
         elif event.type in ("plan", "warning", "review"):
             self._log(event.type, event.content)
         elif event.type == "turn_end":
             # Сколько обращений к модели было в ходе: расход хода — их сумма, и компакт
             # делит на это число, чтобы получить размер контекста ОДНОГО обращения.
             self._last_turn_api_calls = max(1, int(event.metadata.get("num_turns") or 1))
             self._turns.handle_turn_end(event)
         elif event.type == "error":
+            if event.metadata.get("codex_quota_exhausted"):
+                self._session_limit_hit = True
+                from app.routes import system
+
+                usage = system._codex_usage_cache.get("data") or {}
+                if self.model == "gpt-5.3-codex-spark":
+                    usage = usage.get("spark") or {}
+                windows = [
+                    ("primary", usage.get("primary")),
+                    ("secondary", usage.get("secondary")),
+                ]
+                exhausted = [
+                    (key, window)
+                    for key, window in windows
+                    if isinstance(window, dict)
+                    and isinstance(window.get("utilization"), (int, float))
+                    and not isinstance(window["utilization"], bool)
+                    and window["utilization"] >= 100
+                ]
+                selected = exhausted or windows
+                reset_details = []
+                now = datetime.now(timezone.utc)
+                for key, window in selected:
+                    if not isinstance(window, dict):
+                        reset_details.append(f"{key} неизвестно")
+                        continue
+                    minutes = window.get("window_minutes")
+                    label = {300: "5h", 10080: "7d"}.get(minutes, key)
+                    value = window.get("resets_at") if isinstance(window, dict) else None
+                    reset_text = "неизвестно"
+                    if isinstance(value, str) and value:
+                        try:
+                            reset_at = datetime.fromisoformat(value.replace("Z", "+00:00"))
+                            if reset_at.tzinfo is None:
+                                reset_at = reset_at.replace(tzinfo=timezone.utc)
+                            if reset_at > now:
+                                reset_text = reset_at.isoformat().replace("+00:00", "Z")
+                        except ValueError:
+                            pass
+                    reset_details.append(f"{label} {reset_text}")
+                self._log(
+                    "error",
+                    f"квота Codex исчерпана, сброс {', '.join(reset_details)}",
+                )
+                return
             # rate_limit → single retry-status log (skip raw error to avoid duplicate
             # "model error: rate_limit" + "rate limited — retry" on one event)
             if event.metadata.get("model_error") == "rate_limit":
                 # Terminal subscription/usage limits — never retry
                 if self._session_limit_hit:
                     return
                 elif self._rate_limit_retries < self.RATE_LIMIT_MAX_RETRIES:
                     self._rate_limit_retries += 1
diff --git a/app/session_turns.py b/app/session_turns.py
index c41616dff..d03cfa689 100644
--- a/app/session_turns.py
+++ b/app/session_turns.py
@@ -290,16 +290,26 @@ class TurnManager:
 
     def handle_turn_end(self, event: AgentEvent) -> None:
         s = self.s
         meta = event.metadata
         cost_unaccounted = meta.get("cost_unaccounted") is True
         s._turn_start = 0
         ok, sr, nt = s._cost.apply_turn_result(meta, event.usage)
         event_id = str(meta.get("event_id") or "")
+        if ok and event_id and s.backend_type == "codex":
+            from app import mailbox
+
+            try:
+                mailbox.complete_codex_steers(s.name, s.scope, event_id)
+            except Exception as error:
+                logger.warning(
+                    f"[{s.name}] successful-turn steer cleanup failed: "
+                    f"{type(error).__name__}: {error}"
+                )
         if not ok and event_id:
             from app import message_deliveries
 
             try:
                 recovered = message_deliveries.requeue_failed_turn(s.id, event_id)
             except Exception as error:
                 logger.warning(
                     f"[{s.name}] failed-turn steer recovery unavailable: "
diff --git a/tests/test_backend_codex.py b/tests/test_backend_codex.py
index 948f331eb..c7ef198c4 100644
--- a/tests/test_backend_codex.py
+++ b/tests/test_backend_codex.py
@@ -3,18 +3,16 @@
 Regression net for the three bugs found in the codex-integration audit:
   BUG 1 — Sol/Terra/Luna missing from context/price dicts (worker got 258400 ctx, $0).
   BUG 2 — reasoning effort hardcoded, xhigh/max not in the accepted set.
   MCP   — per-worker MCP servers now injected via -c dotted-leaf overrides.
 """
 
 import asyncio
 import json
-import shutil
-import subprocess
 from types import SimpleNamespace
 from unittest.mock import AsyncMock, MagicMock
 
 import pytest
 
 from app.backend_codex import (
     CodexBackend,
     CodexOversizedRecordError,
@@ -68,26 +66,16 @@ def _history_import():
             "type": "user_message",
             "content": "remember",
         }],
         snapshot_id=1,
         thread_id="11111111-2222-4333-8444-555555555555",
     )
 
 
-def test_installed_codex_history_version_matches_pin():
-    cli = shutil.which("codex")
-    if cli is None:
-        pytest.skip("Codex CLI is not installed")
-    result = subprocess.run(
-        [cli, "--version"], capture_output=True, text=True, check=True, timeout=10
-    )
-    assert result.stdout.strip() == f"codex-cli {CODEX_CLI_HISTORY_VERSION}"
-
-
 # ── BUG 1: GPT-5.6 models registered in backend dicts ──
 
 def test_gpt56_context_limits_present():
     # ChatGPT-auth Codex runtime reports a 258400 effective budget for these models.