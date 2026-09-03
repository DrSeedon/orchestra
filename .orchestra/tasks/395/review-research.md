<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

## Summary

Phase 1 identifies the likely hot path, but several load-bearing conclusions are not yet proven. The main blockers are snapshot consistency across canonical files, cross-store idempotency, and an incomplete request-key contract.

Review route: none — Codex reviewer unavailable. No files edited.

## Findings

1. **blocking:** `docs/tasks/395/research.md:198-221`, `app/ia/task_store.py:320-333,411-493,622-653` — the proposed snapshot guarantee is incompatible with the current storage model. `task_list`/`task_get` read canonical JSON state, while the projection receipt is derived from SQLite rows; writing canonical state updates files one by one and can expose mixed heads to a lock-free reader. The existing `projection_head` implementation also rejects mixed row heads, so record-level updates cannot preserve the current invariant without a defined global receipt/schema migration. Specify the atomic read source and cross-file consistency protocol before treating H3 as likely.

2. **blocking:** `docs/tasks/395/research.md:214-220`, `app/tm.py:1549-1575,1584-1606` — the proposed idempotency mapping cannot be atomic across legacy SQLite, canonical Git state, and shadow projection. In shadow mode legacy creation commits before canonical creation; a timeout or failure between them can leave a legacy task that a retry recreates. Persisting a key in each store does not define recovery or ownership across that boundary. Add an explicit crash-order/reconciliation protocol and same-key concurrency behavior.

3. **blocking:** `docs/tasks/395/research.md:214-220`, `app/mcp_stdio.py:504-529,2436-2460`, `app/routes/tm.py:14-25,82-137` — the reusable request-key contract is incomplete at every boundary. MCP currently generates a fresh per-call `request_id`; `task_create` accepts no key, the route model accepts neither a key field nor the `Idempotency-Key` header, and the error response offers no outcome lookup or defined in-progress response. Specify key namespace, fingerprint fields/canonicalization, retention, same-key concurrent calls, response replay, and behavior when the first attempt is still running.

4. **suggestion:** `docs/tasks/395/research.md:23-47,69-84`, `docs/tasks/395/benchmark_tm.py:130-214` — the benchmark demonstrates a slow create and a contended list, but does not prove that both full rebuilds account for the measured latency or quantify the lock contribution. It records no `replace_current` call count/timing and does not run a control with the writer lock or either rebuild isolated. Narrow H1/H2 to “the current path correlates with the stall” or add instrumentation/controls before claiming causal attribution to both rebuilds plus the shared lock.

5. **suggestion:** `docs/tasks/395/benchmark_tm.py:190-214`, `docs/tasks/395/research.md:111-125` — `task_count_delta_after_deadline` is measured after `api_list_tasks` finishes, not at 30 seconds. Therefore `3/3 gave +1 after the deadline` is directionally plausible but not directly measured at the deadline boundary. Record a bounded observation at exactly the deadline or rename the metric to “delta after contended list completion.”

6. **suggestion:** `docs/tasks/395/analyze_timeout_outcomes.py:161-179`, `docs/tasks/395/timeout-outcomes-20260826.raw.json:...` — the exploratory 17/17 attribution is vulnerable to title collisions: rows are grouped only by resolved project plus exact title and assigned to the latest preceding call. The artifact itself contains a duplicated project/title hash, and the analyzer does not compare description, price, status, scope, or transport key. Keeping it separate from 16/17 is correct, but 17/17 should be labelled ambiguous/title-based attribution rather than task-level confirmation.

7. **question:** `docs/tasks/395/research.md:177-196,293-307` — the WAL counter-evidence does not establish that the installed SQLite binary lacks the relevant backport merely because the Debian changelog has no marker. Is the conclusion based on an explicit binary/package patch check, or only absence of a changelog string? Keep the conservative “WAL is not required” recommendation, but downgrade the stated version-risk confidence unless the backport status is directly evidenced.

8. **suggestion:** `docs/tasks/395/benchmark_tm.py:65-98`, `docs/tasks/395/research.md:87-105` — the fixture verifies heads before and after freezing, but the legacy database, JSON state, and two SQLite projections are captured through separate operations rather than one cross-store snapshot. A mutation could theoretically occur between captures and return the system to matching heads. Record a shared generation/watermark captured inside each source transaction, or explicitly state this limitation.

## Verdict

Needs work. The root-cause direction is credible, and the preregistered/exploratory split is handled responsibly, but Phase 1 does not yet establish a safe design boundary for lock-free snapshots or reusable idempotent creation. Exact line read: “A projection failure may not roll the canonical mutation back silently or claim equal heads.”

## Author disposition after Round 1

- Evidence check: the quoted sentence exists verbatim in the reviewed `research.md`; Round 1 is a
  completed Luna review. The generated Summary line `Review route: none — Codex reviewer
  unavailable` conflicts with the actual `gpt-5.6-luna` metadata/output and is not used as the
  route verdict.
- Finding 1 — ACK: research now names `task-current.db` as the sole healthy request-time candidate
  source, defines meta migration validation, old/new transaction overlay, shadow legacy fallback,
  and canonical fail-fast behavior; canonical JSON is explicitly excluded from lock-free reads.
- Finding 2 — ACK: research now defines a durable coordinator state machine and owner-specific
  crash recovery for generation 2/4 and generation 3 instead of claiming cross-store atomicity.
- Finding 3 — ACK: research now defines namespace, normalized fingerprint, retention, concurrent
  state, response replay, mismatch/in-progress outcomes, HTTP lookup and MCP retry propagation.
- Finding 4 — ACK: the harness now times/counts both rebuild methods. Repeated 3-run evidence finds
  one current rebuild at 13.239–16.098 s and one task rebuild at 0.095–0.241 s per create; causal
  language was narrowed to the serialized path and measured component.
- Finding 5 — ACK: the ambiguous field was renamed `task_count_delta_after_create`; a 30-second
  Timer now records direct legacy visibility only when a run reaches the deadline. The final
  lower-load series did not, and research says so.
- Finding 6 — ACK: 17/17 is labelled exploratory, title/time-based and ambiguous rather than task-
  level confirmation; preregistered 16/17 remains primary.
- Finding 7 — ACK: installed version remains confirmed, binary backport status is downgraded to
  uncertain, and the conclusion is only that new WAL is not a prerequisite.
- Finding 8 — ACK: research explicitly states sequential cross-store capture is a performance
  corpus, not crash-consistency evidence.

- Attempt 2: completed — evidence-backed Luna follow-up after material research/harness changes;
  Round 2 verdict recorded below.

## Round (2026-08-26T08:06:10Z)

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

## Re-review status

Round 2/final prose round. `git diff` checked; no files edited. Codex reviewer unavailable, so this is an evidence-backed self-review.

1. Finding 1 — **NONBLOCKING RESIDUAL**: rebuild calls and durations are now measured. The remaining limitation is that lock contribution is still not independently isolated.

2. Finding 2 — **FIXED**: `task-current.db` is now the sole healthy candidate read source, and sequential cross-store fixture limits are explicit.

3. Finding 3 — **FIXED**: namespace, fingerprint, retention, concurrency, replay, lookup, MCP propagation, and generation-specific recovery are specified.

4. Finding 4 — **FIXED**: both rebuilds are counted/timed, and causal language is narrowed to the measured serialized path.

5. Finding 5 — **NONBLOCKING RESIDUAL**: the metric was renamed and the Timer added, but the Timer observation is not guaranteed to occur at exactly 30 seconds.

6. Finding 6 — **FIXED**: exploratory 17/17 is explicitly ambiguous title/time attribution and remains separate from preregistered 16/17.

7. Finding 7 — **FIXED**: WAL backport status is explicitly uncertain; the document only avoids making new WAL a prerequisite.

8. Finding 8 — **FIXED**: sequential fixture capture is explicitly limited to performance evidence, not crash-consistency evidence.

## New findings

- **suggestion:** `docs/tasks/395/benchmark_tm.py:204-216` — `observe_deadline()` opens a rollback-journal SQLite reader while `task_create` may still hold `BEGIN IMMEDIATE`. That reader can block until the writer commits, so the recorded `future.done()` and row count may describe post-deadline state rather than the 30-second instant. Use a nonblocking read/short timeout and record `SQLITE_BUSY` as an explicit observation outcome.

## Verdict

APPROVED for Phase-1 research, with the Timer limitation documented before relying on deadline visibility measurements. Exact current-artifact evidence: “A CAS mismatch or SQL error rolls back that projection transaction, leaves its old head, and persists blocking debt with expected/observed heads.”

## Post-verdict nonblocking resolution

- Timer suggestion accepted without a third prose round (round ceiling reached): callback now
  records elapsed time and `future.done()` before I/O, opens SQLite with `timeout=0`, and records
  `OperationalError/SQLITE_BUSY` explicitly instead of waiting. `research.md` states that the final
  low-load series produced no deadline observation and makes no deadline-visibility claim from it.

## Post-verdict current-main measurement addendum (2026-08-27)

The orchestrator requested a fresh current-`main` and startup baseline after the two prose rounds
above had reached the `codex-debate` ceiling. No third reviewer round was run. The addendum was
mechanically checked against the raw JSON and journal artifacts:

- preserved receipts, three clones: startup/create/concurrent-list medians
  `8.616283066105098 / 9.523592520970851 / 9.355244785081595`, zero full replacements;
- cleared receipts plus cloned-file `POSIX_FADV_DONTNEED`: startup/create/list
  `213.69075538101606 / 108.21595255890861 / 107.95302356104366`; at 30 seconds create was
  incomplete and one legacy task row existed; zero full replacements;
- production journal elapsed: `179.711295 / 299.017950 / 22.424932` seconds.

These measurements change #405's performance status from unmeasured to partial/incomplete. They
do not supersede the reviewed receipt, degraded-state, snapshot-read, or request-key requirements.
