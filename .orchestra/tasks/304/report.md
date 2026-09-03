# #304 — explicit reviewer model for `codex_review`

## Result

`codex_review` now accepts an optional `model`. Omitting it deterministically preserves the
historical `gpt-5.6-sol` behavior. Explicit Luna and Sol, their registry aliases, and other
registered non-Spark Codex-runtime models resolve through `app.models`; Claude, Grok, unknown
models, and the separate Spark quota lane fail before any readiness or background-job call.

The resolved canonical model is used by every fresh, resume, and stale-session fallback Codex
command. The same value reaches the quota gate, background-job message/start result, per-round
artifact metadata, `codex_sessions.json`, and `turn_usage.model`. No routing or pricing logic was
added: alias/model metadata remains owned by `app.models`, and Spark classification remains owned
by the quota policy.

The canonical `codex-debate` skill now calls Luna through `codex_review` and documents the
backward-compatible Sol default. It uses registry aliases rather than copying versioned manifest
model IDs into prompt prose.

## Acceptance evidence

- Focused MCP/artifact/prompt regressions:
  `uv run pytest -q tests/test_mcp_stdio.py tests/test_codex_review_artifact.py
  tests/test_default_pipeline.py tests/test_mcp_codex_review.py tests/test_mcp_quota_gate.py
  tests/test_codex_bin_resolution.py tests/test_codex_review_sandbox.py`
  → `263 passed in 15.89s`.
- Registry/routing/prompt/job regressions:
  `uv run pytest -q tests/test_backend_routing.py tests/test_runtime_router.py
  tests/test_runtime_router_spark.py tests/test_check_pipeline_manifest.py
  tests/test_pipeline.py tests/test_prompting.py tests/test_legacy_pipeline_skills.py
  tests/test_bg_jobs.py` → `292 passed, 1 skipped in 26.64s`.
- `uv run python scripts/check_pipeline_manifest.py --check`
  → default manifest agrees with prompt files.
- `uv run python -m compileall -q app/mcp_stdio.py app/codex_review_artifact.py`
  and `git diff --check` → no output.

## Mutation evidence

Starting from the green focused test, the production CLI construction was changed from the
resolved `review_model` back to the Sol default while quota/accounting metadata still accepted
Luna. Marker count was `1` before mutation. The targeted propagation test returned `rc=1` with two
Luna cases failing because the generated command contained zero `-m gpt-5.6-luna` arguments.
After `mv` restore plus `touch`, marker count was `1` and the same command returned
`3 passed, 93 deselected`. This kills the accepted-but-ignored model defect rather than merely
checking metadata.

## Review gate

- Changed consumers: MCP schema/callers, Codex CLI fresh/resume commands, quota preflight,
  background-job result text, artifact/session persistence, usage accounting, and the canonical
  review skill.
- Author: `gpt-5.6-sol` / Codex, from the assigned session metadata.
- AC: explicit Luna/Sol propagation; Sol default; pre-job rejection of invalid/Claude/Grok/Spark;
  actual-model job/artifact/accounting labels; direct Luna skill route; ignored-argument mutation.
- Oracle: the named 263-test focused suite, 292-test related suite, manifest checker, compile check,
  diff check, and the targeted mutation above.
- Route: mandatory Sol technical review because this changes the shared review/control runtime.
  Same-family review is not independent. Targeted Opus cross-family review is unavailable while
  Claude weekly quota remains blocked; do not substitute Luna as independence evidence.

### Review outcome

One targeted Sol round completed with `APPROVED`, zero blocking findings, and zero actionable
suggestions. The reviewer ran
`uv run pytest -q tests/test_mcp_stdio.py tests/test_codex_review_artifact.py
tests/test_default_pipeline.py` → `205 passed in 12.84s`. Its evidence quote,
`codex_cli = f"{q(codex_bin)} -m {q(review_model)}"`, was verified at
`app/mcp_stdio.py:2331`. Artifact: `docs/tasks/304/codex-review-impl.md`.

Independence: same-family Sol review. A live read-only `/api/usage` check showed Claude seven-day
utilization `100.0%`, reset `2026-08-18T07:00:00.037581+00:00`; therefore
`cross-family verdict unavailable`. No Luna/Sol pass is represented as independent evidence.

No deploy, restart, production call, pricing change, or generic routing change was performed.
