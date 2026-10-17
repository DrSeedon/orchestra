# Context for item-27

## Diff reviewed (-U20, capped at 1500 lines)

diff --git a/.mcp.json b/.mcp.json
deleted file mode 100644
index 66f46a47c..000000000
--- a/.mcp.json
+++ /dev/null
@@ -1,16 +0,0 @@
-{
-  "mcpServers": {
-    "orchestra": {
-      "type": "stdio",
-      "command": "/mnt/data/Projects/Python/orchestra/.venv/bin/python",
-      "args": ["-m", "app.mcp_stdio"],
-      "env": {
-        "PYTHONPATH": "/mnt/data/Projects/Python/orchestra",
-        "ORCHESTRA_URL": "http://127.0.0.1:8888",
-        "ORCHESTRA_SCOPE": "/mnt/data/Projects/Python/test-project",
-        "ORCHESTRA_ROLE": "claude-code-test"
-      },
-      "alwaysLoad": true
-    }
-  }
-}
diff --git a/app/backend_grok.py b/app/backend_grok.py
index f4ba638d3..b52b00d53 100644
--- a/app/backend_grok.py
+++ b/app/backend_grok.py
@@ -245,68 +245,70 @@ class GrokBackend(JsonRpcStdioTransport):
         self._active_prompts = 0
         self._queue_depth = 0
         self._completed_prompts: set[str] = set()
         self._tool_names: dict[str, str] = {}
         # turn_completed carries usage; the turn_end is emitted by the prompt completion.
         self._pending_usage: dict = {}
         self._model_context_window = GROK_CONTEXT_LIMITS.get(model, GROK_DEFAULT_CONTEXT)
         self._context_tokens: int | None = None
         # A matching name is insufficient: a repository can define another command under it.
         expected_configs = self._mcp_server_configs()
         self._expected_server_identities = {
             str(server["name"]): _mcp_server_identity(server)
             for server in expected_configs
         }
         self._expected_servers: set[str] = set(self._expected_server_identities)
         self._started_servers: set[str] = set()
         self._started_server_identities: dict[str, set[tuple]] = {}
         self._ready_servers: set[str] = set()
         self._failed_servers: set[str] = set()
         self._mcp_tool_count: int | None = None
+        self._mcp_loaded_total: int | None = None
         self._mcp_ready: asyncio.Event | None = None
         self._mcp_status_changed: asyncio.Event | None = None
 
     @property
     def session_id(self) -> Optional[str]:
         return self._session_id
 
     async def connect(self) -> None:
         if self.is_alive:
             return
         if self._proc is not None:
             await self.disconnect()
         self._notifications = asyncio.Queue()
         self._disconnecting = False
         self._last_stderr = ""
         self._active_prompts = 0
         self._queue_depth = 0
         expected_configs = self._mcp_server_configs()
         self._expected_server_identities = {
             str(server["name"]): _mcp_server_identity(server)
             for server in expected_configs
         }
         self._expected_servers = set(self._expected_server_identities)
         self._started_servers = set()
         self._started_server_identities = {}
         self._ready_servers = set()
         self._failed_servers = set()
         self._mcp_tool_count = None
+        self._mcp_loaded_total = None
         self._mcp_ready = asyncio.Event()
         self._mcp_status_changed = asyncio.Event()
 
         if not Path(self.cwd).is_dir():
             # Otherwise this surfaces as a bare FileNotFoundError from process spawn, which
             # names the path but not the reason — a worktree that was removed or relocated.
             raise RuntimeError(
                 f"Grok worker cwd does not exist: {self.cwd} "
                 "(worktree removed or relocated?)"
             )
 
         cmd = [GROK_BIN, "agent"]
         # The ONLY delivery route for a system prompt. ACP session/new has no such field:
         # systemPrompt / _meta.systemPrompt / instructions are all accepted and SILENTLY
         # ignored (measured) — a worker would run with no prompt and nobody would notice.
         profile = self._write_agent_profile()
         if profile:
             cmd += ["--agent-profile", str(profile)]
         cmd += ["--model", self.model, "--reasoning-effort", self.reasoning_effort]
         # Managed workers are autonomous and have no one to answer a prompt. Belt and
@@ -394,70 +396,116 @@ class GrokBackend(JsonRpcStdioTransport):
                 )
         while (
             self._mcp_status_changed is not None
             and self._expected_servers - self._ready_servers
             and not (self._expected_servers & self._failed_servers)
         ):
             remaining = deadline - loop.time()
             if remaining <= 0:
                 break
             self._mcp_status_changed.clear()
             if not (self._expected_servers - self._ready_servers):
                 break
             try:
                 await asyncio.wait_for(
                     self._mcp_status_changed.wait(), timeout=remaining
                 )
             except asyncio.TimeoutError:
                 break
         missing = self._expected_servers - self._started_servers
         unexpected = self._started_servers - self._expected_servers
+        # Only servers whose identity the runtime actually echoed can be compared. Grok
+        # 1.0.3 sends an empty `servers_updated` (measured), so demanding an identity here
+        # failed every launch with "unexpected identity" while the real roster was correct.
         mismatched = {
             name
             for name in self._expected_servers & self._started_servers
             if self._started_server_identities.get(name)
+            and self._started_server_identities[name]
             != {self._expected_server_identities[name]}
         }
+        # With no per-server identity, the count is what keeps a foreign server out.
+        overloaded = (
+            self._mcp_loaded_total is not None
+            and self._mcp_loaded_total != len(self._expected_servers)
+        )
         unready = self._expected_servers - self._ready_servers
         no_tools = bool(self._expected_servers) and (
             self._mcp_tool_count is None or self._mcp_tool_count <= 0
         )
-        if missing or unexpected or mismatched or unready or no_tools:
+        if missing or unexpected or mismatched or overloaded or unready or no_tools:
             failures = []
             if missing:
                 failures.append(f"missing required servers {sorted(missing)}")
             if unexpected:
                 failures.append(f"unexpected servers {sorted(unexpected)}")
             if mismatched:
                 failures.append(
                     f"servers with unexpected identity {sorted(mismatched)}"
                 )
+            if overloaded:
+                failures.append(
+                    f"session loaded {self._mcp_loaded_total} MCP servers, "
+                    f"launch plan has {len(self._expected_servers)}"
+                )
             if unready:
                 failures.append(f"required servers not ready {sorted(unready)}")
             if no_tools:
                 failures.append("required MCP launch reported no tools")
             raise GrokMcpIsolationError(
                 "Grok MCP conformance failed: "
                 + "; ".join(failures)
+                + self._shadowing_hint(missing | unready)
                 + ". Refusing to run a worker without the exact Orchestra launch plan."
             )
 
+    def _shadowing_hint(self, absent: set[str]) -> str:
+        """Name the repo-local file that swallowed a server, when that is what happened.
+
+        Grok merges project scope over every other source BY NAME and only then drops the
+        project entry for an untrusted folder — so a repo `.mcp.json` naming `orchestra`
+        annihilates ours and the session starts with zero servers (measured on 1.0.3: the
+        launch plan, `config.toml` and an always-trusted `--plugin-dir` plugin all lost to
+        it). The roster we observe is empty either way, so without this the message is a
+        dead end.
+        """
+        if not absent:
+            return ""
+        shadowed: list[str] = []
+        for rel in (".mcp.json", ".grok/config.toml"):
+            path = Path(self.cwd) / rel
+            try:
+                text = path.read_text(encoding="utf-8")
+            except (OSError, UnicodeDecodeError):
+                # This runs while reporting another failure; never mask it.
+                continue
+            for name in sorted(absent):
+                if f'"{name}"' in text or f"mcp_servers.{name}" in text:
+                    shadowed.append(f"{rel} declares '{name}'")
+        if not shadowed:
+            return ""
+        return (
+            f" — repo-local MCP config shadows the launch plan ({'; '.join(shadowed)}); "
+            "remove that entry or rename it, an untrusted folder makes Grok drop it "
+            "and Orchestra's server with it"
+        )
+
     async def send(self, message: str) -> None:
         if not self.is_alive:
             await self.connect()
         if not self._session_id:
             raise RuntimeError("Grok session is not initialized")
         self._active_prompts += 1
         # Fire without awaiting: the session/prompt response only resolves when that turn
         # ENDS, so awaiting here would block the caller for the whole turn.
         task = asyncio.create_task(self._request("session/prompt", {
             "sessionId": self._session_id,
             "prompt": [{"type": "text", "text": message}],
         }))
         task.add_done_callback(self._on_prompt_settled)
 
     def _on_prompt_settled(self, task: asyncio.Task) -> None:
         """Surface a prompt that failed at the JSON-RPC layer (never silently drop it)."""
         if task.cancelled():
             return
         exc = task.exception()
         if exc is None:
@@ -608,40 +656,48 @@ class GrokBackend(JsonRpcStdioTransport):
                     "method": "_process/exited",
                     "params": {"returncode": returncode, "stderr": self._last_stderr},
                 })
 
     def _track_mcp(self, message: dict) -> None:
         method = message.get("method", "")
         params = message.get("params") or {}
         if method == "_x.ai/mcp/servers_updated":
             # The authoritative roster, and the leak channel itself: this notification
             # carries each server's env, which is how a third-party API key ended up in a
             # task artifact. It also lands before mcp_initialized, unlike server_status,
             # which can report `ready` only after the first turn is already running.
             for server in params.get("mcpServers") or []:
                 name = server.get("name")
                 if name:
                     normalized_name = str(name)
                     self._started_servers.add(normalized_name)
                     self._started_server_identities.setdefault(
                         normalized_name, set()
                     ).add(_mcp_server_identity(server))
+        elif method == "_x.ai/mcp/init_progress":
+            # 1.0.3 stopped populating `servers_updated`, so this is the only remaining
+            # count of what the session actually loaded. It is the check that a foreign
+            # server cannot pass: an extra one makes `total` exceed the launch plan.
+            try:
+                self._mcp_loaded_total = int(params.get("total"))
+            except (TypeError, ValueError):
+                pass
         elif method == "_x.ai/mcp/server_status":
             name = params.get("name")
             status = params.get("status")
             if name:
                 normalized_name = str(name)
                 if status == "ready":
                     self._started_servers.add(normalized_name)
                     self._ready_servers.add(normalized_name)
                     self._failed_servers.discard(normalized_name)
                 elif status not in (None, "starting"):
                     self._ready_servers.discard(normalized_name)
                     self._failed_servers.add(normalized_name)
                 if self._mcp_status_changed is not None:
                     self._mcp_status_changed.set()
         elif method == "_x.ai/mcp_initialized" and self._mcp_ready is not None:
             try:
                 self._mcp_tool_count = int(params.get("mcpToolCount"))
             except (TypeError, ValueError):
                 self._mcp_tool_count = None
             self._mcp_ready.set()
diff --git a/docs/tasks/264/live_grok_worker.py b/docs/tasks/264/live_grok_worker.py
new file mode 100644
index 000000000..525034f1b
--- /dev/null
+++ b/docs/tasks/264/live_grok_worker.py
@@ -0,0 +1,65 @@
+#!/usr/bin/env python3
+"""Live end-to-end run of a Grok worker through Orchestra's real backend.
+
+Not a hand-rolled ACP client: this builds `GrokBackend` exactly the way `_grok_factory`
+does, connects (so `_verify_mcp_isolation` runs for real), and gives the agent a task that
+can only be completed by calling an Orchestra MCP tool. Prints the tool calls it made.
+"""
+import asyncio, os, sys
+from pathlib import Path
+
+ROOT = Path(__file__).resolve().parents[3]
+sys.path.insert(0, str(ROOT))
+os.environ.setdefault("ORCHESTRA_SKIP_DOTENV", "0")
+
+from app.backend_grok import GrokBackend
+from app.manager import _make_mcp_config
+
+PROMPT = (
+    "You are a test worker. Call the Orchestra MCP tool `list_agents` right now and reply "
+    "with the number of agents it returned, in the form COUNT=<n>. Do not do anything else."
+)
+
+
+async def main() -> None:
+    cwd = str(ROOT)
+    assert not (Path(cwd) / ".mcp.json").exists(), (
+        "this run must happen in a checkout without the colliding .mcp.json"
+    )
+    servers = _make_mcp_config("grok-live-264", "/home/kesha/orchestra", "worker")
+    mcp_env = {k: str(v) for cfg in servers.values() for k, v in cfg.get("env", {}).items()}
+    backend = GrokBackend(
+        model="grok-4.5", cwd=cwd,
+        system_prompt="You are an Orchestra worker. Be terse.",
+        mcp_env=mcp_env, mcp_servers=servers, reasoning_effort="low",
+    )
+    await backend.connect()
+    print(f"CONNECTED session={backend.session_id}")
+    print(f"MCP tool count reported by Grok: {backend._mcp_tool_count}")
+    print(f"started servers: {sorted(backend._started_servers)}")
+    print(f"ready servers:   {sorted(backend._ready_servers)}")
+
+    await backend.send(PROMPT)
+    tool_calls, texts = [], []
+    try:
+        async with asyncio.timeout(240):
+            async for ev in backend.events():
+                kind = getattr(ev, "type", None) or getattr(ev, "kind", None)
+                content = getattr(ev, "content", "")
+                if kind == "tool_call":
+                    tool_calls.append(content)
+                    print(f"TOOL_CALL: {str(content)[:200]}")
+                elif kind == "text":
+                    texts.append(content)
+                elif kind == "turn_end":
+                    break
+    except (TimeoutError, asyncio.TimeoutError):
+        print("TIMEOUT waiting for turn_end")
+    finally:
+        print("--- assistant text ---")
+        print("".join(str(t) for t in texts)[:2000])
+        print(f"--- tool calls: {len(tool_calls)} ---")
+        await backend.disconnect()
+
+
+asyncio.run(main())
diff --git a/docs/tasks/264/mutation_check.py b/docs/tasks/264/mutation_check.py
new file mode 100644
index 000000000..65cd425d9
--- /dev/null
+++ b/docs/tasks/264/mutation_check.py
@@ -0,0 +1,64 @@
+#!/usr/bin/env python3
+"""Mutation check: does the conformance gate actually catch broken MCP wiring?
+
+Connect-only (no turn), printing the marker before every phase:
+  1. baseline      — clean wiring                     -> must CONNECT
+  2. mutant-shadow — `.mcp.json` declaring `orchestra` -> must REFUSE and name the file
+  3. reverted      — file removed again                -> must CONNECT
+  4. mutant-cmd    — launch plan points at a missing binary -> must REFUSE
+  5. reverted-cmd  — plan restored                     -> must CONNECT
+
+The mutations are data (a JSON file, an in-memory plan), not `.py` source, so there is no
+`__pycache__` staleness to defeat — the reverted phases re-run the same module objects.
+"""
+import asyncio, json, sys
+from pathlib import Path
+
+ROOT = Path(__file__).resolve().parents[3]
+sys.path.insert(0, str(ROOT))
+from app.backend_grok import GrokBackend, GrokMcpIsolationError
+from app.manager import _make_mcp_config
+
+MCP_JSON = ROOT / ".mcp.json"
+SHADOW = json.dumps({"mcpServers": {"orchestra": {
+    "type": "stdio", "command": "/nonexistent/python",
+    "args": ["-m", "app.mcp_stdio"], "env": {"ORCHESTRA_ROLE": "shadow"}}}}, indent=2)
+
+
+async def attempt(label: str, break_command: bool = False) -> str:
+    servers = _make_mcp_config(f"grok-mut-{label}", "/home/kesha/orchestra", "worker")
+    if break_command:
+        servers["orchestra"]["command"] = "/nonexistent/python3"
+    mcp_env = {k: str(v) for cfg in servers.values() for k, v in cfg.get("env", {}).items()}
+    backend = GrokBackend(model="grok-4.5", cwd=str(ROOT), system_prompt="t",
+                          mcp_env=mcp_env, mcp_servers=servers, reasoning_effort="low")
+    try:
+        await backend.connect()
+        return f"CONNECTED tools={backend._mcp_tool_count} ready={sorted(backend._ready_servers)}"
+    except GrokMcpIsolationError as exc:
+        return f"REFUSED {exc}"
+    except Exception as exc:
+        return f"ERROR {type(exc).__name__}: {exc}"
+    finally:
+        await backend.disconnect()
+
+
+async def phase(name: str, *, shadow: bool = False, break_command: bool = False) -> None:
+    print(f"[{name}] .mcp.json present = {MCP_JSON.exists()}", flush=True)
+    print(f"  -> {await attempt(name, break_command=break_command)}\n", flush=True)
+
+
+async def main() -> None:
+    await phase("baseline")
+
+    MCP_JSON.write_text(SHADOW, encoding="utf-8")
+    await phase("mutant-shadow")
+
+    MCP_JSON.unlink()
+    await phase("reverted")
+
+    await phase("mutant-cmd", break_command=True)
+    await phase("reverted-cmd")
+
+
+asyncio.run(main())
diff --git a/docs/tasks/264/probe_collision.py b/docs/tasks/264/probe_collision.py
new file mode 100644
index 000000000..3e238b357
--- /dev/null
+++ b/docs/tasks/264/probe_collision.py
@@ -0,0 +1,78 @@
+#!/usr/bin/env python3
+"""Which injection route survives a repo-local `.mcp.json` that declares the same name?
+
+cwd is a worktree of this repo, which tracks a `.mcp.json` defining a server called
+`orchestra`. Grok merges project scope over global scope by name, then folder-trust drops
+the project entry — annihilating ours. Reads Grok's own debug log for the verdict.
+"""
+import asyncio, json, os, re, shutil, subprocess, sys, uuid
+from pathlib import Path
+
+ROOT = Path(__file__).resolve().parents[3]
+sys.path.insert(0, str(ROOT))
+sys.path.insert(0, str(Path(__file__).resolve().parent))
+from app.backend_grok import GROK_BIN
+from probe_routes import make_home, make_plugin, toml_block, acp_plan
+
+
+def run(label: str, cwd: str, plugin: Path | None, send_plan: bool,
+        config_server: bool) -> dict:
+    home = make_home(toml_block() if config_server else "")
+    log = f"/tmp/grok-collision-{label}-{uuid.uuid4().hex[:6]}.log"
+    argv = [GROK_BIN, "agent", "--model", "grok-4.5", "--always-approve"]
+    if plugin:
+        argv += ["--plugin-dir", str(plugin)]
+    argv += ["--debug", "--debug-file", log, "stdio"]
+
+    params = {"cwd": cwd}
+    if send_plan:
+        params["mcpServers"] = acp_plan()
+    stdin = "\n".join(json.dumps(m) for m in [
+        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
+            "protocolVersion": 1, "clientCapabilities": {
+                "fs": {"readTextFile": False, "writeTextFile": False}, "terminal": False}}},
+        {"jsonrpc": "2.0", "id": 2, "method": "session/new", "params": params},
+    ]) + "\n"
+
+    env = dict(os.environ)
+    for var in ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy", "ALL_PROXY", "all_proxy"):
+        env.pop(var, None)
+    env["GROK_HOME"] = str(home)
+    try:
+        subprocess.run(argv, input=stdin, text=True, env=env, cwd=cwd,
+                       capture_output=True, timeout=90)
+    except subprocess.TimeoutExpired:
+        pass
+    text = Path(log).read_text(errors="replace") if Path(log).exists() else ""
+    created = re.search(r"created with (\d+) MCP servers", text)
+    names = re.search(r"config_count=(\d+) config_names=(\[[^\]]*\])", text)
+    shutil.rmtree(home, ignore_errors=True)
+    return {
+        "created": int(created.group(1)) if created else None,
+        "init_count": int(names.group(1)) if names else None,
+        "init_names": names.group(2) if names else None,
+        "untrusted_skip": "folder untrusted" in text,
+        "log": log,
+    }
+
+
+def main() -> None:
+    cwd = str(ROOT)  # a worktree of this repo — tracks .mcp.json with an `orchestra` entry
+    assert (Path(cwd) / ".mcp.json").exists(), "probe needs the colliding .mcp.json present"
+    plugin = make_plugin(".claude-plugin")
+    cases = [
+        ("acp-plan", None, True, False),
+        ("config-toml", None, False, True),
+        ("plugin-dir", plugin, False, False),
+        ("plugin+plan", plugin, True, False),
+    ]
+    results = {}
+    for label, plug, send_plan, config_server in cases:
+        results[label] = run(label, cwd, plug, send_plan, config_server)
+        print(f"{label:14} {json.dumps(results[label])}", flush=True)
+    Path("/tmp/grok-collision-results.json").write_text(json.dumps(results, indent=2))
+    shutil.rmtree(plugin, ignore_errors=True)
+
+
+if __name__ == "__main__":
+    main()
diff --git a/docs/tasks/264/probe_routes.py b/docs/tasks/264/probe_routes.py
new file mode 100644
index 000000000..4a57766ec
--- /dev/null
+++ b/docs/tasks/264/probe_routes.py
@@ -0,0 +1,165 @@
+#!/usr/bin/env python3
+"""Probe which MCP injection route Grok 1.0.3 actually honours over ACP.
+
+Each variant gets a fresh scratch GROK_HOME so live workers are never touched. Prints the
+observed roster and tool count per route — the two signals `_verify_mcp_isolation` reads.
+"""
+import asyncio, json, os, shutil, sys, uuid
+from pathlib import Path
+
+ROOT = Path(__file__).resolve().parents[3]
+sys.path.insert(0, str(ROOT))
+from app.backend_grok import _GROK_SANDBOX_CONFIG, GROK_BIN, GROK_USER_HOME
+from app.runtime_env import MCP_STDIO_CMD, MCP_BASE_ENV
+
+SERVER_ENV = {
+    **MCP_BASE_ENV, "ORCHESTRA_URL": "http://127.0.0.1:8888",
+    "ORCHESTRA_SCOPE": "/home/kesha/orchestra", "ORCHESTRA_ROLE": "worker",
+    "ORCHESTRA_ACCESS_MODE": "full", "WORKER_NAME": "grok-probe",
+    "PARENT_NAME": "", "ORCHESTRA_SESSION_ID": "",
+}
+
+
+def acp_plan() -> list[dict]:
+    return [{
+        "name": "orchestra", "type": "stdio",
+        "command": MCP_STDIO_CMD[0], "args": [str(a) for a in MCP_STDIO_CMD[1:]],
+        "env": [{"name": k, "value": str(v)} for k, v in SERVER_ENV.items()],
+    }]
+
+
+def toml_block() -> str:
+    args = ", ".join(json.dumps(str(a)) for a in MCP_STDIO_CMD[1:])
+    env = ", ".join(f"{k} = {json.dumps(str(v))}" for k, v in SERVER_ENV.items())
+    return (f'\n[mcp_servers.orchestra]\ncommand = {json.dumps(MCP_STDIO_CMD[0])}\n'
+            f'args = [{args}]\nenv = {{ {env} }}\nenabled = true\n')
+
+
+def make_home(config_extra: str = "", base: str | None = None) -> Path:
+    home = Path(f"/tmp/grok-probe-home-{uuid.uuid4().hex[:8]}")
+    home.mkdir(parents=True)
+    (home / "config.toml").write_text((base or _GROK_SANDBOX_CONFIG) + config_extra, encoding="utf-8")
+    (home / "auth.json").symlink_to(GROK_USER_HOME / "auth.json")
+    return home
+
+
+def make_plugin(manifest_dir: str) -> Path:
+    d = Path(f"/tmp/grok-probe-plugin-{uuid.uuid4().hex[:8]}")
+    (d / manifest_dir).mkdir(parents=True)
+    (d / manifest_dir / "plugin.json").write_text(json.dumps(
+        {"name": "orchestra", "description": "Orchestra managed MCP", "version": "1.0.0"}))
+    (d / ".mcp.json").write_text(json.dumps({"mcpServers": {"orchestra": {
+        "type": "stdio", "command": MCP_STDIO_CMD[0],
+        "args": [str(a) for a in MCP_STDIO_CMD[1:]], "env": SERVER_ENV}}}, indent=2))
+    return d
+
+
+async def probe(label: str, home: Path, plugin_dir: Path | None, send_plan: bool,
+                cwd: str, settle: float = 25.0) -> dict:
+    env = dict(os.environ)
+    for var in ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy", "ALL_PROXY", "all_proxy"):
+        env.pop(var, None)
+    env["GROK_HOME"] = str(home)
+    argv = [GROK_BIN, "agent", "--model", "grok-4.5", "--reasoning-effort", "high",
+            "--always-approve"]
+    if plugin_dir:
+        argv += ["--plugin-dir", str(plugin_dir)]
+    argv += ["stdio"]
+
+    proc = await asyncio.create_subprocess_exec(
+        *argv, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
+        stderr=asyncio.subprocess.PIPE, env=env, cwd=cwd, limit=16 * 1024 * 1024)
+    dump = open(f"/tmp/grok-probe-{label}-{uuid.uuid4().hex[:6]}.jsonl", "w")
+    pending: dict[int, asyncio.Future] = {}
+    seen = {"servers": [], "tool_count": None, "status": []}
+
+    async def reader() -> None:
+        while True:
+            line = await proc.stdout.readline()
+            if not line:
+                return
+            dump.write(line.decode(errors="replace")); dump.flush()
+            try:
+                msg = json.loads(line)
+            except ValueError:
+                continue
+            if "id" in msg and ("result" in msg or "error" in msg):
+                fut = pending.pop(msg["id"], None)
+                if fut and not fut.done():
+                    fut.set_result(msg)
+                continue
+            method, params = msg.get("method"), msg.get("params") or {}
+            if method == "_x.ai/mcp/servers_updated":
+                seen["servers"] = [s.get("name") for s in (params.get("mcpServers") or [])]
+            elif method == "_x.ai/mcp/server_status":
+                seen["status"].append((params.get("name"), params.get("status")))
+            elif method == "_x.ai/mcp_initialized":
+                seen["tool_count"] = params.get("mcpToolCount")
+            elif method and "id" in msg:
+                proc.stdin.write((json.dumps({"jsonrpc": "2.0", "id": msg["id"],
+                                              "result": {}}) + "\n").encode())
+
+    async def errdrain() -> None:
+        while True:
+            line = await proc.stderr.readline()
+            if not line:
+                return
+            dump.write("STDERR: " + line.decode(errors="replace")); dump.flush()
+
+    tasks = [asyncio.create_task(reader()), asyncio.create_task(errdrain())]
+    counter = 0
+
+    async def request(method: str, params: dict) -> dict:
+        nonlocal counter
+        counter += 1
+        fut = asyncio.get_running_loop().create_future()
+        pending[counter] = fut
+        proc.stdin.write((json.dumps({"jsonrpc": "2.0", "id": counter, "method": method,
+                                      "params": params}) + "\n").encode())
+        await proc.stdin.drain()
+        return await asyncio.wait_for(fut, timeout=60)
+
+    try:
+        await request("initialize", {"protocolVersion": 1, "clientCapabilities": {
+            "fs": {"readTextFile": False, "writeTextFile": False}, "terminal": False}})
+        await request("session/new", {"cwd": cwd,
+                                      "mcpServers": acp_plan() if send_plan else []})
+        await asyncio.sleep(settle)
+    finally:
+        proc.kill()
+        await proc.wait()
+        for t in tasks:
+            t.cancel()
+        dump.close()
+    return seen
+
+
+async def main() -> None:
+    cwd = str(ROOT)
+    results = {}
+
+    variants = [
+        ("acp-plan-only", make_home(), None, True),
+        ("plugin-claude-manifest", make_home(), make_plugin(".claude-plugin"), False),
+        ("plugin-grok-manifest", make_home(), make_plugin(".grok-plugin"), False),
+        ("plugin-compat-on", make_home(base=_GROK_SANDBOX_CONFIG.replace(
+            "[compat.claude]\nmcps = false", "[compat.claude]\nmcps = true")),
+         make_plugin(".claude-plugin"), False),
+        ("home-config-toml", make_home(toml_block()), None, False),
+    ]
+    for label, home, plugin, send_plan in variants:
+        try:
+            seen = await probe(label, home, plugin, send_plan, cwd)
+        except Exception as exc:
+            seen = {"error": f"{type(exc).__name__}: {exc}"}
+        results[label] = seen
+        print(f"{label:26} {json.dumps(seen)}", flush=True)
+        shutil.rmtree(home, ignore_errors=True)
+        if plugin:
+            shutil.rmtree(plugin, ignore_errors=True)
+
+    Path("/tmp/grok-probe-results.json").write_text(json.dumps(results, indent=2))
+
+
+if __name__ == "__main__":
+    asyncio.run(main())
diff --git a/docs/tasks/264/probe_session_new.py b/docs/tasks/264/probe_session_new.py
new file mode 100644
index 000000000..af6014bb0
--- /dev/null
+++ b/docs/tasks/264/probe_session_new.py
@@ -0,0 +1,129 @@
+#!/usr/bin/env python3
+"""Does session/new's `mcpServers` add to, replace, or get ignored against config.toml?
+
+Runs the same ACP handshake three ways against a GROK_HOME whose config.toml already
+declares the orchestra server (proved healthy by `grok mcp doctor`).
+"""
+import asyncio, json, shutil, sys
+from pathlib import Path
+
+sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
+sys.path.insert(0, str(Path(__file__).resolve().parent))
+from probe_routes import make_home, toml_block, probe, acp_plan
+
+ROOT = Path(__file__).resolve().parents[3]
+
+
+async def main() -> None:
+    cwd = str(ROOT)
+    cases = {
+        # (send_plan flag understood by probe(), plus an omit-key override below)
+        "config+no-key": "omit",
+        "config+empty-list": "empty",
+        "config+acp-plan": "plan",
+    }
+    results = {}
+    for label, mode in cases.items():
+        home = make_home(toml_block())
+        try:
+            seen = await probe_mode(label, home, cwd, mode)
+        except Exception as exc:
+            seen = {"error": f"{type(exc).__name__}: {exc}"}
+        results[label] = seen
+        print(f"{label:20} {json.dumps(seen)}", flush=True)
+        shutil.rmtree(home, ignore_errors=True)
+    Path("/tmp/grok-session-new-results.json").write_text(json.dumps(results, indent=2))
+
+
+async def probe_mode(label: str, home: Path, cwd: str, mode: str) -> dict:
+    """probe() always sends the key; patch the params for the omit case."""
+    import probe_routes
+    original = probe_routes.acp_plan
+    if mode == "omit":
+        # Monkeypatch a sentinel the patched probe understands.
+        return await _probe_omit(label, home, cwd)
+    probe_routes.acp_plan = (lambda: acp_plan()) if mode == "plan" else (lambda: [])
+    try:
+        return await probe(label, home, None, True, cwd)
+    finally:
+        probe_routes.acp_plan = original
+
+
+async def _probe_omit(label: str, home: Path, cwd: str) -> dict:
+    """session/new without the mcpServers key at all."""
+    import os, uuid
+    from app.backend_grok import GROK_BIN
+    env = dict(os.environ)
+    for var in ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy", "ALL_PROXY", "all_proxy"):
+        env.pop(var, None)
+    env["GROK_HOME"] = str(home)
+    proc = await asyncio.create_subprocess_exec(
+        GROK_BIN, "agent", "--model", "grok-4.5", "--reasoning-effort", "high",
+        "--always-approve", "stdio",
+        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
+        stderr=asyncio.subprocess.PIPE, env=env, cwd=cwd, limit=16 * 1024 * 1024)
+    dump = open(f"/tmp/grok-omit-{label}-{uuid.uuid4().hex[:6]}.jsonl", "w")
+    pending: dict[int, asyncio.Future] = {}
+    seen = {"servers": [], "tool_count": None, "status": []}
+
+    async def reader() -> None:
+        while True:
+            line = await proc.stdout.readline()
+            if not line:
+                return
+            dump.write(line.decode(errors="replace")); dump.flush()
+            try:
+                msg = json.loads(line)
+            except ValueError:
+                continue
+            if "id" in msg and ("result" in msg or "error" in msg):
+                fut = pending.pop(msg["id"], None)
+                if fut and not fut.done():
+                    fut.set_result(msg)
+                continue
+            method, params = msg.get("method"), msg.get("params") or {}
+            if method == "_x.ai/mcp/servers_updated":
+                seen["servers"] = [s.get("name") for s in (params.get("mcpServers") or [])]
+            elif method == "_x.ai/mcp/server_status":
+                seen["status"].append((params.get("name"), params.get("status")))
+            elif method == "_x.ai/mcp_initialized":
+                seen["tool_count"] = params.get("mcpToolCount")
+            elif method and "id" in msg:
+                proc.stdin.write((json.dumps({"jsonrpc": "2.0", "id": msg["id"],
+                                              "result": {}}) + "\n").encode())
+
+    async def errdrain() -> None:
+        while True:
+            line = await proc.stderr.readline()
+            if not line:
+                return
+            dump.write("STDERR: " + line.decode(errors="replace")); dump.flush()
+
+    tasks = [asyncio.create_task(reader()), asyncio.create_task(errdrain())]
+    counter = 0
+
+    async def request(method: str, params: dict) -> dict:
+        nonlocal counter
+        counter += 1
+        fut = asyncio.get_running_loop().create_future()
+        pending[counter] = fut
+        proc.stdin.write((json.dumps({"jsonrpc": "2.0", "id": counter, "method": method,
+                                      "params": params}) + "\n").encode())
+        await proc.stdin.drain()
+        return await asyncio.wait_for(fut, timeout=60)
+
+    try:
+        await request("initialize", {"protocolVersion": 1, "clientCapabilities": {
+            "fs": {"readTextFile": False, "writeTextFile": False}, "terminal": False}})
+        await request("session/new", {"cwd": cwd})  # no mcpServers key
+        await asyncio.sleep(25)
+    finally:
+        proc.kill()
+        await proc.wait()
+        for t in tasks:
+            t.cancel()
+        dump.close()
+    return seen
+
+
+asyncio.run(main())
diff --git a/docs/tasks/264/report.md b/docs/tasks/264/report.md
new file mode 100644
index 000000000..32f8cca54
--- /dev/null
+++ b/docs/tasks/264/report.md
@@ -0,0 +1,151 @@
+# #264 — Grok не поднимался как рантайм воркера: два дефекта подряд
+
+Симптом (репро оркестратора, 13.08 16:47):
+
+```
+Grok MCP conformance failed: missing required servers ['orchestra'];
+required servers not ready ['orchestra']; required MCP launch reported no tools.
+```
+
+Итог: **оба дефекта найдены и починены, Grok-агент живьём вызвал Orchestra-тул и ответил.**
+`grok mcp list` («No MCP servers configured») — ложный след: Orchestra отдаёт сервер через
+ACP `session/new`, а не через конфиг Grok, поэтому в `grok mcp list` его никогда и не было.
+
+## Дефект 1 (несущий) — репозиторный `.mcp.json` съедал сервер по имени
+
+В репозитории лежал **трекнутый** `.mcp.json`, объявляющий сервер с тем же именем
+`orchestra` (коммит `085c4632` «add .mcp.json for local Claude Code testing», пути ноутбука
+`/mnt/data/Projects/Python/orchestra`, которых на VPS не существует).
+
+Механизм — дословно из отладочного лога самого Grok (`/tmp/grok-debug-264.log`):
+
+```
+INFO  managed_mcp: MCP server loaded from source server="orchestra" source=ConfigToml {...}
+INFO  config::mcp: loaded MCP servers source=".../fix-grok-mcp/.mcp.json" count=1
+WARN  folder_trust: folder untrusted: skipping repo-local (project-scoped) MCP server server=orchestra
+INFO  acp_session::spawn: Session '...' created with 0 MCP servers
+```
+
+Grok сливает project-scope **поверх всех остальных источников ПО ИМЕНИ** (README, строка
+2000: «the project version **replaces** it entirely»), и только ПОТОМ выбрасывает
+project-запись из-за недоверенной папки. Наш сервер аннигилируется вместе с ней.
+
+Проверено, что проигрывают **все** способы доставки, а не только наш (одинаковый cwd с
+коллизией, `docs/tasks/264/probe_collision.py`):
+
+| маршрут | `created with N MCP servers` |
+|---|---|
+| ACP `session/new` (как в проде) | 0 |
+| `config.toml` в GROK_HOME | 0 |
+| `--plugin-dir` (документирован как «always trusted», плагин **обнаружен**: `loaded MCP servers source="plugin:orchestra" count=1`) | 0 |
+| `--plugin-dir` + ACP-план | 0 |
+
+Контроль: тот же ACP-план в cwd **без** `.mcp.json` → `created with 1 MCP servers`,
+`config_names=["orchestra"]`. То есть маршрут исправен, ломала именно коллизия имени.
+
+Запись мертва для всех наших потребителей: `app/runtime_registry.py:126,135` явно
+пропускают ключ `orchestra` из `.mcp.json`/`settings.json`, а `_make_mcp_config` его
+игнорирует с предупреждением. Единственный, кто её читал, — Grok, и читал разрушительно.
+
+**Правка:** `.mcp.json` удалён (в нём была ровно одна эта запись).
+
+## Дефект 2 — Grok 1.0.3 перестал заполнять `servers_updated`, проверка личности падала всегда
+
+После снятия коллизии сервер стартовал, но connect падал уже иначе:
+`servers with unexpected identity ['orchestra']`. Сырой поток уведомлений при живом
+connect:
+
+```
+_x.ai/mcp/servers_updated  {"mcpServers": []}          <- пусто
+_x.ai/mcp/init_progress    {"total": 1, "connected": 1}
+_x.ai/mcp_initialized      {"mcpToolCount": 37}
+_x.ai/mcp/server_status    {"name": "orchestra", "status": "ready"}
+итог: started=['orchestra'] ready=['orchestra'] identities={} tools=37
+```
+
+`_started_server_identities` наполняется ТОЛЬКО из `servers_updated`, а `_started_servers` —
+ещё и из `server_status`. В 1.0.3 роспись роли пуста, поэтому «личность не сообщили»
+читалось как «личность неверная» — при полностью корректном роспуске из 37 тулов.
+
+**Правка** (`app/backend_grok.py`): личность сверяется только там, где рантайм её реально
+прислал; вместо потерянного признака добавлен счётный инвариант из `init_progress.total` —
+`overloaded`: число загруженных сессией серверов обязано совпадать с планом запуска.
+
+### Остаточная дыра, названная честно
+
+`servers_updated` был каналом, по которому #98 ловил подмену сервера с тем же именем (и
+через который когда-то утёк чужой `OPENROUTER_API_KEY`). Пустой — он этот контроль больше
+не даёт. Что осталось: точное совпадение множества имён, `total` из `init_progress` (лишний
+сервер поднимает счётчик), ненулевой `mcpToolCount`, плюс GROK_HOME, которым владеет
+Orchestra и который не помечает папки доверенными — а недоверенная папка, как измерено
+выше, вообще не даёт project-scope загрузиться. Не покрыт случай «папка стала доверенной И
+кто-то объявил сервер с именем `orchestra`»: подмену через ACP теперь не увидеть.
+Настоящее лечение — канареечный хендшейк от нашего же `mcp_stdio.py` (кандидат из
+`docs/tasks/98-grok-runtime-audit/research.md`), это отдельная задача.
+Тесты личности из #98 (`tests/test_backend_grok.py`, 82 passed) остались зелёными: где
+рантайм личность присылает, подмена по-прежнему ловится.
+
+## Диагностика на будущее
+
+Сообщение об отказе теперь само называет причину (`_shadowing_hint`): если недостающий
+сервер объявлен в `.mcp.json` или `.grok/config.toml` рядом с cwd, отказ печатает файл и
+средство. Иначе следующий такой случай — снова часы поиска, потому что наблюдаемый роспись
+пуста в обоих случаях.
+
+## Доказательства
+
+**Живой прогон** через настоящий `GrokBackend` (`docs/tasks/264/live_grok_worker.py`,
+собран как `_grok_factory`, поэтому `_verify_mcp_isolation` отрабатывает по-настоящему):
+
+```
+CONNECTED tools=37, started=['orchestra'], ready=['orchestra']
+EV tool_use    search_tool: {"query": "list_agents orchestra"}
+EV tool_result ... "tool_name": "orchestra__list_agents" ...
+EV tool_use    use_tool: {"tool_name": "orchestra__list_agents", "tool_input": {}}
+EV tool_result {"status": "completed"}
+EV stream      COUNT=30
+EV turn_end    stop_reason=end_turn
+```
+
+Агент получил задание, вызвал тул Orchestra и ответил числом из живых данных.
+
+**Мутация** (`docs/tasks/264/mutation_check.py`, маркер печатается перед каждой фазой):
+
+| фаза | `.mcp.json` | результат |
+|---|---|---|
+| baseline | нет | CONNECTED tools=37 |
+| mutant-shadow | есть | REFUSED + подсказка называет файл |
+| reverted | нет | CONNECTED tools=37 |
+| mutant-cmd (битый путь к бинарю) | нет | REFUSED |
+| reverted-cmd | нет | CONNECTED tools=37 |
+
+Мутант воспроизводит **дословно** прод-ошибку оркестратора — то есть чинили именно тот
+дефект, о котором был тикет. Зелёный повтор после отката отличает «мутация откачена» от
+«мутант продолжает исполняться». Мутации — данные (JSON-файл, план в памяти), не `.py`,
+поэтому `__pycache__` тут не при чём и `touch` не требуется.
+
+## Версия про побочный ущерб от #251 — ОТВЕРГНУТА
+
+Правка `~/.grok/config.toml` ради телеметрии к делу не относится: managed GROK_HOME
+(`data/grok-home`) уводит Grok от пользовательского конфига, и **все** пробы выше
+поднимались на свежезаписанном шаблоне `_GROK_SANDBOX_CONFIG` — и всё равно падали. То есть
+дефект воспроизводится на заведомо чистом конфиге.
+
+Побочная находка (не причина, но реальна): managed `data/grok-home/config.toml` **дрейфует**
+— Grok переписывает его сам. На момент начала задачи он потерял блоки `[features]` и
+`[telemetry]` и приобрёл `[cli]`/`[ui]`/`[marketplace]`. Orchestra самолечится: сравнение с
+шаблоном в `_write_sandbox_config` восстановило их при первом же моём connect (сейчас на
+диске шаблон + дописанный Grok'ом `[marketplace]`). Телеметрия при этом всё равно закрыта
+переменными окружения в `_build_env`, так что ущерб ограничен окном между переписыванием и
+следующим коннектом. Отдельного тикета просит, чинить в рамках #264 не стал.
+
+## Что нужно знать перед мержем
+
+- `.mcp.json` **трекнут в main и лежит в 28 существующих worktree**. Новые воркеры
+  ответвляются от main и после мержа коллизии не увидят; воркеры на СТАРЫХ ветках будут
+  ловить её, пока не подтянут main. Grok-воркера спавнить на ветке с этим удалением.
+- `app/workspace.py:29` копирует `.mcp.json` в каждый новый worktree через `PROJECT_FILES`.
+  После мержа копировать нечего. Но в ЛЮБОМ другом репозитории со своим `.mcp.json`,
+  объявляющим `orchestra`, дефект повторится — теперь он хотя бы называет себя сам.
+- Файл трекнутый и общий с контуром ноутбука: там пути `/mnt/data/Projects/Python/...` могли
+  быть живыми. Удаление согласовать.
diff --git a/docs/tasks/264/repro_acp.py b/docs/tasks/264/repro_acp.py
new file mode 100644
index 000000000..6e2d24ded
--- /dev/null
+++ b/docs/tasks/264/repro_acp.py
@@ -0,0 +1,116 @@
+#!/usr/bin/env python3
+"""Minimal ACP handshake against `grok agent stdio`, dumping every notification.
+
+Reproduces the launch plan Orchestra sends (one stdio server named `orchestra`) against a
+SCRATCH GROK_HOME so live workers' config is never touched.
+"""
+import asyncio, json, os, sys, uuid
+from pathlib import Path
+
+sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
+from app.backend_grok import _GROK_SANDBOX_CONFIG, GROK_BIN, GROK_USER_HOME
+from app.runtime_env import MCP_STDIO_CMD, MCP_BASE_ENV
+
+SCRATCH = Path(os.environ.get("SCRATCH_HOME", "/tmp/grok-repro-home-%s" % uuid.uuid4().hex[:6]))
+
+
+def scratch_home() -> Path:
+    SCRATCH.mkdir(parents=True, exist_ok=True)
+    (SCRATCH / "config.toml").write_text(_GROK_SANDBOX_CONFIG, encoding="utf-8")
+    link = SCRATCH / "auth.json"
+    if not link.is_symlink():
+        link.symlink_to(GROK_USER_HOME / "auth.json")
+    return SCRATCH
+
+
+def server_configs(cwd: str) -> list[dict]:
+    env = {**MCP_BASE_ENV, "ORCHESTRA_URL": "http://127.0.0.1:8888",
+           "ORCHESTRA_SCOPE": "/home/kesha/orchestra", "ORCHESTRA_ROLE": "worker",
+           "ORCHESTRA_ACCESS_MODE": "full", "WORKER_NAME": "grok-repro",
+           "PARENT_NAME": "", "ORCHESTRA_SESSION_ID": ""}
+    return [{
+        "name": "orchestra", "type": "stdio",
+        "command": MCP_STDIO_CMD[0], "args": [str(a) for a in MCP_STDIO_CMD[1:]],
+        "env": [{"name": k, "value": str(v)} for k, v in env.items()],
+    }]
+
+
+async def main() -> None:
+    cwd = str(Path(__file__).resolve().parents[2])
+    home = scratch_home()
+    env = dict(os.environ)
+    for var in ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy", "ALL_PROXY", "all_proxy"):
+        env.pop(var, None)
+    env["GROK_HOME"] = str(home)
+
+    argv = [GROK_BIN, "agent", "--model", "grok-4.5", "--reasoning-effort", "high",
+            "--always-approve"]
+    plugin_dir = os.environ.get("PLUGIN_DIR")
+    if plugin_dir:
+        argv += ["--plugin-dir", plugin_dir]
+    argv += ["stdio"]
+    proc = await asyncio.create_subprocess_exec(
+        *argv,
+        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
+        stderr=asyncio.subprocess.PIPE, env=env, cwd=cwd, limit=16 * 1024 * 1024,
+    )
+    out = open(os.environ.get("DUMP", "/tmp/grok-repro.jsonl"), "w")
+    pending: dict[int, asyncio.Future] = {}
+
+    async def reader() -> None:
+        while True:
+            line = await proc.stdout.readline()
+            if not line:
+                break
+            out.write(line.decode(errors="replace"))
+            out.flush()
+            try:
+                msg = json.loads(line)
+            except ValueError:
+                continue
+            if "id" in msg and ("result" in msg or "error" in msg):
+                fut = pending.pop(msg["id"], None)
+                if fut and not fut.done():
+                    fut.set_result(msg)
+            elif msg.get("method") and "id" in msg:
+                # agent->client request; approve everything
+                proc.stdin.write((json.dumps({"jsonrpc": "2.0", "id": msg["id"],
+                                              "result": {}}) + "\n").encode())
+
+    async def stderr_drain() -> None:
+        while True:
+            line = await proc.stderr.readline()
+            if not line:
+                break
+            out.write("STDERR: " + line.decode(errors="replace"))
+            out.flush()
+
+    asyncio.create_task(reader())
+    asyncio.create_task(stderr_drain())
+    counter = 0
+
+    async def request(method: str, params: dict) -> dict:
+        nonlocal counter
+        counter += 1
+        fut = asyncio.get_running_loop().create_future()
+        pending[counter] = fut
+        proc.stdin.write((json.dumps({"jsonrpc": "2.0", "id": counter,
+                                      "method": method, "params": params}) + "\n").encode())
+        await proc.stdin.drain()
+        return await asyncio.wait_for(fut, timeout=60)
+
+    await request("initialize", {"protocolVersion": 1,
+                                 "clientCapabilities": {"fs": {"readTextFile": False,
+                                                               "writeTextFile": False},
+                                                        "terminal": False}})
+    plan = [] if os.environ.get("PLUGIN_DIR") and os.environ.get("NO_PLAN") else server_configs(cwd)
+    res = await request("session/new", {"cwd": cwd, "mcpServers": plan})
+    print("session/new ->", json.dumps(res)[:400])
+    await asyncio.sleep(25)  # let MCP init notifications land
+    proc.kill()
+    out.close()
+    print("dump:", os.environ.get("DUMP", "/tmp/grok-repro.jsonl"))
+    print("scratch home:", home)
+
+
+asyncio.run(main())
diff --git a/docs/workers/fix-grok-mcp.md b/docs/workers/fix-grok-mcp.md
new file mode 100644
index 000000000..98de05306
--- /dev/null
+++ b/docs/workers/fix-grok-mcp.md
@@ -0,0 +1,27 @@
+# fix-grok-mcp — личная память
+
+## Grok как рантайм (1.0.3)
+
+- **`grok mcp list` пустой — это НЕ диагноз.** Orchestra отдаёт MCP через ACP `session/new`,
+  а не через конфиг Grok. В `grok mcp list` наш сервер не появится никогда.
+- **Единственный быстрый источник правды — отладочный лог самого Grok:**
+  `grok agent --debug --debug-file /tmp/x.log stdio`. Строки, которые отвечают на всё:
+  `created with N MCP servers`, `folder untrusted: skipping repo-local`,
+  `ensure_mcp_tools_initialized: config_count=`. Полдня ACP-проб заменяются одним прогоном —
+  сначала лог, потом гипотезы.
+- `grok mcp doctor` проверяет ПАРСИНГ конфига и здоровье сервера, но НЕ то, что сессия его
+  загрузит. У меня doctor показывал «37 tools, healthy», а сессия поднималась с нулём.
+- Grok сливает project-scope `.mcp.json` поверх всех источников ПО ИМЕНИ, и только потом
+  выбрасывает его по folder-trust. Совпало имя — наш сервер исчезает вместе с чужим.
+  Проигрывают все маршруты, включая `--plugin-dir`, который в `--help` обещает «always trusted».
+- Grok сам переписывает `config.toml` в GROK_HOME, теряя наши блоки. Orchestra чинит это
+  сравнением с шаблоном на следующем коннекте.
+
+## Метод
+
+- Прогон, где ВСЕ варианты дали одинаковый отрицательный ответ, — сигнал, что сломан общий
+  первый шаг, а не что все варианты плохи. У меня 5 маршрутов из 5 дали «0 серверов»;
+  настоящей причиной был confound (коллизия имени), общий для всех пяти. Прежде чем писать
+  «ни один способ не работает», нужен положительный контроль на заведомо рабочем объекте.
+- Модуль-пробник с `asyncio.run(main())` на верхнем уровне перезапускает весь прогон при
+  импорте. Сразу писать `if __name__ == "__main__":` — иначе чужой импорт стоит минут.


## Later history of the touched files on main (after this commit)

10 later commits touch these paths; the first 40 (oldest first):
e9c34833e 2026-08-14 #265: #265: canary handshake so a same-name Grok MCP server cannot impersonate ours
5e11d8772 2026-08-16 fix: stabilize Grok session replay and chat finalization
3c037bdb8 2026-08-18 #290: cross-runtime handoff + канареечный скип по продовому предикату (scratch/290, вердикт #328)
b643c67e3 2026-08-19 #230: горячее применение правок и живучесть ходов при рестарте
247fe6b37 2026-08-24 fix: retarget models within every runtime
498c0d149 2026-09-03 Orchestra: migrate project state to .orchestra
f8e00522e 2026-09-03 #430: research .orchestra path migration
e6da7e30a 2026-09-10 #537: stop runtime trees with Orchestra and remove live adoption
62e76da50 2026-10-08 V-782: shared workflow admission scheduler and agent cgroup isolation
57f85fcd1 2026-10-14 V-846: #V-846: enforce shell wait and search policy

## Patches of the first 8 later commits, restricted to the touched paths (each capped at 150 lines)

### e9c34833e #265: #265: canary handshake so a same-name Grok MCP server cannot impersonate ours

diff --git a/app/backend_grok.py b/app/backend_grok.py
index b52b00d53..f33ae2d50 100644
--- a/app/backend_grok.py
+++ b/app/backend_grok.py
@@ -2,10 +2,12 @@
 
 import asyncio
 import json
 import logging
 import os
+import re
+import secrets
 import shutil
 import tempfile
 import uuid
 from pathlib import Path
 from typing import AsyncIterator, Optional
@@ -85,10 +87,21 @@ GROK_COST_TICK_USD = 1e-10
 
 GROK_REASONING_EFFORTS = {"low", "medium", "high"}
 GROK_SILENCE_HEARTBEAT_SECONDS = 30
 GROK_MCP_INIT_TIMEOUT_SECONDS = 20
 
+# Planted in the orchestra server env; only our mcp_stdio.py writes the matching proof
+# file. Grok 1.0.3 no longer echoes server identity, so a same-name impostor from a
+# trusted-folder `.mcp.json` would otherwise pass the roster check.
+ORCHESTRA_MCP_CANARY_ENV = "ORCHESTRA_MCP_CANARY"
+_ORCHESTRA_MCP_CANARY_RE = re.compile(r"^[0-9a-f]{32}$")
+GROK_MCP_CANARY_TIMEOUT_SECONDS = 0.5
+
+
+def mcp_canary_proof_path(nonce: str) -> Path:
+    return Path(tempfile.gettempdir()) / f"orchestra-mcp-canary-{nonce}"
+
 
 class GrokMcpIsolationError(RuntimeError):
     """A worker session's MCP roster does not match Orchestra's launch plan."""
 
 
@@ -248,10 +261,12 @@ class GrokBackend(JsonRpcStdioTransport):
         self._tool_names: dict[str, str] = {}
         # turn_completed carries usage; the turn_end is emitted by the prompt completion.
         self._pending_usage: dict = {}
         self._model_context_window = GROK_CONTEXT_LIMITS.get(model, GROK_DEFAULT_CONTEXT)
         self._context_tokens: int | None = None
+        self._mcp_canary: str | None = None
+        self._issue_mcp_canary()
         # A matching name is insufficient: a repository can define another command under it.
         expected_configs = self._mcp_server_configs()
         self._expected_server_identities = {
             str(server["name"]): _mcp_server_identity(server)
             for server in expected_configs
@@ -278,10 +293,11 @@ class GrokBackend(JsonRpcStdioTransport):
         self._notifications = asyncio.Queue()
         self._disconnecting = False
         self._last_stderr = ""
         self._active_prompts = 0
         self._queue_depth = 0
+        self._issue_mcp_canary()
         expected_configs = self._mcp_server_configs()
         self._expected_server_identities = {
             str(server["name"]): _mcp_server_identity(server)
             for server in expected_configs
         }
@@ -455,10 +471,50 @@ class GrokBackend(JsonRpcStdioTransport):
                 "Grok MCP conformance failed: "
                 + "; ".join(failures)
                 + self._shadowing_hint(missing | unready)
                 + ". Refusing to run a worker without the exact Orchestra launch plan."
             )
+        await self._verify_mcp_canary()
+
+    def _issue_mcp_canary(self) -> None:
+        previous = self._mcp_canary
+        if previous and _ORCHESTRA_MCP_CANARY_RE.fullmatch(previous):
+            mcp_canary_proof_path(previous).unlink(missing_ok=True)
+        orchestra = self._mcp_servers.get("orchestra") or {}
+        if orchestra.get("command"):
+            self._mcp_canary = secrets.token_hex(16)
+        else:
+            self._mcp_canary = None
+
+    async def _verify_mcp_canary(self) -> None:
+        """Require our mcp_stdio.py to prove it is the process behind `orchestra`."""
+        nonce = self._mcp_canary
+        if not nonce:
+            return
+        path = mcp_canary_proof_path(nonce)
+        loop = asyncio.get_running_loop()
+        deadline = loop.time() + GROK_MCP_CANARY_TIMEOUT_SECONDS
+        while not path.is_file() and loop.time() < deadline:
+            await asyncio.sleep(0.05)
+        try:
+            if not path.is_file():
+                raise GrokMcpIsolationError(
+                    "Grok MCP conformance failed: orchestra canary handshake missing "
+                    "(server named 'orchestra' did not prove it is Orchestra's mcp_stdio). "
+                    "Refusing to run a worker without the exact Orchestra launch plan."
+                )
+            got = path.read_text(encoding="utf-8").strip()
+            if got != nonce:
+                raise GrokMcpIsolationError(
+                    "Grok MCP conformance failed: orchestra canary handshake mismatch. "
+                    "Refusing to run a worker without the exact Orchestra launch plan."
+                )
+        finally:
+            try:
+                path.unlink(missing_ok=True)
+            except OSError:
+                pass
 
     def _shadowing_hint(self, absent: set[str]) -> str:
         """Name the repo-local file that swallowed a server, when that is what happened.
 
         Grok merges project scope over every other source BY NAME and only then drops the
@@ -1041,10 +1097,12 @@ class GrokBackend(JsonRpcStdioTransport):
             if not command and not url:
                 continue
             if command:
                 env = dict(self._mcp_env)
                 env.update({str(k): str(v) for k, v in (cfg.get("env") or {}).items()})
+                if name == "orchestra" and self._mcp_canary:
+                    env[ORCHESTRA_MCP_CANARY_ENV] = self._mcp_canary
                 servers.append({
                     "name": name,
                     "type": "stdio",
                     "command": str(command),
                     "args": [str(a) for a in (cfg.get("args") or [])],
### 5e11d8772 fix: stabilize Grok session replay and chat finalization

diff --git a/app/backend_grok.py b/app/backend_grok.py
index f33ae2d50..ce76723b9 100644
--- a/app/backend_grok.py
+++ b/app/backend_grok.py
@@ -167,20 +167,75 @@ def _grok_cost(model: str, input_tokens: int, cached_tokens: int, output_tokens:
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
@@ -257,10 +312,20 @@ class GrokBackend(JsonRpcStdioTransport):
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
@@ -354,41 +419,55 @@ class GrokBackend(JsonRpcStdioTransport):
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
### 3c037bdb8 #290: cross-runtime handoff + канареечный скип по продовому предикату (scratch/290, вердикт #328)

diff --git a/app/backend_grok.py b/app/backend_grok.py
index ce76723b9..42a61c56c 100644
--- a/app/backend_grok.py
+++ b/app/backend_grok.py
@@ -12,10 +12,11 @@ import uuid
 from pathlib import Path
 from typing import AsyncIterator, Optional
 
 from app.backend_jsonrpc import JsonRpcStdioTransport, bounded_tool_arguments
 from app.events import AgentEvent
+from app.runtime_history import build_model_visible_manifest
 from app.usage_contract import AggregateUsage, TurnUsage, current_context
 
 logger = logging.getLogger(__name__)
 
 # Explicit configuration beats autodiscovery: an unrelated `grok` earlier in PATH must not
@@ -284,18 +285,20 @@ class GrokBackend(JsonRpcStdioTransport):
     def __init__(self, model: str, cwd: str, system_prompt: str = "",
                  resume_session_id: str | None = None,
                  mcp_env: dict[str, str] | None = None,
                  mcp_servers: dict | None = None,
                  reasoning_effort: str = "high",
-                 is_orchestrator: bool = False):
+                 is_orchestrator: bool = False,
+                 validation_profile: bool = False):
         self.model = model
         self.cwd = cwd
         self.system_prompt = system_prompt
         self._session_id: str | None = resume_session_id
         self._mcp_env: dict[str, str] = mcp_env or {}
         self._mcp_servers: dict = mcp_servers or {}
         self._is_orchestrator = is_orchestrator
+        self._validation_profile = validation_profile
         self.reasoning_effort = (
             reasoning_effort if reasoning_effort in GROK_REASONING_EFFORTS else "high"
         )
         self._proc: Optional[asyncio.subprocess.Process] = None
         self._reader_task: Optional[asyncio.Task] = None
@@ -348,10 +351,22 @@ class GrokBackend(JsonRpcStdioTransport):
 
     @property
     def session_id(self) -> Optional[str]:
         return self._session_id
 
+    def build_handoff_manifest(self, prepared, *, validation_profile: bool):
+        return build_model_visible_manifest(
+            runtime="grok",
+            model=self.model,
+            effective_window=self._model_context_window,
+            system_prompt=self.system_prompt,
+            prepared=prepared,
+            validation_profile=validation_profile,
+            project_docs=getattr(prepared, "project_docs", ()),
+            mcp_servers=self._mcp_servers,
+        )
+
     async def connect(self) -> None:
         if self.is_alive:
             return
         if self._proc is not None:
             await self.disconnect()
### b643c67e3 #230: горячее применение правок и живучесть ходов при рестарте

diff --git a/app/backend_grok.py b/app/backend_grok.py
index 42a61c56c..cbb3b253c 100644
--- a/app/backend_grok.py
+++ b/app/backend_grok.py
@@ -1,10 +1,11 @@
 """GrokBackend — wraps the Grok Build CLI (ACP over stdio) for agent sessions."""
 
 import asyncio
 import json
 import logging
+import contextlib
 import os
 import re
 import secrets
 import shutil
 import tempfile
@@ -291,10 +292,11 @@ class GrokBackend(JsonRpcStdioTransport):
                  validation_profile: bool = False):
         self.model = model
         self.cwd = cwd
         self.system_prompt = system_prompt
         self._session_id: str | None = resume_session_id
+        self._active_turn_id: str | None = None
         self._mcp_env: dict[str, str] = mcp_env or {}
         self._mcp_servers: dict = mcp_servers or {}
         self._is_orchestrator = is_orchestrator
         self._validation_profile = validation_profile
         self.reasoning_effort = (
@@ -351,10 +353,20 @@ class GrokBackend(JsonRpcStdioTransport):
 
     @property
     def session_id(self) -> Optional[str]:
         return self._session_id
 
+    @property
+    def active_turn_id(self) -> Optional[str]:
+        """Ход, которому принадлежат принятые байты (#230 T4).
+
+        Читается менеджером при передаче (`_hand_over_backend`) и возвращается обратно в
+        `adopt` следующим поколением. Без этого свойства ход после рестарта терял бы свой
+        идентификатор молча: `getattr` вернул бы пустую строку, и никто бы не заметил.
+        """
+        return getattr(self, "_active_turn_id", None)
+
     def build_handoff_manifest(self, prepared, *, validation_profile: bool):
         return build_model_visible_manifest(
             runtime="grok",
             model=self.model,
             effective_window=self._model_context_window,
@@ -411,20 +423,42 @@ class GrokBackend(JsonRpcStdioTransport):
         # braces: this stops most permission requests from being raised at all, and
         # _pick_allow_option answers correctly the ones that still are.
         cmd += ["--always-approve"]
         cmd += ["stdio"]
 
-        self._proc = await asyncio.create_subprocess_exec(
-            *cmd,
-            stdin=asyncio.subprocess.PIPE,
-            stdout=asyncio.subprocess.PIPE,
-            stderr=asyncio.subprocess.PIPE,
-            env=self._build_env(),
-            cwd=self.cwd,
-            # Codex hit asyncio's default 64KB StreamReader cap on long JSONL lines.
-            limit=16 * 1024 * 1024,
-        )
+        # СВОИ пайпы, а не выпрошенные у asyncio (#230 T6). Дескриптор, полученный из
+        # транспорта через `get_extra_info`, отдать в systemd можно, а принять обратно — нет:
+        # проба `kill -9` получила `Pipe transport is only for pipes, sockets and character
+        # devices`, агент остался без читателя и умер. То есть публикация «срабатывала»,
+        # ничего не защищая.
+        child_stdin, child_stdout, our_stdin, our_stdout = self.new_child_pipes()
+        try:
+            self._proc = await asyncio.create_subprocess_exec(
+                *cmd,
+                stdin=child_stdin,
+                stdout=child_stdout,
+                stderr=asyncio.subprocess.PIPE,
+                env=self._build_env(),
+                cwd=self.cwd,
+                # Codex hit asyncio's default 64KB StreamReader cap on long JSONL lines.
+                limit=16 * 1024 * 1024,
+            )
+        except BaseException:
+            for fd in (child_stdin, child_stdout, our_stdin, our_stdout):
+                with contextlib.suppress(OSError):
+                    os.close(fd)
+            raise
+        # Владение переходит в МОМЕНТ ВЫЗОВА, а не по его успеху: при частичной привязке один
+        # из концов уже принадлежит живому транспорту, и очистка не различит, какой именно.
+        attach_in, attach_out = our_stdin, our_stdout
+        our_stdin = our_stdout = None
+        await self.attach_owned_pipes(attach_in, attach_out, limit=16 * 1024 * 1024)
+        # Свои копии ДЕТСКИХ концов закрываем только теперь: пока они открыты, CLI никогда не
+        # увидит EOF. Закрытие ПОСЛЕ привязки означает, что при её сбое они останутся в руках,
+        # и CLI умрёт на EOF, а не повиснет на пайпе, который никто не читает.
+        os.close(child_stdin)
+        os.close(child_stdout)
         self._reader_task = asyncio.create_task(self._read_stdout())
         self._stderr_task = asyncio.create_task(self._drain_stderr())
         try:
             result = await self._request("initialize", {
                 "protocolVersion": 1,
@@ -643,10 +677,16 @@ class GrokBackend(JsonRpcStdioTransport):
         if not self.is_alive:
             await self.connect()
         if not self._session_id:
             raise RuntimeError("Grok session is not initialized")
         self._active_prompts += 1
+        # Идентификатор живого хода (#230 T8). Менеджер снимает его при передаче, а
+        # `adopt_backend` по пустому значению ставит IDLE вместо RUNNING — то есть без этой
+        # строки ход Grok считался бы законченным, и усыновлённый CLI отпускался бы на
+        # границе хода. Своего идентификатора протокол на этом шаге не даёт: ответ
+        # `session/prompt` приходит только В КОНЦЕ хода, поэтому берём свой.
+        self._active_turn_id = secrets.token_hex(8)
         # Fire without awaiting: the session/prompt response only resolves when that turn
         # ENDS, so awaiting here would block the caller for the whole turn.
         task = asyncio.create_task(self._request("session/prompt", {
             "sessionId": self._session_id,
             "prompt": [{"type": "text", "text": message}],
@@ -720,10 +760,15 @@ class GrokBackend(JsonRpcStdioTransport):
             return False
 
     async def disconnect(self) -> None:
         proc = self._proc
         if proc is None:
+            # У УСЫНОВЛЁННОГО бэкенда своего процесса нет, но есть читатель, транспорты и
+            # дескрипторы — выйти отсюда рано означало бы оставить их жить рядом с новым CLI
+            # (#230 T4). `teardown_adopted` гасит их и сигналит записанному процессу только
+            # после доказательства identity.
+            await self.teardown_adopted()
             self._cleanup_profile()
             return
         self._disconnecting = True
         if self._active_prompts > 0 and proc.returncode is None:
             await self.interrupt()
@@ -748,17 +793,46 @@ class GrokBackend(JsonRpcStdioTransport):
         self._queue_depth = 0
         self._cleanup_profile()
 
     # ── transport ──
 
+    async def adopt(self, fd_in: int, fd_out: int, session_id: str,
+                    active_turn_id: str | None = None, *,
+                    leftover: str = "", cli_pid: int = 0, cli_started_at: int = 0) -> None:
+        """Принять УЖЕ РАБОТАЮЩИЙ Grok CLI по унаследованным пайпам (#230 T4).
+
+        Процесс не поднимается и рукопожатия не шлётся: CLI пережил рестарт супервизора, он
+        уже инициализирован, и его ход продолжает стримить в fd_out. Повторный `initialize`
### 247fe6b37 fix: retarget models within every runtime

diff --git a/app/backend_grok.py b/app/backend_grok.py
index cbb3b253c..cb16f0976 100644
--- a/app/backend_grok.py
+++ b/app/backend_grok.py
@@ -363,10 +363,26 @@ class GrokBackend(JsonRpcStdioTransport):
         `adopt` следующим поколением. Без этого свойства ход после рестарта терял бы свой
         идентификатор молча: `getattr` вернул бы пустую строку, и никто бы не заметил.
         """
         return getattr(self, "_active_turn_id", None)
 
+    async def retarget_model(self, model: str) -> None:
+        """Switch the active ACP session without replacing its native history."""
+        if not self.is_alive or not self._session_id:
+            raise RuntimeError("Grok backend is not connected")
+        if self._active_prompts or self._events_active:
+            raise RuntimeError("cannot retarget Grok model while a turn is active")
+        result = await self._request("session/set_model", {
+            "sessionId": self._session_id,
+            "modelId": model,
+        })
+        self.model = model
+        self._model_context_window = GROK_CONTEXT_LIMITS.get(
+            model, GROK_DEFAULT_CONTEXT,
+        )
+        self._absorb_models((result or {}).get("models") or {})
+
     def build_handoff_manifest(self, prepared, *, validation_profile: bool):
         return build_model_visible_manifest(
             runtime="grok",
             model=self.model,
             effective_window=self._model_context_window,
### 498c0d149 Orchestra: migrate project state to .orchestra

diff --git a/docs/tasks/264/live_grok_worker.py b/docs/tasks/264/live_grok_worker.py
deleted file mode 100644
index 525034f1b..000000000
--- a/docs/tasks/264/live_grok_worker.py
+++ /dev/null
@@ -1,65 +0,0 @@
-#!/usr/bin/env python3
-"""Live end-to-end run of a Grok worker through Orchestra's real backend.
-
-Not a hand-rolled ACP client: this builds `GrokBackend` exactly the way `_grok_factory`
-does, connects (so `_verify_mcp_isolation` runs for real), and gives the agent a task that
-can only be completed by calling an Orchestra MCP tool. Prints the tool calls it made.
-"""
-import asyncio, os, sys
-from pathlib import Path
-
-ROOT = Path(__file__).resolve().parents[3]
-sys.path.insert(0, str(ROOT))
-os.environ.setdefault("ORCHESTRA_SKIP_DOTENV", "0")
-
-from app.backend_grok import GrokBackend
-from app.manager import _make_mcp_config
-
-PROMPT = (
-    "You are a test worker. Call the Orchestra MCP tool `list_agents` right now and reply "
-    "with the number of agents it returned, in the form COUNT=<n>. Do not do anything else."
-)
-
-
-async def main() -> None:
-    cwd = str(ROOT)
-    assert not (Path(cwd) / ".mcp.json").exists(), (
-        "this run must happen in a checkout without the colliding .mcp.json"
-    )
-    servers = _make_mcp_config("grok-live-264", "/home/kesha/orchestra", "worker")
-    mcp_env = {k: str(v) for cfg in servers.values() for k, v in cfg.get("env", {}).items()}
-    backend = GrokBackend(
-        model="grok-4.5", cwd=cwd,
-        system_prompt="You are an Orchestra worker. Be terse.",
-        mcp_env=mcp_env, mcp_servers=servers, reasoning_effort="low",
-    )
-    await backend.connect()
-    print(f"CONNECTED session={backend.session_id}")
-    print(f"MCP tool count reported by Grok: {backend._mcp_tool_count}")
-    print(f"started servers: {sorted(backend._started_servers)}")
-    print(f"ready servers:   {sorted(backend._ready_servers)}")
-
-    await backend.send(PROMPT)
-    tool_calls, texts = [], []
-    try:
-        async with asyncio.timeout(240):
-            async for ev in backend.events():
-                kind = getattr(ev, "type", None) or getattr(ev, "kind", None)
-                content = getattr(ev, "content", "")
-                if kind == "tool_call":
-                    tool_calls.append(content)
-                    print(f"TOOL_CALL: {str(content)[:200]}")
-                elif kind == "text":
-                    texts.append(content)
-                elif kind == "turn_end":
-                    break
-    except (TimeoutError, asyncio.TimeoutError):
-        print("TIMEOUT waiting for turn_end")
-    finally:
-        print("--- assistant text ---")
-        print("".join(str(t) for t in texts)[:2000])
-        print(f"--- tool calls: {len(tool_calls)} ---")
-        await backend.disconnect()
-
-
-asyncio.run(main())
diff --git a/docs/tasks/264/mutation_check.py b/docs/tasks/264/mutation_check.py
deleted file mode 100644
index 65cd425d9..000000000
--- a/docs/tasks/264/mutation_check.py
+++ /dev/null
@@ -1,64 +0,0 @@
-#!/usr/bin/env python3
-"""Mutation check: does the conformance gate actually catch broken MCP wiring?
-
-Connect-only (no turn), printing the marker before every phase:
-  1. baseline      — clean wiring                     -> must CONNECT
-  2. mutant-shadow — `.mcp.json` declaring `orchestra` -> must REFUSE and name the file
-  3. reverted      — file removed again                -> must CONNECT
-  4. mutant-cmd    — launch plan points at a missing binary -> must REFUSE
-  5. reverted-cmd  — plan restored                     -> must CONNECT
-
-The mutations are data (a JSON file, an in-memory plan), not `.py` source, so there is no
-`__pycache__` staleness to defeat — the reverted phases re-run the same module objects.
-"""
-import asyncio, json, sys
-from pathlib import Path
-
-ROOT = Path(__file__).resolve().parents[3]
-sys.path.insert(0, str(ROOT))
-from app.backend_grok import GrokBackend, GrokMcpIsolationError
-from app.manager import _make_mcp_config
-
-MCP_JSON = ROOT / ".mcp.json"
-SHADOW = json.dumps({"mcpServers": {"orchestra": {
-    "type": "stdio", "command": "/nonexistent/python",
-    "args": ["-m", "app.mcp_stdio"], "env": {"ORCHESTRA_ROLE": "shadow"}}}}, indent=2)
-
-
-async def attempt(label: str, break_command: bool = False) -> str:
-    servers = _make_mcp_config(f"grok-mut-{label}", "/home/kesha/orchestra", "worker")
-    if break_command:
-        servers["orchestra"]["command"] = "/nonexistent/python3"
-    mcp_env = {k: str(v) for cfg in servers.values() for k, v in cfg.get("env", {}).items()}
-    backend = GrokBackend(model="grok-4.5", cwd=str(ROOT), system_prompt="t",
-                          mcp_env=mcp_env, mcp_servers=servers, reasoning_effort="low")
-    try:
-        await backend.connect()
-        return f"CONNECTED tools={backend._mcp_tool_count} ready={sorted(backend._ready_servers)}"
-    except GrokMcpIsolationError as exc:
-        return f"REFUSED {exc}"
-    except Exception as exc:
-        return f"ERROR {type(exc).__name__}: {exc}"
-    finally:
-        await backend.disconnect()
-
-
-async def phase(name: str, *, shadow: bool = False, break_command: bool = False) -> None:
-    print(f"[{name}] .mcp.json present = {MCP_JSON.exists()}", flush=True)
-    print(f"  -> {await attempt(name, break_command=break_command)}\n", flush=True)
-
-
-async def main() -> None:
-    await phase("baseline")
-
-    MCP_JSON.write_text(SHADOW, encoding="utf-8")
-    await phase("mutant-shadow")
-
-    MCP_JSON.unlink()
-    await phase("reverted")
-
-    await phase("mutant-cmd", break_command=True)
-    await phase("reverted-cmd")
-
-
-asyncio.run(main())
diff --git a/docs/tasks/264/probe_collision.py b/docs/tasks/264/probe_collision.py
deleted file mode 100644
index 3e238b357..000000000
--- a/docs/tasks/264/probe_collision.py
+++ /dev/null
@@ -1,78 +0,0 @@
-#!/usr/bin/env python3
### f8e00522e #430: research .orchestra path migration

diff --git a/app/backend_grok.py b/app/backend_grok.py
index cb16f0976..ee686904f 100644
--- a/app/backend_grok.py
+++ b/app/backend_grok.py
@@ -64,20 +64,20 @@ mcps = false
 mcps = false
 """
 
 # Measured from the runtime, not from docs: initialize/session/new both report
 # totalContextTokens=500000 for grok-4.5 and grok-4.6. The bundled README's numbers disagree with the
-# runtime elsewhere (see docs/tasks/95/research.md), so the runtime value wins and any
+# runtime elsewhere (see .orchestra/tasks/95/research.md), so the runtime value wins and any
 # per-session value it reports overrides this fallback.
 GROK_CONTEXT_LIMITS = {
     "grok-4.6": 500000,
     "grok-4.5": 500000,
 }
 GROK_DEFAULT_CONTEXT = 500000
 
 # The 4.5 rate card was reconciled against runtime costUsdTicks to zero residual across three
-# turns (docs/tasks/95/research.md F7). The 4.6 card is published by xAI and reconciles with
+# turns (.orchestra/tasks/95/research.md F7). The 4.6 card is published by xAI and reconciles with
 # live #251 turns after the separately billed X-search call is removed.
 GROK_TOKEN_PRICES = {
     "grok-4.6": {"input": 2.0, "cached": 0.50, "output": 6.0},
     "grok-4.5": {"input": 2.0, "cached": 0.30, "output": 6.0},
 }
@@ -163,11 +163,11 @@ def _grok_cost(model: str, input_tokens: int, cached_tokens: int, output_tokens:
         return 0.0
     cached = min(max(0, cached_tokens), max(0, input_tokens))
     fresh = max(0, input_tokens - cached)
     # Deliberately a short-context fallback. ACP exposes a turn aggregate, while the 200k
     # tier applies per model request; a tool-loop can mix tiers. Runtime costUsdTicks remains
-    # the only exact source until ACP exposes per-request usage (docs/tasks/251/research.md).
+    # the only exact source until ACP exposes per-request usage (.orchestra/tasks/251/research.md).
     return (fresh * prices["input"] + cached * prices["cached"]
             + max(0, output_tokens) * prices["output"]) / 1_000_000
 
 
 def _content_text(content) -> str:
@@ -1308,11 +1308,11 @@ class GrokBackend(JsonRpcStdioTransport):
     @staticmethod
     def _classify_error(error: dict) -> str:
         """Classify structurally; text matching only as a last resort.
 
         The terminal quota-exhaustion shape is NOT known yet (could not exhaust SuperGrok —
-        see docs/tasks/95/research.md F7). Unknown errors stay "error" and fail loud rather
+        see .orchestra/tasks/95/research.md F7). Unknown errors stay "error" and fail loud rather
         than being guessed into a rate_limit that silently retries.
         """
         code = error.get("code")
         if code in (429,):
             return "rate_limit"
### e6da7e30a #537: stop runtime trees with Orchestra and remove live adoption

diff --git a/app/backend_grok.py b/app/backend_grok.py
index ee686904f..74e39f54f 100644
--- a/app/backend_grok.py
+++ b/app/backend_grok.py
@@ -292,11 +292,10 @@ class GrokBackend(JsonRpcStdioTransport):
                  validation_profile: bool = False):
         self.model = model
         self.cwd = cwd
         self.system_prompt = system_prompt
         self._session_id: str | None = resume_session_id
-        self._active_turn_id: str | None = None
         self._mcp_env: dict[str, str] = mcp_env or {}
         self._mcp_servers: dict = mcp_servers or {}
         self._is_orchestrator = is_orchestrator
         self._validation_profile = validation_profile
         self.reasoning_effort = (
@@ -353,19 +352,10 @@ class GrokBackend(JsonRpcStdioTransport):
 
     @property
     def session_id(self) -> Optional[str]:
         return self._session_id
 
-    @property
-    def active_turn_id(self) -> Optional[str]:
-        """Ход, которому принадлежат принятые байты (#230 T4).
-
-        Читается менеджером при передаче (`_hand_over_backend`) и возвращается обратно в
-        `adopt` следующим поколением. Без этого свойства ход после рестарта терял бы свой
-        идентификатор молча: `getattr` вернул бы пустую строку, и никто бы не заметил.
-        """
-        return getattr(self, "_active_turn_id", None)
 
     async def retarget_model(self, model: str) -> None:
         """Switch the active ACP session without replacing its native history."""
         if not self.is_alive or not self._session_id:
             raise RuntimeError("Grok backend is not connected")
@@ -693,16 +683,10 @@ class GrokBackend(JsonRpcStdioTransport):
         if not self.is_alive:
             await self.connect()
         if not self._session_id:
             raise RuntimeError("Grok session is not initialized")
         self._active_prompts += 1
-        # Идентификатор живого хода (#230 T8). Менеджер снимает его при передаче, а
-        # `adopt_backend` по пустому значению ставит IDLE вместо RUNNING — то есть без этой
-        # строки ход Grok считался бы законченным, и усыновлённый CLI отпускался бы на
-        # границе хода. Своего идентификатора протокол на этом шаге не даёт: ответ
-        # `session/prompt` приходит только В КОНЦЕ хода, поэтому берём свой.
-        self._active_turn_id = secrets.token_hex(8)
         # Fire without awaiting: the session/prompt response only resolves when that turn
         # ENDS, so awaiting here would block the caller for the whole turn.
         task = asyncio.create_task(self._request("session/prompt", {
             "sessionId": self._session_id,
             "prompt": [{"type": "text", "text": message}],
@@ -776,15 +760,10 @@ class GrokBackend(JsonRpcStdioTransport):
             return False
 
     async def disconnect(self) -> None:
         proc = self._proc
         if proc is None:
-            # У УСЫНОВЛЁННОГО бэкенда своего процесса нет, но есть читатель, транспорты и
-            # дескрипторы — выйти отсюда рано означало бы оставить их жить рядом с новым CLI
-            # (#230 T4). `teardown_adopted` гасит их и сигналит записанному процессу только
-            # после доказательства identity.
-            await self.teardown_adopted()
             self._cleanup_profile()
             return
         self._disconnecting = True
         if self._active_prompts > 0 and proc.returncode is None:
             await self.interrupt()
@@ -809,40 +788,12 @@ class GrokBackend(JsonRpcStdioTransport):
         self._queue_depth = 0
         self._cleanup_profile()
 
     # ── transport ──
 
-    async def adopt(self, fd_in: int, fd_out: int, session_id: str,
-                    active_turn_id: str | None = None, *,
-                    leftover: str = "", cli_pid: int = 0, cli_started_at: int = 0) -> None:
-        """Принять УЖЕ РАБОТАЮЩИЙ Grok CLI по унаследованным пайпам (#230 T4).
-
-        Процесс не поднимается и рукопожатия не шлётся: CLI пережил рестарт супервизора, он
-        уже инициализирован, и его ход продолжает стримить в fd_out. Повторный `initialize`
-        был бы не только семантически неверен, но и завис бы — поток молчит между событиями.
-        Ровно тот же контракт, что у Codex.
-        """
-        self._notifications = asyncio.Queue()
-        self._disconnecting = False
-        await self.adopt_pipes(fd_in, fd_out, limit=16 * 1024 * 1024,
-                               leftover=leftover, cli_pid=cli_pid,
-                               cli_started_at=cli_started_at)
-        self._session_id = session_id
-        self._active_turn_id = active_turn_id
-        # Промпт слал ПРЕДЫДУЩИЙ процесс, поэтому у этого объекта счётчик нулевой — а
-        # `events()` выходит, как только активных промптов и очереди нет (#230 T7). Пустой
-        # счётчик означал бы «ход кончился» на первом же событии: слушатель тихо умирал,
-        # статус падал в IDLE, и обновление на границе хода отпускало ЖИВОЙ CLI. Ход есть
-        # ровно тогда, когда нам передали его идентификатор.
-        self._active_prompts = 1 if active_turn_id else 0
-        self._reader_task = asyncio.create_task(self._read_stdout())
 
     async def _read_stdout(self) -> None:
-        # `self._out` — усыновлённый ридер, если он есть, иначе stdout своего процесса
-        # (#230 T4). Прежняя версия читала только `self._proc.stdout`, поэтому у принятого
-        # после рестарта бэкенда читатель не запускался вовсе: агент стримил в никуда и его
-        # ход не завершался никогда.
         stream = self._out
         if stream is None:
             return
         try:
             while True:
@@ -1234,11 +1185,10 @@ class GrokBackend(JsonRpcStdioTransport):
         key = str(prompt_id or "")
         if key and key in self._completed_prompts:
             return []
         # Ход кончился — идентификатора быть не должно (#230 T8). Иначе следующий рестарт
         # объявит RUNNING на сессии, где ход давно закрыт, и она зависнет навсегда.
-        self._active_turn_id = None
         if key:
             self._completed_prompts.add(key)
         self._active_prompts = max(0, self._active_prompts - 1)
         reason = str(stop_reason or "end_turn")
         ok = reason == "end_turn"