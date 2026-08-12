## Summary

The core qualitative conclusions are supported:

- `can_use_tool` is a permission-prompt fallback, not mandatory interposition.
- Configured Claude `PreToolUse` ran before execution, overrode `Bash(*)`, exposed an error, populated `permission_denials`, and prevented the marker side effect.
- Exact built-in/MCP denial removes the named tool while leaving sibling tools available; this is catalog enforcement, not capability isolation.
- The hook timings support an observed command-hook interval of roughly 55–60 ms p50 and 99–112 ms p95, but not a measured end-to-end latency increase.

Evidence-of-review quote from the artifact: “Формулировка `run_in_background — BLOCKED` сейчас фактически ложна.”

## Findings

blocking: [enforcement-matrix.md:3](/home/kesha/orchestra/worktrees/home-kesha-orchestra/audit-enforcement/docs/tasks/228/enforcement-matrix.md:3) — The claimed unit is “one independently verifiable policy outcome,” but the rows do not apply that unit consistently, so 48 and therefore 15/48 are not reproducible. N5 combines five separately deniable tool names; P8 combines argv secrecy, artifact egress, and protected paths; P9 combines polling, tmpfs use, and resource limits; A3 explicitly combines “dozens” of checks; A13 combines several unrelated skill policies. Conversely, closely related lifecycle and authorization concerns are split across multiple P/R rows. No reviewed artifact contains the 420-line source ledger or a deterministic candidate→canonical-row mapping. This invalidates the load-bearing quantitative claim that hooks cover exactly 15/48 or 31.25%; retain the qualitative “minority” conclusion only after publishing a complete mapping and applying one stable split/merge rule.

suggestion: [findings.md:13](/home/kesha/orchestra/worktrees/home-kesha-orchestra/audit-enforcement/docs/tasks/228/probes/inventory/findings.md:13) — The inventory’s executive result still classifies Claude’s “background flag” among hard runtime guards, while its own later evidence and the final research show that `Bash(run_in_background=true)` executed with zero callback invocations. Even though `research.md` acknowledges that this earlier conclusion was overturned, leaving the contradiction in an executive summary makes the evidence package unsafe to cite independently. Mark the background flag as disproven/stale there.

suggestion: [hook-overhead.raw.txt:19](/home/kesha/orchestra/worktrees/home-kesha-orchestra/audit-enforcement/docs/tasks/228/probes/hooks/hook-overhead.raw.txt:19) — Calling the measured command-hook interval an “upper bound” for an in-process/equivalent guard is unsupported: an alternative implementation can be slower. The raw data establish only the observed duration of this exact fresh-Python-process hook. `research.md` is better calibrated (“может быть дешевле; это гипотеза”), so the raw interpretation should use the same wording. The p50/p95 values are valid descriptive statistics for these 48 calls, not population latency estimates or isolated end-to-end overhead.

## Verdict

**Needs work.** The enforcement-seam and loudness conclusions are evidence-backed, and no missing higher-impact restriction is apparent within the permitted scope. The quantitative 15/48 headline is not auditable under the stated counting unit and must be repaired or downgraded before Phase 1 research is accepted.

## Round (2026-08-12T11:51:12Z)

## Re-review status

- FIXED — exact 15/48 percentage claim removed; bundles are explicitly non-statistical and unequal in granularity.
- FIXED — inventory now marks background payload enforcement as refuted while preserving exact-name enforcement.
- FIXED — hook timing is limited to the measured command-hook configuration; no unsupported upper-bound claim remains.

Evidence quote: “An in-process/equivalent guard may be faster or slower; neither direction was measured.”

Note: `git diff -- <reviewed artifacts>` returned empty, so the review used their current contents rather than an uncommitted diff.

## New findings

None.

## Verdict

APPROVED — prior blocking and suggestions are resolved; no new load-bearing defect found.
