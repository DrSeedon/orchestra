# Context for item-10

## Diff reviewed (-U20, capped at 1500 lines)

diff --git a/app/mcp_stdio.py b/app/mcp_stdio.py
index 45637896a..a18e923da 100644
--- a/app/mcp_stdio.py
+++ b/app/mcp_stdio.py
@@ -1962,40 +1962,46 @@ def _codex_bin() -> str:
     выглядело как «Codex сломался», хотя бинарник стоит и работает.
 
     Порядок: `CODEX_BIN` из окружения (явное переопределение) -> `which codex` -> пусто.
     Пусто здесь НЕ исключение: решает вызывающий, ему нужен внятный текст, а не падение из
     середины сборки shell-команды."""
     override = os.environ.get("CODEX_BIN", "").strip()
     if override:
         return override
     return shutil.which("codex") or ""
 
 
 _CODEX_MISSING_HINT = (
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
     """Slug = output filename stem. One slug = one session = one output file (matches skill)."""
     return os.path.splitext(os.path.basename(output))[0] or "review"
 
 
 def _read_codex_uuid(sessions_path: str, slug: str) -> str:
     """Read stored thread UUID for a slug. Empty string = no session yet."""
     try:
         with open(sessions_path) as f:
             data = json.load(f)
         return (data.get("sessions", {}).get(slug, {}) or {}).get("uuid", "") or ""
     except (FileNotFoundError, json.JSONDecodeError, OSError):
         return ""
@@ -2058,98 +2064,100 @@ async def codex_review(
     # Never let `codex -o` write the durable artifact directly: -o stores the final
     # agent_message and can overwrite a richer file created during the turn. Capture every
     # run in a temporary round, validate it, then atomically persist it.
     codex_out = round_tmp
     q = shlex.quote
 
     # Разрешаем бинарник ДО сборки команды: иначе несуществующий путь уезжает в shell и
     # возвращается голым exit 127 из фоновой джобы, где его никто не связывает с причиной.
     codex_bin = _codex_bin()
     if not codex_bin:
         return _CODEX_MISSING_HINT
 
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
                 code="invalid_argument",
                 message="target file required for mode='exec'",
                 details={"field": "target"},
             )
         prompt_parts_exec = [review_context]
         # Keep the target in the prompt even on resume — the stale-UUID fresh-exec fallback
         # reuses this same prompt file and would otherwise review nothing concrete.
         if target:
             prompt_parts_exec.append(f"Review the file: {target}")
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
         )
 
     # Ensure codex_sessions.json / *.round are git-ignored in THIS worktree before writing them,
     # so they never dirty the tree / block merge_worker — regardless of how old the worktree is
     # (create_worktree only excludes on spawn; long-lived workers need this at use-time too).
     exclude_setup = (
         f"cd {q(cwd)} && GD=$(git rev-parse --git-common-dir 2>/dev/null)"
         f" && {{ case \"$GD\" in /*) ;; *) GD={q(cwd)}/$GD;; esac;"
         f" mkdir -p \"$GD/info\";"
         f" for p in 'codex_sessions.json' '*.round'; do"
         f" grep -qxF \"$p\" \"$GD/info/exclude\" 2>/dev/null || echo \"$p\" >> \"$GD/info/exclude\";"
         f" done; }}; "
@@ -2164,40 +2172,44 @@ async def codex_review(
         "--sessions-file", q(sessions_path),
         "--slug", q(slug),
         "--jsonl-file", q(jsonl_file),
     ]
     if is_resume:
         finalize_args.append("--resume")
     if mode == "exec":
         finalize_args.append("--require-verdict")
     finalize = " ".join(finalize_args)
 
     # Remove stale temp state before each attempt. A service restart can kill the shell after
     # an old .rc=0 was written but before the artifact was persisted; reusing that file caused
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
             "command": cmd,
             "success_file": output_abs,
             "success_pattern": r"(?im)^##\s+Verdict\b" if mode == "exec" else "",
         },
         # Без слова "done": то же поле подставляется в провал как
         # "[Background job FAILED] <message>", и "Codex exec done" читалось как успех.
         "message": f"Codex {action} → {output}",
         "target_name": WORKER_NAME,
         "target_scope": SCOPE,
         "timeout_seconds": 600,
         "created_by": WORKER_NAME,
     })
diff --git a/docs/tasks/179/live-review-fixed.md b/docs/tasks/179/live-review-fixed.md
new file mode 100644
index 000000000..4f5a0b18f
--- /dev/null
+++ b/docs/tasks/179/live-review-fixed.md
@@ -0,0 +1,21 @@
+## Summary
+
+Command executed:
+
+```bash
+sed -n '2p' docs/tasks/179/read-proof.txt
+```
+
+Exact output:
+
+```text
+Line 2: ORCHESTRA-179-READ-PROOF-68427.
+```
+
+## Findings
+
+No blocking issues, suggestions, or questions.
+
+## Verdict
+
+PASS — workspace read execution succeeded.
diff --git a/docs/tasks/179/live-review-mutated.md b/docs/tasks/179/live-review-mutated.md
new file mode 100644
index 000000000..be0019054
--- /dev/null
+++ b/docs/tasks/179/live-review-mutated.md
@@ -0,0 +1,21 @@
+## Summary
+
+Command executed:
+
+```bash
+sed -n '2p' docs/tasks/179/read-proof.txt
+```
+
+Exact output:
+
+```text
+Line 2: ORCHESTRA-179-MUTATED-93158.
+```
+
+## Findings
+
+No blocking issues, suggestions, or questions.
+
+## Verdict
+
+PASS — execution-path acceptance check succeeded.
diff --git a/docs/tasks/179/live-review-original.md b/docs/tasks/179/live-review-original.md
new file mode 100644
index 000000000..ff0dd6678
--- /dev/null
+++ b/docs/tasks/179/live-review-original.md
@@ -0,0 +1,23 @@
+## Summary
+
+Command executed:
+
+```bash
+sed -n '2p' docs/tasks/179/read-proof.txt
+```
+
+Exact output:
+
+```text
+bwrap: loopback: Failed RTM_NEWADDR: Operation not permitted
+```
+
+The command failed before reading line 2.
+
+## Findings (blocking/suggestion/question)
+
+- **blocking:** The Codex sandbox cannot execute the workspace read because `bwrap` attempts a prohibited `RTM_NEWADDR` operation. Therefore, the required line content could not be verified.
+
+## Verdict
+
+**FAIL** — the execution-path acceptance check did not pass.
diff --git a/docs/tasks/179/read-proof.txt b/docs/tasks/179/read-proof.txt
new file mode 100644
index 000000000..74a7c5e02
--- /dev/null
+++ b/docs/tasks/179/read-proof.txt
@@ -0,0 +1,3 @@
+Line 1: Codex sandbox acceptance fixture.
+Line 2: ORCHESTRA-179-READ-PROOF-68427.
+Line 3: The reviewer must quote line 2 exactly.
diff --git a/docs/tasks/179/report.md b/docs/tasks/179/report.md
new file mode 100644
index 000000000..00568eb06
--- /dev/null
+++ b/docs/tasks/179/report.md
@@ -0,0 +1,118 @@
+# Task #179 — Codex review sandbox
+
+## Result
+
+`codex_review` now executes on this VPS without the unavailable user-namespace sandbox and rejects
+blind reviews that nevertheless return exit 0. The live acceptance reviewer executed a real file
+read and quoted an exact line that was absent from its prompt.
+
+## Reproduction confirmed
+
+All commands from the task were repeated unchanged:
+
+```text
+bwrap --dev-bind / / --unshare-net -- /bin/true
+exit 1: bwrap: loopback: Failed RTM_NEWADDR: Operation not permitted
+
+bwrap --dev-bind / / -- /bin/true
+exit 1: bwrap: setting up uid map: Permission denied
+
+unshare --user --map-root-user /bin/true
+exit 1: unshare: write failed /proc/self/uid_map: Operation not permitted
+```
+
+## Implementation
+
+In `app/mcp_stdio.py`:
+
+1. Every fresh, resumed, and stale-session fallback command now invokes Codex as
+   `codex -s danger-full-access -a never exec ...`.
+2. `--full-auto` was removed. It selected `workspace-write`, which starts vendor `bwrap` and fails
+   before every generated shell command on this host.
+3. `_CODEX_EXECUTION_FAILURE_PATTERN` detects the observed low-level errors and explicit reviewer
+   admissions that the sandbox or all commands failed.
+4. The background command checks the JSONL and final round before atomic persistence. A match emits
+   `codex_review failed: Codex could not execute workspace commands` and exits 70.
+
+Why this mode: `read-only` and `workspace-write` are unusable here because both require the kernel
+facility that was reproduced as unavailable. `danger-full-access` is the remaining and therefore
+minimal sufficient Codex sandbox mode. It does not grant permissions beyond the Unix account
+already running Orchestra; it only stops Codex from wrapping commands in a sandbox this account
+cannot create. `-a never` is required for unattended background execution and is expressed
+separately instead of using the broader combined bypass flag.
+
+## Behavioral tests
+
+Command:
+
+```text
+uv run pytest -q tests/test_codex_review_sandbox.py tests/test_mcp_codex_review.py tests/test_codex_bin_resolution.py tests/test_codex_review_artifact.py
+```
+
+Result: `23 passed in 5.05s`.
+
+The new test executes the complete generated shell command with a fake Codex process that writes a
+plausible `## Verdict` and exits 0 after reporting `bwrap`. The command exits 70 and does not persist
+the review artifact. Command-construction coverage checks fresh/resumed `exec` and `review` paths.
+
+## Live acceptance and mutation
+
+The first call through this worker's already-connected MCP reproduced the old defect and is kept as
+`live-review-original.md`: it reported `bwrap`, wrote a verdict, and the job announced exit 0.
+
+A fresh Python process then called the patched `app.mcp_stdio.codex_review()` against
+`read-proof.txt`. The prompt named only the path and line number. Codex emitted a real
+`command_execution` event with exit 0 and quoted:
+
+```text
+Line 2: ORCHESTRA-179-READ-PROOF-68427.
+```
+
+The mutation check ran backup, mutation, patched review, and restoration inside one server-side
+shell command. The reviewer observed the changed value:
+
+```text
+Line 2: ORCHESTRA-179-MUTATED-93158.
+```
+
+After the job, the fixture again contains `ORCHESTRA-179-READ-PROOF-68427` and no backup remains.
+Full outputs: `live-review-fixed.md` and `live-review-mutated.md`.
+
+## Rollout behavior for existing agents
+
+The Orchestra MCP command is an absolute path computed by the running server's
+`app/runtime_env.py`: `/home/kesha/orchestra/app/mcp_stdio.py`. An agent's MCP subprocess starts
+when its backend connects and keeps the imported code for that process lifetime. Editing a worker
+worktree therefore never hot-reloads the connected MCP process; after merge, a new backend
+connection reads the patched file from the main checkout.
+
+Automatic/manual reconnect paths:
+
+- Worker idle hibernation is scheduled after 300 seconds; orchestrator idle hibernation after 600
+  seconds. Hibernation calls `_disconnect_backend()`. The next message constructs and connects a new
+  backend, which starts a new MCP subprocess from main.
+- A real model change while idle also calls `_disconnect_backend()` immediately; the next message
+  starts a new backend/MCP process. Selecting the already active model is a no-op.
+- A server restart recreates every backend/MCP process, but is not necessary and was not performed.
+- A running or waiting session does not hibernate. Manual hibernation also refuses non-idle,
+  pending-delivery, and compacting sessions.
+
+Operational consequence: after merge, the four active workers remain on the old blind MCP until
+their current turns/background jobs finish. To make their upcoming reviews safe without restarting
+Orchestra, wait until each is idle, manually hibernate it, then send the continuation. Otherwise
+allow five idle minutes and let the next message wake it. A model change is an unnecessary,
+context-affecting alternative.
+
+## Follow-up required: protect jobs created by old MCP processes
+
+The MCP-side detector cannot protect commands already assembled by one of the nine old processes.
+`app/bg_jobs.py::_run_exec` currently accepts exit 0 and then checks only that `success_file` is
+nonempty and, for exec review, that it contains `## Verdict`. The reproduced blind artifact passes
+both checks.
+
+A separate shared-runtime change should reject known sandbox/command-execution failure markers in
+`full_output` and the artifact before `_trigger()`, scoped to Codex review jobs. Changing only the
+new MCP job config cannot protect old jobs because their config is already missing such a rule.
+This requires editing `app/bg_jobs.py` outside #179's ownership and, unlike `mcp_stdio.py`, requires
+an authorized Orchestra restart before the running server uses it. Until that follow-up is deployed,
+manual hibernation after this merge is the safe route for currently connected workers.
diff --git a/docs/tasks/179/self-review.md b/docs/tasks/179/self-review.md
new file mode 100644
index 000000000..8484804c3
--- /dev/null
+++ b/docs/tasks/179/self-review.md
@@ -0,0 +1,54 @@
+# Self-review #179
+
+## Scope
+
+Reviewed only `app/mcp_stdio.py`, `tests/test_codex_review_sandbox.py`, and the
+acceptance artifacts in this directory. Per task instruction, no Codex implementation
+review was used; Codex was used only after the fix to prove command execution.
+
+## Correctness checks
+
+- All four command paths (fresh/resumed `review`, fresh/resumed `exec`, including stale-session
+  fallbacks) now put the global CLI policy before `exec`: `-s danger-full-access -a never`.
+  This syntax was checked against `codex --help`, `codex exec review --help`, and
+  `codex exec resume --help`. `codex exec -s ... -a ...` is invalid; the global ordering is
+  required.
+- `danger-full-access` is the least permissive available sandbox *mode* that does not invoke the
+  unavailable namespace sandbox. `read-only` and `workspace-write` both require vendor `bwrap`.
+  `-a never` prevents an unattended background review from waiting for an approval prompt. The
+  stronger combined `--dangerously-bypass-approvals-and-sandbox` flag is not needed.
+- The failure detector runs after the real Codex exit-code check and before artifact persistence.
+  A Codex process that exits 0 but reports `bwrap`, a failed/rejected sandbox, unread files, or
+  commands that all failed exits 70. Therefore a blind verdict cannot satisfy `success_file` or
+  `success_pattern`.
+- The detector reads both JSONL and the final round file. This covers a low-level command failure
+  printed as a tool event and a reviewer that only admits the failure in its final answer.
+- Existing atomic finalization and session UUID persistence remain unchanged.
+
+## Regression risks checked
+
+- Removed every `--full-auto` and `workspace-write` occurrence from generated review commands.
+- Resumed sessions explicitly override their stored policy; otherwise sessions originally created
+  with `workspace-write` would remain broken after this fix.
+- Shell syntax is exercised by existing command-construction tests and by the new behavioral test.
+- The detector is deliberately fail-closed. A review that discusses one of the failure phrases as
+  subject matter may be rejected; that is safer than approving a review that executed no command.
+
+## Evidence
+
+- Targeted tests: `23 passed`.
+- Original connected MCP process reproduced the blind false success in
+  `live-review-original.md` (exit 0 despite `bwrap`).
+- Fresh-process patched `codex_review()` executed `sed -n '2p'` and returned
+  `Line 2: ORCHESTRA-179-READ-PROOF-68427.` in `live-review-fixed.md`.
+- One background shell block copied the fixture, changed line 2, ran the patched review, restored
+  the backup while preserving the review exit code, and left no `.bak`. Codex returned
+  `Line 2: ORCHESTRA-179-MUTATED-93158.` in `live-review-mutated.md`; the fixture now contains the
+  original `ORCHESTRA-179-READ-PROOF-68427` line.
+
+## Remaining deployment gap
+
+Already-connected MCP subprocesses keep the old module until their parent backend disconnects.
+The server-side background-job runner currently trusts exit 0 plus a nonempty artifact/verdict and
+cannot detect blind output produced by an old MCP command. This is outside the authorized files and
+is documented in `report.md` as a separate follow-up.
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


## Later history of the touched files on main (after this commit)

138 later commits touch these paths; the first 40 (oldest first):
106961b53 2026-08-11 #182: #182: preserve Codex review artifacts on guard failure
2cb314128 2026-08-11 #183: #183: restore default Codex review mode
503e71ec9 2026-08-12 #215: #215: account standalone Codex review usage
9fc4534e5 2026-08-12 #231: #231: предрегистрация эксперимента (стенд, критерий, все четыре исхода) — ДО спавна плеч
99dc5e1c4 2026-08-13 #231: #231: MCP-тул open_fan + проводка веера в промпты спавнящих ролей
5c346ffd5 2026-08-13 #227: #227: enforce worker model policy at spawn
85b6174ee 2026-08-13 #246: #246: validate task creation project scopes
83eda0e05 2026-08-13 #241: #241: tag the owner only when the turn calls notify_user
e9c34833e 2026-08-14 #265: #265: canary handshake so a same-name Grok MCP server cannot impersonate ours
4b3ebde4d 2026-08-14 #240: #240: platform runs the ticket acceptance command before squash
4b0611cfb 2026-08-14 #240: #240: drop worker-set acceptance_command in task_create
e439707ce 2026-08-14 #250: #250: refuse unreviewable diffs at merge
077a795c7 2026-08-14 #281: #281: bind orchestrator HTTP privilege to a per-MCP proof
b0b72d655 2026-08-16 #294: #294: plan secure artifact links
bd4f6e61a 2026-08-16 #304: #304: select codex review model explicitly
1e020d60e 2026-08-17 #311: #311: freeze durable delivery RED oracles
9a1e2d108 2026-08-17 #314: #314: freeze enforcement and analytics RED oracles
c87ad448a 2026-08-18 #332, #304: #332: rewrite codex_review model tests against the post-#304 contract
0707d9257 2026-08-19 #343: одно правило допуска по квоте, прежние квотные системы вырезаны
1ecd00717 2026-08-21 bg_list показывает расписание, время срабатывания и команду
fa3e993db 2026-08-23 Allow fresh model switches without handoff
dc09cc236 2026-08-22 Squashed commits: - #366: research + plan + 22 red tests (model catalog, two-level availability) - #366: plan review section + behavioral red reasons (no external reviewer: quota) - #366: T1 — kv_set/kv_delete writers + two-level availability flags (overlay, read-through kv) - #366: T2 — OpenRouter catalog fetch/normalize/kv-cache + registration re-applied inside every registry rebuild - #366: T3 — two-level enforcement: /api/models dashboard filter, agents gate in _create_session_locked, change-model via=dashboard|mcp, bounded unknown-model error; CONTRACT CHANGE: derived views are now a superset of SELECTABLE_MODEL_SPECS (test_derived_views_carry_exactly_the_declared_specs rewritten as subset assertions) - WIP #366: T4 catalog HTTP API written (GET/POST/PATCH /api/models/catalog*), tests not yet run; TODO: run test_catalog_api.py, mutation, T5 frontend+Playwright probe, T6 - #366: T4 — /api/models/catalog GET(union registry+cache)/refresh POST/flags PATCH; dropped counter surfaced; mutation: PATCH-echo-without-persist caught - #366: T5 — catalog modal screen: search/free/tools/image filters, two toggles per model, refresh button; picker untouched - #366: T5 — live Playwright probe evidence (probe-catalog.png): worktree js/css substituted on :8888, catalog modal renders 18 models / 36 toggles, search filters, clone-frozen screenshot - #366: T6 — live-agent shoulders: resume surface intact after both flags off, new spawn rejected with actionable message, switch-away allowed; mutation: message without screen name caught - #366: report + personal memory - #366: изоляция тестов — снимок и восстановление реестра моделей между тестами; kv-чтение флагов/кеша fail-soft при отсутствии таблицы - #366: route surface snapshot — +/api/models/catalog{,/refresh,/flags} (intentional new public endpoints)
3e4d87982 2026-08-23 #279: #279: fix acceptance command contract
e2ecc033d 2026-08-23 #293: #293: freeze ownership lifecycle red tests
0a9ad8130 2026-08-23 #383: #383: expose acceptance command recovery via task update
71374ea56 2026-08-23 #385: #385: research deferred turn control and provenance
81a1c60f8 2026-08-24 #380: #380: research durable send acceptance
f8295d11e 2026-08-24 #386: #386: research regression-aware merge gate
9d2627281 2026-08-24 Merge origin/main into main (2026-08-24 sync)
f4b7d9acd 2026-08-24 fix(prompts): suppress notify tags for active users
9f946a601 2026-08-24 #309: #309: freeze phase2 deletion oracles
2fa666288 2026-08-24 #337: #337: add durable primary TG file receipts
6f874ace5 2026-08-24 #248: make task state platform-owned and restart-safe
f3ae49867 2026-08-25 Merge remote-tracking branch 'origin/main'
e22368b06 2026-08-25 #348: #348: handle send_file version skew
7717ef880 2026-08-25 #349: WIP #349: implement agent-only knowledge pending oracle decision
c2ea45fa0 2026-08-25 #358: #358: complete typed document cutover
08b75e851 2026-08-25 #359: reserve MCP slots for canonical tools
c885f10e5 2026-08-25 #360: reload MCP tools after Codex resume
12d7554a9 2026-08-25 #362: restore file-backed memory prompts

## Patches of the first 8 later commits, restricted to the touched paths (each capped at 150 lines)

### 106961b53 #182: #182: preserve Codex review artifacts on guard failure

diff --git a/app/mcp_stdio.py b/app/mcp_stdio.py
index a18e923da..27c3a3a31 100644
--- a/app/mcp_stdio.py
+++ b/app/mcp_stdio.py
@@ -1983,10 +1983,34 @@ _CODEX_EXECUTION_FAILURE_PATTERN = (
     r"bwrap:|failed rtm_newaddr|setting up uid map: permission denied|"
     r"sandbox.{0,80}(fail|reject)|no files were read|"
     r"(every|all) (local )?commands? failed|"
     r"(could not|unable to) (read|inspect|execute|review).{0,120}(sandbox|file)"
 )
+_CODEX_EXECUTION_FAILURE_JSONL_CHECK = """\
+import json
+import re
+import sys
+
+pattern = re.compile(sys.argv[2], re.IGNORECASE)
+with open(sys.argv[1], encoding="utf-8", errors="replace") as source:
+    for line in source:
+        try:
+            event = json.loads(line)
+        except (json.JSONDecodeError, TypeError):
+            continue
+        if not isinstance(event, dict):
+            continue
+        item = event.get("item")
+        if (isinstance(item, dict) and item.get("type") == "agent_message"
+                and pattern.search(str(item.get("text", "")))):
+            raise SystemExit(0)
+raise SystemExit(1)
+"""
+_CODEX_EXECUTION_FAILURE_NOTE = (
+    "\n\n> **Execution guard failed:** Codex reported that it could not execute "
+    "workspace commands. The review above is preserved for diagnosis.\n"
+)
 
 
 def _codex_sessions_path(output_abs: str) -> str:
     """codex_sessions.json lives next to the review output file (per worker/task dir)."""
     return f"{os.path.dirname(output_abs)}/codex_sessions.json"
@@ -2123,11 +2147,11 @@ async def codex_review(
         else:
             prompt_parts_exec.append("Return the complete review in your final response. Do not edit files.")
         prompt_parts_exec.append("Format: ## Summary, ## Findings (blocking/suggestion/question), ## Verdict")
         exec_prompt = "\n".join(prompt_parts_exec)
 
-        subcmd = f"exec resume {prev_uuid}" if is_resume else "exec"
+        subcmd = f"exec resume {q(prev_uuid)}" if is_resume else "exec"
         codex = (
             f"printf '%s' {q(exec_prompt)} > {q(prompt_file)}; "
             f"cd {q(cwd)} && UV_CACHE_DIR=/tmp/uv-cache {q(codex_bin)}"
             f" -s danger-full-access -a never {subcmd}"
             f" --skip-git-repo-check --json"
@@ -2176,10 +2200,14 @@ async def codex_review(
     if is_resume:
         finalize_args.append("--resume")
     if mode == "exec":
         finalize_args.append("--require-verdict")
     finalize = " ".join(finalize_args)
+    failure_check = " ".join([
+        q(sys.executable), "-c", q(_CODEX_EXECUTION_FAILURE_JSONL_CHECK),
+        q(jsonl_file), q(_CODEX_EXECUTION_FAILURE_PATTERN),
+    ])
 
     # Remove stale temp state before each attempt. A service restart can kill the shell after
     # an old .rc=0 was written but before the artifact was persisted; reusing that file caused
     # false success. Codex's real exit code and the artifact validator must both pass.
     cmd = (
@@ -2187,15 +2215,16 @@ async def codex_review(
         f"mkdir -p {q(os.path.dirname(output_abs))}; "
         f"rm -f {q(rc_file)} {q(jsonl_file)} {q(round_tmp)} {q(prompt_file)}; "
         f"{{ {codex} ; echo $? > {q(rc_file)} ; }} | tee {q(jsonl_file)}; "
         f"RC=$(cat {q(rc_file)} 2>/dev/null || echo 1); "
         f"[ \"$RC\" -eq 0 ] || exit \"$RC\"; "
-        f"if grep -Eiq {q(_CODEX_EXECUTION_FAILURE_PATTERN)}"
-        f" {q(jsonl_file)} {q(round_tmp)}; then "
+        f"{finalize}; FINALIZE_RC=$?; "
+        f"[ \"$FINALIZE_RC\" -eq 0 ] || exit \"$FINALIZE_RC\"; "
+        f"if {failure_check}; then "
+        f"printf '%s' {q(_CODEX_EXECUTION_FAILURE_NOTE)} >> {q(output_abs)}; "
         f"echo 'codex_review failed: Codex could not execute workspace commands' >&2; "
-        f"exit 70; fi; "
-        f"{finalize}"
+        f"exit 70; fi"
     )
 
     action = "resume" if is_resume else mode
     logger.info(f"codex_review: mode={mode} resume={is_resume} slug={slug} cwd={cwd} output={output_abs}")
     result = await _api("POST", "/api/bg/jobs", json={
diff --git a/tests/test_codex_review_sandbox.py b/tests/test_codex_review_sandbox.py
index 54a987191..7126f19a0 100644
--- a/tests/test_codex_review_sandbox.py
+++ b/tests/test_codex_review_sandbox.py
@@ -71,10 +71,11 @@ while [ \"$#\" -gt 0 ]; do
     fi
     shift
 done
 printf '%s\\n' '## Summary' 'Unable to review: bwrap: setting up uid map: Permission denied' '## Verdict' 'PASS' > \"$out\"
 printf '%s\\n' '{\"type\":\"thread.started\",\"thread_id\":\"blind-thread\"}'
+printf '%s\\n' '{\"type\":\"item.completed\",\"item\":{\"type\":\"agent_message\",\"text\":\"Unable to review: bwrap: setting up uid map: Permission denied\"}}'
 exit 0
 """)
     os.chmod(fake_codex, 0o755)
 
     captured = {}
@@ -92,6 +93,113 @@ exit 0
         capture_output=True, text=True,
     )
 
     assert result.returncode == 70
     assert "could not execute workspace commands" in result.stderr
-    assert not (tmp_path / "review.md").exists()
+    review = (tmp_path / "review.md").read_text()
+    assert "Unable to review: bwrap: setting up uid map: Permission denied" in review
+    assert "Execution guard failed" in review
+
+
+def test_codex_review_failure_check_skips_scalar_jsonl_rows(tmp_path):
+    import app.mcp_stdio as mcp
+
+    jsonl = tmp_path / "review.jsonl"
+    jsonl.write_text(
+        '[]\n'
+        '{"type":"item.completed","item":{"type":"agent_message",'
+        '"text":"Unable to review: bwrap: permission denied"}}\n'
+    )
+
+    result = subprocess.run([
+        mcp.sys.executable, "-c", mcp._CODEX_EXECUTION_FAILURE_JSONL_CHECK,
+        str(jsonl), mcp._CODEX_EXECUTION_FAILURE_PATTERN,
+    ], capture_output=True, text=True)
+
+    assert result.returncode == 0
+
+
+def test_codex_review_ignores_failure_marker_in_command_output(tmp_path, monkeypatch):
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
+printf '%s\\n' '## Summary' 'Reviewed the requested file successfully.' '## Verdict' 'PASS' > \"$out\"
### 2cb314128 #183: #183: restore default Codex review mode

diff --git a/app/mcp_stdio.py b/app/mcp_stdio.py
index 27c3a3a31..4a4a6beed 100644
--- a/app/mcp_stdio.py
+++ b/app/mcp_stdio.py
@@ -2097,19 +2097,20 @@ async def codex_review(
     if not codex_bin:
         return _CODEX_MISSING_HINT
 
     if mode == "review":
         review_prompt = (
-            f"{review_context}\n\nReview the current uncommitted diff. "
+            f"{review_context}\n\nReview all current uncommitted changes in this worktree "
+            "(staged, unstaged, and untracked). Inspect them with git status and git diff. "
             "Find bugs, security issues, breaking changes, and race conditions."
         )
         # Fresh review → codex_out: output_abs on a first run, round_tmp on a resume-fallback
         # (so the stale-session recovery is APPENDED as a round, never overwrites prior rounds).
         fresh_review = (
             f"cd {q(cwd)} && UV_CACHE_DIR=/tmp/uv-cache {q(codex_bin)}"
             f" -s danger-full-access -a never exec review"
-            f" --uncommitted --skip-git-repo-check --json"
+            f" --skip-git-repo-check --json"
             f" -o {q(codex_out)} - < {q(prompt_file)}"
         )
         if is_resume:
             # Override the original session policy: old reviews may have stored workspace-write.
             resume_prompt = (
diff --git a/tests/test_codex_review_sandbox.py b/tests/test_codex_review_sandbox.py
index 7126f19a0..c7b2d3572 100644
--- a/tests/test_codex_review_sandbox.py
+++ b/tests/test_codex_review_sandbox.py
@@ -201,5 +201,22 @@ exit 0
     )
 
     assert result.returncode == 0
     assert resume_uuid in args_file.read_text().splitlines()
     assert not injected.exists()
+
+
+def test_installed_codex_rejects_multiple_review_targets(tmp_path):
+    import app.mcp_stdio as mcp
+
+    codex_bin = mcp._codex_bin()
+    if not codex_bin:
+        pytest.skip("Codex CLI is not installed; generated-command test remains mandatory")
+
+    result = subprocess.run(
+        [codex_bin, "exec", "review", "--uncommitted", "-"],
+        cwd=tmp_path, input="", capture_output=True, text=True, timeout=10,
+    )
+
+    assert result.returncode == 2
+    assert "--uncommitted" in result.stderr
+    assert "cannot be used with '[PROMPT]'" in result.stderr
### 503e71ec9 #215: #215: account standalone Codex review usage

diff --git a/app/mcp_stdio.py b/app/mcp_stdio.py
index 4a4a6beed..2a6746948 100644
--- a/app/mcp_stdio.py
+++ b/app/mcp_stdio.py
@@ -537,14 +537,11 @@ def _spawn_delivery_error(
         details=details,
         result=result,
     )
 
 
-# `codex_review` собирает `codex exec` без `--model`, то есть берёт дефолт из
-# ~/.codex/config.toml. Ключа `model` там нет → семейство codex → лимит-id `codex`.
-# Проверено измерением: живой `codex exec` отказал по квоте, когда Spark был на 1% —
-# в Spark-бакет он не ходит. Этой же моделью тул представляется в докстринге.
+# `codex_review` пинит эту модель и в quota gate, и в самом CLI, и в телеметрии.
 _CODEX_REVIEW_MODEL = "gpt-5.6-sol"
 _READINESS_POLICY = "worker-weekly-v1"
 _READINESS_MAX_AGE_SECONDS = 300.0
 _READINESS_CLOCK_SKEW_SECONDS = 5.0
 
@@ -2066,10 +2063,13 @@ async def codex_review(
     if refusal:
         raise refusal
     info = await _api("GET", f"/api/sessions/{WORKER_NAME}", params={"scope": SCOPE})
     if isinstance(info, dict) and info.get("error"):
         return f"Error resolving worker cwd: {info['error']}"
+    requesting_session_id = str(info.get("id") or "").strip()
+    if not requesting_session_id:
+        return "Error resolving worker session id: respawn the worker"
     cwd = info.get("worktree_path") or info.get("cwd") or info.get("scope", SCOPE)
     output_abs = f"{cwd}/{output}" if not output.startswith("/") else output
 
     sessions_path = _codex_sessions_path(output_abs)
     slug = _codex_slug(output)
@@ -2094,21 +2094,22 @@ async def codex_review(
     # Разрешаем бинарник ДО сборки команды: иначе несуществующий путь уезжает в shell и
     # возвращается голым exit 127 из фоновой джобы, где его никто не связывает с причиной.
     codex_bin = _codex_bin()
     if not codex_bin:
         return _CODEX_MISSING_HINT
+    codex_cli = f"{q(codex_bin)} -m {q(_CODEX_REVIEW_MODEL)}"
 
     if mode == "review":
         review_prompt = (
             f"{review_context}\n\nReview all current uncommitted changes in this worktree "
             "(staged, unstaged, and untracked). Inspect them with git status and git diff. "
             "Find bugs, security issues, breaking changes, and race conditions."
         )
         # Fresh review → codex_out: output_abs on a first run, round_tmp on a resume-fallback
         # (so the stale-session recovery is APPENDED as a round, never overwrites prior rounds).
         fresh_review = (
-            f"cd {q(cwd)} && UV_CACHE_DIR=/tmp/uv-cache {q(codex_bin)}"
+            f"cd {q(cwd)} && UV_CACHE_DIR=/tmp/uv-cache {codex_cli}"
             f" -s danger-full-access -a never exec review"
             f" --skip-git-repo-check --json"
             f" -o {q(codex_out)} - < {q(prompt_file)}"
         )
         if is_resume:
@@ -2120,11 +2121,11 @@ async def codex_review(
                 "Output a concise re-review (Re-review status, new findings, verdict)."
             )
             # Stale/invalid UUID → resume fails → fall back to a fresh review (recovery).
             codex = (
                 f"printf '%s' {q(resume_prompt)} > {q(prompt_file)}; "
-                f"cd {q(cwd)} && UV_CACHE_DIR=/tmp/uv-cache {q(codex_bin)}"
+                f"cd {q(cwd)} && UV_CACHE_DIR=/tmp/uv-cache {codex_cli}"
                 f" -s danger-full-access -a never exec resume {q(prev_uuid)}"
                 f" --skip-git-repo-check --json"
                 f" -o {q(codex_out)} - < {q(prompt_file)}"
                 f" || {{ echo '[resume failed — stale session, starting fresh review]'; {fresh_review}; }}"
             )
@@ -2151,21 +2152,21 @@ async def codex_review(
         exec_prompt = "\n".join(prompt_parts_exec)
 
         subcmd = f"exec resume {q(prev_uuid)}" if is_resume else "exec"
         codex = (
             f"printf '%s' {q(exec_prompt)} > {q(prompt_file)}; "
-            f"cd {q(cwd)} && UV_CACHE_DIR=/tmp/uv-cache {q(codex_bin)}"
+            f"cd {q(cwd)} && UV_CACHE_DIR=/tmp/uv-cache {codex_cli}"
             f" -s danger-full-access -a never {subcmd}"
             f" --skip-git-repo-check --json"
             f" -o {q(codex_out)} - < {q(prompt_file)}"
         )
         if is_resume and target:
             # Stale/invalid UUID → resume fails → fresh exec. Only when a target exists —
             # without one the prompt has nothing concrete to review, so let resume fail loud.
             # Writes to codex_out (=round_tmp) so the recovery is appended, not overwriting history.
             fresh_exec = (
-                f"cd {q(cwd)} && UV_CACHE_DIR=/tmp/uv-cache {q(codex_bin)}"
+                f"cd {q(cwd)} && UV_CACHE_DIR=/tmp/uv-cache {codex_cli}"
                 f" -s danger-full-access -a never exec"
                 f" --skip-git-repo-check --json"
                 f" -o {q(codex_out)} - < {q(prompt_file)}"
             )
             codex += f" || {{ echo '[resume failed — stale session, starting fresh]'; {fresh_exec}; }}"
@@ -2188,17 +2189,23 @@ async def codex_review(
         f" done; }}; "
     )
 
     finalizer = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "codex_review_artifact.py")
+    usage_event_id = f"codex-review:{uuid.uuid4()}"
     finalize_args = [
         q(sys.executable), q(finalizer),
         "--output", q(output_abs),
         "--round-file", q(round_tmp),
         "--sessions-file", q(sessions_path),
         "--slug", q(slug),
         "--jsonl-file", q(jsonl_file),
+        "--usage-event-id", q(usage_event_id),
+        "--usage-session-id", q(requesting_session_id),
+        "--usage-scope", q(SCOPE),
+        "--usage-task-id", q(str(info.get("task_id") or "")),
+        "--usage-model", q(_CODEX_REVIEW_MODEL),
     ]
     if is_resume:
         finalize_args.append("--resume")
     if mode == "exec":
         finalize_args.append("--require-verdict")
diff --git a/tests/test_codex_review_sandbox.py b/tests/test_codex_review_sandbox.py
index c7b2d3572..72b46ee42 100644
--- a/tests/test_codex_review_sandbox.py
+++ b/tests/test_codex_review_sandbox.py
@@ -22,17 +22,29 @@ def _fake_api(tmp_path, captured):
                 "threshold": 95, "observed_at": 2_000_000_000,
                 "valid_until": 2_000_000_300, "alternatives": [],
                 "reason": "test",
             }
         if method == "GET":
-            return {"cwd": str(tmp_path), "worktree_path": str(tmp_path)}
+            return {
+                "id": "sandbox-requester", "cwd": str(tmp_path),
+                "worktree_path": str(tmp_path),
+            }
         captured.update(kwargs["json"])
         return {"id": "bg-test"}
 
     return fake_api
 
 
+def _prepare_usage_db(tmp_path, monkeypatch):
+    import app.db as db
+
+    path = tmp_path / "usage.db"
+    monkeypatch.setattr(db, "DB_PATH", path)
+    monkeypatch.setenv("ORCHESTRA_DB_PATH", str(path))
+    db.init_db()
+
### 9fc4534e5 #231: #231: предрегистрация эксперимента (стенд, критерий, все четыре исхода) — ДО спавна плеч

diff --git a/app/mcp_stdio.py b/app/mcp_stdio.py
index 2a6746948..26ee22465 100644
--- a/app/mcp_stdio.py
+++ b/app/mcp_stdio.py
@@ -63,10 +63,17 @@ READ_ONLY_MCP_TOOLS = frozenset({
     "payment_status",
     "bg_list",
     "search_memory",
 })
 
+REDUCER_MCP_TOOLS = frozenset({
+    "send_message",
+    "update_progress",
+    "list_agents",
+    "search_memory",
+})
+
 
 @dataclass
 class ApiToolError(RuntimeError):
     code: str
     message: str
@@ -269,10 +276,12 @@ mcp = OrchestraMCP("orchestra")
 
 def _tool_names_for_access_mode(names: set[str], mode: str) -> set[str]:
     normalized = mode.strip().lower()
     if normalized in {"read-only", "readonly", "read"}:
         return names & READ_ONLY_MCP_TOOLS
+    if normalized == "reducer":
+        return names & REDUCER_MCP_TOOLS
     if normalized == "full":
         return set(names)
     raise ValueError(f"Unknown ORCHESTRA_ACCESS_MODE: {mode!r}")
 
 
### 99dc5e1c4 #231: #231: MCP-тул open_fan + проводка веера в промпты спавнящих ролей

diff --git a/app/mcp_stdio.py b/app/mcp_stdio.py
index 26ee22465..e542f09e1 100644
--- a/app/mcp_stdio.py
+++ b/app/mcp_stdio.py
@@ -910,10 +910,46 @@ async def send_message(to: str, message: str) -> str:
     if parent and parent != WORKER_NAME:
         return f"Message sent to '{to}'\n⚠️ This worker belongs to '{parent}'. Consider messaging '{parent}' instead."
     return f"Message sent to '{to}'"
 
 
+@mcp.tool()
+async def open_fan(children: list[str], deadline_seconds: float = 1800.0,
+                   reducer: str = "") -> str:
+    """Открыть веер: копить отчёты перечисленных детей и разбудить тебя ОДИН раз.
+
+    Зови СРАЗУ после того, как заспавнил нескольких детей на независимые куски одной
+    работы. Пока веер открыт, их отчёты не будят тебя по одному — они копятся, и ты
+    просыпаешься один раз, когда отчитался последний (или когда истёк
+    `deadline_seconds`, по умолчанию 1800.0 = 30 минут). Замер: одно пробуждение
+    родителя стоит ≈$0.87 при 99% cache_read, то есть N детей без веера — N таких ходов.
+
+    ВАЖНО, иначе барьер протечёт: ребёнок, закончивший ход МОЛЧА, будит тебя мимо
+    веера через авто-репорт. В задании КАЖДОМУ ребёнку требуй отчитаться ВЫЗОВОМ
+    `send_message`, а не просто закончить ход.
+
+    Не для одного ребёнка и не «на всякий случай»: забытый открытый веер держит
+    отчёты до дедлайна. Срочное проходит мимо веера по `message_kind`.
+    """
+    kids = [c for c in (children or []) if isinstance(c, str) and c.strip()]
+    if len(kids) < 2:
+        return "open_fan needs at least 2 children; for one child just wait for its report."
+    fan_id = f"{WORKER_NAME or ROLE}-{uuid.uuid4().hex[:8]}"
+    result = await _api("POST", "/api/fan/open", json={
+        "fan_id": fan_id,
+        "parent_name": WORKER_NAME or ROLE,
+        "scope": SCOPE,
+        "children": kids,
+        "deadline_seconds": deadline_seconds,
+        "reducer": reducer,
+    })
+    if isinstance(result, dict) and result.get("error"):
+        return f"open_fan failed: {result['error']}"
+    return (f"Fan '{fan_id}' open for {len(kids)} children (deadline {deadline_seconds}s). "
+            f"END YOUR TURN NOW — you will be woken once, when the last child reports.")
+
+
 _ORCH_ROLES = frozenset({"orchestrator", "sub-orchestrator"})
 
 
 def _cache_pill(s: dict) -> str:
     """Prompt-cache warmth as a short exact/approximate text pill."""
### 5c346ffd5 #227: #227: enforce worker model policy at spawn

diff --git a/app/mcp_stdio.py b/app/mcp_stdio.py
index e542f09e1..39f724941 100644
--- a/app/mcp_stdio.py
+++ b/app/mcp_stdio.py
@@ -721,18 +721,20 @@ async def spawn_worker(name: str, task: str, repo_path: str,
                        description: str = "",
                        base_branch: str = "",
                        role: str = "worker",
                        mcp_servers: str = "",
                        owned_dirs: str = "",
-                       tg_topic: bool = False) -> str:
+                       tg_topic: bool = False,
+                       model_policy_override_reason: str = "") -> str:
     """Spawn a new worker agent in a git worktree. Model is REQUIRED — choose it by the `<model-routing>` block in your own prompt, which is the single source of truth for routing (model ids are deliberately not repeated here: a duplicated list rots).
     base_branch — от какой локальной ветки ответвить worktree. Пусто ("") = авто по
     стратегии пайплайна: parent → ветка родителя, main → проверяемый mainline репозитория.
     При неоднозначности spawn требует явную ветку.
     mcp_servers — JSON-объект с доп. MCP-серверами для воркера (формат как в .mcp.json: {"name": {"command": ..., "args": [...]}}). Мерджится с дефолтным Orchestra MCP; ключ "orchestra" игнорируется. Переживает рестарт.
     owned_dirs — JSON-массив директорий которыми владеет воркер, напр. ["app/api/", "app/models/"]. Инжектится в промпт воркера ("трогай только это"). Пересечение с owned_dirs другого живого воркера → БЛОК (spawn fails).
-    tg_topic — если True, агент получит собственный TG топик для логов и сообщений."""
+    tg_topic — если True, агент получит собственный TG топик для логов и сообщений.
+    model_policy_override_reason — явное исключение из серверной model policy. Пусто = исключения нет; непустая причина записывается в лог."""
     if not model:
         raise ApiToolError(
             code="invalid_argument",
             message="model is required; choose it by the <model-routing> block in your prompt",
             details={"field": "model"},
@@ -787,10 +789,12 @@ async def spawn_worker(name: str, task: str, repo_path: str,
         body["task_id"] = task_id
     if description:
         body["description"] = description
     if tg_topic:
         body["tg_topic"] = True
+    if model_policy_override_reason:
+        body["model_policy_override_reason"] = model_policy_override_reason
     result = await _api("POST", "/api/sessions", json=body)
     if isinstance(result, dict) and result.get("error"):
         raise ApiToolError(code="domain_error", message=f"Spawn failed: {result['error']}")
     required = ("worktree_path", "branch", "repo_path", "git_common_dir")
     missing = [
### 85b6174ee #246: #246: validate task creation project scopes

diff --git a/app/mcp_stdio.py b/app/mcp_stdio.py
index 39f724941..3e045d52c 100644
--- a/app/mcp_stdio.py
+++ b/app/mcp_stdio.py
@@ -1749,21 +1749,25 @@ async def get_worker_info(name: str) -> str:
         result["cache_status"] = _cache_pill(result)  # 🔥 hot Nm / 🟡 warm / 🧊 cold
     return json.dumps(result, ensure_ascii=False)
 
 
 @mcp.tool()
-async def task_create(title: str, project: str, price: int = 0,
+async def task_create(title: str, project: str = "", price: int = 0,
                       description: str = "", assignee: str = "",
                       status: str = "new", priority: int = 2) -> str:
     """Create a new task. Returns task number and details.
+    project: registered project scope or id; omitted uses the caller's mapped scope.
     price in exact currency units (e.g. 20000 = 20 000). 0 is valid (no price).
     priority: 0=critical, 1=high, 2=medium (default), 3=low."""
-    result = await _api("POST", "/api/tm/tasks", json={
-        "title": title, "project": project, "price": price,
+    payload = {
+        "title": title, "price": price,
         "description": description, "assignee": assignee, "status": status,
         "scope": SCOPE, "priority": priority,
-    })
+    }
+    if project:
+        payload["project"] = project
+    result = await _api("POST", "/api/tm/tasks", json=payload)
     if isinstance(result, dict) and result.get("error"):
         return f"Error: {result['error']}"
     if isinstance(result, dict):
         result = dict(result)
         result.setdefault("description", description)
### 83eda0e05 #241: #241: tag the owner only when the turn calls notify_user

diff --git a/app/mcp_stdio.py b/app/mcp_stdio.py
index 3e045d52c..f9c71f0a9 100644
--- a/app/mcp_stdio.py
+++ b/app/mcp_stdio.py
@@ -1245,10 +1245,33 @@ async def send_chart(kind: str, title: str, data: dict, caption: str = "") -> st
         exc.details = {**exc.details, "chart_path": path}
         raise
     return f"{sent} | chart: {path}"
 
 
+@mcp.tool()
+async def notify_user(reason: str) -> str:
+    """Дёрнуть юзера тегом в Telegram на границе ЭТОГО хода. Только для оркестраторов.
+
+    Молчание — нормальный режим: без этого вызова тега не будет, и это не забывчивость.
+    Зови, когда юзер обязан узнать СЕЙЧАС: нужно его РЕШЕНИЕ (развилка, которую ты не
+    вправе закрыть сам); ВЫВОД РАЗВЕРНУЛСЯ (сделали не то, о чём договаривались, или
+    отозвано ранее сказанное); ИНЦИДЕНТ на живых системах; РЕЗУЛЬТАТ с числом, меняющий
+    план. НЕ зови на блокеры ревью, мержи, статусы, промежуточные шаги, «воркер
+    начал/закончил» — на это он смотреть не хочет.
+
+    `reason` — одна короткая фраза, ЗАЧЕМ дёрнули; она уедет юзеру вместе с тегом.
+    Тег ставится один раз за ход независимо от числа вызовов.
+    """
+    reason = reason.strip()
+    if not reason:
+        return "notify_user needs a non-empty reason — one short phrase saying WHY."
+    # Тул сознательно ничего не делает: сигналом служит САМА строка вызова в журнале,
+    # которую пишет рантайм, а читает `stream_logs`. Никакого нового контракта
+    # MCP↔route — значит правка доезжает без окна «новый MCP против старого роута».
+    return f"User will be tagged at the end of this turn: {reason}"
+
+
 @mcp.tool()
 async def update_progress(percent: int, status: str) -> str:
     """Update task progress. percent: 0-100, status: short description of current step."""
     result = await _api("POST", f"/api/sessions/{WORKER_NAME}/progress", json={
         "percent": percent, "status": status, "scope": SCOPE,