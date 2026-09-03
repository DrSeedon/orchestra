# #314 policy correction — Luna Fast default

The orchestrator's 2026-08-17 policy correction supersedes the earlier #314 wording that
disabled a generic Fast lane in `THROTTLE`/`RESERVE`/`FAIL_SAFE`. #291 evidence and all
`docs/tasks/291/oracles/` remain immutable.

The server-owned rule is now:

- `gpt-5.6-luna` is the Luna Fast default for workers, normal execution, spawn/resume/fallback
  paths, and omitted-model `codex_review`.
- Luna Fast is not held merely for an unsafe quota zone.
- Fresh known Codex-primary pressure suppresses Sol and routes new Sol worker/review operations
  to Luna Fast. Missing, stale, foreign-provider, or reason-bearing telemetry falls back to the
  existing static path.
- Orchestrator sessions remain exempt; mid-turn and submitted operations are unchanged.

Evidence is recorded after Sol review round 3 in
`docs/tasks/314/codex-review-impl.md`. Round 3's `REJECT` is preserved; the orchestrator
authorized mechanical closure instead of a fourth Sol round. The default-model mutation and
provider-scope mutation were both caught, and the scoped #314/#291 suites are green.
