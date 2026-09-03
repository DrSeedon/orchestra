<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-sol"} -->

## Summary

The plan closes the three prior Opus blocker groups at their original seams: quota ownership moved into `quota_gate.py`, fetched/candidate provenance and catalog controls were added, and the MCP → runner → real finalizer path is exercised.

However, five blocking oracle gaps remain. Each permits a forbidden implementation to pass the frozen suite. No files were modified.

Direct-reading evidence from the plan:

> marker не удаляется после ошибки. Две параллельные команды могут пересечь ровно один atomic claim.

## Findings

1. blocking: `docs/tasks/261/plan.md:13`, `docs/tasks/261/plan.md:205` — the plan permits publishing `author identity`, while the caller’s contract permits only canonical URL, snowflake timestamp, and independently obtained oEmbed fragment. `tests/test_grok_x_artifact.py:94-106` supplies `author_name` and `author_url` but never asserts their absence, so an artifact leaking both passes. Remove author identity from the output contract and add negative assertions for both fields.

2. blocking: `tests/test_grok_x_artifact.py:199-227` — fetched/candidate ID equality is covered, but canonical oEmbed ID equality is not. An implementation can verify candidate A was fetched, accept an oEmbed response whose canonical URL points to B, and publish B while passing every test. Add an `oembed_mismatched_id` case and require failure without modifying an existing artifact.

3. blocking: `tests/test_grok_x_tool.py:449-475` — T4 tests only `decision_state`; they do not reject an `available` envelope with the wrong policy, wire version, provider, model, expired `valid_until`, future `observed_at`, or malformed freshness. Thus an implementation that authorizes on `decision_state == "available"` passes despite the plan’s “only exact policy + available” rule at `plan.md:149-150`. Add negative available-envelope cases and assert no `POST /api/bg/jobs`.

4. blocking: `tests/test_grok_x_tool.py:273-296`, `tests/test_grok_x_tool.py:397-418` — the persisted command is executed with `shell=True` by `BgJobManager`, but all test paths are shell-safe. Naive interpolation of `worktree_path`, output, run directory, or usage attribution therefore passes, enabling command injection from a path containing spaces, quotes, semicolons, or command substitution. Exercise a metacharacter-bearing path and verify the emitted command round-trips as exact argv without executing injected syntax.

5. blocking: `docs/tasks/261/plan.md:89`, `tests/test_grok_x_tool.py:298-307` — `question.txt` is required to be mode `0600`, but the oracle only reads its contents. A straightforward `Path.write_text()` creates it according to the process umask—commonly `0644`—and passes, exposing potentially sensitive queries in persisted platform state. Assert `stat().st_mode & 0o777 == 0o600`.

6. blocking: `tests/test_grok_x_tool.py:310-387` — catalog matching can be implemented as two substring checks and pass. That accepts a model entry such as `grok-4.50` as pinned `grok-4.5`, and potentially accepts the logged-in phrase embedded in unrelated diagnostic text. Add negative controls for a prefix-collision model and an explicitly logged-out/conflicting banner; require exact parsed catalog entries before job creation.

7. suggestion: `docs/tasks/261/plan.md:146-148`, `tests/test_grok_x_tool.py:310-387` — the required 15-second catalog timeout is not asserted. An implementation with no timeout passes and can hang indefinitely before admission. Capture the subprocess timeout mechanism and add a timeout-path test that produces a fail-closed `ApiToolError` with no job.

## Verdict

**NEEDS WORK.**

The prior Opus blockers are materially addressed, but the frozen acceptance suite still allows contract-violating artifact disclosure, provenance substitution, stale/incompatible quota authorization, shell injection, and insecure prompt-file permissions. Re-freeze the RED oracles before production implementation.

---

Follow-up attempt 2 / review round 3 (Sol resume, 2026-08-17): completed; final verdict NEEDS WORK.

## Round (2026-08-17T08:16:29Z)

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-sol"} -->

## Summary

All seven prior findings are fixed, and first-round dissent remains preserved in `plan.md:267-277`. Two new blocking oracle gaps remain.

Direct-reading evidence:

> Runtime `total_cost_usd_ticks` сохраняется как telemetry, но не называется billing truth.

## Findings

- FIXED — Author leakage: `plan.md:75-76` limits output to URL, timestamp, and fragment; `test_grok_x_artifact.py:149-150` excludes both author sentinels.

- FIXED — Canonical provenance: `plan.md:124-125` requires equality of all three IDs; `test_grok_x_artifact.py:208-240` rejects `oembed_mismatched_id` while preserving the prior artifact.

- FIXED — Readiness identity/freshness: `test_grok_x_tool.py:576-619` rejects wrong policy, wire version, provider, model, expired, future, and malformed envelopes before job creation.

- FIXED — Shell injection: `test_grok_x_tool.py:512-544` uses metacharacter-bearing paths and verifies exact argv round-tripping without the side effect.

- FIXED — Prompt permissions: `test_grok_x_tool.py:306-308` asserts mode `0600`.

- FIXED — Catalog parsing: `test_grok_x_tool.py:319-395` rejects `grok-4.50`, diagnostic-banner text, conflicting logged-out state, nonzero exit, and absent exact model.

- FIXED — Catalog timeout: `test_grok_x_tool.py:398-433` asserts 15 seconds, `grok_catalog_timeout`, and no background job.

- blocking: `plan.md:44-50`, `tests/test_grok_x_tool.py:576-606` — readiness declares `threshold = 100`, but the incompatible-envelope oracle never mutates `threshold` or `weekly_utilization`. A consumer that validates identity/freshness but accepts an `available` envelope produced under threshold 101 can authorize at 100% and pass the suite. Add a mismatched-threshold available case that refuses before `POST /api/bg/jobs`.

- blocking: `plan.md:13`, `plan.md:124-125`, `tests/test_grok_x_artifact.py:208-240` — the oracle proves canonical ID equality but not that candidate and canonical URLs are actually X URLs. An ID-only validator can accept `https://attacker.invalid/status/<matching-id>` from either source and still pass. Add same-ID wrong-host/scheme cases for both the model candidate and oEmbed canonical URL; both must preserve the existing artifact.

## Verdict

NEEDS WORK
