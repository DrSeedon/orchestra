# Candidate cand-29

## ORIGIN commit b929710c17 (2026-07-16): Sol runtime fixes: context accounting, cost delta, limit retry, codex_review atomicity, orphan pipe
(diff of code only, excluding .orchestra/ and *.md; capped 1200 lines)

diff --git a/app/backend_codex.py b/app/backend_codex.py
index 232cb2bfc..f5ae78219 100644
--- a/app/backend_codex.py
+++ b/app/backend_codex.py
@@ -1,50 +1,137 @@
 """CodexBackend — wraps Codex CLI subprocess for agent sessions."""
 
 import asyncio
 import json
 import logging
 import os
 import shutil
+from pathlib import Path
 from typing import AsyncIterator, Optional
 
 from app.events import AgentEvent
 
 logger = logging.getLogger(__name__)
 
 CODEX_BIN = shutil.which("codex") or os.environ.get("CODEX_BIN", "codex")
 
-# Context windows: value = usable prefill budget = model window × ~0.95 safety margin.
-# GPT-5.6 (Sol/Terra/Luna): 1,050,000 window → 997,500 usable. 5.4/5.5: 272,000 → 258,400.
+# Effective context budgets reported by the ChatGPT-auth Codex runtime. The public API
+# advertises a larger GPT-5.6 window, but that is a different surface; local rollout
+# token_count events are the runtime source of truth and may override these fallbacks.
 CODEX_CONTEXT_LIMITS = {
-    "gpt-5.6-sol":   997500,
-    "gpt-5.6-terra": 997500,
-    "gpt-5.6-luna":  997500,
+    "gpt-5.6-sol":   258400,
+    "gpt-5.6-terra": 258400,
+    "gpt-5.6-luna":  258400,
     "gpt-5.5": 258400,
     "gpt-5.4": 258400,
     "gpt-5.4-mini": 258400,
 }
 
 CODEX_TOKEN_PRICES = {
-    "gpt-5.6-sol":   {"input": 5.0, "output": 30.0},
-    "gpt-5.6-terra": {"input": 2.5, "output": 15.0},
-    "gpt-5.6-luna":  {"input": 1.0, "output": 6.0},
-    "gpt-5.5":      {"input": 5.0, "output": 30.0},
-    "gpt-5.4":      {"input": 2.5, "output": 15.0},
-    "gpt-5.4-mini": {"input": 0.3, "output": 1.25},
+    "gpt-5.6-sol":   {"input": 5.0, "cached": 0.5, "output": 30.0},
+    "gpt-5.6-terra": {"input": 2.5, "cached": 0.25, "output": 15.0},
+    "gpt-5.6-luna":  {"input": 1.0, "cached": 0.1, "output": 6.0},
+    "gpt-5.5":      {"input": 5.0, "cached": 0.5, "output": 30.0},
+    "gpt-5.4":      {"input": 2.5, "cached": 0.25, "output": 15.0},
+    "gpt-5.4-mini": {"input": 0.3, "cached": 0.03, "output": 1.25},
 }
 
 
 # GPT-5.6 reasoning ladder (light→low→medium→high→xhigh→max→ultra). "minimal" kept for
 # 5.4/5.5 back-compat. "ultra" (parallel sub-agents) intentionally excluded — a special
 # mode, not a plain effort level, and risky to trigger from a generic worker effort field.
 CODEX_REASONING_EFFORTS = {"minimal", "low", "medium", "high", "xhigh", "max"}
 
 
+def _codex_cost(model: str, input_tokens: int, cached_input_tokens: int,
+                output_tokens: int) -> float:
+    """API-equivalent cost with cached input charged at its actual lower rate."""
+    prices = CODEX_TOKEN_PRICES.get(model)
+    if not prices:
+        return 0.0
+    cached = min(max(0, cached_input_tokens), max(0, input_tokens))
+    fresh = max(0, input_tokens - cached)
+    return (fresh * prices["input"] + cached * prices["cached"]
+            + max(0, output_tokens) * prices["output"]) / 1_000_000
+
+
+def _read_rollout_context(path: Path) -> dict[str, int] | None:
+    """Return the last model-call context from a Codex rollout, or None fail-soft.
+
+    `turn.completed.usage` is cumulative work for the thread and cannot represent the
+    currently occupied window. Internal rollout token_count events expose both the last
+    call and the runtime-provided effective model_context_window.
+    """
+    latest = None
+    try:
+        with path.open(encoding="utf-8", errors="replace") as fh:
+            for line in fh:
+                try:
+                    row = json.loads(line)
+                except (json.JSONDecodeError, TypeError):
+                    continue
+                payload = row.get("payload") or {}
+                if row.get("type") != "event_msg" or payload.get("type") != "token_count":
+                    continue
+                info = payload.get("info") or {}
+                usage = info.get("last_token_usage") or {}
+                window = info.get("model_context_window")
+                input_tokens = usage.get("input_tokens")
+                if not isinstance(window, int) or window <= 0:
+                    continue
+                if not isinstance(input_tokens, int) or input_tokens < 0:
+                    continue
+                cached = usage.get("cached_input_tokens", 0)
+                latest = {
+                    "input_tokens": input_tokens,
+                    "cached_input_tokens": cached if isinstance(cached, int) else 0,
+                    "model_context_window": window,
+                }
+    except (FileNotFoundError, OSError):
+        return None
+    return latest
+
+
+def _read_rollout_totals(path: Path) -> dict[str, int] | None:
+    latest = None
+    try:
+        with path.open(encoding="utf-8", errors="replace") as fh:
+            for line in fh:
+                try:
+                    row = json.loads(line)
+                except (json.JSONDecodeError, TypeError):
+                    continue
+                payload = row.get("payload") or {}
+                if row.get("type") != "event_msg" or payload.get("type") != "token_count":
+                    continue
+                total = ((payload.get("info") or {}).get("total_token_usage") or {})
+                input_tokens = total.get("input_tokens")
+                if not isinstance(input_tokens, int) or input_tokens < 0:
+                    continue
+                latest = {
+                    "input_tokens": input_tokens,
+                    "cached_input_tokens": max(0, int(total.get("cached_input_tokens") or 0)),
+                    "output_tokens": max(0, int(total.get("output_tokens") or 0)),
+                }
+    except (FileNotFoundError, OSError, ValueError, TypeError):
+        return None
+    return latest
+
+
+def _usage_delta(current: dict[str, int], baseline: dict[str, int] | None) -> dict[str, int]:
+    baseline = baseline or {}
+    result = {}
+    for key in ("input_tokens", "cached_input_tokens", "output_tokens"):
+        value = max(0, int(current.get(key) or 0))
+        before = max(0, int(baseline.get(key) or 0))
+        result[key] = value - before if value >= before else value
+    return result
+
+
 class CodexBackend:
     def __init__(self, model: str, cwd: str, system_prompt: str = "",
                  resume_thread_id: str | None = None,
                  mcp_env: dict[str, str] | None = None,
                  mcp_servers: dict | None = None,
                  reasoning_effort: str = "high"):
         self.model = model
         self.cwd = cwd
@@ -52,29 +139,34 @@ class CodexBackend:
         self._thread_id: str | None = resume_thread_id
         self._mcp_env: dict[str, str] = mcp_env or {}
         self._mcp_servers: dict = mcp_servers or {}
         self.reasoning_effort = reasoning_effort if reasoning_effort in CODEX_REASONING_EFFORTS else "high"
         self._proc: Optional[asyncio.subprocess.Process] = None
         self._stderr_task: Optional[asyncio.Task] = None
         self._last_stderr: str = ""
         self._got_turn_completed: bool = False
+        self._rollout_path: Path | None = None
+        self._usage_baseline: dict[str, int] | None = None
 
     @property
     def session_id(self) -> Optional[str]:
         return self._thread_id
 
     async def connect(self) -> None:
         # Codex launches a new subprocess per turn (stateless CLI), so connect is a no-op —
         # the actual process starts in send() when the first message arrives
         pass
 
     async def send(self, message: str) -> None:
         self._got_turn_completed = False
         self._last_stderr = ""
+        # Codex reports cumulative thread usage. Snapshot the prior rollout before resume
+        # so a process/service restart cannot charge the full thread again as one new turn.
+        self._usage_baseline = self._runtime_totals() if self._thread_id else None
 
         # --dangerously-bypass-approvals-and-sandbox: the flag's own help says it's
         # "intended solely for running in environments that are externally sandboxed" —
         # which is exactly our case: every worker runs in an isolated git worktree as a
         # dedicated process, and an autonomous worker has no human to answer approval
         # prompts. -s workspace-write would block on approvals it can't resolve. The
         # worktree is the external sandbox this flag is designed for.
         # RISK (Sol): GPT-5.6 Sol has elevated reward-hacking (METR); no sandbox means it
@@ -103,36 +195,45 @@ class CodexBackend:
             cmd.append(message)
 
         self._proc = await asyncio.create_subprocess_exec(
             *cmd,
             stdout=asyncio.subprocess.PIPE,
             stderr=asyncio.subprocess.PIPE,
             env=self._build_env(),
             cwd=self.cwd,
+            limit=16 * 1024 * 1024,
         )
         self._stderr_task = asyncio.create_task(self._drain_stderr())
 
     async def events(self) -> AsyncIterator[AgentEvent]:
         if not self._proc or not self._proc.stdout:
             return
 
-        async for raw_line in self._proc.stdout:
+        while True:
+            try:
+                raw_line = await self._proc.stdout.readline()
+            except ValueError:
+                logger.warning(f"[{self.model}] JSONL line >16MB, skipped")
+                continue
+            if not raw_line:
+                break
             line = raw_line.decode("utf-8").rstrip("\n")
             if not line:
                 continue
             try:
                 data = json.loads(line)
             except json.JSONDecodeError:
                 continue
 
             etype = data.get("type", "")
 
             if etype == "thread.started":
                 self._thread_id = data["thread_id"]
+                self._rollout_path = None
                 yield AgentEvent("status", f"codex thread={self._thread_id}")
 
             elif etype == "item.completed":
                 item = data.get("item", {})
                 itype = item.get("type", "")
 
                 if itype == "agent_message":
                     yield AgentEvent("text", item.get("text", ""))
@@ -179,43 +280,57 @@ class CodexBackend:
                                      metadata={"tool_name": "Bash", "short_name": "Bash"})
 
             elif etype == "turn.completed":
                 self._got_turn_completed = True
                 usage = data.get("usage", {})
                 input_t = usage.get("input_tokens", 0)
                 cached_t = usage.get("cached_input_tokens", 0)
                 output_t = usage.get("output_tokens", 0)
-
-                ctx_window = CODEX_CONTEXT_LIMITS.get(self.model, 258400)
-                ctx_pct = min(100, int(input_t * 100 / ctx_window)) if ctx_window else 0
-
-                # input_tokens are CUMULATIVE per thread (verified: turn1=16728 → turn2=33472
-                # on resume — the full conversation is re-fed each turn). So this cost is
-                # monotonically increasing per thread, and CostTracker's delta logic
-                # (max(0, new_cost - last_cost)) already yields the correct per-turn cost —
-                # same contract as the Claude SDK. Do NOT re-accumulate here (double-counts).
-                prices = CODEX_TOKEN_PRICES.get(self.model, {"input": 0, "output": 0})
-                cost = (input_t * prices["input"] + output_t * prices["output"]) / 1_000_000
+                turn_usage = _usage_delta({
+                    "input_tokens": input_t,
+                    "cached_input_tokens": cached_t,
+                    "output_tokens": output_t,
+                }, self._usage_baseline)
+                turn_input = turn_usage["input_tokens"]
+                turn_cached = turn_usage["cached_input_tokens"]
+                turn_output = turn_usage["output_tokens"]
+
+                runtime_ctx = self._runtime_context()
+                if runtime_ctx:
+                    ctx_tokens = runtime_ctx["input_tokens"]
+                    ctx_window = runtime_ctx["model_context_window"]
+                    ctx_pct = min(100, int(ctx_tokens * 100 / ctx_window)) if ctx_window else 0
+                    context_known = True
+                else:
+                    # Unknown is safer than presenting cumulative usage as occupied context.
+                    ctx_tokens = 0
+                    ctx_window = CODEX_CONTEXT_LIMITS.get(self.model, 258400)
+                    ctx_pct = 0
+                    context_known = False
+
+                cost = _codex_cost(self.model, turn_input, turn_cached, turn_output)
 
                 yield AgentEvent("turn_end", f"stop_reason=end_turn", metadata={
                     "session_id": self._thread_id,
                     "ok": True,
                     "stop_reason": "end_turn",
                     "cost_usd": cost,
                     "cost_usd_cached": cost,
+                    "cost_is_delta": True,
                     "context_pct": ctx_pct,
-                    "context_tokens": input_t,
+                    "context_tokens": ctx_tokens,
+                    "context_known": context_known,
                     "max_tokens": ctx_window,
-                    "cache_hit": int(cached_t * 100 / input_t) if input_t else 0,
-                    "cache_read": cached_t,
+                    "cache_hit": int(turn_cached * 100 / turn_input) if turn_input else 0,
+                    "cache_read": turn_cached,
                     "cache_create": 0,
-                    "input_tokens": input_t,
-                    "cached_input_tokens": cached_t,
-                    "output_tokens": output_t,
+                    "input_tokens": turn_input,
+                    "cached_input_tokens": turn_cached,
+                    "output_tokens": turn_output,
                 })
 
             elif etype == "turn.failed":
                 error = data.get("error", {})
                 yield AgentEvent("error", error.get("message", "turn failed"))
 
             elif etype == "error":
                 yield AgentEvent("error", data.get("message", "codex error"))
@@ -265,16 +380,38 @@ class CodexBackend:
         while True:
             chunk = await self._proc.stderr.read(4096)
             if not chunk:
                 break
             chunks.append(chunk)
         data = b"".join(chunks)
         self._last_stderr = data[-500:].decode("utf-8", errors="replace")
 
+    def _runtime_context(self) -> dict[str, int] | None:
+        if not self._thread_id:
+            return None
+        if self._rollout_path is None or not self._rollout_path.exists():
+            root = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))).expanduser()
+            sessions = root / "sessions"
+            try:
+                matches = list(sessions.glob(f"**/*{self._thread_id}.jsonl"))
+            except OSError:
+                matches = []
+            if not matches:
+                return None
+            self._rollout_path = max(matches, key=lambda p: p.stat().st_mtime)
+        return _read_rollout_context(self._rollout_path)
+
+    def _runtime_totals(self) -> dict[str, int] | None:
+        # Locate the rollout through the same path/cache as context extraction.
+        self._runtime_context()
+        if self._rollout_path is None:
+            return None
+        return _read_rollout_totals(self._rollout_path)
+
     @staticmethod
     def _toml_str(s: str) -> str:
         # TOML basic string: escape backslash and double-quote (control chars unlikely in
         # command/args/env values here). Keeps the -c inline table parseable.
         return '"' + s.replace('\\', '\\\\').replace('"', '\\"') + '"'
 
     def _mcp_config_args(self) -> list[str]:
         """Dotted `-c mcp_servers.NAME.FIELD=value` overrides, one field per entry.
@@ -299,13 +436,12 @@ class CodexBackend:
             if env:
                 env_inline = ", ".join(f"{k}={self._toml_str(str(v))}" for k, v in env.items())
                 args.append(f"mcp_servers.{name}.env={{" + env_inline + "}")
         return args
 
     def _build_env(self) -> dict:
         env = dict(os.environ)
         env.update(self._mcp_env)
-        # Strip proxy for Codex: it talks directly to OpenAI, not Anthropic —
-        # routing through Hiddify would break OpenAI connectivity
-        env.pop("HTTPS_PROXY", None)
-        env.pop("HTTP_PROXY", None)
+        # Codex, Claude, Cursor, and Orchestra intentionally share the proxy selected in
+        # Orchestra's .env. The launcher wrapper also reloads that file, but preserving the
+        # inherited values keeps direct CODEX_BIN deployments consistent and testable.
         return env
diff --git a/app/bg_jobs.py b/app/bg_jobs.py
index a9bffd61b..14a25f961 100644
--- a/app/bg_jobs.py
+++ b/app/bg_jobs.py
@@ -75,16 +75,22 @@ def _validate_config(job_type: str, config: dict) -> str | None:
             return "pattern is required"
         try:
             re.compile(pattern)
         except re.error as e:
             return f"invalid regex pattern: {e}"
     elif job_type == "run":
         if not config.get("command"):
             return "command is required"
+        success_pattern = config.get("success_pattern", "")
+        if success_pattern:
+            try:
+                re.compile(success_pattern)
+            except re.error as e:
+                return f"invalid success_pattern: {e}"
     elif job_type == "cron":
         expr = config.get("cron_expr", "")
         if not expr:
             return "cron_expr is required"
         if not croniter.is_valid(expr):
             return f"invalid cron expression: {expr!r}"
     else:
         return f"unknown job type: {job_type}"
@@ -178,17 +184,19 @@ class BgJobManager:
             coro = self._run_command_watch(job_id, config["command"], config["pattern"],
                                           interval, message, target_name, target_scope, timeout)
         elif job_type == "ssh":
             coro = self._run_ssh_watch(job_id, config["host"], config["command"],
                                        config["pattern"], message, target_name, target_scope, timeout)
         elif job_type == "run":
             host = config.get("host")
             coro = self._run_exec(job_id, config["command"], message, target_name,
-                                  target_scope, timeout, host=host)
+                                  target_scope, timeout, host=host,
+                                  success_file=config.get("success_file"),
+                                  success_pattern=config.get("success_pattern", ""))
         elif job_type == "cron":
             cron_timeout = None if config.get("no_expiry") else timeout
             coro = self._run_cron(job_id, config["cron_expr"], message,
                                   target_name, target_scope, cron_timeout)
         else:
             return
         task = asyncio.create_task(coro)
         self._tasks[job_id] = task
@@ -308,16 +316,33 @@ class BgJobManager:
             body = f"[Background job TIMED OUT] {err}"
             if output:
                 body += f"\n\nPartial output (last 3000 chars):\n{output[-3000:]}"
             await session.send(body)
             logger.warning(f"bg_job {job_id}: TIMED OUT after {dur} → notified {target_name}")
         except Exception as e:
             logger.error(f"bg_job {job_id}: timeout-notify failed: {e}")
 
+    async def _fail_notify(self, job_id, message, target_name, target_scope,
+                           error, output=""):
+        """Persist a failed run and wake the waiting agent with an explicit failure."""
+        bg_fail_job(job_id, error)
+        try:
+            session = await self._session_manager.ensure_loaded(target_name, target_scope)
+            if not session:
+                logger.warning(f"bg_job {job_id}: failed, target {target_name} not found")
+                return
+            body = f"[Background job FAILED] {message}\n{error}"
+            if output:
+                body += f"\n\nOutput (last 3000 chars):\n{output[-3000:]}"
+            await session.send(body)
+            logger.warning(f"bg_job {job_id}: FAILED → notified {target_name}: {error}")
+        except Exception as e:
+            logger.error(f"bg_job {job_id}: failure-notify failed: {e}")
+
     def _fail_if_active(self, job_id: str, error: str) -> None:
         bg_fail_job_if_active(job_id, error)
 
     # ── Runners ──
 
     async def _run_timer(self, job_id, delay, message, target_name, target_scope):
         try:
             await asyncio.sleep(delay)
@@ -437,18 +462,20 @@ class BgJobManager:
         except Exception as e:
             self._fail_if_active(job_id, str(e)[:500])
         finally:
             self._procs.pop(job_id, None)
             if proc:
                 await _kill_proc(proc)
 
     async def _run_exec(self, job_id, command, message, target_name,
-                        target_scope, timeout, host=None):
+                        target_scope, timeout, host=None, success_file=None,
+                        success_pattern=""):
         proc = None
+        reader_task = None
         output_buf = []
         try:
             # 16MB readline limit: Codex JSONL contains base64 images / long JSON lines
             # that exceed asyncio's default 64KB StreamReader limit → ValueError
             _STREAM_LIMIT = 16 * 1024 * 1024
             if host:
                 proc = await asyncio.create_subprocess_exec(
                     "ssh", *_SSH_OPTS, host, command,
@@ -460,41 +487,107 @@ class BgJobManager:
                     command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
                     preexec_fn=os.setsid, limit=_STREAM_LIMIT,
                 )
             self._procs[job_id] = proc
             where = host or "local"
             logger.info(f"bg_job {job_id}: run started pid={proc.pid} on={where} "
                         f"timeout={timeout}s cmd_len={len(command)}")
             last_progress = time.time()
-            async with asyncio.timeout(timeout):
+
+            async def read_output():
+                nonlocal last_progress, output_buf
                 async for line in proc.stdout:
                     output_buf.append(line.decode(errors="replace"))
                     if len(output_buf) > 500:
                         output_buf = output_buf[-300:]
                     now = time.time()
                     if now - last_progress > OUTPUT_PROGRESS_INTERVAL:
                         bg_update_output(job_id, "".join(output_buf))
                         last_progress = now
-                await proc.wait()
+
+            async with asyncio.timeout(timeout):
+                reader_task = asyncio.create_task(read_output())
+                # asyncio Process.wait() itself waits for pipe EOF. A grandchild that
+                # inherited stdout can therefore keep it blocked after the command
+                # leader has exited. Observe the leader's returncode independently.
+                while proc.returncode is None:
+                    await asyncio.sleep(0.05)
+                try:
+                    await asyncio.wait_for(asyncio.shield(reader_task), timeout=2)
+                except asyncio.TimeoutError:
+                    # Codex may leave an MCP child holding the inherited stdout FD.
+                    # The job itself has exited, so terminate only its dedicated
+                    # process group and stop waiting for an EOF that will never come.
+                    logger.warning(
+                        f"bg_job {job_id}: stdout still open after pid={proc.pid} exited; "
+                        "terminating leftover process group"
+                    )
+                    try:
+                        os.killpg(proc.pid, signal.SIGTERM)
+                    except (ProcessLookupError, PermissionError):
+                        pass
+                    try:
+                        await asyncio.wait_for(asyncio.shield(reader_task), timeout=2)
+                    except asyncio.TimeoutError:
+                        try:
+                            os.killpg(proc.pid, signal.SIGKILL)
+                        except (ProcessLookupError, PermissionError):
+                            pass
+                        reader_task.cancel()
+                        await asyncio.gather(reader_task, return_exceptions=True)
+                        transport = getattr(proc, "_transport", None)
+                        if transport:
+                            transport.close()
             full_output = "".join(output_buf)
             exit_code = proc.returncode
-            note = "" if exit_code == 0 else " — process failed, see output"
-            trigger_msg = f"{message}\nExit code: {exit_code}{note}"
             logger.info(f"bg_job {job_id}: run done pid={proc.pid} exit={exit_code} "
                         f"lines={len(output_buf)}")
+            if exit_code != 0:
+                await self._fail_notify(
+                    job_id, message, target_name, target_scope,
+                    f"Process exited with exit code {exit_code}", full_output,
+                )
+                return
+
+            validation_error = ""
+            if success_file:
+                try:
+                    if not os.path.isfile(success_file) or os.path.getsize(success_file) == 0:
+                        validation_error = f"Required output artifact is missing or empty: {success_file}"
+                    elif success_pattern:
+                        with open(success_file, encoding="utf-8", errors="replace") as fh:
+                            artifact = fh.read()
+                        if re.search(success_pattern, artifact) is None:
+                            validation_error = (
+                                f"Required output artifact does not match success pattern: "
+                                f"{success_file}"
+                            )
+                except OSError as e:
+                    validation_error = f"Cannot validate output artifact {success_file}: {e}"
+            if validation_error:
+                await self._fail_notify(
+                    job_id, message, target_name, target_scope,
+                    validation_error, full_output,
+                )
+                return
+
+            trigger_msg = f"{message}\nExit code: 0"
             await self._trigger(job_id, trigger_msg, target_name, target_scope, full_output)
         except asyncio.TimeoutError:
             if proc:
                 await _kill_proc(proc)
             await self._expire_notify(job_id, message, target_name, target_scope,
                                       timeout, "".join(output_buf))
         except asyncio.CancelledError:
             pass
         except Exception as e:
             bg_fail_job(job_id, str(e)[:500])
         finally:
+            if reader_task and not reader_task.done():
+                reader_task.cancel()
+                await asyncio.gather(reader_task, return_exceptions=True)
             self._procs.pop(job_id, None)
             if proc:
                 await _kill_proc(proc)
 
 
 bg_manager = BgJobManager()
diff --git a/app/mcp_stdio.py b/app/mcp_stdio.py
index f42354caf..f05e7158c 100644
--- a/app/mcp_stdio.py
+++ b/app/mcp_stdio.py
@@ -4,16 +4,17 @@ Runs as a separate process, communicates with Orchestra via HTTP API.
 Avoids the in-process SDK control_request deadlock (issue #425/#701).
 
 Usage: python -m app.mcp_stdio
 """
 
 import json
 import logging
 import os
+import shlex
 import sys
 
 import httpx
 from mcp.server.fastmcp import FastMCP
 
 # Logs go to stderr so they don't pollute the JSON-RPC stdout stream
 logging.basicConfig(level=logging.INFO, stream=sys.stderr)
 logger = logging.getLogger("orchestra-mcp")
@@ -712,17 +713,18 @@ async def search_memory(query: str, limit: int = 5, cross_project: bool = False)
             tag = f"{h.get('kind')}" + (f" from {author}" if author else "")
             head = f"[log: {tag}]"
         if cross_project:
             head = f"({h.get('project')}) {head}"
         lines.append(f"{head}\n{h.get('content', '').strip()}")
     return "\n\n---\n\n".join(lines)
 
 
-# Wrapper at ~/.local/bin/codex sets HTTPS_PROXY for Ёжик tunnel
+# Wrapper reloads Orchestra .env on every invocation, so Codex review follows the same
+# currently selected proxy as workers, Cursor, and the dashboard service.
 _CODEX_BIN = "/home/maxim/.local/bin/codex"
 _REVIEW_CONTEXT = (
     "PROJECT CONTEXT (calibrate review severity):\n"
     "- Scale: small team, MVP stage\n"
     "- Philosophy: simple, flat, minimal abstractions\n"
     "- blocking = crash/corrupt/security. suggestion = real improvement. nit = skip\n"
 )
 
@@ -742,50 +744,16 @@ def _read_codex_uuid(sessions_path: str, slug: str) -> str:
     try:
         with open(sessions_path) as f:
             data = json.load(f)
         return (data.get("sessions", {}).get(slug, {}) or {}).get("uuid", "") or ""
     except (FileNotFoundError, json.JSONDecodeError, OSError):
         return ""
 
 
-def _codex_persist_snippet(sessions_path: str, slug: str, jsonl: str,
-                           is_resume: bool, output_abs: str, round_tmp: str) -> str:
-    """Shell snippet: append the resumed round to the review file (history-preserving) and
-    upsert the thread UUID into codex_sessions.json. Runs AFTER codex — the bg job is a
-    detached subprocess, so Python can't capture the post-run UUID.
-
-    Exit-code safety (dash, no PIPESTATUS): the caller captures codex's real exit code to
-    /tmp before this runs; this snippet never overrides it. jq/persistence failure must not
-    mask a successful review, nor vice-versa."""
-    # resume writes ONLY the last message to round_tmp → append as a new round, never overwrite
-    # prior rounds. (Fresh/fallback runs write directly to output_abs, so round_tmp stays empty.)
-    append = (
-        f"[ -s '{round_tmp}' ] && {{ "
-        f"printf '\\n\\n## Round (%s)\\n\\n' \"$NOW\" >> '{output_abs}'; "
-        f"cat '{round_tmp}' >> '{output_abs}'; rm -f '{round_tmp}'; }};"
-    ) if is_resume else ""
-    # Always upsert the captured thread_id: same UUID on resume, a NEW one if resume fell back
-    # to a fresh session (stale-UUID recovery). One code path handles new/resume/fallback.
-    upsert = (
-        f"jq --arg s '{slug}' --arg u \"$UUID\" --arg now \"$NOW\" "
-        f"'.sessions[$s]={{uuid:$u, started:(.sessions[$s].started // $now), "
-        f"last_used:$now, turns:((.sessions[$s].turns // 0)+1)}}' "
-        f"'{sessions_path}' > '{sessions_path}.tmp' && mv '{sessions_path}.tmp' '{sessions_path}'"
-    )
-    # jq may be absent (minimal VPS) → guard the UUID upsert; the append (plain cat) is unguarded.
-    return (
-        f"; NOW=$(date -u +%Y-%m-%dT%H:%M:%SZ); {append}"
-        f" command -v jq >/dev/null 2>&1 && {{"
-        f" [ -f '{sessions_path}' ] || echo '{{\"sessions\":{{}}}}' > '{sessions_path}';"
-        f" UUID=$(jq -R -r 'fromjson? | select(.type==\"thread.started\") | .thread_id' '{jsonl}' | tail -1);"
-        f" [ -n \"$UUID\" ] && {upsert}; }}"
-    )
-
-
 @mcp.tool()
 async def codex_review(
     target: str = "",
     output: str = "CODEX_REVIEW.md",
     context: str = "",
     mode: str = "review",
     resume: bool = False,
 ) -> str:
@@ -802,53 +770,56 @@ async def codex_review(
     if isinstance(info, dict) and info.get("error"):
         return f"Error resolving worker cwd: {info['error']}"
     cwd = info.get("worktree_path") or info.get("cwd") or info.get("scope", SCOPE)
     output_abs = f"{cwd}/{output}" if not output.startswith("/") else output
 
     sessions_path = _codex_sessions_path(output_abs)
     slug = _codex_slug(output)
     jsonl_file = f"/tmp/codex_review_{WORKER_NAME}_{slug}.jsonl"
-    prompt_file = f"/tmp/codex_review_{WORKER_NAME}.txt"
+    prompt_file = f"/tmp/codex_review_{WORKER_NAME}_{slug}.txt"
     rc_file = f"/tmp/codex_review_{WORKER_NAME}_{slug}.rc"
     # resume writes its last message here; the persist snippet appends it as a ## Round to
     # output_abs so prior rounds are never overwritten.
     round_tmp = f"{output_abs}.round"
 
     prev_uuid = _read_codex_uuid(sessions_path, slug) if resume else ""
     is_resume = bool(prev_uuid)
     if resume and not prev_uuid:
         logger.info(f"codex_review: resume requested but no stored session for slug={slug} → fresh")
 
-    # resume's -o must NOT point at output_abs (it would truncate history); write to round_tmp.
-    codex_out = round_tmp if is_resume else output_abs
+    # Never let `codex -o` write the durable artifact directly: -o stores the final
+    # agent_message and can overwrite a richer file created during the turn. Capture every
+    # run in a temporary round, validate it, then atomically persist it.
+    codex_out = round_tmp
+    q = shlex.quote
 
     if mode == "review":
         # Fresh review → codex_out: output_abs on a first run, round_tmp on a resume-fallback
         # (so the stale-session recovery is APPENDED as a round, never overwrites prior rounds).
         fresh_review = (
-            f"cd {cwd} && UV_CACHE_DIR=/tmp/uv-cache {_CODEX_BIN} exec review"
+            f"cd {q(cwd)} && UV_CACHE_DIR=/tmp/uv-cache {q(_CODEX_BIN)} exec review"
             f" --uncommitted --skip-git-repo-check --full-auto --json"
-            f" -o {codex_out}"
+            f" -o {q(codex_out)}"
         )
         if is_resume:
             # resume inherits sandbox from original session — do NOT pass -s. Re-review the diff.
             resume_prompt = (
                 "Re-review the current uncommitted diff (run git diff yourself). "
                 "For each prior finding: FIXED / STILL BROKEN / NEW BUG. "
                 "Output a concise re-review (Re-review status, new findings, verdict)."
             )
             if context:
                 resume_prompt += f"\nAuthor notes: {context}"
             # Stale/invalid UUID → resume fails → fall back to a fresh review (recovery).
             codex = (
-                f"cat > {prompt_file} << 'CODEX_PROMPT_EOF'\n{resume_prompt}\nCODEX_PROMPT_EOF\n"
-                f"cd {cwd} && UV_CACHE_DIR=/tmp/uv-cache {_CODEX_BIN} exec resume {prev_uuid}"
+                f"printf '%s' {q(resume_prompt)} > {q(prompt_file)}; "
+                f"cd {q(cwd)} && UV_CACHE_DIR=/tmp/uv-cache {q(_CODEX_BIN)} exec resume {q(prev_uuid)}"
                 f" --skip-git-repo-check --full-auto --json"
-                f" -o {codex_out} - < {prompt_file}"
+                f" -o {q(codex_out)} - < {q(prompt_file)}"
                 f" || {{ echo '[resume failed — stale session, starting fresh review]'; {fresh_review}; }}"
             )
         else:
             codex = fresh_review
     elif mode == "exec":
         if not target and not is_resume:
             return "Error: target file required for mode='exec'"
         prompt_parts_exec = [_REVIEW_CONTEXT]
@@ -857,69 +828,92 @@ async def codex_review(
         # Keep the target in the prompt even on resume — the stale-UUID fresh-exec fallback
         # reuses this same prompt file and would otherwise review nothing concrete.
         if target:
             prompt_parts_exec.append(f"Review the file: {target}")
         if is_resume:
             prompt_parts_exec.append("Re-review after the author's changes above. "
                                      "Output a concise re-review (status of prior findings, new findings, verdict).")
         else:
-            prompt_parts_exec.append(f"Write your findings to {output}.")
+            prompt_parts_exec.append("Return the complete review in your final response. Do not edit files.")
         prompt_parts_exec.append("Format: ## Summary, ## Findings (blocking/suggestion/question), ## Verdict")
         exec_prompt = "\n".join(prompt_parts_exec)
 
         # resume inherits sandbox — do NOT pass -s; fresh exec writes with workspace-write.
         sandbox = "" if is_resume else " -s workspace-write"
         subcmd = f"exec resume {prev_uuid}" if is_resume else "exec"
         codex = (
-            f"cat > {prompt_file} << 'CODEX_PROMPT_EOF'\n{exec_prompt}\nCODEX_PROMPT_EOF\n"
-            f"cd {cwd} && UV_CACHE_DIR=/tmp/uv-cache {_CODEX_BIN} {subcmd}"
+            f"printf '%s' {q(exec_prompt)} > {q(prompt_file)}; "
+            f"cd {q(cwd)} && UV_CACHE_DIR=/tmp/uv-cache {q(_CODEX_BIN)} {subcmd}"
             f"{sandbox} --skip-git-repo-check --full-auto --json"
-            f" -o {codex_out} - < {prompt_file}"
+            f" -o {q(codex_out)} - < {q(prompt_file)}"
         )
         if is_resume and target:
             # Stale/invalid UUID → resume fails → fresh exec. Only when a target exists —
             # without one the prompt has nothing concrete to review, so let resume fail loud.
             # Writes to codex_out (=round_tmp) so the recovery is appended, not overwriting history.
             fresh_exec = (
-                f"cd {cwd} && UV_CACHE_DIR=/tmp/uv-cache {_CODEX_BIN} exec"
+                f"cd {q(cwd)} && UV_CACHE_DIR=/tmp/uv-cache {q(_CODEX_BIN)} exec"
                 f" -s workspace-write --skip-git-repo-check --full-auto --json"
-                f" -o {codex_out} - < {prompt_file}"
+                f" -o {q(codex_out)} - < {q(prompt_file)}"
             )
             codex += f" || {{ echo '[resume failed — stale session, starting fresh]'; {fresh_exec}; }}"
     else:
         return f"Error: unknown mode '{mode}'. Use 'review' or 'exec'."
 
     # Ensure codex_sessions.json / *.round are git-ignored in THIS worktree before writing them,
     # so they never dirty the tree / block merge_worker — regardless of how old the worktree is
     # (create_worktree only excludes on spawn; long-lived workers need this at use-time too).
     exclude_setup = (
-        f"cd {cwd} && GD=$(git rev-parse --git-common-dir 2>/dev/null)"
-        f" && {{ case \"$GD\" in /*) ;; *) GD=\"{cwd}/$GD\";; esac;"
+        f"cd {q(cwd)} && GD=$(git rev-parse --git-common-dir 2>/dev/null)"
+        f" && {{ case \"$GD\" in /*) ;; *) GD={q(cwd)}/$GD;; esac;"
         f" mkdir -p \"$GD/info\";"
         f" for p in 'codex_sessions.json' '*.round'; do"
         f" grep -qxF \"$p\" \"$GD/info/exclude\" 2>/dev/null || echo \"$p\" >> \"$GD/info/exclude\";"
         f" done; }}; "
     )
 
-    # dash has no PIPESTATUS: capture codex's exit code, tee JSONL, then persist, then exit
-    # with codex's real code so bg-job success/failure reporting reflects the review, not jq.
-    persist = _codex_persist_snippet(sessions_path, slug, jsonl_file, is_resume, output_abs, round_tmp)
+    finalizer = os.path.join(os.path.dirname(os.path.abspath(__file__)),
+                             "codex_review_artifact.py")
+    finalize_args = [
+        q(sys.executable), q(finalizer),
+        "--output", q(output_abs),
+        "--round-file", q(round_tmp),
+        "--sessions-file", q(sessions_path),
+        "--slug", q(slug),
+        "--jsonl-file", q(jsonl_file),
+    ]
+    if is_resume:
+        finalize_args.append("--resume")
+    if mode == "exec":
+        finalize_args.append("--require-verdict")
+    finalize = " ".join(finalize_args)
+
+    # Remove stale temp state before each attempt. A service restart can kill the shell after
+    # an old .rc=0 was written but before the artifact was persisted; reusing that file caused
+    # false success. Codex's real exit code and the artifact validator must both pass.
     cmd = (
         f"{exclude_setup}"
-        f"{{ {codex} ; echo $? > {rc_file} ; }} | tee {jsonl_file}"
-        f"{persist}"
-        f"; exit $(cat {rc_file} 2>/dev/null || echo 1)"
+        f"mkdir -p {q(os.path.dirname(output_abs))}; "
+        f"rm -f {q(rc_file)} {q(jsonl_file)} {q(round_tmp)} {q(prompt_file)}; "
+        f"{{ {codex} ; echo $? > {q(rc_file)} ; }} | tee {q(jsonl_file)}; "
+        f"RC=$(cat {q(rc_file)} 2>/dev/null || echo 1); "
+        f"[ \"$RC\" -eq 0 ] || exit \"$RC\"; "
+        f"{finalize}"
     )
 
     action = "resume" if is_resume else mode
     logger.info(f"codex_review: mode={mode} resume={is_resume} slug={slug} cwd={cwd} output={output_abs}")
     result = await _api("POST", "/api/bg/jobs", json={
         "type": "run",
-        "config": {"command": cmd},
+        "config": {
+            "command": cmd,
+            "success_file": output_abs,
+            "success_pattern": r"(?im)^##\s+Verdict\b" if mode == "exec" else "",
+        },
         "message": f"Codex {action} done. Results in {output}",
         "target_name": WORKER_NAME,
         "target_scope": SCOPE,
         "timeout_seconds": 600,
         "created_by": WORKER_NAME,
     })
     if isinstance(result, dict) and result.get("error"):
         return f"Error creating bg job: {result['error']}"
diff --git a/app/models.py b/app/models.py
index 15fd6566e..7574e2c9d 100644
--- a/app/models.py
+++ b/app/models.py
@@ -29,19 +29,21 @@ MODELS = {
 }
 
 CONTEXT_LIMITS = {
     "claude-fable-5[1m]": 1000000,
     "claude-opus-4-8[1m]": 1000000,
     "claude-opus-4-6[1m]": 1000000,
     "claude-sonnet-5[1m]": 1000000,
     "claude-haiku-4-5": 200000,
-    "gpt-5.6-sol": 1050000,
-    "gpt-5.6-terra": 1050000,
-    "gpt-5.6-luna": 1050000,
+    # Effective ChatGPT-auth Codex runtime budget. Public API window is larger, but
+    # Orchestra's GPT workers run through Codex CLI and must use its runtime contract.
+    "gpt-5.6-sol": 258400,
+    "gpt-5.6-terra": 258400,
+    "gpt-5.6-luna": 258400,
     "gpt-5.5": 258400,
     "gpt-5.4": 258400,
     "gpt-5.4-mini": 258400,
 }
 
 # Short aliases let agents use "opus", "sonnet" etc. in spawn_worker without
 # knowing the exact versioned model ID — reduces prompt brittleness on model upgrades
 ALIASES = {
diff --git a/app/session.py b/app/session.py
index 70d6518c2..359368087 100644
--- a/app/session.py
+++ b/app/session.py
@@ -21,16 +21,28 @@ from app.session_state import (  # noqa: F401 — re-exported: importers use app
 from app.session_turns import TurnManager
 
 if TYPE_CHECKING:
     from app.backend_protocol import BackendLike
 from app.db import save_session, add_log
 
 logger = logging.getLogger(__name__)
 
+
+def _is_terminal_subscription_limit(text: str) -> bool:
+    """Known non-transient subscription limits that must never enter server retry."""
+    lowered = text.lower()
+    return any(marker in lowered for marker in (
+        "session limit",
+        "hit your session",
+        "monthly spend limit",
+        "weekly usage limit",
+        "weekly limit",
+    ))
+
 import concurrent.futures
 _DB_EXECUTOR: Optional[concurrent.futures.ThreadPoolExecutor] = None
 
 
 def _db_executor() -> concurrent.futures.ThreadPoolExecutor:
     """Dedicated pool for DB writes so logs/persists don't contend with git ops
     on the default executor (used by asyncio.to_thread)."""
     global _DB_EXECUTOR
@@ -300,16 +312,21 @@ class AgentSession:
     async def start(self, initial_message: str | None = None) -> None:
         if initial_message:
             await self.send(initial_message)
         else:
             self.status = AgentStatus.IDLE
             self._persist()
 
     async def send(self, message: str) -> None:
+        if not message.startswith("[system] Retrying after rate limit."):
+            # Retry budget belongs to one logical request. A real new message starts a new
+            # budget; internal retry turns deliberately preserve the current count.
+            self._rate_limit_retries = 0
+            self._session_limit_hit = False
         if self._compacting:
             self._pending_messages.append(message)
             self._log("user_message", message)
             self._log("status", f"message queued (compact in progress, {len(self._pending_messages)} pending)")
             return
 
         if self.status == AgentStatus.RUNNING:
             if self.backend_type == "codex":
@@ -567,18 +584,18 @@ class AgentSession:
         if sub_id and event.type in ("tool_use", "tool_result", "text", "thinking"):
             from app.live_broker import broker
             broker.publish(self.id, {"type": "subagent_event", "event_type": event.type,
                                      "content": event.content[:2000], "subagent_id": sub_id})
             return
         if event.type == "text":
             from app.live_broker import broker
             broker.clear_accum(self.id)
-            # Session limit comes as text "You've hit your session limit", not as error event
-            if "session limit" in event.content.lower() or "hit your session" in event.content.lower():
+            # Subscription limits arrive as text before the generic rate_limit error.
+            if _is_terminal_subscription_limit(event.content):
                 self._session_limit_hit = True
             self._log("text", event.content)
             self._turn_logs.append(event.content)
         elif event.type == "thinking":
             self._log("thinking", event.content)
         elif event.type == "tool_use":
             self.total_tool_calls += 1
             self._log("tool", event.content)
@@ -595,17 +612,17 @@ class AgentSession:
         elif event.type == "turn_end":
             self._turns.handle_turn_end(event)
         elif event.type == "error":
             # rate_limit → single retry-status log (skip raw error to avoid duplicate
             # "model error: rate_limit" + "rate limited — retry" on one event)
             if "rate_limit" in event.content:
                 # Session limit text arrives BEFORE the error event as text "You've hit your session limit"
                 if self._session_limit_hit:
-                    self._log("error", f"⏳ session limit (подписка) — ждём сброса окна. НЕ ретраим")
+                    self._log("error", "⏳ subscription limit — ждём сброса квоты. НЕ ретраим")
                     self._session_limit_hit = False
                 elif self._rate_limit_retries < self.RATE_LIMIT_MAX_RETRIES:
                     self._rate_limit_retries += 1
                     delay = self.RATE_LIMIT_DELAY * self._rate_limit_retries
                     self._log("status", f"⏳ rate limit (Anthropic сервер) — повтор через {delay}s ({self._rate_limit_retries}/{self.RATE_LIMIT_MAX_RETRIES})")
                     self._spawn_bg(self._rate_limit_retry(delay))
                 else:
                     self._log("error", f"rate limit — gave up after {self.RATE_LIMIT_MAX_RETRIES} retries")
diff --git a/app/session_cost.py b/app/session_cost.py
index a389d75af..7bf9076a3 100644
--- a/app/session_cost.py
+++ b/app/session_cost.py
@@ -30,36 +30,46 @@ class CostTracker:
             # SDK reports cost_usd cumulative per session_id — reset baseline
             # when a new session starts (e.g. after compact creates a fresh session)
             s._last_cost = 0.0
             s._last_cost_cached = 0.0
             s._context_cost = 0.0
         if sid:
             s.session_id = sid
         new_cost = meta.get("cost_usd", 0)
-        # Delta from last known cumulative — gives per-turn cost without SDK support
-        s._turn_cost = max(0, new_cost - s._last_cost)
+        is_delta = bool(meta.get("cost_is_delta"))
+        # Claude SDK reports cumulative session cost; CodexBackend normalizes its own
+        # cumulative thread counters to a per-turn delta before emitting metadata.
+        s._turn_cost = max(0, new_cost) if is_delta else max(0, new_cost - s._last_cost)
         s.cost_usd += s._turn_cost
         s._context_cost += s._turn_cost
         s._session_cost += s._turn_cost
-        s._last_cost = new_cost
+        s._last_cost = 0.0 if is_delta else new_cost
         new_cost_cached = meta.get("cost_usd_cached", 0)
-        s.cost_usd_cached += max(0, new_cost_cached - s._last_cost_cached)
-        s._last_cost_cached = new_cost_cached
+        if is_delta:
+            s.cost_usd_cached += max(0, new_cost_cached)
+            s._last_cost_cached = 0.0
+        else:
+            s.cost_usd_cached += max(0, new_cost_cached - s._last_cost_cached)
+            s._last_cost_cached = new_cost_cached
         s.total_turns += nt
         s.total_input_tokens += meta.get("input_tokens", 0)
         s.total_output_tokens += meta.get("output_tokens", 0)
         s.total_cache_read_tokens += meta.get("cache_read", 0)
         s.total_cache_create_tokens += meta.get("cache_create", 0)
         return ok, sr, nt
 
     def update_context_from_turn(self, meta: dict) -> None:
         """Update context window stats from turn metadata."""
         s = self.s
         ctx_pct = meta.get("context_pct", 0)
         ctx_tokens = meta.get("context_tokens", 0)
-        if ctx_pct:
+        if meta.get("context_known") is False:
+            # Explicit fail-soft signal from a backend: clear stale dashboard data.
+            s._last_context["percentage"] = 0
+            s._last_context["total_tokens"] = 0
+        elif ctx_pct:
             s._last_context["percentage"] = ctx_pct
             s._last_context["total_tokens"] = ctx_tokens
         s._last_context["max_tokens"] = meta.get("max_tokens", 200000)
         s._last_context["cache_hit"] = meta.get("cache_hit", 0)
         s._last_context["cache_read"] = meta.get("cache_read", 0)
         s._last_context["cache_create"] = meta.get("cache_create", 0)
diff --git a/app/session_turns.py b/app/session_turns.py
index f517b68aa..36d6e3451 100644
--- a/app/session_turns.py
+++ b/app/session_turns.py
@@ -132,17 +132,16 @@ class TurnManager:
             else:
                 s._auto_continue_count += 1
                 s._log("status", f"{sr} ({nt} turns), auto-continuing "
                                  f"({s._auto_continue_count}/{s.AUTO_CONTINUE_MAX})")
                 s._spawn_bg(s._auto_continue())
                 return
         else:
             s._auto_continue_count = 0
-            s._rate_limit_retries = 0
 
         live_pct = s._last_context.get("percentage", 0)
         ctx_s = f"ctx:{live_pct}%" if live_pct else ""
         def _fc(v):
             return f"{v:.4f}" if v < 0.01 and v > 0 else f"{v:.2f}"
         limits_s = _format_limits()
         s._log("status", f"turn ended ({sr}, {nt} turns, ${_fc(s._turn_cost)} turn, ${_fc(s._context_cost)} ctx, ${_fc(s._session_cost)} session, ${_fc(s.cost_usd)} total {ctx_s}){limits_s}")
 
diff --git a/tests/test_backend_codex.py b/tests/test_backend_codex.py
index b1c8589e8..a943c5116 100644
--- a/tests/test_backend_codex.py
+++ b/tests/test_backend_codex.py
@@ -1,48 +1,103 @@
-"""CodexBackend — model dicts, reasoning effort, per-worker MCP config.
+"""CodexBackend — model dicts, runtime accounting, and per-worker MCP config.
 
 Regression net for the three bugs found in the codex-integration audit:
   BUG 1 — Sol/Terra/Luna missing from context/price dicts (worker got 258400 ctx, $0).
   BUG 2 — reasoning effort hardcoded, xhigh/max not in the accepted set.
   MCP   — per-worker MCP servers now injected via -c dotted-leaf overrides.
 """
 
+import json
+
+import pytest
+
 from app.backend_codex import (
     CodexBackend,
     CODEX_CONTEXT_LIMITS,
     CODEX_TOKEN_PRICES,
     CODEX_REASONING_EFFORTS,
+    _codex_cost,
+    _read_rollout_context,
+    _usage_delta,
 )
 
 
 # ── BUG 1: GPT-5.6 models registered in backend dicts ──
 
 def test_gpt56_context_limits_present():
-    # 1.05M window × 0.95 usable = 997500 (not the 258400 fallback for 5.4/5.5)
+    # ChatGPT-auth Codex runtime reports a 258400 effective budget for these models.
+    # The public API's 1.05M window is a different surface and must not drive dashboard
+    # accounting or auto-compact for a local Codex worker.
     for m in ("gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna"):
-        assert CODEX_CONTEXT_LIMITS[m] == 997500, m
+        assert CODEX_CONTEXT_LIMITS[m] == 258400, m
 
 
 def test_gpt56_prices_present():
-    assert CODEX_TOKEN_PRICES["gpt-5.6-sol"] == {"input": 5.0, "output": 30.0}
-    assert CODEX_TOKEN_PRICES["gpt-5.6-terra"] == {"input": 2.5, "output": 15.0}
-    assert CODEX_TOKEN_PRICES["gpt-5.6-luna"] == {"input": 1.0, "output": 6.0}
+    assert CODEX_TOKEN_PRICES["gpt-5.6-sol"] == {"input": 5.0, "cached": 0.5, "output": 30.0}
+    assert CODEX_TOKEN_PRICES["gpt-5.6-terra"] == {"input": 2.5, "cached": 0.25, "output": 15.0}
+    assert CODEX_TOKEN_PRICES["gpt-5.6-luna"] == {"input": 1.0, "cached": 0.1, "output": 6.0}
 
 
 def test_legacy_gpt_models_unchanged():
     assert CODEX_CONTEXT_LIMITS["gpt-5.5"] == 258400
-    assert CODEX_TOKEN_PRICES["gpt-5.4"] == {"input": 2.5, "output": 15.0}
+    assert CODEX_TOKEN_PRICES["gpt-5.4"] == {"input": 2.5, "cached": 0.25, "output": 15.0}
 
 
 def test_sol_price_and_ctx_not_zero_fallback():
-    # The bug's symptom: a Sol worker used the {input:0,output:0} / 258400 fallbacks.
+    # Sol has an explicit runtime limit and price rather than relying on fallbacks.
     b = CodexBackend(model="gpt-5.6-sol", cwd="/tmp")
-    assert CODEX_CONTEXT_LIMITS.get(b.model, 258400) == 997500
-    assert CODEX_TOKEN_PRICES.get(b.model, {"input": 0, "output": 0})["output"] == 30.0
+    assert CODEX_CONTEXT_LIMITS[b.model] == 258400
+    assert CODEX_TOKEN_PRICES[b.model]["output"] == 30.0
+
+
+def test_codex_cost_applies_cached_input_discount():
+    # 100 fresh × $5/M + 900 cached × $0.5/M + 10 output × $30/M.
+    assert _codex_cost("gpt-5.6-sol", 1000, 900, 10) == pytest.approx(0.00125)
+
+
+def test_usage_delta_survives_resume_and_counter_reset():
+    current = {"input_tokens": 130, "cached_input_tokens": 90, "output_tokens": 20}
+    baseline = {"input_tokens": 100, "cached_input_tokens": 80, "output_tokens": 5}
+    assert _usage_delta(current, baseline) == {
+        "input_tokens": 30, "cached_input_tokens": 10, "output_tokens": 15,
+    }
+    # A Codex-side compact may reset counters. Treat the new value as this turn rather
+    # than producing negative usage or zeroing a real call.
+    assert _usage_delta({"input_tokens": 10}, {"input_tokens": 100})["input_tokens"] == 10
+
+
+def test_rollout_context_uses_last_call_not_accumulated_usage(tmp_path):
+    rollout = tmp_path / "rollout.jsonl"
+    rows = [
+        {"type": "event_msg", "payload": {"type": "token_count", "info": {
+            "total_token_usage": {"input_tokens": 760838},
+            "last_token_usage": {"input_tokens": 95489, "cached_input_tokens": 92928},
+            "model_context_window": 258400,
+        }}},
+        {"type": "event_msg", "payload": {"type": "token_count", "info": {
+            "total_token_usage": {"input_tokens": 2042411},
+            "last_token_usage": {"input_tokens": 142165, "cached_input_tokens": 141056},
+            "model_context_window": 258400,
+        }}},
+    ]
+    rollout.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
+
+    assert _read_rollout_context(rollout) == {
+        "input_tokens": 142165,
+        "cached_input_tokens": 141056,
+        "model_context_window": 258400,
+    }
+
+
+def test_rollout_context_fails_soft_on_missing_or_corrupt_data(tmp_path):
+    assert _read_rollout_context(tmp_path / "missing.jsonl") is None
+    corrupt = tmp_path / "corrupt.jsonl"
+    corrupt.write_text("not-json\n{}\n")
+    assert _read_rollout_context(corrupt) is None
 
 
 # ── BUG 2: reasoning effort ──
 
 def test_xhigh_and_max_accepted():
     assert "xhigh" in CODEX_REASONING_EFFORTS
     assert "max" in CODEX_REASONING_EFFORTS
 
@@ -78,8 +133,16 @@ def test_mcp_config_skips_url_only_servers():
 
 
 def test_mcp_config_empty_when_no_servers():
     assert CodexBackend(model="gpt-5.6-sol", cwd="/tmp")._mcp_config_args() == []
 
 
 def test_toml_str_escapes():
     assert CodexBackend._toml_str('a"b\\c') == '"a\\"b\\\\c"'
+
+
+def test_codex_inherits_orchestra_proxy(monkeypatch):
+    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:12343")
+    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:12343")
+    env = CodexBackend(model="gpt-5.6-sol", cwd="/tmp")._build_env()
+    assert env["HTTPS_PROXY"] == "http://127.0.0.1:12343"
+    assert env["HTTP_PROXY"] == "http://127.0.0.1:12343"
diff --git a/tests/test_bg_jobs.py b/tests/test_bg_jobs.py
index 7fdf4466b..73024232b 100644
--- a/tests/test_bg_jobs.py
+++ b/tests/test_bg_jobs.py
@@ -37,16 +37,22 @@ class TestValidateCron:
         err = _validate_config("cron", {"cron_expr": "not a cron"})
         assert err and "invalid cron" in err
 
     def test_accepts_valid(self):
         from app.bg_jobs import _validate_config
         assert _validate_config("cron", {"cron_expr": "*/5 * * * *"}) is None
 
 
+def test_run_rejects_invalid_success_pattern():


## LATER FIX 9f777f912d (19.4 days later): Squashed commits: - #82: исследование — имя как внешний ключ в трёх слоях, тихий путь не тот, что в репорте - #82: план — env чинится пересб
lines of origin it changed/deleted: 2
(code only, capped 400 lines)

Squashed commits:
- #82: исследование — имя как внешний ключ в трёх слоях, тихий путь не тот, что в репорте
- #82: план — env чинится пересборкой, сохранённые ссылки предпочитают id, 4 тикета
- #82: T1 — bg-джобы будят по неизменяемому id, а не по имени
- WIP #82: T2 наполовину — в session.py есть флаг _identity_stale и его гашение на границе хода; НЕ сделано: manager.refresh_identity (пересборка mcp_servers) и вызов из rename_session, весь T3, T4
- #82: T2 — переименование пересобирает MCP-идентичность, перезапуск на границе хода
- #82: T3 — держатель тест-лока по неизменяемому id, дети переименованного родителя
- #82: T4 — живой прогон переименования, отчёт и личная память

(cherry picked from commit 827cd2a6ff6c44030dc80503ae75f0eea0a74f80)

diff --git a/app/bg_jobs.py b/app/bg_jobs.py
index d9f5a4740..c7cd9c228 100644
--- a/app/bg_jobs.py
+++ b/app/bg_jobs.py
@@ -17,17 +17,17 @@ from uuid import uuid4
 from croniter import croniter
 
 from app.db import (
     bg_save_job, bg_claim_trigger, bg_finish_trigger, bg_fail_job,
     bg_cancel_job, bg_expire_job, bg_update_output, bg_get_active_all,
     bg_expire_overdue, bg_count_active, bg_cancel_by_session,
     bg_reset_stale_triggering, bg_cleanup_old,
     bg_cron_should_fire, bg_cron_record_fire,
-    bg_get_jobs, bg_fail_job_if_active, bg_replace_job,
+    bg_get_jobs, bg_get_job, bg_fail_job_if_active, bg_replace_job,
     bg_reset_wake_triggering,
 )
 from app.pidfd_exec import pidfd_send_group
 from app.tasks import spawn_supervised
 
 logger = logging.getLogger(__name__)
 
 MAX_JOBS_PER_SCOPE = 50
@@ -504,26 +504,49 @@ class BgJobManager:
 
     # ── Trigger ──
 
     @staticmethod
     def _restore_report_provenance(session) -> None:
         if not session.last_task_sender and session.parent_name:
             session.last_task_sender = session.parent_name
 
+    async def _load_job_target(self, job_id: str, target_name: str):
+        """Найти цель джоба по НЕИЗМЕНЯЕМОМУ id из его же строки.
+
+        Имя, записанное при создании, к моменту срабатывания могло смениться
+        (`rename_worker`) или уже принадлежать ДРУГОМУ агенту — разбудить по нему значит
+        либо не разбудить никого молча, либо разбудить чужого. Имя оставлено для человека.
+        """
+        row = bg_get_job(job_id) or {}
+        target_session_id = str(row.get("target_session_id") or "")
+        if not target_session_id:
+            logger.error(
+                f"bg_job {job_id}: no target_session_id "
+                f"(name at creation: {target_name!r}) — refusing to wake by name"
+            )
+            return None, "job has no target_session_id"
+        session = await self._session_manager.ensure_loaded_by_id(target_session_id)
+        if not session:
+            logger.warning(
+                f"bg_job {job_id}: target session {target_session_id} "
+                f"(name at creation: {target_name!r}) not found"
+            )
+            return None, "target session not found"
+        return session, ""
+
     async def _trigger(self, job_id: str, message: str,
                        target_name: str, target_scope: str, output: str = "") -> None:
         claimed = bg_claim_trigger(job_id)
         if not claimed:
             return
         try:
-            session = await self._session_manager.ensure_loaded(target_name, target_scope)
+            session, failure = await self._load_job_target(job_id, target_name)
             if not session:
-                bg_fail_job(job_id, "target session not found")
-                logger.warning(f"bg_job {job_id}: target {target_name} not found")
+                bg_fail_job(job_id, failure)
                 return
             body = f"[Background job completed] {message}"
             if output:
                 body += f"\n\nOutput (last 3000 chars):\n{output[-3000:]}"
             self._restore_report_provenance(session)
             await self._session_manager.send(session.id, body)
             bg_finish_trigger(job_id, output)
             logger.info(f"bg_job {job_id}: triggered → {target_name}")
@@ -553,37 +576,35 @@ class BgJobManager:
         Without this, a hung process leaves the worker waiting forever."""
         bg_expire_job(job_id)
         self._procs.pop(job_id, None)
         dur = f"{round(timeout / 60, 1)} min" if timeout >= 60 else f"{int(timeout)}s"
         err = (f"{message}\n[TIMEOUT] killed after {dur} — no completion. "
                f"The process produced no output or hung. Check the target tool "
                f"(codex auth/proxy/sandbox) and retry.")
         try:
-            session = await self._session_manager.ensure_loaded(target_name, target_scope)
+            session, _failure = await self._load_job_target(job_id, target_name)
             if not session:
-                logger.warning(f"bg_job {job_id}: timeout, target {target_name} not found")
                 return
             body = f"[Background job TIMED OUT] {err}"
             if output:
                 body += f"\n\nPartial output (last 3000 chars):\n{output[-3000:]}"
             self._restore_report_provenance(session)
             await self._session_manager.send(session.id, body)
             logger.warning(f"bg_job {job_id}: TIMED OUT after {dur} → notified {target_name}")
         except Exception as e:
             logger.error(f"bg_job {job_id}: timeout-notify failed: {e}")
 
     async def _fail_notify(self, job_id, message, target_name, target_scope,
                            error, output=""):
         """Persist a failed run and wake the waiting agent with an explicit failure."""
         bg_fail_job(job_id, error)
         try:
-            session = await self._session_manager.ensure_loaded(target_name, target_scope)
+            session, _failure = await self._load_job_target(job_id, target_name)
             if not session:
-                logger.warning(f"bg_job {job_id}: failed, target {target_name} not found")
                 return
             body = f"[Background job FAILED] {message}\n{error}"
             if output:
                 body += f"\n\nOutput (last 3000 chars):\n{output[-3000:]}"
             self._restore_report_provenance(session)
             await self._session_manager.send(session.id, body)
             logger.warning(f"bg_job {job_id}: FAILED → notified {target_name}: {error}")
         except Exception as e:
@@ -640,19 +661,19 @@ class BgJobManager:
             pass
         except Exception as e:
             bg_fail_job(job_id, str(e)[:500])
 
     async def _fire_cron(self, job_id, message, target_name, target_scope):
         if not bg_cron_should_fire(job_id):
             return
         try:
-            session = await self._session_manager.ensure_loaded(target_name, target_scope)
+            session, _failure = await self._load_job_target(job_id, target_name)
             if not session:
-                logger.warning(f"cron {job_id}: target {target_name} not found, skipping fire")
+                # Расписание живёт дальше: цель могла быть выгружена временно.
                 return
             await self._session_manager.send(
                 session.id, f"[Cron job fired] {message}",
             )
             bg_cron_record_fire(job_id)
             logger.info(f"cron {job_id}: fired → {target_name}")
         except Exception as e:
             logger.error(f"cron {job_id}: fire failed (continuing schedule): {e}")
@@ -695,25 +716,18 @@ class BgJobManager:
             if proc.returncode:
                 output += f"\n[exit code {proc.returncode}]"
             output = output.strip()
             bg_update_output(job_id, output)
             if not raw_output or re.search(pattern, raw_output) is None:
                 return
             if not bg_cron_should_fire(job_id):
                 return
-            session = await self._session_manager.ensure_loaded(
-                target_name, target_scope,
-            )
+            session, _failure = await self._load_job_target(job_id, target_name)
             if not session:
-                logger.warning(
-                    "cron_command %s: target %s not found, skipping match",
-                    job_id,
-                    target_name,
-                )
                 return
             self._restore_report_provenance(session)
             body = f"[Cron command matched] {message}"
             if output:
                 body += f"\n\nOutput (last 3000 chars):\n{output[-3000:]}"
             await self._session_manager.send(session.id, body)
             bg_cron_record_fire(job_id)
             bg_update_output(job_id, output)
diff --git a/app/db.py b/app/db.py
index ffce0e963..762e69f3d 100644
--- a/app/db.py
+++ b/app/db.py
@@ -118,16 +118,17 @@ def init_db() -> None:
                 ended_at TEXT,
                 UNIQUE(session_id, task_id)
             );
             CREATE INDEX IF NOT EXISTS idx_subagents_session ON subagents(session_id);
 
             CREATE TABLE IF NOT EXISTS test_lock (
                 scope TEXT PRIMARY KEY,
                 holder TEXT NOT NULL,
+                holder_session_id TEXT NOT NULL DEFAULT '',
                 reason TEXT DEFAULT '',
                 acquired_at TEXT NOT NULL
             );
         """)
         c.executescript("""
             CREATE TABLE IF NOT EXISTS tm_projects (
                 id TEXT PRIMARY KEY,
                 name TEXT NOT NULL,
@@ -404,16 +405,19 @@ def _guard_session_id(c) -> None:
         BEGIN SELECT RAISE(ABORT, 'sessions.id must be non-empty'); END;
     """)
 
 
 def _migrate(c) -> None:
     # Additive ALTER TABLE migrations — safe to re-run (IF NOT EXISTS / column check).
     # Never drop columns: old Orchestra versions reading the same DB must still work.
     _guard_session_id(c)
+    lock_cols = {row[1] for row in c.execute("PRAGMA table_info(test_lock)").fetchall()}
+    if lock_cols and "holder_session_id" not in lock_cols:
+        c.execute("ALTER TABLE test_lock ADD COLUMN holder_session_id TEXT NOT NULL DEFAULT ''")
     cols = {row[1] for row in c.execute("PRAGMA table_info(sessions)").fetchall()}
     if "color" not in cols:
         c.execute("ALTER TABLE sessions ADD COLUMN color TEXT DEFAULT ''")
     if "context_pct" not in cols:
         c.execute("ALTER TABLE sessions ADD COLUMN context_pct INTEGER DEFAULT 0")
     if "context_tokens" not in cols:
         c.execute("ALTER TABLE sessions ADD COLUMN context_tokens INTEGER DEFAULT 0")
     if "progress_pct" not in cols:
@@ -1330,16 +1334,22 @@ def bg_claim_trigger(job_id: str) -> bool:
     with _conn() as c:
         cur = c.execute(
             "UPDATE bg_jobs SET status='triggering', triggered_at=? WHERE id=? AND status='active'",
             (datetime.now(timezone.utc).isoformat(), job_id),
         )
         return cur.rowcount > 0
 
 
+def bg_get_job(job_id: str) -> dict | None:
+    with _conn() as c:
+        row = c.execute("SELECT * FROM bg_jobs WHERE id = ?", (job_id,)).fetchone()
+        return dict(row) if row else None
+
+
 def bg_finish_trigger(job_id: str, last_output: str = "") -> None:
     with _conn() as c:
         c.execute(
             "UPDATE bg_jobs SET status='triggered', last_output=? WHERE id=?",
             (last_output[-3000:], job_id),
         )
 
 
@@ -1802,44 +1812,68 @@ def usage_get_history(hours: int = 24, step_minutes: int = 5, until: str = "") -
         t += step
     if not grid or grid[-1].get("id") != raw[-1].get("id"):
         grid.append(raw[-1])
     return grid
 
 
 # ── Test Lock ──
 
-def acquire_test_lock(scope: str, holder: str, reason: str = "") -> tuple[bool, str | None]:
+def _same_lock_holder(row, holder: str, holder_session_id: str) -> bool:
+    """Тот же держатель?
+
+    По НЕИЗМЕНЯЕМОМУ id, когда он известен обеим сторонам: имя агента меняется
+    `rename_worker` и может быть занято другим агентом — тогда сравнение по строке либо
+    не даёт снять свой лок, либо даёт снять ЧУЖОЙ. Строка от старого сервера id не имеет,
+    и для неё остаётся сравнение по имени — иначе живой лок стал бы неснимаемым в окне
+    между мержем и рестартом.
+    """
+    stored_id = row["holder_session_id"] if "holder_session_id" in row.keys() else ""
+    if stored_id and holder_session_id:
+        return stored_id == holder_session_id
+    return row["holder"] == holder
+
+
+def acquire_test_lock(scope: str, holder: str, reason: str = "",
+                      holder_session_id: str = "") -> tuple[bool, str | None]:
     """Захватить глобальный тест-лок для scope.
 
     Возвращает (ok, current_holder):
     - (True, None)   — лок свободен, захвачен
-    - (True, holder) — лок уже за этим же holder (идемпотентно), reason обновлён
+    - (True, holder) — лок уже за этим же держателем (идемпотентно), reason обновлён
     - (False, name)  — занят другим, name = текущий держатель
     """
     now = datetime.now(timezone.utc).isoformat()
     with _conn() as c:
-        row = c.execute("SELECT holder FROM test_lock WHERE scope = ?", (scope,)).fetchone()
+        row = c.execute("SELECT * FROM test_lock WHERE scope = ?", (scope,)).fetchone()
         if row is not None:
-            if row["holder"] == holder:
-                c.execute("UPDATE test_lock SET reason = ?, acquired_at = ? WHERE scope = ?",
-                          (reason, now, scope))
+            if _same_lock_holder(row, holder, holder_session_id):
+                # Имя держателя могло смениться с момента захвата — показываем текущее.
+                c.execute(
+                    "UPDATE test_lock SET holder = ?, holder_session_id = ?, reason = ?, "
+                    "acquired_at = ? WHERE scope = ?",
+                    (holder, holder_session_id or row["holder_session_id"], reason, now, scope),
+                )
                 return True, holder
             return False, row["holder"]
         c.execute(
-            "INSERT INTO test_lock (scope, holder, reason, acquired_at) VALUES (?, ?, ?, ?)",
-            (scope, holder, reason, now),
+            "INSERT INTO test_lock (scope, holder, holder_session_id, reason, acquired_at) "
+            "VALUES (?, ?, ?, ?, ?)",
+            (scope, holder, holder_session_id, reason, now),
         )
         return True, None
 
 
-def release_test_lock(scope: str, holder: str) -> bool:
-    """Освободить лок. True — освобождён (был за этим holder); False — не держатель / лок свободен."""
+def release_test_lock(scope: str, holder: str, holder_session_id: str = "") -> bool:
+    """Освободить лок. True — освобождён (был за этим держателем); False — не держатель."""
     with _conn() as c:
-        cur = c.execute("DELETE FROM test_lock WHERE scope = ? AND holder = ?", (scope, holder))
+        row = c.execute("SELECT * FROM test_lock WHERE scope = ?", (scope,)).fetchone()
+        if row is None or not _same_lock_holder(row, holder, holder_session_id):
+            return False
+        cur = c.execute("DELETE FROM test_lock WHERE scope = ?", (scope,))
         return cur.rowcount > 0
 
 
 def get_test_lock(scope: str) -> dict | None:
     """Текущий держатель лока для scope или None."""
     with _conn() as c:
         row = c.execute("SELECT * FROM test_lock WHERE scope = ?", (scope,)).fetchone()
         return dict(row) if row else None
diff --git a/app/manager.py b/app/manager.py
index ccf0f7822..96a5a6963 100644
--- a/app/manager.py
+++ b/app/manager.py
@@ -383,25 +383,29 @@ def _parse_custom_mcp(raw) -> dict:
             return {}
     if not isinstance(raw, dict):
         logger.warning(f"mcp_servers_custom is not an object ({type(raw).__name__}); ignoring")
         return {}
     return {k: v for k, v in raw.items() if k != "orchestra"}
 
 
 def _make_mcp_config(name: str, scope: str, role: str = "worker",
-                     parent_name: str = "", extra: dict | None = None) -> dict:
+                     parent_name: str = "", extra: dict | None = None,
+                     session_id: str = "") -> dict:
     env = {
         **MCP_BASE_ENV,
         "ORCHESTRA_URL": "http://127.0.0.1:8888",
         "ORCHESTRA_SCOPE": scope,
         "ORCHESTRA_ROLE": role,
         "ORCHESTRA_ACCESS_MODE": "full",
         "WORKER_NAME": name,
         "PARENT_NAME": parent_name,
+        # Имя агент может сменить, id — нет. Всё, что СОХРАНЯЕТСЯ и сравнивается позже
+        # (держатель тест-лока), обязано опираться на него, а не на имя (#82).
+        "ORCHESTRA_SESSION_ID": session_id,
     }
     cfg = {"orchestra": {"command": MCP_STDIO_CMD[0], "args": MCP_STDIO_CMD[1:], "env": env, "alwaysLoad": True}}
     if extra:
         for k, v in extra.items():
             if k == "orchestra":
                 logger.warning("custom MCP server 'orchestra' would override Orchestra MCP — ignored")
                 continue
             cfg[k] = v
@@ -638,23 +642,25 @@ class SessionManager:
         if is_orch and not parent_name:
             tg_topic = True
 
         custom_mcp = _parse_custom_mcp(mcp_servers)
         bt = backend_for_model(model)
         _rr_effort = get_role(pipeline, role)
         raw_effort = getattr(_rr_effort, "effort", None) if _rr_effort else None
         effort = raw_effort if isinstance(raw_effort, str) and raw_effort else None
+        session_id = str(uuid.uuid4())
         session = AgentSession(
-            id=str(uuid.uuid4()), name=name, scope=scope, cwd=cwd, model=model,
+            id=session_id, name=name, scope=scope, cwd=cwd, model=model,
             system_prompt=prompt, role=role,
             parent_id=parent_id, parent_name=parent_name,
             pipeline=pipeline, profile=profile,
             color="" if is_orch else self._pick_color(),
-            mcp_servers=_make_mcp_config(name, scope, role, parent_name=parent_name, extra=custom_mcp),
+            mcp_servers=_make_mcp_config(name, scope, role, parent_name=parent_name,
+                                         extra=custom_mcp, session_id=session_id),
             mcp_servers_custom=custom_mcp,
             backend_type=bt, effort=effort, task_id=task_id, description=description,
             base_branch=base_branch,
             owned_dirs=owned_dirs,
             tg_topic=tg_topic,
         )
         session.is_orchestrator = is_orch
         session._template_hash = prompt_template_hash(role)
@@ -956,16 +962,40 @@ class SessionManager:
             await asyncio.to_thread(
                 remove_worktree,
                 session.scope,
                 session.worktree_path,
             )
         archive_session(session_id)
         self.sessions.pop(session_id, None)
 
+    def refresh_identity(self, session) -> str:
+        """Пересобрать MCP-конфиг сессии под её ТЕКУЩИЕ имя и родителя.
+
+        `WORKER_NAME`/`PARENT_NAME` попадают в env MCP-подпроцесса один раз — при его
+        старте, — поэтому переименование обязано поднять подпроцесс заново. Конфиг
+        обновляем СРАЗУ: любой следующий коннект строит бэкенд из `session.mcp_servers`,
+        значит упавший ход, гибернация и рестарт чинятся сами. Живой бэкенд гасится не


## LATER FIX 17a7d398b9 (83.4 days later): V-756: #V-756: fix repeated workflow prompts and wakes
lines of origin it changed/deleted: 8
(code only, capped 400 lines)

V-756: #V-756: fix repeated workflow prompts and wakes

Squashed commits:
- #V-756: fix repeated workflow prompts and wakes
- #V-756: import workflow runner in regression test
- #V-756: record merge gate verification

Orchestra-Operation: a3291105-3158-41af-aecd-f325f21e867f


diff --git a/app/bg_jobs.py b/app/bg_jobs.py
index c88f5ca4d..147005f5b 100644
--- a/app/bg_jobs.py
+++ b/app/bg_jobs.py
@@ -478,38 +478,52 @@ class BgJobManager:
             lambda finished: (
                 self._tasks.pop(job_id, None)
                 if self._tasks.get(job_id) is finished
                 else None
             )
         )
 
     async def cancel(self, job_id: str) -> dict:
+        row = bg_get_job(job_id) or {}
         ok = bg_cancel_job(job_id)
         if not ok:
             return {"error": "job not found or not active"}
         task = self._tasks.pop(job_id, None)
         if task and not task.done():
             task.cancel()
         proc = self._procs.pop(job_id, None)
         if proc:
             await _kill_proc(proc)
+        if row.get("type") == "run":
+            await self._interrupt_run_notify(
+                job_id, row.get("message") or "Background run", row.get("target_name") or "?",
+                row.get("target_scope") or "",
+                reason="Отменён вызывающим агентом; повторный запуск не выполнялся.",
+                output=row.get("last_output") or "",
+            )
         return {"ok": True}
 
     async def cancel_by_session(self, session_id: str) -> None:
         active = bg_get_jobs(session_id=session_id, active_only=True)
         job_ids = [j["id"] for j in active]
         cancelled_count = bg_cancel_by_session(session_id)
         for jid in job_ids:
             task = self._tasks.pop(jid, None)
             if task and not task.done():
                 task.cancel()
             proc = self._procs.pop(jid, None)
             if proc:
                 await _kill_proc(proc)
+            row = next((job for job in active if job["id"] == jid), {})
+            if row.get("type") == "run":
+                await self._report_undelivered_job(
+                    jid, row.get("target_name") or "?", row.get("target_scope") or "",
+                    "target session stopped while its run job was active",
+                )
         if cancelled_count:
             logger.info(f"bg_jobs: cancelled {cancelled_count} jobs for session {session_id}")
 
     async def restore_from_db(self) -> None:
         legacy_idle = bg_cancel_removed_idle()
         if legacy_idle:
             logger.info("bg_jobs: cancelled %s legacy idle watches (type removed)", legacy_idle)
         cleaned = bg_cleanup_old(24)
@@ -521,16 +535,27 @@ class BgJobManager:
                 "bg_jobs: reset %s interrupted wake jobs",
                 len(wake_reset_ids),
             )
         expired_ids = bg_expire_overdue()
         for jid in expired_ids:
             task = self._tasks.pop(jid, None)
             if task and not task.done():
                 task.cancel()
+            row = bg_get_job(jid)
+            if row and row.get("type") == "run":
+                timeout = max(
+                    1,
+                    (datetime.fromisoformat(row["expires_at"])
+                     - datetime.fromisoformat(row["created_at"])).total_seconds(),
+                )
+                await self._expire_notify(
+                    jid, row["message"], row["target_name"], row["target_scope"],
+                    timeout, row.get("last_output") or "",
+                )
         reset_ids = bg_reset_stale_triggering()
         if reset_ids:
             logger.info(f"bg_jobs: reset {len(reset_ids)} stale triggering jobs")
         interrupted_delivery = set(reset_ids)
         active = bg_get_active_all()
         restored = 0
         for row in active:
             if row["id"] in self._tasks:
@@ -620,129 +645,128 @@ class BgJobManager:
         if not session:
             logger.warning(
                 f"bg_job {job_id}: target session {target_session_id} "
                 f"(name at creation: {target_name!r}) not found"
             )
             return None, "target session not found"
         return session, ""
 
-    async def _trigger(self, job_id: str, message: str,
-                       target_name: str, target_scope: str, output: str = "") -> None:
-        claimed = bg_claim_trigger(job_id)
-        if not claimed:
-            return
+    async def _notify_job_target(
+        self, job_id: str, outcome: str, body: str,
+        target_name: str, target_scope: str,
+    ) -> str | None:
         try:
             session, failure = await self._load_job_target(job_id, target_name)
             if not session:
-                bg_fail_job(job_id, failure)
-                return
-            body = f"[Background job completed] {message}"
-            if output:
-                body += f"\n\nOutput (last 3000 chars):\n{output[-3000:]}"
+                raise RuntimeError(failure or "target session not found")
             self._restore_report_provenance(session)
-            injected = self._terminal_message(job_id, "completed", body)
+            injected = self._terminal_message(job_id, outcome, body)
             await self._session_manager.send(
-                session.id,
-                injected,
-                provenance=injected.provenance,
+                session.id, injected, provenance=injected.provenance,
             )
-            bg_finish_trigger(job_id, output)
-            logger.info(f"bg_job {job_id}: triggered → {target_name}")
-        except Exception as e:
-            bg_fail_job(job_id, str(e)[:500])
-            logger.error(f"bg_job {job_id}: trigger failed: {e}")
-            # Факт в состоянии джоба виден только глазами в дашборде — это не уведомление.
-            # Адресат — оркестратор scope: он ставил джоб, ему и решать (#30).
-            from app.notify import report_undelivered
+            return None
+        except Exception as error:
+            reason = f"{type(error).__name__}: {error}"
+            logger.error("bg_job %s: %s notification failed: %s", job_id, outcome, reason)
+            await self._report_undelivered_job(
+                job_id, target_name, target_scope, reason,
+            )
+            return reason
+
+    async def _report_undelivered_job(
+        self, job_id: str, target_name: str, target_scope: str, reason: str,
+    ) -> None:
+        from app.notify import report_undelivered
 
+        try:
             await report_undelivered(
                 self._session_manager,
                 scope=target_scope,
                 worker=target_name,
-                what=f"результат фоновой задачи {job_id}",
-                reason=f"{type(e).__name__}: {e}",
+                what=f"result of background job {job_id}",
+                reason=reason,
                 dedupe_key=f"bgjob:{job_id}",
             )
+        except Exception as fallback_error:
+            logger.error(
+                "bg_job %s: undelivered report failed (%s): %s",
+                job_id, type(fallback_error).__name__, fallback_error,
+            )
+
+    async def _trigger(self, job_id: str, message: str,
+                       target_name: str, target_scope: str, output: str = "") -> None:
+        claimed = bg_claim_trigger(job_id)
+        if not claimed:
+            return
+        body = f"[Background job completed] {message}"
+        if output:
+            body += f"\n\nOutput (last 3000 chars):\n{output[-3000:]}"
+        failure = await self._notify_job_target(
+            job_id, "completed", body, target_name, target_scope,
+        )
+        if failure is None:
+            bg_finish_trigger(job_id, output)
+            logger.info(f"bg_job {job_id}: triggered → {target_name}")
+        else:
+            bg_fail_job(job_id, failure)
 
     def _expire(self, job_id: str) -> None:
         bg_expire_job(job_id)
         self._procs.pop(job_id, None)
 
     async def _expire_notify(self, job_id, message, target_name, target_scope,
                              timeout, output=""):
         """Timeout for a `run` job: NOTIFY the worker instead of expiring silently.
         Without this, a hung process leaves the worker waiting forever."""
         bg_expire_job(job_id)
         self._procs.pop(job_id, None)
         dur = f"{round(timeout / 60, 1)} min" if timeout >= 60 else f"{int(timeout)}s"
         err = (f"{message}\n[TIMEOUT] killed after {dur} — no completion. "
                f"The process produced no output or hung. Check the target tool "
                f"(codex auth/proxy/sandbox) and retry.")
-        try:
-            session, _failure = await self._load_job_target(job_id, target_name)
-            if not session:
-                return
-            body = f"[Background job TIMED OUT] {err}"
-            if output:
-                body += f"\n\nPartial output (last 3000 chars):\n{output[-3000:]}"
-            self._restore_report_provenance(session)
-            injected = self._terminal_message(job_id, "timed_out", body)
-            await self._session_manager.send(
-                session.id,
-                injected,
-                provenance=injected.provenance,
-            )
+        body = f"[Background job TIMED OUT] {err}"
+        if output:
+            body += f"\n\nPartial output (last 3000 chars):\n{output[-3000:]}"
+        failure = await self._notify_job_target(
+            job_id, "timed_out", body, target_name, target_scope,
+        )
+        if failure is None:
             logger.warning(f"bg_job {job_id}: TIMED OUT after {dur} → notified {target_name}")
-        except Exception as e:
-            logger.error(f"bg_job {job_id}: timeout-notify failed: {e}")
 
     async def _fail_notify(self, job_id, message, target_name, target_scope,
                            error, output=""):
         """Persist a failed run and wake the waiting agent with an explicit failure."""
         bg_fail_job(job_id, error)
-        try:
-            session, _failure = await self._load_job_target(job_id, target_name)
-            if not session:
-                return
-            body = f"[Background job FAILED] {message}\n{error}"
-            if output:
-                body += f"\n\nOutput (last 3000 chars):\n{output[-3000:]}"
-            self._restore_report_provenance(session)
-            injected = self._terminal_message(job_id, "failed", body)
-            await self._session_manager.send(
-                session.id,
-                injected,
-                provenance=injected.provenance,
-            )
+        body = f"[Background job FAILED] {message}\n{error}"
+        if output:
+            body += f"\n\nOutput (last 3000 chars):\n{output[-3000:]}"
+        failure = await self._notify_job_target(
+            job_id, "failed", body, target_name, target_scope,
+        )
+        if failure is None:
             logger.warning(f"bg_job {job_id}: FAILED → notified {target_name}: {error}")
-        except Exception as e:
-            logger.error(f"bg_job {job_id}: failure-notify failed: {e}")
 
-    async def _interrupt_run_notify(self, job_id, message, target_name, target_scope):
-        reason = "Прерван рестартом сервиса, повторный запуск не выполнялся."
+    async def _interrupt_run_notify(
+        self, job_id, message, target_name, target_scope,
+        reason="Прерван рестартом сервиса, повторный запуск не выполнялся.",
+        output="",
+    ):
         bg_fail_job(job_id, reason)
-        try:
-            session, _failure = await self._load_job_target(job_id, target_name)
-            if not session:
-                return
-            body = f"[Background job INTERRUPTED] {message}\n{reason}"
-            self._restore_report_provenance(session)
-            injected = self._terminal_message(job_id, "interrupted", body)
-            await self._session_manager.send(
-                session.id,
-                injected,
-                provenance=injected.provenance,
-            )
+        body = f"[Background job INTERRUPTED] {message}\n{reason}"
+        if output:
+            body += f"\n\nPartial output (last 3000 chars):\n{output[-3000:]}"
+        failure = await self._notify_job_target(
+            job_id, "interrupted", body, target_name, target_scope,
+        )
+        if failure is None:
             logger.warning(
-                "bg_job %s: interrupted by service restart → notified %s",
+                "bg_job %s: interrupted → notified %s",
                 job_id, target_name,
             )
-        except Exception as e:
-            logger.error(f"bg_job {job_id}: restart-interrupt notify failed: {e}")
 
     def _fail_if_active(self, job_id: str, error: str) -> None:
         bg_fail_job_if_active(job_id, error)
 
     # ── Runners ──
 
     async def _run_merge_watch(self, job_id, operation_id, message,
                                target_name, target_scope, timeout):
@@ -1133,24 +1157,38 @@ class BgJobManager:
                     job_id, message, target_name, target_scope,
                     validation_error, full_output,
                 )
                 return
 
             trigger_msg = f"{message}\nExit code: 0"
             await self._trigger(job_id, trigger_msg, target_name, target_scope, full_output)
         except asyncio.TimeoutError:
+            kill_error = ""
             if proc:
-                await _kill_proc(proc)
-            await self._expire_notify(job_id, message, target_name, target_scope,
-                                      timeout, "".join(output_buf))
+                try:
+                    await _kill_proc(proc)
+                except Exception as error:
+                    kill_error = f"; process kill failed: {type(error).__name__}: {error}"
+            output = "".join(output_buf)
+            if kill_error:
+                output += f"\n{kill_error}"
+            await self._expire_notify(
+                job_id, message, target_name, target_scope, timeout,
+                output,
+            )
+            if kill_error:
+                logger.error("bg_job %s: %s", job_id, kill_error.lstrip("; "))
         except asyncio.CancelledError:
             pass
         except Exception as e:
-            bg_fail_job(job_id, str(e)[:500])
+            await self._fail_notify(
+                job_id, message, target_name, target_scope,
+                f"{type(e).__name__}: {e}", "".join(output_buf),
+            )
         finally:
             if reader_task and not reader_task.done():
                 reader_task.cancel()
                 await asyncio.gather(reader_task, return_exceptions=True)
             self._procs.pop(job_id, None)
             if proc:
                 await _kill_proc(proc)
                 transport = getattr(proc, "_transport", None)
diff --git a/scripts/wf_run.py b/scripts/wf_run.py
index a490e303e..49a76f9b8 100644
--- a/scripts/wf_run.py
+++ b/scripts/wf_run.py
@@ -106,16 +106,20 @@ class WorkflowValue:
             workspace_path=str(row.get("workspace_path") or ""),
             free_sources=frozenset(str(item) for item in row.get("free_sources") or []),
             verified_sources=frozenset(
                 str(item) for item in row.get("verified_sources") or []
             ),
         )
 
 
+class WorkspacePreparationError(RuntimeError):
+    pass
+
+
 class Budget:
     def __init__(self, maximum_usd: float, maximum_calls: int):
         if maximum_usd < 0:
             raise ValueError("budget_usd must be non-negative")
         if maximum_calls < 1:
             raise ValueError("max_calls must be positive")
         self.maximum_usd = float(maximum_usd)
         self.maximum_calls = int(maximum_calls)
@@ -492,29 +496,37 @@ class WorkflowEngine:
                 self.budget.spent_usd += float(row.get("cost_usd") or 0)
             elif event == "schema_invalid":
                 call_key = str(row.get("call_key") or "")
                 last_state[call_key] = "schema_invalid"
                 self._retry_state[call_key] = (
                     int(row.get("next_attempt") or 0),
                     str(row.get("error") or "schema validation failed"),
                 )
+            elif event == "prepare_failed":
+                call_key = str(row.get("call_key") or "")
+                last_state[call_key] = "prepare_failed"
+                self.budget.dispatched_calls = max(0, self.budget.dispatched_calls - 1)
+                self._step_records[call_key] = {
+                    **row, "reason": "prepare_failed", "value": None,
+                }
             elif event == "completed":
                 call_key = str(row.get("call_key") or "")
                 last_state[call_key] = "completed"
                 value = row.get("value")
                 self._completed[call_key] = (
                     WorkflowValue.from_record(value) if isinstance(value, dict) else None
                 )
                 self._completed_reason[call_key] = str(row.get("reason") or "completed")
                 self._step_records[call_key] = row
         self._unknown_calls = {
             call_key
             for call_key in dispatched_calls
-            if call_key not in self._completed and last_state.get(call_key) != "schema_invalid"
+            if call_key not in self._completed
+            and last_state.get(call_key) not in {"schema_invalid", "prepare_failed"}
         }
         if self._unknown_calls:
             self.budget.spent_usd = max(self.budget.spent_usd, self.budget.maximum_usd)
 