# Frozen capsules — #292

All blocks are derived from the DB/task docs named in `protocol.json`. They are
not owners and must not be edited by an agent. The runner pads each B block with
deterministic non-semantic bytes to create P at the same position and byte length.

## t237

```text
DERIVED — DO NOT EDIT
Task: #237
Authority: DB tm_tasks.par_number=237; docs/tasks/237/plan.md; docs/tasks/237/research.md
Source: bc5e639d7346f248578f018a5fce74b42d4ed95d; solution-after-handoff: fecd2402c024c794662b297661e24fbd71d6a52d

Observable requirements:
- T1: Codex receives Orchestra-owned child stdin/stdout FDs; no PIPE ownership fallback.
- T2: every prepared active Codex session has paired inherited descriptors and strict names.
- T3: restart preparation is all-or-none; refusal rolls back every prepared session and leaves no marker.
- T4: the rehearsal is transient/read-only and cannot target production.

Non-goals: Claude/Grok transport; changing the runtime contract; deploying or signaling production.
Exact AC: uv run python -m pytest -q tests/test_seamless_restart.py
```

## t241

```text
DERIVED — DO NOT EDIT
Task: #241
Authority: DB tm_tasks.par_number=241 (canonical task description)
Source: c0185e9d88a2f519a9ecdde81ef05c6b9e396105; solution-after-handoff: 0a328591ec3d6dd8ed306297b3b7cadcdf9de551, e8283644f184fb11bfd1ae6c98048d0c2c931955

Observable requirements:
- notify_user is an MCP tool with mandatory short reason.
- A tool call during the orchestrator turn emits one user tag at turn end; no call emits none.
- The reason is retained and shown with the tag.
- Tagged dashboard messages are visibly highlighted and navigable.
- Worker turns are unaffected; delivery mechanics are unchanged.

Non-goals: tagging workers; tagging status/progress/merge/review noise; changing message delivery.
Exact AC: uv run python -m pytest -q tests/test_tg_bridge.py tests/test_api.py
```

## t248

```text
DERIVED — DO NOT EDIT
Task: #248 T2
Authority: DB tm_tasks.par_number=248; docs/tasks/248/plan.md; docs/tasks/248/research.md
Source: b35795dc5a6e81bd42750cc70ac58087a8cb40f8; solution-after-handoff: 60528bfc15e874da0b0f8bfedf4605d0f467cdf2

Observable requirements:
- Merge preflight rejects missing durable task binding or invalid outcome before Git.
- Unknown, foreign-project, and substituted task refs are rejected with target HEAD unchanged.
- Empty refs bind the durable primary; same-scope refs are linked atomically.
- Candidate refs are recomputed under the repo lock at the exact worker HEAD and emitted refs are rechecked.
- Reserved trailer and commit-point outcomes are explicit; no false success on partial finalization.

Non-goals: changing task ownership policy; merging unknown work; mutating the target on refusal.
Exact AC: uv run python -m pytest -q tests/test_task_tracker_integration.py
```
