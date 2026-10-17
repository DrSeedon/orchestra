# Candidate cand-19

## ORIGIN commit c2f8519792 (2026-07-09): #codex-sessions: persistent Codex sessions in codex_review + full-cycle second-opinion rules
(diff of code only, excluding .orchestra/ and *.md; capped 1200 lines)

diff --git a/app/mcp_stdio.py b/app/mcp_stdio.py
index 14b3a335b..2ebec06b9 100644
--- a/app/mcp_stdio.py
+++ b/app/mcp_stdio.py
@@ -663,85 +663,217 @@ _CODEX_BIN = "/home/maxim/.local/bin/codex"
 _REVIEW_CONTEXT = (
     "PROJECT CONTEXT (calibrate review severity):\n"
     "- Scale: small team, MVP stage\n"
     "- Philosophy: simple, flat, minimal abstractions\n"
     "- blocking = crash/corrupt/security. suggestion = real improvement. nit = skip\n"
 )
 
 
+def _codex_sessions_path(output_abs: str) -> str:
+    """codex_sessions.json lives next to the review output file (per worker/task dir)."""
+    return f"{os.path.dirname(output_abs)}/codex_sessions.json"
+
+
+def _codex_slug(output: str) -> str:
+    """Slug = output filename stem. One slug = one session = one output file (matches skill)."""
+    return os.path.splitext(os.path.basename(output))[0] or "review"
+
+
+def _read_codex_uuid(sessions_path: str, slug: str) -> str:
+    """Read stored thread UUID for a slug. Empty string = no session yet."""
+    try:
+        with open(sessions_path) as f:
+            data = json.load(f)
+        return (data.get("sessions", {}).get(slug, {}) or {}).get("uuid", "") or ""
+    except (FileNotFoundError, json.JSONDecodeError, OSError):
+        return ""
+
+
+def _codex_persist_snippet(sessions_path: str, slug: str, jsonl: str,
+                           is_resume: bool, output_abs: str, round_tmp: str) -> str:
+    """Shell snippet: append the resumed round to the review file (history-preserving) and
+    upsert the thread UUID into codex_sessions.json. Runs AFTER codex — the bg job is a
+    detached subprocess, so Python can't capture the post-run UUID.
+
+    Exit-code safety (dash, no PIPESTATUS): the caller captures codex's real exit code to
+    /tmp before this runs; this snippet never overrides it. jq/persistence failure must not
+    mask a successful review, nor vice-versa."""
+    # resume writes ONLY the last message to round_tmp → append as a new round, never overwrite
+    # prior rounds. (Fresh/fallback runs write directly to output_abs, so round_tmp stays empty.)
+    append = (
+        f"[ -s '{round_tmp}' ] && {{ "
+        f"printf '\\n\\n## Round (%s)\\n\\n' \"$NOW\" >> '{output_abs}'; "
+        f"cat '{round_tmp}' >> '{output_abs}'; rm -f '{round_tmp}'; }};"
+    ) if is_resume else ""
+    # Always upsert the captured thread_id: same UUID on resume, a NEW one if resume fell back
+    # to a fresh session (stale-UUID recovery). One code path handles new/resume/fallback.
+    upsert = (
+        f"jq --arg s '{slug}' --arg u \"$UUID\" --arg now \"$NOW\" "
+        f"'.sessions[$s]={{uuid:$u, started:(.sessions[$s].started // $now), "
+        f"last_used:$now, turns:((.sessions[$s].turns // 0)+1)}}' "
+        f"'{sessions_path}' > '{sessions_path}.tmp' && mv '{sessions_path}.tmp' '{sessions_path}'"
+    )
+    # jq may be absent (minimal VPS) → guard the UUID upsert; the append (plain cat) is unguarded.
+    return (
+        f"; NOW=$(date -u +%Y-%m-%dT%H:%M:%SZ); {append}"
+        f" command -v jq >/dev/null 2>&1 && {{"
+        f" [ -f '{sessions_path}' ] || echo '{{\"sessions\":{{}}}}' > '{sessions_path}';"
+        f" UUID=$(jq -R -r 'fromjson? | select(.type==\"thread.started\") | .thread_id' '{jsonl}' | tail -1);"
+        f" [ -n \"$UUID\" ] && {upsert}; }}"
+    )
+
+
 @mcp.tool()
 async def codex_review(
     target: str = "",
     output: str = "CODEX_REVIEW.md",
     context: str = "",
     mode: str = "review",
+    resume: bool = False,
 ) -> str:
     """Run Codex (GPT-5.5) cross-LLM review in background. Returns immediately, notifies when done.
     target: file path for review, or empty for git diff review.
-    output: where to write results (relative to your cwd).
+    output: where to write results (relative to your cwd). Also the session key — reuse the SAME
+        output filename to continue a debate.
     context: extra instructions for the review prompt.
-    mode: 'review' (git diff, default) or 'exec' (review specific file)."""
+    mode: 'review' (git diff, default) or 'exec' (review specific file).
+    resume: continue the previous Codex session for this output (debate round). Falls back to a
+        fresh session if none stored. On a resumed round put your counter-arguments / changelog
+        in context (e.g. 'I fixed X and Y, re-review')."""
     info = await _api("GET", f"/api/sessions/{WORKER_NAME}", params={"scope": SCOPE})
     if isinstance(info, dict) and info.get("error"):
         return f"Error resolving worker cwd: {info['error']}"
     cwd = info.get("worktree_path") or info.get("cwd") or info.get("scope", SCOPE)
     output_abs = f"{cwd}/{output}" if not output.startswith("/") else output
 
-    prompt_parts = [_REVIEW_CONTEXT]
-    if context:
-        prompt_parts.append(f"Additional context: {context}\n")
-    prompt_parts.append(f"Write your review to {output}.")
-    prompt_parts.append("Format: ## Summary, ## Findings (blocking/suggestion/question), ## Verdict")
-    review_prompt = "\n".join(prompt_parts)
-
+    sessions_path = _codex_sessions_path(output_abs)
+    slug = _codex_slug(output)
+    jsonl_file = f"/tmp/codex_review_{WORKER_NAME}_{slug}.jsonl"
     prompt_file = f"/tmp/codex_review_{WORKER_NAME}.txt"
+    rc_file = f"/tmp/codex_review_{WORKER_NAME}_{slug}.rc"
+    # resume writes its last message here; the persist snippet appends it as a ## Round to
+    # output_abs so prior rounds are never overwritten.
+    round_tmp = f"{output_abs}.round"
+
+    prev_uuid = _read_codex_uuid(sessions_path, slug) if resume else ""
+    is_resume = bool(prev_uuid)
+    if resume and not prev_uuid:
+        logger.info(f"codex_review: resume requested but no stored session for slug={slug} → fresh")
+
+    # resume's -o must NOT point at output_abs (it would truncate history); write to round_tmp.
+    codex_out = round_tmp if is_resume else output_abs
 
     if mode == "review":
-        cmd = (
+        # Fresh review → codex_out: output_abs on a first run, round_tmp on a resume-fallback
+        # (so the stale-session recovery is APPENDED as a round, never overwrites prior rounds).
+        fresh_review = (
             f"cd {cwd} && UV_CACHE_DIR=/tmp/uv-cache {_CODEX_BIN} exec review"
-            f" --uncommitted --skip-git-repo-check --full-auto --ephemeral"
-            f" -o {output_abs}"
+            f" --uncommitted --skip-git-repo-check --full-auto --json"
+            f" -o {codex_out}"
         )
+        if is_resume:
+            # resume inherits sandbox from original session — do NOT pass -s. Re-review the diff.
+            resume_prompt = (
+                "Re-review the current uncommitted diff (run git diff yourself). "
+                "For each prior finding: FIXED / STILL BROKEN / NEW BUG. "
+                "Output a concise re-review (Re-review status, new findings, verdict)."
+            )
+            if context:
+                resume_prompt += f"\nAuthor notes: {context}"
+            # Stale/invalid UUID → resume fails → fall back to a fresh review (recovery).
+            codex = (
+                f"cat > {prompt_file} << 'CODEX_PROMPT_EOF'\n{resume_prompt}\nCODEX_PROMPT_EOF\n"
+                f"cd {cwd} && UV_CACHE_DIR=/tmp/uv-cache {_CODEX_BIN} exec resume {prev_uuid}"
+                f" --skip-git-repo-check --full-auto --json"
+                f" -o {codex_out} - < {prompt_file}"
+                f" || {{ echo '[resume failed — stale session, starting fresh review]'; {fresh_review}; }}"
+            )
+        else:
+            codex = fresh_review
     elif mode == "exec":
-        if not target:
+        if not target and not is_resume:
             return "Error: target file required for mode='exec'"
         prompt_parts_exec = [_REVIEW_CONTEXT]
         if context:
             prompt_parts_exec.append(f"Additional context: {context}\n")
-        prompt_parts_exec.append(f"Review the file: {target}")
-        prompt_parts_exec.append(f"Write your findings to {output}.")
+        # Keep the target in the prompt even on resume — the stale-UUID fresh-exec fallback
+        # reuses this same prompt file and would otherwise review nothing concrete.
+        if target:
+            prompt_parts_exec.append(f"Review the file: {target}")
+        if is_resume:
+            prompt_parts_exec.append("Re-review after the author's changes above. "
+                                     "Output a concise re-review (status of prior findings, new findings, verdict).")
+        else:
+            prompt_parts_exec.append(f"Write your findings to {output}.")
         prompt_parts_exec.append("Format: ## Summary, ## Findings (blocking/suggestion/question), ## Verdict")
         exec_prompt = "\n".join(prompt_parts_exec)
 
-        cmd = (
+        # resume inherits sandbox — do NOT pass -s; fresh exec writes with workspace-write.
+        sandbox = "" if is_resume else " -s workspace-write"
+        subcmd = f"exec resume {prev_uuid}" if is_resume else "exec"
+        codex = (
             f"cat > {prompt_file} << 'CODEX_PROMPT_EOF'\n{exec_prompt}\nCODEX_PROMPT_EOF\n"
-            f"cd {cwd} && UV_CACHE_DIR=/tmp/uv-cache {_CODEX_BIN} exec"
-            f" -s workspace-write --skip-git-repo-check --full-auto --ephemeral"
-            f" -o {output_abs}"
-            f" - < {prompt_file}"
+            f"cd {cwd} && UV_CACHE_DIR=/tmp/uv-cache {_CODEX_BIN} {subcmd}"
+            f"{sandbox} --skip-git-repo-check --full-auto --json"
+            f" -o {codex_out} - < {prompt_file}"
         )
+        if is_resume and target:
+            # Stale/invalid UUID → resume fails → fresh exec. Only when a target exists —
+            # without one the prompt has nothing concrete to review, so let resume fail loud.
+            # Writes to codex_out (=round_tmp) so the recovery is appended, not overwriting history.
+            fresh_exec = (
+                f"cd {cwd} && UV_CACHE_DIR=/tmp/uv-cache {_CODEX_BIN} exec"
+                f" -s workspace-write --skip-git-repo-check --full-auto --json"
+                f" -o {codex_out} - < {prompt_file}"
+            )
+            codex += f" || {{ echo '[resume failed — stale session, starting fresh]'; {fresh_exec}; }}"
     else:
         return f"Error: unknown mode '{mode}'. Use 'review' or 'exec'."
 
-    logger.info(f"codex_review: mode={mode} cwd={cwd} output={output_abs} cmd={cmd[:300]}")
+    # Ensure codex_sessions.json / *.round are git-ignored in THIS worktree before writing them,
+    # so they never dirty the tree / block merge_worker — regardless of how old the worktree is
+    # (create_worktree only excludes on spawn; long-lived workers need this at use-time too).
+    exclude_setup = (
+        f"cd {cwd} && GD=$(git rev-parse --git-common-dir 2>/dev/null)"
+        f" && {{ case \"$GD\" in /*) ;; *) GD=\"{cwd}/$GD\";; esac;"
+        f" mkdir -p \"$GD/info\";"
+        f" for p in 'codex_sessions.json' '*.round'; do"
+        f" grep -qxF \"$p\" \"$GD/info/exclude\" 2>/dev/null || echo \"$p\" >> \"$GD/info/exclude\";"
+        f" done; }}; "
+    )
+
+    # dash has no PIPESTATUS: capture codex's exit code, tee JSONL, then persist, then exit
+    # with codex's real code so bg-job success/failure reporting reflects the review, not jq.
+    persist = _codex_persist_snippet(sessions_path, slug, jsonl_file, is_resume, output_abs, round_tmp)
+    cmd = (
+        f"{exclude_setup}"
+        f"{{ {codex} ; echo $? > {rc_file} ; }} | tee {jsonl_file}"
+        f"{persist}"
+        f"; exit $(cat {rc_file} 2>/dev/null || echo 1)"
+    )
+
+    action = "resume" if is_resume else mode
+    logger.info(f"codex_review: mode={mode} resume={is_resume} slug={slug} cwd={cwd} output={output_abs}")
     result = await _api("POST", "/api/bg/jobs", json={
         "type": "run",
         "config": {"command": cmd},
-        "message": f"Codex {mode} done. Results in {output}",
+        "message": f"Codex {action} done. Results in {output}",
         "target_name": WORKER_NAME,
         "target_scope": SCOPE,
         "timeout_seconds": 600,
         "created_by": WORKER_NAME,
     })
     if isinstance(result, dict) and result.get("error"):
         return f"Error creating bg job: {result['error']}"
     job_id = result.get("id", "?")
+    resumed_note = f" (resumed session {prev_uuid[:8]})" if is_resume else ""
     return (
-        f"Codex {mode} started (bg job {job_id}, 10-min timeout). "
+        f"Codex {action} started{resumed_note} (bg job {job_id}, 10-min timeout). "
         f"You WILL be notified on success, timeout, or failure — do NOT poll, just wait. "
-        f"On success: read {output}. Do not start another codex_review until this one reports back."
+        f"On success: read {output}. To continue this debate, call codex_review again with the "
+        f"SAME output and resume=True. Do not start another codex_review until this one reports back."
     )
 
 
 if __name__ == "__main__":
     logger.info(f"Orchestra MCP stdio (url={ORCHESTRA_URL}, scope={SCOPE})")
     mcp.run(transport="stdio")
diff --git a/app/workspace.py b/app/workspace.py
index 42dcf2120..81f887ea2 100644
--- a/app/workspace.py
+++ b/app/workspace.py
@@ -113,21 +113,26 @@ def _git_cmd(args: list[str], **kwargs) -> subprocess.CompletedProcess:
     if agent_uid:
         import shutil as _sh
         gosu = _sh.which("gosu")
         if gosu:
             args = [gosu, agent_uid] + args
     return subprocess.run(args, **kwargs)
 
 
+# Injected / machine-local artifacts that must never dirty the tree or block merge_worker:
+# `.claude/` (injected skills+settings), and Codex session metadata written by codex_review
+# (`codex_sessions.json` = thread UUIDs, `*.round` = per-round temp before append).
+_WORKTREE_EXCLUDES = (".claude/", "codex_sessions.json", "*.round")
+
+
 def _exclude_claude_dir(wt_path: Path) -> None:
-    """Ignore injected `.claude/` (skills, settings) via `info/exclude` — untracked,
-    never committed, so it can't dirty the tree or block merge_worker. Idempotent.
-    External repos that don't already ignore `.claude/` would otherwise leave injected
-    skills as untracked files.
+    """Ignore injected/machine-local artifacts via `info/exclude` — untracked, never committed,
+    so they can't dirty the tree or block merge_worker. Idempotent. External repos that don't
+    already ignore these would otherwise leave them as untracked files.
 
     Git reads `info/exclude` from the COMMON git dir (`--git-common-dir`), not the
     per-worktree dir — a per-worktree `info/exclude` is silently ignored.
     """
     gd = _git_cmd(
         ["git", "rev-parse", "--git-common-dir"],
         cwd=str(wt_path), capture_output=True, text=True,
     )
@@ -135,22 +140,24 @@ def _exclude_claude_dir(wt_path: Path) -> None:
         logger.warning(f"could not locate git-common-dir for {wt_path}: {gd.stderr.strip()}")
         return
     git_dir = Path(gd.stdout.strip())
     if not git_dir.is_absolute():
         git_dir = (wt_path / git_dir).resolve()
     exclude = git_dir / "info" / "exclude"
     exclude.parent.mkdir(parents=True, exist_ok=True)
     existing = exclude.read_text() if exclude.exists() else ""
-    if any(line.strip() == ".claude/" for line in existing.splitlines()):
+    have = {line.strip() for line in existing.splitlines()}
+    missing = [p for p in _WORKTREE_EXCLUDES if p not in have]
+    if not missing:
         return
     with exclude.open("a") as f:
         if existing and not existing.endswith("\n"):
             f.write("\n")
-        f.write(".claude/\n")
+        f.write("".join(f"{p}\n" for p in missing))
 
 
 def create_worktree(repo_path: str, name: str, scope: str, task_id: str = "",
                     base_branch: str = "main",
                     worktree_cfg: "WorktreeCfg | None" = None) -> Worktree:
     # Защитный дефолт: пустая строка (sentinel из manager) → main, чтобы git не упал.
     if not base_branch:
         base_branch = "main"


## LATER FIX b929710c17 (6.7 days later): Sol runtime fixes: context accounting, cost delta, limit retry, codex_review atomicity, orphan pipe
lines of origin it changed/deleted: 51
(code only, capped 400 lines)

Sol runtime fixes: context accounting, cost delta, limit retry, codex_review atomicity, orphan pipe

- Context: read last_token_usage from Codex rollout instead of cumulative
- Cost: delta-only after resume (was re-counting full session)
- Retry: monthly/weekly limit = terminal, not infinite retry
- codex_review: atomic .round write, stale temp cleanup
- bg_jobs: orphan pipe fix (wait for leader exit, kill process group)
- StreamReader: limit=16MB + fail-soft while/readline/except ValueError


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


## LATER FIX ce2ddc4572 (32.6 days later): #179: #179: restore executable Codex reviews
lines of origin it changed/deleted: 7
(code only, capped 400 lines)

#179: #179: restore executable Codex reviews


diff --git a/app/mcp_stdio.py b/app/mcp_stdio.py
index 45637896a..a18e923da 100644
--- a/app/mcp_stdio.py
+++ b/app/mcp_stdio.py
@@ -1974,16 +1974,22 @@ _CODEX_MISSING_HINT = (
     "codex не найден: ни CODEX_BIN в окружении, ни `codex` в PATH. "
     "Поставь Codex CLI или задай CODEX_BIN=/путь/к/codex в .env сервиса. "
     "Проверить: `which codex`"
 )
 _REVIEW_RUBRIC = (
     "Review calibration: blocking = crash/corrupt/security; "
     "suggestion = real improvement; nit = skip."
 )
+_CODEX_EXECUTION_FAILURE_PATTERN = (
+    r"bwrap:|failed rtm_newaddr|setting up uid map: permission denied|"
+    r"sandbox.{0,80}(fail|reject)|no files were read|"
+    r"(every|all) (local )?commands? failed|"
+    r"(could not|unable to) (read|inspect|execute|review).{0,120}(sandbox|file)"
+)
 
 
 def _codex_sessions_path(output_abs: str) -> str:
     """codex_sessions.json lives next to the review output file (per worker/task dir)."""
     return f"{os.path.dirname(output_abs)}/codex_sessions.json"
 
 
 def _codex_slug(output: str) -> str:
@@ -2070,33 +2076,35 @@ async def codex_review(
     if mode == "review":
         review_prompt = (
             f"{review_context}\n\nReview the current uncommitted diff. "
             "Find bugs, security issues, breaking changes, and race conditions."
         )
         # Fresh review → codex_out: output_abs on a first run, round_tmp on a resume-fallback
         # (so the stale-session recovery is APPENDED as a round, never overwrites prior rounds).
         fresh_review = (
-            f"cd {q(cwd)} && UV_CACHE_DIR=/tmp/uv-cache {q(codex_bin)} exec review"
-            f" --uncommitted --skip-git-repo-check --full-auto --json"
+            f"cd {q(cwd)} && UV_CACHE_DIR=/tmp/uv-cache {q(codex_bin)}"
+            f" -s danger-full-access -a never exec review"
+            f" --uncommitted --skip-git-repo-check --json"
             f" -o {q(codex_out)} - < {q(prompt_file)}"
         )
         if is_resume:
-            # resume inherits sandbox from original session — do NOT pass -s. Re-review the diff.
+            # Override the original session policy: old reviews may have stored workspace-write.
             resume_prompt = (
                 f"{review_context}\n\n"
                 "Re-review the current uncommitted diff (run git diff yourself). "
                 "For each prior finding: FIXED / STILL BROKEN / NEW BUG. "
                 "Output a concise re-review (Re-review status, new findings, verdict)."
             )
             # Stale/invalid UUID → resume fails → fall back to a fresh review (recovery).
             codex = (
                 f"printf '%s' {q(resume_prompt)} > {q(prompt_file)}; "
-                f"cd {q(cwd)} && UV_CACHE_DIR=/tmp/uv-cache {q(codex_bin)} exec resume {q(prev_uuid)}"
-                f" --skip-git-repo-check --full-auto --json"
+                f"cd {q(cwd)} && UV_CACHE_DIR=/tmp/uv-cache {q(codex_bin)}"
+                f" -s danger-full-access -a never exec resume {q(prev_uuid)}"
+                f" --skip-git-repo-check --json"
                 f" -o {q(codex_out)} - < {q(prompt_file)}"
                 f" || {{ echo '[resume failed — stale session, starting fresh review]'; {fresh_review}; }}"
             )
         else:
             codex = f"printf '%s' {q(review_prompt)} > {q(prompt_file)}; {fresh_review}"
     elif mode == "exec":
         if not target and not is_resume:
             raise ApiToolError(
@@ -2112,32 +2120,32 @@ async def codex_review(
         if is_resume:
             prompt_parts_exec.append("Re-review after the author's changes above. "
                                      "Output a concise re-review (status of prior findings, new findings, verdict).")
         else:
             prompt_parts_exec.append("Return the complete review in your final response. Do not edit files.")
         prompt_parts_exec.append("Format: ## Summary, ## Findings (blocking/suggestion/question), ## Verdict")
         exec_prompt = "\n".join(prompt_parts_exec)
 
-        # resume inherits sandbox — do NOT pass -s; fresh exec writes with workspace-write.
-        sandbox = "" if is_resume else " -s workspace-write"
         subcmd = f"exec resume {prev_uuid}" if is_resume else "exec"
         codex = (
             f"printf '%s' {q(exec_prompt)} > {q(prompt_file)}; "
-            f"cd {q(cwd)} && UV_CACHE_DIR=/tmp/uv-cache {q(codex_bin)} {subcmd}"
-            f"{sandbox} --skip-git-repo-check --full-auto --json"
+            f"cd {q(cwd)} && UV_CACHE_DIR=/tmp/uv-cache {q(codex_bin)}"
+            f" -s danger-full-access -a never {subcmd}"
+            f" --skip-git-repo-check --json"
             f" -o {q(codex_out)} - < {q(prompt_file)}"
         )
         if is_resume and target:
             # Stale/invalid UUID → resume fails → fresh exec. Only when a target exists —
             # without one the prompt has nothing concrete to review, so let resume fail loud.
             # Writes to codex_out (=round_tmp) so the recovery is appended, not overwriting history.
             fresh_exec = (
-                f"cd {q(cwd)} && UV_CACHE_DIR=/tmp/uv-cache {q(codex_bin)} exec"
-                f" -s workspace-write --skip-git-repo-check --full-auto --json"
+                f"cd {q(cwd)} && UV_CACHE_DIR=/tmp/uv-cache {q(codex_bin)}"
+                f" -s danger-full-access -a never exec"
+                f" --skip-git-repo-check --json"
                 f" -o {q(codex_out)} - < {q(prompt_file)}"
             )
             codex += f" || {{ echo '[resume failed — stale session, starting fresh]'; {fresh_exec}; }}"
     else:
         raise ApiToolError(
             code="invalid_argument",
             message=f"unknown mode '{mode}'; use 'review' or 'exec'",
             details={"field": "mode"},
@@ -2176,16 +2184,20 @@ async def codex_review(
     # false success. Codex's real exit code and the artifact validator must both pass.
     cmd = (
         f"{exclude_setup}"
         f"mkdir -p {q(os.path.dirname(output_abs))}; "
         f"rm -f {q(rc_file)} {q(jsonl_file)} {q(round_tmp)} {q(prompt_file)}; "
         f"{{ {codex} ; echo $? > {q(rc_file)} ; }} | tee {q(jsonl_file)}; "
         f"RC=$(cat {q(rc_file)} 2>/dev/null || echo 1); "
         f"[ \"$RC\" -eq 0 ] || exit \"$RC\"; "
+        f"if grep -Eiq {q(_CODEX_EXECUTION_FAILURE_PATTERN)}"
+        f" {q(jsonl_file)} {q(round_tmp)}; then "
+        f"echo 'codex_review failed: Codex could not execute workspace commands' >&2; "
+        f"exit 70; fi; "
         f"{finalize}"
     )
 
     action = "resume" if is_resume else mode
     logger.info(f"codex_review: mode={mode} resume={is_resume} slug={slug} cwd={cwd} output={output_abs}")
     result = await _api("POST", "/api/bg/jobs", json={
         "type": "run",
         "config": {
diff --git a/docs/tasks/179/read-proof.txt b/docs/tasks/179/read-proof.txt
new file mode 100644
index 000000000..74a7c5e02
--- /dev/null
+++ b/docs/tasks/179/read-proof.txt
@@ -0,0 +1,3 @@
+Line 1: Codex sandbox acceptance fixture.
+Line 2: ORCHESTRA-179-READ-PROOF-68427.
+Line 3: The reviewer must quote line 2 exactly.
diff --git a/tests/test_codex_review_sandbox.py b/tests/test_codex_review_sandbox.py
new file mode 100644
index 000000000..54a987191
--- /dev/null
+++ b/tests/test_codex_review_sandbox.py
@@ -0,0 +1,97 @@
+import asyncio
+import json
+import os
+import subprocess
+
+import pytest
+
+
+PROJECT_CONTEXT = """PROJECT CONTEXT:
+- production Python service
+- review must inspect the requested file
+"""
+
+
+def _fake_api(tmp_path, captured):
+    async def fake_api(method, path, **kwargs):
+        if path == "/api/usage/readiness":
+            return {
+                "policy": "worker-weekly-v1", "state": "available",
+                "model": "gpt-5.6-sol", "provider": "codex",
+                "provider_label": "Codex", "weekly_utilization": 1,
+                "threshold": 95, "observed_at": 2_000_000_000,
+                "valid_until": 2_000_000_300, "alternatives": [],
+                "reason": "test",
+            }
+        if method == "GET":
+            return {"cwd": str(tmp_path), "worktree_path": str(tmp_path)}
+        captured.update(kwargs["json"])
+        return {"id": "bg-test"}
+
+    return fake_api
+
+
+@pytest.mark.parametrize("mode", ["exec", "review"])
+@pytest.mark.parametrize("resume", [False, True])
+def test_codex_review_disables_unusable_namespace_sandbox(
+    tmp_path, monkeypatch, mode, resume,
+):
+    import app.mcp_stdio as mcp
+
+    if resume:
+        (tmp_path / "codex_sessions.json").write_text(json.dumps({
+            "sessions": {"review": {"uuid": "019f0000-0000-7000-8000-000000000001"}},
+        }))
+    captured = {}
+    monkeypatch.setattr(mcp, "_api", _fake_api(tmp_path, captured))
+    monkeypatch.setattr(mcp, "WORKER_NAME", "sandbox-test")
+    monkeypatch.setattr(mcp.time, "time", lambda: 2_000_000_001)
+
+    asyncio.run(mcp.codex_review(
+        context=PROJECT_CONTEXT, target="artifact.txt",
+        output="review.md", mode=mode, resume=resume,
+    ))
+
+    command = captured["config"]["command"]
+    assert "-s danger-full-access -a never exec" in command
+    assert "workspace-write" not in command
+    assert "--full-auto" not in command
+
+
+def test_codex_review_rejects_blind_verdict_from_successful_process(tmp_path, monkeypatch):
+    import app.mcp_stdio as mcp
+
+    fake_codex = tmp_path / "fake-codex"
+    fake_codex.write_text("""#!/bin/sh
+out=
+while [ \"$#\" -gt 0 ]; do
+    if [ \"$1\" = \"-o\" ]; then
+        shift
+        out=$1
+    fi
+    shift
+done
+printf '%s\\n' '## Summary' 'Unable to review: bwrap: setting up uid map: Permission denied' '## Verdict' 'PASS' > \"$out\"
+printf '%s\\n' '{\"type\":\"thread.started\",\"thread_id\":\"blind-thread\"}'
+exit 0
+""")
+    os.chmod(fake_codex, 0o755)
+
+    captured = {}
+    monkeypatch.setattr(mcp, "_api", _fake_api(tmp_path, captured))
+    monkeypatch.setattr(mcp, "_codex_bin", lambda: str(fake_codex))
+    monkeypatch.setattr(mcp, "WORKER_NAME", "sandbox-test")
+    monkeypatch.setattr(mcp.time, "time", lambda: 2_000_000_001)
+
+    asyncio.run(mcp.codex_review(
+        context=PROJECT_CONTEXT, target="artifact.txt",
+        output="review.md", mode="exec",
+    ))
+    result = subprocess.run(
+        ["dash", "-c", captured["config"]["command"]],
+        capture_output=True, text=True,
+    )
+
+    assert result.returncode == 70
+    assert "could not execute workspace commands" in result.stderr
+    assert not (tmp_path / "review.md").exists()