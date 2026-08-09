# T4 — skill/worktree guard before/after and mutations

## Behavioral before

A git fixture with a tracked binary `.codex` file preserved the file but left
the session without any fallback signal. The new end-to-end assertion failed
with:

```text
AttributeError: 'AgentSession' object has no attribute '_codex_skill_index_fallback'
1 failed in 4.47s
```

Phase 1 independently measured the second baseline: `AGENTS.md=155284 bytes`
with configured `project_doc_max_bytes=65536` produced no pre-connect
diagnostic or tail-read fallback.

## Behavioral after

- tracked `.codex` remains byte-for-byte identical and `git status --short` is
  empty;
- one bounded canonical prompt index is enabled only when native skill home is
  unavailable; repeated refresh produces one warning/index;
- ASCII `actual==budget` is not flagged;
- multibyte bytes (not characters) identify the first partially omitted line;
- malformed config reports unknown budget without claiming truncation;
- oversized diagnostic/preflight completes before fake CLI build/connect.

Focused guard subset: `8 passed in 4.60s`. Wider prompting/manager/registry
suite: `215 passed in 44.19s`. Async/reconnect nodes repeated:

```text
3 passed in 4.07s
3 passed in 4.11s
3 passed in 4.23s
```

## Independent mutations

| ID | Mutation | Behavioral red evidence |
|---|---|---|
| M1 | home-file report falsely says no conflict | tracked fallback: `1 failed in 4.14s` |
| M2 | ignore session fallback flag in Codex factory | prompt index assertion: `1 failed in 4.46s` |
| M3 | count Unicode characters instead of bytes | multibyte boundary: `1 failed in 3.51s` |
| M4 | suppress oversized-doc instruction | prompt warning integration: `1 failed in 4.17s` |

Each mutation was restored in-command; each production marker count returned
to `1`. No test writes outside its temporary git fixture.
