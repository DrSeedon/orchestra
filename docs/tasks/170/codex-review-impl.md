# #170 — implementation review

## External verdict

**External verdict unavailable.** The single permitted `codex_review` attempt
returned before creating a review job:

```text
weekly_quota_unknown: New Codex worker turn blocked: weekly quota status for
gpt-5.6-sol is unavailable or stale (missing or legacy readiness policy).
Stop/model change remain available.
```

The readiness gate was not bypassed, no direct `codex exec` or Claude review
was used, and no second quota source was consulted.

## Strict Sol self-review

Scope reviewed: the complete uncommitted production diff in
`app/backend_codex.py`, `app/mcp_stdio.py`, `app/prompting.py`,
`app/quota_gate.py`, `app/routes/system.py`, `app/runtime_registry.py`,
`app/session.py`, and `app/session_turns.py`, plus the corresponding tests and
measurement artifacts. The review checked the approved T1–T5 invariants,
version-skew fail-open paths, timestamp boundaries, runtime cache selection,
managed-worker capabilities, tracked-file mutation, reconnect duplication and
false-green tests.

### Resolved finding

`blocker (fixed):` `_quota_refusal_from_readiness` initially selected
`decision_state` whenever the key existed, including a malformed v1-shaped
response with no `wire_version`. An inconsistent payload could therefore use
`decision_state=available` to override a blocking top-level state. The parser
now accepts canonical state only with exact integer `wire_version=2`, requires
the canonical field for v2, rejects `bool`, float and unsupported versions,
and retains the current-v1 path only when the canonical field is absent.
Four adversarial cases were added; the T1 subset is `68 passed in 5.89s`.

### Unresolved findings

No CRITICAL, HIGH or blocking finding remains.

- `note:` T1 preserves one central quota decision. The compatibility
  `reset_at` is used only by legacy clients; `decision_reset_at`,
  `observed_at` and `valid_until` remain canonical and are never synthesized.
- `note:` T2 reads one runtime-specific cache snapshot once per turn-end for
  both DB and display. It does not call admission or change a quota decision.
- `note:` T3 disables native Codex multi-agent in every managed backend while
  leaving Orchestra `spawn_worker` and role delegation configuration intact.
- `note:` T4 never writes the tracked `.codex` file or `AGENTS.md`; the skill
  fallback is bounded to 16,000 characters and visibly marks truncation. The
  project-doc instruction is ephemeral and rebuilt per connect.
- `note:` T5 has no comparable Sol arms, so the pre-registered gate correctly
  returns `NO_CHANGE`; no latency optimization was smuggled into runtime or
  prompts.

## Verification considered by the review

- 14/14 independent production mutations were detected by their behavioral
  tests and restored in-command.
- Combined targeted suite before the final guard: `564 passed in 70.75s`.
- T1 after the final guard: `68 passed in 5.89s`.
- Final required full-suite command exited `0`; `uv.lock` was unchanged and
  `git diff --check` was clean. Pytest emitted five post-suite
  `BaseSubprocessTransport.__del__` warnings after success; they are existing
  event-loop cleanup noise, not a failed test or a runtime change in #170.

Self-review verdict: **PASS; external verdict unavailable**.
