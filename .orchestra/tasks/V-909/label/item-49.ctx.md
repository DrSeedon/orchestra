# Context for item-49

## Diff reviewed (-U20, capped at 1500 lines)

diff --git a/app/backend_codex.py b/app/backend_codex.py
index 0b8550fde..afc14a3f0 100644
--- a/app/backend_codex.py
+++ b/app/backend_codex.py
@@ -314,41 +314,41 @@ def _carried_base_scalars() -> str:
     except (OSError, tomllib.TOMLDecodeError) as exc:
         logger.warning("could not read base codex config %s: %s", base, exc)
         return ""
     lines = [
         f"{key} = {json.dumps(data[key])}"
         for key in _CARRIED_BASE_KEYS
         if isinstance(data.get(key), (int, float, bool, str))
     ]
     return "\n".join(lines)
 
 
 ORCHESTRA_FULL_MCP_TOOLS = (
     "spawn_worker", "acquire_test_lock", "release_test_lock", "test_lock_status",
     "send_message", "list_agents", "list_orchestrators", "get_worker_logs",
     "compact_worker", "kill_worker", "stop_worker", "rename_worker",
     "send_file", "update_progress", "change_worker_model", "merge_worker",
     "switch_worker_branch", "check_conflict", "worker_wip", "report_bug",
     "update_worker_description", "update_worker_prompt", "get_worker_info",
     "task_create", "task_update", "task_list", "task_get", "payment_receive",
     "payment_status", "bg_create", "bg_list", "bg_cancel", "search_memory",
-    "codex_review",
+    "codex_review", "open_fan",
 )
 
 
 class CodexProtocolError(RuntimeError):
     """JSON-RPC error returned by Codex app-server."""
 
     def __init__(self, method: str, error: dict):
         self.method = method
         self.error = error
         super().__init__(f"{method}: {error.get('message', 'Codex app-server error')}")
 
 
 class CodexBackend(JsonRpcStdioTransport):
     """Persistent Codex app-server client with native turn steering.
 
     One app-server process owns one resumable thread. `send()` starts a turn while idle
     and uses `turn/steer` while that turn is in flight, matching the native Codex TUI.
     """
 
     RUNTIME_LABEL = "Codex app-server"
diff --git a/docs/tasks/244/codex-review-impl.md b/docs/tasks/244/codex-review-impl.md
new file mode 100644
index 000000000..04879ab07
--- /dev/null
+++ b/docs/tasks/244/codex-review-impl.md
@@ -0,0 +1,13 @@
+## Summary
+
+APPROVED. `open_fan` is included in the Codex allowlist and rendered TOML. The registration-derived guard detects missing and stale entries while preserving exactly the two intentional exclusions.
+
+## Findings
+
+None.
+
+## Verdict
+
+APPROVED
+
+`uv run pytest -q tests/test_backend_codex.py` → **78 passed in 7.86s**.
diff --git a/tests/test_backend_codex.py b/tests/test_backend_codex.py
index 76e1ec14e..0fbd957d6 100644
--- a/tests/test_backend_codex.py
+++ b/tests/test_backend_codex.py
@@ -1,40 +1,41 @@
 """CodexBackend — model dicts, runtime accounting, and per-worker MCP config.
 
 Regression net for the three bugs found in the codex-integration audit:
   BUG 1 — Sol/Terra/Luna missing from context/price dicts (worker got 258400 ctx, $0).
   BUG 2 — reasoning effort hardcoded, xhigh/max not in the accepted set.
   MCP   — per-worker MCP servers now injected via -c dotted-leaf overrides.
 """
 
 import asyncio
 import json
 import shutil
 import subprocess
 from types import SimpleNamespace
 from unittest.mock import AsyncMock, MagicMock
 
 import pytest
 
 from app.backend_codex import (
     CodexBackend,
     CodexProtocolError,
+    ORCHESTRA_FULL_MCP_TOOLS,
     CODEX_CONTEXT_LIMITS,
     CODEX_TOKEN_PRICES,
     CODEX_REASONING_EFFORTS,
     _codex_cost,
     _read_rollout_context,
     _read_rollout_totals,
     _usage_delta,
 )
 from app.runtime_history import (
     CODEX_CLI_HISTORY_VERSION,
     HISTORICAL_TOOL_INSTRUCTION,
     NativeHistoryUnsupported,
     render_codex_history,
 )
 
 
 class _FakeProcess:
     def __init__(self, pid=123):
         self.pid = pid
         self.returncode = None
@@ -225,59 +226,70 @@ def test_rollout_context_fails_soft_on_missing_or_corrupt_data(tmp_path):
 # ── BUG 2: reasoning effort ──
 
 def test_xhigh_and_max_accepted():
     assert "xhigh" in CODEX_REASONING_EFFORTS
     assert "max" in CODEX_REASONING_EFFORTS
 
 
 def test_effort_passthrough_and_fallback():
     assert CodexBackend(model="gpt-5.6-sol", cwd="/tmp", reasoning_effort="xhigh").reasoning_effort == "xhigh"
     # unknown value falls back to high, never crashes
     assert CodexBackend(model="gpt-5.6-sol", cwd="/tmp", reasoning_effort="bogus").reasoning_effort == "high"
 
 
 # ── Per-worker MCP config ──
 # КОНТРАКТ СМЕНИЛСЯ в #224: раньше конфиг ехал в argv как `-c mcp_servers.<n>.env={...}`
 # со ЗНАЧЕНИЯМИ секретов, а `/proc/<pid>/cmdline` читает процесс ЛЮБОГО uid. Теперь он
 # целиком лежит в `$CODEX_HOME/config.toml` с правами 600. Утверждения ниже переписаны на
 # новый носитель: проверяется то же самое (command/args/env/enabled_tools/url), но там,
 # где оно теперь находится.
 
+
+def test_full_mcp_allowlist_tracks_registered_tools():
+    from app.mcp_stdio import mcp
+
+    registered = {tool.name for tool in mcp._tool_manager.list_tools()}
+    enabled = set(ORCHESTRA_FULL_MCP_TOOLS)
+
+    assert enabled <= registered
+    assert registered - enabled == {"resolve_merge_operation", "send_chart"}
+
 def test_mcp_config_rendered_into_config_toml_not_argv():
     import tomllib
     b = CodexBackend(model="gpt-5.6-sol", cwd="/tmp", mcp_servers={
         "orchestra": {
             "command": "python",
             "args": ["/x/mcp_stdio.py"],
             "env": {"WORKER_NAME": "w1", "ORCHESTRA_SESSION_ID": "sess-codexcfg"},
         },
     })
     assert b._mcp_config_args() == [], "конфиг снова уезжает в argv"
 
     data = tomllib.loads((b._prepare_codex_home() / "config.toml").read_text())
     srv = data["mcp_servers"]["orchestra"]
     assert srv["command"] == "python"
     assert srv["args"] == ["/x/mcp_stdio.py"]
     assert srv["enabled"] is True
     assert srv["env"]["WORKER_NAME"] == "w1"
     assert "send_message" in srv["enabled_tools"]
     assert "spawn_worker" in srv["enabled_tools"]
+    assert "open_fan" in srv["enabled_tools"]
 
 
 def test_mcp_config_supports_url_only_servers():
     import tomllib
     b = CodexBackend(model="gpt-5.6-sol", cwd="/tmp", mcp_servers={
         "orchestra": {"command": "python", "args": [],
                       "env": {"ORCHESTRA_SESSION_ID": "sess-urlonly"}},
         "remote": {"url": "https://example/sse"},
     })
     data = tomllib.loads((b._prepare_codex_home() / "config.toml").read_text())
     assert data["mcp_servers"]["remote"]["enabled"] is True
     assert data["mcp_servers"]["remote"]["url"] == "https://example/sse"
 
 
 def test_mcp_config_empty_when_no_servers():
     assert CodexBackend(model="gpt-5.6-sol", cwd="/tmp")._mcp_config_args() == []
 
 
 def test_toml_str_escapes():
     assert CodexBackend._toml_str('a"b\\c') == '"a\\"b\\\\c"'


## Later history of the touched files on main (after this commit)

44 later commits touch these paths; the first 40 (oldest first):
42d221b23 2026-08-13 #244: #244: derive Codex tools from FastMCP registry
017ca19c0 2026-08-13 #237: #237: research seamless active-turn restart
b92be6ec2 2026-08-16 #180: restore Codex project trust and context
b604ef449 2026-08-17 #305: #305: serialize managed Codex cold starts
3c037bdb8 2026-08-18 #290: cross-runtime handoff + канареечный скип по продовому предикату (scratch/290, вердикт #328)
e9ad128d0 2026-08-23 Allow Codex managed state to migrate on CLI upgrade
70497a2f3 2026-08-23 Validate Codex 0.147 managed state
48ba54d8e 2026-08-22 цены Sol: промо OpenAI от 22.08.2026, input -20%, output -33%
c3e66f162 2026-08-23 #209: maximize managed Codex context
9c4c5dc00 2026-08-23 #218: refresh Codex context config before idle turns
150e696e0 2026-08-23 #284: #284: make Codex JSONL reader fail-soft and clear lost turns
71374ea56 2026-08-23 #385: #385: research deferred turn control and provenance
9d2627281 2026-08-24 Merge origin/main into main (2026-08-24 sync)
b11ba9be1 2026-08-24 #307: harden Codex oversized resume recovery
db8708aaa 2026-08-24 #319: #319: port bounded Codex cleanup onto current main
e26dcde85 2026-08-24 fix: switch Codex models in place
c885f10e5 2026-08-25 #360: reload MCP tools after Codex resume
2bf3776d3 2026-08-27 Integrate Codex CLI 0.150.1
8ceff6c7a 2026-09-01 #434: instrument Codex reconnect stages
498c0d149 2026-09-03 Orchestra: migrate project state to .orchestra
f8e00522e 2026-09-03 #430: research .orchestra path migration
cd39b74c9 2026-09-03 merge: забрать 38 коммитов контура VPS (#395,#426,#435,#500-#506) в переехавший main
d6155f9d4 2026-09-05 #503: freeze Astra registry regression oracle
3f8bffbf7 2026-09-05 fix: pin Codex 0.153.4 state migration 52 — CLI applied it after the version bump
6968f34f3 2026-09-05 fix: let Codex own native migrations without startup version gates
e7710f4d0 2026-09-05 Merge branch 'fix/codex-native-state-compat' into fix/instruction-guard-ci
e6277e321 2026-09-05 Use configured catalog-bounded Codex window for handoff preflight
ebbff3f53 2026-09-06 #520: свежий Codex-воркер не сканирует все managed homes перед стартом CLI
789e96a9c 2026-09-07 #523, #520: уборка диска 92%→57%, факты в KB про codex-home и чистку временных каталогов
4f87cecca 2026-09-08 #536: WIP #536: preserve writer conflict detection and regression coverage
0eaae5904 2026-09-08 #537: persist CLI identity when publishing surviving pipes
f5713f4df 2026-09-08 Retire legacy review gates and fix adopted Codex writer release
59fe32bc4 2026-09-08 Merge remote-tracking branch 'origin/main' into codex/retire-legacy-review
e6da7e30a 2026-09-10 #537: stop runtime trees with Orchestra and remove live adoption
4c8cb1d70 2026-09-12 каталог: убрать неиспользуемые GPT-5.4 и 5.4 Mini вместе с их устаревшими тарифами
b15940ba5 2026-09-12 V-562: preserve steered messages after failed turns
f197e2958 2026-09-23 V-620: полный счёт токенов и денег по пяти моделям; ставки GPT-6 в таблице Codex
4bc0a84b5 2026-10-05 V-703: #V-703: fix Codex runtime recovery and quota errors
3582eea67 2026-10-05 V-699: WIP #V-699: measure worktree bottleneck and clarify retries
607d566ee 2026-10-05 V-726: #V-726: document blocked Codex CLI upgrade

## Patches of the first 8 later commits, restricted to the touched paths (each capped at 150 lines)

### 42d221b23 #244: #244: derive Codex tools from FastMCP registry

diff --git a/app/backend_codex.py b/app/backend_codex.py
index afc14a3f0..38be247e5 100644
--- a/app/backend_codex.py
+++ b/app/backend_codex.py
@@ -320,21 +320,26 @@ def _carried_base_scalars() -> str:
         if isinstance(data.get(key), (int, float, bool, str))
     ]
     return "\n".join(lines)
 
 
-ORCHESTRA_FULL_MCP_TOOLS = (
-    "spawn_worker", "acquire_test_lock", "release_test_lock", "test_lock_status",
-    "send_message", "list_agents", "list_orchestrators", "get_worker_logs",
-    "compact_worker", "kill_worker", "stop_worker", "rename_worker",
-    "send_file", "update_progress", "change_worker_model", "merge_worker",
-    "switch_worker_branch", "check_conflict", "worker_wip", "report_bug",
-    "update_worker_description", "update_worker_prompt", "get_worker_info",
-    "task_create", "task_update", "task_list", "task_get", "payment_receive",
-    "payment_status", "bg_create", "bg_list", "bg_cancel", "search_memory",
-    "codex_review", "open_fan",
-)
+_ORCHESTRA_MCP_TOOL_EXCLUSIONS: frozenset[str] = frozenset()
+
+
+def _orchestra_full_mcp_tools() -> tuple[str, ...]:
+    """Build Codex's full allowlist from the authoritative FastMCP registry."""
+    from app.mcp_stdio import mcp
+
+    registered = {tool.name for tool in mcp._tool_manager.list_tools()}
+    stale_exclusions = _ORCHESTRA_MCP_TOOL_EXCLUSIONS - registered
+    if stale_exclusions:
+        raise RuntimeError(
+            f"Orchestra MCP exclusions are not registered: {sorted(stale_exclusions)}"
+        )
+    # resolve_merge_operation and send_chart were absent only because their registrations
+    # postdated the deleted static allowlist; neither omission expressed an access policy.
+    return tuple(sorted(registered - _ORCHESTRA_MCP_TOOL_EXCLUSIONS))
 
 
 class CodexProtocolError(RuntimeError):
     """JSON-RPC error returned by Codex app-server."""
 
@@ -1728,11 +1733,11 @@ class CodexBackend(JsonRpcStdioTransport):
                 )
             else:
                 lines.append(f"url = {self._toml_str(str(url))}")
             enabled_tools = cfg.get("enabled_tools")
             if name == "orchestra" and enabled_tools is None:
-                enabled_tools = ORCHESTRA_FULL_MCP_TOOLS
+                enabled_tools = _orchestra_full_mcp_tools()
             if enabled_tools is not None:
                 lines.append(
                     "enabled_tools = ["
                     + ", ".join(self._toml_str(str(t)) for t in enabled_tools)
                     + "]"
diff --git a/docs/tasks/244/codex-review-impl.md b/docs/tasks/244/codex-review-impl.md
index 04879ab07..25b85f7b1 100644
--- a/docs/tasks/244/codex-review-impl.md
+++ b/docs/tasks/244/codex-review-impl.md
@@ -9,5 +9,21 @@ None.
 ## Verdict
 
 APPROVED
 
 `uv run pytest -q tests/test_backend_codex.py` → **78 passed in 7.86s**.
+
+## Round (2026-08-13T06:24:49Z)
+
+## Summary
+
+Prior round had no findings. The replacement establishes FastMCP registration as the single source of truth. The lazy import avoids module-load coupling, sorting makes TOML deterministic, explicit custom `enabled_tools` still bypasses derivation, and fake registration is removed in `finally`.
+
+## Findings
+
+None.
+
+## Verdict
+
+APPROVED
+
+`uv run pytest -q tests/test_backend_codex.py` → **79 passed in 7.02s**.
diff --git a/tests/test_backend_codex.py b/tests/test_backend_codex.py
index 0fbd957d6..8d12c9731 100644
--- a/tests/test_backend_codex.py
+++ b/tests/test_backend_codex.py
@@ -16,15 +16,16 @@ from unittest.mock import AsyncMock, MagicMock
 import pytest
 
 from app.backend_codex import (
     CodexBackend,
     CodexProtocolError,
-    ORCHESTRA_FULL_MCP_TOOLS,
     CODEX_CONTEXT_LIMITS,
     CODEX_TOKEN_PRICES,
     CODEX_REASONING_EFFORTS,
     _codex_cost,
+    _ORCHESTRA_MCP_TOOL_EXCLUSIONS,
+    _orchestra_full_mcp_tools,
     _read_rollout_context,
     _read_rollout_totals,
     _usage_delta,
 )
 from app.runtime_history import (
@@ -242,18 +243,38 @@ def test_effort_passthrough_and_fallback():
 # целиком лежит в `$CODEX_HOME/config.toml` с правами 600. Утверждения ниже переписаны на
 # новый носитель: проверяется то же самое (command/args/env/enabled_tools/url), но там,
 # где оно теперь находится.
 
 
-def test_full_mcp_allowlist_tracks_registered_tools():
+def test_full_mcp_tools_are_derived_from_registration():
+    import tomllib
     from app.mcp_stdio import mcp
 
-    registered = {tool.name for tool in mcp._tool_manager.list_tools()}
-    enabled = set(ORCHESTRA_FULL_MCP_TOOLS)
+    @mcp.tool(name="test_dynamic_codex_tool")
+    def fake_tool() -> str:
+        return "fake"
 
-    assert enabled <= registered
-    assert registered - enabled == {"resolve_merge_operation", "send_chart"}
+    try:
+        assert "test_dynamic_codex_tool" in _orchestra_full_mcp_tools()
+        backend = CodexBackend(
+            model="gpt-5.6-sol",
+            cwd="/tmp",
+            mcp_servers={"orchestra": {"command": "python"}},
+        )
+        config = tomllib.loads(backend._mcp_servers_toml())
+        assert "test_dynamic_codex_tool" in (
+            config["mcp_servers"]["orchestra"]["enabled_tools"]
+        )
+    finally:
+        mcp.remove_tool("test_dynamic_codex_tool")
+
+
+def test_full_mcp_exclusions_are_registered_tools():
+    from app.mcp_stdio import mcp
+
+    registered = {tool.name for tool in mcp._tool_manager.list_tools()}
+    assert _ORCHESTRA_MCP_TOOL_EXCLUSIONS <= registered
 
 def test_mcp_config_rendered_into_config_toml_not_argv():
     import tomllib
     b = CodexBackend(model="gpt-5.6-sol", cwd="/tmp", mcp_servers={
         "orchestra": {
### 017ca19c0 #237: #237: research seamless active-turn restart

diff --git a/app/backend_codex.py b/app/backend_codex.py
index 38be247e5..ec193f266 100644
--- a/app/backend_codex.py
+++ b/app/backend_codex.py
@@ -504,20 +504,50 @@ class CodexBackend(JsonRpcStdioTransport):
         else:
             self._scope_unit = None
             self._scope_env = {}
             cmd = codex_cmd
 
+        if scope_ok:
+            # A scoped launch puts `systemd-run` between us and the CLI, so `_proc.pid` is the
+            # launcher, not the app-server. Handing those pipes over would advertise a survivor
+            # we could not identify later, so this path keeps PIPE and stays non-adoptable —
+            # the same behaviour as before #237, but said out loud instead of silently.
+            logger.warning(
+                "Codex scope launch: seamless handover is unavailable for this session "
+                "(pid identity belongs to systemd-run, not to the app-server)"
+            )
+
+        child_stdin = child_stdout = our_stdin = our_stdout = None
         try:
+            if scope_ok:
+                stdio = {"stdin": asyncio.subprocess.PIPE,
+                         "stdout": asyncio.subprocess.PIPE}
+            else:
+                child_stdin, child_stdout, our_stdin, our_stdout = self.new_child_pipes()
+                stdio = {"stdin": child_stdin, "stdout": child_stdout}
             self._proc = await asyncio.create_subprocess_exec(
                 *cmd,
-                stdin=asyncio.subprocess.PIPE,
-                stdout=asyncio.subprocess.PIPE,
+                **stdio,
                 stderr=asyncio.subprocess.PIPE,
                 env=env,
                 cwd=self.cwd,
                 limit=16 * 1024 * 1024,
             )
+            if our_stdin is not None:
+                # Ownership passes at the CALL, not on success: half-attached, one of these
+                # already belongs to a live transport and the cleanup below cannot tell which.
+                attach_in, attach_out = our_stdin, our_stdout
+                our_stdin = our_stdout = None
+                await self.attach_owned_pipes(attach_in, attach_out,
+                                              limit=16 * 1024 * 1024)
+                # Only now drop our copies of the CLI's own ends: the child has had them
+                # since the spawn, and keeping ours open would stop it from ever seeing EOF.
+                # Closing them AFTER wiring also means a failed wiring leaves them in hand,
+                # so the CLI dies on EOF instead of hanging on a pipe nobody reads.
+                os.close(child_stdin)
+                os.close(child_stdout)
+                child_stdin = child_stdout = None
             self._reader_task = asyncio.create_task(self._read_stdout())
             self._stderr_task = asyncio.create_task(self._drain_stderr())
             initialize_params = {
                 "clientInfo": {
                     "name": "orchestra",
@@ -565,10 +595,19 @@ class CodexBackend(JsonRpcStdioTransport):
             self._thread_id = thread_id
             self._history_import = None
             self._rollout_path = None
             self._teardown_error = None
         except BaseException:
+            # Raw descriptors that never reached a transport are ours alone to close; the
+            # ones already handed to `attach_owned_pipes` are cleared above and closed by
+            # `disconnect()`, so nothing is closed twice.
+            for fd in (child_stdin, child_stdout, our_stdin, our_stdout):
+                if fd is not None:
+                    try:
+                        os.close(fd)
+                    except OSError:
+                        pass
             await self.disconnect()
             raise
 
     async def send(self, message: str) -> None:
         if self._teardown_error or not self.is_alive:
@@ -842,10 +881,11 @@ class CodexBackend(JsonRpcStdioTransport):
         self._pending_requests.clear()
         if self._compact_future and not self._compact_future.done():
             self._compact_future.set_exception(
                 RuntimeError("Codex app-server disconnected during context compact")
             )
+        await self.teardown_owned_pipes()
         self._proc = None
         self._scope_unit = None
         self._reader_task = None
         self._stderr_task = None
         self._active_turn_id = None
@@ -924,37 +964,37 @@ class CodexBackend(JsonRpcStdioTransport):
         except asyncio.CancelledError:
             return
         except Exception as exc:
             logger.exception("Codex app-server reader failed: %s", exc)
         finally:
-            # An ADOPTED transport has no Process object at all (#230 T2): the CLI is not our
-            # child. Its exit is then visible only as EOF on the pipe, which is why the reason
-            # is worded without a code instead of pretending we can wait() on someone else.
-            proc = self._proc
-            returncode = await proc.wait() if proc is not None else None
-            error = RuntimeError(
-                f"Codex app-server exited with code {returncode}" if proc is not None
-                else "Codex app-server closed the adopted pipe (no process: adopted transport)"
-            )
-            # Gated by the SAME flag as the notification below. A handover cancels this reader
-            # deliberately; completing pending futures with "app-server exited" would be a lie
-            # about a process that is still alive. The window is narrow (the caller refuses the
-            # handover while requests are in flight) but a late request lands right here.
+            # ONE gate over the whole "the process died" story. A handover cancels this reader
+            # on a process that is very much alive, so none of it may run: not the pending
+            # futures, not the notification, and above all not `proc.wait()` — waiting for a
+            # live CLI to exit stalled every handover until the shutdown timeout (#237 T1).
             if not self._handover_quiescing:
+                # An ADOPTED transport has no Process object at all (#230 T2): the CLI is not
+                # our child. Its exit is then visible only as EOF on the pipe, which is why the
+                # reason is worded without a code instead of pretending we can wait() on it.
+                proc = self._proc
+                returncode = await proc.wait() if proc is not None else None
+                error = RuntimeError(
+                    f"Codex app-server exited with code {returncode}" if proc is not None
+                    else "Codex app-server closed the adopted pipe (no process: adopted transport)"
+                )
                 for future in self._pending_requests.values():
                     if not future.done():
                         future.set_exception(error)
                 if self._compact_future and not self._compact_future.done():
                     self._compact_future.set_exception(error)
-            if not self._disconnecting and not self._handover_quiescing:
-                await self._notifications.put({
-                    "method": "_process/exited",
-                    "params": {
-                        "returncode": returncode,
-                        "stderr": self._last_stderr,
-                    },
-                })
+                if not self._disconnecting:
+                    await self._notifications.put({
+                        "method": "_process/exited",
+                        "params": {
+                            "returncode": returncode,
+                            "stderr": self._last_stderr,
+                        },
+                    })
 
     def _record_token_usage(self, params: dict) -> None:
         usage = params.get("tokenUsage") or {}
         total = usage.get("total") or {}
         last = usage.get("last") or {}
### b92be6ec2 #180: restore Codex project trust and context

diff --git a/app/backend_codex.py b/app/backend_codex.py
index ec193f266..fdafd7c83 100644
--- a/app/backend_codex.py
+++ b/app/backend_codex.py
@@ -1791,10 +1791,24 @@ class CodexBackend(JsonRpcStdioTransport):
                     for k, v in env.items()
                 )
             blocks.append("\n".join(lines))
         return "\n\n".join(blocks)
 
+    def _trusted_project_toml(self) -> str:
+        """Trust only this backend's canonical cwd in its private CODEX_HOME.
+
+        Managed Codex runs are created for an Orchestra-owned project/worktree.  Without
+        this entry Codex deliberately disables that checkout's project-local `.codex`
+        config, hooks, and rules.  Copying the base config's whole `[projects]` table is
+        still forbidden: it would grant one agent trust in unrelated checkouts.
+        """
+        project = str(Path(self.cwd).expanduser().resolve())
+        return (
+            f"[projects.{self._toml_key(project)}]\n"
+            'trust_level = "trusted"'
+        )
+
     def _prepare_codex_home(self) -> Path:
         """Собрать приватный `CODEX_HOME` этого агента и вернуть путь.
 
         СОБРАТЬ, а не скопировать базовый: копия затащила бы глобальные MCP-серверы
         (со своими токенами) и `[projects.*]` в конфиг каждого воркера, в обход отбора
@@ -1857,10 +1871,11 @@ class CodexBackend(JsonRpcStdioTransport):
 
         parts = []
         carried = _carried_base_scalars()
         if carried:
             parts.append(carried)
+        parts.append(self._trusted_project_toml())
         servers = self._mcp_servers_toml()
         if servers:
             parts.append(servers)
         # Через временный файл + os.replace: коннект, попавший на середину записи,
         # прочитал бы ОБРЕЗАННЫЙ config.toml и стартовал без части серверов — тихий отказ.
### b604ef449 #305: #305: serialize managed Codex cold starts

diff --git a/app/backend_codex.py b/app/backend_codex.py
index fdafd7c83..dc13a3961 100644
--- a/app/backend_codex.py
+++ b/app/backend_codex.py
@@ -1,26 +1,34 @@
 """CodexBackend — wraps Codex CLI subprocess for agent sessions."""
 
 import asyncio
+import fcntl
+import hashlib
 import json
 import logging
 import os
 import re
 import shutil
+import sqlite3
 import sys
 import tomllib
 import uuid
+import weakref
+from contextlib import asynccontextmanager
+from dataclasses import dataclass
+from datetime import datetime, timezone
 from pathlib import Path
 from typing import AsyncIterator, Optional
 
 from app.backend_jsonrpc import JsonRpcStdioTransport, bounded_tool_arguments
 from app.events import AgentEvent
 from app.runtime_history import (
     CODEX_CLI_HISTORY_VERSION,
     HISTORICAL_TOOL_INSTRUCTION,
     CodexHistoryImport,
     NativeHistoryUnsupported,
+    sanitize_sensitive_text,
 )
 from app.usage_contract import AggregateUsage, TurnUsage, current_context
 
 logger = logging.getLogger(__name__)
 
@@ -275,10 +283,61 @@ def _tool_arguments_json(arguments) -> str:
     )
 
 
 _SAFE_HOME_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_\-]{0,63}$")
 _CODEX_HOME_ROOT = Path.home() / ".orchestra" / "codex-home"
+_MANAGED_HOME_LOCKS: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()
+_CODEX_STATE_MIGRATIONS_BY_CLI = {
+    # Captured from a read-only Codex 0.146.0 state DB. Checksums are SQLx's
+    # provider-owned migration identity; a mutable base DB is not schema authority.
+    CODEX_CLI_HISTORY_VERSION: (
+        (1, bytes.fromhex("627ef19164c9bb298a0cd99945981c9b7bda3d9e6cf12eb35145e3b1d3bf7cf8740f0dbaa0b475185fc2993397078049")),
+        (2, bytes.fromhex("521b72cbc04c7d03b1e4aef8dc0fdee672f1f7f5881385a55a0e937e4ebe87a3f67bca4d3f6b59afbc9a7ca723c82856")),
+        (3, bytes.fromhex("e58a2862bdb66d3274e60144a26dc9d68bbefff834cd29b82b740f38fcf95862934f412665d985715167839e8f0eb377")),
+        (4, bytes.fromhex("8adc251366e4c7e5ea78b620ac71f4c4bdfb8f048bf9f2fd7204226cfba54c8e83fc9d83fc1ec334bc683bb7f6d0d8a8")),
+        (5, bytes.fromhex("1ac64f85e083e5b49b974bf498fc39c630f0032057fb4bf4cb31708619fac5a80189f261cf3e38dafd92dc406e73c220")),
+        (6, bytes.fromhex("a203fc4b597e1420bffdc4e00e214798b21cf7fc921d8bd6f089c75248fb6a4b4942c97a1f8e0271eca8cf3b3e5e7a80")),
+        (7, bytes.fromhex("7e35a464df6d4c82694de50865ba3fe9104f9e1385a33be7d633ab4b8d6cf60b7f369fe083d31251fd77b75fa2d61f82")),
+        (8, bytes.fromhex("aa3f287f7a448554e7af01f259f0871ce90ace1a7d4b8ebbd74c87ae57c3e21119f7eec8b9c2e9f4a9e76e63a0f0b60a")),
+        (9, bytes.fromhex("8b469360777e6dd6c21d3f0eb93481251846b0a50e0a44eb0dbee4a0a32b7206768a5d83a5fcec30c6fd2e43d755ff1b")),
+        (10, bytes.fromhex("8adaf1365f8e5deeba68bdeee9fd83b094a87bdab364d95ab5c714f7b8bd95dc3b38576871470312154c9d41e8f10f93")),
+        (11, bytes.fromhex("31ececbd07f04452d0dc5127d824ed183056b9900a31aa739387a4aef232016d975110829814841fb6bf3fd23634b799")),
+        (12, bytes.fromhex("0012a213ed25f2cf806c2530c487ebb00b4f102f5960d1a852154a0f77d25c9e9f7df29550faeb30ebaff15a26c7d604")),
+        (13, bytes.fromhex("05526a0900a8430523a9a05932ea61302fce20782b245498565c1b9a2dfd10cf5c49932089b496ae23af44f6c5f76af4")),
+        (14, bytes.fromhex("4d2fbb2442c5c5c7c47b4254b5b8dc2c52129f65c4a952a79f1ec5c40fb07483326429ce5acdbd372bc9262352cb6277")),
+        (15, bytes.fromhex("0eece6db59c948faa6608526af440a9f53f5a982d27f3e866cd9f1401c2e59bc61f8381b5a1c9744acb232f50db493e5")),
+        (16, bytes.fromhex("4768f743e981293735c6e07b0282ec8ace98af720059d68555b17979d28c94b0c893a97a950d5e32758bc6d92d8fe6ff")),
+        (17, bytes.fromhex("4cbdb2edfebf6040858ffc193cffa36e6b3fbf508f8418ad073081bbfcf59d53d423b6eb4c0ded206ab4d4c1a0efed94")),
+        (18, bytes.fromhex("a4363003bc44f0a4ae1eed53b536b7175f97863ea6881a059dc6642e70e2921576204697cec2345f560e65ff7fbf4455")),
+        (19, bytes.fromhex("3884c02f080f0184e92b620f870dfbb840a8ec5dfce2fe6455dd8197fcd27d7dd86e63ad6ec7c4091a1161d9ed199f8d")),
+        (20, bytes.fromhex("07673f4859f740134569ab9606760d8173ed6df92da47c86fbd0ceeb333e18ab7ac91d525ab8c11503c42164fd4167ae")),
+        (21, bytes.fromhex("ea1aebe4f5a1d56c8effcc15f705c272275dd8adfeb01bc97d3f7b283474a3b8c2b0c8c69de55786e8bda17cae6f4de7")),
+        (22, bytes.fromhex("160fe01b757dd06f9573b9030952d021f2b148732bea5fc5f5ae09e9227f3f83ca676695edaf8502669fcb546119dc94")),
+        (23, bytes.fromhex("e6c748a9a18286e4c773ffe0dad659f16fb7e5b7b032235815991c405f2d32c068f3edde920d0fcf589b687bffcfee2e")),
+        (24, bytes.fromhex("e92aa526b1f36e26f6221c04a671f07b27de2e7a5112d93a8c3af816a87846e7804d5fbad689e61cf4ec91fd79d3bd8a")),
+        (25, bytes.fromhex("d6fb51d79941b93c3278fe2a8a0c6fa882407b7b716e32d72329f0b7b60c181a42f49e56cd552315efb0402a111ede12")),
+        (26, bytes.fromhex("6c62a325d3b9ca8e424eacb9e3890d8d9de57c3725e2d1fa30c3743ae779fca2969387174359dfb26e4920791ae7e831")),
+        (27, bytes.fromhex("d84dca6a039e004c0c7d06c5a16c2ccc363137537f3dd9898f50bb013ce9067140761b87d58ca742d769d35976863fc3")),
+        (28, bytes.fromhex("ef44adaa291e40dfe6b74e3cd259711adae13f01c5594b177d08e2d2041a67ed3813feecf049662aaed0f636bd3f4ac3")),
+        (29, bytes.fromhex("e9ec76f97dbf41ce4949de324a2a26538c2025c0ac4f272b77a852970fb14b7ec970d6978a765f91ae171dce9c0e4149")),
+        (30, bytes.fromhex("80c1cdacd4520b42b18b960164912685591a7ee041645f35609a2ee2792eb474b7b0b758366556982d8cde2acb583672")),
+        (31, bytes.fromhex("943675a9b3dc92d0b2731ae7d2fe324ff1a40b6366b9d5d8b4cb47ca885c08beb6ebb1d776a5a47c878b4094dde70ea0")),
+        (32, bytes.fromhex("3c01d615c5e3aba0fd858b7168e73881598d7d33a0ecc41527bdf6595a199d1aec2ff9f3b3000a57241c500d81b34259")),
+        (33, bytes.fromhex("4904aae354e3d8ce32ac21d2ae579fd708446ae1dfb2649fc9dd22dc9279b91a2bbb02e6f01b3e0abd1088177bf2f030")),
+        (34, bytes.fromhex("d6fea739c76ebdef35a23f06e54efb5904d7987fb6b663db1ebc98eb9b192305f454932bfbaa2231aedca6209903a5f3")),
+        (35, bytes.fromhex("d7b56acb07c96858bdc7ca4c53db51eb71c6a19ef2c524ff68c2660a6fe0d23211a6d39cb905f01c42ffb7c8ee913bbc")),
+        (36, bytes.fromhex("6381f7bb4c36be41c6106b8523ea6c68f5a00273a5522155b7b84bad26d152436f3375df7097ce3abf2421aec32641ed")),
+        (37, bytes.fromhex("f6a5ab0db36bb9e45ab5285b56090fb453df0a4d4d8d62eace234f0b557f4203c6c455fc67bd7d6e72623c3979ec9405")),
+        (38, bytes.fromhex("e7778522cbe529f5e2ba179b502aee8e5c21272ad820e672ab0a565f7edc9bd0f29171ccf9815c0acc0f89eae0a2b1fc")),
+        (39, bytes.fromhex("c217b3d14c08c23603f485af11452ee2b68f65fa8dbaf215f33f53b608c092be8738de3f63d6a38f120edea5af247c17")),
+        (40, bytes.fromhex("a7a99674f90a43184e43d66595c4f1da50ae8715a5bfcb1579a2b7b10668335d7f7ab6b6f2d7a7a379272773d803a914")),
+        (41, bytes.fromhex("0dc734dbe4cbcc5ad5a8bbc2fdc1cf770ddea3cb53eb36c55a4da6fa2e8be4cc8e68672f43ac953e727e415e45c50a78")),
+        (42, bytes.fromhex("cfdc4fd47328d1b67c0c7555125de4fb4add5b3b57fd31ac1987e4d8b0c99b1f5418db9ee7ec2158aed8a2e3dfcfd636")),
+        (43, bytes.fromhex("605128e722bd2521c7e979e9961c16706435e442b3e3a8efa36f6b16c42e3833090906d9a62fde097a109b78e29da830")),
+        (44, bytes.fromhex("5d29223bd1cafe456a4af992a545e8ec420b71331eb12a7427e26512b8a44117d9445b83562f095b3a5a0f11c4f091d2")),
+    ),
+}
 # Из базового конфига переносим ТОЛЬКО это. Расширять список осознанно: каждая строка
 # здесь — копия, которая начинает расходиться с оригиналом.
 _CARRIED_BASE_KEYS = ("project_doc_max_bytes",)
 
 
@@ -302,10 +361,318 @@ def _write_private(path: Path, text: str) -> None:
 
 def _base_codex_home() -> Path:
     return Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))).expanduser()
 
 
+@dataclass(frozen=True)
+class _CodexStateInfo:
+    status: str
+    last_success_at: int | None
+    migrations: tuple[tuple[int, bytes], ...]
+    thread_count: int
+
+
+def _managed_home_async_lock(home: Path) -> asyncio.Lock:
+    loop = asyncio.get_running_loop()
+    locks = _MANAGED_HOME_LOCKS.setdefault(loop, {})
+    return locks.setdefault(home.resolve(), asyncio.Lock())
+
+
+def _acquire_managed_home_file_lock(home: Path) -> int:
+    lock_dir = home.parent / ".locks"
+    lock_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
+    os.chmod(lock_dir, 0o700)
+    digest = hashlib.sha256(os.fsencode(str(home.resolve()))).hexdigest()[:24]
+    lock_path = lock_dir / f"{digest}.lock"
+    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_CLOEXEC", 0)
+    flags |= getattr(os, "O_NOFOLLOW", 0)
+    fd = os.open(lock_path, flags, 0o600)
+    try:
+        os.fchmod(fd, 0o600)
+        fcntl.flock(fd, fcntl.LOCK_EX)
+        return fd
+    except BaseException:
+        os.close(fd)
+        raise
+
+
+def _release_managed_home_file_lock(fd: int) -> None:
+    try:
+        fcntl.flock(fd, fcntl.LOCK_UN)
+    finally:
+        os.close(fd)
+
+
+async def _acquire_managed_home_file_lock_async(home: Path) -> int:
+    task = asyncio.create_task(asyncio.to_thread(_acquire_managed_home_file_lock, home))
### 3c037bdb8 #290: cross-runtime handoff + канареечный скип по продовому предикату (scratch/290, вердикт #328)

diff --git a/app/backend_codex.py b/app/backend_codex.py
index dc13a3961..aaa3a078c 100644
--- a/app/backend_codex.py
+++ b/app/backend_codex.py
@@ -25,10 +25,11 @@ from app.runtime_history import (
     CODEX_CLI_HISTORY_VERSION,
     HISTORICAL_TOOL_INSTRUCTION,
     CodexHistoryImport,
     NativeHistoryUnsupported,
     sanitize_sensitive_text,
+    build_model_visible_manifest,
 )
 from app.usage_contract import AggregateUsage, TurnUsage, current_context
 
 logger = logging.getLogger(__name__)
 
@@ -729,11 +730,12 @@ class CodexBackend(JsonRpcStdioTransport):
                  resume_thread_id: str | None = None,
                  mcp_env: dict[str, str] | None = None,
                  mcp_servers: dict | None = None,
                  reasoning_effort: str = "high",
                  is_orchestrator: bool = False,
-                 history_import: object | None = None):
+                 history_import: object | None = None,
+                 validation_profile: bool = False):
         self.model = model
         self.cwd = cwd
         self.system_prompt = system_prompt
         self._thread_id: str | None = resume_thread_id
         self._mcp_env: dict[str, str] = mcp_env or {}
@@ -743,10 +745,11 @@ class CodexBackend(JsonRpcStdioTransport):
         self._codex_home: Path | None = None
         self._is_orchestrator = is_orchestrator
         if history_import is not None and not isinstance(history_import, CodexHistoryImport):
             raise TypeError("history_import must be CodexHistoryImport")
         self._history_import = history_import
+        self._validation_profile = validation_profile
         self.reasoning_effort = (
             reasoning_effort if reasoning_effort in CODEX_REASONING_EFFORTS else "high"
         )
         self._proc: Optional[asyncio.subprocess.Process] = None
         self._reader_task: Optional[asyncio.Task] = None
@@ -778,10 +781,22 @@ class CodexBackend(JsonRpcStdioTransport):
 
     @property
     def session_id(self) -> Optional[str]:
         return self._thread_id
 
+    def build_handoff_manifest(self, prepared, *, validation_profile: bool):
+        return build_model_visible_manifest(
+            runtime="codex",
+            model=self.model,
+            effective_window=self._model_context_window,
+            system_prompt=self.system_prompt,
+            prepared=prepared,
+            validation_profile=validation_profile,
+            project_docs=getattr(prepared, "project_docs", ()),
+            mcp_servers=self._mcp_servers,
+        )
+
     @property
     def active_turn_id(self) -> Optional[str]:
         """The turn the adopted bytes belong to (#230 T4)."""
         return self._active_turn_id
 
### e9ad128d0 Allow Codex managed state to migrate on CLI upgrade

diff --git a/app/backend_codex.py b/app/backend_codex.py
index aaa3a078c..73da962cd 100644
--- a/app/backend_codex.py
+++ b/app/backend_codex.py
@@ -884,14 +884,20 @@ class CodexBackend(JsonRpcStdioTransport):
             return
         async with _managed_home_lock(home):
             await _run_home_io(self._prepare_codex_home)
             cli_version = await self._managed_state_cli_version()
             if cli_version != CODEX_CLI_HISTORY_VERSION:
-                raise RuntimeError(
-                    "managed Codex state is validated only for CLI "
-                    f"{CODEX_CLI_HISTORY_VERSION}, got {cli_version or 'unknown'}"
+                # The provider owns forward migrations.  Blocking before the app-server
+                # starts strands every fresh worker after a CLI upgrade; let that binary
+                # migrate its own managed state under the per-home lock.
+                logger.warning(
+                    "skipping pinned managed Codex state seed for CLI %s; "
+                    "provider will migrate state on startup",
+                    cli_version or "unknown",
                 )
+                await self._connect_unlocked()
+                return
             if await _run_home_io(
                 _managed_codex_state_needs_seed,
                 home,
                 cli_version,
             ):
### 70497a2f3 Validate Codex 0.147 managed state

diff --git a/app/backend_codex.py b/app/backend_codex.py
index 73da962cd..051b4ec5e 100644
--- a/app/backend_codex.py
+++ b/app/backend_codex.py
@@ -286,11 +286,11 @@ def _tool_arguments_json(arguments) -> str:
 
 _SAFE_HOME_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_\-]{0,63}$")
 _CODEX_HOME_ROOT = Path.home() / ".orchestra" / "codex-home"
 _MANAGED_HOME_LOCKS: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()
 _CODEX_STATE_MIGRATIONS_BY_CLI = {
-    # Captured from a read-only Codex 0.146.0 state DB. Checksums are SQLx's
+    # Captured from a fresh Codex 0.147.0 app-server state DB. Checksums are SQLx's
     # provider-owned migration identity; a mutable base DB is not schema authority.
     CODEX_CLI_HISTORY_VERSION: (
         (1, bytes.fromhex("627ef19164c9bb298a0cd99945981c9b7bda3d9e6cf12eb35145e3b1d3bf7cf8740f0dbaa0b475185fc2993397078049")),
         (2, bytes.fromhex("521b72cbc04c7d03b1e4aef8dc0fdee672f1f7f5881385a55a0e937e4ebe87a3f67bca4d3f6b59afbc9a7ca723c82856")),
         (3, bytes.fromhex("e58a2862bdb66d3274e60144a26dc9d68bbefff834cd29b82b740f38fcf95862934f412665d985715167839e8f0eb377")),
@@ -333,10 +333,12 @@ _CODEX_STATE_MIGRATIONS_BY_CLI = {
         (40, bytes.fromhex("a7a99674f90a43184e43d66595c4f1da50ae8715a5bfcb1579a2b7b10668335d7f7ab6b6f2d7a7a379272773d803a914")),
         (41, bytes.fromhex("0dc734dbe4cbcc5ad5a8bbc2fdc1cf770ddea3cb53eb36c55a4da6fa2e8be4cc8e68672f43ac953e727e415e45c50a78")),
         (42, bytes.fromhex("cfdc4fd47328d1b67c0c7555125de4fb4add5b3b57fd31ac1987e4d8b0c99b1f5418db9ee7ec2158aed8a2e3dfcfd636")),
         (43, bytes.fromhex("605128e722bd2521c7e979e9961c16706435e442b3e3a8efa36f6b16c42e3833090906d9a62fde097a109b78e29da830")),
         (44, bytes.fromhex("5d29223bd1cafe456a4af992a545e8ec420b71331eb12a7427e26512b8a44117d9445b83562f095b3a5a0f11c4f091d2")),
+        (45, bytes.fromhex("a7fadc8caea8b6abeb108f588a91b8e5d1c9e2645ce990f2251b9f0234e6e53d78fc854f1c88c7217cc143016539d691")),
+        (46, bytes.fromhex("63addf6115c3fb1a22a886108ce6ebff5cd8408f219606dc2f8396836418e56d5be2a6de7b0df877119a28096ee67d22")),
     ),
 }
 # Из базового конфига переносим ТОЛЬКО это. Расширять список осознанно: каждая строка
 # здесь — копия, которая начинает расходиться с оригиналом.
 _CARRIED_BASE_KEYS = ("project_doc_max_bytes",)
@@ -550,34 +552,31 @@ def _backup_codex_state(source: Path, destination: Path) -> None:
     os.chmod(destination, 0o600)
 
 
 def _select_managed_codex_state_source(target_home: Path, cli_version: str) -> Path:
     base = _base_codex_home() / "state_5.sqlite"
-    base_info = _inspect_codex_state(base, check_integrity=True)
-    _validate_codex_state_migrations(base_info, cli_version)
-    if base_info.status != "complete" or base_info.last_success_at is None:
+    candidates: list[tuple[int, int, Path]] = []
+    sources = [base]
+    if _CODEX_HOME_ROOT.is_dir():
+        sources.extend(
+            candidate
+            for candidate in _CODEX_HOME_ROOT.glob("*/state_5.sqlite")
+            if candidate.parent != target_home
+        )
+    for candidate in sources:
+        try:
+            info = _inspect_codex_state(candidate, check_integrity=True)
+            _validate_codex_state_migrations(info, cli_version)
+        except RuntimeError as exc:
+            logger.warning("ignoring invalid Codex state source %s: %s", candidate, exc)
+            continue
+        if info.status == "complete" and info.last_success_at is not None:
+            candidates.append((info.thread_count, info.last_success_at, candidate))
+    if not candidates:
         raise RuntimeError(
-            "refusing incomplete base Codex state source: "
-            f"status={base_info.status!r}, "
-            f"last_success_at={base_info.last_success_at!r}"
+            f"no healthy Codex state source validated for CLI {cli_version}"
         )
-    candidates = [(base_info.thread_count, base_info.last_success_at, base)]
-    if _CODEX_HOME_ROOT.is_dir():
-        for candidate in _CODEX_HOME_ROOT.glob("*/state_5.sqlite"):
-            if candidate.parent == target_home:
-                continue
-            try:
-                info = _inspect_codex_state(candidate, check_integrity=False)
-            except RuntimeError as exc:
-                logger.warning("ignoring invalid managed Codex state %s: %s", candidate, exc)
-                continue
-            if (
-                info.status == "complete"
-                and info.last_success_at is not None
-                and info.migrations == base_info.migrations
-            ):
-                candidates.append((info.thread_count, info.last_success_at, candidate))
     return max(candidates, key=lambda item: (item[0], item[1], str(item[2])))[2]
 
 
 def _prepare_managed_codex_state(
     home: Path,
diff --git a/tests/test_backend_codex.py b/tests/test_backend_codex.py
index d197f779a..bba587b51 100644
--- a/tests/test_backend_codex.py
+++ b/tests/test_backend_codex.py
@@ -584,19 +584,19 @@ async def test_history_connect_fails_before_spawn_on_version_mismatch(monkeypatc
         history_import=_history_import(),
     )
     monkeypatch.setattr(
         module,
         "_run_process",
-        AsyncMock(return_value=(0, "codex-cli 0.147.0", "")),
+        AsyncMock(return_value=(0, "codex-cli 0.148.0", "")),
     )
     spawn = AsyncMock(return_value=_FakeProcess())
     monkeypatch.setattr(module.asyncio, "create_subprocess_exec", spawn)
     backend._read_stdout = AsyncMock()
     backend._drain_stderr = AsyncMock()
     backend._request = AsyncMock(side_effect=AssertionError("app-server started"))
 
-    with pytest.raises(NativeHistoryUnsupported, match="0.147.0"):
+    with pytest.raises(NativeHistoryUnsupported, match="0.148.0"):
         await backend.connect()
 
     spawn.assert_not_awaited()
     assert backend.has_owned_processes is False
 
### 48ba54d8e цены Sol: промо OpenAI от 22.08.2026, input -20%, output -33%

diff --git a/app/backend_codex.py b/app/backend_codex.py
index 051b4ec5e..0a361e0c7 100644
--- a/app/backend_codex.py
+++ b/app/backend_codex.py
@@ -56,11 +56,14 @@ CODEX_CONTEXT_LIMITS = {
 # Terra and Luna list prices dropped below what we had (Luna 5×: was 1.0/6.0) — rows already
 # in `turn_usage` keep the price of their own day and are deliberately not rewritten.
 # The long-context tier is per request, while Codex's measured 258,400-token request window
 # is below its 272K threshold. Spark is listed explicitly but has no published final price.
 CODEX_TOKEN_PRICES = {
-    "gpt-5.6-sol":   {"input": 5.0, "cached": 0.5, "write": 6.25, "output": 30.0},
+    # Promotional pricing from 22.08.2026, published "at least through November 21, 2026":
+    # input −20%, output −33%. Verified in the source table, not from the announcement.
+    # Rows already in `turn_usage` keep their own day's price, as with Terra/Luna below.
+    "gpt-5.6-sol":   {"input": 4.0, "cached": 0.4, "write": 5.0, "output": 20.0},
     "gpt-5.6-terra": {"input": 2.0, "cached": 0.2, "write": 2.5, "output": 12.0},
     "gpt-5.6-luna":  {"input": 0.2, "cached": 0.02, "write": 0.25, "output": 1.2},
     "gpt-5.5":      {"input": 5.0, "cached": 0.5, "output": 30.0},
     "gpt-5.4":      {"input": 2.5, "cached": 0.25, "output": 15.0},
     "gpt-5.4-mini": {"input": 0.3, "cached": 0.03, "output": 1.25},
diff --git a/tests/test_backend_codex.py b/tests/test_backend_codex.py
index bba587b51..1efc35b69 100644
--- a/tests/test_backend_codex.py
+++ b/tests/test_backend_codex.py
@@ -91,11 +91,11 @@ def test_spark_context_limit_matches_local_codex_metadata():
 
 
 def test_gpt56_prices_present():
     # Standard-tier list prices, https://platform.openai.com/docs/pricing, verified 11.08.2026.
     assert CODEX_TOKEN_PRICES["gpt-5.6-sol"] == {
-        "input": 5.0, "cached": 0.5, "write": 6.25, "output": 30.0,
+        "input": 4.0, "cached": 0.4, "write": 5.0, "output": 20.0,
     }
     assert CODEX_TOKEN_PRICES["gpt-5.6-terra"] == {
         "input": 2.0, "cached": 0.2, "write": 2.5, "output": 12.0,
     }
     assert CODEX_TOKEN_PRICES["gpt-5.6-luna"] == {
@@ -119,21 +119,21 @@ def test_legacy_gpt_models_unchanged():
 
 def test_sol_price_and_ctx_not_zero_fallback():
     # Sol has an explicit runtime limit and price rather than relying on fallbacks.
     b = CodexBackend(model="gpt-5.6-sol", cwd="/tmp")
     assert CODEX_CONTEXT_LIMITS[b.model] == 258400
-    assert CODEX_TOKEN_PRICES[b.model]["output"] == 30.0
+    assert CODEX_TOKEN_PRICES[b.model]["output"] == 20.0
 
 
 def test_codex_cost_applies_cached_input_discount():
-    # 100 fresh × $5/M + 900 cached × $0.5/M + 10 output × $30/M.
-    assert _codex_cost("gpt-5.6-sol", 1000, 900, 0, 10) == pytest.approx(0.00125)
+    # 100 fresh × $4/M + 900 cached × $0.4/M + 10 output × $20/M.
+    assert _codex_cost("gpt-5.6-sol", 1000, 900, 0, 10) == pytest.approx(0.00096)
 
 
 def test_codex_cost_charges_cache_writes_once_at_their_own_rate():
-    # 100 fresh × $5/M + 700 cached × $0.5/M + 200 writes × $6.25/M + output.
-    assert _codex_cost("gpt-5.6-sol", 1000, 700, 200, 10) == pytest.approx(0.0024)
+    # 100 fresh × $4/M + 700 cached × $0.4/M + 200 writes × $5/M + output.
+    assert _codex_cost("gpt-5.6-sol", 1000, 700, 200, 10) == pytest.approx(0.00188)
 
 
 def test_spark_cost_fails_loud_without_a_published_price():
     assert CODEX_TOKEN_PRICES["gpt-5.3-codex-spark"] is None
     with pytest.raises(ValueError, match="No published token price"):
@@ -1323,11 +1323,11 @@ def test_turn_usage_keeps_codex_delta_and_last_call_context_distinct():
         "status": "completed",
     })[-1]
 
     assert end.usage.aggregate.input_tokens == 60_000
     assert end.usage.aggregate.cache_create_tokens == 3_000
-    assert end.metadata["cost_usd"] == pytest.approx(0.12375)
+    assert end.metadata["cost_usd"] == pytest.approx(0.093)
     assert isinstance(end.usage.current, KnownContext)
     assert end.metadata["context_tokens"] == 33_124
     assert end.metadata["context_known"] is True
 
 