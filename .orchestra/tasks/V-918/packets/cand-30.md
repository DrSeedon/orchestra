# Candidate cand-30

## ORIGIN commit 420dfaba99 (2026-07-16): WIP: auto-saved uncommitted changes before worker spawn (2026-07-16 16:36)
(diff of code only, excluding .orchestra/ and *.md; capped 1200 lines)

diff --git a/app/codex_review_artifact.py b/app/codex_review_artifact.py
new file mode 100644
index 000000000..eee8566a8
--- /dev/null
+++ b/app/codex_review_artifact.py
@@ -0,0 +1,110 @@
+"""Atomic persistence and validation for codex_review output artifacts."""
+
+from __future__ import annotations
+
+import argparse
+import json
+import os
+import re
+from datetime import datetime, timezone
+from pathlib import Path
+
+
+def _last_thread_id(jsonl_path: Path) -> str:
+    thread_id = ""
+    try:
+        with jsonl_path.open(encoding="utf-8", errors="replace") as fh:
+            for line in fh:
+                try:
+                    row = json.loads(line)
+                except (json.JSONDecodeError, TypeError):
+                    continue
+                if row.get("type") == "thread.started" and row.get("thread_id"):
+                    thread_id = str(row["thread_id"])
+    except OSError:
+        return ""
+    return thread_id
+
+
+def finalize_review_artifact(*, output: Path, round_file: Path, sessions_file: Path,
+                             slug: str, jsonl_file: Path, resume: bool,
+                             require_verdict: bool) -> None:
+    """Validate the final agent message, persist it atomically, and store its thread UUID."""
+    try:
+        review = round_file.read_text(encoding="utf-8").strip()
+    except OSError as e:
+        raise ValueError(f"review output is missing: {round_file}: {e}") from e
+    if not review:
+        raise ValueError(f"review output is empty: {round_file}")
+    if require_verdict and re.search(r"(?im)^##\s+Verdict\b", review) is None:
+        raise ValueError("review output has no '## Verdict' section")
+
+    sessions = {"sessions": {}}
+    try:
+        loaded = json.loads(sessions_file.read_text(encoding="utf-8"))
+        if isinstance(loaded, dict) and isinstance(loaded.get("sessions"), dict):
+            sessions = loaded
+    except (OSError, json.JSONDecodeError, TypeError):
+        pass
+
+    previous = sessions["sessions"].get(slug) or {}
+    thread_id = _last_thread_id(jsonl_file) or previous.get("uuid", "")
+    if not thread_id:
+        raise ValueError(f"Codex thread UUID is missing from {jsonl_file}")
+
+    output.parent.mkdir(parents=True, exist_ok=True)
+    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
+    if resume and output.exists():
+        prior = output.read_text(encoding="utf-8").rstrip()
+        content = f"{prior}\n\n## Round ({now})\n\n{review}\n"
+    else:
+        content = review + "\n"
+    output_tmp = output.with_name(output.name + ".tmp")
+    output_tmp.write_text(content, encoding="utf-8")
+    os.replace(output_tmp, output)
+
+    sessions["sessions"][slug] = {
+        "uuid": thread_id,
+        "started": previous.get("started") or now,
+        "last_used": now,
+        "turns": int(previous.get("turns") or 0) + 1,
+    }
+    sessions_file.parent.mkdir(parents=True, exist_ok=True)
+    sessions_tmp = sessions_file.with_name(sessions_file.name + ".tmp")
+    sessions_tmp.write_text(json.dumps(sessions, ensure_ascii=False, indent=2) + "\n",
+                            encoding="utf-8")
+    os.replace(sessions_tmp, sessions_file)
+    try:
+        round_file.unlink()
+    except FileNotFoundError:
+        pass
+
+
+def main() -> int:
+    parser = argparse.ArgumentParser()
+    parser.add_argument("--output", type=Path, required=True)
+    parser.add_argument("--round-file", type=Path, required=True)
+    parser.add_argument("--sessions-file", type=Path, required=True)
+    parser.add_argument("--slug", required=True)
+    parser.add_argument("--jsonl-file", type=Path, required=True)
+    parser.add_argument("--resume", action="store_true")
+    parser.add_argument("--require-verdict", action="store_true")
+    args = parser.parse_args()
+    try:
+        finalize_review_artifact(
+            output=args.output,
+            round_file=args.round_file,
+            sessions_file=args.sessions_file,
+            slug=args.slug,
+            jsonl_file=args.jsonl_file,
+            resume=args.resume,
+            require_verdict=args.require_verdict,
+        )
+    except ValueError as e:
+        print(f"codex_review artifact validation failed: {e}")
+        return 70
+    return 0
+
+
+if __name__ == "__main__":
+    raise SystemExit(main())
diff --git a/tests/test_codex_review_artifact.py b/tests/test_codex_review_artifact.py
new file mode 100644
index 000000000..4c20f63ad
--- /dev/null
+++ b/tests/test_codex_review_artifact.py
@@ -0,0 +1,84 @@
+import json
+
+import pytest
+
+from app.codex_review_artifact import finalize_review_artifact
+
+
+def _jsonl(path, thread_id="thread-1"):
+    path.write_text(json.dumps({"type": "thread.started", "thread_id": thread_id}) + "\n")
+
+
+def test_fresh_review_is_atomic_and_persists_session(tmp_path):
+    output = tmp_path / "review.md"
+    round_file = tmp_path / "review.md.round"
+    sessions = tmp_path / "codex_sessions.json"
+    jsonl = tmp_path / "review.jsonl"
+    round_file.write_text("## Summary\nOK\n\n## Verdict\nPASS\n")
+    _jsonl(jsonl)
+
+    finalize_review_artifact(
+        output=output, round_file=round_file, sessions_file=sessions,
+        slug="review", jsonl_file=jsonl, resume=False, require_verdict=True,
+    )
+
+    assert "## Verdict" in output.read_text()
+    assert not round_file.exists()
+    saved = json.loads(sessions.read_text())
+    assert saved["sessions"]["review"]["uuid"] == "thread-1"
+    assert saved["sessions"]["review"]["turns"] == 1
+
+
+def test_resume_appends_without_overwriting_prior_review(tmp_path):
+    output = tmp_path / "review.md"
+    output.write_text("original findings\n")
+    round_file = tmp_path / "review.md.round"
+    round_file.write_text("## Verdict\nPASS after fixes\n")
+    sessions = tmp_path / "codex_sessions.json"
+    sessions.write_text(json.dumps({"sessions": {"review": {
+        "uuid": "thread-1", "started": "old", "last_used": "old", "turns": 1,
+    }}}))
+    jsonl = tmp_path / "review.jsonl"
+    _jsonl(jsonl)
+
+    finalize_review_artifact(
+        output=output, round_file=round_file, sessions_file=sessions,
+        slug="review", jsonl_file=jsonl, resume=True, require_verdict=True,
+    )
+
+    content = output.read_text()
+    assert content.startswith("original findings")
+    assert "## Round" in content
+    assert "PASS after fixes" in content
+    assert json.loads(sessions.read_text())["sessions"]["review"]["turns"] == 2
+
+
+def test_missing_verdict_fails_without_touching_existing_output(tmp_path):
+    output = tmp_path / "review.md"
+    output.write_text("keep me\n")
+    round_file = tmp_path / "review.md.round"
+    round_file.write_text("Looks fine, probably.\n")
+    jsonl = tmp_path / "review.jsonl"
+    _jsonl(jsonl)
+
+    with pytest.raises(ValueError, match="Verdict"):
+        finalize_review_artifact(
+            output=output, round_file=round_file,
+            sessions_file=tmp_path / "sessions.json", slug="review",
+            jsonl_file=jsonl, resume=False, require_verdict=True,
+        )
+
+    assert output.read_text() == "keep me\n"
+
+
+def test_missing_thread_id_fails_loud(tmp_path):
+    round_file = tmp_path / "review.md.round"
+    round_file.write_text("## Verdict\nPASS\n")
+    jsonl = tmp_path / "review.jsonl"
+    jsonl.write_text("{}\n")
+    with pytest.raises(ValueError, match="UUID"):
+        finalize_review_artifact(
+            output=tmp_path / "review.md", round_file=round_file,
+            sessions_file=tmp_path / "sessions.json", slug="review",
+            jsonl_file=jsonl, resume=False, require_verdict=True,
+        )
diff --git a/tests/test_mcp_codex_review.py b/tests/test_mcp_codex_review.py
new file mode 100644
index 000000000..7d341981e
--- /dev/null
+++ b/tests/test_mcp_codex_review.py
@@ -0,0 +1,40 @@
+from pathlib import Path
+
+import pytest
+
+
+@pytest.mark.asyncio
+async def test_codex_review_uses_temp_artifact_and_declares_success_contract(tmp_path, monkeypatch):
+    import app.mcp_stdio as mcp
+
+    captured = {}
+
+    async def fake_api(method, path, **kwargs):
+        if method == "GET":
+            return {"cwd": str(tmp_path), "worktree_path": str(tmp_path), "scope": str(tmp_path)}
+        captured.update(kwargs["json"])
+        return {"id": "bg-test"}
+
+    monkeypatch.setattr(mcp, "_api", fake_api)
+    monkeypatch.setattr(mcp, "WORKER_NAME", "sol-pilot")
+    monkeypatch.setattr(mcp, "SCOPE", str(tmp_path))
+
+    result = await mcp.codex_review(
+        target="research.md", output="docs/review.md", mode="exec",
+    )
+
+    assert "bg-test" in result
+    config = captured["config"]
+    output = str(tmp_path / "docs/review.md")
+    assert config["success_file"] == output
+    assert "Verdict" in config["success_pattern"]
+    command = config["command"]
+    assert f"-o {output}.round" in command
+    assert "codex_review_artifact.py" in command
+    assert "--require-verdict" in command
+    assert command.index("rm -f") < command.index(" | tee ")
+
+    # Parse only; do not execute Codex.
+    import subprocess
+    parsed = subprocess.run(["dash", "-n", "-c", command], capture_output=True, text=True)
+    assert parsed.returncode == 0, parsed.stderr
diff --git a/tests/test_session.py b/tests/test_session.py
index 63311711b..11f5fc569 100644
--- a/tests/test_session.py
+++ b/tests/test_session.py
@@ -689,16 +689,70 @@ class TestCompactGuards:
         assert not session._compact_ack_event.is_set()
 
         # turn_end for the matching gen SETS it
         session._turn_gen = 5
         session._turns.handle_turn_end(AgentEvent(type="turn_end", content="", metadata={}))
         assert session._compact_ack_event.is_set()
 
 
+class TestRateLimitClassification:
+    @staticmethod
+    def _capture_coroutines(session):
+        spawned = []
+        session._log = lambda *_args, **_kwargs: None
+
+        def capture(coro):
+            spawned.append(coro)
+            coro.close()
+
+        session._spawn_bg = capture
+        return spawned
+
+    def test_monthly_spend_limit_is_terminal_and_never_retried(self, session):
+        from app.events import AgentEvent
+        spawned = self._capture_coroutines(session)
+
+        session._handle_event(AgentEvent(
+            type="text",
+            content="You've hit your monthly spend limit · raise it at claude.ai/settings/usage",
+        ))
+        session._handle_event(AgentEvent(type="error", content="rate_limit"))
+
+        assert session._rate_limit_retries == 0
+        assert spawned == []
+
+    @pytest.mark.asyncio
+    async def test_failed_turn_does_not_reset_transient_retry_budget(self, session, monkeypatch):
+        from app.events import AgentEvent
+        monkeypatch.setattr("app.bg_jobs.bg_manager", None)
+        self._capture_coroutines(session)
+        session._rate_limit_retries = 2
+
+        session._turns.handle_turn_end(AgentEvent(type="turn_end", metadata={
+            "ok": False, "stop_reason": "error", "num_turns": 0,
+        }))
+        await session._drain_persist()
+
+        assert session._rate_limit_retries == 2
+
+    @pytest.mark.asyncio
+    async def test_new_user_message_resets_retry_budget(self, session):
+        from app.session import AgentStatus
+        session.model = "gpt-5.6-sol"
+        session.backend_type = "codex"
+        session.status = AgentStatus.RUNNING
+        session._rate_limit_retries = 2
+        session._log = lambda *_args, **_kwargs: None
+
+        await session.send("new user request")
+
+        assert session._rate_limit_retries == 0
+
+
 class TestFlushPendingDefersDuringCompact:
     @pytest.mark.asyncio
     async def test_flush_defers_when_compacting(self, session):
         sent = []
         backend = AsyncMock()
         backend.send = AsyncMock(side_effect=lambda m: sent.append(m))
         session._backend = backend
         session._compacting = True


## LATER FIX afc99e2deb (25.0 days later): #173: #173: fix prompt P0 defects
lines of origin it changed/deleted: 4
(code only, capped 400 lines)

#173: #173: fix prompt P0 defects


diff --git a/app/db.py b/app/db.py
index 9448e8c82..d64d382ca 100644
--- a/app/db.py
+++ b/app/db.py
@@ -49,16 +49,17 @@ def init_db() -> None:
                 -- NOT NULL для новых БД; существующие закрывает триггер в _guard_session_id:
                 -- ужесточить колонку без перестройки таблицы SQLite не даёт (#54)
                 id TEXT PRIMARY KEY NOT NULL,
                 name TEXT NOT NULL,
                 scope TEXT NOT NULL,
                 cwd TEXT NOT NULL,
                 model TEXT NOT NULL,
                 system_prompt TEXT DEFAULT '',
+                prompt_overlay TEXT,
                 status TEXT DEFAULT 'starting',
                 session_id TEXT,
                 cost_usd REAL DEFAULT 0.0,
                 worktree_path TEXT,
                 branch TEXT,
                 base_branch TEXT DEFAULT '',
                 needs_switch INTEGER DEFAULT 0,
                 is_orchestrator INTEGER DEFAULT 0,
@@ -591,16 +592,20 @@ def _migrate(c) -> None:
     if "runtime_handoff" not in cols:
         c.execute("ALTER TABLE sessions ADD COLUMN runtime_handoff TEXT DEFAULT ''")
     if "last_summary" not in cols:
         c.execute("ALTER TABLE sessions ADD COLUMN last_summary TEXT DEFAULT ''")
     if "base_branch" not in cols:
         c.execute("ALTER TABLE sessions ADD COLUMN base_branch TEXT DEFAULT ''")
     if "needs_switch" not in cols:
         c.execute("ALTER TABLE sessions ADD COLUMN needs_switch INTEGER DEFAULT 0")
+    if "prompt_overlay" not in cols:
+        # NULL distinguishes a legacy assembled prompt from a new, explicitly separated
+        # overlay. _load_from_db migrates an empty or current-base legacy prompt safely.
+        c.execute("ALTER TABLE sessions ADD COLUMN prompt_overlay TEXT")
     log_cols = {row[1] for row in c.execute("PRAGMA table_info(logs)").fetchall()}
     if log_cols and "event_id" not in log_cols:
         c.execute("ALTER TABLE logs ADD COLUMN event_id TEXT NOT NULL DEFAULT ''")
     c.execute(
         """CREATE INDEX IF NOT EXISTS idx_logs_event_id
            ON logs(event_id)
            WHERE event_id <> ''"""
     )
@@ -695,47 +700,49 @@ def save_session(
     s.setdefault("owned_dirs", "")
     s.setdefault("tg_topic", 0)
     s.setdefault("session_id_history", "[]")
     s.setdefault("effort", "")
     s.setdefault("runtime_handoff", "")
     s.setdefault("last_summary", "")
     s.setdefault("base_branch", "")
     s.setdefault("needs_switch", 0)
+    s.setdefault("prompt_overlay", None)
     connection_scope = (
         nullcontext(_connection) if _connection is not None else _conn()
     )
     with connection_scope as c:
         c.execute("""
-            INSERT INTO sessions (id, name, scope, cwd, model, system_prompt,
+            INSERT INTO sessions (id, name, scope, cwd, model, system_prompt, prompt_overlay,
                 status, session_id, cost_usd, worktree_path, branch, base_branch,
                 needs_switch, is_orchestrator,
                 color, created_at, finished_at, context_pct, context_tokens,
                 progress_pct, progress_status, backend_type, task_id, description,
                 cost_usd_cached, context_cost,
                 total_turns, total_input_tokens, total_output_tokens,
                 total_cache_read_tokens, total_cache_create_tokens, total_tool_calls,
                 template_hash, role, parent_id, parent_name, mcp_servers_custom, pipeline,
                 profile, owned_dirs, tg_topic, session_id_history, effort, runtime_handoff,
                 last_summary)
-            VALUES (:id, :name, :scope, :cwd, :model, :system_prompt,
+            VALUES (:id, :name, :scope, :cwd, :model, :system_prompt, :prompt_overlay,
                 :status, :session_id, :cost_usd, :worktree_path, :branch, :base_branch,
                 :needs_switch, :is_orchestrator,
                 :color, :created_at, :finished_at, :context_pct, :context_tokens,
                 :progress_pct, :progress_status, :backend_type, :task_id, :description,
                 :cost_usd_cached, :context_cost,
                 :total_turns, :total_input_tokens, :total_output_tokens,
                 :total_cache_read_tokens, :total_cache_create_tokens, :total_tool_calls,
                 :template_hash, :role, :parent_id, :parent_name, :mcp_servers_custom, :pipeline,
                 :profile, :owned_dirs, :tg_topic, :session_id_history, :effort,
                 :runtime_handoff, :last_summary)
             ON CONFLICT(id) DO UPDATE SET
                 name=excluded.name,
                 model=excluded.model,
                 system_prompt=excluded.system_prompt,
+                prompt_overlay=excluded.prompt_overlay,
                 status=excluded.status,
                 session_id=excluded.session_id,
                 cost_usd=excluded.cost_usd,
                 cost_usd_cached=excluded.cost_usd_cached,
                 context_cost=excluded.context_cost,
                 worktree_path=excluded.worktree_path,
                 branch=excluded.branch,
                 base_branch=excluded.base_branch,
diff --git a/app/manager.py b/app/manager.py
index cefe7ad54..1d6cf1a9f 100644
--- a/app/manager.py
+++ b/app/manager.py
@@ -15,16 +15,17 @@ from contextlib import asynccontextmanager
 from datetime import datetime, timezone
 from pathlib import Path
 from typing import Awaitable, Callable, Optional
 
 from app.session import AgentSession, AgentStatus
 from app.prompting import (
     is_orchestrator_role, safe_format_prompt,
     prompt_template_hash, inject_skills_to_worktree, load_worker_memory,
+    refresh_worker_memory, strip_worker_memory,
 )
 
 # Matches "task-42/worker-name" or "PAR-42/worker-name" — extracts task number from branch
 _TASK_BRANCH_RE = re.compile(r"^(?:task-|[A-Z]{2,5}-)(\d+)/")
 from app.workspace import (
     create_worktree, discard_prepared_worktree, remove_worktree,
     parse_owned_dirs, dirs_overlap,
     validate_repo_root, resolve_base_branch as resolve_git_base_branch,
@@ -598,20 +599,23 @@ class SessionManager:
                 pipeline = get_active_pipeline(scope, parent_pipeline=parent_pipeline)
                 is_orch = self._role_is_orchestrator(pipeline, role)
             if parent_name and not explicit_profile:
                 # Тот же авто-найденный родитель — воркер наследует и его профиль.
                 parent_profile = self._resolve_profile(parent_name, scope)
                 profile = get_active_profile(scope, parent_profile=parent_profile)
 
         if is_orch:
-            prompt = ROLE_SYSTEM_PROMPT(pipeline, role, scope) + ("\n\n" + system_prompt if system_prompt else "")
+            base_prompt = ROLE_SYSTEM_PROMPT(pipeline, role, scope)
+            prompt_overlay = "\n\n" + system_prompt if system_prompt else ""
         else:
-            prompt = ROLE_SYSTEM_PROMPT(pipeline, role) + ("\n\n" + system_prompt if system_prompt else "")
-            prompt += self._ownership_prompt(owned_dirs)
+            base_prompt = ROLE_SYSTEM_PROMPT(pipeline, role)
+            prompt_overlay = ("\n\n" + system_prompt if system_prompt else "")
+            prompt_overlay += self._ownership_prompt(owned_dirs)
+        prompt = base_prompt + prompt_overlay
 
         # Worker persistent memory: docs/workers/{name}.md or docs/workers/{role}.md
         # Survives kill/respawn/compact — worker writes rules here, they auto-inject next time
         worker_memory = load_worker_memory(name, role, scope)
         if worker_memory:
             prompt += f"\n\n<worker-memory>\n{worker_memory}\n</worker-memory>"
 
         if not parent_id and parent_name:
@@ -654,17 +658,17 @@ class SessionManager:
         custom_mcp = _parse_custom_mcp(mcp_servers)
         bt = backend_for_model(model)
         _rr_effort = get_role(pipeline, role)
         raw_effort = getattr(_rr_effort, "effort", None) if _rr_effort else None
         effort = raw_effort if isinstance(raw_effort, str) and raw_effort else None
         session_id = str(uuid.uuid4())
         session = AgentSession(
             id=session_id, name=name, scope=scope, cwd=cwd, model=model,
-            system_prompt=prompt, role=role,
+            system_prompt=prompt, prompt_overlay=prompt_overlay, role=role,
             parent_id=parent_id, parent_name=parent_name,
             pipeline=pipeline, profile=profile,
             color="" if is_orch else self._pick_color(),
             mcp_servers=_make_mcp_config(name, scope, role, parent_name=parent_name,
                                          extra=custom_mcp, session_id=session_id),
             mcp_servers_custom=custom_mcp,
             backend_type=bt, effort=effort, task_id=task_id, description=description,
             base_branch=base_branch,
@@ -710,16 +714,21 @@ class SessionManager:
 
             if not is_orch:
                 orch_name = parent_name or self._find_orchestrator_name(scope)
                 session.system_prompt = safe_format_prompt(
                     session.system_prompt,
                     worker_name=name, orchestrator_name=orch_name or "orchestrator",
                     scope=scope, branch=session.branch or session.base_branch,
                 )
+                session.prompt_overlay = safe_format_prompt(
+                    session.prompt_overlay or "",
+                    worker_name=name, orchestrator_name=orch_name or "orchestrator",
+                    scope=scope, branch=session.branch or session.base_branch,
+                )
                 session.on_idle = self._make_idle_callback(scope)
                 session.on_turn_blocked = self._make_quota_blocked_callback(scope)
 
             await session.start(persist=False)
 
         async def compensate() -> None:
             errors: list[str] = []
             try:
@@ -1162,16 +1171,17 @@ class SessionManager:
             status = AgentStatus(row.get("status") or "idle")
         except ValueError:
             status = AgentStatus.IDLE
         s = AgentSession(
             id=row["id"], name=row["name"], scope=row["scope"],
             cwd=row.get("cwd") or row["scope"],
             model=row.get("model") or "",
             system_prompt=row.get("system_prompt") or "",
+            prompt_overlay=row.get("prompt_overlay"),
             status=status,
             session_id=row.get("session_id"),
             cost_usd=row.get("cost_usd") or 0.0,
             cost_usd_cached=row.get("cost_usd_cached") or 0.0,
             _context_cost=row.get("context_cost") or 0.0,
             worktree_path=row.get("worktree_path"),
             branch=row.get("branch"),
             base_branch=row.get("base_branch") or "",
@@ -1224,21 +1234,29 @@ class SessionManager:
         if unknown:
             raise ValueError(f"non-updatable fields: {sorted(unknown)}")
         found = self.get_by_name(name, scope)
         if not found:
             return None
         if found.loaded:
             for k, v in fields.items():
                 setattr(found, k, v)
+            if "system_prompt" in fields:
+                # The endpoint replaces the complete assembled prompt, so no older
+                # separated overlay may override it on the next reload.
+                found.prompt_overlay = None
+                found._current_prompt = fields["system_prompt"]
             found._persist()
         else:
             from app.db import _conn
-            sets = ", ".join(f"{k}=?" for k in fields)
-            vals = [int(v) if isinstance(v, bool) else v for v in fields.values()]
+            db_fields = dict(fields)
+            if "system_prompt" in fields:
+                db_fields["prompt_overlay"] = None
+            sets = ", ".join(f"{k}=?" for k in db_fields)
+            vals = [int(v) if isinstance(v, bool) else v for v in db_fields.values()]
             with _conn() as c:
                 cur = c.execute(
                     f"UPDATE sessions SET {sets} WHERE id=?", (*vals, found.id),
                 )
                 if cur.rowcount == 0:
                     # Молчаливый ноль здесь означал бы, что поля «сохранены» только
                     # в памяти вызывающего, а в БД их нет (#54).
                     logger.warning(
@@ -1411,20 +1429,19 @@ class SessionManager:
         # колонка is_orchestrator (денормализована при спавне); иначе frozenset.
         is_orch = self._role_is_orchestrator(pipeline, role)
         try:
             if get_role(pipeline, role) is None:
                 is_orch = bool(db_row.get("is_orchestrator")) or is_orchestrator_role(role)
         except FileNotFoundError:
             is_orch = bool(db_row.get("is_orchestrator")) or is_orchestrator_role(role)
         old_prompt = db_row.get("system_prompt", "")
-        current_prompt = ROLE_SYSTEM_PROMPT(pipeline, role, db_row["scope"]) if is_orch else ROLE_SYSTEM_PROMPT(pipeline, role)
-        worker_memory = load_worker_memory(db_row["name"], role, db_row["scope"])
-        if worker_memory:
-            current_prompt += f"\n\n<worker-memory>\n{worker_memory}\n</worker-memory>"
+        current_base = ROLE_SYSTEM_PROMPT(
+            pipeline, role, db_row["scope"]
+        ) if is_orch else ROLE_SYSTEM_PROMPT(pipeline, role)
         cwd = db_row.get("cwd") or db_row["scope"]
         if not Path(cwd).is_dir():
             cwd = db_row["scope"]
         expected_bt = backend_for_model(db_row["model"])
         stored_bt = db_row.get("backend_type") or expected_bt
         if stored_bt != expected_bt:
             logger.warning(f"backend mismatch for {db_row['name']}: stored={stored_bt}, model implies={expected_bt}. Using {expected_bt}.")
             stored_bt = expected_bt
@@ -1439,20 +1456,53 @@ class SessionManager:
             )
             if actual.returncode == 0:
                 actual_branch = actual.stdout.strip()
                 if actual_branch != db_branch:
                     db_branch = actual_branch
                     m = _TASK_BRANCH_RE.match(actual_branch)
                     db_task_id = m.group(1) if m else ""
 
+        orch_name = self._find_orchestrator_name(db_row["scope"]) if not is_orch else None
+        if not is_orch:
+            current_base = safe_format_prompt(
+                current_base,
+                worker_name=db_row["name"], orchestrator_name=orch_name or "orchestrator",
+                scope=db_row["scope"],
+                branch=db_row.get("branch") or db_row.get("base_branch") or "",
+            )
+        stored_overlay = db_row.get("prompt_overlay")
+        if stored_overlay is None:
+            old_without_memory = strip_worker_memory(old_prompt)
+            if not old_without_memory:
+                prompt_overlay = self._ownership_prompt(
+                    parse_owned_dirs(db_row.get("owned_dirs"))
+                )
+                prompt_without_memory = current_base + prompt_overlay
+            elif old_without_memory.startswith(current_base):
+                prompt_overlay = old_without_memory[len(current_base):]
+                prompt_without_memory = current_base + prompt_overlay
+            else:
+                # A legacy/full-prompt override has no component boundary to recover.
+                # Preserve it byte-for-byte instead of guessing and dropping authority.
+                prompt_overlay = None
+                prompt_without_memory = old_without_memory
+        else:
+            prompt_overlay = strip_worker_memory(stored_overlay)
+            prompt_without_memory = current_base + prompt_overlay
+        current_prompt = refresh_worker_memory(
+            prompt_without_memory,
+            db_row["name"], role, db_row["scope"],
+        )
+
         custom_mcp = _parse_custom_mcp(db_row.get("mcp_servers_custom"))
         session = AgentSession(
             id=db_row["id"], name=db_row["name"], scope=db_row["scope"], cwd=cwd,
-            model=db_row["model"], system_prompt=old_prompt or current_prompt,
+            model=db_row["model"], system_prompt=current_prompt,
+            prompt_overlay=prompt_overlay,
             session_id=db_row.get("session_id"), cost_usd=db_row.get("cost_usd", 0),
             cost_usd_cached=db_row.get("cost_usd_cached", 0),
             _context_cost=db_row.get("context_cost", 0),
             worktree_path=wt_path, branch=db_branch,
             base_branch=db_row.get("base_branch") or "",
             created_at=datetime.fromisoformat(db_row["created_at"]) if db_row.get("created_at") else datetime.now(timezone.utc),
             role=role,
             parent_id=db_row.get("parent_id", ""),
@@ -1485,34 +1535,16 @@ class SessionManager:
             session.session_id_history = json.loads(raw_hist) if isinstance(raw_hist, str) else raw_hist
         except (json.JSONDecodeError, TypeError):
             session.session_id_history = []
         pct = db_row.get("context_pct", 0) or 0
         tokens = db_row.get("context_tokens", 0) or 0
         if pct or tokens:
             max_t = get_model_spec(db_row["model"]).context_length
             session._last_context = {"percentage": pct, "total_tokens": tokens, "max_tokens": max_t}
-        orch_name = self._find_orchestrator_name(db_row["scope"]) if not is_orch else None
-        if not is_orch:
-            current_prompt = safe_format_prompt(
-                current_prompt,
-                worker_name=db_row["name"], orchestrator_name=orch_name or "orchestrator",
-                scope=db_row["scope"],
-                branch=db_row.get("branch") or db_row.get("base_branch") or "",
-            )
-        if old_prompt and old_prompt != current_prompt:
-            formatted_base = safe_format_prompt(
-                ROLE_SYSTEM_PROMPT(pipeline, role, db_row["scope"]) if is_orch else ROLE_SYSTEM_PROMPT(pipeline, role),
-                worker_name=db_row["name"], orchestrator_name=orch_name or "orchestrator",
-                scope=db_row["scope"],
-                branch=db_row.get("branch") or db_row.get("base_branch") or "",
-            )
-            if old_prompt.startswith(formatted_base) and len(old_prompt) > len(formatted_base):
-                custom_part = old_prompt[len(formatted_base):]
-                current_prompt = current_prompt + custom_part
         session._current_prompt = current_prompt
         session._template_hash = db_row.get("template_hash") or prompt_template_hash(role)
         if not is_orch:
             session.on_idle = self._make_idle_callback(db_row["scope"])
             session.on_turn_blocked = self._make_quota_blocked_callback(db_row["scope"])
         await session.start()
         self.sessions[session.id] = session
         return session
@@ -1661,17 +1693,17 @@ class SessionManager:
     # это не скорость, а ВЕРОЯТНОСТЬ ДОСТАВКИ: у юзера между нами и его машиной прозрачный
     # посредник, на котором ответы до ~15 КБ доходят 10 из 10, а крупные — 17 из 33 (#65,
     # замер perf). `system_prompt` — 86.4% веса ответа по проводу (46.9 КБ из 54.3),
     # `last_summary` — ещё 5.9%. Ни одно из двух в списке не читается:
     # промпт берётся отдельным роутом `GET /api/sessions/{name}/prompt` по кнопке 📜,
     # а `last_summary` нужен только серверу (`runtime_handoff`).
     # Понадобилось поле в списке — добавляй осознанно и перемеряй вес: tests/test_manager.py::TestListSessions
     # держит потолок.
-    _LIST_OMIT = ("system_prompt", "last_summary")
+    _LIST_OMIT = ("system_prompt", "prompt_overlay", "last_summary")
 
     def list_sessions(self, scope: str | None = None) -> list[dict]:
         from app.db import get_last_turn_map
         result = []
         seen = set()
         for s in self.sessions.values():
             if scope is None or s.scope == scope:
                 result.append(s.to_dict())
diff --git a/app/mcp_stdio.py b/app/mcp_stdio.py
index 318a04c68..45637896a 100644
--- a/app/mcp_stdio.py
+++ b/app/mcp_stdio.py
@@ -1075,17 +1075,19 @@ async def get_worker_logs(name: str, limit: int = 20) -> str:
             lines.append(f"🔧 {c}")
         elif t == 'error':
             lines.append(f"❌ {c}")
     return "\n".join(lines) if lines else f"No meaningful logs for '{name}'"
 
 
 @mcp.tool()
 async def compact_worker(name: str) -> str:
-    """Compact a worker's context — summarize, reset session, continue fresh. Use when worker context >80%. Returns summary. Takes ~30-60s."""
+    """Manually compact an idle worker's context. Codex compacts natively in the same thread;
+    Claude creates a summary, reconnects fresh, and retains that handoff. This is a manual escape
+    hatch, not the auto-compact policy. Returns the runtime result; may take 30-60s."""
     result = await _api("POST", f"/api/sessions/{name}/compact", json={"scope": SCOPE}, timeout=120)
     if isinstance(result, dict) and result.get("error"):
         return f"Compact failed: {result['error']}"
     if isinstance(result, dict) and result.get("ok"):
         return f"Compact done: {result.get('before_pct', '?')}% → {result.get('after_pct', '?')}%. Summary ({result.get('summary_chars', 0)} chars): {result.get('summary', '')}"
     return f"Compact result: {result}"
 
 
@@ -1968,21 +1970,19 @@ def _codex_bin() -> str:
     return shutil.which("codex") or ""
 
 