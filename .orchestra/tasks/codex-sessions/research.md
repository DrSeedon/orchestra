# Research — MCP codex_review persistent sessions + full-cycle "second opinion"

## Question
Two changes:
1. Make the MCP `codex_review` tool (`app/mcp_stdio.py:671-742`) support **persistent Codex
   sessions** (resume/debate), mirroring what the `codex-debate` Bash skill already does.
   Add a `resume: bool` param; store the session UUID per worker; clean up on merge/kill.
2. Add "adversarial second opinion" rules to `roles/full-cycle.md` (Phase 1 research
   verification, Phase 2 disagreement → debate round, plus a general rule).

Baseline: the MCP tool today runs Codex **ephemeral** (`--ephemeral`), so every call is a
fresh throwaway session — no resume, no debate. The Bash skill already does persistent
sessions via `codex exec resume <UUID>` + `codex_sessions.json`. Goal: bring the MCP tool
to parity for the Bash-less (Codex-backend) worker path.

## Hypotheses considered
- **H1 (leading):** `codex exec review` can persist a session (drop `--ephemeral`, add
  `--json`), and that session is resumable via `codex exec resume <UUID>`. UUID extracted
  from JSONL `thread.started.thread_id`. → **CONFIRMED by measurement.**
- **H2 (ruled out):** Session UUID must be captured by the MCP Python code and stored in DB.
  → **REFUTED by architecture**: the bg job runs the codex command in a *detached* shell
  subprocess and `codex_review` returns immediately (before codex finishes). Python cannot
  capture the post-run UUID. Extraction+persist must happen *inside the shell command*
  (jq on JSONL), writing to a file. File-based storage (`codex_sessions.json` in task dir)
  is therefore the natural fit — same as the skill. DB would need a job-completion callback.
- **H3 (ruled out):** review subcommand doesn't support `--json`/resume, so persistent
  review is impossible. → **REFUTED**: `codex exec review --help` shows both `--json` and
  `-o`, and resume works on a review-started thread (measured).

## Findings

### F1 — `codex exec review` supports `--json` + `-o`, no `--ephemeral` needed
CONFIRMED — primary source (`codex exec review --help`):
```
--ephemeral   Run without persisting session files to disk
--json        Print events to stdout as JSONL
-o, --output-last-message <FILE>
```
Dropping `--ephemeral` persists the session; adding `--json` exposes the thread id on stdout.

### F2 — UUID is in JSONL `thread.started.thread_id` (stdout) and `session_meta.payload.id` (rollout file)
CONFIRMED — measurement. Ran a real review in `/tmp/codextest` (git repo, uncommitted diff):
```
"type":"thread.started"
"thread_id":"019f479e-5a51-7311-82ca-6c6665c994b8"
```
Rollout file `~/.codex/sessions/2026/.../rollout-*.jsonl` first line:
`{"type":"session_meta","payload":{"id":"019f3c33-...","cwd":"...","source":"exec",...}}`
The skill extracts both (`thread.started.thread_id` primary, `session_meta.payload.id`
fallback). Same extraction applies here.

### F3 — resume works on a review-started session
CONFIRMED — measurement. `codex exec resume 019f479e-... "..."` returned the SAME
`thread_id`, EXIT 0, and continued the thread across two follow-up turns. The session thread
is continuous. (Note: the `review` subcommand's internal diff context does not fully carry
into a resumed free-form prompt — the resumed model said "I can't determine that from the
review output shown." This is fine: debate re-review prompts instruct Codex to re-inspect
the diff via shell each round, exactly as the skill does. The resume gives *conversation
continuity*, not a guarantee the diff stays in context.)

### F4 — resume does NOT accept `-s`/`--sandbox`
CONFIRMED — skill's own note (line 244) + CLI: `resume` inherits sandbox from the original
session. The resume command must NOT pass `-s`. The initial `exec` (non-review) uses
`-s workspace-write`; `review` sets its own sandbox. So: set sandbox only on the *first*
call, never on resume.

### F5 — storage: file in task dir, written by the shell command
CONFIRMED by architecture (H2). `_run_exec` (`app/bg_jobs.py:185`) runs `config["command"]`
via shell, detached; `codex_review` MCP returns a "started" string immediately. Therefore:
- **Persist UUID inside the shell command** (append jq step after codex, like skill lines
  192-203), writing `<cwd>/<sessions_json>`.
- **Read UUID inside the MCP Python** before launching (to decide new-vs-resume and build
  the resume command). File read is synchronous and safe.
- `jq` is available (`/usr/bin/jq`, 1.8.1).

Storage key: the MCP tool has no reliable task_id (session task_id is optional/absent). Use
a **per-worker file** keyed by a slug derived from `output` filename, mirroring the skill's
`codex_sessions.json` structure. Simplest: store at `<cwd>/docs/tasks/codex_sessions.json`
OR alongside the output file. Recommendation (see plan): store `codex_sessions.json` next to
the output file's directory, slug = output filename stem. One slug = one session = one output
file, matching the skill's model exactly.

### F6 — cleanup on merge/kill
The `codex_sessions.json` lives in the worktree. On `kill_worker` the worktree is archived;
on `merge_worker` the file (under `docs/tasks/`) merges into main harmlessly. The Codex
rollout files in `~/.codex/sessions/` are Codex-managed, machine-local, and harmless to
leave. **Cleanup = delete the worker's `codex_sessions.json`** so a re-spawned worker with
the same name doesn't resume a stale/foreign thread. This is a best-effort file delete in
the kill/merge path; a stale UUID on resume is already handled (codex errors → fall back to
new session, per skill Error Handling "Resume with stale UUID").

## Affected files
- `app/mcp_stdio.py` — `codex_review` tool (add `resume`, session read/persist, non-ephemeral
  review command with `--json` + jq UUID capture). `kill_worker`/`merge_worker` — best-effort
  session-file cleanup (optional; low value since worktree is discarded — see plan for
  cost/benefit).
- `pipelines/default/prompts/roles/full-cycle.md` — Phase 1 second-opinion, Phase 2 debate-on-
  disagreement, general "adversarial not rubber stamp" rule.

## Risks / edge cases
- **Stale UUID on resume** → codex errors. Must fall back to fresh session (drop UUID, retry
  as new) — don't hard-fail. (Skill: delete from json, start fresh.)
- **jq missing on VPS** → UUID capture silently fails, resume never available. Guard: if the
  sessions file has no UUID, always start fresh (graceful degradation, no crash).
- **Quoting**: review mode has no prompt (uses `--uncommitted`), so no heredoc needed for the
  UUID-capture append. exec/resume modes already use a heredoc prompt file — keep that.
- **Concurrency**: one worker = one codex_review at a time (tool already enforces "do not
  start another until this reports back"). No lock needed on the json file.
- **Do NOT touch**: proxy (`_CODEX_BIN` wrapper with HTTPS_PROXY=12343), the 600s MCP timeout.

## Confidence
- F1 CONFIRMED (primary: CLI help)
- F2 CONFIRMED (measured JSONL + rollout file)
- F3 CONFIRMED (measured resume, same thread id, EXIT 0)
- F4 CONFIRMED (skill note + CLI)
- F5 CONFIRMED (architecture: detached bg subprocess ⇒ shell-side persist)
- F6 LIKELY (cleanup is best-effort; worktree discard already handles most of it)

## Sources
1. `codex exec review --help` — flags `--ephemeral`, `--json`, `-o` (fetched this session)
2. `codex exec resume --help` — SESSION_ID arg, no `-s` (fetched this session)
3. Measurement `/tmp/codextest` — review `--json` thread.started + resume continuity (this session)
4. `pipelines/default/prompts/skills/codex-debate.md` — session json schema, jq extraction,
   resume mechanics, error handling (read this session)
5. `app/bg_jobs.py:80-90,183-186` — `run` job = detached shell subprocess (read this session)
6. `app/db.py:241-257` — kv table + helpers (considered, not used — file storage chosen)
