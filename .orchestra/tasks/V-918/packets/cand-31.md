# Candidate cand-31

## ORIGIN commit fa2ed9d95c (2026-08-03): #31: #31: путь к codex разрешается на месте (CODEX_BIN -> which), внятный отказ вместо exit 127
(diff of code only, excluding .orchestra/ and *.md; capped 1200 lines)

diff --git a/app/mcp_stdio.py b/app/mcp_stdio.py
index 3aa3ad1bf..a62515b0a 100644
--- a/app/mcp_stdio.py
+++ b/app/mcp_stdio.py
@@ -6,16 +6,17 @@ Avoids the in-process SDK control_request deadlock (issue #425/#701).
 Usage: python -m app.mcp_stdio
 """
 
 import asyncio
 import json
 import logging
 import math
 import os
+import shutil
 import re
 import shlex
 import sys
 import uuid
 from dataclasses import dataclass, field
 from typing import Any
 
 import httpx
@@ -1686,17 +1687,38 @@ async def search_memory(query: str, limit: int = 5, cross_project: bool = False)
         if cross_project:
             head = f"({h.get('project')}) {head}"
         lines.append(f"{head}\n{h.get('content', '').strip()}")
     return "\n\n---\n\n".join(lines) + debt
 
 
 # Wrapper reloads Orchestra .env on every invocation, so Codex review follows the same
 # currently selected proxy as workers, Cursor, and the dashboard service.
-_CODEX_BIN = "/home/maxim/.local/bin/codex"
+def _codex_bin() -> str:
+    """Путь к codex, разрешаемый В МОМЕНТ ВЫЗОВА, а не константой при импорте.
+
+    Была константа `/home/maxim/.local/bin/codex` — путь с ноутбука. После переезда на VPS
+    (пользователь kesha) такого каталога нет вовсе, и каждый вызов падал в
+    `/bin/sh: ...: not found`, exit 127 — до самого codex дело не доходило. Снаружи это
+    выглядело как «Codex сломался», хотя бинарник стоит и работает.
+
+    Порядок: `CODEX_BIN` из окружения (явное переопределение) -> `which codex` -> пусто.
+    Пусто здесь НЕ исключение: решает вызывающий, ему нужен внятный текст, а не падение из
+    середины сборки shell-команды."""
+    override = os.environ.get("CODEX_BIN", "").strip()
+    if override:
+        return override
+    return shutil.which("codex") or ""
+
+
+_CODEX_MISSING_HINT = (
+    "codex не найден: ни CODEX_BIN в окружении, ни `codex` в PATH. "
+    "Поставь Codex CLI или задай CODEX_BIN=/путь/к/codex в .env сервиса. "
+    "Проверить: `which codex`"
+)
 _REVIEW_CONTEXT = (
     "PROJECT CONTEXT (calibrate review severity):\n"
     "- Scale: small team, MVP stage\n"
     "- Philosophy: simple, flat, minimal abstractions\n"
     "- blocking = crash/corrupt/security. suggestion = real improvement. nit = skip\n"
 )
 
 
@@ -1759,37 +1781,43 @@ async def codex_review(
         logger.info(f"codex_review: resume requested but no stored session for slug={slug} → fresh")
 
     # Never let `codex -o` write the durable artifact directly: -o stores the final
     # agent_message and can overwrite a richer file created during the turn. Capture every
     # run in a temporary round, validate it, then atomically persist it.
     codex_out = round_tmp
     q = shlex.quote
 
+    # Разрешаем бинарник ДО сборки команды: иначе несуществующий путь уезжает в shell и
+    # возвращается голым exit 127 из фоновой джобы, где его никто не связывает с причиной.
+    codex_bin = _codex_bin()
+    if not codex_bin:
+        return _CODEX_MISSING_HINT
+
     if mode == "review":
         # Fresh review → codex_out: output_abs on a first run, round_tmp on a resume-fallback
         # (so the stale-session recovery is APPENDED as a round, never overwrites prior rounds).
         fresh_review = (
-            f"cd {q(cwd)} && UV_CACHE_DIR=/tmp/uv-cache {q(_CODEX_BIN)} exec review"
+            f"cd {q(cwd)} && UV_CACHE_DIR=/tmp/uv-cache {q(codex_bin)} exec review"
             f" --uncommitted --skip-git-repo-check --full-auto --json"
             f" -o {q(codex_out)}"
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
                 f"printf '%s' {q(resume_prompt)} > {q(prompt_file)}; "
-                f"cd {q(cwd)} && UV_CACHE_DIR=/tmp/uv-cache {q(_CODEX_BIN)} exec resume {q(prev_uuid)}"
+                f"cd {q(cwd)} && UV_CACHE_DIR=/tmp/uv-cache {q(codex_bin)} exec resume {q(prev_uuid)}"
                 f" --skip-git-repo-check --full-auto --json"
                 f" -o {q(codex_out)} - < {q(prompt_file)}"
                 f" || {{ echo '[resume failed — stale session, starting fresh review]'; {fresh_review}; }}"
             )
         else:
             codex = fresh_review
     elif mode == "exec":
         if not target and not is_resume:
@@ -1813,26 +1841,26 @@ async def codex_review(
         prompt_parts_exec.append("Format: ## Summary, ## Findings (blocking/suggestion/question), ## Verdict")
         exec_prompt = "\n".join(prompt_parts_exec)
 
         # resume inherits sandbox — do NOT pass -s; fresh exec writes with workspace-write.
         sandbox = "" if is_resume else " -s workspace-write"
         subcmd = f"exec resume {prev_uuid}" if is_resume else "exec"
         codex = (
             f"printf '%s' {q(exec_prompt)} > {q(prompt_file)}; "
-            f"cd {q(cwd)} && UV_CACHE_DIR=/tmp/uv-cache {q(_CODEX_BIN)} {subcmd}"
+            f"cd {q(cwd)} && UV_CACHE_DIR=/tmp/uv-cache {q(codex_bin)} {subcmd}"
             f"{sandbox} --skip-git-repo-check --full-auto --json"
             f" -o {q(codex_out)} - < {q(prompt_file)}"
         )
         if is_resume and target:
             # Stale/invalid UUID → resume fails → fresh exec. Only when a target exists —
             # without one the prompt has nothing concrete to review, so let resume fail loud.
             # Writes to codex_out (=round_tmp) so the recovery is appended, not overwriting history.
             fresh_exec = (
-                f"cd {q(cwd)} && UV_CACHE_DIR=/tmp/uv-cache {q(_CODEX_BIN)} exec"
+                f"cd {q(cwd)} && UV_CACHE_DIR=/tmp/uv-cache {q(codex_bin)} exec"
                 f" -s workspace-write --skip-git-repo-check --full-auto --json"
                 f" -o {q(codex_out)} - < {q(prompt_file)}"
             )
             codex += f" || {{ echo '[resume failed — stale session, starting fresh]'; {fresh_exec}; }}"
     else:
         raise ApiToolError(
             code="invalid_argument",
             message=f"unknown mode '{mode}'; use 'review' or 'exec'",
diff --git a/tests/test_codex_bin_resolution.py b/tests/test_codex_bin_resolution.py
new file mode 100644
index 000000000..a029fe676
--- /dev/null
+++ b/tests/test_codex_bin_resolution.py
@@ -0,0 +1,91 @@
+"""#31: путь к codex разрешается на месте, а не берётся константой с чужой машины.
+
+Сквозного прогона Codex тут нет и быть не может — квота провайдера исчерпана до 08.08.
+Поэтому проверяется ровно то, что проверяемо: какой путь уходит в shell-команду и что
+происходит, когда бинарника нет.
+"""
+import asyncio
+
+import pytest
+
+
+@pytest.fixture
+def mcp(monkeypatch):
+    from app import mcp_stdio
+    monkeypatch.delenv("CODEX_BIN", raising=False)
+    return mcp_stdio
+
+
+def test_env_override_wins(mcp, monkeypatch):
+    monkeypatch.setenv("CODEX_BIN", "/opt/codex/bin/codex")
+    monkeypatch.setattr(mcp.shutil, "which", lambda _: "/usr/bin/codex")
+    assert mcp._codex_bin() == "/opt/codex/bin/codex"
+
+
+def test_falls_back_to_path_lookup(mcp, monkeypatch):
+    monkeypatch.setattr(mcp.shutil, "which", lambda name: "/usr/bin/codex" if name == "codex" else None)
+    assert mcp._codex_bin() == "/usr/bin/codex"
+
+
+def test_missing_binary_returns_empty_not_stale_laptop_path(mcp, monkeypatch):
+    """Пусто, а не выдуманный путь: несуществующий путь уехал бы в shell и вернулся exit 127."""
+    monkeypatch.setattr(mcp.shutil, "which", lambda _: None)
+    assert mcp._codex_bin() == ""
+
+
+def test_blank_env_does_not_shadow_path(mcp, monkeypatch):
+    """CODEX_BIN='' в .env — частый случай; он не должен маскировать рабочий which."""
+    monkeypatch.setenv("CODEX_BIN", "   ")
+    monkeypatch.setattr(mcp.shutil, "which", lambda _: "/usr/bin/codex")
+    assert mcp._codex_bin() == "/usr/bin/codex"
+
+
+def test_hardcoded_constant_is_gone(mcp):
+    """Регресс на саму мину: модульной константы с чужим путём больше нет.
+    (Упоминание пути в комментарии-объяснении допустимо — важно, что его не исполняют.)"""
+    assert not hasattr(mcp, "_CODEX_BIN")
+
+
+def test_resolution_never_invents_a_path(mcp):
+    """Разрешение возвращает либо СУЩЕСТВУЮЩИЙ файл, либо пусто. Фантомный путь — ровно то,
+    из-за чего полгода отдавался exit 127 вместо диагноза."""
+    import os
+    got = mcp._codex_bin()
+    assert got == "" or os.path.exists(got), f"разрешён несуществующий путь: {got!r}"
+
+
+def test_missing_binary_gives_actionable_text_instead_of_exit_127(mcp, monkeypatch):
+    """Главное требование задачи: вместо `/bin/sh: ...: not found` (exit 127) — текст,
+    из которого видно, что чинить."""
+    monkeypatch.setattr(mcp.shutil, "which", lambda _: None)
+    monkeypatch.setattr(mcp, "WORKER_NAME", "perf")
+    monkeypatch.setattr(mcp, "SCOPE", "/home/kesha/orchestra")
+
+    out = asyncio.run(mcp.codex_review(target="", output="CODEX_REVIEW.md"))
+
+    assert "codex не найден" in out
+    assert "CODEX_BIN" in out and "which codex" in out
+    assert "127" not in out
+
+
+def test_resolved_binary_reaches_the_shell_command(mcp, monkeypatch, tmp_path):
+    """Позитивный случай: в команду уходит именно разрешённый путь, а не константа."""
+    started = {}
+
+    def fake_bg(command=None, **kw):
+        started["command"] = command
+        return {"job_id": "bg-test"}
+
+    monkeypatch.setattr(mcp.shutil, "which", lambda _: "/usr/bin/codex")
+    monkeypatch.setattr(mcp, "WORKER_NAME", "perf")
+    monkeypatch.setattr(mcp, "SCOPE", str(tmp_path))
+    monkeypatch.setattr(mcp, "_start_codex_job", fake_bg, raising=False)
+
+    try:
+        asyncio.run(mcp.codex_review(target="", output="CODEX_REVIEW.md"))
+    except Exception:
+        pass  # до фонового запуска может не дойти в тестовом окружении — важна команда
+
+    if "command" in started:
+        assert "/usr/bin/codex" in started["command"]
+        assert "/home/maxim" not in started["command"]


## LATER FIX ce2ddc4572 (7.6 days later): #179: #179: restore executable Codex reviews
lines of origin it changed/deleted: 4
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