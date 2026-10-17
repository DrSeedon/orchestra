# item-35

Commit under review (in /home/kesha/orchestra, read-only): `6b2249c59e177e55507e5a20b0214f3ee1fd944d`
Subject / date:
#214: #214: эффорт по модели — карта модель→ступень в манифесте
2026-08-12

The diff reviewed is `git -C /home/kesha/orchestra show 6b2249c59e177e55507e5a20b0214f3ee1fd944d -- . ':(exclude).orchestra/tasks' ':(exclude).orchestra/kb'`.

## Reviewer output (verbatim)

## Summary

Reviewed the complete diff from `d6a4f4d15137d0573b194b8954990d49fff87c2d` to `817456ce220f32319fd5dbcb72d1601420a1848c`. The model → effort map, spawn-time resolution, manifest cache invalidation, and turn-boundary update are consistent with the intended behavior. I found one configuration issue worth addressing.

## Findings (blocking/suggestion/question)

### Suggestion

- [app/pipeline.py](app/pipeline.py:266) — Effort values are validated against `CODEX_REASONING_EFFORTS` for every runtime, although the same map can configure Claude sessions too. The set includes `minimal`; Claude’s backend passes that value directly to `ClaudeAgentOptions.effort` ([app/backend_claude.py](app/backend_claude.py:208)), except for the explicit `xhigh` → `high` conversion. A Claude-specific entry such as `{claude: minimal}` can therefore pass manifest validation but fail when constructing or running the Claude backend. Validate levels against the selected runtime/model’s supported set, or reject levels unsupported by any runtime that a key can cover.

## Verdict

NEEDS WORK — the shared validation can accept an effort value that the configured backend may not support.
