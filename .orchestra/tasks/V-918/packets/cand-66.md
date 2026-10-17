# Candidate cand-66

## ORIGIN commit 62e76da504 (2026-10-08): V-782: shared workflow admission scheduler and agent cgroup isolation
(diff of code only, excluding .orchestra/ and *.md; capped 1200 lines)

diff --git a/app/agent_cgroups.py b/app/agent_cgroups.py
new file mode 100644
index 000000000..d430d2a88
--- /dev/null
+++ b/app/agent_cgroups.py
@@ -0,0 +1,156 @@
+"""Place external agent commands in the delegated, resource-limited cgroup."""
+
+from __future__ import annotations
+
+import os
+from pathlib import Path
+
+
+# Fixed shares of the service limits, independent of current usage, so every startup
+# (and any re-run) yields the same values. high=75% throttles agents while the API and
+# orchestrators keep >= 25% of service.high; max=87.5% keeps the emergency margin
+# between the two limits for the API side.
+AGENTS_MEMORY_HIGH_SHARE = 0.75
+AGENTS_MEMORY_MAX_SHARE = 0.875
+
+
+def delegated_service_cgroup(proc_cgroup: Path = Path("/proc/self/cgroup"), root: Path = Path("/sys/fs/cgroup")) -> Path:
+    for line in proc_cgroup.read_text().splitlines():
+        if line.startswith("0::"):
+            current = root / line[3:].lstrip("/")
+            for candidate in (current, *current.parents):
+                if candidate.name == "orchestra.service":
+                    return candidate
+            break
+    raise RuntimeError("current process is not inside orchestra.service cgroup")
+
+
+def _read_limit(path: Path) -> int:
+    value = path.read_text().strip()
+    if value == "max":
+        raise RuntimeError(f"unbounded parent cgroup limit: {path}")
+    return int(value)
+
+
+def _read_weight(path: Path, prefix: str = "") -> int:
+    value = path.read_text().split()
+    if prefix:
+        value = [item for item in value if item != prefix]
+    return int(value[-1])
+
+
+def _move_processes(source_group: Path, destination_group: Path) -> None:
+    source = source_group / "cgroup.procs"
+    destination = destination_group / "cgroup.procs"
+    while True:
+        try:
+            pids = [int(value) for value in source.read_text().split()]
+        except OSError as error:
+            raise RuntimeError(f"cannot read delegated service processes: {error}") from error
+        if not pids:
+            return
+        moved = False
+        for pid in pids:
+            try:
+                destination.write_text(str(pid))
+            except ProcessLookupError:
+                moved = True
+            except OSError as error:
+                if error.errno != 3:
+                    raise RuntimeError(f"cannot move service process {pid} to orchestra-api: {error}") from error
+                moved = True
+            else:
+                moved = True
+        if not moved:
+            raise RuntimeError("delegated service cgroup did not make progress while evacuating processes")
+
+
+def configure_agent_cgroup(service: Path | None = None) -> Path:
+    service = service or delegated_service_cgroup()
+    _move_processes(service, service / "orchestra-api")
+    controllers = set((service / "cgroup.controllers").read_text().split())
+    required = {"cpu", "io", "memory"}
+    if not required.issubset(controllers):
+        raise RuntimeError(f"delegated cgroup controllers missing: {sorted(required - controllers)}")
+    subtree = service / "cgroup.subtree_control"
+    enabled = set(subtree.read_text().split())
+    missing = required - enabled
+    if missing:
+        with subtree.open("w") as stream:
+            stream.write(" ".join(f"+{name}" for name in sorted(missing)))
+    agents = service / "agents"
+    agents.mkdir(exist_ok=True)
+    workers = agents / "workers"
+    workers.mkdir(exist_ok=True)
+    # agents becomes an internal node (per-workflow groups need memory accounting),
+    # so every process must live in a leaf beneath it.
+    if (agents / "cgroup.procs").exists():
+        _move_processes(agents, workers)
+    agents_subtree = agents / "cgroup.subtree_control"
+    if not required.issubset(set(agents_subtree.read_text().split()) if agents_subtree.exists() else set()):
+        agents_subtree.write_text(" ".join(f"+{name}" for name in sorted(required)))
+    cpu_weight = max(1, _read_weight(service / "cpu.weight") // 2)
+    io_weight = max(1, _read_weight(service / "io.weight", "default") // 2)
+    values = {
+        "cpu.weight": str(cpu_weight),
+        "io.weight": f"default {io_weight}",
+        "memory.high": str(int(_read_limit(service / "memory.high") * AGENTS_MEMORY_HIGH_SHARE)),
+        "memory.max": str(int(_read_limit(service / "memory.max") * AGENTS_MEMORY_MAX_SHARE)),
+    }
+    for name, value in values.items():
+        path = agents / name
+        if path.exists() and path.read_text().strip() == value:
+            continue
+        path.write_text(value)
+    return agents
+
+
+def move_current_process(cgroup: str | None = None) -> None:
+    target = cgroup or os.environ.get("ORCHESTRA_AGENT_CGROUP", "")
+    if target:
+        (Path(target) / "cgroup.procs").write_text(str(os.getpid()))
+
+
+def _move_subprocess_before_exec() -> None:
+    target = os.environ.get("ORCHESTRA_AGENT_CGROUP", "")
+    if not target:
+        return
+    fd = os.open(Path(target) / "cgroup.procs", os.O_WRONLY)
+    try:
+        os.write(fd, str(os.getpid()).encode())
+    finally:
+        os.close(fd)
+
+
+def enter_workflow_cgroup(run_id: str) -> Path | None:
+    """Move this runner into its own leaf under agents so its memory is measurable alone."""
+    root = os.environ.get("ORCHESTRA_AGENT_ROOT", "")
+    if not root:
+        return None
+    group = Path(root) / f"workflow-{run_id}"
+    try:
+        group.mkdir(exist_ok=True)
+        (group / "cgroup.procs").write_text(str(os.getpid()))
+    except OSError:
+        return None
+    os.environ["ORCHESTRA_AGENT_CGROUP"] = str(group)
+    return group
+
+
+def leave_workflow_cgroup(group: Path | None) -> None:
+    if group is not None:
+        try:
+            group.rmdir()
+        except OSError:
+            pass
+
+
+def agent_process_options(orchestrator: bool = False) -> dict:
+    # Orchestrators stay beside the API: they are part of the service the agent limits protect.
+    if orchestrator:
+        return {}
+    if os.environ.get("ORCHESTRA_AGENT_CGROUP"):
+        return {"preexec_fn": _move_subprocess_before_exec}
+    if os.environ.get("ORCHESTRA_AGENT_CGROUP_REQUIRED") == "1":
+        raise RuntimeError("delegated agent cgroup is unavailable; refusing to launch provider process")
+    return {}
diff --git a/app/agent_cli_exec.py b/app/agent_cli_exec.py
new file mode 100755
index 000000000..5a3391dd5
--- /dev/null
+++ b/app/agent_cli_exec.py
@@ -0,0 +1,18 @@
+#!/usr/bin/env python3
+"""Move an SDK-launched provider CLI into the agent cgroup before exec."""
+
+import os
+import sys
+from pathlib import Path
+
+
+def main() -> None:
+    target = os.environ["ORCHESTRA_AGENT_CLI"]
+    cgroup = os.environ.get("ORCHESTRA_AGENT_CGROUP", "")
+    if cgroup:
+        (Path(cgroup) / "cgroup.procs").write_text(str(os.getpid()))
+    os.execvp(target, [target, *sys.argv[1:]])
+
+
+if __name__ == "__main__":
+    main()
diff --git a/app/backend_claude.py b/app/backend_claude.py
index 3631e793a..35c309a17 100644
--- a/app/backend_claude.py
+++ b/app/backend_claude.py
@@ -1083,22 +1083,26 @@ class ClaudeBackend:
             if not api_key:
                 raise RuntimeError("Claude API-credit route is missing its configured key")
             env["ANTHROPIC_API_KEY"] = api_key
         # Профиль: переопределяем CLAUDE_CONFIG_DIR подпроцесса (SDK строит
         # env как {**os.environ, **options.env}). Пусто → наследуем env процесса
         # orchestra (back-compat). expanduser — на случай "~" в config_dir.
         if self._config_dir:
             env["CLAUDE_CONFIG_DIR"] = os.path.expanduser(self._config_dir)
+        cli_path = cli
+        if os.environ.get("ORCHESTRA_AGENT_CGROUP") and not self._is_orchestrator:
+            cli_path = str(Path(__file__).with_name("agent_cli_exec.py"))
+            env["ORCHESTRA_AGENT_CLI"] = cli
         agent_uid = os.environ.get("ORCHESTRA_AGENT_UID")
         pretooluse_hooks = None
         if os.environ.get("CLAUDE_BASH_HOOK_ENABLED") == "1":
             pretooluse_hooks = _make_pretooluse_hooks(_classify_bash_payload, cwd=self.cwd)
         options = ClaudeAgentOptions(
-            model=self.model, cwd=self.cwd, cli_path=cli,
+            model=self.model, cwd=self.cwd, cli_path=cli_path,
             permission_mode="default", can_use_tool=_make_auto_approve(self._is_orchestrator),
             disallowed_tools=list(self._cli_disallowed_tools),
             hooks={"PreToolUse": pretooluse_hooks} if pretooluse_hooks is not None else None,
             include_partial_messages=True, max_turns=200,
             max_buffer_size=50 * 1024 * 1024,
             env=env,
             user=agent_uid,
             stderr=self._capture_stderr,
@@ -1155,21 +1159,24 @@ class ClaudeBackend:
         sdk_version = importlib.metadata.version("claude-agent-sdk")
         if sdk_version != CLAUDE_SDK_HISTORY_VERSION:
             raise NativeHistoryUnsupported(
                 "native Claude history requires claude-agent-sdk "
                 f"{CLAUDE_SDK_HISTORY_VERSION}, got {sdk_version}"
             )
         cli = shutil.which("claude") or os.environ.get("CLAUDE_CLI_PATH", "claude")
         try:
+            from app.agent_cgroups import agent_process_options
+
             process = await asyncio.create_subprocess_exec(
                 cli,
                 "--version",
                 stdout=asyncio.subprocess.PIPE,
                 stderr=asyncio.subprocess.PIPE,
+                **agent_process_options(),
             )
         except OSError as error:
             raise NativeHistoryUnsupported(
                 f"cannot verify Claude CLI history version: {err_text(error)}"
             ) from error
         try:
             stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=10)
         except asyncio.TimeoutError as error:
diff --git a/app/backend_codex.py b/app/backend_codex.py
index 9693b5ac3..156855b97 100644
--- a/app/backend_codex.py
+++ b/app/backend_codex.py
@@ -101,21 +101,24 @@ class CodexOversizedRecordError(RuntimeError):
     """The app-server JSONL framing was lost and this transport is unusable."""
 
 
 async def _run_process(
     *cmd: str,
     env: dict[str, str] | None = None,
     timeout: float = CODEX_PROCESS_TIMEOUT_SECONDS,
 ) -> tuple[int, str, str]:
+    from app.agent_cgroups import agent_process_options
+
     proc = await asyncio.create_subprocess_exec(
         *cmd,
         stdout=asyncio.subprocess.PIPE,
         stderr=asyncio.subprocess.PIPE,
         env=env,
+        **agent_process_options(),
     )
     try:
         stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
     except BaseException:
         if proc.returncode is None:
             proc.kill()
             await proc.wait()
         raise
@@ -652,29 +655,32 @@ class CodexBackend(JsonRpcStdioTransport):
         self._notifications = asyncio.Queue()
         self._disconnecting = False
         self._last_stderr = ""
         self._reader_failure = None
         self._terminal_reader_failure = False
         codex_cmd = self._codex_command()
 
         env = self._build_env()
-        self._process_group, self._scope_reason = RuntimeProcessGroup.create()
+        self._process_group, self._scope_reason = RuntimeProcessGroup.create(orchestrator=self._is_orchestrator)
         self._hibernate_safe = self._process_group is not None
         if self._process_group is None:
             logger.warning("Codex hibernation unavailable: %s", self._scope_reason)
         cmd = self._process_group.command(codex_cmd) if self._process_group else codex_cmd
         child_stdin = child_stdout = our_stdin = our_stdout = None
         try:
+            from app.agent_cgroups import agent_process_options
+
             child_stdin, child_stdout, our_stdin, our_stdout = self.new_child_pipes()
             spawn_started = time.monotonic()
             self._proc = await asyncio.create_subprocess_exec(
                 *cmd, stdin=child_stdin, stdout=child_stdout,
                 stderr=asyncio.subprocess.PIPE, env=env, cwd=self.cwd,
                 limit=CODEX_STREAM_LIMIT,
+                **agent_process_options(self._is_orchestrator),
             )
             self._log_connect_stage("cli_spawn", spawn_started)
             if our_stdin is not None:
                 # Ownership passes at the CALL, not on success: half-attached, one of these
                 # already belongs to a live transport and the cleanup below cannot tell which.
                 attach_in, attach_out = our_stdin, our_stdout
                 our_stdin = our_stdout = None
                 await self.attach_owned_pipes(attach_in, attach_out,
diff --git a/app/backend_grok.py b/app/backend_grok.py
index 74e39f54f..d7d0d3a9a 100644
--- a/app/backend_grok.py
+++ b/app/backend_grok.py
@@ -433,25 +433,28 @@ class GrokBackend(JsonRpcStdioTransport):
 
         # СВОИ пайпы, а не выпрошенные у asyncio (#230 T6). Дескриптор, полученный из
         # транспорта через `get_extra_info`, отдать в systemd можно, а принять обратно — нет:
         # проба `kill -9` получила `Pipe transport is only for pipes, sockets and character
         # devices`, агент остался без читателя и умер. То есть публикация «срабатывала»,
         # ничего не защищая.
         child_stdin, child_stdout, our_stdin, our_stdout = self.new_child_pipes()
         try:
+            from app.agent_cgroups import agent_process_options
+
             self._proc = await asyncio.create_subprocess_exec(
                 *cmd,
                 stdin=child_stdin,
                 stdout=child_stdout,
                 stderr=asyncio.subprocess.PIPE,
                 env=self._build_env(),
                 cwd=self.cwd,
                 # Codex hit asyncio's default 64KB StreamReader cap on long JSONL lines.
                 limit=16 * 1024 * 1024,
+                **agent_process_options(self._is_orchestrator),
             )
         except BaseException:
             for fd in (child_stdin, child_stdout, our_stdin, our_stdout):
                 with contextlib.suppress(OSError):
                     os.close(fd)
             raise
         # Владение переходит в МОМЕНТ ВЫЗОВА, а не по его успеху: при частичной привязке один
         # из концов уже принадлежит живому транспорту, и очистка не различит, какой именно.
diff --git a/app/bg_jobs.py b/app/bg_jobs.py
index 147005f5b..cfeb2ba2a 100644
--- a/app/bg_jobs.py
+++ b/app/bg_jobs.py
@@ -336,16 +336,24 @@ class BgJobManager:
         self._procs: dict[str, asyncio.subprocess.Process] = {}
         self._session_manager = None
 
     def set_session_manager(self, mgr) -> None:
         self._session_manager = mgr
 
     async def _spawn_managed_process(self, job_id, command, *, shell, **kwargs):
         """Register a process or kill it if the owner is cancelled during spawn."""
+        agent_workload = kwargs.pop("agent_workload", False)
+        if agent_workload:
+            cgroup = os.environ.get("ORCHESTRA_AGENT_CGROUP", "")
+            if not cgroup or not (Path(cgroup) / "cgroup.procs").exists():
+                raise RuntimeError("delegated agent cgroup is unavailable; workflow task remains queued")
+            env = dict(kwargs.pop("env", os.environ))
+            env["ORCHESTRA_AGENT_CGROUP"] = cgroup
+            kwargs["env"] = env
         spawn_task = asyncio.create_task(
             _spawn_bg_process(command, shell=shell, **kwargs)
         )
         proc = await _await_owned_spawn(spawn_task)
         self._procs[job_id] = proc
         return proc
 
     async def create(self, job_type: str, config: dict, message: str,
@@ -452,17 +460,18 @@ class BgJobManager:
                                        config["pattern"], message, target_name, target_scope,
                                        watch_timeout)
         elif job_type == "run":
             host = config.get("host")
             coro = self._run_exec(job_id, config["command"], message, target_name,
                                   target_scope, timeout, host=host,
                                   cwd=config.get("cwd"),
                                   success_file=config.get("success_file"),
-                                  success_pattern=config.get("success_pattern", ""))
+                                  success_pattern=config.get("success_pattern", ""),
+                                  agent_workload=bool(config.get("agent_workload")))
         elif job_type == "merge":
             coro = self._run_merge_watch(job_id, config["operation_id"], message,
                                          target_name, target_scope, timeout)
         elif job_type == "cron":
             coro = self._run_cron(job_id, config["cron_expr"], message,
                                   target_name, target_scope, watch_timeout)
         elif job_type == "cron_command":
             coro = self._run_cron(
@@ -1055,34 +1064,36 @@ class BgJobManager:
             self._fail_if_active(job_id, str(e)[:500])
         finally:
             self._procs.pop(job_id, None)
             if proc:
                 await _kill_proc(proc)
 
     async def _run_exec(self, job_id, command, message, target_name,
                         target_scope, timeout, host=None, success_file=None,
-                        success_pattern="", cwd=None):
+                        success_pattern="", cwd=None, agent_workload=False):
         proc = None
         reader_task = None
         output_buf = []
         try:
             # 16MB readline limit: Codex JSONL contains base64 images / long JSON lines
             # that exceed asyncio's default 64KB StreamReader limit → ValueError
             _STREAM_LIMIT = 16 * 1024 * 1024
             if host:
                 proc = await self._spawn_managed_process(
                     job_id, ["ssh", *_SSH_OPTS, host, command],
                     shell=False,
+                    agent_workload=agent_workload,
                     stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
                     limit=_STREAM_LIMIT,
                 )
             else:
                 proc = await self._spawn_managed_process(
                     job_id, command, shell=True,
+                    agent_workload=agent_workload,
                     stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
                     limit=_STREAM_LIMIT, cwd=cwd,
                 )
             self._procs[job_id] = proc
             where = host or "local"
             logger.info(f"bg_job {job_id}: run started pid={proc.pid} on={where} "
                         f"timeout={timeout}s cmd_len={len(command)}")
             last_progress = time.time()
diff --git a/app/harness/mcp.py b/app/harness/mcp.py
index 63b9cd304..571a0be0e 100644
--- a/app/harness/mcp.py
+++ b/app/harness/mcp.py
@@ -46,25 +46,28 @@ class _Server:
         self.tools: list[dict] = []           # this server's tools/list entries
         self.proc: asyncio.subprocess.Process | None = None
         self._reader: asyncio.Task | None = None
         self._pending: dict[int, asyncio.Future] = {}
         self._next_id = 0
         self._alive = False
 
     async def start(self) -> None:
+        from app.agent_cgroups import agent_process_options
+
         env = {**os.environ, **(self.cfg.get("env") or {})}
         self.proc = await asyncio.create_subprocess_exec(
             self.cfg["command"], *(self.cfg.get("args") or []),
             stdin=asyncio.subprocess.PIPE,
             stdout=asyncio.subprocess.PIPE,
             stderr=asyncio.subprocess.DEVNULL,   # server logs to stderr; drop to avoid pipe-fill block
             env={k: str(v) for k, v in env.items()},
             start_new_session=True,              # own process group → killpg can reap grandchildren
             limit=STDIO_LIMIT,
+            **agent_process_options(),
         )
         self._alive = True
         self._reader = asyncio.create_task(self._read_loop())
         await self._handshake()
 
     async def _handshake(self) -> None:
         await self._request("initialize", {
             "protocolVersion": PROTOCOL_VERSION,
diff --git a/app/main.py b/app/main.py
index 46b429dda..360fbdbbb 100644
--- a/app/main.py
+++ b/app/main.py
@@ -449,16 +449,40 @@ async def lifespan(app: FastAPI):
     import sys as _sys
     if "pytest" in _sys.modules:
         logger.warning("load_dotenv skipped: running under pytest")
     else:
         from dotenv import load_dotenv
         load_dotenv()
     from app import db as database
     database.DB_PATH = database._db_path_from_env()
+    from app.agent_cgroups import configure_agent_cgroup
+    if "pytest" in _sys.modules:
+        agent_cgroup = None
+        os.environ.pop("ORCHESTRA_AGENT_CGROUP", None)
+        os.environ.pop("ORCHESTRA_AGENT_ROOT", None)
+        os.environ.pop("ORCHESTRA_AGENT_CGROUP_REQUIRED", None)
+        agent_cgroup_error = "disabled under pytest"
+    else:
+        try:
+            agent_cgroup = configure_agent_cgroup()
+        except (OSError, RuntimeError, ValueError) as error:
+            agent_cgroup = None
+            agent_cgroup_error = str(error)
+            os.environ.pop("ORCHESTRA_AGENT_CGROUP", None)
+            os.environ.pop("ORCHESTRA_AGENT_ROOT", None)
+            os.environ["ORCHESTRA_AGENT_CGROUP_REQUIRED"] = "1"
+            logger.error("dynamic workflow cgroup setup failed: %s", error)
+        else:
+            os.environ["ORCHESTRA_AGENT_ROOT"] = str(agent_cgroup)
+            os.environ["ORCHESTRA_AGENT_CGROUP"] = str(agent_cgroup / "workers")
+            os.environ["ORCHESTRA_AGENT_CGROUP_REQUIRED"] = "1"
+            agent_cgroup_error = ""
+    app.state.agent_cgroup = str(agent_cgroup) if agent_cgroup else ""
+    app.state.agent_cgroup_error = agent_cgroup_error
     from app.session import validate_auto_compact_window_config
     validate_auto_compact_window_config()
     # Миграция V-576 идёт ДО init_db: тот отказывается стартовать на базе чужой
     # версии, а привести её к нужной — как раз задача миграции. От владельца при
     # этом требуется один рестарт и ни одной команды на остановленной системе.
     from app.startup_migration import migrate_v576
     from app.task_runtime import task_repository_path
     app.state.v576_migration = migrate_v576(database.DB_PATH, task_repository_path())
diff --git a/app/mcp_stdio.py b/app/mcp_stdio.py
index 6b92c3398..54788e578 100644
--- a/app/mcp_stdio.py
+++ b/app/mcp_stdio.py
@@ -3307,16 +3307,17 @@ async def dynamic_workflow(
     ]
     command = shlex.join(command_parts)
     manifest_path = runner_root / "data" / "workflow-runs" / run_id / "manifest.json"
     result = await _api("POST", "/api/bg/jobs", json={
         "type": "run",
         "config": {
             "command": command,
             "cwd": str(repo_path),
+            "agent_workload": True,
             "success_file": str(manifest_path),
             "success_pattern": r'"complete"\s*:\s*true',
         },
         "message": f"Dynamic workflow {run_id} ({total_tasks if stages is not None else len(tasks)} tasks, {mode})",
         "target_name": WORKER_NAME,
         "target_scope": SCOPE,
         "timeout_seconds": 3600,
         "created_by": WORKER_NAME,
diff --git a/app/pidfd_exec.py b/app/pidfd_exec.py
index bf7b990f1..188b8c7ac 100644
--- a/app/pidfd_exec.py
+++ b/app/pidfd_exec.py
@@ -1,16 +1,17 @@
 """Exec shim that hands its own pidfd to the parent before running a target."""
 
 import array
 import ctypes
 import errno
 import os
 import socket
 import sys
+from pathlib import Path
 
 
 PIDFD_SIGNAL_PROCESS_GROUP = 1 << 2
 
 _libc = ctypes.CDLL(None, use_errno=True)
 try:
     _pidfd_open = _libc.pidfd_open
     _pidfd_send_signal = _libc.pidfd_send_signal
@@ -119,16 +120,23 @@ def _send_pidfd(control: socket.socket, pidfd: int) -> None:
     )
 
 
 def main() -> int:
     if len(sys.argv) < 4 or sys.argv[2] not in {"shell", "argv"}:
         return 64
     control = socket.socket(fileno=int(sys.argv[1]))
     try:
+        try:
+            cgroup = os.environ.get("ORCHESTRA_AGENT_CGROUP", "")
+            if cgroup:
+                (Path(cgroup) / "cgroup.procs").write_text(str(os.getpid()))
+        except OSError as exc:
+            control.send((f"E{exc.errno}:{exc.strerror}").encode())
+            return 70
         try:
             pidfd = pidfd_open_self()
         except OSError as exc:
             control.send((f"E{exc.errno}:{exc.strerror}").encode())
             return 70
         try:
             _send_pidfd(control, pidfd)
         finally:
diff --git a/app/routes/bg.py b/app/routes/bg.py
index a9d404b85..8bfef4635 100644
--- a/app/routes/bg.py
+++ b/app/routes/bg.py
@@ -66,16 +66,19 @@ def _workflow_answer_preview(value) -> str:
     text = " ".join(str(text).split())
     return text[:280] + ("…" if len(text) > 280 else "")
 
 
 def _workflow_finished(run_dir: Path) -> bool:
     manifest = run_dir / "manifest.json"
     journal = run_dir / "journal.jsonl"
     try:
+        data = _read_workflow_json(manifest, default={})
+        if isinstance(data, dict) and isinstance(data.get("finished"), bool):
+            return data["finished"]
         return manifest.is_file() and (
             not journal.exists() or manifest.stat().st_mtime_ns >= journal.stat().st_mtime_ns
         )
     except OSError:
         return manifest.is_file()
 
 
 def _workflow_detail(run_id: str, run_dir: Path) -> dict:
@@ -120,45 +123,48 @@ def _workflow_detail(run_id: str, run_dir: Path) -> dict:
         items = []
         for task_no, task in enumerate(group):
             label = str(task.get("label") or f"Task {task_no + 1}")
             event = task_states.get(label, {})
             status = "pending"
             reason = event.get("reason") or event.get("event")
             if reason == "completed":
                 status = "completed" if event.get("value") is not None else "failed"
+            elif reason == "slot_waiting":
+                status = "waiting"
             elif reason in {"prepare_failed", "schema_invalid", "skipped", "accounting_failed"}:
                 status = "failed"
-            elif reason in {"task_started", "dispatched", "attempt_finished"}:
+            elif reason in {"task_started", "dispatched", "attempt_finished", "slot_acquired"}:
                 status = "running"
             value = flat_results[global_index] if global_index < len(flat_results) else None
             if value is not None:
                 status = "completed"
             elif manifest and (manifest.get("complete") or manifest.get("partial_reason")) and status == "pending":
                 status = "failed"
             call_key = str(value.get("value_id")) if isinstance(value, dict) else str(event.get("call_key") or "")
             result_url = f"/api/bg/workflows/{run_id}/results/{global_index}"
             items.append({
                 "index": task_no,
                 "global_index": global_index,
                 "label": label,
                 "model": str(task.get("model") or "gpt-6-luna"),
                 "status": status,
                 "reason": str(event.get("reason") or (event.get("event") if status == "failed" else "") or ""),
+                "position": event.get("position"),
                 "error": str(event.get("error") or ""),
                 "answer_preview": _workflow_answer_preview(value.get("data")) if finished and isinstance(value, dict) else None,
                 "result_url": result_url if finished and value is not None else "",
                 "call_key": call_key,
             })
             global_index += 1
         stages.append({"index": stage_no, "tasks": items})
 
     tasks = [task for stage in stages for task in stage["tasks"]]
     counts = {state: sum(task["status"] == state for task in tasks)
-              for state in ("running", "completed", "failed", "pending")}
+              for state in ("running", "waiting", "completed", "failed", "pending")}
     created_at = request.get("dashboard", {}).get("created_at")
     if not created_at:
         try:
             created_at = datetime.fromtimestamp((run_dir / "request.json").stat().st_mtime, timezone.utc).isoformat()
         except FileNotFoundError:
             created_at = ""
     ended_at = ""
     if manifest:
@@ -175,36 +181,83 @@ def _workflow_detail(run_id: str, run_dir: Path) -> dict:
     return {
         "run_id": run_id,
         "mode": request.get("mode", "parallel"),
         "task_id": request.get("dashboard", {}).get("task_id", ""),
         "repo": request.get("dashboard", {}).get("repo", ""),
         "budget_usd": request.get("dashboard", {}).get("budget_usd", manifest.get("budget_usd")),
         "max_calls": request.get("dashboard", {}).get("max_calls"),
         "max_concurrency": request.get("dashboard", {}).get("max_concurrency"),
+        "scheduler": manifest.get("scheduler") or {},
         "spent_usd": manifest.get("spent_usd", 0),
         "complete": bool(manifest.get("complete", False)),
         "finished": finished,
         "partial_reason": manifest.get("partial_reason"),
         "elapsed_seconds": elapsed_seconds,
         "counts": counts,
         "stages": stages,
         "available": bool(tasks_flat),
     }
 
 
+class WorkflowSlotRequest(BaseModel):
+    request_id: str
+    run_id: str
+    label: str = ""
+
+
+class WorkflowSlotRelease(BaseModel):
+    request_id: str
+
+
+@router.post("/workflow-scheduler/acquire")
+async def bg_workflow_slot_acquire(req: WorkflowSlotRequest, request: Request):
+    if not req.request_id or len(req.request_id) > 512 or not req.run_id or len(req.run_id) > 128:
+        return JSONResponse({"error": "invalid workflow slot identity"}, status_code=400)
+    if not getattr(request.app.state, "agent_cgroup", ""):
+        return JSONResponse({"error": "agent cgroup unavailable", "detail": getattr(request.app.state, "agent_cgroup_error", "")}, status_code=503)
+    try:
+        from app.workflow_scheduler import get_scheduler
+        return get_scheduler().acquire(req.request_id, req.run_id, req.label)
+    except (OSError, RuntimeError, ValueError) as error:
+        return JSONResponse({"error": f"workflow scheduler unavailable: {error}"}, status_code=503)
+
+
+@router.post("/workflow-scheduler/release")
+async def bg_workflow_slot_release(req: WorkflowSlotRelease):
+    from app.workflow_scheduler import get_scheduler
+    scheduler = get_scheduler()
+    scheduler.release(req.request_id)
+    return {"released": True, **scheduler.snapshot()}
+
+
+@router.get("/workflow-scheduler")
+async def bg_workflow_scheduler_status(request: Request):
+    if not getattr(request.app.state, "agent_cgroup", ""):
+        return JSONResponse({"error": "agent cgroup unavailable"}, status_code=503)
+    from app.workflow_scheduler import get_scheduler
+    return get_scheduler().snapshot()
+
+
 @router.get("/workflows/{run_id}")
-async def bg_workflow_detail(run_id: str):
+async def bg_workflow_detail(run_id: str, request: Request):
     run_dir = _workflow_run_dir(run_id)
     if run_dir is None:
         return JSONResponse({"error": "not found"}, status_code=404, headers=_WORKFLOW_HEADERS)
     if not run_dir.is_dir():
         return JSONResponse({"error": "not found"}, status_code=404, headers=_WORKFLOW_HEADERS)
     try:
-        return JSONResponse(_workflow_detail(run_id, run_dir), headers=_WORKFLOW_HEADERS)
+        detail = _workflow_detail(run_id, run_dir)
+        if getattr(request.app.state, "agent_cgroup", ""):
+            try:
+                from app.workflow_scheduler import get_scheduler
+                detail["scheduler"] = get_scheduler().snapshot()
+            except (OSError, RuntimeError, ValueError):
+                pass
+        return JSONResponse(detail, headers=_WORKFLOW_HEADERS)
     except (OSError, UnicodeDecodeError, json.JSONDecodeError):
         return JSONResponse(
             {"error": "workflow data unavailable"},
             status_code=500,
             headers=_WORKFLOW_HEADERS,
         )
 
 
diff --git a/app/runtime_process_group.py b/app/runtime_process_group.py
index cbb30eab0..0932dd3f5 100644
--- a/app/runtime_process_group.py
+++ b/app/runtime_process_group.py
@@ -9,22 +9,26 @@ import sys
 import uuid
 
 
 class RuntimeProcessGroup:
     def __init__(self, path: Path):
         self.path = path
 
     @classmethod
-    def create(cls) -> tuple['RuntimeProcessGroup | None', str]:
+    def create(cls, orchestrator: bool = False) -> tuple['RuntimeProcessGroup | None', str]:
         path = None
         try:
-            row = next(line for line in Path('/proc/self/cgroup').read_text().splitlines()
-                       if line.startswith('0::'))
-            parent = Path('/sys/fs/cgroup') / row[3:].lstrip('/')
+            delegated_agents = None if orchestrator else os.environ.get('ORCHESTRA_AGENT_CGROUP')
+            if delegated_agents:
+                parent = Path(delegated_agents)
+            else:
+                row = next(line for line in Path('/proc/self/cgroup').read_text().splitlines()
+                           if line.startswith('0::'))
+                parent = Path('/sys/fs/cgroup') / row[3:].lstrip('/')
             path = parent / f'runtime-{uuid.uuid4().hex}'
             path.mkdir()
             # Only process ownership is delegated; we do not enable controllers.
             for name in ('cgroup.procs', 'cgroup.kill'):
                 fd = os.open(path / name, os.O_WRONLY | os.O_CLOEXEC)
                 os.close(fd)
             return cls(path), ''
         except (OSError, StopIteration) as error:
diff --git a/app/static/js/chat.js b/app/static/js/chat.js
index 6482cd588..6a782bd3d 100644
--- a/app/static/js/chat.js
+++ b/app/static/js/chat.js
@@ -2359,36 +2359,47 @@ function _renderWorkflowStatus(card, data) {
     const detail = card.querySelector('[data-role="workflow-detail"]');
     if (!status || !detail) return;
     const counts = data.counts || {};
     const total = Object.values(counts).reduce((sum, value) => sum + Number(value || 0), 0);
     const isComplete = Boolean(data.complete && data.finished);
     const isPartial = Boolean(data.finished && !data.complete);
     const tone = counts.failed ? '#f87171' : isComplete ? '#4ade80' : '#38bdf8';
     status.style.color = tone;
-    status.textContent = `${isComplete ? T('✅ Complete') : isPartial ? T('⚠️ Partial') : T('⏳ In progress')} · ${T('{completed}/{total} ready', {completed: counts.completed || 0, total})} · ${T('{running} running', {running: counts.running || 0})} · ${T('{failed} failed', {failed: counts.failed || 0})} · ${MODEL_COST_CURRENCY}${Number(data.spent_usd || 0).toFixed(2)} / ${MODEL_COST_CURRENCY}${Number(data.budget_usd || 0).toFixed(2)} · ${_workflowElapsed(data.elapsed_seconds)}`;
+    status.textContent = `${isComplete ? T('✅ Complete') : isPartial ? T('⚠️ Partial') : T('⏳ In progress')} · ${T('{completed}/{total} ready', {completed: counts.completed || 0, total})} · ${T('{running} running', {running: counts.running || 0})} · ${T('{waiting} waiting', {waiting: counts.waiting || 0})} · ${T('{failed} failed', {failed: counts.failed || 0})} · ${MODEL_COST_CURRENCY}${Number(data.spent_usd || 0).toFixed(2)} / ${MODEL_COST_CURRENCY}${Number(data.budget_usd || 0).toFixed(2)} · ${_workflowElapsed(data.elapsed_seconds)}`;
     detail.replaceChildren();
+    const scheduler = data.scheduler || {};
+    if (scheduler.limit != null) {
+        const line = document.createElement('div');
+        line.style.cssText = 'margin-top:5px;color:#94a3b8;font-size:10px';
+        line.textContent = T('Shared slots {active}/{limit} · queued {queued} · {reason}', {
+            active: Number(scheduler.active || 0), limit: Number(scheduler.limit),
+            queued: Number(scheduler.queued || 0),
+            reason: String(scheduler.reason || ''),
+        });
+        detail.appendChild(line);
+    }
     for (const stage of data.stages || []) {
         const section = document.createElement('div');
         section.style.cssText = 'display:flex;flex-direction:column;gap:3px;margin-top:5px';
         if (card.dataset.workflowMode === 'stages') {
             const heading = document.createElement('div');
             heading.style.cssText = 'font-size:10px;color:#a78bfa;font-weight:600';
             heading.textContent = T('Stage {n}', {n: Number(stage.index) + 1});
             section.appendChild(heading);
         }
         for (const task of stage.tasks || []) {
             const row = document.createElement('div');
             row.style.cssText = 'padding:5px 7px;border-radius:6px;background:rgba(30,41,59,.38);font-size:10px;color:#cbd5e1';
-            const state = {running: '🔵', completed: '✅', failed: '❌', pending: '◯'}[task.status] || '◯';
+            const state = {running: '🔵', waiting: '⏳', completed: '✅', failed: '❌', pending: '◯'}[task.status] || '◯';
             const line = document.createElement('div');
             line.style.cssText = 'display:flex;gap:7px;align-items:center';
             const label = document.createElement('span'); label.style.cssText = 'color:#64748b;flex:1'; label.textContent = task.label || '';
             const model = document.createElement('span'); model.style.cssText = 'color:#a78bfa;flex:none'; model.textContent = _workflowModelLabel(task.model);
-            const badge = document.createElement('span'); badge.textContent = state; badge.title = task.status || '';
+            const badge = document.createElement('span'); badge.textContent = task.status === 'waiting' ? T('⏳ queue {position}', {position: task.position || '?'}) : state; badge.title = task.status === 'waiting' ? T('Waiting in shared queue · position {position}', {position: task.position || '?'}) : task.status || '';
             line.append(label, model, badge);
             row.appendChild(line);
             if (task.error) {
                 const error = document.createElement('div'); error.style.cssText = 'margin:4px 0 0 22px;color:#fca5a5;white-space:pre-wrap;overflow-wrap:anywhere'; error.textContent = task.error;
                 row.appendChild(error);
             }
             const answerPreview = task.answer_preview ?? task.answer;
             if (answerPreview != null) {
diff --git a/app/static/js/i18n.js b/app/static/js/i18n.js
index 9d4215c81..1b9259e8c 100644
--- a/app/static/js/i18n.js
+++ b/app/static/js/i18n.js
@@ -549,16 +549,20 @@
     '{n} files': 'файлов: {n}',
     '{n} tokens': 'токенов: {n}',
     '{n} turns': 'ходов: {n}',
     '{n} unaccounted': 'неучтённых: {n}',
     '{pct}% context': '{pct}% контекста',
     '{priced} priced turns': 'платных ходов: {priced}',
     '{status} {age}': '{status} {age}',
     '{total} total · {counts}': '{total} всего · {counts}',
+    '{waiting} waiting': 'в очереди: {waiting}',
+    'Shared slots {active}/{limit} · queued {queued} · {reason}': 'Общие слоты {active}/{limit} · в очереди {queued} · {reason}',
+    'Waiting in shared queue · position {position}': 'Ожидает общий слот · позиция {position}',
+    '⏳ queue {position}': '⏳ очередь {position}',
     '± Live turn diff': '± Изменения текущего хода',
     '↓ New messages below': '↓ Новые ниже',
     '↪ Message steered into the current Codex turn': '↪ Сообщение вставлено в текущий ход Codex',
     '↻ Refresh': '↻ обновить',
     '↻ Restoring generated image': '↻ Восстановление созданного изображения',
     '⌁ Codex still working': '⌁ Codex ещё работает',
     '⏱ Waiting {n}s': '⏱ Ожидание {n} с',
     '⏳': '⏳',
diff --git a/app/workflow_scheduler.py b/app/workflow_scheduler.py
new file mode 100644
index 000000000..fc0665c4f
--- /dev/null
+++ b/app/workflow_scheduler.py
@@ -0,0 +1,259 @@
+"""Durable, process-wide admission control for dynamic workflow model calls."""
+
+from __future__ import annotations
+
+import os
+import sqlite3
+import time
+from pathlib import Path
+
+
+def _read_number(path: Path) -> int | None:
+    try:
+        value = path.read_text().strip()
+        return int(value) if value != "max" else None
+    except (OSError, ValueError):
+        return None
+
+
+def _pressure(path: Path) -> float | None:
+    try:
+        for line in path.read_text().splitlines():
+            if line.startswith("some "):
+                return float(dict(item.split("=", 1) for item in line.split()[1:])["avg10"])
+    except (OSError, ValueError, KeyError):
+        return None
+    return None
+
+
+def resource_snapshot(cgroup: Path | None = None, proc: Path = Path("/proc")) -> dict:
+    cgroup = cgroup or Path(os.environ.get(
+        "ORCHESTRA_AGENT_ROOT", "/sys/fs/cgroup/system.slice/orchestra.service/agents",
+    ))
+    try:
+        cpu_count = len(os.sched_getaffinity(0))
+    except AttributeError:
+        cpu_count = os.cpu_count() or 1
+    try:
+        quota, period = (cgroup / "cpu.max").read_text().split()
+        if quota != "max":
+            cpu_count = min(cpu_count, max(1, int(quota) / int(period)))
+    except (OSError, ValueError, ZeroDivisionError):
+        pass
+    high = _read_number(cgroup / "memory.high")
+    maximum = _read_number(cgroup / "memory.max")
+    current = _read_number(cgroup / "memory.current") or 0
+    service = cgroup.parent
+    service_high = _read_number(service / "memory.high")
+    service_maximum = _read_number(service / "memory.max")
+    service_current = _read_number(service / "memory.current") or 0
+    cpu_pressure = _pressure(proc / "pressure/cpu")
+    memory_pressure = _pressure(proc / "pressure/memory")
+    return {
+        "cpu_count": cpu_count,
+        "cpu_capacity": int(cpu_count),
+        "memory_high": high,
+        "memory_max": maximum,
+        "memory_current": current,
+        "service_memory_high": service_high,
+        "service_memory_max": service_maximum,
+        "service_memory_current": service_current,
+        "cpu_pressure": cpu_pressure,
+        "memory_pressure": memory_pressure,
+    }
+
+
+def run_memory(run_id: str) -> int:
+    """Memory of one workflow runner's own cgroup; 0 when it is not measurable."""
+    root = os.environ.get("ORCHESTRA_AGENT_ROOT", "")
+    return (_read_number(Path(root) / f"workflow-{run_id}" / "memory.current") or 0) if root else 0
+
+
+def _prune_empty_run_groups(active_run_ids: set[str]) -> None:
+    root = os.environ.get("ORCHESTRA_AGENT_ROOT", "")
+    if not root:
+        return
+    try:
+        for group in Path(root).glob("workflow-*"):
+            if group.name[len("workflow-"):] not in active_run_ids:
+                try:
+                    group.rmdir()  # fails while populated, which is the safe answer
+                except OSError:
+                    pass
+    except OSError:
+        pass
+
+
+def calculate_limit(snapshot: dict, active: int, average_task_bytes: int) -> tuple[int, str]:
+    cpu_count = max(1, int(snapshot.get("cpu_capacity", snapshot["cpu_count"])))
+    high = snapshot.get("memory_high")
+    maximum = snapshot.get("memory_max")
+    current = max(0, int(snapshot.get("memory_current") or 0))
+    memory_headrooms = [max(0, int(limit) - current) for limit in (high, maximum) if limit is not None]
+    service_current = max(0, int(snapshot.get("service_memory_current") or 0))
+    memory_headrooms.extend(
+        max(0, int(limit) - service_current)
+        for limit in (snapshot.get("service_memory_high"), snapshot.get("service_memory_max"))
+        if limit is not None
+    )
+    headroom = min(memory_headrooms) if memory_headrooms else 0
+    memory_limit = headroom // average_task_bytes if average_task_bytes else 1
+    cpu_pressure = snapshot.get("cpu_pressure")
+    memory_pressure = snapshot.get("memory_pressure")
+    if cpu_pressure is None or memory_pressure is None:
+        pressure_factor = 0.0
+        pressure_limit = 0
+        pressure_detail = "unavailable=>0"
+    else:
+        pressure_factor = max(0.0, 1.0 - max(float(cpu_pressure), float(memory_pressure)) / 100)
+        pressure_limit = int(cpu_count * pressure_factor)
+        pressure_detail = f"{pressure_factor:.3f}=>{pressure_limit}"
+    limit = max(0, min(cpu_count, memory_limit, pressure_limit))
+    idle_floor = False
+    # With nothing running the queue must still move while the host is not saturated.
+    if active == 0 and limit == 0 and cpu_pressure is not None and memory_pressure is not None \
+            and max(float(cpu_pressure), float(memory_pressure)) < 90:
+        limit, idle_floor = 1, True
+    memory_detail = (
+        f"{headroom}/{average_task_bytes}={memory_limit}"
+        if average_task_bytes else f"{headroom}/measuring=>{memory_limit}"
+    )
+    reason = (
+        f"min(cpu={cpu_count}, memory_headroom={memory_detail}, pressure_factor={pressure_detail}); "
+        f"active={active}, avg_task_memory={average_task_bytes or 'measuring'}"
+        + ("; idle floor=1" if idle_floor else "")
+    )
+    return limit, reason
+
+
+class WorkflowScheduler:
+    def __init__(self, db_path: Path, *, snapshot=resource_snapshot, lease_seconds: int = 90,
+                 run_memory_reader=run_memory):
+        self.db_path = Path(db_path)
+        self.run_memory_reader = run_memory_reader
+        self.snapshot_reader = snapshot
+        self.lease_seconds = lease_seconds
+        self.db_path.parent.mkdir(parents=True, exist_ok=True)
+        with self._connect() as db:
+            db.execute("PRAGMA journal_mode=WAL")
+            db.executescript("""
+                CREATE TABLE IF NOT EXISTS requests (
+                    request_id TEXT PRIMARY KEY,
+                    run_id TEXT NOT NULL,
+                    label TEXT NOT NULL DEFAULT '',
+                    queued_at REAL NOT NULL,
+                    last_seen REAL NOT NULL,
+                    lease_until REAL,
+                    granted_at REAL,
+                    memory_sample INTEGER NOT NULL DEFAULT 0
+                );
+                CREATE INDEX IF NOT EXISTS requests_queue ON requests(queued_at);
+                CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT NOT NULL);
+                INSERT OR IGNORE INTO state(key, value) VALUES ('avg_task_bytes', '0');
+                INSERT OR IGNORE INTO state(key, value) VALUES ('sample_count', '0');
+                INSERT OR IGNORE INTO state(key, value) VALUES ('last_run', '');
+            """)
+
+    def _connect(self):
+        db = sqlite3.connect(self.db_path, timeout=10, isolation_level=None)
+        db.row_factory = sqlite3.Row
+        db.execute("PRAGMA busy_timeout=10000")
+        return db
+
+    def acquire(self, request_id: str, run_id: str, label: str = "") -> dict:
+        now = time.time()
+        with self._connect() as db:
+            db.execute("BEGIN IMMEDIATE")
+            db.execute("DELETE FROM requests WHERE last_seen < ?", (now - self.lease_seconds,))
+            _prune_empty_run_groups({row[0] for row in db.execute("SELECT DISTINCT run_id FROM requests")} | {run_id})
+            db.execute(
+                "INSERT OR IGNORE INTO requests(request_id, run_id, label, queued_at, last_seen) VALUES (?, ?, ?, ?, ?)",
+                (request_id, run_id, label, now, now),
+            )
+            db.execute("UPDATE requests SET last_seen=?, lease_until=CASE WHEN lease_until IS NULL THEN NULL ELSE ? END WHERE request_id=?",
+                       (now, now + self.lease_seconds, request_id))
+            snapshot = self.snapshot_reader()
+            active = db.execute("SELECT count(*) FROM requests WHERE lease_until IS NOT NULL").fetchone()[0]
+            average = int(db.execute("SELECT value FROM state WHERE key='avg_task_bytes'").fetchone()[0])
+            run_active = db.execute(
+                "SELECT count(*) FROM requests WHERE run_id=? AND lease_until IS NOT NULL", (run_id,)).fetchone()[0]
+            run_bytes = self.run_memory_reader(run_id) if run_active else 0
+            if run_bytes > 0:
+                db.execute("UPDATE requests SET memory_sample=max(memory_sample, ?) WHERE request_id=? AND lease_until IS NOT NULL",
+                           (run_bytes // run_active, request_id))
+            limit, reason = calculate_limit(snapshot, active, average)
+            current = db.execute("SELECT * FROM requests WHERE request_id=?", (request_id,)).fetchone()
+            if current["lease_until"] is not None:
+                queued = db.execute("SELECT count(*) FROM requests WHERE lease_until IS NULL").fetchone()[0]
+                db.commit()
+                return {"granted": True, "position": 0, "active": active, "queued": queued,
+                        "limit": limit, "reason": reason}
+            queue = db.execute("""
+                SELECT request_id, run_id, queued_at FROM requests
+                WHERE lease_until IS NULL ORDER BY queued_at, request_id
+            """).fetchall()
+            by_run = {}
+            for row in queue:
+                by_run.setdefault(row["run_id"], []).append(row)
+            last_run = db.execute("SELECT value FROM state WHERE key='last_run'").fetchone()[0]
+            run_order = sorted(by_run, key=lambda run: by_run[run][0]["queued_at"])
+            if last_run in run_order:
+                start = run_order.index(last_run)
+                run_order = run_order[start + 1:] + run_order[:start + 1]
+            ordered = []
+            while any(by_run.values()):
+                for run in run_order:
+                    if by_run[run]:
+                        ordered.append(by_run[run].pop(0)["request_id"])
+            if active < limit and ordered and ordered[0] == request_id:
+                db.execute("UPDATE requests SET lease_until=?, granted_at=? WHERE request_id=?",
+                           (now + self.lease_seconds, now, request_id))
+                db.execute("UPDATE state SET value=? WHERE key='last_run'", (run_id,))
+                queued = db.execute("SELECT count(*) FROM requests WHERE lease_until IS NULL").fetchone()[0]
+                db.commit()
+                return {"granted": True, "position": 0, "active": active + 1, "queued": queued,
+                        "limit": limit, "reason": reason}
+            position = ordered.index(request_id) + 1 if request_id in ordered else len(queue)
+            db.commit()
+            return {"granted": False, "position": position, "active": active, "queued": len(queue),
+                    "limit": limit, "reason": reason}
+
+    def release(self, request_id: str) -> None:
+        with self._connect() as db:
+            db.execute("BEGIN IMMEDIATE")
+            row = db.execute("SELECT run_id, memory_sample, lease_until FROM requests WHERE request_id=?", (request_id,)).fetchone()
+            if row and row["lease_until"] is not None:
+                run_active = db.execute(
+                    "SELECT count(*) FROM requests WHERE run_id=? AND lease_until IS NOT NULL", (row["run_id"],)).fetchone()[0]
+                sample = max(int(row["memory_sample"]), self.run_memory_reader(row["run_id"]) // max(1, run_active))
+                if sample:
+                    count = int(db.execute("SELECT value FROM state WHERE key='sample_count'").fetchone()[0])
+                    average = int(db.execute("SELECT value FROM state WHERE key='avg_task_bytes'").fetchone()[0])
+                    average = (average * count + sample) // (count + 1)
+                    db.execute("UPDATE state SET value=? WHERE key='avg_task_bytes'", (str(average),))
+                    db.execute("UPDATE state SET value=? WHERE key='sample_count'", (str(count + 1),))
+            db.execute("DELETE FROM requests WHERE request_id=?", (request_id,))
+            db.commit()
+
+    def snapshot(self) -> dict:
+        with self._connect() as db:
+            now = time.time()
+            db.execute("DELETE FROM requests WHERE last_seen < ?", (now - self.lease_seconds,))
+            queued = db.execute("SELECT count(*) FROM requests WHERE lease_until IS NULL").fetchone()[0]
+            active = db.execute("SELECT count(*) FROM requests WHERE lease_until IS NOT NULL").fetchone()[0]
+            average = int(db.execute("SELECT value FROM state WHERE key='avg_task_bytes'").fetchone()[0])
+            snapshot = self.snapshot_reader()
+            limit, reason = calculate_limit(snapshot, active, average)
+            head = db.execute("SELECT run_id FROM requests WHERE lease_until IS NULL ORDER BY queued_at LIMIT 1").fetchone()
+            return {"active": active, "queued": queued, "limit": limit, "reason": reason,
+                    "waiting_run": head["run_id"] if head else "", "average_task_bytes": average}
+
+
+_scheduler: WorkflowScheduler | None = None
+
+
+def get_scheduler() -> WorkflowScheduler:
+    global _scheduler
+    if _scheduler is None:
+        _scheduler = WorkflowScheduler(Path(__file__).resolve().parents[1] / "data" / "workflow-scheduler.sqlite3")
+    return _scheduler
diff --git a/scripts/wf_run.py b/scripts/wf_run.py
index bfc0ed718..2b9d442ff 100644
--- a/scripts/wf_run.py
+++ b/scripts/wf_run.py
@@ -14,16 +14,17 @@ import os
 import re
 import shlex
 import shutil
 import subprocess
 import sys
 import urllib.error
 import urllib.parse
 import urllib.request
+import uuid
 from dataclasses import dataclass, field
 from pathlib import Path
 from typing import Any, Awaitable, Callable, Iterable
 
 ROOT = Path(__file__).resolve().parents[1]
 if str(ROOT) not in sys.path:
     sys.path.insert(0, str(ROOT))
 
@@ -270,16 +271,37 @@ async def _readiness(model: str) -> dict:
                 row = json.loads(response.read())
         except (OSError, urllib.error.URLError, json.JSONDecodeError):
             return {"state": "unknown"}
         return row if isinstance(row, dict) else {"state": "unknown"}
 
     return await asyncio.to_thread(request)
 
 
+async def _workflow_slot_request(path: str, payload: dict) -> dict | None:
+    base = os.environ.get("ORCHESTRA_URL", "http://127.0.0.1:8888").rstrip("/")
+    headers = {"Content-Type": "application/json"}
+    token = os.environ.get("INTERNAL_TOKEN", "")
+    if token:
+        headers["Authorization"] = f"Bearer {token}"
+
+    def request() -> dict | None:
+        body = json.dumps(payload).encode("utf-8")
+        try:
+            with urllib.request.urlopen(urllib.request.Request(
+                f"{base}{path}", data=body, headers=headers, method="POST",
+            ), timeout=10) as response:
+                result = json.loads(response.read())
+        except (OSError, urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError):
+            return None
+        return result if isinstance(result, dict) else None
+
+    return await asyncio.to_thread(request)
+
+
 async def _await_despite_cancellation(task: asyncio.Task) -> tuple[Any, int]:
     cancellations = 0
     current = asyncio.current_task()
     while True:
         try:
             return await asyncio.shield(task), cancellations
         except asyncio.CancelledError:
             cancellations += 1
@@ -438,16 +460,17 @@ class WorkflowEngine:
         self.run_id = run_id
         self.run_dir = Path(run_dir)
         self.run_dir.mkdir(parents=True, exist_ok=True)
         self.steps_dir = self.run_dir / "steps"
         self.steps_dir.mkdir(exist_ok=True)
         self.workflow_path = Path(workflow_path) if workflow_path is not None else None
         self.resume_command_override = resume_command_override.strip()
         self.journal = Journal(self.run_dir / "journal.jsonl")
+        self._injected_adapter = adapter is not None
         self.adapter = adapter or run_adapter
         self.usage_writer = usage_writer if usage_writer is not None else (
             persist_turn_usage if adapter is None else None
         )
         self.readiness_checker = readiness_checker or (_readiness if adapter is None else _allow_all)
         concurrency = max_concurrency or int(os.environ.get("WF_MAX_CONCURRENCY", "3"))
         self._semaphore = asyncio.Semaphore(max(1, concurrency))
         self._codex_semaphore = asyncio.Semaphore(2)
@@ -470,16 +493,19 @@ class WorkflowEngine:
             )
             if self.workspace_repo is not None and not self.workspace_base_commit
             else ""
         )
         self.pipeline_name = pipeline_name
         self.default_modules = tuple(default_modules)
         self.session_id = f"wf:{run_id}"
         self.partial_reason = ""


## LATER FIX 532c73f620 (8.9 days later): V-916: #V-916: fix workflow schema, identity, and resume races
lines of origin it changed/deleted: 2
(code only, capped 400 lines)

V-916: #V-916: fix workflow schema, identity, and resume races

Orchestra-Operation: f8bf4dd7-0b63-4535-ba68-7174a99677cb


diff --git a/app/mcp_stdio.py b/app/mcp_stdio.py
index 1e98ff5cd..341948147 100644
--- a/app/mcp_stdio.py
+++ b/app/mcp_stdio.py
@@ -3257,47 +3257,60 @@ async def dynamic_workflow(
             default_billing = stage.get("billing", "subscription")
             if "tasks" in stage:
                 if "prompt" in stage or "items" in stage:
                     return f"Error: stages[{stage_index}] must use either tasks or prompt and items"
                 stage_tasks = stage["tasks"]
                 if not isinstance(stage_tasks, list) or not stage_tasks:
                     return f"Error: stages[{stage_index}].tasks must be a non-empty array"
                 task_count = len(stage_tasks)
+                stage_tasks = [(task, None, None) for task in stage_tasks]
             elif "prompt" in stage and "items" in stage:
                 template = stage["prompt"]
                 items = stage["items"]
                 if not isinstance(template, str) or "{item}" not in template:
                     return f"Error: stages[{stage_index}].prompt must contain '{{item}}'"
                 if not isinstance(items, list) or not items:
                     return f"Error: stages[{stage_index}].items must be a non-empty array"
                 task_count = len(items)
                 stage_tasks = (
-                    {"prompt": template.replace(
-                        "{item}", item if isinstance(item, str) else json.dumps(item, ensure_ascii=False)
-                    )}
-                    for item in items
+                    (
+                        {"prompt": template.replace(
+                            "{item}", item if isinstance(item, str) else json.dumps(item, ensure_ascii=False)
+                        )},
+                        item,
+                        task_index,
+                    )
+                    for task_index, item in enumerate(items)
                 )
             else:
                 return f"Error: stages[{stage_index}] needs tasks or prompt and items"
             if total_tasks + task_count > 1000:
                 return "Error: expanded workflow exceeds 1,000 tasks"
             normalized_stage = []
-            for task_index, task in enumerate(stage_tasks):
+            for task_index, (task, item, item_index) in enumerate(stage_tasks):
                 if not isinstance(task, dict) or not isinstance(task.get("prompt"), str) or not task["prompt"].strip():
                     return f"Error: stages[{stage_index}].tasks[{task_index}].prompt must be a non-empty string"
                 normalized, error = _normalize_dynamic_task(
                     task, default_model=default_model,
                     default_schema=default_schema,
                     default_billing=default_billing,
                     label=f"stages[{stage_index}].tasks[{task_index}]",
                 )
                 if error:
                     return f"Error: {error}"
                 normalized["label"] = f"Stage {stage_index + 1} · Task {task_index + 1}"
+                normalized["task_id"] = str(
+                    task.get("task_id") or task.get("id")
+                    or f"stage-{stage_index + 1}-task-{task_index + 1}"
+                )
+                if item_index is not None:
+                    normalized["task_id"] = f"stage-{stage_index + 1}-item-{item_index + 1}"
+                    normalized["item"] = item
+                    normalized["item_index"] = item_index
                 normalized_stage.append(normalized)
                 spec_payload_size += len(
                     json.dumps(normalized, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
                 )
                 if spec_payload_size > 1024 * 1024:
                     return "Error: workflow specification exceeds 1 MiB"
             expanded_stages.append({"tasks": normalized_stage})
             total_tasks += task_count
@@ -3310,16 +3323,19 @@ async def dynamic_workflow(
         normalized = []
         for index, task in enumerate(tasks):
             if not isinstance(task, dict) or not isinstance(task.get("prompt"), str) or not task["prompt"].strip():
                 return f"Error: tasks[{index}].prompt must be a non-empty string"
             row, error = _normalize_dynamic_task(task, label=f"tasks[{index}]")
             if error:
                 return f"Error: {error}"
             row["label"] = f"Task {index + 1}"
+            row["task_id"] = str(
+                task.get("task_id") or task.get("id") or f"task-{index + 1}"
+            )
             normalized.append(row)
         spec_payload = {"tasks": normalized, "mode": mode}
     if (not isinstance(budget_usd, (int, float)) or isinstance(budget_usd, bool)
             or not math.isfinite(budget_usd) or budget_usd <= 0):
         return "Error: budget_usd must be positive"
     if not isinstance(max_calls, int) or isinstance(max_calls, bool) or max_calls < 1:
         return "Error: max_calls must be a positive integer"
     if not isinstance(max_concurrency, int) or isinstance(max_concurrency, bool) or not 1 <= max_concurrency <= 100:
diff --git a/scripts/wf_run.py b/scripts/wf_run.py
index 352da7f85..4c4e8ec0f 100644
--- a/scripts/wf_run.py
+++ b/scripts/wf_run.py
@@ -2,16 +2,17 @@
 """Deterministic scripted fan-out hosted by an Orchestra background run job."""
 
 from __future__ import annotations
 
 import argparse
 import asyncio
 import ast
 import base64
+import fcntl
 import hashlib
 import inspect
 import json
 import os
 import re
 import shlex
 import shutil
 import subprocess
@@ -113,16 +114,74 @@ class WorkflowValue:
             ),
         )
 
 
 class WorkspacePreparationError(RuntimeError):
     pass
 
 
+class WorkflowRunAlreadyActive(RuntimeError):
+    pass
+
+
+class WorkflowRunLock:
+    def __init__(self, path: Path):
+        self.path = path
+        self.fd: int | None = None
+
+    def __enter__(self) -> "WorkflowRunLock":
+        self.path.parent.mkdir(parents=True, exist_ok=True)
+        fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
+        try:
+            try:
+                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
+            except BlockingIOError:
+                os.lseek(fd, 0, os.SEEK_SET)
+                owner = os.read(fd, 64).decode("ascii", errors="ignore").strip()
+                if owner.isdigit():
+                    raise WorkflowRunAlreadyActive(
+                        f"workflow run already active (pid {owner})"
+                    )
+                # The owner may have acquired the lock but not yet published its PID.
+                fcntl.flock(fd, fcntl.LOCK_EX)
+            os.ftruncate(fd, 0)
+            os.write(fd, str(os.getpid()).encode("ascii"))
+            os.fsync(fd)
+            self.fd = fd
+            return self
+        except BaseException:
+            os.close(fd)
+            raise
+
+    def __exit__(self, exc_type, exc, traceback) -> None:
+        if self.fd is not None:
+            fcntl.flock(self.fd, fcntl.LOCK_UN)
+            os.close(self.fd)
+            self.fd = None
+
+
+def _task_result_record(
+    task: dict[str, Any], result: WorkflowValue | None, *, task_id: str,
+    task_index: int, stage_index: int | None = None,
+) -> dict[str, Any]:
+    record: dict[str, Any] = {
+        "task_id": str(task.get("task_id") or task.get("id") or task_id),
+        "task_index": task_index,
+        "result": result,
+    }
+    if stage_index is not None:
+        record["stage_index"] = stage_index
+    if "item" in task:
+        record["item"] = task["item"]
+    if "item_index" in task:
+        record["item_index"] = task["item_index"]
+    return record
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
@@ -219,25 +278,70 @@ def _validate_schema(value: Any, schema: dict, path: str = "$") -> None:
         if "maxLength" in schema and len(value) > int(schema["maxLength"]):
             raise ValueError(f"{path} is longer than {schema['maxLength']}")
 
 
 def _parse_and_validate(raw: str, schema: dict) -> Any:
     try:
         value = json.loads(raw)
     except json.JSONDecodeError as error:
-        if schema.get("type") == "string":
+        wrapped = _extract_wrapped_json(raw)
+        if wrapped is not None:
+            try:
+                value = json.loads(wrapped)
+            except json.JSONDecodeError as wrapped_error:
+                if schema.get("type") != "string":
+                    raise ValueError(
+                        f"invalid JSON: {wrapped_error.msg} at line "
+                        f"{wrapped_error.lineno} column {wrapped_error.colno}"
+                    ) from wrapped_error
+                value = raw
+        elif schema.get("type") == "string":
             value = raw
-            _validate_schema(value, schema)
-            return value
-        raise ValueError(f"invalid JSON: {error.msg} at line {error.lineno} column {error.colno}") from error
+        else:
+            raise ValueError(
+                f"invalid JSON: {error.msg} at line {error.lineno} column {error.colno}"
+            ) from error
     _validate_schema(value, schema)
     return value
 
 
+def _extract_wrapped_json(raw: str) -> str | None:
+    for match in re.finditer(r"```(?:json)?\s*\r?\n?(.*?)```", raw, re.IGNORECASE | re.DOTALL):
+        return match.group(1).strip()
+
+    stack: list[str] = []
+    start = -1
+    in_string = False
+    escaped = False
+    pairs = {"}": "{", "]": "["}
+    for index, char in enumerate(raw):
+        if in_string:
+            if escaped:
+                escaped = False
+            elif char == "\\":
+                escaped = True
+            elif char == '"':
+                in_string = False
+            continue
+        if char == '"':
+            in_string = True
+        elif char in "{[":
+            if not stack:
+                start = index
+            stack.append(char)
+        elif char in "}]" and stack:
+            if stack[-1] != pairs[char]:
+                return None
+            stack.pop()
+            if not stack:
+                return raw[start:index + 1]
+    return None
+
+
 def _schema_retry_prompt(prompt: str, error: str, schema: dict) -> str:
     return (
         prompt
         + "\n\nValidation error: "
         + error
         + "\nReturn only JSON that satisfies this schema:\n"
         + json.dumps(schema, ensure_ascii=False, sort_keys=True)
     )
@@ -555,16 +659,17 @@ class WorkflowEngine:
                 self.budget.spent_usd += float(row.get("cost_usd") or 0)
             elif event == "schema_invalid":
                 call_key = str(row.get("call_key") or "")
                 last_state[call_key] = "schema_invalid"
                 self._retry_state[call_key] = (
                     int(row.get("next_attempt") or 0),
                     str(row.get("error") or "schema validation failed"),
                 )
+                self._step_records[call_key] = {**row, "reason": "schema", "value": None}
             elif event == "prepare_failed":
                 call_key = str(row.get("call_key") or "")
                 last_state[call_key] = "prepare_failed"
                 self.budget.dispatched_calls = max(0, self.budget.dispatched_calls - 1)
                 self._step_records[call_key] = {
                     **row, "reason": "prepare_failed", "value": None,
                 }
             elif event == "completed":
@@ -936,40 +1041,48 @@ class WorkflowEngine:
             except ValueError as error:
                 schema_error = str(error)
                 response_path = _save_schema_invalid_response(
                     scratch, attempt + 1, result.text,
                 )
                 self.journal.append({
                     "event": "schema_invalid",
                     "call_key": call_key,
+                    "label": label,
                     "attempt": attempt + 1,
                     "next_attempt": attempt + 1,
                     "error": schema_error,
                     "response_path": response_path.relative_to(self.run_dir).as_posix(),
                     "response_bytes": response_path.stat().st_size,
                     "response_truncated": len(
                         result.text.encode("utf-8", errors="replace")
                     ) > _SCHEMA_RESPONSE_MAX_BYTES,
                 })
+                self._step_records[call_key] = {
+                    "call_key": call_key,
+                    "label": label,
+                    "reason": "schema",
+                    "error": schema_error,
+                    "value": None,
+                }
                 if attempt < 2:
                     current_prompt = _schema_retry_prompt(rendered, schema_error, schema)
 
         if deferred_reason:
             return None
         if result is None or not result.ok or schema_error:
             reason = "error" if result is None else ("schema" if schema_error else result.stop_reason)
             self.partial_reason = self.partial_reason or reason
             self._finish(
                 call_key,
                 None,
                 reason=reason,
                 label=label,
                 cost_usd=total_cost,
-                error=result.error if result is not None else "",
+                error=(schema_error or result.error) if result is not None else "",
             )
             return None
 
         own_id = call_key
         output_free = free_sources | ({own_id} if runtime == "harness" else set())
         output_verified = verified_sources | (free_sources if purpose == "verify" else set())
         step_path = self.steps_dir / f"{call_key.replace(':', '-')}.json"
         value = WorkflowValue(
@@ -1271,50 +1384,69 @@ class WorkflowEngine:
             return await self.agent(
                 task["prompt"], model=task.get("model", "luna"),
                 schema=task.get("schema"), inputs=inputs,
                 label=task.get("label", ""),
                 billing=task.get("billing", "subscription"),
             )
 
         if mode == "parallel":
-            self.result = await self.parallel([
+            values = await self.parallel([
                 lambda task=task: run_task(task) for task in tasks
             ])
+            self.result = [
+                _task_result_record(
+                    task, value,
+                    task_id=f"task-{index + 1}", task_index=index,
+                )
+                for index, (task, value) in enumerate(zip(tasks, values))
+            ]
         elif mode == "chain":
             results = []
             prior = None
-            for task in tasks:
+            for index, task in enumerate(tasks):
                 prior = await run_task(task, prior)
-                results.append(prior)
+                results.append(_task_result_record(
+                    task, prior,
+                    task_id=f"task-{index + 1}", task_index=index,
+                ))
                 if prior is None:
                     break
             self.result = results
         else:
             raise ValueError("mode must be 'parallel' or 'chain'")
         return self.result
 
     async def execute_stages(self, stages: list[dict[str, Any]]) -> Any:
         results_by_stage = []
         previous: list[WorkflowValue] = []
-        for stage in stages:
+        for stage_index, stage in enumerate(stages):
             stage_tasks = stage["tasks"]
-            results = await self.parallel([
+            values = await self.parallel([
                 lambda task=task, prior=tuple(previous): self.agent(
                     task["prompt"], model=task.get("model", "luna"),
                     schema=task.get("schema"), inputs=prior,
                     label=task.get("label", ""),
                     billing=task.get("billing", "subscription"),
                 )
                 for task in stage_tasks
             ])
+            results = [
+                _task_result_record(
+                    task, value,
+                    task_id=f"stage-{stage_index + 1}-task-{task_index + 1}",
+                    task_index=task_index,
+                    stage_index=stage_index,
+                )
+                for task_index, (task, value) in enumerate(zip(stage_tasks, values))
+            ]
             results_by_stage.append(results)
-            if any(value is None for value in results):