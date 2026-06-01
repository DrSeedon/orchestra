# #43 — Codex Review Stability: Research & Recommendation

## Current Architecture

```
Worker (Claude CLI in worktree) 
  → calls codex_review() MCP tool (mcp_stdio.py:623)
    → resolves worker's worktree_path via GET /api/sessions/{name}
    → constructs codex CLI command with cd {worktree_path}
    → POST /api/bg/jobs {type: "run", command: "cd /worktree && codex exec ..."}
      → bg_jobs.py _run_exec(): subprocess_shell, reads stdout, 300s timeout
        → on success: _trigger() → session.send() → worker gets notification
        → on timeout: _expire_notify() → session.send() → worker gets timeout error
        → on exception: bg_fail_job() → NO NOTIFICATION (silent failure)
```

## Problems Identified

### P1: Worker sees a black box
Worker calls `codex_review()`, gets "started bg job X, wait". No progress, no streaming.
If anything goes wrong, worker waits idle for 5 minutes (timeout). This wastes a full
turn slot — the worker is IDLE but mentally "waiting", producing no output.

### P2: bg_create exception path = silent failure
`_run_exec` catches generic `Exception` and calls `bg_fail_job(job_id, str(e))` —
this updates DB status to "failed" but **never notifies the worker**. Only timeout
and success paths notify. The `_expire_notify` fix from #41 covers timeout, not crash.

### P3: Worktree path resolution is indirect
`codex_review` does an HTTP roundtrip (`GET /api/sessions/{name}`) to find the worker's
`worktree_path`, then embeds it as `cd {cwd}` in the shell command. This works but is
fragile — the session API returns data for the MCP server's `WORKER_NAME`, and the
path comes back correctly. But `-o {output_abs}` writes relative to wherever codex
decides its workspace root is, and `codex exec review` uses git context, so `cd` is
essential.

### P4: Output file goes to right place but review mode doesn't use it
Current `review` mode command:
```
cd {cwd} && codex exec review --uncommitted --skip-git-repo-check --full-auto --ephemeral -o {output_abs}
```
The `-o` flag writes the "last message" (final text output) to the file. This works.
But the worker is told "read {output}" — the worker must then do a Read tool call on
that file. Total interaction: 1 MCP call + wait 1-5 min + 1 Read = minimum 3 turns of
overhead.

### P5: Opus hallucination ("I already ran codex")
Because the worker calls an MCP tool that returns immediately, Opus 4.8 sometimes
confuses "I called the tool" with "the tool produced results". This is a prompt/UX
issue — the current return message tries to address it but Opus still hallucinates.

## Architecture Options

### Option A: Synchronous Bash (worker runs codex directly)

The worker uses its Bash tool to run codex:
```bash
codex exec review --uncommitted --full-auto --ephemeral --skip-git-repo-check -o review.md 2>&1
```

**How it works:** Worker's Bash runs in the worktree (Claude CLI cwd = worktree_path).
No bg_create, no MCP roundtrip, no notification machinery. Codex runs, stdout streams
to the Bash output, `-o review.md` writes the file in the worktree. Worker reads it.

**Pros:**
- Zero infrastructure changes. No MCP tool, no bg_jobs, no notification issues
- Worker sees stdout in real-time (Bash tool captures it)
- File is written in the correct worktree (Bash cwd = worktree)
- No hallucination risk — worker sees codex output directly
- Simplest possible architecture

**Cons:**
- **Bash timeout**: Claude Code Bash tool has a 120s default, 600s max timeout.
  Codex review takes 60-300s. If it exceeds Bash timeout, the output is lost
- **Turn blocks**: Worker's entire turn is blocked while codex runs. Can't do anything
  else. Not a real problem — worker was going to wait anyway
- **No dashboard visibility**: No bg_job record in dashboard. Just a Bash call in logs

**Verdict:** Works IF codex finishes within Bash timeout. For reviews (typically 60-120s),
this is reliable. For exec mode with complex tasks (could be 5+ min), risky.

### Option B: bg_create with streaming to worker logs

Keep bg_create(type="run") but:
1. Stream codex `--json` JSONL output to worker logs in real-time
2. Notify worker on ALL exit paths (success, timeout, AND exception)
3. Include full output in notification

**How it works:** Same as current, but `_run_exec` logs each JSONL line to the worker's
session log stream. Dashboard shows codex progress. On completion, worker gets notified
with the output.

**Pros:**
- Dashboard visibility (codex events appear in worker's log)
- Handles long-running codex (no Bash timeout issue)
- Worker gets notification asynchronously — can be woken from idle
- Existing infra, just needs bug fixes

**Cons:**
- Complex: bg_jobs → session.send → wake worker → worker reads file
  Multiple points of failure (the very problem we're solving)
- Session log streaming requires piping JSONL to session.log() from bg_jobs,
  which crosses abstraction boundaries (bg_jobs shouldn't know about session logs)
- The worker still can't see progress without reading logs — it's a black box
  from the worker's perspective (only dashboard users see it)
- Exception path still needs fixing (P2)
- codex `--json` output is verbose JSONL — parsing it server-side adds code

**Verdict:** Fixes bugs but doesn't simplify. More moving parts to maintain.

### Option C: codex_review as synchronous MCP tool (blocking call)

Change `codex_review` MCP tool to run codex synchronously (not via bg_create).
The MCP tool blocks until codex finishes, then returns the review content directly.

**How it works:** `codex_review` in mcp_stdio.py runs `asyncio.create_subprocess_shell`
directly, awaits completion, reads the `-o` file, returns its content as the tool result.

**Pros:**
- Worker gets result directly from the MCP tool call — no notification, no waiting
- No bg_jobs involvement, no notification failures
- File written in correct worktree (same cd approach)
- No hallucination — result is in the tool response

**Cons:**
- **MCP tool timeout**: Claude SDK kills MCP tools that take too long (no documented
  timeout, but empirically ~60-120s). Codex can exceed this
- **MCP server blocks**: While codex runs, the MCP server (stdio, single-threaded)
  can't serve other tool calls from the worker. This freezes all MCP tools for the
  worker for the duration
- If codex hangs, the entire MCP connection may die, requiring session recovery

**Verdict:** Elegant but fragile. MCP tool timeout is unpredictable and not configurable.

### Option D: Worker Bash + timeout guard (RECOMMENDED)

Hybrid of Option A with a safety net:

```bash
timeout 240 codex exec review --uncommitted --full-auto --ephemeral \
  --skip-git-repo-check -o review.md 2>&1; echo "EXIT:$?"
```

The worker calls codex via Bash with an explicit `timeout` command. If codex
exceeds 240s, `timeout` kills it and the worker sees a non-zero exit code.

For the prompt side: update the `codex-review` section in worker prompts to say
"run codex via Bash" with the exact command. Remove the `codex_review` MCP tool
entirely (or keep it as a deprecated wrapper that tells the worker to use Bash).

**How it works:**
1. Worker's Bash tool runs in the worktree → correct cwd
2. `timeout 240` prevents infinite hangs
3. stdout shows codex progress in real-time
4. `-o review.md` writes output file in the worktree
5. Worker reads the file after Bash returns
6. No bg_jobs, no notification machinery, no MCP roundtrip

**Pros:**
- Simplest possible solution — just a Bash command
- All 4 problems solved:
  - P1 (black box): Worker sees stdout
  - P2 (silent failure): Bash returns exit code
  - P3 (worktree path): Bash cwd IS the worktree
  - P4 (output location): File in worktree
  - P5 (hallucination): Direct output, no async
- Zero code changes to app/ (only prompt changes)
- Worker has full control — can retry, adjust flags, handle errors

**Cons:**
- Bash tool timeout: Claude Code's Bash tool has 120s default timeout.
  **Must pass `timeout: 300000` (5 min)** to the Bash tool call — this is
  supported by the Bash tool's `timeout` parameter
- Worker turn is blocked during codex run (2-5 min) — acceptable
- No dashboard-visible bg_job record — just a Bash log entry
- Prompt-driven: workers must follow instructions correctly.
  But they already must follow codex_review MCP instructions correctly

**Verdict:** Best option. Zero infrastructure code, solves all problems.

## Worktree Path Problem

**Root cause:** The `codex_review` MCP tool runs inside the MCP server process, whose
cwd is the main repo (not the worker's worktree). It resolves the worktree path via
API and embeds `cd {path}` in the command.

**With Option D (Bash):** Problem disappears. The worker's Bash tool already runs in
the worktree. `codex exec` picks up the git context from cwd. `-o review.md` writes
to the worktree. No path resolution needed.

## Codex CLI Key Findings

- **Version:** 0.124.0 (OpenAI Codex CLI)
- **`-C, --cd <DIR>`:** Sets working directory. Redundant if we `cd` first, but cleaner
- **`--json`:** JSONL streaming to stdout — available for both `exec` and `exec review`
- **`--ephemeral`:** No session persistence — good for one-shot reviews
- **`--full-auto`:** No approval prompts — required for non-interactive use
- **`-o, --output-last-message <FILE>`:** Writes the agent's final text to a file
- **`exec review --uncommitted`:** Reviews staged + unstaged + untracked changes
- **`exec review --base <BRANCH>`:** Reviews changes vs a base branch
- **`mcp-server`:** Codex can run as an MCP server (stdio) — interesting for future
  integration but overkill for reviews
- **Typical runtime:** review mode 60-120s, exec mode 60-300s

## Recommendation

**Option D: Worker Bash + timeout guard.**

### Migration Plan (minimal changes)

1. **Update worker prompt** (codex-review section): Replace "call codex_review() MCP tool"
   with exact Bash commands:
   ```
   ## Codex review (via Bash)
   ### Review mode (git diff)
   timeout 240 /home/maxim/.npm-global/bin/codex exec review \
     --uncommitted --full-auto --ephemeral --skip-git-repo-check \
     -o CODEX_REVIEW.md 2>&1
   
   ### Exec mode (review a specific file)
   timeout 240 /home/maxim/.npm-global/bin/codex exec \
     -s workspace-write --full-auto --ephemeral --skip-git-repo-check \
     -o CODEX_REVIEW.md \
     "Review the file: {path}. Write findings to CODEX_REVIEW.md. Format: ## Summary, ## Findings, ## Verdict" 2>&1
   ```

2. **Deprecate codex_review MCP tool**: Either remove it or make it return
   "DEPRECATED: use Bash instead. Command: ..." to guide workers.

3. **Keep bg_create path as fallback**: Don't delete bg_jobs codex code yet. Some
   edge cases (Codex backend workers that lack Bash tool) might need it.

4. **Fix P2 regardless**: In `_run_exec`, add worker notification on the exception
   path (not just timeout). This is a 3-line fix that helps all bg_create users:
   ```python
   except Exception as e:
       bg_fail_job(job_id, str(e)[:500])
       await self._expire_notify(job_id, message, target_name, target_scope,
                                  timeout, "".join(output_buf))
   ```

### What NOT to do
- Don't add streaming/JSONL parsing infrastructure — over-engineering for the problem
- Don't make codex_review synchronous MCP — MCP timeout is unpredictable
- Don't add a new MCP tool for "codex status" — unnecessary with Bash approach
- Don't add codex as a persistent MCP server — overkill, different auth model (OpenAI)

### Risk Assessment
- **Low risk:** Prompt change only. No app/ code required for the primary fix
- **Fallback:** If Bash approach fails for some workers, bg_create path still exists
- **Testing:** Run one review via Bash in a worker to validate timing
