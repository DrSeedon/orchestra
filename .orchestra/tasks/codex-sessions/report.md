# Report — MCP codex_review persistent sessions + full-cycle second-opinion

## What shipped

### 1. `codex_review` MCP tool — persistent Codex sessions (resume/debate)
`app/mcp_stdio.py`. The tool ran Codex ephemeral (throwaway each call); now it persists the
Codex thread and can resume it for multi-round debate.

- **New `resume: bool` param.** `resume=True` continues the previous Codex session keyed by the
  `output` filename. Falls back to a fresh session if none stored.
- **Session storage** — `codex_sessions.json` next to the output file (slug = output stem),
  same schema/model as the `codex-debate` Bash skill. Written **shell-side** (jq on the JSONL
  `thread.started.thread_id`) because the bg `run` job is a detached subprocess and the tool
  returns before Codex finishes — Python can't capture the post-run UUID (see research H2).
- **Non-ephemeral review** — dropped `--ephemeral`, added `--json` so the thread id is on stdout.
  Resume works on a `review`-started thread (measured).
- **History-preserving resume** — resume writes its last message to a temp `*.round` file, which
  is appended as a `## Round (ts)` section to the output file (never overwrites prior rounds).
- **Stale-UUID recovery** — if `resume` fails (session gone/moved machine), falls back to a
  fresh review (review mode always; exec mode only when a `target` exists — else fail loud).
  The fallback also appends (writes to the round temp), preserving prior history.
- **Exit-code integrity** — dash has no PIPESTATUS; codex's real exit code is captured to a temp
  file and re-exited, so bg-job success/failure reporting reflects the review, not the jq/persist
  chain. jq missing → graceful degrade (no session saved, review still succeeds).
- **Git hygiene** — `codex_sessions.json` and `*.round` are added to the worktree's
  `info/exclude` (a) at spawn via `create_worktree` and (b) inline at tool-run time (covers
  already-existing long-lived worktrees) so they never dirty the tree / block merge_worker.

### 2. full-cycle.md — adversarial second-opinion rules
`pipelines/default/prompts/roles/full-cycle.md`:
- **Phase 1** — after findings, run a Codex debate to challenge key research conclusions
  ("second opinion on my research conclusions"); fold the outcome into research.md.
- **Phase 2** — on Codex disagreement, RESUME the session and debate to consensus, don't just
  record-and-move-on; escalate only after 5+ rounds / deletion / architecture demands.
- **Pipeline rule** — "Codex = adversarial second opinion, NOT a rubber stamp": verify blocking
  findings via code before accepting, never dismiss silently, debate or escalate.

## Files
- `app/mcp_stdio.py` — codex_review rewrite + 3 helpers (`_codex_sessions_path`, `_codex_slug`,
  `_read_codex_uuid`, `_codex_persist_snippet`) (+~150/-20)
- `app/workspace.py` — generalized `_exclude_claude_dir` → `_WORKTREE_EXCLUDES` (+.claude/,
  codex_sessions.json, *.round) (+8/-6)
- `pipelines/default/prompts/roles/full-cycle.md` — 3 rule additions (+~20)
- `docs/tasks/codex-sessions/` — research.md, report.md, codex-review-impl.md

## Tests
- `tests/test_mcp_stdio.py` — 12/12 pass
- `tests/test_workspace.py` — 35/36 pass (1 pre-existing failure `test_rollback_on_copy_failure`,
  fails on clean tree without my changes — env/mock issue, not a regression)
- **End-to-end measured** (real Codex runs in /tmp): new review persists UUID; resume continues
  same thread + appends round + bumps turns; stale-UUID fallback recovers + preserves history +
  captures new UUID; jq-missing degrades to exit 0; codex-fail propagates non-zero; git excludes
  ignore both artifacts (clean status, idempotent).

## Codex review (6 rounds — adversarial, all applied or reasoned)
1. `-o` overwrites history on resume → **fixed** (round temp + append)
2. exit status masked by persist chain → **fixed** (capture rc, re-exit)
3. jq parse-error on mixed non-JSON stdout → **fixed** (`jq -R 'fromjson?'`)
4. no stale-UUID fallback → **fixed** (`|| fresh` recovery)
5. exec fallback reviews no target → **fixed** (keep target in prompt; guard fallback on target)
6. metadata dirties existing worktrees → **fixed** (inline info/exclude at tool-run time)

## Known / intentional
- **resume=True with no stored metadata** → degrades to a fresh review written to `output_abs`
  (documented in the tool docstring). If an orphaned output file exists it is overwritten — but
  with no live session there is no debate history to preserve. Intentional, low-severity.
- **Codex rollout files** in `~/.codex/sessions/` are Codex-managed, machine-local, left as-is.
- Did NOT touch: proxy wrapper (`_CODEX_BIN` HTTPS_PROXY=12343), the 600s MCP timeout (per task).

## Breaking
None. `resume` defaults to False → existing callers unchanged (except review is now non-ephemeral
+ persists a session file, which is git-ignored).

## Adversarial self-review
- **Slug collision**: two reviews with the same output filename share a session — intended (that's
  the debate key). Different outputs = different sessions. OK.
- **Shell-metachar in slug/output**: `output` is worker-controlled/trusted and always a plain
  filename; single-quoted in jq args. Consistent with pre-existing `output_abs` interpolation.
- **Concurrency**: tool already enforces one codex_review per worker at a time → no json race.
