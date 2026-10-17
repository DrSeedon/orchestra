# Context for item-37

## Diff reviewed (-U20, capped at 1500 lines)

diff --git a/app/backend_claude.py b/app/backend_claude.py
index bf53d98ba..a99f73ff9 100644
--- a/app/backend_claude.py
+++ b/app/backend_claude.py
@@ -71,104 +71,112 @@ def _extract_tool_result(block) -> str:
         text = raw.get('text', str(raw))
     else:
         text = str(raw)
     try:
         parsed = _json.loads(text)
         if isinstance(parsed, dict) and 'result' in parsed:
             return str(parsed['result'])
     except (ValueError, TypeError):
         pass
     return text
 
 
 class ClaudeBackend:
     def __init__(self, model: str, cwd: str, system_prompt: str = "",
                  resume_session_id: str | None = None,
                  mcp_servers: dict | None = None,
                  is_orchestrator: bool = False,
                  scope_mcp_servers: dict | None = None,
                  config_dir: str = "",
                  inherit_claude_md: bool = True,
-                 user_mcp_servers: dict | None = None):
+                 user_mcp_servers: dict | None = None,
+                 lean_tools: bool = False):
         self.model = model
         self.cwd = cwd
         self.system_prompt = system_prompt
         self._resume_id = resume_session_id
         self._mcp_servers = mcp_servers or {}
         self._scope_mcp_servers = scope_mcp_servers or {}
         self._is_orchestrator = is_orchestrator
         # Профиль Claude (F1/F4 резолвятся против него): пустой → env процесса
         # orchestra (back-compat, 1:1 upstream).
         self._config_dir = config_dir
         # F4: наследовать ли user/project CLAUDE.md + настройки профиля.
         self._inherit_claude_md = inherit_claude_md
         # F2: user-MCP из профильного .claude.json (базовый слой merge).
         self._user_mcp_servers = user_mcp_servers or {}
+        self._lean_tools = lean_tools
         self._client: Optional[ClaudeSDKClient] = None
         self._session_id: str | None = resume_session_id
 
     @property
     def session_id(self) -> Optional[str]:
         return self._session_id
 
     def _make_client(self) -> ClaudeSDKClient:
         import os
         cli = shutil.which("claude") or os.environ.get("CLAUDE_CLI_PATH", "claude")
         resume_id = self._session_id or self._resume_id
         env = {}
         for _k in ("HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY"):
             if os.environ.get(_k):
                 env[_k] = os.environ[_k]
         # #56: kill non-essential background haiku calls (tips/banter/flavor) + telemetry
         env["DISABLE_NON_ESSENTIAL_MODEL_CALLS"] = "1"
         env["DISABLE_TELEMETRY"] = "1"
+        env["DISABLE_ERROR_REPORTING"] = "1"               # #58: Sentry off
+        env["CLAUDE_CODE_DISABLE_FEEDBACK_SURVEY"] = "1"  # #58: survey off
         # Профиль: переопределяем CLAUDE_CONFIG_DIR подпроцесса (SDK строит
         # env как {**os.environ, **options.env}). Пусто → наследуем env процесса
         # orchestra (back-compat). expanduser — на случай "~" в config_dir.
         if self._config_dir:
             env["CLAUDE_CONFIG_DIR"] = os.path.expanduser(self._config_dir)
         agent_uid = os.environ.get("ORCHESTRA_AGENT_UID")
         options = ClaudeAgentOptions(
             model=self.model, cwd=self.cwd, cli_path=cli,
             permission_mode="default", can_use_tool=_make_auto_approve(self._is_orchestrator),
             disallowed_tools=_disallowed_tools(self._is_orchestrator),
             include_partial_messages=False, max_turns=200,
             max_buffer_size=50 * 1024 * 1024,
             env=env,
             user=agent_uid,
         )
         if resume_id:
             options.resume = resume_id
         else:
             options.system_prompt = {"type": "preset", "preset": "claude_code", "append": self.system_prompt}
         merged_mcp = {
             **self._user_mcp_servers,
             **self._scope_mcp_servers,
             **self._mcp_servers,
         }
         if merged_mcp:
             options.mcp_servers = merged_mcp
         # F4: inherit_claude_md=False → только local-слой (нет user/project
         # CLAUDE.md и настроек); иначе — полный набор, как в upstream.
         options.setting_sources = (
             ["user", "project", "local"] if self._inherit_claude_md else ["local"]
         )
+        # #58: per-role tools — lean prefix for coding workers (-57% tokens).
+        # orchestrators и full-cycle нуждаются в полном наборе (WebSearch, spawn_worker и т.д.).
+        if not self._is_orchestrator and self._lean_tools:
+            options.tools = ["Read", "Edit", "Write", "Bash", "Glob", "Grep"]
         # F1: options.skills НЕ задаём НИКОГДА. Ветка "skills-список → options.skills"
         # сознательно НЕ реализована (B4: default 1:1 upstream — его роли имеют
         # skills-списки, но скиллы инъектятся через _inject_skills_to_worktree,
         # не через options.skills). Единственное действие F1 — gating инъекции
         # в manager.create_session при skills=="all".
         return ClaudeSDKClient(options=options)
 
     async def _cleanup_failed_client(self) -> None:
         if self._client:
             try:
                 await self._client.disconnect()
             except BaseException:
                 pass
             self._client = None
 
     async def connect(self) -> None:
         self._client = self._make_client()
         try:
             await asyncio.wait_for(self._client.connect(), timeout=60)
         except BaseException as e:
diff --git a/app/session.py b/app/session.py
index 75342a7c4..5c61fc964 100644
--- a/app/session.py
+++ b/app/session.py
@@ -198,50 +198,55 @@ class AgentSession:
         else:
             from app.backend_claude import ClaudeBackend
             from app.pipeline import get_role
             from app.db import get_profile
             # Резолв роли: нет манифеста → чистый upstream-fallback
             # (inherit=True, config_dir по профилю, user_mcp пуст — как сегодня).
             try:
                 rr = get_role(self.pipeline, self.role)
             except FileNotFoundError:
                 rr = None
             inherit = rr.inherit_claude_md if rr else True
             config_dir = ""
             if self.profile:
                 p = get_profile(self.profile)
                 config_dir = p["config_dir"] if p else ""
             # F2: user-MCP подмешиваем ТОЛЬКО при mcp_servers=="all" (tasks-pm);
             # default/список — без user-MCP (1:1 upstream).
             user_mcp: dict = {}
             if rr is not None and rr.mcp_servers == "all":
                 user_mcp = _load_user_mcp_servers(config_dir)
+            # #58: lean_tools=True для coding-воркеров (worker роль) — режет префикс с 48K до 20K.
+            # full-cycle, orchestrator, sub-orchestrator — False (нужны WebSearch/MCP/spawn tools).
+            _LEAN_ROLES = frozenset({"worker", "reviewer", "watcher"})
+            lean = not self.is_orchestrator and self.role in _LEAN_ROLES
             return ClaudeBackend(
                 model=self.model, cwd=self.cwd,
                 system_prompt=self.system_prompt,
                 resume_session_id=resume,
                 mcp_servers=self.mcp_servers,
                 is_orchestrator=self.is_orchestrator,
                 scope_mcp_servers=_load_scope_mcp_servers(self.scope),
                 config_dir=config_dir,
                 inherit_claude_md=inherit,
                 user_mcp_servers=user_mcp,
+                lean_tools=lean,
             )
 
     def _codex_reasoning_effort(self) -> str:
         return "high"
 
     def _spawn_bg(self, coro) -> asyncio.Task:
         task = asyncio.create_task(coro)
         self._background_tasks.add(task)
         def _on_done(t):
             self._background_tasks.discard(t)
             if not t.cancelled():
                 exc = t.exception()
                 if exc:
                     logger.warning(f"[{self.name}] background task failed: {exc}")
         task.add_done_callback(_on_done)
         return task
 
     def _build_codex_mcp_env(self) -> dict[str, str]:
         env = {}
         for _name, cfg in self.mcp_servers.items():


## Later history of the touched files on main (after this commit)

209 later commits touch these paths; the first 40 (oldest first):
064167f87 2026-06-06 Revert "#51: #51: per-role tools — lean prefix for coding workers (-57% tokens)"
04a4b4e0f 2026-06-09 tests: P0/P1 coverage — tg_bridge, mcp_stdio, compact
9c4d87db4 2026-06-09 fix: change_model immediately persists to DB — survives restart
f940023e6 2026-06-10 feat: orchestrators auto-save context to files before compact (CLAUDE.md, TODO, BUGS, docs)
798197a5c 2026-06-10 Add context-level cost tracking (turn/ctx/total)
a473c42f8 2026-06-10 add WHY-only comments to backend Python files
972f530ea 2026-06-11 filter ede_diagnostic telemetry noise from turn errors
df7a93141 2026-06-11 reset progress bar when agent goes idle
d0cada2a5 2026-06-11 log hibernate/wake/stop/listen-death to dashboard — full lifecycle visibility
cb5ca55a1 2026-06-11 #refactor-ecs P0: fail-loud excepts + to_thread for sync-DB-in-async + loop-capture for YouGile sync
cb9b92128 2026-06-11 #refactor-ecs P1: get_by_name always returns AgentSession — loaded discriminator kills the dict union
a42340a2d 2026-06-11 #refactor-ecs P3: cut the 3 real cycles — wired callbacks instead of lazy imports
33fe3fcbb 2026-06-11 #refactor-ecs P4: split session.py god object — CostTracker + TurnManager + HibernateManager
c59047bd3 2026-06-11 merge refactor-ecs: P0-P4 full codebase refactoring + re-apply lifecycle logging, ede_diagnostic filter, progress reset
cf54e376b 2026-06-12 log tool calls during compact turn — no more black hole
eaff2f850 2026-06-13 fix: use real TOKEN_PRICES for non-Claude models — SDK hardcodes Claude rates
3bbb6660b 2026-06-14 feat: 4-level cost (turn/ctx/session/total), persist ctx cost, new experimenter role
fbe1b24df 2026-06-14 hide hibernate/wake from chat+TG, throttle topic icon updates (10s cooldown)
6e2cb319d 2026-06-14 #96: OpenCodeBackend — third BackendLike over opencode serve daemon
cdccb4ffd 2026-06-14 Merge remote-tracking branch 'origin/main'
9b55629ef 2026-06-14 #96: fix opencode event loop — start after send() not at connect() (SSE needs pre-opened stream)
91e2973fd 2026-06-14 Merge remote-tracking branch 'origin/main'
cf4e66fdd 2026-06-14 #96: fix event loop — opencode turn completion is normal, not a failure
a6bc36c45 2026-06-14 Merge remote-tracking branch 'origin/main'
ded9b9242 2026-06-14 fix: 6 UX issues — .claude gitignore, no reconnect for opencode, cost precision, dedup, tool truncate
324c3023b 2026-06-14 Merge remote-tracking branch 'origin/main'
a1ef91e3a 2026-06-14 fix: force IDLE + persist when opencode event loop exits while still RUNNING
d80d04966 2026-06-14 Merge remote-tracking branch 'origin/main'
c8ae0ea99 2026-06-14 fix: force IDLE on ALL opencode exit paths (early return + no-reconnect)
97a057d23 2026-06-14 Merge remote-tracking branch 'origin/main'
521b3ac8a 2026-06-15 #97: replace SSE turn-boundary with poll-based detection — fixes 11h stuck-running bug
f42d955b5 2026-06-15 Merge remote-tracking branch 'enterprise/main'
9dc240151 2026-06-21 #83: feat(#83): real-time token streaming in dashboard
08d218643 2026-06-22 fix: block Workflow tool for all agents — Orchestra manages orchestration, built-in workflows waste tokens
e1d694a58 2026-06-24 feat: auto-retry on rate_limit errors — 3 retries with 30/60/90s backoff
39d195817 2026-06-28 fix: log compact summary to chat/TG so user can see what was preserved
05a020475 2026-06-28 fix: no limit on compact summary length in chat log
88fc1a1e7 2026-06-29 fix: replay accumulated stream text on SSE reconnect — no lost partials on agent switch
dc3be906d 2026-06-30 fix: proxy persistence + hot-switch + lowercase env leak
1aa9c06ad 2026-07-01 WIP: auto-saved uncommitted changes before worker spawn (2026-07-01 11:28)

## Patches of the first 8 later commits, restricted to the touched paths (each capped at 150 lines)

### 064167f87 Revert "#51: #51: per-role tools — lean prefix for coding workers (-57% tokens)"

diff --git a/app/backend_claude.py b/app/backend_claude.py
index a99f73ff9..bf53d98ba 100644
--- a/app/backend_claude.py
+++ b/app/backend_claude.py
@@ -86,12 +86,11 @@ class ClaudeBackend:
                  mcp_servers: dict | None = None,
                  is_orchestrator: bool = False,
                  scope_mcp_servers: dict | None = None,
                  config_dir: str = "",
                  inherit_claude_md: bool = True,
-                 user_mcp_servers: dict | None = None,
-                 lean_tools: bool = False):
+                 user_mcp_servers: dict | None = None):
         self.model = model
         self.cwd = cwd
         self.system_prompt = system_prompt
         self._resume_id = resume_session_id
         self._mcp_servers = mcp_servers or {}
@@ -102,11 +101,10 @@ class ClaudeBackend:
         self._config_dir = config_dir
         # F4: наследовать ли user/project CLAUDE.md + настройки профиля.
         self._inherit_claude_md = inherit_claude_md
         # F2: user-MCP из профильного .claude.json (базовый слой merge).
         self._user_mcp_servers = user_mcp_servers or {}
-        self._lean_tools = lean_tools
         self._client: Optional[ClaudeSDKClient] = None
         self._session_id: str | None = resume_session_id
 
     @property
     def session_id(self) -> Optional[str]:
@@ -121,12 +119,10 @@ class ClaudeBackend:
             if os.environ.get(_k):
                 env[_k] = os.environ[_k]
         # #56: kill non-essential background haiku calls (tips/banter/flavor) + telemetry
         env["DISABLE_NON_ESSENTIAL_MODEL_CALLS"] = "1"
         env["DISABLE_TELEMETRY"] = "1"
-        env["DISABLE_ERROR_REPORTING"] = "1"               # #58: Sentry off
-        env["CLAUDE_CODE_DISABLE_FEEDBACK_SURVEY"] = "1"  # #58: survey off
         # Профиль: переопределяем CLAUDE_CONFIG_DIR подпроцесса (SDK строит
         # env как {**os.environ, **options.env}). Пусто → наследуем env процесса
         # orchestra (back-compat). expanduser — на случай "~" в config_dir.
         if self._config_dir:
             env["CLAUDE_CONFIG_DIR"] = os.path.expanduser(self._config_dir)
@@ -154,14 +150,10 @@ class ClaudeBackend:
         # F4: inherit_claude_md=False → только local-слой (нет user/project
         # CLAUDE.md и настроек); иначе — полный набор, как в upstream.
         options.setting_sources = (
             ["user", "project", "local"] if self._inherit_claude_md else ["local"]
         )
-        # #58: per-role tools — lean prefix for coding workers (-57% tokens).
-        # orchestrators и full-cycle нуждаются в полном наборе (WebSearch, spawn_worker и т.д.).
-        if not self._is_orchestrator and self._lean_tools:
-            options.tools = ["Read", "Edit", "Write", "Bash", "Glob", "Grep"]
         # F1: options.skills НЕ задаём НИКОГДА. Ветка "skills-список → options.skills"
         # сознательно НЕ реализована (B4: default 1:1 upstream — его роли имеют
         # skills-списки, но скиллы инъектятся через _inject_skills_to_worktree,
         # не через options.skills). Единственное действие F1 — gating инъекции
         # в manager.create_session при skills=="all".
diff --git a/app/session.py b/app/session.py
index 5c61fc964..75342a7c4 100644
--- a/app/session.py
+++ b/app/session.py
@@ -213,25 +213,20 @@ class AgentSession:
             # F2: user-MCP подмешиваем ТОЛЬКО при mcp_servers=="all" (tasks-pm);
             # default/список — без user-MCP (1:1 upstream).
             user_mcp: dict = {}
             if rr is not None and rr.mcp_servers == "all":
                 user_mcp = _load_user_mcp_servers(config_dir)
-            # #58: lean_tools=True для coding-воркеров (worker роль) — режет префикс с 48K до 20K.
-            # full-cycle, orchestrator, sub-orchestrator — False (нужны WebSearch/MCP/spawn tools).
-            _LEAN_ROLES = frozenset({"worker", "reviewer", "watcher"})
-            lean = not self.is_orchestrator and self.role in _LEAN_ROLES
             return ClaudeBackend(
                 model=self.model, cwd=self.cwd,
                 system_prompt=self.system_prompt,
                 resume_session_id=resume,
                 mcp_servers=self.mcp_servers,
                 is_orchestrator=self.is_orchestrator,
                 scope_mcp_servers=_load_scope_mcp_servers(self.scope),
                 config_dir=config_dir,
                 inherit_claude_md=inherit,
                 user_mcp_servers=user_mcp,
-                lean_tools=lean,
             )
 
     def _codex_reasoning_effort(self) -> str:
         return "high"
 
### 04a4b4e0f tests: P0/P1 coverage — tg_bridge, mcp_stdio, compact

diff --git a/app/session.py b/app/session.py
index 75342a7c4..5836f436f 100644
--- a/app/session.py
+++ b/app/session.py
@@ -781,10 +781,12 @@ class AgentSession:
         )
         PREAMBLE = "[PREVIOUS CONTEXT SUMMARY — context was compacted]\n\n{summary}\n\n[END OF SUMMARY — continue naturally]\n\n"
 
         if self._compacting:
             return {"ok": False, "error": "compact already in progress"}
+        if self.status == AgentStatus.RUNNING:
+            return {"ok": False, "error": "cannot compact while agent is running"}
         self._compacting = True
         before_pct = self._last_context.get("percentage", 0)
         self._log("status", f"compact started (context {before_pct}%)")
 
         if self._listen_task and not self._listen_task.done():
### 9c4d87db4 fix: change_model immediately persists to DB — survives restart

diff --git a/app/session.py b/app/session.py
index 5836f436f..167f4e0e2 100644
--- a/app/session.py
+++ b/app/session.py
@@ -944,10 +944,12 @@ class AgentSession:
 
         self._log("status", f"model change: {old_model} → {new_model}")
         await self._disconnect_backend()
         self.model = new_model
         self._persist()
+        snapshot = self._to_db_dict()
+        await asyncio.get_running_loop().run_in_executor(_db_executor(), save_session, snapshot)
         return {"ok": True, "model": new_model, "old_model": old_model, "changed": True}
 
     async def _disconnect_backend(self) -> None:
         if self._hibernate_task and not self._hibernate_task.done() and self._hibernate_task is not asyncio.current_task():
             self._hibernate_task.cancel()
### f940023e6 feat: orchestrators auto-save context to files before compact (CLAUDE.md, TODO, BUGS, docs)

diff --git a/app/session.py b/app/session.py
index 167f4e0e2..ce9f87f0b 100644
--- a/app/session.py
+++ b/app/session.py
@@ -763,13 +763,22 @@ class AgentSession:
         self.status = AgentStatus.IDLE
         self._log("status", "interrupted")
         self._persist()
 
     async def compact(self) -> dict:
+        _ORCH_PRESAVE = (
+            "BEFORE writing the summary — persist your knowledge to files so it survives compact:\n"
+            "1. CLAUDE.md — append key decisions, new rules, patterns discovered this session (section '## Session notes')\n"
+            "2. TODO.md — add new items, remove done items\n"
+            "3. BUGS.md — add found bugs, close fixed ones\n"
+            "4. docs/ — save any research or analysis worth keeping\n"
+            "Use Edit/Write tools NOW. Then write the summary below.\n\n"
+        )
         COMPACT_PROMPT = (
             "[SYSTEM: Context compaction requested — handoff summary]\n\n"
-            "Write a detailed handoff summary so your next session can continue seamlessly. "
+            + (_ORCH_PRESAVE if self.is_orchestrator else "")
+            + "Write a detailed handoff summary so your next session can continue seamlessly. "
             "Be as thorough as possible — this is the ONLY context your next session will have. No length limit.\n\n"
             "INTENT: What you are working on and why (2-3 sentences with full context).\n"
             "DECISIONS: All key decisions made during this session (bullet points, include reasoning).\n"
             "FILES: Every file touched with what was done (path — description of change).\n"
             "PENDING: Open questions, unfinished work, TODOs, blockers, next steps.\n"
### 798197a5c Add context-level cost tracking (turn/ctx/total)

diff --git a/app/session.py b/app/session.py
index ce9f87f0b..9287ea6ca 100644
--- a/app/session.py
+++ b/app/session.py
@@ -160,10 +160,11 @@ class AgentSession:
     _compacting: bool = field(default=False, repr=False)
     _compact_ack_event: Optional[asyncio.Event] = field(default=None, repr=False)
     _compact_ack_gen: int = field(default=-1, repr=False)
     _last_cost: float = field(default=0.0, repr=False)
     _turn_cost: float = field(default=0.0, repr=False)
+    _context_cost: float = field(default=0.0, repr=False)
     _last_cost_cached: float = field(default=0.0, repr=False)
     _last_turn_ok: bool = field(default=True, repr=False)
     _last_stop_reason: str = field(default="", repr=False)
     _lifecycle_lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)
     _persist_task: Optional[asyncio.Task] = field(default=None, repr=False)
@@ -544,11 +545,11 @@ class AgentSession:
             self._spawn_bg(self._auto_continue())
             return
 
         live_pct = self._last_context.get("percentage", 0)
         ctx_s = f"ctx:{live_pct}%" if live_pct else ""
-        self._log("status", f"turn ended ({sr}, {nt} turns, ${self._turn_cost:.2f} this turn, ${self.cost_usd:.2f} total {ctx_s})")
+        self._log("status", f"turn ended ({sr}, {nt} turns, ${self._turn_cost:.2f} turn, ${self._context_cost:.2f} ctx, ${self.cost_usd:.2f} total {ctx_s})")
 
         self._finish_turn_status()
         self._after_turn_idle_actions(live_pct)
 
     def _apply_turn_result(self, meta: dict) -> tuple[bool, str, int]:
@@ -561,15 +562,17 @@ class AgentSession:
 
         sid = meta.get("session_id")
         if sid and sid != self.session_id:
             self._last_cost = 0.0
             self._last_cost_cached = 0.0
+            self._context_cost = 0.0
         if sid:
             self.session_id = sid
         new_cost = meta.get("cost_usd", 0)
         self._turn_cost = max(0, new_cost - self._last_cost)
         self.cost_usd += self._turn_cost
+        self._context_cost += self._turn_cost
         self._last_cost = new_cost
         new_cost_cached = meta.get("cost_usd_cached", 0)
         self.cost_usd_cached += max(0, new_cost_cached - self._last_cost_cached)
         self._last_cost_cached = new_cost_cached
         self.total_turns += nt
### a473c42f8 add WHY-only comments to backend Python files

diff --git a/app/backend_claude.py b/app/backend_claude.py
index bf53d98ba..aafb26f7e 100644
--- a/app/backend_claude.py
+++ b/app/backend_claude.py
@@ -29,25 +29,28 @@ from app.events import AgentEvent
 
 logger = logging.getLogger(__name__)
 
 _BLOCKED_TOOLS = {"AskUserQuestion", "Monitor"}
 _ORCH_BLOCKED_TOOLS = {"AskUserQuestion", "Agent", "Monitor"}
-# Имена инструмента запуска субагентов. Режем на уровне CLI (disallowed_tools),
-# а не через can_use_tool: запуск субагента идёт мимо permission-колбэка
-# (SDK отдаёт его как TaskStartedMessage), поэтому _ORCH_BLOCKED_TOOLS его не ловит.
-# Имя хеджируем двумя вариантами (Task/Agent) — лишнее имя CLI игнорирует.
+# Orchestrators must use spawn_worker instead of the built-in Agent/Task tools —
+# those bypass Orchestra's worktree isolation and session tracking.
+# Blocked via disallowed_tools (not can_use_tool) because subagent launches arrive
+# as TaskStartedMessage, which the permission callback never sees.
 _ORCH_DISALLOWED_TOOLS = ["Task", "Agent"]
+# ScheduleWakeup/Cron* removed for all agents — Orchestra manages scheduling via bg_jobs
 _ALWAYS_DISALLOWED = ["ScheduleWakeup", "CronCreate", "CronDelete", "CronList"]
 
 
 def _make_auto_approve(is_orchestrator: bool = False):
     blocked = _ORCH_BLOCKED_TOOLS if is_orchestrator else _BLOCKED_TOOLS
     async def _auto_approve(tool_name, tool_input, _context=None):
         if tool_name in blocked:
             msg = f"{tool_name} is not available for orchestrators. Use spawn_worker instead." if tool_name == "Agent" else f"{tool_name} is not available in Orchestra."
             return PermissionResultDeny(message=msg)
         if isinstance(tool_input, dict) and tool_input.get("run_in_background"):
+            # run_in_background spawns a detached process that dies when the CLI turn ends —
+            # use bg_create MCP tool instead for actual background work
             return PermissionResultDeny(message="run_in_background is disabled in Orchestra — background processes are killed when your turn ends. Run synchronously instead.")
         return PermissionResultAllow(updated_input=tool_input)
     return _auto_approve
 
 
@@ -138,10 +141,12 @@ class ClaudeBackend:
         )
         if resume_id:
             options.resume = resume_id
         else:
             options.system_prompt = {"type": "preset", "preset": "claude_code", "append": self.system_prompt}
+        # MCP merge order: user < scope < instance — more specific wins.
+        # Instance (Orchestra's own server) always overrides to prevent hijacking.
         merged_mcp = {
             **self._user_mcp_servers,
             **self._scope_mcp_servers,
             **self._mcp_servers,
         }
@@ -313,10 +318,11 @@ class ClaudeBackend:
 
                 prices = TOKEN_PRICES.get(self.model)
                 if prices:
                     p_in = prices["input"]
                     p_out = prices["output"]
+                    # Anthropic cache pricing: cache_read = 10% of input, cache_create = 125%
                     cost_cached = (input_tokens * p_in + cache_read * p_in * 0.1 + cache_create * p_in * 1.25 + output_tokens * p_out) / 1_000_000
 
             if denials:
                 logger.info(f"[{self.model}] {len(denials)} permission denial(s) this turn")
 
diff --git a/app/session.py b/app/session.py
index 9287ea6ca..622ef6ed6 100644
--- a/app/session.py
+++ b/app/session.py
@@ -27,14 +27,17 @@ _DB_EXECUTOR: Optional[concurrent.futures.ThreadPoolExecutor] = None
 def _db_executor() -> concurrent.futures.ThreadPoolExecutor:
     """Dedicated pool for DB writes so logs/persists don't contend with git ops
     on the default executor (used by asyncio.to_thread)."""
     global _DB_EXECUTOR
     if _DB_EXECUTOR is None:
+        # 4 workers: enough for concurrent log/persist bursts without starving the event loop
         _DB_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=4, thread_name_prefix="db")
     return _DB_EXECUTOR
 
 
+# Orchestrators get 2x idle time: they manage long-running workflows and get TG
+# messages from users, so premature hibernate kills useful context.
 IDLE_TIMEOUT_WORKER = 300
 IDLE_TIMEOUT_ORCHESTRATOR = 600
 
 
 
@@ -264,17 +267,19 @@ class AgentSession:
             self._log("status", f"message queued (compact in progress, {len(self._pending_messages)} pending)")
             return
 
         if self.status == AgentStatus.RUNNING:
             if self.backend_type == "codex":
+                # Codex backend is a one-shot subprocess; mid-turn inject isn't supported
                 self._pending_messages.append(message)
                 self._log("user_message", message)
                 self._log("status", f"message queued ({len(self._pending_messages)} pending)")
                 return
             self._log("user_message", message)
             try:
                 backend = await self._ensure_backend()
+                # Claude SDK supports inject via stdin during an active turn
                 await backend.send(message)
                 return
             except Exception as e:
                 logger.warning(f"[{self.name}] mid-turn inject failed, queueing: {e}")
                 self._pending_messages.append(message)
@@ -310,10 +315,13 @@ class AgentSession:
 
             did_inject = False
             pending_th = ""
             templates_changed = False
             if self.session_id and self._current_prompt and not self._prompt_injected:
+                # Inject updated system prompt once per session — workers list, role
+                # catalog, and template content drift as other agents spawn/die.
+                # Only on first message after resume; subsequent turns use cached prompt.
                 from app.prompting import prompt_template_hash
                 current_th = prompt_template_hash(self.role)
                 old_th = self._template_hash or current_th
                 templates_changed = old_th != current_th
                 pending_th = current_th
@@ -390,11 +398,12 @@ class AgentSession:
                         # Keep status=RUNNING — agent is actively being continued
                         await self._backend.send("[system] Turn timed out. Continue where you left off.")
                         continue
                     self._handle_event(event)
                     consecutive_failures = 0
-                # events() exhausted normally — treat as failure
+                # events() returns without error when the SDK stream closes unexpectedly
+                # (not via turn_end) — treat as a soft failure to trigger reconnect
                 consecutive_failures += 1
                 logger.warning(f"[{self.name}] events() exhausted normally (attempt {consecutive_failures}/{self.MAX_CONSECUTIVE_FAILURES})")
                 self._log("error", f"listener stream ended unexpectedly (attempt {consecutive_failures})")
             except asyncio.CancelledError:
                 logger.info(f"[{self.name}] claude event loop cancelled")
@@ -508,10 +517,13 @@ class AgentSession:
     def _fire_auto_report(self) -> None:
         """Send auto-report to parent immediately when worker goes idle.
         Orchestrators don't auto-report — they reply to user directly.
         Skipped if worker already sent explicit send_message, has pending messages,
         or was interrupted/stopped by user.
+
+        Without this, silent workers (those that don't call send_message) would
+        leave the orchestrator waiting forever for a signal that never comes.
         """
         if self.is_orchestrator or not self.on_idle or self._did_report:
             return
         if self._pending_messages or self._compacting:
             return
@@ -539,10 +551,12 @@ class AgentSession:
             errors = meta.get("errors") or []
### 972f530ea filter ede_diagnostic telemetry noise from turn errors

diff --git a/app/session.py b/app/session.py
index 622ef6ed6..262d076a1 100644
--- a/app/session.py
+++ b/app/session.py
@@ -546,13 +546,16 @@ class AgentSession:
         ok, sr, nt = self._apply_turn_result(meta)
         self._update_context_from_turn(meta)
         self._spawn_bg(self._refresh_context_from_api())
 
         if not ok:
-            errors = meta.get("errors") or []
-            err_txt = "; ".join(str(e) for e in errors) if errors else sr
-            self._log("error", f"turn FAILED: {err_txt}")
+            # CLI injects [ede_diagnostic] telemetry strings on interrupt — cosmetic noise, not real errors
+            errors = [e for e in (meta.get("errors") or []) if not str(e).startswith("[ede_diagnostic]")]
+            if errors:
+                self._log("error", f"turn FAILED: {'; '.join(str(e) for e in errors)}")
+            else:
+                self._log("status", f"turn interrupted ({sr})")
 
         if sr in ("error_max_turns", "max_turns") and ok:
             # SDK has a per-turn limit; auto-continue so agents don't silently stop
             # mid-task when they hit it. The injected message gives them context.
             self._log("status", f"max_turns reached ({nt}), auto-continuing")
### df7a93141 reset progress bar when agent goes idle

diff --git a/app/session.py b/app/session.py
index 262d076a1..aa66d9e57 100644
--- a/app/session.py
+++ b/app/session.py
@@ -618,10 +618,13 @@ class AgentSession:
         if bg_manager and bg_manager.has_active_jobs(self.id):
             self.status = AgentStatus.WAITING
             self._log("status", "waiting for bg jobs")
         else:
             self.status = AgentStatus.IDLE
+            # Clear progress bar so it doesn't stick at old % forever
+            self.progress_pct = 0
+            self.progress_status = ""
         self._persist()
 
     def _after_turn_idle_actions(self, live_pct: int) -> None:
         """Post-turn actions: compact ack, scope idle, auto-compact, auto-report, flush/hibernate."""
         if self._compact_ack_event is not None and self._turn_gen == self._compact_ack_gen: