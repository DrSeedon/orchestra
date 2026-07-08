# Report — codex_review CWD fix

## What
`codex_review` ran `codex` CLI in the MAIN repo instead of the calling worker's worktree.

## Root cause
`AgentSession.to_dict()` omitted `worktree_path` and `cwd`. `GET /api/sessions/{name}`
returns `to_dict()` for **loaded** sessions (the normal case for a running worker), so
`codex_review`'s resolution `worktree_path or cwd or scope` fell through to `scope` =
main repo. (Detached/DB path already carried `worktree_path`, so the bug only bit live
workers — matching "reproduces stably".)

## Fix
- `app/session.py` `to_dict()` — added `"cwd"` + `"worktree_path"` (+2 lines). codex now
  `cd`s into the worker's worktree.
- `app/mcp_stdio.py` `codex_review` — bg-job `timeout_seconds` 300→600, return text
  "5-min"→"10-min" (large-diff timeout, secondary ask).

## Files
- `app/session.py` (+2)
- `app/mcp_stdio.py` (+1/-1, text)

## Tests
- Sanity: verified `to_dict()` now exposes both fields.
- `pytest -k "session or to_dict or mcp or codex"`: 119 passed. 3 failures
  (test_api test_list_empty, 2 test_session async-loop) are **pre-existing** — confirmed
  identical failures on clean base via `git stash` (event-loop fixture pollution in the
  parallel test env, unrelated to this change).

## Breaking
None. `to_dict()` gains two additive keys; all consumers read it as a JSON dict.

## Notes
- Orchestrators (no worktree): `worktree_path=None` → falls to `cwd` (real repo) → correct.
- Applies after Orchestra restart (MCP server + session code reload).
- No bg_jobs change needed — the codex command already does its own `cd {cwd}`.
