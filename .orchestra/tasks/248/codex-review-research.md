## Summary

The central conclusion—Task Manager is not an authoritative lifecycle projection—is plausible and supported by several consistent measurements. However, some headline counts and the 28-task audit are stated more strongly than the linked evidence permits.

## Findings

[suggestion] `docs/tasks/248/research.md:79-90` — The reverse reconciliation count of 81 is potentially overstated. The method recognizes only the first `^#N:` in a commit subject, so a tracker task mentioned as a secondary number in `#A, #B:` is classified as having no matching main commit. The limitation at lines 207–208 correctly calls 132 a lower bound, but does not identify 81 as an upper bound under the same selector. Either scan all task references for the reverse relation or qualify the 81 accordingly.

[suggestion] `docs/tasks/248/research.md:70-71` — “the tracker is not the place orchestrators consult to recover current state” is an inference, not established by the 6.2% denominator. The measurement covers only four explicit task MCP tools. It excludes dashboard/API reads, state returned by create/update calls, and state supplied through prompts. Retain the 6.2% result but label the behavioral conclusion as suggestive rather than confirmed.

[suggestion] `docs/tasks/248/research.md:144-179` — The total “20 already done” is not supported uniformly by E4. Several raw commands establish only symbol/file presence, not satisfaction of the task:

- Orchestra #2 shows IndexedDB and sync paths but no behavioral result demonstrating that worker switching no longer reloads history.
- Seedon #3 lists four files but does not expose the claimed completed calculations/actions.
- Seedon #112 is a broad grep dominated by generic `typing` matches and does not demonstrate authenticated deployment or full-dialog behavior.

The report itself says, “A file/symbol present in main proves delivery,” which is weaker than “already done.” Split these into verified-complete versus implementation/artifact-present, or provide task-specific completion evidence.

[question] `docs/tasks/248/research.md:157-163` — Why is Orchestra #219 classified as “duplicate / superseded” instead of “actual” or “partially superseded”? The row itself says #219’s T3/notional-corpus work remains, while only the fan/barrier outcome shipped under #231. Superseding one outcome does not establish that the entire tracked task should cease being active unless the original task scope was explicitly narrowed or cancelled.

[suggestion] `docs/tasks/248/research.md:195-198` — H3 is refuted, but the supporting sentence mixes incompatible scopes: “removing the five active ghost tasks” is followed by `17/28`, which already excludes all ghost projects by construction. State instead that the canonical-only measurements independently refute H3; no subtraction from the 28-task denominator occurs.

[question] `docs/tasks/248/research.md:40-44,239-257` — The linked evidence does not include the snapshot or the outputs of the advertised integrity/hash validations. It provides generated tables and query methods, but the load-bearing SQLite counts cannot be independently recomputed from the review scope. Can the snapshot validation output—or a compact set of independent SQL aggregate outputs—be included under `evidence/`?

## Verdict

CHANGES REQUESTED. No crash, corruption, or security blocker was found, but the reverse-reconciliation denominator and the “20 already done” total need qualification or stronger evidence before the Phase 1 conclusions are treated as confirmed.

## Round (2026-08-13T07:11:01Z)

## Summary

All six round-1 findings are fixed. The revised reconciliation counts are internally consistent, and the task verdicts sum correctly: 20 already done + 8 actual = 28.

## Findings

- **FIXED — reverse reconciliation:** “For mapped projects, 60 tracker rows have no reference anywhere in the recognized leading task header; 81 is only the upper bound produced by looking at the first number.” The table consistently reports 132 strict-primary forward misses, 137 any-header misses, 81 primary-only reverse misses, and 60 any-header reverse misses.

- **FIXED — behavioral inference:** “The 6.2% list/get share suggests that explicit task-tool retrieval is not routine, but does not establish every consultation path.” The unmeasured dashboard/API, returned-state, and prompt-injection paths are named.

- **FIXED — completion evidence:** “The three challenged ‘done’ rows now use task-specific reports/assertions [E5].” E5 provides behavioral evidence for Orchestra #2, task-specific calculations for Seedon #3, and dialog/typing assertions for Seedon #112.

- **FIXED — #219 classification:** “Orchestra #219 | actual (partially superseded).” The remaining T3 and corpus-divisibility work are explicitly identified.

- **FIXED — canonical denominator:** “No ghost task was subtracted from the 28-task denominator.” The canonical-only `17/28` measurement is now correctly separated from ghost projects.

- **FIXED — reproducibility evidence:** “SQLite validation and compact aggregates are in `snapshot-aggregates.txt`; all Git counts are tied to `git-refs.txt`.” The evidence records `sqlite3.Connection.backup()`, hash, size, integrity result, aggregate queries, and five pinned refs.

No new blocking, suggestion, or question findings.

## Verdict

**APPROVED.** The revised Phase 1 conclusions are supported at the stated confidence levels and are internally consistent.
