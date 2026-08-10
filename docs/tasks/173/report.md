# Report — #173 prompt P0 defects

## Result

Implemented only the three P0 findings accepted from `docs/tasks/172/research.md`. No P1/P2 work,
LLM A/B, performance/latency/token/size benchmark, production action, deploy, restart, or generated
`AGENTS.md` edit was performed.

## P0-1 — reload keeps one current personal-memory block

- Added nullable `sessions.prompt_overlay` and carried it through `AgentSession`, create, hydrate,
  upsert, reload, rename, and manual full-prompt replacement.
- Fresh sessions store custom overlay plus ownership separately from personal memory. Reload builds
  the current role base plus the exact stored overlay, removes all stale memory blocks, and appends
  at most one freshly read `<worker-memory>`.
- `NULL` is the legacy/full-override sentinel; explicit `""` is a separated empty overlay. Matching
  legacy bases are split exactly. An unmatched legacy full prompt is preserved rather than guessed;
  only its old memory blocks are replaced.
- `prompt_overlay` is omitted from session-list payloads together with the already omitted assembled
  `system_prompt`; detail/persistence paths retain it.

Affected runtime: `app/db.py`, `app/manager.py`, `app/prompting.py`, `app/routes/sessions.py`,
`app/session.py`.

## P0-2 — codex_review uses caller project context

- Removed the unconditional `Scale: small team, MVP stage` context.
- Made `context` required in the tool schema and rejected blank/no-`PROJECT CONTEXT` input before
  quota/readiness or job creation.
- Both `review` and `exec` modes now receive the caller's task/project context and the same
  scale-neutral severity rubric. Review-mode stdin carries those instructions into
  `codex exec review`.
- Updated every current code/test/default-pipeline call example found outside historical task and
  changelog material.

Affected runtime/prompt sources: `app/mcp_stdio.py`,
`pipelines/default/prompts/roles/full-cycle.md`,
`pipelines/default/prompts/skills/codex-debate.md`.

## P0-3 — current Codex behavior in guidance

- `CLAUDE.md` now records the current machine-local `project_doc_max_bytes = 131072` while requiring
  an actual config read before future conclusions.
- Project skills are described as native `.codex/skills`, with the bounded generated index only as
  the current unavailable-native-home fallback.
- Codex auto/manual compact is described as native same-thread behavior; Claude's summary/fresh
  reconnect is separate. `compact_worker` no longer promises a universal reset or `>80%` policy.
- `CHANGELOG.md` was written manually from the implementation and measured trigger, not generated
  from this internal report.

## Verification

- Relevant suite:
  `pytest -x -q tests/test_prompting.py tests/test_manager.py tests/test_db.py tests/test_mcp_codex_review.py tests/test_codex_bin_resolution.py tests/test_mcp_quota_gate.py tests/test_session.py tests/test_default_pipeline.py tests/test_p1_union.py tests/test_api.py`
  → **702 passed in 142.84s** (`/tmp/pytest-173-relevant-final.log`).
- Final focused regression set after the last live-prompt synchronization fix → **61 passed in
  10.33s** (`/tmp/pytest-173-targeted-final.log`).
- `python -m py_compile` passed for all changed Python runtime files; `git diff --check` passed.
- Independent reversible mutations each made its guarding regression red, then the file was restored
  and marker-checked: single-match memory replacement, ignoring stored overlay on changed base,
  restoring the fixed MVP sentence, and claiming Codex compact resets the thread.
- External review: **unavailable**. The one allowed `codex_review` attempt returned
  `weekly_quota_upgrade_required` because readiness lacks `worker-weekly-v1`; no bypass/retry was
  attempted. Strict review: `docs/tasks/173/self-review.md`.

## Compatibility and risk

- DB change is additive and nullable. Existing rows remain readable.
- Intentional tool-contract change: `codex_review.context` is now required and must contain caller
  `PROJECT CONTEXT`; legacy context-free callers fail loud instead of receiving invented scale.
- Unmatched legacy full prompts retain their old base until explicitly normalized, because their
  custom/base boundary is not recoverable. This preserves authority text and removes stale memory;
  the bounded tradeoff is detailed in `self-review.md`.
- Safety, authorization, role lifecycle, model routing, production state, and deployment paths were
  not weakened or changed.
