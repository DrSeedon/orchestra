# Candidate cand-03

## ORIGIN commit a473c42f88 (2026-06-10): add WHY-only comments to backend Python files
(diff of code only, excluding .orchestra/ and *.md; capped 1200 lines)

diff --git a/app/backend_claude.py b/app/backend_claude.py
index bf53d98ba..aafb26f7e 100644
--- a/app/backend_claude.py
+++ b/app/backend_claude.py
@@ -26,31 +26,34 @@ from claude_agent_sdk.types import (
 )
 
 from app.events import AgentEvent
 
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
 
 
 def _disallowed_tools(is_orchestrator: bool) -> list[str]:
     """Инструменты, полностью убираемые из набора модели (через CLI),
     а не через can_use_tool. Оркестратор делегирует через spawn_worker,
@@ -135,16 +138,18 @@ class ClaudeBackend:
             max_buffer_size=50 * 1024 * 1024,
             env=env,
             user=agent_uid,
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
         if merged_mcp:
             options.mcp_servers = merged_mcp
         # F4: inherit_claude_md=False → только local-слой (нет user/project
@@ -310,16 +315,17 @@ class ClaudeBackend:
                 from app.models import CONTEXT_LIMITS, TOKEN_PRICES
                 max_tokens = CONTEXT_LIMITS.get(self.model, 200000)
                 cache_hit = int(cache_read * 100 / cache_total) if cache_total else 0
 
                 prices = TOKEN_PRICES.get(self.model)
                 if prices:
                     p_in = prices["input"]
                     p_out = prices["output"]
+                    # Anthropic cache pricing: cache_read = 10% of input, cache_create = 125%
                     cost_cached = (input_tokens * p_in + cache_read * p_in * 0.1 + cache_create * p_in * 1.25 + output_tokens * p_out) / 1_000_000
 
             if denials:
                 logger.info(f"[{self.model}] {len(denials)} permission denial(s) this turn")
 
             events.append(AgentEvent("turn_end", f"stop_reason={sr}, num_turns={nt}", metadata={
                 "session_id": self._session_id,
                 "ok": not is_err,
diff --git a/app/backend_codex.py b/app/backend_codex.py
index c3fc85d32..a669bd6c7 100644
--- a/app/backend_codex.py
+++ b/app/backend_codex.py
@@ -45,16 +45,18 @@ class CodexBackend:
         self._last_stderr: str = ""
         self._got_turn_completed: bool = False
 
     @property
     def session_id(self) -> Optional[str]:
         return self._thread_id
 
     async def connect(self) -> None:
+        # Codex launches a new subprocess per turn (stateless CLI), so connect is a no-op —
+        # the actual process starts in send() when the first message arrives
         pass
 
     async def send(self, message: str) -> None:
         self._got_turn_completed = False
         self._last_stderr = ""
 
         cmd = [CODEX_BIN]
         if self._thread_id:
@@ -188,16 +190,18 @@ class CodexBackend:
 
         if self._stderr_task:
             try:
                 await asyncio.wait_for(self._stderr_task, timeout=5)
             except (asyncio.TimeoutError, Exception):
                 pass
 
         if not self._got_turn_completed:
+            # Process exited without emitting turn.completed — treat as error turn
+            # so session.py can update status and trigger auto-report
             yield AgentEvent("turn_end", f"stop_reason=process_exit_{returncode}", metadata={
                 "session_id": self._thread_id,
                 "ok": False,
                 "stop_reason": f"process_exit_{returncode}",
                 "returncode": returncode,
                 "stderr_tail": self._last_stderr,
                 "cost_usd": 0,
                 "context_pct": 0,
@@ -228,11 +232,13 @@ class CodexBackend:
                 break
             chunks.append(chunk)
         data = b"".join(chunks)
         self._last_stderr = data[-500:].decode("utf-8", errors="replace")
 
     def _build_env(self) -> dict:
         env = dict(os.environ)
         env.update(self._mcp_env)
+        # Strip proxy for Codex: it talks directly to OpenAI, not Anthropic —
+        # routing through Hiddify would break OpenAI connectivity
         env.pop("HTTPS_PROXY", None)
         env.pop("HTTP_PROXY", None)
         return env
diff --git a/app/db.py b/app/db.py
index 58e4d0b7e..b9aa87eeb 100644
--- a/app/db.py
+++ b/app/db.py
@@ -24,17 +24,19 @@ def _resolve_db_path() -> Path:
 
 DB_PATH = _resolve_db_path()
 
 
 def _conn() -> sqlite3.Connection:
     DB_PATH.parent.mkdir(exist_ok=True)
     conn = sqlite3.connect(str(DB_PATH))
     conn.row_factory = sqlite3.Row
+    # WAL: readers don't block writers — essential when many agents log concurrently
     conn.execute("PRAGMA journal_mode=WAL")
+    # 5s busy timeout: retry on locked DB instead of raising immediately
     conn.execute("PRAGMA busy_timeout=5000")
     conn.execute("PRAGMA foreign_keys=ON")
     return conn
 
 
 def init_db() -> None:
     with _conn() as c:
         c.executescript("""
@@ -235,16 +237,18 @@ def _reconstruct_costs(c) -> None:
                 real_cost += prev
             prev = val
         real_cost += prev
         c.execute("UPDATE sessions SET cost_usd=?, cost_usd_cached=0, cost_reset_v1=1 WHERE id=?",
                   (round(real_cost, 4), s["id"]))
 
 
 def _migrate(c) -> None:
+    # Additive ALTER TABLE migrations — safe to re-run (IF NOT EXISTS / column check).
+    # Never drop columns: old Orchestra versions reading the same DB must still work.
     cols = {row[1] for row in c.execute("PRAGMA table_info(sessions)").fetchall()}
     if "color" not in cols:
         c.execute("ALTER TABLE sessions ADD COLUMN color TEXT DEFAULT ''")
     if "context_pct" not in cols:
         c.execute("ALTER TABLE sessions ADD COLUMN context_pct INTEGER DEFAULT 0")
     if "context_tokens" not in cols:
         c.execute("ALTER TABLE sessions ADD COLUMN context_tokens INTEGER DEFAULT 0")
     if "progress_pct" not in cols:
@@ -370,23 +374,26 @@ def _migrate(c) -> None:
                 c.execute(create_sql)
                 c.execute(f"INSERT INTO {tbl} SELECT * FROM {old_name}")
                 c.execute(f"DROP TABLE {old_name}")
         except Exception:
             pass
     c.execute("CREATE INDEX IF NOT EXISTS idx_tm_tasks_yougile ON tm_tasks(yougile_task_id)")
     task_cols = {row[1] for row in c.execute("PRAGMA table_info(tm_tasks)").fetchall()}
     if task_cols and "priority" not in task_cols:
+        # 0=critical, 1=high, 2=medium (default), 3=low — existing tasks land at medium
         c.execute("ALTER TABLE tm_tasks ADD COLUMN priority INTEGER NOT NULL DEFAULT 2")
     client_cols = {row[1] for row in c.execute("PRAGMA table_info(tm_clients)").fetchall()}
     if client_cols and "journal_yougile_id" not in client_cols:
         c.execute("ALTER TABLE tm_clients ADD COLUMN journal_yougile_id TEXT DEFAULT ''")
     if task_cols:
         max_price = c.execute("SELECT MAX(price_rub) FROM tm_tasks").fetchone()[0] or 0
         if 0 < max_price < 1000:
+            # Schema changed from "thousands" to exact kopeks — multiply all money
+            # columns by 1000 to bring old data in line with the new unit
             c.execute("UPDATE tm_tasks SET price_rub = price_rub * 1000, paid_rub = paid_rub * 1000")
             c.execute("UPDATE tm_payment_allocations SET amount_rub = amount_rub * 1000")
             c.execute("UPDATE tm_payments SET amount_rub = amount_rub * 1000")
             c.execute("UPDATE tm_clients SET balance_rub = balance_rub * 1000")
     if "role" not in cols:
         c.execute("ALTER TABLE sessions ADD COLUMN role TEXT DEFAULT 'worker'")
         c.execute("UPDATE sessions SET role = 'orchestrator' WHERE is_orchestrator = 1")
     if "parent_id" not in cols:
@@ -700,16 +707,18 @@ def get_stats(scope: str | None = None) -> dict:
 
 
 def cleanup_old_logs(days: int = 7) -> int:
     with _conn() as c:
         cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
         cur = c.execute("DELETE FROM logs WHERE ts < ?", (cutoff,))
         deleted = cur.rowcount
     with _conn() as c:
+        # Checkpoint after bulk delete: reclaims WAL disk space that stays
+        # allocated otherwise until the next checkpoint or DB restart
         c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
     return deleted
 
 
 def add_inbox(session_id: str, sender: str, message: str) -> int:
     with _conn() as c:
         cur = c.execute(
             "INSERT INTO inbox (session_id, sender, message, created_at) VALUES (?, ?, ?, ?)",
@@ -786,16 +795,18 @@ def bg_cron_should_fire(job_id: str) -> bool:
         row = c.execute(
             "SELECT 1 FROM bg_jobs WHERE id=? AND status='active' AND expires_at >= ?",
             (job_id, now),
         ).fetchone()
         return row is not None
 
 
 def bg_cron_record_fire(job_id: str) -> None:
+    # IMMEDIATE lock: prevents two scheduler ticks from recording the same fire
+    # (cron jobs can fire again while the previous trigger is still being processed)
     with _conn() as c:
         c.execute("BEGIN IMMEDIATE")
         row = c.execute("SELECT config, status FROM bg_jobs WHERE id=?", (job_id,)).fetchone()
         if not row or row["status"] != "active":
             c.execute("ROLLBACK")
             return
         try:
             cfg = json.loads(row["config"])
@@ -807,16 +818,18 @@ def bg_cron_record_fire(job_id: str) -> None:
         c.execute(
             "UPDATE bg_jobs SET config=?, last_output=? WHERE id=? AND status='active'",
             (json.dumps(cfg), f"fired #{cfg['fire_count']} at {now_iso}", job_id),
         )
         c.execute("COMMIT")
 
 
 def bg_claim_trigger(job_id: str) -> bool:
+    # Atomic CAS: only one concurrent checker can move job to 'triggering' —
+    # multiple scheduler ticks could race here without this guard
     with _conn() as c:
         cur = c.execute(
             "UPDATE bg_jobs SET status='triggering', triggered_at=? WHERE id=? AND status='active'",
             (datetime.now(timezone.utc).isoformat(), job_id),
         )
         return cur.rowcount > 0
 
 
@@ -991,16 +1004,18 @@ def usage_get_history(hours: int = 24, step_minutes: int = 5) -> list[dict]:
         return []
     step = timedelta(minutes=step_minutes)
     start = datetime.fromisoformat(raw[0]["ts"]).replace(tzinfo=timezone.utc)
     grid: list[dict] = []
     ri = 0
     t = start
     prev = raw[0]
     while t <= now:
+        # Step-forward interpolation: for each grid point, use the last known
+        # snapshot at or before that time — matches "last-value" chart semantics
         while ri < len(raw) - 1:
             next_ts = datetime.fromisoformat(raw[ri + 1]["ts"]).replace(tzinfo=timezone.utc)
             if next_ts > t:
                 break
             ri += 1
             prev = raw[ri]
         grid.append({**prev, "ts": t.isoformat()})
         t += step
diff --git a/app/diff_image.py b/app/diff_image.py
index 1bbbd1724..504d18fe0 100644
--- a/app/diff_image.py
+++ b/app/diff_image.py
@@ -13,16 +13,18 @@ MAX_LINES_WRITE = 30
 
 def _load_fonts():
     try:
         return (
             ImageFont.truetype(_FONT_PATH, 13),
             ImageFont.truetype(_FONT_PATH, 11),
         )
     except Exception:
+        # PIL may not be installed or font missing — graceful degradation with
+        # the built-in bitmap font rather than crashing TG diff rendering
         f = ImageFont.load_default()
         return f, f
 
 
 def _short_path(file_path: str) -> str:
     p = file_path
     p = re.sub(r'^.*/worktrees/[^/]+/[^/]+/', '', p)
     for prefix in ('/mnt/data/Projects/Python/', '/home/'):
@@ -44,17 +46,18 @@ def _lcs_diff(a: list[str], b: list[str]):
         if i > 0 and j > 0 and a[i-1] == b[j-1]:
             raw.append(('ctx', a[i-1])); i -= 1; j -= 1
         elif j > 0 and (i == 0 or dp[i][j-1] >= dp[i-1][j]):
             raw.append(('add', b[j-1])); j -= 1
         else:
             raw.append(('del', a[i-1])); i -= 1
     raw.reverse()
 
-    # pair del+add for inline diff
+    # Pair consecutive del+add into linked pairs so _inline_diff can highlight
+    # the exact characters that changed (not just the whole line)
     lines = []
     idx = 0
     while idx < len(raw):
         if raw[idx][0] == 'del' and idx + 1 < len(raw) and raw[idx+1][0] == 'add':
             lines.append(('del', raw[idx][1], raw[idx+1][1]))
             lines.append(('add', raw[idx+1][1], raw[idx][1]))
             idx += 2
         else:
diff --git a/app/main.py b/app/main.py
index 0fee1d769..589d887e6 100644
--- a/app/main.py
+++ b/app/main.py
@@ -76,16 +76,18 @@ async def global_exception_handler(request: Request, exc: Exception):
     logger.error(f"Unhandled exception on {request.method} {request.url.path}: {exc}\n{tb}")
     return JSONResponse({"error": f"Internal: {exc}"}, status_code=500)
 
 
 class AuthMiddleware(BaseHTTPMiddleware):
     async def dispatch(self, request: Request, call_next):
         path = request.url.path
         method = request.method
+        # Internal token bypasses cookie auth — allows MCP subprocess and workers
+        # to call the API without a browser session
         if check_internal_token(request.headers.get("authorization", "")):
             return await call_next(request)
         if not is_auth_enabled():
             return await call_next(request)
         if not requires_auth(path, method):
             return await call_next(request)
         token = request.cookies.get("session")
         if token and validate_session(token):
@@ -259,31 +261,34 @@ async def list_projects():
         results.append({"path": real_path, "name": folder})
     return results
 
 
 _ALLOWED_ROOTS: list[str] = []
 
 
 def _get_allowed_roots() -> list[str]:
+    # Lazy init: ALLOWED_ROOTS env lets operators add extra roots without code changes;
+    # standard data directories are always included as a baseline
     if _ALLOWED_ROOTS:
         return _ALLOWED_ROOTS
     extra = os.environ.get("ALLOWED_ROOTS", "")
     if extra:
         for p in extra.split(":"):
             if p and Path(p).is_dir():
                 _ALLOWED_ROOTS.append(p)
     for root in ["/mnt/data", "/opt", "/tmp", str(Path.home())]:
         if Path(root).is_dir():
             _ALLOWED_ROOTS.append(root)
     uploads = str(Path(__file__).parent.parent / "data" / "uploads")
     _ALLOWED_ROOTS.append(uploads)
     return _ALLOWED_ROOTS
 
 
+# Block access to secrets and key material even if they live inside an allowed root
 _DENIED_PARTS = {".env", ".ssh", ".git", ".credentials", ".gnupg", ".aws",
                  ".npmrc", ".pypirc", ".netrc", ".docker", ".kube"}
 _DENIED_HOME_PARTS = {".claude", ".config"}
 _DENIED_EXTENSIONS = {".db", ".db-shm", ".db-wal", ".db-journal", ".sqlite", ".sqlite3", ".key", ".pem", ".p12", ".pfx"}
 
 
 def _is_safe_path(path: str) -> bool:
     try:
@@ -570,16 +575,17 @@ async def stream_session_logs(name: str, scope: str, request: Request, after_id:
                     initial = False
                 else:
                     logs = get_logs(session_id, after_id=last_id, conn=c)
                     initial = False
                 for log in logs:
                     yield f"data: {json.dumps(log)}\n\n"
                     last_id = log["id"]
                 idle_ticks = 0 if logs else idle_ticks + 1
+                # Back off to 3s after 2s of inactivity — reduces DB polling when idle
                 await asyncio.sleep(0.5 if idle_ticks < 4 else 3.0)
         finally:
             c.close()
     return StreamingResponse(event_generator(), media_type="text/event-stream",
                              headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
 
 
 @app.get("/api/sessions/{name}/logs")
@@ -1338,16 +1344,17 @@ async def serve_upload(filename: str):
         path.relative_to(UPLOADS_DIR.resolve())
     except ValueError:
         return JSONResponse({"error": "forbidden"}, status_code=403)
     if not path.exists() or not path.is_file():
         return JSONResponse({"error": "not found"}, status_code=404)
     return FileResponse(path, headers={"Content-Disposition": f'attachment; filename="{path.name}"'})
 
 
+# Short TTL: git status is cheap but 10s prevents dashboard refresh storms
 _git_status_cache: dict = {}  # scope -> {ts, data}
 _GIT_STATUS_TTL = 10
 
 
 async def _run_git(cmd: list[str], cwd: str) -> str:
     proc = await asyncio.create_subprocess_exec(
         *cmd, cwd=cwd,
         stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
@@ -1450,16 +1457,17 @@ def _parse_repo_to_scope() -> dict[str, str]:
             repo, scope = item.split("=", 1)
             result[repo.strip()] = scope.strip()
     return result
 
 REPO_TO_SCOPE = _parse_repo_to_scope()
 
 
 def _verify_github_signature(payload: bytes, signature: str, secret: str) -> bool:
+    # compare_digest prevents timing attacks on the signature check
     expected = "sha256=" + hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
     return hmac.compare_digest(expected, signature)
 
 
 async def _fetch_failed_log(owner: str, repo: str, run_id: int, token: str) -> str:
     import httpx
     headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github+json"}
     async with httpx.AsyncClient(timeout=15) as client:
diff --git a/app/manager.py b/app/manager.py
index e502e0981..b515c8ff8 100644
--- a/app/manager.py
+++ b/app/manager.py
@@ -13,16 +13,17 @@ from typing import Optional
 
 from app.session import AgentSession, AgentStatus
 from app.prompting import (
     is_orchestrator_role, safe_format_prompt, read_prompt,
     role_prompt_file, role_can_spawn,
     roles_catalog, skills_catalog, prompt_template_hash, inject_skills_to_worktree,
 )
 
+# Matches "task-42/worker-name" or "PAR-42/worker-name" — extracts task number from branch
 _TASK_BRANCH_RE = re.compile(r"^(?:task-|[A-Z]{2,5}-)(\d+)/")
 from app.workspace import create_worktree, remove_worktree, parse_owned_dirs, dirs_overlap
 from app.models import resolve_model, backend_for_model
 from app.pipeline import (
     DEFAULT_PIPELINE,
     build_system_prompt,
     get_active_pipeline,
     get_role,
@@ -37,16 +38,18 @@ from app.db import (
     delete_session, archive_session, get_stats,
 )
 
 logger = logging.getLogger(__name__)
 
 _PROJECT_ROOT = str(Path(__file__).parent.parent)
 _MCP_SCRIPT = str(Path(__file__).parent / "mcp_stdio.py")
 MCP_STDIO_CMD = [sys.executable, _MCP_SCRIPT]
+# Propagate proxy + auth token to the MCP subprocess so it can reach Anthropic
+# and call back to Orchestra's own API with internal auth
 MCP_BASE_ENV = {"PYTHONPATH": _PROJECT_ROOT}
 for _k in ("HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY", "INTERNAL_TOKEN"):
     if os.environ.get(_k):
         MCP_BASE_ENV[_k] = os.environ[_k]
 
 COLOR_PALETTE = [
     "#818cf8", "#34d399", "#f97316", "#38bdf8", "#f472b6",
     "#a78bfa", "#fbbf24", "#2dd4bf", "#fb7185", "#4ade80",
@@ -325,16 +328,18 @@ class SessionManager:
 
     async def _spawn_worker_loop(self) -> None:
         from app.db import update_job
         while True:
             job = await self._spawn_queue.get()
             job_id = job.get("job_id", "?")
             try:
                 update_job(job_id, "executing")
+                # Brief yield: lets the MCP tool that enqueued this job return its
+                # response to the agent before the spawn starts writing to the DB
                 await asyncio.sleep(0.5)
                 session = await self.create_session(
                     name=job["name"], scope=job["repo_path"], cwd=job["repo_path"],
                     model=job["model"], system_prompt=job.get("system_prompt", ""),
                     use_worktree=True, repo_path=job["repo_path"],
                     role=job.get("role", "worker"),
                     task_id=job.get("task_id", ""),
                     description=job.get("description", ""),
@@ -347,16 +352,18 @@ class SessionManager:
             except Exception as e:
                 update_job(job_id, "failed", str(e))
                 logger.error(f"Spawn '{job.get('name')}' failed (job {job_id}): {e}")
             finally:
                 self._spawn_queue.task_done()
 
     @staticmethod
     def _auto_commit_if_dirty(repo_path: str) -> str:
+        # Worktrees branch from HEAD of the source repo — if it's dirty, the new
+        # worktree inherits unstaged junk. Auto-commit gives the worker a clean base.
         import subprocess, datetime
         r = subprocess.run(["git", "status", "--porcelain"], cwd=repo_path, capture_output=True, text=True)
         if r.returncode != 0:
             logger.error(f"auto-commit git status failed in {repo_path}: {r.stderr.strip()}")
             return f"FAILED to check repo status (git status rc={r.returncode}) — spawn proceeds, auto-save NOT run"
         if not r.stdout.strip():
             return ""
         files = [l[3:] for l in r.stdout.strip().splitlines()]
@@ -473,22 +480,23 @@ class SessionManager:
                 pipeline = get_active_pipeline(scope, parent_pipeline=parent_pipeline)
                 is_orch = self._role_is_orchestrator(pipeline, role)
             if parent_name and not explicit_profile:
                 # Тот же авто-найденный родитель — воркер наследует и его профиль.
                 parent_profile = self._resolve_profile(parent_name, scope)
                 profile = get_active_profile(scope, parent_profile=parent_profile)
 
         if is_orch:
-            # v2.16: кастомный system_prompt ДОПИСЫВАЕТСЯ к базе роли, а не заменяет
-            # её (раньше было `system_prompt or ROLE_SYSTEM_PROMPT(...)`).
+            # v2.16: custom system_prompt appended to role base, not replacing it —
+            # orchestrators need their catalog/worker-blocks to stay intact for navigation
             prompt = ROLE_SYSTEM_PROMPT(pipeline, role, scope) + ("\n\n" + system_prompt if system_prompt else "")
         else:
             prompt = ROLE_SYSTEM_PROMPT(pipeline, role) + ("\n\n" + system_prompt if system_prompt else "")
-            # Ownership (upstream): для воркера дописываем блок "трогай только это".
+            # Inject directory ownership constraint into prompt so worker refuses
+            # to touch files outside its slice — prevents parallel-worker conflicts
             prompt += self._ownership_prompt(owned_dirs)
 
         if not parent_id and parent_name:
             p_session = self.get_by_name(parent_name, scope)
             if p_session:
                 parent_id = p_session.id if isinstance(p_session, AgentSession) else p_session.get("id", "")
 
         # R2: валидация спавна ДО любых side-effects (worktree/start).
@@ -506,17 +514,18 @@ class SessionManager:
                         f"role '{parent_role}' is not allowed to spawn role '{role}'. "
                         f"Allowed: {allowed}"
                     )
 
         # Резолв базовой ветки worktree по стратегии манифеста (DESIGN §10, B3).
         # Делаем ДО create_worktree, когда pipeline/role/parent_name уже определены.
         base_branch = self._resolve_base_branch(base_branch, pipeline, role, parent_name, scope)
 
-        # Root orchestrators (no parent) always get a TG topic
+        # Root orchestrators get a dedicated TG topic so users can message them
+        # directly from Telegram without knowing worker names
         if is_orch and not parent_name:
             tg_topic = True
 
         custom_mcp = _parse_custom_mcp(mcp_servers)
         bt = backend_for_model(model)
         session = AgentSession(
             id=str(uuid.uuid4()), name=name, scope=scope, cwd=cwd, model=model,
             system_prompt=prompt, role=role,
@@ -1016,20 +1025,22 @@ class SessionManager:
             ).fetchall()}
             was_waiting = {r["id"] for r in c.execute(
                 "SELECT id FROM sessions WHERE status = 'waiting'"
             ).fetchall()}
             resumable = [dict(r) for r in c.execute(
                 "SELECT * FROM sessions WHERE session_id IS NOT NULL "
                 "AND status IN ('running', 'idle', 'waiting')"
             ).fetchall()]
+            # Reset to idle before loading: prevents any session from resuming
+            # as 'running' (the backend process died on server restart)
             c.execute("UPDATE sessions SET status='idle' WHERE status IN ('running', 'waiting')")
 
-        # R1: используем денормализованную колонку is_orchestrator (наши PM-роли
-        # не входят в frozenset апстрима; колонка проставлена при спавне/миграции).
+        # R1: load orchestrators first — workers need their parent_name resolved,
+        # and the orchestrator's on_idle callback registered before workers resume
         orchs = [r for r in resumable if bool(r.get("is_orchestrator")) or is_orchestrator_role(r.get("role", "worker"))]
         workers = [r for r in resumable if not (bool(r.get("is_orchestrator")) or is_orchestrator_role(r.get("role", "worker")))]
 
         for row in orchs:
             if row["id"] in self.sessions:
                 continue
             if not Path(row.get("cwd") or row["scope"]).is_dir():
                 continue
@@ -1061,16 +1072,18 @@ class SessionManager:
                         session._persist()
                 elif row["id"] in was_running:
                     asyncio.create_task(self._inject_restart_notice(session))
             except Exception as e:
                 logger.error(f"Failed to resume worker {row['name']}: {e}")
 
     async def _inject_restart_notice(self, session: AgentSession) -> None:
         import random
+        # Random stagger: if N agents resume simultaneously they'd all hit the SDK
+        # concurrently and cause a connection storm; spread them over 15s
         await asyncio.sleep(3 + random.uniform(0, 12))
         try:
             await session.send(
                 "[system] Orchestra server restarted. "
                 "Your session was restored — continue where you left off."
             )
             logger.info(f"Restart notice injected: {session.name}")
         except Exception as e:
diff --git a/app/mcp_stdio.py b/app/mcp_stdio.py
index ac884d147..b619c8631 100644
--- a/app/mcp_stdio.py
+++ b/app/mcp_stdio.py
@@ -9,16 +9,17 @@ Usage: python -m app.mcp_stdio
 import json
 import logging
 import os
 import sys
 
 import httpx
 from mcp.server.fastmcp import FastMCP
 
+# Logs go to stderr so they don't pollute the JSON-RPC stdout stream
 logging.basicConfig(level=logging.INFO, stream=sys.stderr)
 logger = logging.getLogger("orchestra-mcp")
 
 ORCHESTRA_URL = os.environ.get("ORCHESTRA_URL", "http://127.0.0.1:8888")
 SCOPE = os.environ.get("ORCHESTRA_SCOPE", "")
 ROLE = os.environ.get("ORCHESTRA_ROLE", "orchestrator")
 WORKER_NAME = os.environ.get("WORKER_NAME", "worker")
 _INTERNAL_TOKEN = os.environ.get("INTERNAL_TOKEN", "")
@@ -28,16 +29,17 @@ mcp = FastMCP("orchestra")
 
 def _auth_headers() -> dict:
     if _INTERNAL_TOKEN:
         return {"Authorization": f"Bearer {_INTERNAL_TOKEN}"}
     return {}
 
 
 async def _api(method: str, path: str, **kwargs) -> dict | list | None:
+    # New client per call: avoids shared state across tool invocations in the same MCP session
     t = kwargs.pop("timeout", 30)
     headers = _auth_headers()
     async with httpx.AsyncClient(base_url=ORCHESTRA_URL, timeout=t, headers=headers) as client:
         if method == "GET":
             r = await client.get(path, params=kwargs.get("params"))
         elif method == "POST":
             r = await client.post(path, json=kwargs.get("json"))
         elif method == "PUT":
@@ -644,16 +646,17 @@ async def bg_list() -> str:
 async def bg_cancel(job_id: str) -> str:
     """Cancel an active background job."""
     result = await _api("DELETE", f"/api/bg/jobs/{job_id}")
     if isinstance(result, dict) and result.get("error"):
         return f"Cancel failed: {result['error']}"
     return f"Job {job_id} cancelled."
 
 
+# Hardcoded path: Codex CLI installed globally via npm, not in the uv venv
 _CODEX_BIN = "/home/maxim/.npm-global/bin/codex"
 _REVIEW_CONTEXT = (
     "PROJECT CONTEXT (calibrate review severity):\n"
     "- Scale: small team, MVP stage\n"
     "- Philosophy: simple, flat, minimal abstractions\n"
     "- blocking = crash/corrupt/security. suggestion = real improvement. nit = skip\n"
 )
 
@@ -681,16 +684,17 @@ async def codex_review(
         prompt_parts.append(f"Additional context: {context}\n")
     prompt_parts.append(f"Write your review to {output}.")
     prompt_parts.append("Format: ## Summary, ## Findings (blocking/suggestion/question), ## Verdict")
     review_prompt = "\n".join(prompt_parts)
 
     prompt_file = f"/tmp/codex_review_{WORKER_NAME}.txt"
 
     if mode == "review":
+        # Clear proxy vars: Codex talks to OpenAI, not Anthropic — same as _build_env
         cmd = (
             f"cd {cwd} && HTTPS_PROXY= HTTP_PROXY= UV_CACHE_DIR=/tmp/uv-cache {_CODEX_BIN} exec review"
             f" --uncommitted --skip-git-repo-check --full-auto --ephemeral"
             f" -o {output_abs}"
         )
     elif mode == "exec":
         if not target:
             return "Error: target file required for mode='exec'"
diff --git a/app/models.py b/app/models.py
index 7b2536d97..5dc42dcb7 100644
--- a/app/models.py
+++ b/app/models.py
@@ -17,16 +17,18 @@ CONTEXT_LIMITS = {
     "claude-opus-4-6[1m]": 1000000,
     "claude-sonnet-4-6": 200000,
     "claude-haiku-4-5": 200000,
     "gpt-5.5": 258400,
     "gpt-5.4": 258400,
     "gpt-5.4-mini": 258400,
 }
 
+# Short aliases let agents use "opus", "sonnet" etc. in spawn_worker without
+# knowing the exact versioned model ID — reduces prompt brittleness on model upgrades
 ALIASES = {
     "fable": "claude-fable-5[1m]",
     "fable5": "claude-fable-5[1m]",
     "claude-fable-5": "claude-fable-5[1m]",
     "claude-fable-5-1m": "claude-fable-5[1m]",
     "mythos": "claude-fable-5[1m]",
     "opus": "claude-opus-4-6[1m]",
     "opus4.8": "claude-opus-4-8[1m]",
@@ -51,16 +53,18 @@ BACKENDS = {
     "claude-opus-4-6[1m]": "claude",
     "claude-sonnet-4-6": "claude",
     "claude-haiku-4-5": "claude",
     "gpt-5.5": "codex",
     "gpt-5.4": "codex",
     "gpt-5.4-mini": "codex",
 }
 
+# TOKEN_PRICES is for internal cost tracking only (subscription plan, not real API billing)
+# Codex models intentionally absent — their prices live in backend_codex.py
 TOKEN_PRICES = {
     "claude-fable-5[1m]": {"input": 10.0, "output": 50.0},
     "claude-opus-4-8[1m]": {"input": 15.0, "output": 75.0},
     "claude-opus-4-6[1m]": {"input": 15.0, "output": 75.0},
     "claude-sonnet-4-6":   {"input": 3.0,  "output": 15.0},
     "claude-haiku-4-5":    {"input": 0.80, "output": 4.0},
 }
 
diff --git a/app/pipeline.py b/app/pipeline.py
index a3d30bd79..30c5d0829 100644
--- a/app/pipeline.py
+++ b/app/pipeline.py
@@ -30,17 +30,21 @@ DEFAULT_PIPELINE = "default"
 AllOrList = Union[Literal["all"], list[str]]
 
 Kind = Literal["orchestrator", "worker"]
 ValidationMode = Literal["fail-closed", "fail-open"]
 BranchStrategy = Literal["parent", "main"]
 
 
 def _model_is_known(model: str) -> bool:
-    """Модель валидна, если это alias (lowercase) ИЛИ полный id из app.models."""
+    """Модель валидна, если это alias (lowercase) ИЛИ полный id из app.models.
+
+    Two-tier check: aliases use lowercase comparison so manifest can write
+    'opus' or 'Opus', but full model IDs are case-sensitive (must match MODELS).
+    """
     return model.lower() in ALIASES or model in MODELS
 
 
 def _is_safe_rel(p: str) -> bool:
     """True если ``p`` — безопасный относительный путь (без абсолютного и '..').
 
     Защита изоляции: слои промпта/шаблоны не должны выходить за pipelines/<name>/.
     """
diff --git a/app/session.py b/app/session.py
index 9287ea6ca..622ef6ed6 100644
--- a/app/session.py
+++ b/app/session.py
@@ -24,20 +24,23 @@ import concurrent.futures
 _DB_EXECUTOR: Optional[concurrent.futures.ThreadPoolExecutor] = None
 
 
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
 
 
 
 def _load_scope_mcp_servers(scope: str) -> dict:
     servers = {}
     for name in ("settings.json", "settings.local.json"):
@@ -261,23 +264,25 @@ class AgentSession:
         if self._compacting:
             self._pending_messages.append(message)
             self._log("user_message", message)
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
                 self._log("status", f"inject failed, queued ({len(self._pending_messages)} pending)")
                 return
 
@@ -307,16 +312,19 @@ class AgentSession:
             self.progress_pct = 0
             self.progress_status = ""
             self._log("user_message", message)
 
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
                 message = f"[Orchestra platform note: {'your role instructions were updated.' if templates_changed else 'refreshed context (worker list, etc.).'} This is from the server, not another agent.]\n{self._current_prompt}\n\n---\n\n{message}"
                 did_inject = True
 
@@ -387,17 +395,18 @@ class AgentSession:
                         logger.error(f"[{self.name}] turn timeout")
                         self._log("error", f"Turn timeout ({self.TURN_TIMEOUT}s)")
                         self._turn_start = asyncio.get_event_loop().time()
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
                 return
             except Exception as e:
                 consecutive_failures += 1
@@ -505,16 +514,19 @@ class AgentSession:
         self._turn_gen += 1
         self._cancel_auto_report()
 
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
         if not self._last_turn_ok:
             return
         last_texts = self._turn_logs[-5:] if self._turn_logs else []
@@ -536,16 +548,18 @@ class AgentSession:
         self._spawn_bg(self._refresh_context_from_api())
 
         if not ok:
             errors = meta.get("errors") or []
             err_txt = "; ".join(str(e) for e in errors) if errors else sr
             self._log("error", f"turn FAILED: {err_txt}")
 
         if sr in ("error_max_turns", "max_turns") and ok:
+            # SDK has a per-turn limit; auto-continue so agents don't silently stop
+            # mid-task when they hit it. The injected message gives them context.
             self._log("status", f"max_turns reached ({nt}), auto-continuing")
             self._spawn_bg(self._auto_continue())
             return
 
         live_pct = self._last_context.get("percentage", 0)
         ctx_s = f"ctx:{live_pct}%" if live_pct else ""
         self._log("status", f"turn ended ({sr}, {nt} turns, ${self._turn_cost:.2f} turn, ${self._context_cost:.2f} ctx, ${self.cost_usd:.2f} total {ctx_s})")
 
@@ -557,22 +571,25 @@ class AgentSession:
         ok = meta.get("ok", True)
         sr = meta.get("stop_reason", "unknown")
         nt = meta.get("num_turns", 0)
         self._last_turn_ok = ok
         self._last_stop_reason = sr
 
         sid = meta.get("session_id")
         if sid and sid != self.session_id:
+            # SDK reports cost_usd cumulative per session_id — reset baseline
+            # when a new session starts (e.g. after compact creates a fresh session)
             self._last_cost = 0.0
             self._last_cost_cached = 0.0
             self._context_cost = 0.0
         if sid:
             self.session_id = sid
         new_cost = meta.get("cost_usd", 0)
+        # Delta from last known cumulative — gives per-turn cost without SDK support
         self._turn_cost = max(0, new_cost - self._last_cost)
         self.cost_usd += self._turn_cost
         self._context_cost += self._turn_cost
         self._last_cost = new_cost
         new_cost_cached = meta.get("cost_usd_cached", 0)
         self.cost_usd_cached += max(0, new_cost_cached - self._last_cost_cached)
         self._last_cost_cached = new_cost_cached
         self.total_turns += nt
@@ -605,38 +622,44 @@ class AgentSession:
     def _after_turn_idle_actions(self, live_pct: int) -> None:
         """Post-turn actions: compact ack, scope idle, auto-compact, auto-report, flush/hibernate."""
         if self._compact_ack_event is not None and self._turn_gen == self._compact_ack_gen:
             self._compact_ack_event.set()
 
         self._spawn_bg(self._notify_scope_idle())
 
         if live_pct > 90 and not self.is_orchestrator and not self._compacting:
+            # Workers auto-compact to stay operational; orchestrators are left for
+            # the user to compact manually since they hold long-running session state
             self._log("status", f"auto-compact triggered ({live_pct}%)")
             self._spawn_bg(self._auto_compact())
 
         self._fire_auto_report()
 
         if self._pending_messages:
             self._spawn_bg(self._flush_pending())
             return
 
         self._schedule_hibernate()
 
     async def _flush_pending(self) -> None:
+        # Brief delay: let the just-finished turn fully settle (persist, hibernate schedule)
+        # before starting the next one — avoids nested lock acquisition from the same coroutine
         await asyncio.sleep(0.3)
         if self._compacting:
             return
         if not self._pending_messages:
             return
         msgs = list(self._pending_messages)
         self._pending_messages.clear()
         if len(msgs) == 1:
             combined = msgs[0]
         else:
+            # Batch queued messages into one turn to avoid spawning N sequential turns —
+            # each turn has ~3s round-trip overhead and occupies the lifecycle lock
             combined = "\n".join(
                 f"--- message {i+1}/{len(msgs)} ---\n{m}"
                 for i, m in enumerate(msgs)
             )
         self._log("status", f"delivering {len(msgs)} queued message(s)")
         try:
             async with self._lifecycle_lock:
                 if self._compacting:
@@ -987,16 +1010,18 @@ class AgentSession:
     async def stop(self) -> None:
         self._cancel_auto_report()
         await self._disconnect_backend()
         self._hibernated = False
         self.status = AgentStatus.IDLE
         self._persist()
 
     def _persist(self) -> None:
+        # Coalesce rapid successive calls: mark dirty, let one active task drain them all —
+        # prevents N DB writes when status/cost/context all change in the same event loop tick
         self._persist_dirty = True
         if self._persist_task and not self._persist_task.done():
             return
         self._persist_task = asyncio.get_running_loop().create_task(self._persist_loop())
         self._persist_task.add_done_callback(self._on_persist_done)
 
     def _on_persist_done(self, task: asyncio.Task) -> None:
         try:
@@ -1015,16 +1040,17 @@ class AgentSession:
             except Exception as e:
                 logger.error(f"[{self.name}] persist failed: {e}")
 
     async def _drain_persist(self) -> None:
         if self._persist_task and not self._persist_task.done():
             await asyncio.gather(self._persist_task, return_exceptions=True)
 
     def _log(self, type: str, content: str) -> None:
+        # Fire-and-forget on dedicated DB pool — keeps event loop non-blocking for log-heavy turns
         asyncio.get_event_loop().run_in_executor(_db_executor(), add_log, self.id, datetime.now(timezone.utc), type, content)
 
     def _to_db_dict(self) -> dict:
         return {
             "id": self.id, "name": self.name, "scope": self.scope, "cwd": self.cwd,
             "model": self.model, "system_prompt": self.system_prompt,
             "status": self.status.value, "session_id": self.session_id,
             "cost_usd": self.cost_usd, "cost_usd_cached": self.cost_usd_cached,
diff --git a/app/tm.py b/app/tm.py
index 6845af279..551349ecc 100644
--- a/app/tm.py
+++ b/app/tm.py
@@ -234,16 +234,18 @@ def update_task(conn: sqlite3.Connection, task_id: int, *,
         if task["status"] == "cancelled":
             raise ValueError("Cannot change price on cancelled task")
         if price_rub < task["paid_rub"]:
             raise ValueError(f"Cannot lower price below paid_rub ({task['paid_rub']})")
         updates.append("price_rub = ?")
         params.append(price_rub)
         changed.append("price")
         if task["status"] == "paid" and price_rub > task["paid_rub"]:
+            # Price raised above what was paid — reopen to 'done' so the debt
+            # shows up in the next payment distribution
             updates.append("status = 'done'")
             updates.append("paid_at = NULL")
             changed.append("status")
 
     old_status = task["status"]
     if status is not None and status != old_status:
         if status not in VALID_STATUSES:
             raise ValueError(f"Invalid status: {status}")
@@ -423,16 +425,18 @@ def receive_payment(conn: sqlite3.Connection, client_id: str, amount_rub: int,
         "remainder_to_balance": result["remainder_to_balance"],
         "new_balance": new_balance,
         "total_debt_remaining": total_debt,
     }
 
 
 def _distribute_payment(conn: sqlite3.Connection, payment_id: int,
                         client_id: str, amount_rub: int) -> dict:
+    # Greedy distribution: smallest debt first → closes the most tasks per payment.
+    # Unallocated remainder lands in client balance for future tasks.
     tasks = conn.execute(
         """SELECT * FROM tm_tasks
            WHERE status = 'done' AND price_rub > 0
              AND project_id IN (SELECT project_id FROM tm_clients WHERE id = ?)
              AND paid_rub < price_rub
            ORDER BY (price_rub - paid_rub) ASC, par_number ASC""",
         (client_id,),
     ).fetchall()
diff --git a/app/workspace.py b/app/workspace.py
index 2b256dded..c95e0ccff 100644
--- a/app/workspace.py
+++ b/app/workspace.py
@@ -17,16 +17,18 @@ if TYPE_CHECKING:
     # Только для аннотаций (строковые аннотации + from __future__ import annotations):
     # рантайм-импорт не нужен, объекты приходят готовыми от вызывающего. Так избегаем
     # циклической зависимости (pipeline ← workspace).
     from app.pipeline import Symlink, Worktree as WorktreeCfg
 
 logger = logging.getLogger(__name__)
 
 WORKTREE_ROOT = Path(__file__).parent.parent / "worktrees"
+# Files copied into each new worktree so workers get project config without
+# being on the main branch (CLAUDE.md = project rules, .env = secrets, .mcp.json = tools)
 PROJECT_FILES = ("CLAUDE.md", ".worktreeinclude", ".mcp.json", ".env")
 
 
 @dataclass
 class Worktree:
     path: str
     branch: str
 
@@ -236,17 +238,21 @@ def _get_commit_messages(repo: str, branch: str, base: str) -> list[str]:
         cwd=repo, capture_output=True, text=True,
     )
     if log.returncode != 0 or not log.stdout.strip():
         return []
     return [line for line in log.stdout.strip().splitlines() if line.strip()]
 
 
 def _build_squash_message(branch: str, messages: list[str]) -> str:
-    """Build squash commit message with task refs prefix and message list."""
+    """Build squash commit message with task refs prefix and message list.
+
+    Squash merge collapses N worker commits into one clean main-branch commit.
+    The message aggregates all task refs so PM tooling can link the merge to tasks.
+    """
     all_refs: list[str] = []
     seen: set[str] = set()
     for msg in messages:
         for m in _TASK_REF_RE.finditer(msg):
             if m.group(3):
                 ref = f"#{m.group(3)}"
             else:
                 ref = f"#{m.group(2)}"
@@ -265,17 +271,20 @@ def _build_squash_message(branch: str, messages: list[str]) -> str:
     body_lines = "\n".join(f"- {m}" for m in messages)
     if len(messages) > 1:
         return f"{header}\n\nSquashed commits:\n{body_lines}"
     return header
 
 
 def _cherry_pick_branch(repo: str, branch: str, old_head: str) -> dict:
     """Cherry-pick all commits from branch onto current HEAD.
-    Fallback for unrelated histories where git merge refuses to work.
+
+    Fallback for unrelated histories: happens when a worker was spawned from a
+    separate repo or rebased its branch, losing the common ancestor with main.
+    git merge refuses unrelated histories; cherry-pick applies diffs anyway.
     """
     rev_list = subprocess.run(
         ["git", "rev-list", "--reverse", branch],
         cwd=repo, capture_output=True, text=True,
     )
     if rev_list.returncode != 0 or not rev_list.stdout.strip():
         return {"ok": False, "error": f"cannot list commits on {branch}: {rev_list.stderr.strip()}"}
 
@@ -347,19 +356,21 @@ def merge_worktree_to_main(worktree_path: str, repo_path: str, target_branch: st
     repo = _resolve_repo(str(wt), repo_path)
     lock_path = repo / ".git" / "orchestra-merge.lock"
 
     original_branch = None   # инициализируем ДО try/with — finally видит всегда
     did_stash = False         # инициализируем ДО try — иначе UnboundLocalError в finally
     result = None             # инициализируем ДО try — возврат по умолчанию при любом пути
 
     with open(lock_path, "w") as lock_file:
+        # Exclusive lock prevents two concurrent merges from racing on main — git
+        # squash-merge is not atomic and needs the repo HEAD stable throughout
         fcntl.flock(lock_file, fcntl.LOCK_EX)
         try:
-            # Сохраняем исходную ветку ДО любого checkout
+            # Save original branch BEFORE any checkout — needed to restore it in finally
             original_branch_result = subprocess.run(
                 ["git", "symbolic-ref", "--short", "HEAD"],
                 cwd=str(repo), capture_output=True, text=True,
             )
             original_branch = original_branch_result.stdout.strip() if original_branch_result.returncode == 0 else None
 
             branch_result = subprocess.run(
                 ["git", "rev-parse", "--abbrev-ref", "HEAD"],
@@ -470,17 +481,18 @@ def merge_worktree_to_main(worktree_path: str, repo_path: str, target_branch: st
                                                 merged_commits = _parse_merged_commits(str(repo), old_head) if old_head else {}
                                                 result = {"ok": True, "commits_merged": commits_merged, "branch": branch, "merged_commits": merged_commits}
                                         else:
                                             result = {"ok": True, "commits_merged": 0, "branch": branch, "merged_commits": {}}
 
                                         if result and result.get("ok"):
                                             _reset_worktree_to_ref(str(wt), target_branch, str(repo))
         finally:
-            # ПОРЯДОК КРИТИЧЕН: сначала restore исходной ветки, ПОТОМ stash pop.
+            # Order is critical: restore HEAD branch first, then stash pop.
+            # Stash pop on the wrong branch would apply changes to the wrong tree.
             restore_ok = True
             if original_branch and original_branch != target_branch:
                 restore = subprocess.run(
                     ["git", "checkout", original_branch],
                     cwd=str(repo), capture_output=True, text=True,
                 )
                 if restore.returncode != 0:
                     restore_ok = False
@@ -492,16 +504,17 @@ def merge_worktree_to_main(worktree_path: str, repo_path: str, target_branch: st
                 pop = subprocess.run(
                     ["git", "stash", "pop"], cwd=str(repo), capture_output=True, text=True,
                 )
                 if pop.returncode != 0:
                     logger.error(f"stash pop failed: {pop.stderr.strip()} — repo state may be dirty")
                     result = {"ok": False, "state": "stash_pop_failed",
                               "error": f"stash pop failed after merge: {pop.stderr.strip()}"}
             elif did_stash and not restore_ok:
+                # Better to leave stash intact than pop onto whatever branch we're stuck on
                 logger.error("skipping stash pop: HEAD restore failed; stash kept to avoid wrong-branch apply")
             fcntl.flock(lock_file, fcntl.LOCK_UN)
     return result if result is not None else {"ok": False, "error": "merge produced no result"}
 
 
 _TASK_REF_RE = re.compile(r"(?:\b([A-Z]{2,5})-(\d+)\b|#(\d+)\b)")
 
 
@@ -592,16 +605,17 @@ def switch_worktree_branch(worktree_path: str, new_branch: str,
         dirty_files = [l[3:] for l in dirty_lines]
         return {"ok": False, "error": f"dirty working tree ({len(dirty_lines)} file(s): {', '.join(dirty_files)}) — commit or discard first"}
 
     unmerged = subprocess.run(
         ["git", "rev-list", f"{from_ref}..HEAD", "--count"],
         cwd=str(wt), capture_output=True, text=True,
     )
     if not force and unmerged.returncode == 0 and int(unmerged.stdout.strip() or "0") > 0:
+        # Guard: switching with unmerged commits would silently discard the worker's work
         n = unmerged.stdout.strip()
         return {"ok": False, "error": f"{n} unmerged commit(s) on current branch — merge_worker first or pass force=True"}
 
     reset = subprocess.run(
         ["git", "reset", "--hard", from_ref],
         cwd=str(wt), capture_output=True, text=True,
     )
     if reset.returncode != 0:


## LATER FIX 76ea4de820 (2.8 days later): fix: pipeline model validation uses resolve_model fallback — unblocks enterprise single-model
lines of origin it changed/deleted: 3
(code only, capped 400 lines)

fix: pipeline model validation uses resolve_model fallback — unblocks enterprise single-model


diff --git a/app/pipeline.py b/app/pipeline.py
index 30c5d0829..ef6cb6bdb 100644
--- a/app/pipeline.py
+++ b/app/pipeline.py
@@ -30,22 +30,26 @@ DEFAULT_PIPELINE = "default"
 AllOrList = Union[Literal["all"], list[str]]
 
 Kind = Literal["orchestrator", "worker"]
 ValidationMode = Literal["fail-closed", "fail-open"]
 BranchStrategy = Literal["parent", "main"]
 
 
 def _model_is_known(model: str) -> bool:
-    """Модель валидна, если это alias (lowercase) ИЛИ полный id из app.models.
+    """Модель валидна, если резолвится в любую доступную модель.
 
-    Two-tier check: aliases use lowercase comparison so manifest can write
-    'opus' or 'Opus', but full model IDs are case-sensitive (must match MODELS).
+    In enterprise mode with limited models, resolve_model falls back to
+    first available — so any alias is valid as long as MODELS is non-empty.
     """
-    return model.lower() in ALIASES or model in MODELS
+    if model.lower() in ALIASES or model in MODELS:
+        return True
+    from app.models import resolve_model
+    resolved = resolve_model(model)
+    return resolved in MODELS
 
 
 def _is_safe_rel(p: str) -> bool:
     """True если ``p`` — безопасный относительный путь (без абсолютного и '..').
 
     Защита изоляции: слои промпта/шаблоны не должны выходить за pipelines/<name>/.
     """
     from pathlib import PurePosixPath


## LATER FIX 83d824805f (5.7 days later): fix: readable bash/read/grep result images — bigger font, word wrap, line limit
lines of origin it changed/deleted: 2
(code only, capped 400 lines)

fix: readable bash/read/grep result images — bigger font, word wrap, line limit


diff --git a/app/diff_image.py b/app/diff_image.py
index 504d18fe0..e77a99de7 100644
--- a/app/diff_image.py
+++ b/app/diff_image.py
@@ -6,29 +6,42 @@ from PIL import Image, ImageDraw, ImageFont
 
 
 _FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
 
 MAX_LINES_EDIT = 50
 MAX_LINES_WRITE = 30
 
 
+WRAP_COLS = 90
+
+
 def _load_fonts():
     try:
         return (
+            ImageFont.truetype(_FONT_PATH, 16),
             ImageFont.truetype(_FONT_PATH, 13),
-            ImageFont.truetype(_FONT_PATH, 11),
         )
     except Exception:
-        # PIL may not be installed or font missing — graceful degradation with
-        # the built-in bitmap font rather than crashing TG diff rendering
         f = ImageFont.load_default()
         return f, f
 
 
+def _wrap_line(text: str, cols: int = WRAP_COLS) -> list[str]:
+    if len(text) <= cols:
+        return [text]
+    parts = []
+    while len(text) > cols:
+        parts.append(text[:cols])
+        text = text[cols:]
+    if text:
+        parts.append(text)
+    return parts
+
+
 def _short_path(file_path: str) -> str:
     p = file_path
     p = re.sub(r'^.*/worktrees/[^/]+/[^/]+/', '', p)
     for prefix in ('/mnt/data/Projects/Python/', '/home/'):
         if p.startswith(prefix):
             p = p[len(prefix):]
     return p
 
@@ -89,28 +102,24 @@ def _inline_diff(line: str, other: str | None):
 
 _BG = {'del': (50, 20, 20), 'add': (15, 40, 25)}
 _BG_G = {'del': (70, 25, 25), 'add': (20, 55, 30)}
 _CLR = {'del': (254, 202, 202), 'add': (187, 247, 208), 'ctx': (148, 163, 184)}
 _CLR_G = {'del': (248, 113, 113), 'add': (74, 222, 128), 'ctx': (71, 85, 105)}
 _HL = {'del': (120, 40, 40), 'add': (15, 70, 40)}
 _SIGN = {'del': '−', 'add': '+', 'ctx': ' '}
 
-LINE_H = 22
-GUTTER_W = 24
-PAD_X = 10
-HEADER_H = 26
+LINE_H = 26
+GUTTER_W = 28
+PAD_X = 12
+HEADER_H = 30
 
 
-def _measure_max_w(font, lines_text: list[str]) -> int:
-    max_w = 700
-    for text in lines_text:
-        tw = font.getlength(text) + GUTTER_W + PAD_X * 2 + 20
-        max_w = max(max_w, int(tw))
-    return min(max_w, 1200)
+def _measure_max_w(_font, _lines_text: list[str]) -> int:
+    return 800
 
 
 def _draw_header(draw, max_w: int, label: str, font_small):
     draw.line([0, HEADER_H, max_w, HEADER_H], fill=(30, 41, 59))
     draw.text((PAD_X, 5), label, fill=(100, 116, 139), font=font_small)
 
 
 def _draw_truncated(draw, y: int, remaining: int, font_small):
@@ -140,32 +149,35 @@ def render_edit_diff(file_path: str, old_string: str, new_string: str) -> bytes
     img_h = HEADER_H + LINE_H * (len(display) + extra) + 4
     img = Image.new('RGB', (max_w, img_h), (15, 23, 42))
     draw = ImageDraw.Draw(img)
 
     _draw_header(draw, max_w, f"✏️ {_short_path(file_path)}", font_small)
 
     y = HEADER_H + 2
     for typ, text, other in display:
+        text = text[:WRAP_COLS]
+        if other is not None:
+            other = other[:WRAP_COLS]
         if typ in ('del', 'add'):
             draw.rectangle([0, y, max_w, y + LINE_H], fill=_BG[typ])
             draw.rectangle([0, y, GUTTER_W, y + LINE_H], fill=_BG_G[typ])
-            draw.text((8, y + 3), _SIGN[typ], fill=_CLR_G[typ], font=font)
+            draw.text((10, y + 4), _SIGN[typ], fill=_CLR_G[typ], font=font)
             parts = _inline_diff(text, other)
             x = GUTTER_W + PAD_X
             for part_text, is_hl in parts:
                 if is_hl:
                     tw = font.getlength(part_text)
                     draw.rectangle([x - 1, y + 2, x + tw + 1, y + LINE_H - 2], fill=_HL[typ])
-                draw.text((x, y + 3), part_text, fill=_CLR[typ], font=font)
+                draw.text((x, y + 4), part_text, fill=_CLR[typ], font=font)
                 x += font.getlength(part_text)
         else:
             draw.rectangle([0, y, GUTTER_W, y + LINE_H], fill=(15, 23, 42))
-            draw.text((8, y + 3), ' ', fill=_CLR_G['ctx'], font=font)
-            draw.text((GUTTER_W + PAD_X, y + 3), text, fill=_CLR['ctx'], font=font)
+            draw.text((10, y + 4), ' ', fill=_CLR_G['ctx'], font=font)
+            draw.text((GUTTER_W + PAD_X, y + 4), text, fill=_CLR['ctx'], font=font)
         y += LINE_H
 
     if truncated:
         _draw_truncated(draw, y, len(lines) - MAX_LINES_EDIT, font_small)
 
     buf = io.BytesIO()
     img.save(buf, format='PNG', optimize=True)
     return buf.getvalue()
@@ -184,20 +196,21 @@ def render_write_diff(file_path: str, content: str) -> bytes:
     img_h = HEADER_H + LINE_H * (len(display) + extra) + 4
     img = Image.new('RGB', (max_w, img_h), (15, 23, 42))
     draw = ImageDraw.Draw(img)
 
     _draw_header(draw, max_w, f"📄 {_short_path(file_path)} (new)", font_small)
 
     y = HEADER_H + 2
     for text in display:
+        text = text[:WRAP_COLS]
         draw.rectangle([0, y, max_w, y + LINE_H], fill=(15, 40, 25))
         draw.rectangle([0, y, GUTTER_W, y + LINE_H], fill=(20, 55, 30))
-        draw.text((8, y + 3), '+', fill=(74, 222, 128), font=font)
-        draw.text((GUTTER_W + PAD_X, y + 3), text, fill=(187, 247, 208), font=font)
+        draw.text((10, y + 4), '+', fill=(74, 222, 128), font=font)
+        draw.text((GUTTER_W + PAD_X, y + 4), text, fill=(187, 247, 208), font=font)
         y += LINE_H
 
     if truncated:
         _draw_truncated(draw, y, len(lines_text) - MAX_LINES_WRITE, font_small)
 
     buf = io.BytesIO()
     img.save(buf, format='PNG', optimize=True)
     return buf.getvalue()
@@ -205,126 +218,139 @@ def render_write_diff(file_path: str, content: str) -> bytes:
 
 MAX_LINES_READ = 25
 MAX_LINES_GREP = 20
 _GUTTER_W_READ = 40  # wider for line numbers
 
 
 def render_read(file_path: str, content: str, offset: int = 0) -> bytes:
     """Render Read tool result as PNG with line numbers."""
-    lines_text = content.split('\n')[:MAX_LINES_READ]
+    raw_lines = content.split('\n')
     font, font_small = _load_fonts()
 
-    max_w = 700
-    for text in lines_text:
-        tw = font.getlength(text) + _GUTTER_W_READ + PAD_X * 2 + 20
-        max_w = max(max_w, int(tw))
-    max_w = min(max_w, 1200)
+    display = []  # (line_no_str, text)
+    for i, ln in enumerate(raw_lines):
+        parts = _wrap_line(ln)
+        for j, p in enumerate(parts):
+            display.append((str(offset + i + 1) if j == 0 else "", p))
+        if len(display) >= MAX_LINES_READ:
+            break
+    display = display[:MAX_LINES_READ]
+    truncated = len(raw_lines) > MAX_LINES_READ
+    extra = 1 if truncated else 0
 
-    img_h = HEADER_H + LINE_H * len(lines_text) + 4
+    max_w = 800
+    img_h = HEADER_H + LINE_H * (len(display) + extra) + 4
     img = Image.new('RGB', (max_w, img_h), (15, 23, 42))
     draw = ImageDraw.Draw(img)
 
     draw.line([0, HEADER_H, max_w, HEADER_H], fill=(30, 41, 59))
-    draw.text((PAD_X, 5), f"📖 {_short_path(file_path)} :{offset + 1}", fill=(100, 116, 139), font=font_small)
+    draw.text((PAD_X, 7), f"📖 {_short_path(file_path)} :{offset + 1}", fill=(100, 116, 139), font=font_small)
 
     y = HEADER_H + 2
-    for i, text in enumerate(lines_text):
-        line_no = str(offset + i + 1)
+    for line_no, text in display:
         draw.rectangle([0, y, _GUTTER_W_READ, y + LINE_H], fill=(15, 23, 42))
-        nw = font_small.getlength(line_no)
-        draw.text((_GUTTER_W_READ - nw - 4, y + 4), line_no, fill=(71, 85, 105), font=font_small)
-        draw.text((_GUTTER_W_READ + PAD_X, y + 3), text, fill=(226, 232, 240), font=font)
+        if line_no:
+            nw = font_small.getlength(line_no)
+            draw.text((_GUTTER_W_READ - nw - 4, y + 5), line_no, fill=(71, 85, 105), font=font_small)
+        draw.text((_GUTTER_W_READ + PAD_X, y + 4), text, fill=(226, 232, 240), font=font)
         y += LINE_H
 
+    if truncated:
+        _draw_truncated(draw, y, len(raw_lines) - MAX_LINES_READ, font_small)
+
     buf = io.BytesIO()
     img.save(buf, format='PNG', optimize=True)
     return buf.getvalue()
 
 
 def render_grep(pattern: str, results: list) -> bytes:
     """Render Grep results as PNG with match highlighting.
 
     results: list of (file, line_no, text, match_start, match_end)
     """
     font, font_small = _load_fonts()
     display = results[:MAX_LINES_GREP]
 
-    max_w = 700
-    for f, ln, text, ms, me in display:
-        tw = font.getlength(f"{f}:{ln}: {text}") + PAD_X * 2 + 20
-        max_w = max(max_w, int(tw))
-    max_w = min(max_w, 1200)
-
+    max_w = 800
     img_h = HEADER_H + LINE_H * len(display) + 4
     img = Image.new('RGB', (max_w, img_h), (15, 23, 42))
     draw = ImageDraw.Draw(img)
 
     draw.line([0, HEADER_H, max_w, HEADER_H], fill=(30, 41, 59))
-    draw.text((PAD_X, 5), f"🔍 grep: {pattern} ({len(results)} matches)", fill=(100, 116, 139), font=font_small)
+    draw.text((PAD_X, 7), f"🔍 grep: {pattern[:40]} ({len(results)} matches)", fill=(100, 116, 139), font=font_small)
 
     y = HEADER_H + 2
     for f, ln, text, ms, me in display:
-        prefix = f"{f}:{ln}: "
-        draw.text((PAD_X, y + 3), prefix, fill=(100, 116, 139), font=font)
+        prefix = f"{_short_path(f)}:{ln}: "
+        full_line = prefix + text
+        if len(full_line) > WRAP_COLS:
+            text = text[:WRAP_COLS - len(prefix)]
+            if me > len(text):
+                me = len(text)
+        draw.text((PAD_X, y + 4), prefix, fill=(100, 116, 139), font=font)
         x = PAD_X + font.getlength(prefix)
         before = text[:ms]
         match = text[ms:me]
         after = text[me:]
-        draw.text((x, y + 3), before, fill=(226, 232, 240), font=font)
+        draw.text((x, y + 4), before, fill=(226, 232, 240), font=font)
         x += font.getlength(before)
         tw = font.getlength(match)
         draw.rectangle([x - 1, y + 2, x + tw + 1, y + LINE_H - 2], fill=(120, 80, 0))
-        draw.text((x, y + 3), match, fill=(253, 224, 71), font=font)
+        draw.text((x, y + 4), match, fill=(253, 224, 71), font=font)
         x += tw
-        draw.text((x, y + 3), after, fill=(226, 232, 240), font=font)
+        draw.text((x, y + 4), after, fill=(226, 232, 240), font=font)
         y += LINE_H
 
     buf = io.BytesIO()
     img.save(buf, format='PNG', optimize=True)
     return buf.getvalue()
 
 
 MAX_LINES_BASH = 30
 
 
 def render_bash(command: str, output: str) -> bytes:
     """Render Bash tool — macOS-style terminal with command and output."""
-    LINE_H, PAD_X, HEADER_H = 22, 12, 28
+    _LH, _PX, _HH = 26, 12, 32
     font, font_small = _load_fonts()
 
-    out_lines_all = output.split('\n')
-    lines = out_lines_all[:MAX_LINES_BASH]
-    truncated = len(out_lines_all) > MAX_LINES_BASH
-
-    max_w = 650
-    for text in [command] + lines:
-        tw = font.getlength(text) + PAD_X * 2 + 30
-        max_w = max(max_w, int(tw))
-    max_w = min(max_w, 1200)
-
+    raw_lines = output.split('\n')
+    wrapped = []
+    for ln in raw_lines:
+        wrapped.extend(_wrap_line(ln))
+        if len(wrapped) >= MAX_LINES_BASH:
+            break
+    display = wrapped[:MAX_LINES_BASH]
+    truncated = len(raw_lines) > MAX_LINES_BASH or len(wrapped) > MAX_LINES_BASH
+    cmd_wrapped = _wrap_line(command)
+
+    max_w = 800
     extra = 1 if truncated else 0
-    img_h = HEADER_H + LINE_H * (len(lines) + 1 + extra) + 6
+    total_lines = len(cmd_wrapped) + len(display) + extra
+    img_h = _HH + _LH * total_lines + 8
     img = Image.new('RGB', (max_w, img_h), (13, 17, 23))
     draw = ImageDraw.Draw(img)
 
-    # macOS-style header with traffic lights
-    draw.rectangle([0, 0, max_w, HEADER_H], fill=(30, 30, 30))
-    draw.ellipse([10, 8, 22, 20], fill=(255, 95, 86))
-    draw.ellipse([28, 8, 40, 20], fill=(255, 189, 46))
-    draw.ellipse([46, 8, 58, 20], fill=(39, 201, 63))
-    draw.text((70, 7), "bash", fill=(150, 150, 150), font=font_small)
+    draw.rectangle([0, 0, max_w, _HH], fill=(30, 30, 30))
+    draw.ellipse([12, 10, 24, 22], fill=(255, 95, 86))
+    draw.ellipse([30, 10, 42, 22], fill=(255, 189, 46))
+    draw.ellipse([48, 10, 60, 22], fill=(39, 201, 63))
+    draw.text((72, 8), "bash", fill=(150, 150, 150), font=font_small)
 
-    y = HEADER_H + 4
-    draw.text((PAD_X, y + 3), "$ ", fill=(74, 222, 128), font=font)
-    draw.text((PAD_X + font.getlength("$ "), y + 3), command, fill=(226, 232, 240), font=font)
-    y += LINE_H
+    y = _HH + 4
+    for i, part in enumerate(cmd_wrapped):
+        prefix = "$ " if i == 0 else "  "
+        draw.text((_PX, y + 3), prefix, fill=(74, 222, 128), font=font)
+        draw.text((_PX + font.getlength(prefix), y + 3), part, fill=(226, 232, 240), font=font)
+        y += _LH
 
-    for text in lines:
-        draw.text((PAD_X, y + 3), text, fill=(180, 190, 200), font=font)
-        y += LINE_H
+    for text in display:
+        draw.text((_PX, y + 3), text, fill=(180, 190, 200), font=font)
+        y += _LH
 
     if truncated:
-        draw.text((PAD_X, y + 3), f"... +{len(out_lines_all) - MAX_LINES_BASH} more lines", fill=(100, 116, 139), font=font_small)
+        remaining = len(raw_lines) - MAX_LINES_BASH
+        draw.text((_PX, y + 3), f"... +{max(remaining, 0)} more lines", fill=(100, 116, 139), font=font_small)
 
     buf = io.BytesIO()
     img.save(buf, format='PNG', optimize=True)
     return buf.getvalue()


## LATER FIX 3d43458cf4 (10.9 days later): fix: codex_review uses proxy wrapper instead of direct binary — fixes DNS/403 errors from Russia
lines of origin it changed/deleted: 2
(code only, capped 400 lines)

fix: codex_review uses proxy wrapper instead of direct binary — fixes DNS/403 errors from Russia


diff --git a/app/mcp_stdio.py b/app/mcp_stdio.py
index 8db0631c1..5cc9c487c 100644
--- a/app/mcp_stdio.py
+++ b/app/mcp_stdio.py
@@ -653,18 +653,18 @@ async def bg_list() -> str:
 async def bg_cancel(job_id: str) -> str:
     """Cancel an active background job."""
     result = await _api("DELETE", f"/api/bg/jobs/{job_id}")
     if isinstance(result, dict) and result.get("error"):
         return f"Cancel failed: {result['error']}"
     return f"Job {job_id} cancelled."
 
 
-# Hardcoded path: Codex CLI installed globally via npm, not in the uv venv
-_CODEX_BIN = "/home/maxim/.npm-global/bin/codex"
+# Wrapper at ~/.local/bin/codex sets HTTPS_PROXY for Ёжик tunnel
+_CODEX_BIN = "/home/maxim/.local/bin/codex"
 _REVIEW_CONTEXT = (
     "PROJECT CONTEXT (calibrate review severity):\n"
     "- Scale: small team, MVP stage\n"
     "- Philosophy: simple, flat, minimal abstractions\n"
     "- blocking = crash/corrupt/security. suggestion = real improvement. nit = skip\n"
 )
 
 
@@ -691,36 +691,35 @@ async def codex_review(
         prompt_parts.append(f"Additional context: {context}\n")
     prompt_parts.append(f"Write your review to {output}.")
     prompt_parts.append("Format: ## Summary, ## Findings (blocking/suggestion/question), ## Verdict")
     review_prompt = "\n".join(prompt_parts)
 
     prompt_file = f"/tmp/codex_review_{WORKER_NAME}.txt"
 
     if mode == "review":
-        # Clear proxy vars: Codex talks to OpenAI, not Anthropic — same as _build_env
         cmd = (
-            f"cd {cwd} && HTTPS_PROXY= HTTP_PROXY= UV_CACHE_DIR=/tmp/uv-cache {_CODEX_BIN} exec review"
+            f"cd {cwd} && UV_CACHE_DIR=/tmp/uv-cache {_CODEX_BIN} exec review"
             f" --uncommitted --skip-git-repo-check --full-auto --ephemeral"
             f" -o {output_abs}"
         )
     elif mode == "exec":
         if not target:
             return "Error: target file required for mode='exec'"
         prompt_parts_exec = [_REVIEW_CONTEXT]
         if context:
             prompt_parts_exec.append(f"Additional context: {context}\n")
         prompt_parts_exec.append(f"Review the file: {target}")
         prompt_parts_exec.append(f"Write your findings to {output}.")
         prompt_parts_exec.append("Format: ## Summary, ## Findings (blocking/suggestion/question), ## Verdict")
         exec_prompt = "\n".join(prompt_parts_exec)
 
         cmd = (
             f"cat > {prompt_file} << 'CODEX_PROMPT_EOF'\n{exec_prompt}\nCODEX_PROMPT_EOF\n"
-            f"cd {cwd} && HTTPS_PROXY= HTTP_PROXY= UV_CACHE_DIR=/tmp/uv-cache {_CODEX_BIN} exec"
+            f"cd {cwd} && UV_CACHE_DIR=/tmp/uv-cache {_CODEX_BIN} exec"
             f" -s workspace-write --skip-git-repo-check --full-auto --ephemeral"
             f" -o {output_abs}"
             f" - < {prompt_file}"
         )
     else:
         return f"Error: unknown mode '{mode}'. Use 'review' or 'exec'."
 
     logger.info(f"codex_review: mode={mode} cwd={cwd} output={output_abs} cmd={cmd[:300]}")