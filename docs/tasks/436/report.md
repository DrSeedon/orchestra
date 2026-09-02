# #436 — итог реализации

## Result

`review_receipts` now records review provenance at start and terminal execution, while review text remains only in the artifact. `record_review_outcome(receipt_id, outcome, outcome_evidence_ref)` is the sole author-outcome path selected by the user.

- `accepted`, `disputed`, `partial` are the only outcomes; `disputed` requires a non-empty evidence reference.
- Duplicate identical outcome submissions return the same receipt; a conflicting second outcome fails.
- Model/runtime/session/scope/task/artifact/mode/round/job/usage ids are recorded without using the readiness model or historical default.
- Round allocation uses `BEGIN IMMEDIATE` plus a unique `(artifact_path, round)` index.
- Terminal receipt records rc, artifact bytes/hash, current-round verdict, JSONL agent-message presence and recovery source. Empty round output is recovered only from a live terminal `item.type="agent_message"`; no new Codex call is made.
- Per-run JSONL, prompt, rc and `.round` paths include the receipt id. TERM/INT records an interrupted receipt before exit.
- Historical migration supports `--dry-run` and guarded `--apply --confirm-live`; apply validates SHA-256/size, snapshots with `sqlite3.Connection.backup()` before `init_db()`, inserts in one transaction, and rejects conflicting replay payloads.

## Frozen oracle and review evidence

- Frozen red oracle commit: `ba6db551`; five files, five distinct missing-behavior messages.
- Luna implementation review: `docs/tasks/436/review-implementation-luna.md`; substantive findings were checked and fixed. The external job once returned a blind status despite a complete agent message; the message itself is preserved as evidence.
- Sol irreversible-seam review: `docs/tasks/436/codex-review-sol.md`; one fresh targeted pass, four blockers. The pass verdict was REJECT before the listed fixes; no second Sol round was run after fixes due the three-round ceiling.

## Checks

- Frozen five plus existing review/db/bg suites: `174 passed`.
- Affected-file command, identical on main and branch: `169 passed` on each (`RC=0`). `--collect-only` sets: main 169, branch 169, `main_only=0`, `branch_only=0`.
- T5 mutation — MCP wiring: production marker `1 → 0 → 1`, mutated test `RC=1` (`Unknown tool`), green repeat `1 passed`.
- T5 mutation — DB primitive: marker `1 → 0 → 1`, mutated test `RC=1` (`ImportError`), green repeat `1 passed`.
- Finalizer concurrency safety: true two-thread barrier test ran three times, each `2 passed`; with the publication-lock marker mutated `1 → 0 → 1`, the parallel test fails `RC=1` on `review artifact changed during finalization`.
- Backup alias safety: symlink alias is rejected before opening the destination; mutation of both realpath/inode guards gives `RC=1` (wrong `backup path already exists` message), restored marker counts are `1/1`, and the green repeat passes.
- Temporary migration rehearsal: dry-run `RC=0`, first apply `RC=0`, repeated apply with the existing backup path refuses with `RC=2`, durable backup exists, one receipt row remains, changed artifact refuses apply with `RC=2`.
- Full unsharded suite was not used as an oracle: it reproducibly reaches about 80% and exits `137` from memory pressure without terminal summary. The same failure occurred in #418; no new-failure claim is based on that run.

## Live migration

No `--apply` was run against `data/orchestra.db`. A real 437-artifact dry-run was exercised against a generated conservative manifest (`RC=0`, 437 artifacts): `direct=86`, `derived=0`, `unknown=351`. The 351 unknown include all 276 historical-default model labels; the migration intentionally does not guess them as derived. A final audit manifest must carry any proven `derived` rows explicitly.

Sol Round 3 — NEEDS WORK, 3 блокера FIXED, 2 новых blocking закрыты ПОСЛЕ потолка раундов, вердикта ревьюера на эти две правки нет.
